(function initializeBackendCrops() {
  "use strict";
  const el = (id) => document.getElementById("crops-" + id);
  const pageSize = 50;
  let offset = 0;
  let hasMore = false;
  let started = false;
  let listRequest = 0;
  let activationRequest = 0;
  let imageRequest = 0;
  let devicesRequest = 0;
  let imageURL = null;
  let imageController = null;
  let selected = null;
  const reviews = window.YouSpeedCropReview?.create(getJSON, (row) => {
    for (const card of el("gallery").children) {
      if (card.dataset?.cropIdentity === reviews.core.key(row)) {
        const badge = card.querySelector?.(".crop-review-badge");
        if (badge) badge.textContent = reviews.core.reviewLabel(row.current_review);
      }
    }
  });

  async function getJSON(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", credentials: "omit", ...options });
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("Crop-Server fehlt. Inspector mit python3 inspector/server.py starten; python -m http.server bietet keinen Backend-Zugriff.");
    }
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error || "Report-Abfrage fehlgeschlagen.");
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function clearImage() {
    imageController?.abort();
    imageController = null;
    imageRequest += 1;
    el("stage").hidden = true;
    el("image").removeAttribute("src");
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null;
  }

  function displayBox() {
    const manifest = selected?.manifest;
    const original = manifest?.original_box;
    const actual = manifest?.actual_box;
    const box = el("sign-box");
    box.hidden = true;
    if (!el("show-box").checked || !Array.isArray(original) || !Array.isArray(actual)
      || original.length !== 4 || actual.length !== 4 || ![...original, ...actual].every(Number.isFinite)) return;
    const width = actual[2] - actual[0];
    const height = actual[3] - actual[1];
    if (width <= 0 || height <= 0) return;
    const left = Math.max(original[0], actual[0]);
    const top = Math.max(original[1], actual[1]);
    const right = Math.min(original[2], actual[2]);
    const bottom = Math.min(original[3], actual[3]);
    if (right <= left || bottom <= top) return;
    Object.assign(box.style, {
      left: ((left - actual[0]) / width * 100) + "%",
      top: ((top - actual[1]) / height * 100) + "%",
      width: ((right - left) / width * 100) + "%",
      height: ((bottom - top) / height * 100) + "%"
    });
    box.hidden = false;
  }

  function label(row) {
    const classification = row.observation?.classification;
    return classification?.canonical_code || classification?.model_label || "Ohne Zeichenklasse";
  }

  function platformLabel(platform) {
    if (["ios", "iphone"].includes(platform?.toLowerCase())) return "iPhone";
    if (platform?.toLowerCase() === "android") return "Android";
    return platform || "Plattform unbekannt";
  }

  async function loadDevices() {
    const request = ++devicesRequest;
    const value = el("installation").value;
    const result = await getJSON("./api/crops/devices?" + new URLSearchParams({scope: el("scope").value || "live"}));
    if (request !== devicesRequest) return;
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "Alle Geräte";
    const options = [all];
    for (const device of result.devices) {
      const option = document.createElement("option");
      option.value = device.installation;
      const platforms = device.platforms?.length ? device.platforms.map(platformLabel).join(" / ") : "Plattform unbekannt";
      option.textContent = `${platforms} · ${device.installation} · ${device.crop_count} Crops`;
      options.push(option);
    }
    if (value && !result.devices.some(device => device.installation === value)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `${value} · keine aktiven Crops`;
      options.push(option);
    }
    el("installation").replaceChildren(...options);
    el("installation").value = value;
  }

  function addMetadata(name, value) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = name;
    description.textContent = value == null ? "—" : String(value);
    el("metadata").append(term, description);
    return description;
  }

  function addVehiclePosition(position) {
    const lat = position?.latitude;
    const lon = position?.longitude;
    const description = addMetadata("Fahrzeugposition", position ? `${lat}, ${lon}` : null);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
    const link = document.createElement("a");
    link.href = `?lat=${lat}&lon=${lon}#matcher`;
    link.textContent = `${lat}, ${lon}`;
    link.title = "Fahrzeugposition auf der Karte öffnen";
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      document.getElementById("matcher-mode-btn").click();
      const bridge = window.YouSpeedInspectorBridge;
      // The bundled drive may fit its bounds while loading; focus after it settles.
      void Promise.resolve(bridge?.ensureMatcherData()).then(() => bridge?.focusVehiclePosition(lat, lon));
    });
    description.replaceChildren(link);
  }

  function addFramePosition(manifest, observation) {
    const cropPosition = Object.prototype.hasOwnProperty.call(manifest, "vehicle_position");
    // Explicitly missing crop GPS must never inherit an older sighting's fix.
    const position = cropPosition ? manifest.vehicle_position : observation?.vehicle_position;
    addMetadata("Positionsbezug", cropPosition ? "Crop-Aufnahme" : "Beobachtung · ältere Crop-Metadaten");
    addVehiclePosition(position);
    const number = (value, unit) => Number.isFinite(value) ? `${value} ${unit}` : null;
    addMetadata("Fahrtrichtung (GPS-Kurs)", number(position?.course_degrees, "°"));
    addMetadata("Kursgenauigkeit", number(position?.course_accuracy_degrees, "°"));
    addMetadata("Positionsgenauigkeit", number(position?.horizontal_accuracy_m, "m"));
    addMetadata("GPS-Fix (UTC)", position?.fix_at);
    addMetadata("Frame − GPS-Fix", number(position?.frame_fix_delta_ms, "ms"));
    addMetadata("Positionsabgleich", position?.alignment);
  }

  async function select(row, button) {
    clearImage();
    selected = row;
    void reviews?.select(row);
    for (const card of el("gallery").children) card.setAttribute("aria-pressed", String(card === button));
    const manifest = row.manifest;
    const observation = row.observation;
    el("title").textContent = label(row);
    el("metadata").replaceChildren();
    addMetadata("Geräte-ID (Installation)", row.installation);
    addMetadata("Sammlungsepoche", row.epoch);
    addMetadata("Crop-ID", row.crop_id);
    addMetadata("Beobachtung", manifest.observation_id);
    addMetadata("Aufnahme (UTC)", manifest.source_frame_at);
    addMetadata("Erfassung", manifest.source_kind);
    addMetadata("Land", observation?.classification?.country);
    addMetadata("App", observation?.app ? `${observation.app.platform} · ${observation.app.version} (${observation.app.build})` : null);
    addMetadata("Detektor / Klassifikator", `${observation?.scores?.detector_raw ?? "—"} / ${observation?.scores?.classifier_raw ?? "—"}`);
    addMetadata("Bild", `${manifest.decoded_width} × ${manifest.decoded_height} · ${manifest.encoding} · ${manifest.byte_length} Bytes`);
    addMetadata("Kontext unten", `${manifest.actual_extra_height} px${manifest.bottom_clipped ? " · abgeschnitten" : ""}`);
    addFramePosition(manifest, observation);
    addMetadata("Läuft ab (UTC)", new Date(row.expires * 1000).toISOString());
    addMetadata("SHA-256", row.digest);
    el("raw").textContent = JSON.stringify({ installation_id: row.installation, collection_epoch: row.epoch, manifest, observation }, null, 2);
    el("image-status").textContent = "Bild wird geladen und serverseitig geprüft …";
    const request = imageRequest;
    imageController = new AbortController();
    try {
      const response = await fetch(row.image_url, { cache: "no-store", credentials: "omit", signal: imageController.signal });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error || "Bild nicht verfügbar.");
      }
      if (!["image/png", "image/jpeg"].includes(response.headers.get("content-type"))) throw new Error("Unerwartetes Bildformat.");
      const blob = await response.blob();
      if (request !== imageRequest) return;
      imageURL = URL.createObjectURL(blob);
      el("image").src = imageURL;
      await el("image").decode();
      if (request !== imageRequest) return;
      el("stage").hidden = false;
      el("image-status").textContent = "Gespeicherte Originalbytes · SHA-256 geprüft";
      displayBox();
    } catch (error) {
      if (request === imageRequest) el("image-status").textContent = error.message;
    }
  }

  async function load() {
    const request = ++listRequest;
    clearImage();
    selected = null;
    reviews?.clear();
    reviews?.setPage([], el("scope").value || "live");
    el("title").textContent = "Crop auswählen";
    el("metadata").replaceChildren();
    el("raw").textContent = "Kein Crop ausgewählt.";
    el("image-status").textContent = "";
    el("gallery").replaceChildren();
    el("previous").disabled = true;
    el("next").disabled = true;
    el("summary").textContent = "Crops werden geladen …";
    const params = new URLSearchParams({ offset, limit: pageSize });
    params.set("scope", el("scope").value || "live");
    for (const name of ["installation", "country", "source", "query", "from", "to", "review_state", "exit_context", "class_source"]) {
      if (el(name).value) params.set(name, el(name).value);
    }
    try {
      const result = await getJSON("./api/crops?" + params);
      if (request !== listRequest) return;
      hasMore = result.has_more;
      reviews?.setPage(result.crops, el("scope").value || "live");
      el("summary").textContent = result.crops.length
        ? `${offset + 1}–${offset + result.crops.length} · neueste Aufnahmen zuerst`
        : "Keine aktiven, nicht abgelaufenen Crops für diese Filter gespeichert.";
      el("previous").disabled = offset === 0;
      el("next").disabled = !hasMore;
      for (const row of result.crops) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "crop-card";
        if (reviews) card.dataset.cropIdentity = reviews.core.key(row);
        card.setAttribute("aria-pressed", "false");
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = "Crop · " + label(row);
        img.src = row.image_url;
        const title = document.createElement("strong");
        title.textContent = label(row);
        const time = document.createElement("span");
        time.textContent = row.manifest.source_frame_at;
        const device = document.createElement("span");
        device.textContent = `${platformLabel(row.observation?.app?.platform)} · ${row.installation}`;
        const availability = document.createElement("span");
        availability.className = "hint";
        availability.textContent = `${row.manifest.decoded_width} × ${row.manifest.decoded_height} · ${row.manifest.source_kind}`;
        img.addEventListener("error", () => { img.hidden = true; availability.textContent = "Bild nicht verfügbar · Details öffnen"; });
        card.append(img, title, time, device, availability);
        if (reviews) {
          const review = document.createElement("span"); review.className = "crop-review-badge";
          review.textContent = reviews.core.reviewLabel(row.current_review);
          const context = document.createElement("span");
          const exit = typeof row.exit_context === "string" ? row.exit_context : row.exit_context?.result || row.exit_context?.status || "not_computed";
          context.textContent = reviews.core.exitLabels[exit] || exit;
          card.append(review, context);
        }
        card.addEventListener("click", () => void select(row, card));
        el("gallery").append(card);
      }
    } catch (error) {
      if (request === listRequest) el("summary").textContent = error.message;
    }
  }

  async function activate() {
    if (started) return;
    started = true;
    const request = ++activationRequest;
    try {
      const connection = await getJSON("./api/crops/status");
      if (request !== activationRequest) return;
      el("connection").textContent = `${connection.database} · ${connection.user} · ${connection.media_available ? "Bildverzeichnis verfügbar" : "Bildverzeichnis fehlt oder ist nicht lesbar"}`;
      await loadDevices();
      if (request !== activationRequest) return;
      await load();
    } catch (error) {
      if (request !== activationRequest) return;
      started = false;
      el("connection").textContent = error.message;
    }
  }

  el("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    offset = 0;
    if (!started) void activate();
    else void loadDevices().then(load).catch(error => { el("summary").textContent = error.message; });
  });
  el("previous").addEventListener("click", () => { offset = Math.max(0, offset - pageSize); void load(); });
  el("next").addEventListener("click", () => { if (hasMore) { offset += pageSize; void load(); } });
  el("show-box").addEventListener("change", displayBox);
  window.addEventListener("youspeed:mode", (event) => {
    if (event.detail === "crops") void activate();
    else {
      // Recheck availability on return; avoid retaining deleted evidence on screen.
      started = false;
      ++activationRequest;
      ++listRequest;
      ++devicesRequest;
      clearImage();
      el("gallery").replaceChildren();
      el("metadata").replaceChildren();
      el("raw").textContent = "Kein Crop ausgewählt.";
      selected = null;
      reviews?.clear();
      reviews?.setPage([], "live");
    }
  });
  window.addEventListener("pagehide", clearImage);
  if (document.body.dataset.inspectorMode === "crops") void activate();
})();
