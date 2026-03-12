const statusEl = document.getElementById("status");
const coordValueEl = document.getElementById("coord-value");
const wayValueEl = document.getElementById("way-value");
const streetValueEl = document.getElementById("street-value");
const bundleValueEl = document.getElementById("bundle-value");

const dbURLInput = document.getElementById("db-url-input");
const dbLoadBtn = document.getElementById("db-load-btn");
const dbFileInput = document.getElementById("db-file-input");
const logFileInput = document.getElementById("log-file-input");
const wayInput = document.getElementById("way-id-input");
const locateBtn = document.getElementById("locate-btn");
const identifyBtn = document.getElementById("identify-btn");
const wayBtn = document.getElementById("way-btn");
const logSummaryEl = document.getElementById("log-summary");
const logOverviewEl = document.getElementById("log-overview");
const logBreakdownsEl = document.getElementById("log-breakdowns");
const logListEl = document.getElementById("log-list");
const traceMetaEl = document.getElementById("trace-meta");
const traceMetricsEl = document.getElementById("trace-metrics");
const traceDebugEl = document.getElementById("trace-debug");
const selectionTraceEl = document.getElementById("selection-trace");
const candidateTraceEl = document.getElementById("candidate-trace");
const rawEntryEl = document.getElementById("raw-entry");

const defaultDriveLogURL = "./drive_match_log.ndjson";

const map = L.map("map", {
  zoomControl: true,
  preferCanvas: true
}).setView([49.0069, 8.4037], 11);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

let locationMarker = null;
let wayLayers = [];
let drivePathLayer = null;
let selectedFixMarker = null;
let sqlModulePromise = null;
let sqlDatabase = null;
let loadedDriveLogEntries = [];
let selectedDriveLogIndex = -1;

const replayWayColors = {
  logged: "#00e4ff",
  replay: "#ffb454",
  replayError: "#ff6a6a",
  hindsight: "#7fda8b"
};

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function setCoordinateValue(lat, lon) {
  coordValueEl.textContent = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}

function setBundleValue(value) {
  bundleValueEl.textContent = value;
}

function setStreetAndWay(street, wayID) {
  streetValueEl.textContent = street ?? "n/a";
  wayValueEl.textContent = wayID != null ? String(wayID) : "n/a";
}

function normalizeWayID(rawValue) {
  const trimmed = String(rawValue ?? "").trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  return Number.parseInt(trimmed, 10);
}

function safeString(value) {
  if (value == null) {
    return null;
  }
  const text = String(value).trim();
  return text.length ? text : null;
}

function finiteNumber(value) {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function streetDisplay(streetName, ref) {
  const name = safeString(streetName);
  const normalizedRef = safeString(ref);
  if (name && normalizedRef) {
    return `${name} (${normalizedRef})`;
  }
  return name ?? normalizedRef ?? null;
}

function resultStreetLabel(result) {
  return streetDisplay(result?.streetName, result?.streetRef) ?? safeString(result?.streetBaseName) ?? null;
}

function replayDebug(entry) {
  return entry?.replayDebug && typeof entry.replayDebug === "object" ? entry.replayDebug : null;
}

function replayResult(entry) {
  const debug = replayDebug(entry);
  return debug?.replayResult && typeof debug.replayResult === "object" ? debug.replayResult : null;
}

function replayHindsight(entry) {
  const debug = replayDebug(entry);
  return debug?.hindsight && typeof debug.hindsight === "object" ? debug.hindsight : null;
}

function replayOutcomeLabel(outcome) {
  switch (safeString(outcome)) {
    case "stable_correct":
      return "korrekt stabil";
    case "recovered":
      return "korrigiert";
    case "regressed":
      return "Regression";
    case "still_wrong":
      return "weiter falsch";
    case "diverged":
      return "abweichend";
    case "stable":
      return "stabil";
    default:
      return "annotiert";
  }
}

function replayOutcomeClass(outcome) {
  switch (safeString(outcome)) {
    case "stable_correct":
      return "ok";
    case "recovered":
    case "diverged":
      return "warn";
    case "regressed":
    case "still_wrong":
      return "error";
    default:
      return "neutral";
  }
}

function replayOutcomeSortKey(outcome) {
  switch (safeString(outcome)) {
    case "still_wrong":
      return 0;
    case "regressed":
      return 1;
    case "recovered":
      return 2;
    case "diverged":
      return 3;
    case "stable_correct":
      return 4;
    case "stable":
      return 5;
    default:
      return 6;
  }
}

function selectedTrace(result) {
  const traces = Array.isArray(result?.candidateTraces) ? result.candidateTraces : [];
  return traces.find((candidate) => candidate?.isSelected) ?? null;
}

function candidateRankForWay(result, wayID) {
  const normalizedWayID = safeString(wayID);
  if (!normalizedWayID) {
    return null;
  }
  const traces = Array.isArray(result?.candidateTraces) ? result.candidateTraces : [];
  return finiteNumber(traces.find((candidate) => safeString(candidate?.wayID) === normalizedWayID)?.rank);
}

function describeWay(result, wayID) {
  const normalizedWayID = safeString(wayID ?? result?.wayID);
  return {
    wayID: normalizedWayID,
    street: resultStreetLabel(result) ?? normalizedWayID ?? "n/a",
    ref: safeString(result?.streetRef)
  };
}

function basenameFromPath(path) {
  const cleaned = String(path ?? "").split("?")[0].split("#")[0];
  const parts = cleaned.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : cleaned;
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;");
}

function formatTimestamp(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return "n/a";
  }
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "short",
    timeStyle: "medium"
  }).format(date);
}

function formatNumber(value, digits = 1) {
  const numeric = finiteNumber(value);
  if (numeric == null) {
    return "n/a";
  }
  return numeric.toFixed(digits);
}

function formatDistance(value) {
  const numeric = finiteNumber(value);
  if (numeric == null) {
    return "n/a";
  }
  if (numeric >= 1000) {
    return `${(numeric / 1000).toFixed(2)} km`;
  }
  return `${numeric.toFixed(1)} m`;
}

function formatScorePair(score, geometryScore) {
  const effective = formatNumber(score, 1);
  const geometric = finiteNumber(geometryScore);
  if (geometric == null) {
    return `score ${effective}`;
  }
  return `score ${effective} · geom ${formatNumber(geometric, 1)}`;
}

function formatSpeed(value) {
  const numeric = finiteNumber(value);
  return numeric == null ? "n/a" : `${numeric.toFixed(1)} km/h`;
}

function formatDurationMs(value) {
  const numeric = finiteNumber(value);
  if (numeric == null || numeric < 0) {
    return "n/a";
  }
  const totalSeconds = Math.round(numeric / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function formatPercent(value) {
  const numeric = finiteNumber(value);
  return numeric == null ? "n/a" : `${numeric.toFixed(1)}%`;
}

function formatCount(value) {
  const numeric = finiteNumber(value);
  return numeric == null ? "0" : String(Math.round(numeric));
}

function compareDriveLogEntries(left, right) {
  const leftTimestamp = Date.parse(left?.timestampUTC ?? "");
  const rightTimestamp = Date.parse(right?.timestampUTC ?? "");
  if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp) && leftTimestamp !== rightTimestamp) {
    return leftTimestamp - rightTimestamp;
  }
  const leftFixID = finiteNumber(left?.fixID);
  const rightFixID = finiteNumber(right?.fixID);
  if (leftFixID != null && rightFixID != null && leftFixID !== rightFixID) {
    return leftFixID - rightFixID;
  }
  return 0;
}

function normalizeDriveLogEntries(entries) {
  return entries
    .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
    .map((entry) => ({ ...entry }))
    .sort(compareDriveLogEntries);
}

async function ensureSQLModule() {
  if (!sqlModulePromise) {
    if (typeof initSqlJs !== "function") {
      throw new Error("sql.js konnte nicht geladen werden");
    }
    sqlModulePromise = initSqlJs({
      locateFile: (file) => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/${file}`
    });
  }
  return sqlModulePromise;
}

function closeCurrentDatabase() {
  if (sqlDatabase && typeof sqlDatabase.close === "function") {
    sqlDatabase.close();
  }
  sqlDatabase = null;
}

function executeRows(sql, params = []) {
  if (!sqlDatabase) {
    throw new Error("Keine SQLite-Datenbank geladen");
  }
  const stmt = sqlDatabase.prepare(sql);
  try {
    stmt.bind(params);
    const rows = [];
    while (stmt.step()) {
      rows.push(stmt.getAsObject());
    }
    return rows;
  } finally {
    stmt.free();
  }
}

function querySingleValue(sql, params = []) {
  const rows = executeRows(sql, params);
  if (!rows.length) {
    return null;
  }
  const first = rows[0];
  const keys = Object.keys(first);
  return keys.length ? first[keys[0]] : null;
}

function validateRequiredTables() {
  const tables = new Set(
    executeRows("SELECT name FROM sqlite_master WHERE type='table'").map((row) => String(row.name || ""))
  );
  const required = ["ways", "way_geom"];
  const missing = required.filter((name) => !tables.has(name));
  if (missing.length) {
    throw new Error(`Fehlende Tabellen: ${missing.join(", ")}`);
  }
}

async function loadDatabaseFromBytes(bytes, sourceLabel) {
  const SQL = await ensureSQLModule();
  closeCurrentDatabase();
  sqlDatabase = new SQL.Database(new Uint8Array(bytes));
  validateRequiredTables();

  const schemaVersion = safeString(querySingleValue("SELECT value FROM metadata WHERE key='schema_version' LIMIT 1"));
  const sourceDist = safeString(querySingleValue("SELECT value FROM metadata WHERE key='source_v1_dist' LIMIT 1"));

  const suffixParts = [];
  if (schemaVersion) {
    suffixParts.push(`schema=${schemaVersion}`);
  }
  if (sourceDist) {
    suffixParts.push(sourceDist);
  }
  const suffix = suffixParts.length ? ` (${suffixParts.join(", ")})` : "";
  setBundleValue(`${sourceLabel}${suffix}`);

  if (selectedDriveLogIndex >= 0) {
    renderSelectedDriveLogEntry({ focusMap: false });
  }
}

async function loadDatabaseFromURL() {
  const url = dbURLInput.value.trim();
  if (!url) {
    setStatus("Bitte eine DB-URL eintragen.", true);
    return;
  }

  setStatus("Lade SQLite-Bundle ...");
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.arrayBuffer();
    await loadDatabaseFromBytes(data, basenameFromPath(url) || "sqlite-url");
    setStatus("SQLite-Bundle geladen.");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unbekannter Fehler";
    setStatus(`SQLite-Laden fehlgeschlagen: ${message}`, true);
  }
}

async function loadDatabaseFromFile(file) {
  setStatus("Lade ausgewählte SQLite-Datei ...");
  try {
    const data = await file.arrayBuffer();
    await loadDatabaseFromBytes(data, file.name || "sqlite-file");
    setStatus("SQLite-Datei geladen.");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unbekannter Fehler";
    setStatus(`Datei-Laden fehlgeschlagen: ${message}`, true);
  }
}

function parseDriveLogEntries(rawText) {
  const trimmed = String(rawText ?? "").trim();
  if (!trimmed) {
    return [];
  }

  if (trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed : [];
  }

  return trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function driveLogStreetLabel(entry) {
  const result = entry?.result ?? replayResult(entry) ?? {};
  return (
    streetDisplay(result.streetName, result.streetRef) ??
    safeString(result.streetBaseName) ??
    safeString(result.wayID) ??
    "n/a"
  );
}

function driveLogStatusClass(status) {
  return status === "matched" ? "ok" : status === "error" ? "warn" : "neutral";
}

function computeDriveLogStats(entries) {
  const stats = {
    totalEntries: entries.length,
    matchedCount: 0,
    routeDistanceM: 0,
    durationMs: null,
    maxSpeedKmh: null,
    speedLimitChanges: 0,
    distinctWays: new Set(),
    statusCounts: new Map(),
    streetCounts: new Map(),
    cityCounts: new Map(),
    limitCounts: new Map(),
    replayOutcomeCounts: new Map(),
    firstTimestamp: null,
    lastTimestamp: null,
    annotatedCount: 0,
    replayErrorCount: 0,
    replayDeltaCount: 0,
    replayGateCount: 0,
    hindsightCount: 0,
    hindsightReplayCorrectCount: 0,
    hindsightLoggedCorrectCount: 0,
    recoveredCount: 0,
    regressedCount: 0,
    stillWrongCount: 0
  };

  let previousPoint = null;
  let previousLimit = null;

  for (const entry of entries) {
    const timestamp = Date.parse(entry.timestampUTC ?? "");
    if (Number.isFinite(timestamp)) {
      stats.firstTimestamp = stats.firstTimestamp == null ? timestamp : Math.min(stats.firstTimestamp, timestamp);
      stats.lastTimestamp = stats.lastTimestamp == null ? timestamp : Math.max(stats.lastTimestamp, timestamp);
    }

    const status = safeString(entry.status) ?? "unknown";
    stats.statusCounts.set(status, (stats.statusCounts.get(status) ?? 0) + 1);
    if (status === "matched") {
      stats.matchedCount += 1;
    }

    const speedKmh = finiteNumber(entry.speedKmh);
    if (speedKmh != null) {
      stats.maxSpeedKmh = stats.maxSpeedKmh == null ? speedKmh : Math.max(stats.maxSpeedKmh, speedKmh);
    }

    const streetName = driveLogStreetLabel(entry);
    if (streetName !== "n/a") {
      stats.streetCounts.set(streetName, (stats.streetCounts.get(streetName) ?? 0) + 1);
    }

    const cityName = safeString(entry.result?.cityName);
    if (cityName) {
      stats.cityCounts.set(cityName, (stats.cityCounts.get(cityName) ?? 0) + 1);
    }

    const speedLimit = entry.speedLimitOverrideKmh ?? entry.result?.speedLimitKmh ?? null;
    if (speedLimit != null) {
      const label = String(speedLimit);
      stats.limitCounts.set(label, (stats.limitCounts.get(label) ?? 0) + 1);
      if (previousLimit != null && previousLimit !== label) {
        stats.speedLimitChanges += 1;
      }
      previousLimit = label;
    }

    const wayID = safeString(entry.result?.wayID);
    if (wayID) {
      stats.distinctWays.add(wayID);
    }

    const debug = replayDebug(entry);
    if (debug) {
      stats.annotatedCount += 1;
      const outcome = safeString(debug.outcome) ?? "annotated";
      stats.replayOutcomeCounts.set(outcome, (stats.replayOutcomeCounts.get(outcome) ?? 0) + 1);
      if (debug.isError) {
        stats.replayErrorCount += 1;
      }
      if (debug.loggedMatchesReplay === false) {
        stats.replayDeltaCount += 1;
      }
      if (debug.replayUsedThreeWayGate) {
        stats.replayGateCount += 1;
      }

      const hindsight = replayHindsight(entry);
      if (hindsight?.wayID) {
        stats.hindsightCount += 1;
        if (hindsight.replayMatches) {
          stats.hindsightReplayCorrectCount += 1;
        }
        if (hindsight.loggedMatches) {
          stats.hindsightLoggedCorrectCount += 1;
        }
      }

      if (outcome === "recovered") {
        stats.recoveredCount += 1;
      } else if (outcome === "regressed") {
        stats.regressedCount += 1;
      } else if (outcome === "still_wrong") {
        stats.stillWrongCount += 1;
      }
    }

    const lat = finiteNumber(entry.lat);
    const lon = finiteNumber(entry.lon);
    if (lat != null && lon != null) {
      if (previousPoint) {
        stats.routeDistanceM += haversineDistanceMeters(previousPoint.lat, previousPoint.lon, lat, lon);
      }
      previousPoint = { lat, lon };
    }
  }

  if (stats.firstTimestamp != null && stats.lastTimestamp != null) {
    stats.durationMs = Math.max(0, stats.lastTimestamp - stats.firstTimestamp);
  }

  const sortEntries = (mapObject) =>
    Array.from(mapObject.entries())
      .sort((left, right) => right[1] - left[1] || String(left[0]).localeCompare(String(right[0]), "de"))
      .slice(0, 5);

  stats.matchRate = stats.totalEntries ? (stats.matchedCount / stats.totalEntries) * 100 : null;
  stats.distinctWayCount = stats.distinctWays.size;
  stats.topStatuses = sortEntries(stats.statusCounts);
  stats.topStreets = sortEntries(stats.streetCounts);
  stats.topCities = sortEntries(stats.cityCounts);
  stats.topLimits = sortEntries(stats.limitCounts).map(([label, count]) => [`${label} km/h`, count]);
  stats.topReplayOutcomes = Array.from(stats.replayOutcomeCounts.entries())
    .sort((left, right) => right[1] - left[1] || replayOutcomeSortKey(left[0]) - replayOutcomeSortKey(right[0]))
    .map(([label, count]) => [replayOutcomeLabel(label), count]);
  stats.hindsightReplayAccuracy = stats.hindsightCount
    ? (stats.hindsightReplayCorrectCount / stats.hindsightCount) * 100
    : null;
  stats.hindsightLoggedAccuracy = stats.hindsightCount
    ? (stats.hindsightLoggedCorrectCount / stats.hindsightCount) * 100
    : null;

  return stats;
}

function renderOverviewCards(items) {
  return items
    .map(
      (item) => `
        <article class="overview-card">
          <span class="label">${escapeHTML(item.label)}</span>
          <span class="value">${escapeHTML(item.value)}</span>
          ${item.subvalue ? `<span class="subvalue">${escapeHTML(item.subvalue)}</span>` : ""}
        </article>
      `
    )
    .join("");
}

function renderBreakdownCard(title, rows) {
  const content = rows.length
    ? rows
        .map(
          ([label, count]) => `
            <div class="breakdown-row">
              <span>${escapeHTML(label)}</span>
              <strong>${escapeHTML(String(count))}</strong>
            </div>
          `
        )
        .join("")
    : '<div class="trace-empty">Keine Daten.</div>';

  return `
    <section class="breakdown-card">
      <h3>${escapeHTML(title)}</h3>
      <div class="breakdown-list">${content}</div>
    </section>
  `;
}

function updateDriveLogSummary() {
  if (!loadedDriveLogEntries.length) {
    logSummaryEl.textContent = "Noch kein Log geladen.";
    return;
  }
  const stats = computeDriveLogStats(loadedDriveLogEntries);
  const first = stats.firstTimestamp != null ? formatTimestamp(stats.firstTimestamp) : "n/a";
  const last = stats.lastTimestamp != null ? formatTimestamp(stats.lastTimestamp) : "n/a";
  const replaySuffix = stats.annotatedCount
    ? ` · ${stats.replayErrorCount} Replay-Fehler markiert`
    : "";
  logSummaryEl.textContent = `${stats.totalEntries} Fixes geladen (${first} bis ${last})${replaySuffix}.`;
}

function renderDriveLogOverview() {
  if (!loadedDriveLogEntries.length) {
    logOverviewEl.innerHTML = "";
    logBreakdownsEl.innerHTML = "";
    return;
  }

  const stats = computeDriveLogStats(loadedDriveLogEntries);
  const overviewItems = [
    {
      label: "Fixes",
      value: formatCount(stats.totalEntries),
      subvalue: `${formatPercent(stats.matchRate)} matched`
    },
    {
      label: "Dauer",
      value: formatDurationMs(stats.durationMs),
      subvalue: `${formatTimestamp(stats.firstTimestamp)} bis ${formatTimestamp(stats.lastTimestamp)}`
    },
    {
      label: "Route",
      value: formatDistance(stats.routeDistanceM),
      subvalue: `${formatCount(stats.distinctWayCount)} Ways`
    },
    {
      label: "Tempo",
      value: formatSpeed(stats.maxSpeedKmh),
      subvalue: `${formatCount(stats.speedLimitChanges)} Limitwechsel`
    }
  ];
  if (stats.annotatedCount) {
    overviewItems.push(
      {
        label: "Replay",
        value: formatCount(stats.annotatedCount),
        subvalue: `${formatCount(stats.replayErrorCount)} Fehler · ${formatCount(stats.recoveredCount)} korrigiert`
      },
      {
        label: "Hindsight",
        value: formatCount(stats.hindsightCount),
        subvalue: `Replay ${formatPercent(stats.hindsightReplayAccuracy)} · Log ${formatPercent(stats.hindsightLoggedAccuracy)}`
      }
    );
  }
  logOverviewEl.innerHTML = renderOverviewCards(overviewItems);

  const breakdowns = [
    renderBreakdownCard("Status", stats.topStatuses),
    renderBreakdownCard("Haeufige Strassen", stats.topStreets),
    renderBreakdownCard("Orte", stats.topCities),
    renderBreakdownCard("Limits", stats.topLimits)
  ];
  if (stats.annotatedCount) {
    breakdowns.unshift(renderBreakdownCard("Replay", stats.topReplayOutcomes));
  }
  logBreakdownsEl.innerHTML = breakdowns.join("");
}

function renderDriveLogList() {
  if (!loadedDriveLogEntries.length) {
    logListEl.innerHTML = "";
    return;
  }

  logListEl.innerHTML = loadedDriveLogEntries
    .map((entry, index) => {
      const selectedClass = index === selectedDriveLogIndex ? " active" : "";
      const debug = replayDebug(entry);
      const replay = replayResult(entry);
      const baseResult = entry.result ?? replay ?? {};
      const debugClass = debug?.isError ? " debug-error" : debug ? " debug-annotated" : "";
      const status = safeString(entry.status) ?? "unknown";
      const street = driveLogStreetLabel(entry);
      const city = safeString(baseResult.cityName) ?? "n/a";
      const limit = entry.speedLimitOverrideKmh ?? baseResult.speedLimitKmh ?? "n/a";
      const continuity = selectedTrace(baseResult)?.continuityClass ?? "n/a";
      const hindsight = replayHindsight(entry);
      const replayPill = debug
        ? `<span class="pill ${replayOutcomeClass(debug.outcome)}">${escapeHTML(replayOutcomeLabel(debug.outcome))}</span>`
        : "";
      const replaySummary = debug
        ? `<div class="muted">Replay ${escapeHTML(replay?.wayID ?? "n/a")} · Hindsight ${escapeHTML(hindsight?.wayID ?? "n/a")} · ${escapeHTML(debug.replayUsedThreeWayGate ? "three-way gate" : "kein gate")}</div>`
        : "";
      return `
        <button type="button" class="log-entry${selectedClass}${debugClass}" data-log-index="${index}">
          <div class="log-entry-header">
            <strong>${escapeHTML(formatTimestamp(entry.timestampUTC))}</strong>
            <div class="pill-row">
              <span class="pill ${driveLogStatusClass(status)}">${escapeHTML(status)}</span>
              ${replayPill}
            </div>
          </div>
          <div class="mono">${escapeHTML(street)}</div>
          <div class="muted">Fix ${escapeHTML(entry.fixID ?? "n/a")} · ${escapeHTML(city)} · Way ${escapeHTML(baseResult.wayID ?? "n/a")}</div>
          <div class="muted">Limit ${escapeHTML(limit)} · Tempo ${escapeHTML(formatSpeed(entry.speedKmh))} · Kontinuitaet ${escapeHTML(continuity)}</div>
          ${replaySummary}
        </button>
      `;
    })
    .join("");
}

function renderTraceSection(title, items, renderItem) {
  const body = items.length
    ? items.map(renderItem).join("")
    : '<div class="trace-empty">Keine Daten.</div>';
  return `
    <section>
      <div class="trace-section-title">${escapeHTML(title)}</div>
      ${body}
    </section>
  `;
}

function renderReplayWayChip(label, color, way, subtitle = null) {
  return `
    <div class="way-chip">
      <span class="swatch" style="background:${escapeHTML(color)}"></span>
      <div class="way-chip-copy">
        <span class="label">${escapeHTML(label)}</span>
        <strong>${escapeHTML(way.street)}</strong>
        <span class="muted mono">Way ${escapeHTML(way.wayID ?? "n/a")}${subtitle ? ` · ${escapeHTML(subtitle)}` : ""}</span>
      </div>
    </div>
  `;
}

function renderReplayDebugPanel(entry) {
  const debug = replayDebug(entry);
  if (!debug) {
    return "";
  }

  const logged = describeWay(entry.result);
  const replay = describeWay(replayResult(entry));
  const hindsight = replayHindsight(entry);
  const hindsightCandidate =
    (Array.isArray(entry.result?.candidateTraces)
      ? entry.result.candidateTraces.find((candidate) => safeString(candidate?.wayID) === safeString(hindsight?.wayID))
      : null) ??
    (Array.isArray(replayResult(entry)?.candidateTraces)
      ? replayResult(entry).candidateTraces.find((candidate) => safeString(candidate?.wayID) === safeString(hindsight?.wayID))
      : null);
  const hindsightWay = describeWay(
    hindsightCandidate,
    hindsight?.wayID
  );

  const cards = [
    renderReplayWayChip(
      "Logged",
      replayWayColors.logged,
      logged,
      debug.loggedSelectedRank != null ? `Rank ${debug.loggedSelectedRank}` : null
    ),
    renderReplayWayChip(
      "Replay",
      debug.isError ? replayWayColors.replayError : replayWayColors.replay,
      replay,
      debug.replaySelectedRank != null ? `Rank ${debug.replaySelectedRank}` : null
    )
  ];
  if (hindsight?.wayID) {
    const subtitleParts = [];
    if (hindsight.loggedCandidateRank != null) {
      subtitleParts.push(`Log Rank ${hindsight.loggedCandidateRank}`);
    }
    if (hindsight.replayCandidateRank != null) {
      subtitleParts.push(`Replay Rank ${hindsight.replayCandidateRank}`);
    }
    cards.push(renderReplayWayChip("Hindsight", replayWayColors.hindsight, hindsightWay, subtitleParts.join(" · ")));
  }

  const hindsightSummary = hindsight?.wayID
    ? `Log ${hindsight.loggedMatches ? "korrekt" : "falsch"} · Replay ${hindsight.replayMatches ? "korrekt" : "falsch"}`
    : "Kein hindsight-Label fuer diesen Fix";

  return `
    <section class="debug-panel">
      <div class="debug-panel-head">
        <div class="debug-panel-title">Replay Debug</div>
        <span class="pill ${replayOutcomeClass(debug.outcome)}">${escapeHTML(replayOutcomeLabel(debug.outcome))}</span>
      </div>
      <div class="debug-summary">
        <div class="debug-row">
          <span class="label">Vergleich</span>
          <span class="value muted">${escapeHTML(debug.loggedMatchesReplay ? "Log und Replay gleich" : "Replay weicht vom Log ab")}</span>
        </div>
        <div class="debug-row">
          <span class="label">Hindsight</span>
          <span class="value muted">${escapeHTML(hindsightSummary)}</span>
        </div>
        <div class="debug-row">
          <span class="label">Gate</span>
          <span class="value muted">${escapeHTML(debug.replayUsedThreeWayGate ? "three-way gate aktiv" : "kein three-way gate")}</span>
        </div>
      </div>
      <div class="way-legend">
        ${cards.join("")}
      </div>
    </section>
  `;
}

function renderSelectionTraceBlock(title, items) {
  return renderTraceSection(title, items ?? [], (item) => `
    <div class="trace-entry${item?.step === "three_way_gate" ? " replay-emphasis" : ""}">
      <strong>${escapeHTML(item?.step ?? "step")}</strong>
      <div class="mono">${escapeHTML(item?.detail ?? "")}</div>
    </div>
  `);
}

function renderCandidateTraceBlock(title, result, expectedWayID) {
  return renderTraceSection(title, result?.candidateTraces ?? [], (item) => {
    const isExpected = safeString(item?.wayID) != null && safeString(item?.wayID) === safeString(expectedWayID);
    const chips = [
      item?.isSelected ? '<span class="pill ok">selected</span>' : "",
      isExpected ? '<span class="pill expect">hindsight</span>' : ""
    ]
      .filter(Boolean)
      .join("");
    return `
      <div class="candidate-entry${item?.isSelected ? " selected" : ""}${isExpected ? " expected" : ""}">
        <div class="trace-section-head">
          <strong>#${escapeHTML(item?.rank ?? "n/a")} ${escapeHTML(streetDisplay(item?.streetName, item?.streetRef) ?? item?.wayID ?? "n/a")}</strong>
          <div class="pill-row">${chips}</div>
        </div>
        <div class="mono">way ${escapeHTML(item?.wayID ?? "n/a")} · ${escapeHTML(formatScorePair(item?.score, item?.geometryScore))} · dist ${escapeHTML(formatDistance(item?.distanceM))}</div>
        <div class="muted">continuity ${escapeHTML(item?.continuityClass ?? "n/a")} · endpoint ${escapeHTML(formatDistance(item?.endpointProximityM))} · corridor ${(item?.corridorSelectable ?? true) ? "ok" : "blocked"} · tunnel ${item?.tunnelSelectable ? "ok" : "blocked"}</div>
      </div>
    `;
  });
}

function renderHypothesisTraceBlock(title, result) {
  return renderTraceSection(title, result?.matchHypotheses ?? [], (item) => `
    <div class="trace-entry">
      <strong>${escapeHTML(streetDisplay(item?.streetName, item?.streetRef) ?? item?.wayID ?? "n/a")}</strong>
      <div class="mono">way ${escapeHTML(item?.wayID ?? "n/a")} · emission ${escapeHTML(formatNumber(item?.emissionScore, 1))} · cumulative ${escapeHTML(formatNumber(item?.cumulativeCost, 1))}</div>
      <div class="muted">endpoint ${escapeHTML(formatDistance(item?.endpointProximityM))} · ${escapeHTML(item?.highway ?? "n/a")} · tunnel ${item?.isTunnel ? "yes" : "no"}</div>
    </div>
  `);
}

function selectedMarkerStyle(entry) {
  const debug = replayDebug(entry);
  if (debug?.isError) {
    return {
      color: "#ffe5e5",
      fillColor: replayWayColors.replayError
    };
  }
  if (debug) {
    return {
      color: "#fff4dd",
      fillColor: replayWayColors.replay
    };
  }
  return {
    color: "#f8fafc",
    fillColor: "#ff8f40"
  };
}

function clearSelectedFixMarker() {
  if (selectedFixMarker) {
    selectedFixMarker.remove();
    selectedFixMarker = null;
  }
}

function renderSelectedDriveLogEntry(options = {}) {
  const { focusMap = true } = options;
  const entry = loadedDriveLogEntries[selectedDriveLogIndex];
  if (!entry) {
    traceMetaEl.textContent = "Kein Fix ausgewählt.";
    traceMetricsEl.innerHTML = "";
    traceDebugEl.innerHTML = "";
    selectionTraceEl.innerHTML = "";
    candidateTraceEl.innerHTML = "";
    rawEntryEl.textContent = "";
    clearWayLayers();
    clearSelectedFixMarker();
    return;
  }

  const debug = replayDebug(entry);
  const replay = replayResult(entry);
  const result = entry.result ?? replay ?? {};
  const hindsight = replayHindsight(entry);
  const street = driveLogStreetLabel(entry);
  const traceMetaSuffix = debug ? ` · ${replayOutcomeLabel(debug.outcome)}` : "";
  traceMetaEl.textContent = `Fix ${entry.fixID ?? "n/a"} · ${entry.status ?? "unknown"} · ${street} · Way ${result.wayID ?? "n/a"}${traceMetaSuffix}`;

  const metricCards = [
    {
      label: "Tempo / Limit",
      value: `${formatSpeed(entry.speedKmh)} / ${result.speedLimitKmh ?? entry.speedLimitOverrideKmh ?? "n/a"} km/h`,
      subvalue: `Override ${entry.speedLimitOverrideKmh ?? "n/a"}`
    },
    {
      label: "Ort",
      value: safeString(result.cityName) ?? "n/a",
      subvalue: result.citySource ? `${result.citySource} · ${result.insideCity ? "innerorts" : "ausserorts"}` : null
    },
    {
      label: "Matcher",
      value: `${formatCount(result.candidateCount)} Kandidaten`,
      subvalue: `${formatDurationMs(finiteNumber(result.queryTimeMs) != null ? result.queryTimeMs : null)} Query`
    },
    {
      label: "Entfernung",
      value: formatDistance(result.nearestCandidateDistanceM),
      subvalue: `Speed ${formatDistance(result.nearestSpeedCandidateDistanceM)}`
    },
    {
      label: "GPS",
      value: `${formatDistance(entry.horizontalAccM)} hAcc`,
      subvalue: `${formatDistance(entry.verticalAccM)} vAcc · ${entry.gpsSignalBars ?? "n/a"}/4 Balken`
    },
    {
      label: "Kurs / Tunnel",
      value: `${entry.courseDeg ?? "n/a"} deg`,
      subvalue: `Tunnel ${entry.tunnelModeState ?? "n/a"}`
    }
  ];
  if (debug) {
    metricCards.push(
      {
        label: "Replay",
        value: `${replay?.wayID ?? "n/a"} / ${replay?.speedLimitKmh ?? "n/a"} km/h`,
        subvalue: debug.replayUsedThreeWayGate ? "three-way gate aktiv" : "kein three-way gate"
      },
      {
        label: "Hindsight",
        value: hindsight?.wayID ?? "n/a",
        subvalue: hindsight?.wayID
          ? `Log ${hindsight.loggedMatches ? "korrekt" : "falsch"} · Replay ${hindsight.replayMatches ? "korrekt" : "falsch"}`
          : "kein Label"
      }
    );
  }
  traceMetricsEl.innerHTML = renderOverviewCards(metricCards);
  traceDebugEl.innerHTML = renderReplayDebugPanel(entry);

  selectionTraceEl.innerHTML = debug
    ? [
        renderSelectionTraceBlock("Logged Selection Trace", result.selectionTrace ?? []),
        renderSelectionTraceBlock("Replay Selection Trace", replay?.selectionTrace ?? [])
      ].join("")
    : renderSelectionTraceBlock("Selection Trace", result.selectionTrace ?? []);

  candidateTraceEl.innerHTML = debug
    ? [
        renderCandidateTraceBlock("Logged Kandidaten", result, hindsight?.wayID),
        renderCandidateTraceBlock("Replay Kandidaten", replay, hindsight?.wayID),
        renderHypothesisTraceBlock("Logged Hypothesen", result),
        renderHypothesisTraceBlock("Replay Hypothesen", replay)
      ].join("")
    : [
        renderCandidateTraceBlock("Kandidaten", result, null),
        renderHypothesisTraceBlock("Hypothesen", result)
      ].join("");

  rawEntryEl.textContent = JSON.stringify(entry, null, 2);

  const lat = finiteNumber(entry.lat);
  const lon = finiteNumber(entry.lon);
  if (lat != null && lon != null) {
    setCoordinateValue(lat, lon);
    const markerStyle = selectedMarkerStyle(entry);

    if (!selectedFixMarker) {
      selectedFixMarker = L.circleMarker([lat, lon], {
        radius: 8,
        color: markerStyle.color,
        weight: 2,
        fillColor: markerStyle.fillColor,
        fillOpacity: 0.95
      }).addTo(map);
    } else {
      selectedFixMarker.setLatLng([lat, lon]);
      selectedFixMarker.setStyle({
        color: markerStyle.color,
        fillColor: markerStyle.fillColor
      });
    }

    if (focusMap) {
      map.setView([lat, lon], Math.max(map.getZoom(), 15));
    }
  } else {
    clearSelectedFixMarker();
  }

  if (result.streetName || result.wayID) {
    setStreetAndWay(streetDisplay(result.streetName, result.streetRef) ?? street, result.wayID ?? null);
    wayInput.value = result.wayID != null ? String(result.wayID) : wayInput.value;
  }

  if (sqlDatabase) {
    const specs = [];
    if (safeString(result.wayID)) {
      specs.push({
        wayID: result.wayID,
        label: "logged",
        color: replayWayColors.logged,
        weight: 6,
        opacity: 0.9
      });
    }
    if (safeString(replay?.wayID)) {
      specs.push({
        wayID: replay.wayID,
        label: "replay",
        color: debug?.isError ? replayWayColors.replayError : replayWayColors.replay,
        weight: 5,
        opacity: 0.95,
        dashArray: "10 8"
      });
    }
    if (safeString(hindsight?.wayID)) {
      specs.push({
        wayID: hindsight.wayID,
        label: "hindsight",
        color: replayWayColors.hindsight,
        weight: 4,
        opacity: 0.95,
        dashArray: "4 8"
      });
    }
    drawWayHighlights(specs);
  } else {
    clearWayLayers();
  }
}

function loadDriveLogEntries(entries, sourceLabel, options = {}) {
  const { statusMessage = true } = options;
  loadedDriveLogEntries = normalizeDriveLogEntries(entries);
  selectedDriveLogIndex = loadedDriveLogEntries.length ? loadedDriveLogEntries.length - 1 : -1;
  updateDriveLogSummary();
  renderDriveLogOverview();
  renderDriveLogList();
  drawDriveLogPath();
  renderSelectedDriveLogEntry({ focusMap: false });

  if (drivePathLayer) {
    map.fitBounds(drivePathLayer.getBounds(), { padding: [36, 36] });
  }

  if (statusMessage) {
    setStatus(`Drive-Log geladen: ${sourceLabel}`);
  }
}

async function loadDriveLogFromFile(file) {
  setStatus("Lade Drive-Log ...");
  try {
    const rawText = await file.text();
    loadDriveLogEntries(parseDriveLogEntries(rawText), file.name || "drive-log");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unbekannter Fehler";
    setStatus(`Drive-Log fehlgeschlagen: ${message}`, true);
  }
}

async function loadDriveLogFromURL(url, options = {}) {
  const { silent = false } = options;
  if (!silent) {
    setStatus("Lade Drive-Log ...");
  }
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const rawText = await response.text();
    loadDriveLogEntries(parseDriveLogEntries(rawText), basenameFromPath(url) || "drive-log", {
      statusMessage: !silent
    });
  } catch (error) {
    if (!silent) {
      const message = error instanceof Error ? error.message : "Unbekannter Fehler";
      setStatus(`Drive-Log fehlgeschlagen: ${message}`, true);
    }
  }
}

function requireDatabase() {
  if (!sqlDatabase) {
    setStatus("Bitte zuerst ein SQLite-Bundle laden.", true);
    return false;
  }
  return true;
}

function parseWayPoints(rawJSON) {
  const raw = safeString(rawJSON);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((entry) => Array.isArray(entry) && entry.length >= 2)
      .map((entry) => [Number(entry[0]), Number(entry[1])])
      .filter((pair) => Number.isFinite(pair[0]) && Number.isFinite(pair[1]));
  } catch {
    return [];
  }
}

function queryBounds(lat, lon, radiusM = 50) {
  const degLat = radiusM / 111132.0;
  const cosLat = Math.max(0.173648, Math.abs(Math.cos((lat * Math.PI) / 180.0)));
  const degLon = radiusM / (111320.0 * cosLat);
  return {
    minLon: lon - degLon,
    minLat: lat - degLat,
    maxLon: lon + degLon,
    maxLat: lat + degLat
  };
}

function toXYMeters(lat, lon, originLat, originLon) {
  const metersPerDegLat = 111132.0;
  const metersPerDegLon = 111320.0 * Math.cos((originLat * Math.PI) / 180.0);
  return {
    x: (lon - originLon) * metersPerDegLon,
    y: (lat - originLat) * metersPerDegLat
  };
}

function pointToSegmentDistanceM(lat, lon, lat1, lon1, lat2, lon2) {
  const origin = toXYMeters(lat, lon, lat, lon);
  const start = toXYMeters(lat1, lon1, lat, lon);
  const end = toXYMeters(lat2, lon2, lat, lon);

  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) {
    return Math.hypot(origin.x - start.x, origin.y - start.y);
  }

  const tNumerator = (origin.x - start.x) * dx + (origin.y - start.y) * dy;
  const tDenominator = dx * dx + dy * dy;
  const t = Math.min(Math.max(tNumerator / tDenominator, 0), 1);
  const projectionX = start.x + t * dx;
  const projectionY = start.y + t * dy;
  return Math.hypot(origin.x - projectionX, origin.y - projectionY);
}

function haversineDistanceMeters(aLat, aLon, bLat, bLon) {
  const r = 6371008.8;
  const p1 = (aLat * Math.PI) / 180.0;
  const p2 = (bLat * Math.PI) / 180.0;
  const dLat = ((bLat - aLat) * Math.PI) / 180.0;
  const dLon = ((bLon - aLon) * Math.PI) / 180.0;
  const s1 = Math.sin(dLat / 2) ** 2;
  const s2 = Math.sin(dLon / 2) ** 2;
  const a = s1 + Math.cos(p1) * Math.cos(p2) * s2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

function distanceToBBoxM(lat, lon, minLon, minLat, maxLon, maxLat) {
  const clampedLon = Math.min(Math.max(lon, minLon), maxLon);
  const clampedLat = Math.min(Math.max(lat, minLat), maxLat);
  return haversineDistanceMeters(lat, lon, clampedLat, clampedLon);
}

function polylineDistanceM(lat, lon, points) {
  if (!points.length) {
    return null;
  }
  if (points.length === 1) {
    const [pLat, pLon] = points[0];
    return haversineDistanceMeters(lat, lon, pLat, pLon);
  }
  let best = Number.POSITIVE_INFINITY;
  for (let i = 0; i < points.length - 1; i += 1) {
    const [lat1, lon1] = points[i];
    const [lat2, lon2] = points[i + 1];
    const distance = pointToSegmentDistanceM(lat, lon, lat1, lon1, lat2, lon2);
    if (distance < best) {
      best = distance;
    }
  }
  return Number.isFinite(best) ? best : null;
}

function clearWayLayers() {
  for (const layer of wayLayers) {
    layer.remove();
  }
  wayLayers = [];
}

function drawWay(points) {
  clearWayLayers();
  if (points.length < 2) {
    return;
  }
  const layer = L.polyline(points, {
    color: "#00e4ff",
    weight: 6,
    opacity: 0.85
  }).addTo(map);
  wayLayers = [layer];
}

function drawWayHighlights(specs) {
  clearWayLayers();
  if (!sqlDatabase || !Array.isArray(specs) || !specs.length) {
    return;
  }

  const mergedSpecs = new Map();
  for (const spec of specs) {
    const wayID = normalizeWayID(spec?.wayID);
    if (wayID == null) {
      continue;
    }
    const existing = mergedSpecs.get(wayID);
    if (existing) {
      existing.labels.push(spec.label);
      existing.weight = Math.max(existing.weight, spec.weight ?? 5);
      existing.opacity = Math.max(existing.opacity, spec.opacity ?? 0.9);
      continue;
    }
    mergedSpecs.set(wayID, {
      ...spec,
      wayID,
      labels: [spec.label]
    });
  }

  for (const spec of mergedSpecs.values()) {
    const row = queryWayByID(spec.wayID);
    if (!row) {
      continue;
    }
    const points = parseWayPoints(row.points_json);
    if (points.length < 2) {
      continue;
    }
    const layer = L.polyline(points, {
      color: spec.color ?? replayWayColors.logged,
      weight: spec.weight ?? 5,
      opacity: spec.opacity ?? 0.9,
      dashArray: spec.dashArray
    }).addTo(map);
    if (spec.labels?.length) {
      layer.bindTooltip(spec.labels.join(" + "));
    }
    wayLayers.push(layer);
  }
}

function drawDriveLogPath() {
  if (drivePathLayer) {
    drivePathLayer.remove();
    drivePathLayer = null;
  }

  const points = loadedDriveLogEntries
    .map((entry) => {
      const lat = finiteNumber(entry.lat);
      const lon = finiteNumber(entry.lon);
      return lat != null && lon != null ? [lat, lon] : null;
    })
    .filter(Boolean);

  if (points.length < 2) {
    return;
  }

  drivePathLayer = L.polyline(points, {
    color: "#7fda8b",
    weight: 4,
    opacity: 0.75
  }).addTo(map);
}

function queryWayByID(wayID) {
  const sql = `
    SELECT
      w.way_id AS way_id,
      w.street_name AS street_name,
      w.ref AS ref,
      w.maxspeed AS maxspeed,
      w.min_lon AS min_lon,
      w.min_lat AS min_lat,
      w.max_lon AS max_lon,
      w.max_lat AS max_lat,
      g.points_json AS points_json
    FROM ways w
    LEFT JOIN way_geom g ON g.way_id = w.way_id
    WHERE w.way_id = ?1
    LIMIT 1
  `;
  const rows = executeRows(sql, [wayID]);
  return rows.length ? rows[0] : null;
}

function queryBestWayAt(lat, lon, radiusM = 50, maxCandidates = 256) {
  const bounds = queryBounds(lat, lon, radiusM);
  const sql = `
    SELECT
      w.way_id AS way_id,
      w.street_name AS street_name,
      w.ref AS ref,
      w.maxspeed AS maxspeed,
      w.min_lon AS min_lon,
      w.min_lat AS min_lat,
      w.max_lon AS max_lon,
      w.max_lat AS max_lat,
      g.points_json AS points_json
    FROM ways w
    LEFT JOIN way_geom g ON g.way_id = w.way_id
    WHERE w.min_lon <= ?1 AND w.max_lon >= ?2
      AND w.min_lat <= ?3 AND w.max_lat >= ?4
    LIMIT ?5
  `;

  const rows = executeRows(sql, [bounds.maxLon, bounds.minLon, bounds.maxLat, bounds.minLat, maxCandidates]);
  if (!rows.length) {
    return null;
  }

  let best = null;
  for (const row of rows) {
    const points = parseWayPoints(row.points_json);
    const bboxDistance = distanceToBBoxM(
      lat,
      lon,
      Number(row.min_lon),
      Number(row.min_lat),
      Number(row.max_lon),
      Number(row.max_lat)
    );
    const polyDistance = polylineDistanceM(lat, lon, points);
    const distanceM = polyDistance ?? bboxDistance;

    if (!best || distanceM < best.distanceM || (distanceM === best.distanceM && Number(row.way_id) < Number(best.row.way_id))) {
      best = {
        row,
        points,
        distanceM
      };
    }
  }
  return best;
}

function applyLocation(lat, lon) {
  setCoordinateValue(lat, lon);
  if (!locationMarker) {
    locationMarker = L.circleMarker([lat, lon], {
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#5da9ff",
      fillOpacity: 0.9
    }).addTo(map);
  } else {
    locationMarker.setLatLng([lat, lon]);
  }
  map.flyTo([lat, lon], Math.max(map.getZoom(), 16), {
    animate: true,
    duration: 0.5
  });
}

function readBrowserLocation() {
  if (!navigator.geolocation) {
    setStatus("Geolocation wird im Browser nicht unterstützt.", true);
    return;
  }
  setStatus("Lese aktuelle Position ...");
  navigator.geolocation.getCurrentPosition(
    (position) => {
      applyLocation(position.coords.latitude, position.coords.longitude);
      setStatus("Aktuelle Position gesetzt.");
    },
    (error) => {
      const codeText = typeof error?.code === "number" ? ` (Code ${error.code})` : "";
      setStatus(`Standort konnte nicht gelesen werden${codeText}.`, true);
    },
    {
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 0
    }
  );
}

function loadAndCenterWay(rawWayID) {
  if (!requireDatabase()) {
    return;
  }
  const wayID = normalizeWayID(rawWayID);
  if (wayID == null) {
    setStatus("Ungültige Way-ID. Bitte nur Ziffern eingeben.", true);
    return;
  }

  const row = queryWayByID(wayID);
  if (!row) {
    setStatus(`Way ${wayID} nicht im geladenen Bundle gefunden.`, true);
    setStreetAndWay(null, wayID);
    return;
  }

  const points = parseWayPoints(row.points_json);
  drawWay(points);

  const street = streetDisplay(row.street_name, row.ref);
  setStreetAndWay(street, wayID);
  wayInput.value = String(wayID);

  if (points.length >= 2 && wayLayers[0]) {
    map.fitBounds(wayLayers[0].getBounds(), { padding: [32, 32] });
    const center = wayLayers[0].getBounds().getCenter();
    setCoordinateValue(center.lat, center.lng);
  } else {
    const centerLat = (Number(row.min_lat) + Number(row.max_lat)) / 2;
    const centerLon = (Number(row.min_lon) + Number(row.max_lon)) / 2;
    map.flyTo([centerLat, centerLon], Math.max(map.getZoom(), 16), { animate: true, duration: 0.5 });
    setCoordinateValue(centerLat, centerLon);
  }

  const speed = safeString(row.maxspeed) ?? "n/a";
  setStatus(`Way ${wayID} geladen (maxspeed=${speed}).`);
}

function identifyStreetUnderCrosshair() {
  if (!requireDatabase()) {
    return;
  }

  const center = map.getCenter();
  setCoordinateValue(center.lat, center.lng);
  setStatus("Suche Straße unter Fadenkreuz ...");

  const best = queryBestWayAt(center.lat, center.lng, 50, 256);
  if (!best) {
    setStreetAndWay(null, null);
    setStatus("Keine Straße im Suchradius gefunden.", true);
    return;
  }

  drawWay(best.points);
  const street = streetDisplay(best.row.street_name, best.row.ref) ?? "unbekannt";
  const wayID = Number(best.row.way_id);
  setStreetAndWay(street, wayID);
  wayInput.value = String(wayID);

  if (wayLayers[0]) {
    map.fitBounds(wayLayers[0].getBounds(), { padding: [32, 32] });
  }

  setStatus(`Identifiziert: ${street} (Way ${wayID}, ~${Math.round(best.distanceM)} m).`);
}

dbLoadBtn.addEventListener("click", loadDatabaseFromURL);
dbFileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  await loadDatabaseFromFile(file);
  dbFileInput.value = "";
});
logFileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  await loadDriveLogFromFile(file);
  logFileInput.value = "";
});
locateBtn.addEventListener("click", readBrowserLocation);
identifyBtn.addEventListener("click", identifyStreetUnderCrosshair);
wayBtn.addEventListener("click", () => loadAndCenterWay(wayInput.value));
logListEl.addEventListener("click", (event) => {
  const button = event.target.closest("[data-log-index]");
  if (!button) {
    return;
  }
  const index = Number(button.getAttribute("data-log-index"));
  if (!Number.isInteger(index)) {
    return;
  }
  selectedDriveLogIndex = index;
  renderDriveLogList();
  renderSelectedDriveLogEntry({ focusMap: true });
});
wayInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    loadAndCenterWay(wayInput.value);
  }
});

map.whenReady(() => {
  const center = map.getCenter();
  setCoordinateValue(center.lat, center.lng);
  setStreetAndWay(null, null);
  setBundleValue("nicht geladen");
  setStatus("Bereit. SQLite-Bundle laden.");
  void loadDatabaseFromURL();
  void loadDriveLogFromURL(defaultDriveLogURL, { silent: true });
});

map.on("moveend", () => {
  const center = map.getCenter();
  setCoordinateValue(center.lat, center.lng);
});
