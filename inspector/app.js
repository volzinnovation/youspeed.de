const statusEl = document.getElementById("status");
const coordValueEl = document.getElementById("coord-value");
const wayValueEl = document.getElementById("way-value");
const streetValueEl = document.getElementById("street-value");
const bundleValueEl = document.getElementById("bundle-value");

const dbURLInput = document.getElementById("db-url-input");
const dbLoadBtn = document.getElementById("db-load-btn");
const dbFileInput = document.getElementById("db-file-input");
const wayInput = document.getElementById("way-id-input");
const locateBtn = document.getElementById("locate-btn");
const identifyBtn = document.getElementById("identify-btn");
const wayBtn = document.getElementById("way-btn");

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
let sqlModulePromise = null;
let sqlDatabase = null;

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
    opacity: 0.9
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
locateBtn.addEventListener("click", readBrowserLocation);
identifyBtn.addEventListener("click", identifyStreetUnderCrosshair);
wayBtn.addEventListener("click", () => loadAndCenterWay(wayInput.value));
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
});

map.on("moveend", () => {
  const center = map.getCenter();
  setCoordinateValue(center.lat, center.lng);
});
