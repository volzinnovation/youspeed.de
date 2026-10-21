(function () {
  "use strict";
  const core = window.YouSpeedLaneCore, zip = window.YouSpeedLaneZip;
  const el = id => document.getElementById("lane-" + id);
  const canvas = el("canvas"), ctx = canvas.getContext("2d"), video = document.getElementById("track-video");
  const stage = video.parentElement, controller = window.YouSpeedTrackVideoController;
  const uuid = () => crypto.randomUUID();
  let dataset = core.create(uuid()), images = new Map(), source = null, current = null, bitmap = null;
  let session = null, sessionSource = null, active = false, busy = false, selected = null, adding = null, drag = null;
  let zoom = 1, request = 0, undo = new Map(), redo = new Map(), pendingSave = Promise.resolve(), db = null;
  let requestAbort = null;
  let datasetBusy = false;
  let restored = false, restoreFailed = false;
  let savePending = 0, backupFailed = false;
  const status = (text, error = false) => { el("status").textContent = text; el("status").dataset.error = String(error); };
  const blobJSON = data => new Blob([JSON.stringify(data, null, 2) + "\n"], {type: "application/json"});
  async function digest(blob) { return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())), b => b.toString(16).padStart(2, "0")).join(""); }
  async function response(res) {
    if (!res.ok) { const error = await res.json().catch(() => ({})); throw new Error(error.error || `HTTP ${res.status}`); }
    return res;
  }
  function option(select, value, label) { const o = document.createElement("option"); o.value = value; o.textContent = label; select.append(o); }
  function options(select, placeholder) { select.replaceChildren(); option(select, "", placeholder); }
  function sample() { return dataset.samples.find(s => s.id === current); }
  function history(map, id) { if (!map.has(id)) map.set(id, []); return map.get(id); }
  function snapshot() { return core.clone(sample()); }
  function save() {
    if (!db || !restored || restoreFailed) return;
    const record = {dataset: core.clone(dataset), images: Array.from(images)};
    savePending++;
    pendingSave = pendingSave.catch(() => {}).then(() => new Promise((resolve, reject) => {
      const tx = db.transaction("workspace", "readwrite");
      tx.objectStore("workspace").put(record, "current");
      tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error || new Error("Speicherfehler"));
    }));
    pendingSave.then(() => { savePending--; backupFailed = false; }, () => {
      savePending--; backupFailed = true;
      status("Lokale Sicherung fehlgeschlagen (Speicherlimit). Dataset jetzt als ZIP exportieren.", true);
    });
  }
  function replaceSample(replacement) {
    const at = dataset.samples.findIndex(s => s.id === replacement.id);
    dataset.samples[at] = replacement;
  }
  function mutate(fn, prior = snapshot()) {
    try {
      fn(sample());
      history(undo, current).push(prior);
      if (history(undo, current).length > 50) history(undo, current).shift();
      redo.set(current, []); save(); render();
    } catch (error) { replaceSample(prior); status(error.message, true); render(false); }
  }
  function travel(from, to) {
    if (!current || busy) return;
    const stack = history(from, current); if (!stack.length) return;
    history(to, current).push(snapshot());
    const next = stack.pop(), revision = sample().revision;
    next.revision = revision; core.edited(next); replaceSample(next);
    selected = next.curves.some(c => c.id === selected) ? selected : null;
    save(); render();
  }
  function rectangle() {
    const b = canvas.getBoundingClientRect();
    const rect = core.fitRect(b.width, b.height, source.width, source.height);
    rect.width *= zoom; rect.height *= zoom; rect.x = (b.width - rect.width) / 2; rect.y = (b.height - rect.height) / 2;
    return rect;
  }
  function draw() {
    if (!active || !source || !bitmap) return;
    const box = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
    const width = Math.round(box.width * ratio), height = Math.round(box.height * ratio);
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.fillStyle = "#000"; ctx.fillRect(0, 0, box.width, box.height);
    const rect = rectangle(), screen = p => [rect.x + p[0] * rect.width, rect.y + p[1] * rect.height];
    ctx.drawImage(bitmap, rect.x, rect.y, rect.width, rect.height);
    for (const curve of sample()?.curves ?? []) {
      const points = curve.controlPoints.map(screen), isSelected = curve.id === selected;
      ctx.strokeStyle = isSelected ? "#64e6ff" : "#ffe064"; ctx.lineWidth = isSelected ? 3 : 2;
      ctx.setLineDash(curve.marking === "dashed" ? [10, 8] : []);
      ctx.beginPath(); ctx.moveTo(...points[0]); ctx.bezierCurveTo(...points[1], ...points[2], ...points[3]); ctx.stroke();
      if (isSelected) {
        ctx.setLineDash([3, 4]); ctx.lineWidth = 1; ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke();
        ctx.setLineDash([]);
        points.forEach((p, i) => { ctx.fillStyle = i === 0 || i === 3 ? "#64e6ff" : "#fff"; ctx.beginPath(); ctx.arc(...p, 5, 0, Math.PI*2); ctx.fill(); });
      }
    }
    ctx.setLineDash([]); ctx.fillStyle = "#64e6ff";
    for (const p of adding ?? []) { ctx.beginPath(); ctx.arc(...screen(p), 5, 0, Math.PI*2); ctx.fill(); }
  }
  function render(announce = true) {
    const s = sample();
    const ordered = [...dataset.samples].sort((a,b) => a.sourceId.localeCompare(b.sourceId) || a.frameIndex - b.frameIndex);
    options(el("samples"), `${dataset.samples.length} gespeicherte Frames`);
    for (const item of ordered) option(el("samples"), item.id,
      `${dataset.sources.find(v => v.id === item.sourceId).name} · Frame ${item.frameIndex} · ${item.status === "reviewed" ? "geprüft" : "Entwurf"}`);
    el("samples").value = current ?? "";
    el("editor").hidden = !active; el("exit").disabled = !active || busy;
    el("open").disabled = busy; el("import").disabled = busy; el("export").disabled = busy || !dataset.samples.length;
    el("new").disabled = busy;
    if (!s || !active) return;
    el("frame").value = s.frameIndex; el("frame").max = source.frames.length - 1;
    el("position").textContent = `${s.frameIndex + 1} / ${source.frames.length} · ${s.timeSeconds.toFixed(6)} s · PTS ${s.pts} · ${s.status === "reviewed" ? "Geprüft" : "ENTWURF"}`;
    el("group").value = source.groupId; el("split").value = source.split;
    options(el("curves"), "Kurve auswählen");
    s.curves.forEach((c, i) => option(el("curves"), c.id, `${i+1} · ${c.marking === "solid" ? "durchgezogen" : "gestrichelt"} · Track ${c.trackId.slice(0,8)}`));
    el("curves").value = selected ?? "";
    const curve = s.curves.find(c => c.id === selected);
    if (curve) el("marking").value = curve.marking;
    options(el("track"), "Track auswählen");
    const tracks = new Map();
    for (const item of ordered.filter(item => item.sourceId === source.id)) for (const c of item.curves) {
      if (!tracks.has(c.trackId)) tracks.set(c.trackId, item.frameIndex);
    }
    for (const [trackId, index] of tracks) option(el("track"), trackId, `${trackId.slice(0,8)} · ab Frame ${index}`);
    el("track").value = curve?.trackId ?? "";
    const priorChoice = el("prior").value;
    options(el("prior"), "Vorheriger annotierter Frame");
    for (const item of ordered.filter(item => item.sourceId === source.id && item.frameIndex < s.frameIndex && item.curves.length).reverse())
      option(el("prior"), item.id, `Frame ${item.frameIndex} · ${item.status === "reviewed" ? "geprüft" : "Entwurf"}`);
    if (Array.from(el("prior").options).some(o => o.value === priorChoice)) el("prior").value = priorChoice;
    for (const name of ["add", "confirm", "clear", "copy", "group-save"]) el(name).disabled = busy;
    for (const name of ["delete", "unlink", "track"]) el(name).disabled = busy || !curve;
    el("undo").disabled = busy || !history(undo, current).length;
    el("redo").disabled = busy || !history(redo, current).length;
    el("copy").disabled = busy || s.curves.length > 0 || s.status === "reviewed" || el("prior").options.length < 2;
    el("add").textContent = adding ? `Punkt ${adding.length+1} / 4 · Esc abbrechen` : "Neue Kurve · 4 Punkte";
    if (announce) status(s.status === "reviewed" ? `Frame ${s.frameIndex} geprüft (${s.curves.length} Markierungen).` :
      `Frame ${s.frameIndex}: Entwurf (${s.curves.length} Markierungen)${s.draftFrom ? ` aus Frame ${dataset.samples.find(p => p.id === s.draftFrom.sampleId)?.frameIndex}` : ""}. Vor Verwendung prüfen und bestätigen.`);
    draw();
  }
  function editing(enabled) {
    active = enabled;
    document.getElementById("track-video-panel").classList.toggle("lane-annotating", enabled);
    stage.classList.toggle("lane-editing", enabled); canvas.hidden = !enabled;
    if (enabled) {
      controller.pause(); document.getElementById("track-video-content").hidden = false;
    } else if (!controller.getFile()) document.getElementById("track-video-content").hidden = true;
    for (const id of ["back", "forward", "reverse", "play", "rate"]) document.getElementById("track-video-"+id).disabled = enabled;
    el("editor").hidden = !enabled; el("exit").disabled = !enabled;
  }
  function deactivate() {
    requestAbort?.abort(); requestAbort = null;
    ++request; busy = datasetBusy; adding = null;
    if (drag) { replaceSample(drag.before); drag = null; }
    editing(false); render(false);
  }
  async function show(index, nextSource = source) {
    if (busy || !nextSource || !Number.isInteger(index) || index < 0 || index >= nextSource.frames.length) return;
    if (drag) return;
    const token = ++request, id = core.sampleId(nextSource, index);
    requestAbort = new AbortController();
    busy = true; adding = null; status(`Frame ${index} wird exakt dekodiert …`); render(false);
    try {
      let blob = images.get(id);
      if (!blob) {
        if (sessionSource !== nextSource.id || !session) throw new Error("Für diesen Frame das ursprüngliche Video wählen und „Video annotieren“ starten.");
        const res = await response(await fetch(`/inspector/api/lanes/video/${session}/frames/${index}`, {signal: requestAbort.signal}));
        blob = await res.blob();
      }
      const nextBitmap = await createImageBitmap(blob);
      if (nextBitmap.width !== nextSource.width || nextBitmap.height !== nextSource.height) { nextBitmap.close(); throw new Error("Frame-Geometrie stimmt nicht."); }
      const hash = await digest(blob);
      if (token !== request) { nextBitmap.close(); return; }
      const existing = dataset.samples.find(s => s.id === id);
      if (existing && (hash !== existing.image.sha256 || blob.size !== existing.image.byteLength)) { nextBitmap.close(); throw new Error("Frame-Bild stimmt nicht mit dem gespeicherten Sample überein."); }
      source = nextSource; current = id; selected = null;
      bitmap?.close(); bitmap = nextBitmap; images.set(id, blob);
      if (!existing) dataset.samples.push(core.createSample(source, index, {path: `images/${id}.png`, sha256: hash, byteLength: blob.size}));
      editing(true);
      if (sessionSource === source.id && controller.getFile()) controller.showTime(source.frames[index].timeSeconds);
      save(); busy = false; requestAbort = null; render();
    } catch (error) { if (token === request) { busy = false; requestAbort = null; render(false); status(error.message, true); } }
  }
  async function closeSession() {
    if (!session) return;
    const token = session; session = null; sessionSource = null;
    await fetch(`/inspector/api/lanes/video/${token}`, {method: "DELETE"}).catch(() => {});
  }
  el("open").addEventListener("click", async () => {
    await ready;
    const file = controller.getFile(); if (!file) { status("Zuerst ein Dashcam-Video wählen.", true); return; }
    if (busy) return;
    controller.pause(); busy = true; render(false);
    const token = ++request;
    status("Video wird an den lokalen Decoder übertragen und Frame für Frame indexiert …");
    try {
      await closeSession();
      if (token !== request || controller.getFile() !== file) return;
      requestAbort = new AbortController();
      const data = await (await response(await fetch("/inspector/api/lanes/video", {method: "POST", headers: {
        "Content-Type": "application/octet-stream", "X-Video-Name": encodeURIComponent(file.name)}, body: file, signal: requestAbort.signal}))).json();
      if (token !== request || controller.getFile() !== file) {
        await fetch(`/inspector/api/lanes/video/${data.session}`, {method: "DELETE"}); return;
      }
      session = data.session; sessionSource = data.source.id;
      source = core.addSource(dataset, data.source);
      // Verify the same bytes still decode into the imported geometry and frame index.
      if (["width", "height", "byteLength", "timeBase", "startPts", "sourceRotation", "transform"].some(key => source[key] !== data.source[key]) ||
          source.frames.length !== data.source.frames.length || source.frames.some((frame, index) =>
            ["index", "pts", "timeSeconds"].some(key => frame[key] !== data.source.frames[index][key])))
        throw new Error("Decoder-Index weicht vom gespeicherten Dataset ab.");
      busy = false;
      const time = video.currentTime;
      let index = 0; while (index+1 < source.frames.length && source.frames[index+1].timeSeconds <= time) index++;
      await show(index);
    } catch (error) { if (token === request) { busy = false; requestAbort = null; render(false); status(error.message, true); } }
  });
  el("exit").addEventListener("click", deactivate);
  el("new").addEventListener("click", async () => {
    await ready;
    if (busy || drag) return;
    if (dataset.samples.length && !window.confirm("Neues Dataset starten? Vorhandene Annotationen vorher als ZIP exportieren. Die lokale Sicherung wird ersetzt.")) return;
    datasetBusy = true; deactivate(); render(false); await closeSession();
    dataset = core.create(uuid()); images = new Map(); current = null; source = null;
    bitmap?.close(); bitmap = null; undo.clear(); redo.clear(); restoreFailed = false;
    save(); datasetBusy = false; busy = false; render(false); status("Neues Dataset bereit. Dashcam wählen und „Video annotieren“ starten.");
  });
  el("frame").addEventListener("change", () => {
    const index = Number(el("frame").value);
    if (!source || !Number.isInteger(index) || index < 0 || index >= source.frames.length || !el("frame").value.trim()) {
      render(false); status("Gültige Frame-Nummer innerhalb des Videos eingeben.", true); return;
    }
    return show(index);
  });
  el("samples").addEventListener("change", () => {
    const s = dataset.samples.find(s => s.id === el("samples").value);
    if (s) show(s.frameIndex, dataset.sources.find(v => v.id === s.sourceId));
  });
  el("zoom").addEventListener("change", () => { zoom = Number(el("zoom").value); draw(); });
  el("add").addEventListener("click", () => { adding = []; selected = null; render(); canvas.focus(); });
  el("curves").addEventListener("change", () => { selected = el("curves").value || null; adding = null; render(); });
  el("marking").addEventListener("change", () => {
    if (selected && !busy) mutate(s => { s.curves.find(c => c.id === selected).marking = el("marking").value; core.edited(s); });
  });
  el("delete").addEventListener("click", () => {
    if (selected && !busy) mutate(s => { s.curves = s.curves.filter(c => c.id !== selected); selected = null; core.edited(s); });
  });
  el("undo").addEventListener("click", () => travel(undo, redo));
  el("redo").addEventListener("click", () => travel(redo, undo));
  el("track").addEventListener("change", () => { if (selected && el("track").value && !busy) mutate(s => core.link(s, selected, el("track").value)); });
  el("unlink").addEventListener("click", () => { if (selected && !busy) mutate(s => core.link(s, selected, uuid())); });
  el("copy").addEventListener("click", () => {
    if (busy) return;
    const priorId = el("prior").value || el("prior").options[1]?.value;
    const prior = dataset.samples.find(s => s.id === priorId);
    if (prior) mutate(s => core.copyDraft(prior, s, uuid));
  });
  el("clear").addEventListener("click", () => {
    if (!busy && sample() && window.confirm("Alle Kurven dieses Frames löschen und als Entwurf markieren? Dies erlaubt anschließend eine neue Vorlage."))
      mutate(s => { s.curves = []; s.draftFrom = null; selected = null; core.edited(s); });
  });
  el("confirm").addEventListener("click", () => { if (!busy && sample()) { adding = null; mutate(s => core.confirm(s)); } });
  el("group-save").addEventListener("click", () => {
    try { core.setGroup(dataset, source.id, el("group").value.trim(), el("split").value); save(); render(); }
    catch (error) { status(error.message, true); }
  });
  canvas.addEventListener("pointerdown", event => {
    if (!active || busy || !bitmap || event.button !== 0) return;
    canvas.focus();
    const box = canvas.getBoundingClientRect(), rect = rectangle();
    const x = event.clientX - box.left, y = event.clientY - box.top, point = core.pointAt(x, y, rect);
    if (!point) return;
    if (adding) {
      adding.push(point);
      if (adding.length === 4) {
        const controlPoints = adding; adding = null;
        mutate(s => { const curve = {id: uuid(), trackId: uuid(), degree: 3, controlPoints, marking: el("marking").value, copiedFrom: null};
          s.curves.push(curve); selected = curve.id; core.edited(s); });
      } else render();
      return;
    }
    const distance = p => Math.hypot(rect.x + p[0]*rect.width - x, rect.y + p[1]*rect.height - y);
    let hit = null;
    for (const c of [...sample().curves].sort((a,b) => Number(b.id === selected)-Number(a.id === selected))) {
      const handle = c.controlPoints.findIndex(p => distance(p) < 10);
      if (handle >= 0) { hit = {curve: c, handle}; break; }
    }
    if (hit) {
      selected = hit.curve.id; drag = {before: snapshot(), id: selected, handle: hit.handle, pointerId: event.pointerId};
      canvas.setPointerCapture(event.pointerId); render();
    } else {
      selected = sample().curves.find(c => Array.from({length: 65}, (_, i) => core.evaluate(c.controlPoints, i/64)).some(p => distance(p) < 9))?.id ?? null;
      render();
    }
  });
  canvas.addEventListener("pointermove", event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const box = canvas.getBoundingClientRect();
    sample().curves.find(c => c.id === drag.id).controlPoints[drag.handle] = core.pointAt(event.clientX-box.left, event.clientY-box.top, rectangle(), true);
    draw();
  });
  function finishDrag(event, cancel) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const before = drag.before; drag = null;
    if (cancel) { replaceSample(before); render(); }
    else if (JSON.stringify(before.curves) !== JSON.stringify(sample().curves)) mutate(s => core.edited(s), before);
    canvas.releasePointerCapture(event.pointerId);
  }
  canvas.addEventListener("pointerup", e => finishDrag(e, false));
  canvas.addEventListener("pointercancel", e => finishDrag(e, true));
  function step(direction) { if (active && !busy && sample()) return show(sample().frameIndex + direction); }
  document.addEventListener("keydown", event => {
    if (!active || busy || !el("panel").open || !stage.closest("main") || stage.closest("main").hidden ||
        ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) || event.target.isContentEditable) return;
    if (![canvas, el("panel"), document.querySelector('.track-video-toolbar[aria-label="Videosteuerung"]')]
      .some(parent => parent === event.target || parent?.contains(event.target))) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); step(event.key === "ArrowLeft" ? -1 : 1); }
    else if (event.key === "Escape") { adding = null; render(); }
    else if (event.key === "Delete") { event.preventDefault(); el("delete").click(); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); travel(event.shiftKey ? redo : undo, event.shiftKey ? undo : redo); }
  });
  new ResizeObserver(draw).observe(stage);
  el("export").addEventListener("click", async () => {
    await ready; if (busy || !dataset.samples.length || drag) return;
    datasetBusy = true; busy = true; render(false); status("Dataset mit PNGs, Annotationen und Splits wird gepackt …");
    try {
      core.validate(dataset);
      const files = [["manifest.json", blobJSON(dataset)]];
      for (const [split, ids] of Object.entries(core.splitManifests(dataset))) files.push([`splits/${split}.json`, blobJSON(ids)]);
      for (const s of dataset.samples) {
        const image = images.get(s.id);
        if (!image || image.size !== s.image.byteLength || await digest(image) !== s.image.sha256) throw new Error("Ein annotiertes Frame-Bild fehlt oder ist beschädigt.");
        files.push([s.image.path, image]);
      }
      const archive = await zip.pack(files), url = URL.createObjectURL(archive), a = document.createElement("a");
      a.href = url; a.download = `lane-dataset-${dataset.id}.zip`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      status(`${dataset.samples.length} Frames exportiert. Entwürfe sind gespeichert, aber aus den Trainings-/Evaluations-Splits ausgeschlossen.`);
    } catch (error) { status(error.message, true); }
    finally { datasetBusy = false; busy = false; render(false); }
  });
  el("import").addEventListener("change", async event => {
    await ready;
    const input = event.target.files?.[0]; if (!input || busy || drag) return;
    if (dataset.samples.length && !window.confirm("Aktuelles Dataset durch importiertes Dataset ersetzen? Vorher als ZIP exportieren, wenn es erhalten bleiben soll.")) { el("import").value = ""; return; }
    datasetBusy = true; busy = true; render(false); status("Dataset und Bildintegrität werden geprüft …");
    try {
      const files = await zip.unpack(input), manifest = files.get("manifest.json");
      if (!manifest) throw new Error("Dataset-Manifest fehlt.");
      const next = core.validate(JSON.parse(await manifest.text())), nextImages = new Map();
      const splits = core.splitManifests(next);
      for (const split of core.SPLITS) {
        const file = files.get(`splits/${split}.json`);
        if (!file || JSON.stringify(JSON.parse(await file.text())) !== JSON.stringify(splits[split])) throw new Error("Split-Manifest stimmt nicht mit geprüften Samples überein.");
      }
      for (const s of next.samples) {
        const blob = files.get(s.image.path);
        if (!blob || blob.size !== s.image.byteLength || await digest(blob) !== s.image.sha256) throw new Error("Frame-Bild fehlt oder SHA-256 stimmt nicht.");
        const decoded = await createImageBitmap(blob);
        const ok = decoded.width === s.width && decoded.height === s.height; decoded.close();
        if (!ok) throw new Error("PNG-Geometrie stimmt nicht.");
        nextImages.set(s.id, blob);
      }
      if (files.size !== next.samples.length + 4) throw new Error("Unerwartete Dateien im Dataset.");
      deactivate(); dataset = next; images = nextImages; current = null; source = null; undo.clear(); redo.clear(); restoreFailed = false;
      save(); render(false); status(`${dataset.samples.length} Frames importiert. Gespeicherten Frame öffnen oder Originalvideo erneut wählen.`);
    } catch (error) { status(error.message, true); }
    finally { datasetBusy = false; busy = false; el("import").value = ""; render(false); }
  });
  const ready = new Promise(resolve => {
    if (!window.indexedDB) { restored = true; status("Lokale Browsersicherung nicht verfügbar. Dataset vor dem Schließen exportieren.", true); resolve(); return; }
    const opening = indexedDB.open("youspeed-lane-annotations-v1", 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore("workspace");
    opening.onerror = () => { restored = true; status("Lokale Browsersicherung nicht verfügbar. Dataset als ZIP exportieren.", true); resolve(); };
    opening.onsuccess = () => {
      db = opening.result;
      const reading = db.transaction("workspace").objectStore("workspace").get("current");
      reading.onsuccess = () => {
        try {
          if (reading.result) { dataset = core.validate(reading.result.dataset); images = new Map(reading.result.images); render(false); status(`${dataset.samples.length} Frames lokal wiederhergestellt. Originalvideo wählen oder gespeicherten Frame öffnen.`); }
        } catch (error) { restoreFailed = true; status("Lokale Sicherung beschädigt. ZIP importieren; bestehende Sicherung wird nicht überschrieben.", true); }
        restored = true; resolve();
      };
      reading.onerror = () => { restored = true; restoreFailed = true; status("Lokale Sicherung nicht lesbar. ZIP importieren.", true); resolve(); };
    };
  });
  window.YouSpeedLaneAnnotations = {isActive: () => active, step, deactivate,
    closeVideo: () => { deactivate(); closeSession(); }};
  window.addEventListener("beforeunload", event => {
    if (busy || drag || savePending || (dataset.samples.length && (!db || restoreFailed || backupFailed))) { event.preventDefault(); event.returnValue = ""; }
  });
  window.addEventListener("pagehide", () => {
    if (session) fetch(`/inspector/api/lanes/video/${session}`, {method: "DELETE", keepalive: true}).catch(() => {});
  });
  render(false);
})();
