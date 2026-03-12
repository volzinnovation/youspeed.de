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
let wayLayer = null;
let drivePathLayer = null;
let selectedFixMarker = null;
let sqlModulePromise = null;
let sqlDatabase = null;
let loadedDriveLogEntries = [];
let selectedDriveLogIndex = -1;

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
  const result = entry?.result ?? {};
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
    firstTimestamp: null,
    lastTimestamp: null
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
  logSummaryEl.textContent = `${stats.totalEntries} Fixes geladen (${first} bis ${last}).`;
}

function renderDriveLogOverview() {
  if (!loadedDriveLogEntries.length) {
    logOverviewEl.innerHTML = "";
    logBreakdownsEl.innerHTML = "";
    return;
  }

  const stats = computeDriveLogStats(loadedDriveLogEntries);
  logOverviewEl.innerHTML = renderOverviewCards([
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
  ]);

  logBreakdownsEl.innerHTML = [
    renderBreakdownCard("Status", stats.topStatuses),
    renderBreakdownCard("Haeufige Strassen", stats.topStreets),
    renderBreakdownCard("Orte", stats.topCities),
    renderBreakdownCard("Limits", stats.topLimits)
  ].join("");
}

function renderDriveLogList() {
  if (!loadedDriveLogEntries.length) {
    logListEl.innerHTML = "";
    return;
  }

  logListEl.innerHTML = loadedDriveLogEntries
    .map((entry, index) => {
      const selectedClass = index === selectedDriveLogIndex ? " active" : "";
      const status = safeString(entry.status) ?? "unknown";
      const street = driveLogStreetLabel(entry);
      const city = safeString(entry.result?.cityName) ?? "n/a";
      const limit = entry.speedLimitOverrideKmh ?? entry.result?.speedLimitKmh ?? "n/a";
      const continuity =
        entry.result?.candidateTraces?.find((candidate) => candidate?.isSelected)?.continuityClass ?? "n/a";
      return `
        <button type="button" class="log-entry${selectedClass}" data-log-index="${index}">
          <div class="log-entry-header">
            <strong>${escapeHTML(formatTimestamp(entry.timestampUTC))}</strong>
            <span class="pill ${driveLogStatusClass(status)}">${escapeHTML(status)}</span>
          </div>
          <div class="mono">${escapeHTML(street)}</div>
          <div class="muted">Fix ${escapeHTML(entry.fixID ?? "n/a")} · ${escapeHTML(city)} · Way ${escapeHTML(entry.result?.wayID ?? "n/a")}</div>
          <div class="muted">Limit ${escapeHTML(limit)} · Tempo ${escapeHTML(formatSpeed(entry.speedKmh))} · Kontinuitaet ${escapeHTML(continuity)}</div>
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
    selectionTraceEl.innerHTML = "";
    candidateTraceEl.innerHTML = "";
    rawEntryEl.textContent = "";
    clearSelectedFixMarker();
    return;
  }

  const result = entry.result ?? {};
  const street = driveLogStreetLabel(entry);
  traceMetaEl.textContent = `Fix ${entry.fixID ?? "n/a"} · ${entry.status ?? "unknown"} · ${street} · Way ${result.wayID ?? "n/a"}`;

  traceMetricsEl.innerHTML = renderOverviewCards([
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
  ]);

  selectionTraceEl.innerHTML = renderTraceSection("Selection Trace", result.selectionTrace ?? [], (item) => `
    <div class="trace-entry">
      <strong>${escapeHTML(item.step ?? "step")}</strong>
      <div class="mono">${escapeHTML(item.detail ?? "")}</div>
    </div>
  `);

  candidateTraceEl.innerHTML = [
    renderTraceSection("Kandidaten", result.candidateTraces ?? [], (item) => `
      <div class="candidate-entry${item.isSelected ? " selected" : ""}">
        <div class="trace-section-head">
          <strong>#${escapeHTML(item.rank ?? "n/a")} ${escapeHTML(streetDisplay(item.streetName, item.streetRef) ?? item.wayID ?? "n/a")}</strong>
          ${item.isSelected ? '<span class="pill ok">selected</span>' : ""}
        </div>
        <div class="mono">way ${escapeHTML(item.wayID ?? "n/a")} · ${escapeHTML(formatScorePair(item.score, item.geometryScore))} · dist ${escapeHTML(formatDistance(item.distanceM))}</div>
        <div class="muted">continuity ${escapeHTML(item.continuityClass ?? "n/a")} · endpoint ${escapeHTML(formatDistance(item.endpointProximityM))} · corridor ${(item.corridorSelectable ?? true) ? "ok" : "blocked"} · tunnel ${item.tunnelSelectable ? "ok" : "blocked"}</div>
      </div>
    `),
    renderTraceSection("Hypothesen", result.matchHypotheses ?? [], (item) => `
      <div class="trace-entry">
        <strong>${escapeHTML(streetDisplay(item.streetName, item.streetRef) ?? item.wayID ?? "n/a")}</strong>
        <div class="mono">way ${escapeHTML(item.wayID ?? "n/a")} · emission ${escapeHTML(formatNumber(item.emissionScore, 1))} · cumulative ${escapeHTML(formatNumber(item.cumulativeCost, 1))}</div>
        <div class="muted">endpoint ${escapeHTML(formatDistance(item.endpointProximityM))} · ${escapeHTML(item.highway ?? "n/a")} · tunnel ${item.isTunnel ? "yes" : "no"}</div>
      </div>
    `)
  ].join("");

  rawEntryEl.textContent = JSON.stringify(entry, null, 2);

  const lat = finiteNumber(entry.lat);
  const lon = finiteNumber(entry.lon);
  if (lat != null && lon != null) {
    setCoordinateValue(lat, lon);

    if (!selectedFixMarker) {
      selectedFixMarker = L.circleMarker([lat, lon], {
        radius: 8,
        color: "#f8fafc",
        weight: 2,
        fillColor: "#ff8f40",
        fillOpacity: 0.95
      }).addTo(map);
    } else {
      selectedFixMarker.setLatLng([lat, lon]);
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

  const selectedWayID = normalizeWayID(result.wayID);
  if (selectedWayID != null && sqlDatabase) {
    const row = queryWayByID(selectedWayID);
    if (row) {
      drawWay(parseWayPoints(row.points_json));
    }
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

function drawWay(points) {
  if (wayLayer) {
    wayLayer.remove();
    wayLayer = null;
  }
  if (points.length < 2) {
    return;
  }
  wayLayer = L.polyline(points, {
    color: "#00e4ff",
    weight: 6,
    opacity: 0.85
  }).addTo(map);
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

  if (points.length >= 2 && wayLayer) {
    map.fitBounds(wayLayer.getBounds(), { padding: [32, 32] });
    const center = wayLayer.getBounds().getCenter();
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

  if (wayLayer) {
    map.fitBounds(wayLayer.getBounds(), { padding: [32, 32] });
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
