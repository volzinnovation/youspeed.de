/* Portable ZIP (STORE, UTF-8, CRC32). No dependencies or remote scripts. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.YouSpeedLaneZip = api;
})(typeof window === "object" ? window : globalThis, function () {
  "use strict";
  const encoder = new TextEncoder(), decoder = new TextDecoder("utf-8", {fatal: true});
  const table = Array.from({length: 256}, (_, i) => { for (let j = 0; j < 8; j++) i = i & 1 ? 0xedb88320 ^ (i >>> 1) : i >>> 1; return i >>> 0; });
  function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) crc = table[(crc ^ byte) & 255] ^ (crc >>> 8); return (crc ^ 0xffffffff) >>> 0; }
  function safe(name) { return /^(?:manifest\.json|splits\/(?:train|validation|test)\.json|images\/[a-f0-9]{64}-\d+\.png)$/.test(name); }
  function header(size) { const bytes = new Uint8Array(size); return {bytes, view: new DataView(bytes.buffer)}; }
  async function pack(files) {
    if (files.length > 65535) throw new Error("Zu viele Dateien für ZIP. Dataset in kleinere Pakete teilen.");
    const chunks = [], directory = [];
    let offset = 0, directoryLength = 0;
    for (const [name, blob] of files) {
      if (!safe(name)) throw new Error("Ungültiger ZIP-Pfad.");
      if (offset + directoryLength + blob.size + 30 + 46 + encoder.encode(name).length * 2 + 22 > 0xffffffff)
        throw new Error("ZIP über 4 GiB. Dataset in kleinere Pakete teilen.");
      const encoded = encoder.encode(name), bytes = new Uint8Array(await blob.arrayBuffer()), crc = crc32(bytes);
      const local = header(30); local.view.setUint32(0, 0x04034b50, true); local.view.setUint16(4, 20, true);
      local.view.setUint16(6, 0x800, true); local.view.setUint32(14, crc, true);
      local.view.setUint32(18, bytes.length, true); local.view.setUint32(22, bytes.length, true); local.view.setUint16(26, encoded.length, true);
      const central = header(46); central.view.setUint32(0, 0x02014b50, true); central.view.setUint16(4, 20, true); central.view.setUint16(6, 20, true);
      central.view.setUint16(8, 0x800, true); central.view.setUint32(16, crc, true); central.view.setUint32(20, bytes.length, true);
      central.view.setUint32(24, bytes.length, true); central.view.setUint16(28, encoded.length, true); central.view.setUint32(42, offset, true);
      chunks.push(local.bytes, encoded, blob); directory.push(central.bytes, encoded);
      offset += 30 + encoded.length + bytes.length; directoryLength += 46 + encoded.length;
      if (offset + directoryLength > 0xffffffff) throw new Error("ZIP über 4 GiB. Dataset in kleinere Pakete teilen.");
    }
    const end = header(22); end.view.setUint32(0, 0x06054b50, true); end.view.setUint16(8, files.length, true); end.view.setUint16(10, files.length, true);
    end.view.setUint32(12, directoryLength, true); end.view.setUint32(16, offset, true);
    return new Blob([...chunks, ...directory, end.bytes], {type: "application/zip"});
  }
  async function unpack(blob) {
    if (blob.size < 22 || blob.size > 0xffffffff) throw new Error("Ungültige ZIP-Größe.");
    const end = new DataView(await blob.slice(-22).arrayBuffer());
    if (end.getUint32(0, true) !== 0x06054b50 || end.getUint16(4, true) || end.getUint16(6, true) || end.getUint16(20, true) || end.getUint16(8, true) !== end.getUint16(10, true)) throw new Error("Nur lokale Lane-Dataset-ZIPs ohne ZIP64 unterstützt.");
    const count = end.getUint16(10, true), directorySize = end.getUint32(12, true), directoryStart = end.getUint32(16, true);
    if (directoryStart + directorySize !== blob.size - 22) throw new Error("Beschädigtes ZIP-Verzeichnis.");
    const directory = new Uint8Array(await blob.slice(directoryStart, directoryStart + directorySize).arrayBuffer());
    const files = new Map(); let at = 0, localEnd = 0;
    for (let i = 0; i < count; i++) {
      if (at + 46 > directory.length) throw new Error("Beschädigtes ZIP.");
      const v = new DataView(directory.buffer, at);
      const length = v.getUint32(24, true), nameLength = v.getUint16(28, true), extra = v.getUint16(30, true), comment = v.getUint16(32, true), offset = v.getUint32(42, true);
      if (v.getUint32(0, true) !== 0x02014b50 || v.getUint16(8, true) !== 0x800 || v.getUint16(10, true) !== 0 || v.getUint32(20, true) !== length || offset !== localEnd || at + 46 + nameLength + extra + comment > directory.length) throw new Error("Nur unkomprimierte Lane-Dataset-ZIPs unterstützt.");
      const name = decoder.decode(directory.slice(at+46, at+46+nameLength));
      if (!safe(name) || files.has(name)) throw new Error("Ungültiger oder doppelter ZIP-Pfad.");
      const local = new DataView(await blob.slice(offset, offset + 30).arrayBuffer());
      if (local.getUint32(0, true) !== 0x04034b50 || local.getUint16(6, true) !== 0x800 || local.getUint16(8, true) !== 0 || local.getUint16(28, true) || local.getUint16(26, true) !== nameLength || local.getUint32(18, true) !== length || local.getUint32(22, true) !== length || local.getUint32(14, true) !== v.getUint32(16, true)) throw new Error("Beschädigter ZIP-Header.");
      if (decoder.decode(await blob.slice(offset+30, offset+30+nameLength).arrayBuffer()) !== name) throw new Error("ZIP-Pfade widersprechen sich.");
      localEnd = offset + 30 + nameLength + length;
      if (localEnd > directoryStart) throw new Error("Ungültiger ZIP-Bildbereich.");
      const data = blob.slice(offset+30+nameLength, localEnd, name.endsWith(".png") ? "image/png" : "application/json");
      if (crc32(new Uint8Array(await data.arrayBuffer())) !== v.getUint32(16, true)) throw new Error("ZIP-Prüfsumme fehlgeschlagen.");
      files.set(name, data); at += 46 + nameLength + extra + comment;
    }
    if (at !== directory.length || localEnd !== directoryStart) throw new Error("Unvollständiges ZIP.");
    return files;
  }
  return {pack, unpack, crc32};
});
