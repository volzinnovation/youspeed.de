/* Bounded local QuickTime/MP4 metadata reads and UTC/video clock conversion. */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.YouSpeedTrackVideo = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const epoch = Date.UTC(1904, 0, 1);
  function utc(value) {
    if (typeof value !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
    const time = Date.parse(value);
    return Number.isFinite(time) ? time : null;
  }
  function videoTime(time, start, duration) {
    if (![time, start, duration].every(Number.isFinite) || duration <= 0) return null;
    const seconds = (time - start) / 1000;
    return seconds >= 0 && seconds <= duration ? seconds : null;
  }
  function alignment(value, name) {
    if (value?.schema !== "youspeed-dashcam-alignment-v1" || value.videoFile !== name) throw new Error("Zeitdatei gehört nicht zu diesem Video.");
    const start = utc(value.startUTC);
    if (start == null) throw new Error("Videostart braucht einen ISO-Zeitstempel mit Zeitzone.");
    if (!Number.isFinite(value.frameRate) || value.frameRate <= 0 || value.frameRate > 240) throw new Error("Ungültige Bildrate.");
    return {start, fps: value.frameRate, source: String(value.source ?? "Zeitdatei")};
  }
  async function movieStart(file) {
    // Never read the media payload (several GB); only atom headers and mvhd.
    let reads = 0;
    async function scan(begin, end, depth) {
      for (let offset = begin; offset + 8 <= end;) {
        if (++reads > 4096) throw new Error("Zu viele Video-Metadatenblöcke.");
        const bytes = await file.slice(offset, Math.min(offset + 32, end)).arrayBuffer();
        const view = new DataView(bytes);
        let size = view.getUint32(0), header = 8;
        const type = String.fromCharCode(...new Uint8Array(bytes, 4, 4));
        if (size === 1) { if (bytes.byteLength < 16) return null; size = Number(view.getBigUint64(8)); header = 16; }
        else if (size === 0) size = end - offset;
        if (!Number.isSafeInteger(size) || size < header || offset + size > end) return null;
        if (type === "moov" && depth === 0) {
          const start = await scan(offset + header, offset + size, depth + 1);
          if (start != null) return start;
        }
        if (type === "mvhd" && depth === 1 && bytes.byteLength >= header + 12) {
          const version = view.getUint8(header);
          const seconds = version === 1 ? Number(view.getBigUint64(header + 4)) : version === 0 ? view.getUint32(header + 4) : 0;
          const time = epoch + seconds * 1000;
          return seconds > 0 && time >= Date.UTC(2000, 0, 1) && time <= Date.UTC(2200, 0, 1) ? time : null;
        }
        offset += size;
      }
      return null;
    }
    return scan(0, file.size, 0);
  }
  return {utc, videoTime, alignment, movieStart};
});
