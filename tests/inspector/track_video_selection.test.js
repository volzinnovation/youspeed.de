const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const core = require("../../inspector/track-video-core.js");
const source = fs.readFileSync(require.resolve("../../inspector/track-video.js"), "utf8");
const start = Date.parse("2026-09-24T11:53:07Z");

// Exercise the actual event controller with a minimal media/DOM adapter.
function inspector() {
  const elements = new Map(), windowListeners = {};
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      listeners: {}, style: {}, value: "", currentTime: 0, duration: 1540, readyState: 1,
      paused: true, scrolls: 0, focuses: 0,
      addEventListener(name, fn) { this.listeners[name] = fn; },
      setAttribute() {}, removeAttribute() {}, load() {},
      pause() { this.paused = true; },
      scrollIntoView() { this.scrolls++; },
      focus() { this.focuses++; }
    });
    return elements.get(id);
  };
  const window = {
    YouSpeedTrackVideo: {...core, movieStart: async () => start},
    YouSpeedInspectorBridge: {invalidateMap() {}, getDriveEntries: () => []},
    addEventListener(name, fn) { windowListeners[name] = fn; }
  };
  vm.runInNewContext(source, {
    window, document: {getElementById: element, addEventListener() {}},
    URL: {createObjectURL: () => "blob:local-video", revokeObjectURL() {}},
    clearInterval() {}, setInterval() {}
  });
  return {
    video: element("track-video"), status: element("track-video-status"),
    load: () => element("track-video-file").listeners.change({target: {files: [{name: "drive.mov"}]}}),
    event: (name, detail) => windowListeners[name]({detail})
  };
}

test("sign selection overrides the nearest GPS time and reveals the paused exact frame", async () => {
  const app = inspector(); await app.load();
  app.video.paused = false;
  app.event("inspector:drive-fix", {time: start + 620400});
  app.event("inspector:tsr-select", {time: start + 620937, revealVideo: true});
  assert.equal(app.video.currentTime, 620.937);
  assert.equal(app.video.paused, true);
  assert.equal(app.video.scrolls, 1);
  assert.equal(app.video.focuses, 1);
});

test("sign selection without video leaves focus and scrolling alone", () => {
  const app = inspector();
  app.event("inspector:tsr-select", {time: start + 1000, revealVideo: true});
  assert.equal(app.video.scrolls, 0);
  assert.equal(app.video.focuses, 0);
});

test("passive filter rerender keeps the frame selected without stealing focus", async () => {
  const app = inspector(); await app.load();
  app.event("inspector:tsr-select", {time: start + 1000, revealVideo: false});
  assert.equal(app.video.currentTime, 1);
  assert.equal(app.video.scrolls, 0);
  assert.equal(app.video.focuses, 0);
});

test("out-of-coverage sign reveals the explanation instead of a stale frame", async () => {
  const app = inspector(); await app.load();
  app.event("inspector:tsr-select", {time: start - 1000, revealVideo: true});
  assert.equal(app.video.style.visibility, "hidden");
  assert.equal(app.video.focuses, 0);
  assert.equal(app.status.focuses, 1);
  assert.equal(app.status.scrolls, 1);
  assert.match(app.status.textContent, /außerhalb/);
});

test("selection during media loading is sought once metadata becomes available", async () => {
  const app = inspector(); await app.load(); app.video.readyState = 0;
  app.event("inspector:tsr-select", {time: start + 42000, revealVideo: true});
  assert.equal(app.video.currentTime, 0);
  assert.equal(app.video.scrolls, 1);
  app.video.readyState = 1;
  app.video.listeners.loadedmetadata();
  assert.equal(app.video.currentTime, 42);
});
