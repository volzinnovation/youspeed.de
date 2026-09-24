(function () {
  "use strict";
  const core = window.YouSpeedTrackVideo, bridge = window.YouSpeedInspectorBridge;
  const el = id => document.getElementById("track-video" + (id ? "-" + id : ""));
  const video = el("");
  let url = null, file = null, start = null, version = 0, reverse = null, pendingTime = null, cursor = null;
  let fixes = [];
  const status = text => { el("status").textContent = text; };
  function stopReverse() { clearInterval(reverse); reverse = null; el("reverse").setAttribute("aria-pressed", "false"); }
  function update() {
    const time = start == null ? null : start + video.currentTime * 1000;
    el("clock").textContent = "Video " + video.currentTime.toFixed(3) + " s / " + (video.duration || 0).toFixed(1) + " s" +
      (time == null ? " · Zeitabgleich fehlt" : " · " + new Date(time).toISOString());
    let lo = 0, hi = fixes.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (fixes[mid].time < time) lo = mid + 1; else hi = mid; }
    const nearest = time == null ? null : [fixes[lo - 1], fixes[lo]].filter(Boolean).sort((a,b) => Math.abs(a.time-time)-Math.abs(b.time-time))[0];
    if (nearest && Math.abs(nearest.time - time) <= 2000) {
      if (!cursor) cursor = L.circleMarker([nearest.lat, nearest.lon], {radius: 8, color: "#fff", fillColor: "#5da9ff", fillOpacity: 1, weight: 3}).addTo(bridge.trackMap);
      else cursor.setLatLng([nearest.lat, nearest.lon]);
      cursor.bindTooltip("Dashcam · " + new Date(time).toLocaleTimeString());
    } else { cursor?.remove(); cursor = null; }
  }
  function seekTimestamp(time) {
    if (!file || !Number.isFinite(time)) return;
    pendingTime = time;
    if (video.readyState < 1) return;
    stopReverse(); video.pause();
    const seconds = core.videoTime(time, start, video.duration);
    if (seconds == null) {
      video.style.visibility = "hidden"; cursor?.remove(); cursor = null;
      status(start == null ? "Zeitabgleich fehlt: Videostart mit Zeitzone eingeben." :
        "Ausgewählter Zeitpunkt liegt außerhalb dieses Videos. Kein passendes Videobild.");
      return;
    }
    video.style.visibility = "visible";
    video.currentTime = seconds;
    status("Zum ausgewählten Zeitpunkt: " + new Date(time).toISOString());
  }
  function step(delta) {
    stopReverse(); video.pause();
    if (!Number.isFinite(video.duration)) return;
    video.style.visibility = "visible";
    video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + delta));
    status("Manuelle Videoprüfung");
  }
  function clear(resetInput = true) {
    ++version; stopReverse(); video.pause(); video.removeAttribute("src"); video.load();
    if (url) URL.revokeObjectURL(url);
    url = null; file = null; start = null; pendingTime = null;
    video.style.visibility = "visible"; video.playbackRate = 1;
    cursor?.remove(); cursor = null;
    el("content").hidden = true; el("clear").disabled = true; if (resetInput) el("file").value = ""; el("start").value = "";
    el("source").textContent = ""; el("fps").value = "30"; el("rate").value = "1";
    bridge.invalidateMap();
  }
  el("file").addEventListener("change", async event => {
    const next = event.target.files?.[0]; if (!next) return;
    clear(false); file = next;
    const token = version;
    url = URL.createObjectURL(next); video.src = url;
    el("content").hidden = false; el("clear").disabled = false; bridge.invalidateMap();
    status(next.name + " · wird lokal geöffnet …");
    try {
      const metadataStart = await core.movieStart(next);
      if (token !== version) return;
      start = metadataStart;
      el("start").value = start == null ? "" : new Date(start).toISOString();
      el("source").textContent = start == null ? "Kein UTC-Start im Container. Videostart manuell eingeben oder Zeitdatei laden." :
        "Start aus QuickTime-Metadaten (sekundengenau; Aufnahmeverzögerung prüfen). Bildrate zunächst 30; bei Bedarf korrigieren.";
      update();
      if (pendingTime != null) seekTimestamp(pendingTime);
    } catch (error) { if (token === version) status("Metadaten: " + error.message + " Videostart manuell eingeben."); }
  });
  el("clear").addEventListener("click", () => { clear(); status("Video entfernt."); });
  el("start").addEventListener("change", () => {
    start = core.utc(el("start").value);
    el("source").textContent = start == null ? "Ungültiger ISO-Zeitstempel: Zeitzone Z oder ±HH:MM erforderlich." : "Manueller Zeitabgleich.";
    update(); if (pendingTime != null) seekTimestamp(pendingTime);
  });
  el("alignment").addEventListener("change", async event => {
    const input = event.target.files?.[0], token = version;
    if (!input || !file) return;
    try {
      const data = JSON.parse(await input.text());
      if (token !== version) return;
      const next = core.alignment(data, file.name);
      start = next.start; el("start").value = new Date(start).toISOString(); el("fps").value = next.fps;
      el("source").textContent = next.source; update();
      if (pendingTime != null) seekTimestamp(pendingTime);
      else status("Zeitdatei geladen.");
    } catch(error) { status(error.message); }
    finally { el("alignment").value = ""; }
  });
  el("back").addEventListener("click", () => step(-5));
  el("forward").addEventListener("click", () => step(5));
  function frame(direction) {
    const fps = Number(el("fps").value);
    if (!Number.isFinite(fps) || fps < 1 || fps > 240) { status("Gültige Bildrate (1–240) eingeben."); return; }
    step(direction / fps);
  }
  el("prev-frame").addEventListener("click", () => frame(-1));
  el("next-frame").addEventListener("click", () => frame(1));
  el("play").addEventListener("click", async () => {
    stopReverse();
    if (!video.paused) video.pause();
    else { video.style.visibility = "visible"; try { await video.play(); } catch (e) { status("Wiedergabe nicht möglich: " + e.message); } }
  });
  el("reverse").addEventListener("click", () => {
    if (reverse) { stopReverse(); return; }
    video.style.visibility = "visible"; video.pause(); el("reverse").setAttribute("aria-pressed", "true");
    // Browsers do not reliably support negative playbackRate. Seek backwards,
    // waiting for each previous seek to finish rather than queuing decoder work.
    reverse = setInterval(() => {
      if (video.currentTime <= 0 || !Number.isFinite(video.duration)) { stopReverse(); return; }
      if (!video.seeking) video.currentTime = Math.max(0, video.currentTime - .25 * Number(el("rate").value));
    }, 250);
    status("Rücklauf in kurzen Schritten (ohne Ton).");
  });
  el("rate").addEventListener("change", () => { video.playbackRate = Number(el("rate").value); });
  video.addEventListener("play", stopReverse);
  video.addEventListener("timeupdate", update);
  video.addEventListener("seeked", update);
  video.addEventListener("loadedmetadata", () => {
    if (!file) return;
    update(); if (pendingTime != null) seekTimestamp(pendingTime);
    else status(file.name + " · " + video.duration.toFixed(1) + " s");
  });
  video.addEventListener("error", () => status("Video kann im Browser nicht dekodiert werden. MOV/HEVC ggf. lokal nach H.264/MP4 konvertieren; Zeitabgleich beibehalten."));
  window.addEventListener("inspector:tsr-select", e => {
    seekTimestamp(e.detail.time);
    if (!file || !Number.isFinite(e.detail.time) || e.detail.revealVideo === false) return;
    // Reveal inside both the scrolling video pane and a narrow page layout.
    // Passive filter rerenders must not move the reader away from the filters.
    const target = video.style.visibility === "hidden" ? el("status") : video;
    target.scrollIntoView({block: "nearest", inline: "nearest"});
    target.focus({preventScroll: true});
  });
  window.addEventListener("inspector:drive-fix", e => seekTimestamp(e.detail.time));
  window.addEventListener("inspector:drive-log", () => {
    fixes = bridge.getDriveEntries().map(e => ({time: Date.parse(e.timestampUTC), lat: e.lat, lon: e.lon}))
      .filter(e => [e.time,e.lat,e.lon].every(Number.isFinite)).sort((a,b) => a.time-b.time);
    pendingTime = null; update();
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { stopReverse(); video.pause(); } });
})();
