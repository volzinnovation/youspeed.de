const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../inspector/track-path-core.js");
const seconds = Date.parse("2026-09-29T10:00:00Z") / 1000;
const frame = (extra = {}) => ({frameId: "frame-1", capturedAtSeconds: seconds, geometryId: "camera-a",
  captureClockKnown: true, imageWidth: 384, imageHeight: 216, calibrationAvailable: false,
  boundaries: [{confidence: .82, cue: "paint", points: [[.4, .5], [.15, .94]]}],
  corridors: [{id: "corridor-0", role: "unknown", confidence: .76, imagePolygon: [[.4,.5],[.15,.94],[.85,.94],[.6,.5]]}],
  signBoxes: [{trackId: "sign-1", x: .8, y: .2, width: .1, height: .15}],
  associations: [{trackId: "sign-1", classification: "unknown", reason: "calibration_missing"}], ...extra});
const parsed = (...frames) => core.parseLog(JSON.stringify(frames));
const context = (extra = {}) => ({videoFile: "drive.mp4", videoTimeSeconds: 1, timeMs: seconds * 1000,
  videoWidth: 1920, videoHeight: 1080, alignmentConfirmed: true, geometryId: "camera-a", ...extra});

test("Android envelopes and iPhone prefixes preserve frame identity, exposure and uncertainty", () => {
  const android = JSON.stringify({event: "tsr_path_evidence_v1", details: {evidence: JSON.stringify(frame())}});
  const iphone = "2026-09-29T10:00:01Z tsr_path_evidence_v1=" + JSON.stringify(frame({frameId: "frame-2", capturedAtSeconds: seconds + 1}));
  const data = core.parseLog(android + "\n" + iphone + "\nordinary log line");
  assert.equal(data.frames.length, 2);
  assert.deepEqual(data.geometryIds, ["camera-a"]);
  assert.equal(data.frames[0].time, seconds * 1000);
  assert.equal(data.frames[1].frameId, "frame-2");
  assert.equal(data.frames[0].corridors[0].role, "unknown");
  assert.equal(data.frames[0].associations[0].classification, "unknown");
  assert.equal(data.ignored, 1);
});

test("identical duplicates are collapsed and conflicting duplicates poison their exposure", () => {
  const same = parsed(frame(), frame());
  assert.equal(same.frames.length, 1);
  const conflict = parsed(frame(), frame({deadlineExceeded: true}));
  assert.equal(conflict.frames.length, 1);
  assert.equal(conflict.warnings.length, 1);
  assert.equal(core.selectFrame(conflict, context()).frame, null);
});

test("a matched exposure needs explicit time/crop confirmation and matching geometry/aspect", () => {
  const data = parsed(frame());
  assert.equal(core.selectFrame(data, context()).frame.frameId, "frame-1");
  for (const change of [{alignmentConfirmed: false}, {geometryId: "camera-b"}, {geometryId: ""},
    {timeMs: null}, {videoWidth: 1080, videoHeight: 1920}, {videoWidth: 0}, {hidden: true}, {seeking: true}]) {
    assert.equal(core.selectFrame(data, context(change)).frame, null, JSON.stringify(change));
  }
});

test("clock, processing deadline and geometry deadline records clear rather than reuse older evidence", () => {
  for (const unavailable of [{captureClockKnown: false}, {deadlineExceeded: true}, {geometryDeadlineExceeded: true}]) {
    const data = parsed(frame(), frame({frameId: "frame-2", capturedAtSeconds: seconds + .05, ...unavailable}));
    assert.equal(core.selectFrame(data, context({timeMs: (seconds + .05) * 1000})).frame, null);
  }
});

test("replay never extrapolates, clamps timestamps or skips a nearer incompatible geometry", () => {
  const data = parsed(frame(), frame({frameId: "frame-2", geometryId: "camera-b", capturedAtSeconds: seconds + .05}));
  assert.equal(core.selectFrame(data, context({timeMs: (seconds + .05) * 1000})).frame, null);
  assert.equal(core.selectFrame(parsed(frame()), context({timeMs: (seconds + .081) * 1000})).frame, null);
  assert.equal(core.selectFrame(parsed(frame()), context({timeMs: (seconds + .079) * 1000})).frame.frameId, "frame-1");
  assert.equal(core.selectFrame(parsed(frame()), context({frameId: "different-frame"})).frame, null);
});

test("malformed newer geometry forms a barrier and normalized points cannot escape the video", () => {
  const invalid = frame({frameId: "bad", capturedAtSeconds: seconds + .04,
    boundaries: [{confidence: .7, cue: "paint", points: [[-1, .5], [.1, .9]]}]});
  const data = parsed(frame(), invalid);
  assert.equal(data.warnings.length, 1);
  assert.equal(core.selectFrame(data, context({timeMs: (seconds + .04) * 1000})).frame, null);
  assert.equal(parsed(frame({signBoxes: [{x:.9,y:.5,width:.2,height:.1}]})).warnings.length, 1);
});

test("verified exposure-to-PTS mapping is file bound while callback anchors remain approximate", () => {
  const mapping = {videoFile: "drive.mp4", videoTimeSeconds: 1, geometryId: "camera-a", timingQuality: "exposure_pts_verified"};
  const verified = parsed(frame({dashcam: mapping}));
  const noManual = context({alignmentConfirmed: false, timeMs: null, geometryId: ""});
  assert.equal(core.selectFrame(verified, noManual).alignment, "logged_pts");
  assert.equal(core.selectFrame(verified, {...noManual, videoFile: "other.mp4"}).frame, null);
  assert.equal(core.selectFrame(parsed(frame({dashcam: {...mapping, timingQuality: "callback_anchor_estimated"}})), noManual).frame, null);
  assert.equal(core.selectFrame(verified, {...noManual, videoTimeSeconds: 1.2}).frame, null);
});

test("recording callback anchors are retained as diagnostics, never used to manufacture a precise time", () => {
  const recording = {videoFile: "drive.mp4", event: "start", observedAtSeconds: seconds, timingQuality: "callback_anchor_estimated"};
  const data = core.parseLog("tsr_path_recording_v1=" + JSON.stringify(recording) + "\n" +
    JSON.stringify({event:"tsr_path_recording_v1", details:{evidence:JSON.stringify({...recording,event:"stop"})}}));
  assert.equal(data.recordings.length, 2);
  assert.equal(data.frames.length, 0);
  assert.equal(data.recordings[0].timingQuality, "callback_anchor_estimated");
});

test("viewport respects contain letterboxing for landscape and portrait", () => {
  assert.deepEqual(core.viewport(800, 600, 1920, 1080), {x:0,y:75,width:800,height:450});
  assert.deepEqual(core.viewport(800, 600, 1080, 1920), {x:231.25,y:0,width:337.5,height:600});
  assert.equal(core.viewport(800, 600, 0, 1080), null);
});
