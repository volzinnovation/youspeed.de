const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../inspector/track-video-core.js");
const start = Date.parse("2026-09-24T11:53:07Z");
function atom(type, payload, extended = false) {
  const header = Buffer.alloc(extended ? 16 : 8);
  header.writeUInt32BE(extended ? 1 : header.length + payload.length);
  header.write(type, 4);
  if (extended) header.writeBigUInt64BE(BigInt(header.length + payload.length), 8);
  return Buffer.concat([header,payload]);
}
function mvhd(version) {
  const data = Buffer.alloc(20); data[0] = version;
  const seconds = (start - Date.UTC(1904,0,1))/1000;
  if (version === 1) data.writeBigUInt64BE(BigInt(seconds),4);
  else data.writeUInt32BE(seconds,4);
  return atom("moov", atom("mvhd", data));
}
test("UTC offset and coverage boundaries cannot silently clamp to another frame", () => {
  assert.equal(core.utc("2026-09-24T13:53:07+02:00"), start);
  assert.equal(core.utc("2026-09-24T13:53:07"), null);
  assert.equal(core.utc("invalidZ"), null);
  assert.equal(core.videoTime(start+621000,start,1540.918),621);
  for (const time of [start-1,start+1541000,NaN]) assert.equal(core.videoTime(time,start,1540.918),null);
  assert.equal(core.videoTime(start,null,1540),null);
});
test("sidecar must match selected video and carry a valid explicit clock", () => {
  const sidecar = {schema:"youspeed-dashcam-alignment-v1", videoFile:"drive.mov",startUTC:"2026-09-24T11:53:07Z",frameRate:30};
  assert.equal(core.alignment(sidecar,"drive.mov").start,start);
  assert.throws(() => core.alignment(sidecar,"other.mov"));
  assert.throws(() => core.alignment({...sidecar,startUTC:"2026-09-24T11:53:07"},"drive.mov"));
  assert.throws(() => core.alignment({...sidecar,frameRate:0},"drive.mov"));
});
test("QuickTime version 0 and 1 start metadata", async () => {
  for (const version of [0,1]) assert.equal(await core.movieStart(new Blob([mvhd(version)])),start);
});
test("5 GB media payload is skipped using 64-bit atom size", async () => {
  const payloadSize = 5_000_000_000;
  const header = Buffer.alloc(16); header.writeUInt32BE(1);header.write("mdat",4);header.writeBigUInt64BE(BigInt(payloadSize),8);
  const metadata = mvhd(1); let readBytes = 0;
  const file = {size:payloadSize+metadata.length,slice(a,b) {
    assert.ok(a===0 || a>=payloadSize,"Never read media payload");
    readBytes += b-a;
    const buffer = a===0 ? Buffer.concat([header,Buffer.alloc(b-a-16)]) : metadata.subarray(a-payloadSize,b-payloadSize);
    return new Blob([buffer]);
  }};
  assert.equal(await core.movieStart(file),start);
  assert.ok(readBytes<=96);
});
test("malformed or missing movie metadata is not a fabricated time", async () => {
  assert.equal(await core.movieStart(new Blob([atom("free",Buffer.alloc(16))])),null);
  const malformed=Buffer.alloc(8);malformed.writeUInt32BE(4);malformed.write("moov",4);
  assert.equal(await core.movieStart(new Blob([malformed])),null);
  assert.equal(await core.movieStart(new Blob([atom("moov",atom("mvhd",Buffer.alloc(20)))])),null);
});
