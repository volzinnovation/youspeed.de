(function initializeSignAnnotations() {
  "use strict";
  const el = name => document.getElementById("sign-annotation-" + name);
  if (!el("editor")) return;
  const core = window.YouSpeedSignAnnotationsCore;
  const base = "/inspector/api/sign-annotations";
  const svgNS = "http://www.w3.org/2000/svg";
  const coordinates = ["left", "top", "right", "bottom"];
  let context, picture, original, draft, service, controller, serial = 0, pending = false;
  let drawing = false, start = null, requestId = null, uncertain = false, imageReady = false;
  const historyItems = [];
  let catalog = {classes: [], search: []};
  const evidence = el("editor").closest(".place-sign-evidence");
  const dirty = () => core.changed(original, draft);
  const active = () => !el("editor").hidden;
  const writable = () => service?.write_enabled === true && picture?.write_enabled !== false;
  function status(text) { el("status").textContent = text || ""; }
  function canLeave() {
    if (pending || dirty() || uncertain) {
      status(uncertain ? "Der Speicherstatus ist unklar. Bitte zuerst den Status prüfen."
        : pending ? "Speichern läuft. Bitte kurz warten."
        : "Es gibt ungespeicherte Änderungen. Bitte speichern oder verwerfen.");
      return false;
    }
    return true;
  }
  async function api(path, options = {}) {
    const response = await fetch(base + path, {cache: "no-store", ...options});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.error || "Panoramax ist derzeit nicht erreichbar.");
      error.status = response.status;
      error.uncertain = body.uncertain === true;
      throw error;
    }
    return body;
  }
  function neighbors() {
    if (!picture) return [null, null];
    if (el("mode").value === "sequence") return [picture.previous, picture.next];
    const entries = core.groupPictures(context?.observations);
    const i = entries.findIndex(item => item.image_id === picture.id);
    return i < 0 ? [null, null] : [entries[i - 1], entries[i + 1]];
  }
  function controls() {
    const [previous, next] = neighbors();
    el("previous").disabled = !previous || pending;
    el("next").disabled = !next || pending;
    el("selection").disabled = !picture || pending || uncertain;
    el("mode").disabled = pending;
    el("nearby").disabled = !picture?.nearby?.length || pending;
    const edit = Boolean(picture && draft && writable() && !pending && !uncertain);
    el("class").disabled = !edit;
    el("class-picker").disabled = !edit || !catalog.classes.length;
    const geometryEditable = !original || original.geometry_editable !== false && service?.supports_shape_edit !== false;
    coordinates.forEach(name => { el(name).disabled = !edit || !geometryEditable; });
    el("new").disabled = !picture || !writable() || pending || uncertain;
    el("redraw").disabled = !edit || !imageReady || !geometryEditable;
    el("discard").disabled = !dirty() || pending || uncertain;
    const validClass = draft && (core.classCode(draft.sign_code) || catalog.classes.some(item => item.class_id === draft.class_id));
    el("save").disabled = !uncertain && (!edit || !dirty() || !validClass
      || !core.validBox(draft.box_xyxy, picture.width, picture.height));
    el("save").textContent = uncertain ? "Speicherstatus prüfen" : pending ? "Wird gespeichert …" : "In Panoramax speichern";
    el("stage").dataset.draw = String(drawing);
  }
  function classLabel() {
    const entry = catalog.search.find(item => draft?.sign_code && item.code === draft.sign_code)
      || catalog.classes.find(item => draft?.class_id && item.class_id === draft.class_id);
    el("class-label").textContent = entry ? `${entry.label} · ${entry.code || "ohne eindeutigen StVO-Code"} · ${entry.class_id}`
      : draft?.sign_code || "Verkehrszeichen über Nummer, Namen oder TSR-Klasse auswählen.";
    el("icon").hidden = !entry?.icon;
    if (entry?.icon) { el("icon").src = entry.icon; el("icon").alt = entry.label; }
  }
  function closePickers() {
    el("suggestions").hidden = true; el("classes").hidden = true;
    el("class").setAttribute("aria-expanded", "false"); el("class-picker").setAttribute("aria-expanded", "false");
  }
  function pickClass(entry) {
    if (!draft || el("class").disabled) return;
    draft.sign_code = entry.code; draft.class_id = catalog.classes.some(item => item.class_id === entry.class_id) ? entry.class_id : null;
    closePickers(); form(); boxes();
  }
  function options(entries, target) {
    target.replaceChildren(...entries.map((entry, index) => {
      const button = document.createElement("button"); button.type = "button"; button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(draft?.class_id === entry.class_id && draft?.sign_code === entry.code));
      if (entry.icon) { const image = document.createElement("img"); image.src = entry.icon; image.alt = ""; image.loading = "lazy"; button.append(image); }
      const label = document.createElement("span"); label.textContent = `${entry.code ? entry.code.replace(/^DE:/, "") + " · " : ""}${entry.label}`;
      const detail = document.createElement("small"); detail.textContent = entry.class_id; label.append(detail); button.append(label);
      button.addEventListener("click", () => pickClass(entry));
      button.addEventListener("keydown", event => {
        if (event.key === "Escape") { closePickers(); el("class").focus(); }
        const offset = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
        if (offset) { event.preventDefault(); target.children[Math.max(0, Math.min(entries.length - 1, index + offset))]?.focus(); }
      });
      return button;
    }));
  }
  function form() {
    const entry = catalog.classes.find(item => item.class_id === draft?.class_id);
    el("class").value = draft?.sign_code || entry?.label || "";
    coordinates.forEach((name, i) => { el(name).value = draft?.box_xyxy?.[i] ?? ""; });
    classLabel(); controls();
  }
  function boxes() {
    const svg = el("stage").querySelector("svg");
    if (!svg || !picture) return;
    svg.replaceChildren();
    const entries = picture.annotations.filter(item => item.id !== original?.id);
    if (draft) entries.push({...draft, id: original?.id || "new", selected: true});
    for (const annotation of entries) {
      const box = annotation.box_xyxy;
      if (!core.validBox(box, picture.width, picture.height)) continue;
      const entry = catalog.search.find(item => annotation.sign_code && item.code === annotation.sign_code)
        || catalog.classes.find(item => annotation.class_id && item.class_id === annotation.class_id);
      const rect = document.createElementNS(svgNS, "rect");
      for (const [key, value] of Object.entries({x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1]})) rect.setAttribute(key, value);
      rect.dataset.selected = String(annotation.selected === true);
      rect.addEventListener("click", () => { if (!drawing) choose(annotation.id); });
      const label = document.createElementNS(svgNS, "text");
      label.setAttribute("x", box[0]); label.setAttribute("y", Math.max(24, box[1] - 10));
      label.setAttribute("font-size", Math.max(24, picture.width / 65));
      label.textContent = annotation.sign_code || entry?.label || annotation.class_id || "Annotation";
      svg.append(rect, label);
      if (el("show-icons").checked) {
        if (entry?.icon) {
          const icon = document.createElementNS(svgNS, "image");
          const size = Math.min(picture.width / 12, Math.max(picture.width / 45, Math.min(box[2] - box[0], box[3] - box[1]) * .8));
          icon.setAttribute("href", entry.icon); icon.setAttribute("width", size); icon.setAttribute("height", size);
          icon.setAttribute("x", (box[0] + box[2] - size) / 2); icon.setAttribute("y", (box[1] + box[3] - size) / 2);
          icon.setAttribute("pointer-events", "none"); svg.append(icon);
        }
      }
    }
  }
  function choose(id, force = false) {
    if (!force && !canLeave()) return;
    original = picture?.annotations.find(item => item.id === id) || null;
    if (original) {
      const entry = catalog.classes.find(item => item.code && item.code === original.sign_code);
      original = {...original, sign_code: original.sign_code || null, class_id: original.class_id || entry?.class_id || null};
    }
    draft = original && core.validBox(original.box_xyxy, picture.width, picture.height)
      ? {sign_code: original.sign_code, class_id: original.class_id, box_xyxy: [...original.box_xyxy]} : null;
    requestId = null; uncertain = false; drawing = false;
    el("selection").value = original?.id || "";
    closePickers(); form(); boxes();
    if (original && !draft) status("Diese Annotation verwendet keinen rechteckigen Rahmen und kann hier nur angezeigt werden.");
  }
  function drawPoint(event) {
    return picture && imageReady ? core.imagePoint(event.clientX, event.clientY,
      el("stage").getBoundingClientRect(), picture.width, picture.height) : null;
  }
  function nearbyOptions() {
    el("nearby").replaceChildren(new Option("Nach Abstand und Blickrichtung", ""), ...(picture?.nearby || []).map(item => {
      const parts = [];
      if (Number.isFinite(item.distance_m)) parts.push(`${item.distance_m.toFixed(0)} m`);
      if (Number.isFinite(item.heading_deg)) parts.push(`${item.heading_deg.toFixed(0)}°`);
      if (item.captured_at) parts.push(new Date(item.captured_at).toLocaleDateString("de-DE"));
      return new Option(parts.join(" · ") || item.id, item.id);
    }));
    controls();
  }
  function renderPicture(value) {
    if (!value || !Array.isArray(value.annotations) || !value.id || !Number.isInteger(value.width)
        || !Number.isInteger(value.height) || value.width <= 0 || value.height <= 0) throw new Error("Ungültige Bilddaten.");
    const photo = new URL(value.photo_url, window.location.origin);
    if (photo.origin !== window.location.origin || !photo.pathname.startsWith(base + "/")) throw new Error("Ungültige Bildquelle.");
    picture = value; imageReady = false;
    const image = document.createElement("img");
    image.alt = "Panoramax-Aufnahme zur Verkehrszeichenannotation";
    image.referrerPolicy = "no-referrer";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${picture.width} ${picture.height}`);
    svg.setAttribute("aria-label", "Annotationsrahmen");
    image.addEventListener("load", () => { if (image.parentNode === el("stage")) { imageReady = true; controls(); } });
    image.addEventListener("error", () => { if (image.parentNode === el("stage")) { imageReady = false; controls(); status("Die Bilddatei ist nicht verfügbar. Rahmen können erst mit sichtbarem Bild gezogen werden."); } });
    el("stage").replaceChildren(image, svg); image.src = photo.href;
    el("selection").replaceChildren(new Option("Annotation wählen", ""), ...picture.annotations.map(item => {
      const entry = catalog.classes.find(entry => entry.class_id === item.class_id);
      return new Option(item.sign_code || entry?.label || "Ohne Verkehrsschildklasse", item.id);
    }));
    nearbyOptions();
    const fields = [];
    if (Number.isFinite(picture.latitude) && Number.isFinite(picture.longitude)) fields.push(`${picture.latitude.toFixed(6)}, ${picture.longitude.toFixed(6)}`);
    if (Number.isFinite(picture.heading_deg)) fields.push(`Kurs ${picture.heading_deg.toFixed(1)}°`);
    if (picture.captured_at) fields.push(new Date(picture.captured_at).toLocaleString("de-DE"));
    fields.push(`${picture.annotations.length} Annotationen`);
    if (Number.isInteger(picture.rank)) fields.push(`Sequenzbild ${picture.rank}`);
    el("location").textContent = fields.join(" · ");
    const selected = picture.annotations.find(item => item.id === context?.observation?.annotation_id);
    choose(selected?.id || picture.annotations[0]?.id || "", true);
    window.dispatchEvent(new CustomEvent("youspeed:annotation-picture", {detail: {picture, independent: el("mode").value === "sequence"}}));
    if (picture.nearby_available && !picture.nearby?.length) {
      const token = serial, id = picture.id;
      void api("/pictures/" + id + "/nearby", {signal: controller?.signal}).then(result => {
        if (serial === token && active() && picture?.id === id) { picture.nearby = result.nearby || []; nearbyOptions(); }
      }).catch(() => {});
    }
  }
  async function loadPicture(id) {
    if (!id || !canLeave()) return;
    controller?.abort(); controller = new AbortController(); const token = ++serial;
    picture = original = draft = null; imageReady = false; drawing = false; controls();
    el("stage").replaceChildren(); el("selection").replaceChildren(); el("location").textContent = ""; form();
    status("Aktuelle Panoramax-Annotationen werden geladen …");
    try {
      if (!service || !catalog.classes.length) {
        const configuration = await api("/status", {signal: controller.signal});
        const response = await fetch("/shared/tsr/prolix-de-class-catalog-v1.json", {cache: "no-store", signal: controller.signal});
        if (!response.ok) throw new Error("Verkehrszeichenkatalog nicht verfügbar.");
        const entries = core.catalogEntries(await response.json());
        if (token !== serial || !active()) return;
        service = configuration; catalog = entries;
        options(catalog.classes, el("classes"));
        el("class-picker").textContent = `${catalog.classes.length} TSR-Klassen auswählen ▾`;
        void api("/history", {signal: controller.signal}).then(value => {
          if (token !== serial) return;
          historyItems.splice(0, historyItems.length, ...(value.corrections || []).slice(0, 100));
          record();
        }).catch(() => {});
      }
      const value = await api("/pictures/" + encodeURIComponent(id), {signal: controller.signal});
      if (token !== serial || !active()) return;
      renderPicture(value);
      status(writable() ? "Annotation auswählen oder mit „Neues Zeichen“ einen Rahmen hinzufügen."
        : service.message || "Lesemodus. Zum Speichern muss der Panoramax-Zugang am Inspector eingerichtet sein.");
    } catch (error) { if (token === serial && error.name !== "AbortError") status(error.message); }
  }
  function record(receipt) {
    if (receipt) historyItems.unshift(receipt);
    el("history").replaceChildren(...historyItems.map(item => {
      const li = document.createElement("li");
      const label = catalog.classes.find(entry => entry.class_id === item.class_id)?.label;
      li.textContent = `${item.created_at || item.timestamp || "Jetzt"} · ${item.sign_code || label || item.class_id || "Korrektur"} · ${item.status || "gespeichert"}`;
      return li;
    }));
  }
  async function save(event) {
    event.preventDefault();
    if (pending || !picture || (!uncertain && el("save").disabled)) return;
    requestId ||= crypto.randomUUID();
    const id = picture.id;
    const payload = {request_id: requestId, base_revision: picture.revision,
      annotation_id: original?.id || null, box_xyxy: draft.box_xyxy, sign_code: core.classCode(draft.sign_code), class_id: draft.class_id || null};
    pending = true; controls(); status(uncertain ? "Speicherstatus wird geprüft …" : "Korrektur wird in Panoramax gespeichert …");
    try {
      const value = await api("/pictures/" + encodeURIComponent(id) + "/annotations", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
      });
      record(value.receipt || value.correction);
      pending = false; uncertain = false; requestId = null;
      if (value.picture_sync === "refresh_required") {
        original = draft = null;
        await loadPicture(id);
        status(picture ? "In Panoramax gespeichert und Ansicht aktualisiert."
          : "In Panoramax gespeichert. Die Bildansicht konnte noch nicht aktualisiert werden; bitte erneut öffnen.");
        return;
      }
      renderPicture(value.picture || value);
      status("In Panoramax gespeichert und im Korrekturprotokoll erfasst. Gruppen und WFS beim nächsten Benchmark aktualisieren.");
    } catch (error) {
      // A lost response cannot prove that a create failed. Keep the request ID for reconciliation.
      uncertain = error.uncertain || !error.status || error.status >= 500;
      status(uncertain ? "Panoramax hat noch keinen eindeutigen Speicherstatus geliefert. „Speicherstatus prüfen“ gleicht dieselbe Korrektur ab."
        : error.status === 409 ? "Die Annotation wurde inzwischen geändert. Änderung verwerfen und Bild erneut laden, bevor Sie sie bearbeiten."
        : error.message);
    } finally { pending = false; controls(); }
  }
  function reset() {
    if (pending) return;
    controller?.abort(); serial++; context = picture = original = draft = null;
    service = null; uncertain = false; requestId = null; imageReady = false;
    el("editor").hidden = true; evidence.classList.remove("is-annotating");
    el("stage").replaceChildren(); form();
  }
  window.YouSpeedSignAnnotations = {
    canLeave,
    openPicture(id, mode = "sequence") {
      if (!canLeave()) return;
      el("editor").hidden = false; evidence.classList.add("is-annotating");
      el("mode").value = mode;
      void loadPicture(id);
    },
    select(value) {
      context = value;
      el("open").disabled = !value?.observation?.image_id || !!value?.observation?.mobile_kind;
      if (active()) void loadPicture(value?.observation?.image_id);
    },
    reset
  };
  el("open").addEventListener("click", () => {
    if (!context?.observation?.image_id) return;
    el("editor").hidden = false; evidence.classList.add("is-annotating");
    void loadPicture(context.observation.image_id);
  });
  el("close").addEventListener("click", () => {
    if (!canLeave()) return;
    controller?.abort(); serial++; el("editor").hidden = true; evidence.classList.remove("is-annotating");
    window.dispatchEvent(new CustomEvent("youspeed:annotation-close"));
  });
  el("mode").addEventListener("change", () => {
    controls();
    if (picture) window.dispatchEvent(new CustomEvent("youspeed:annotation-picture", {detail: {picture, independent: el("mode").value === "sequence"}}));
    if (el("mode").value === "sequence") status("Alle Bilder dieser Fahrt, einschließlich Bildern ohne Annotation. Pfeiltasten wechseln das Bild.");
  });
  el("nearby").addEventListener("change", () => {
    const id = el("nearby").value;
    if (!id || !canLeave()) { el("nearby").value = ""; return; }
    el("mode").value = "sequence"; void loadPicture(id);
  });
  for (const [name, index] of [["previous", 0], ["next", 1]]) el(name).addEventListener("click", () => {
    const target = neighbors()[index]; void loadPicture(target?.id || target?.image_id);
  });
  el("selection").addEventListener("change", () => {
    if (!canLeave()) { el("selection").value = original?.id || ""; return; }
    choose(el("selection").value);
    if (original && service?.supports_shape_edit === false) status("Zeichenklasse bearbeitbar. Panoramax unterstützt für bestehende Annotationen derzeit keine Rahmenänderung.");
  });
  el("new").addEventListener("click", () => {
    if (!canLeave()) return;
    const previous = draft;
    original = null; draft = {sign_code: previous?.sign_code || null, class_id: previous?.class_id || null, box_xyxy: []};
    drawing = true; requestId = null; el("selection").value = ""; form(); boxes();
    status("Rahmen um das neue Zeichen ziehen und die Verkehrszeichenklasse angeben.");
  });
  el("redraw").addEventListener("click", () => { drawing = true; controls(); status("Neuen Rahmen für die ausgewählte Annotation ziehen."); });
  el("discard").addEventListener("click", () => { choose(original?.id || "", true); status("Ungespeicherte Änderung verworfen."); });
  el("class").addEventListener("input", () => {
    if (!draft) return;
    const value = el("class").value.trim();
    const code = core.classCode(/^\d/.test(value) ? "DE:" + value : value);
    const exact = (code && catalog.search.find(item => item.code === code)) || catalog.classes.find(item => item.label.toLowerCase() === value.toLowerCase());
    draft.sign_code = exact?.code || code; draft.class_id = exact && catalog.classes.some(item => item.class_id === exact.class_id) ? exact.class_id : null;
    const entries = core.searchClasses(catalog.search, value);
    options(entries, el("suggestions")); el("suggestions").hidden = !entries.length; el("classes").hidden = true;
    el("class").setAttribute("aria-expanded", String(!!entries.length)); el("class-picker").setAttribute("aria-expanded", "false");
    classLabel(); boxes(); controls();
  });
  el("class").addEventListener("keydown", event => {
    if (event.key === "ArrowDown" && !el("suggestions").hidden) { event.preventDefault(); el("suggestions").children[0]?.focus(); }
    if (event.key === "Escape") closePickers();
    if (event.key === "Enter" && !el("suggestions").hidden) { event.preventDefault(); el("suggestions").children[0]?.click(); }
  });
  el("class-picker").addEventListener("click", () => {
    const hidden = !el("classes").hidden; closePickers(); el("classes").hidden = hidden;
    el("class-picker").setAttribute("aria-expanded", String(!hidden));
    if (!hidden) { options(catalog.classes, el("classes")); el("classes").children[0]?.focus(); }
  });
  el("show-icons").addEventListener("change", boxes);
  coordinates.forEach(name => el(name).addEventListener("input", () => {
    if (draft) { draft.box_xyxy = coordinates.map(key => el(key).value === "" ? NaN : Number(el(key).value)); boxes(); controls(); }
  }));
  el("stage").addEventListener("pointerdown", event => {
    if (!drawing || !writable() || pending || uncertain || event.button !== 0) return;
    start = drawPoint(event); if (start) { el("stage").setPointerCapture(event.pointerId); event.preventDefault(); }
  });
  el("stage").addEventListener("pointermove", event => {
    if (!start || !drawing) return;
    const box = core.dragBox(start, drawPoint(event), picture.width, picture.height);
    if (box) { draft.box_xyxy = box; form(); boxes(); }
  });
  el("stage").addEventListener("pointerup", event => {
    if (!start) return;
    const box = core.dragBox(start, drawPoint(event), picture.width, picture.height);
    start = null;
    if (box) { draft.box_xyxy = box; drawing = false; form(); boxes(); status("Rahmen gesetzt. Klasse prüfen und in Panoramax speichern."); }
  });
  el("stage").addEventListener("pointercancel", () => { start = null; });
  el("form").addEventListener("submit", save);
  window.addEventListener("keydown", event => {
    if (!active() || event.altKey || event.ctrlKey || event.metaKey || /INPUT|SELECT|TEXTAREA/.test(event.target?.tagName)) return;
    const name = event.key === "ArrowLeft" ? "previous" : event.key === "ArrowRight" ? "next" : null;
    if (name && !el(name).disabled) { event.preventDefault(); el(name).click(); }
  });
  window.addEventListener("beforeunload", event => { if (dirty() || pending || uncertain) { event.preventDefault(); event.returnValue = ""; } });
})();
