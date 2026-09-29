const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const core = require("../../inspector/track-path-core.js");
const source = fs.readFileSync(require.resolve("../../inspector/track-path.js"), "utf8");
const seconds = Date.parse("2026-09-29T10:00:00Z") / 1000;
const sample = {frameId:"frame-1", geometryId:"camera-a", capturedAtSeconds:seconds, captureClockKnown:true,
  imageWidth:384, imageHeight:216, calibrationAvailable:false,
  boundaries:[{cue:"paint", confidence:.8, points:[[.4,.5],[.2,.9]]}], corridors:[], associations:[]};

function inspector() {
  const elements = new Map(), listeners = {}, drawing = {strokes:0};
  const context = {clearRect() {}, setTransform() {}, beginPath() {}, lineTo() {}, moveTo() {},
    setLineDash() {}, closePath() {}, fill() {}, stroke() { drawing.strokes++; },
    measureText: text => ({width:text.length * 6}), fillRect() {}, fillText() {}};
  const element = id => {
    if (!elements.has(id)) elements.set(id, {listeners:{}, checked:id === "track-path-enabled", value:id === "track-path-offset" ? "0" : "",
      clientWidth:800, clientHeight:450, width:800, height:450,
      addEventListener(name, fn) {this.listeners[name] = fn;}, getContext() {return context;},
      replaceChildren() {this.value="";}, append() {}});
    return elements.get(id);
  };
  vm.runInNewContext(source, {window:{YouSpeedTrackPath:core,devicePixelRatio:1,addEventListener(name,fn){listeners[name]=fn;}},
    document:{getElementById:element}, Option:class {constructor(text,value){this.text=text;this.value=value;}}});
  const emit = (name, detail) => listeners[name]({detail});
  const state = {videoFile:"drive.mp4",version:1,startMs:seconds*1000,timeMs:seconds*1000,
    videoTimeSeconds:0,videoWidth:1920,videoHeight:1080,seeking:false,hidden:false};
  return {element,drawing,emit,state,
    load: (frames=[sample]) => emit("inspector:path-log",{text:JSON.stringify(frames),name:"test.ndjson"}),
    show() {emit("inspector:video-frame",state);element("track-path-geometry").value="camera-a";
      element("track-path-geometry").listeners.change();element("track-path-confirmed").checked=true;
      element("track-path-confirmed").listeners.change();}
  };
}

test("controller renders only confirmed exposure and clears at stale time or during seek", () => {
  const app=inspector();app.load();app.show();
  assert.equal(app.element("track-path-overlay").hidden,false);
  assert.ok(app.drawing.strokes>0);
  assert.match(app.element("track-path-status").textContent,/Kalibrierung unbekannt/);
  app.emit("inspector:video-frame",{...app.state,timeMs:app.state.timeMs+500});
  assert.equal(app.element("track-path-overlay").hidden,true);
  app.emit("inspector:video-frame",{...app.state,seeking:true});
  assert.equal(app.element("track-path-overlay").hidden,true);
});

test("switching video, time anchor, geometry or offset requires fresh alignment confirmation", () => {
  for (const changed of [{videoFile:"other.mp4"},{startMs:seconds*1000+1000},{version:2}]) {
    const app=inspector();app.load();app.show();app.emit("inspector:video-frame",{...app.state,...changed});
    assert.equal(app.element("track-path-confirmed").checked,false);
    assert.equal(app.element("track-path-overlay").hidden,true);
  }
  const app=inspector();app.load();app.show();app.element("track-path-offset").value="50";
  app.element("track-path-offset").listeners.change();
  assert.equal(app.element("track-path-confirmed").checked,false);
  assert.equal(app.element("track-path-overlay").hidden,true);
});

test("deadline frames and disabling overlay immediately remove previous strokes", () => {
  const app=inspector();app.load([sample,{...sample,frameId:"frame-2",capturedAtSeconds:seconds+.05,deadlineExceeded:true}]);
  app.show();assert.equal(app.element("track-path-overlay").hidden,false);
  app.emit("inspector:video-frame",{...app.state,timeMs:(seconds+.05)*1000});
  assert.equal(app.element("track-path-overlay").hidden,true);
  assert.match(app.element("track-path-status").textContent,/budget/);
  app.element("track-path-enabled").checked=false;app.element("track-path-enabled").listeners.change();
  assert.equal(app.element("track-path-overlay").hidden,true);
});
