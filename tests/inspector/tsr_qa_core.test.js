"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const core = require("../../inspector/tsr-qa-core.js");

const fixtureRoot = path.resolve(
  __dirname,
  "../../shared/tsr/fixtures"
);

function readFixture(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(fixtureRoot, relativePath), "utf8"));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

const diagnosticBundle = readFixture("diagnostic-bundle-v1/manifest.json");
const recognitionEvents = readFixture("recognition-events-v1.json");
const modelPack = readFixture("de-direct-pack-v1.json");
const recognitionEventsV2 = readFixture("recognition-events-v2.json");
const modelPackV2 = readFixture("de-yolox-mnv3-shadow-pack-v2.json");

test("parseJSONOrNDJSON accepts arrays, event envelopes, single objects, and NDJSON", () => {
  const array = [{ id: 1 }, { id: 2 }];
  assert.deepEqual(core.parseJSONOrNDJSON(JSON.stringify(array)), array);
  assert.deepEqual(core.parseJSONOrNDJSON(JSON.stringify({ events: array })), array);
  assert.deepEqual(core.parseJSONOrNDJSON('{"id":3}'), [{ id: 3 }]);
  assert.deepEqual(
    core.parseJSONOrNDJSON('{"id":1}\n\n {"id":2}\r\n'),
    array
  );
  assert.deepEqual(core.parseJSONOrNDJSON("  \n"), []);
  assert.throws(
    () => core.parseJSONOrNDJSON('{"id":1}\nnot-json'),
    /Invalid JSON on line 2/
  );
});

test("v2 Panoramax reviewed expectations pass preflight without claiming inference", () => {
  const eventGate = core.eventGateAssessment(recognitionEventsV2);
  assert.deepEqual(eventGate, { passed: true, issues: [] });
  const packGate = core.modelPackGateAssessment(modelPackV2);
  assert.deepEqual(packGate, { passed: true, issues: [] });
  assert.equal(core.eventTimestampUtc(recognitionEventsV2[0]), "2026-09-01T16:14:33.731Z");
  assert.equal(recognitionEventsV2[0].evidence_origin, "reviewed_expectation");
  assert.equal(recognitionEventsV2[0].stage_runs.detector.invoked, false);
  assert.equal(recognitionEventsV2[0].assemblies[0].primary.detector_score, null);
  assert.equal(core.eventOverrideAssessment(recognitionEventsV2[1]).effect, "none");
  assert.match(core.eventOverrideAssessment(recognitionEventsV2[1]).reason, /shadow-only/);
  assert.deepEqual(core.provenanceAssessment(null, recognitionEventsV2, modelPackV2), {
    passed: true,
    issues: []
  });
});

test("v2 event preflight preserves unreadable history and blocks all overrides", () => {
  const inherited = clone(recognitionEventsV2);
  inherited[0].assemblies[0].supplementary_plates[0].restriction = {
    kind: "extent",
    normalized_value: "2000 m",
    extent_m: 2000
  };
  assert.ok(core.eventGateAssessment(inherited).issues.includes(
    "events[0].assemblies[0].supplementary_plates[0].restriction must be null when unreadable"
  ));

  const override = clone(recognitionEventsV2);
  override[1].override_eligible = true;
  assert.ok(core.eventGateAssessment(override).issues.includes(
    "events[1].override_eligible must be false"
  ));
  assert.deepEqual(
    { eligible: core.eventOverrideAssessment(override[1]).eligible, effect: core.eventOverrideAssessment(override[1]).effect },
    { eligible: false, effect: "none" }
  );

  const fakeInference = clone(recognitionEventsV2);
  fakeInference[0].evidence_origin = "runtime_inference";
  assert.ok(core.eventGateAssessment(fakeInference).issues.includes(
    "events[0].stage_runs.detector must be invoked for runtime inference"
  ));
  assert.ok(core.eventGateAssessment(fakeInference).issues.includes(
    "events[0].assemblies[0].primary.detector_score must be an object"
  ));
});

test("v2 model-pack preflight enforces independent crops, identities, and offline-only references", () => {
  const linkedCrops = clone(modelPackV2);
  linkedCrops.stages.classifier.preprocessing.crop_policy.include_linked_objects = true;
  assert.ok(core.modelPackGateAssessment(linkedCrops).issues.includes(
    "model_pack.stages.classifier.preprocessing.crop_policy must require independent role-hinted crops"
  ));

  const aliased = clone(modelPackV2);
  aliased.stages.classifier.artifacts.coreml.sha256 = aliased.stages.detector.artifacts.coreml.sha256;
  assert.ok(core.modelPackGateAssessment(aliased).issues.includes(
    "model_pack.stages.classifier.artifacts.coreml reuses a global artifact hash"
  ));

  const promotedTeacher = clone(modelPackV2);
  promotedTeacher.offline_references[0].runtime_included = true;
  assert.ok(core.modelPackGateAssessment(promotedTeacher).issues.includes(
    "model_pack.offline_references[0] cannot be a runtime or acceptance model"
  ));

  const wrongClassifier = clone(recognitionEventsV2);
  wrongClassifier[1].stage_runs.classifier.artifact_sha256 = "a".repeat(64);
  assert.ok(core.provenanceAssessment(null, wrongClassifier, modelPackV2).issues.includes(
    "events[1] classifier provenance does not match the loaded manifest"
  ));
});

test("intersectionOverUnion handles identical, partial, disjoint, and invalid boxes", () => {
  const left = { x: 0, y: 0, width: 0.5, height: 0.5 };
  assert.equal(core.intersectionOverUnion(left, left), 1);
  assert.ok(Math.abs(core.intersectionOverUnion(
    left,
    { x: 0.25, y: 0.25, width: 0.5, height: 0.5 }
  ) - (1 / 7)) < 1e-12);
  assert.equal(
    core.intersectionOverUnion(left, { x: 0.6, y: 0.6, width: 0.2, height: 0.2 }),
    0
  );
  assert.equal(core.intersectionOverUnion(left, { x: 0, y: 0, width: -1, height: 1 }), 0);
  assert.equal(core.intersectionOverUnion(left, { x: 0.9, y: 0, width: 0.2, height: 0.2 }), 0);
});

test("assetPathIsSafe accepts bundle-relative assets and rejects traversal or external paths", () => {
  assert.equal(core.assetPathIsSafe("frames/frame-0001.ppm"), true);
  assert.equal(core.assetPathIsSafe("crops/assembly-0001.ppm"), true);
  for (const unsafe of [
    "",
    "/tmp/frame.ppm",
    "../frame.ppm",
    "%2e%2e/frame.ppm",
    "frames/../frame.ppm",
    "./frame.ppm",
    "frames//frame.ppm",
    "frames\\frame.ppm",
    "https://example.invalid/frame.ppm",
    "file:frame.ppm"
  ]) {
    assert.equal(core.assetPathIsSafe(unsafe), false, unsafe);
  }
});

test("committed diagnostic bundle passes contract and privacy gates at a pinned review time", () => {
  const gates = core.bundleGateAssessment(
    diagnosticBundle,
    new Date("2026-09-01T00:00:00Z")
  );
  assert.deepEqual(gates, {
    contract: { passed: true, issues: [] },
    privacy: { passed: true, issues: [] }
  });
});

test("bundle gates report unsafe assets, duplicate samples, and each privacy blocker", () => {
  const bundle = clone(diagnosticBundle);
  const duplicate = clone(bundle.samples[0]);
  duplicate.assets[0].path = "../escaped-frame.ppm";
  bundle.samples.push(duplicate);
  bundle.consent.scope = "analytics";
  bundle.consent.export_approved = false;
  bundle.consent.retention_expires_at = "2025-01-01T00:00:00Z";
  bundle.privacy.redaction_state = "pending";
  bundle.privacy.raw_dashcam_video_included = true;
  bundle.privacy.direct_device_identifier_included = true;

  const gates = core.bundleGateAssessment(bundle, new Date("2026-09-01T00:00:00Z"));
  assert.equal(gates.contract.passed, false);
  assert.ok(gates.contract.issues.includes("sample IDs must be present and unique"));
  assert.ok(gates.contract.issues.includes("samples[1].assets[0].path is unsafe"));
  assert.equal(gates.privacy.passed, false);
  assert.deepEqual(gates.privacy.issues, [
    "consent scope is invalid",
    "export is not approved",
    "exported full frames require verified redaction",
    "raw dashcam video is present or unspecified",
    "direct device identity is present or unspecified",
    "retention does not extend beyond capture",
    "retention has expired or is invalid"
  ]);
});

test("bundle preflight rejects missing required fields and permits crop-only not-required redaction", () => {
  const incomplete = {
    schema_version: 1,
    bundle_id: "incomplete",
    capture_group_id: "capture",
    consent: clone(diagnosticBundle.consent),
    privacy: clone(diagnosticBundle.privacy),
    samples: [{ sample_id: "sample" }]
  };
  const incompleteGates = core.bundleGateAssessment(incomplete, new Date("2026-09-01T00:00:00Z"));
  assert.equal(incompleteGates.contract.passed, false);
  assert.ok(incompleteGates.contract.issues.includes("bundle.purpose is missing"));
  assert.ok(incompleteGates.contract.issues.includes("samples[0].capture_context is missing"));

  const cropOnly = clone(diagnosticBundle);
  cropOnly.privacy.full_frame_retention = false;
  cropOnly.privacy.redaction_state = "not_required";
  cropOnly.samples[0].assets = cropOnly.samples[0].assets.filter((asset) => asset.role !== "full_frame");
  const cropOnlyGates = core.bundleGateAssessment(cropOnly, new Date("2026-09-01T00:00:00Z"));
  assert.equal(cropOnlyGates.contract.passed, true);
  assert.equal(cropOnlyGates.privacy.passed, true);
});

test("bundle privacy derives full-frame handling from retained assets", () => {
  const undeclaredFullFrame = clone(diagnosticBundle);
  undeclaredFullFrame.privacy.full_frame_retention = false;
  undeclaredFullFrame.privacy.redaction_state = "not_required";
  const undeclaredGates = core.bundleGateAssessment(
    undeclaredFullFrame,
    new Date("2026-09-01T00:00:00Z")
  );
  assert.equal(undeclaredGates.privacy.passed, false);
  assert.ok(undeclaredGates.privacy.issues.includes(
    "full-frame retention declaration does not match retained assets"
  ));
  assert.ok(undeclaredGates.privacy.issues.includes(
    "exported full frames require verified redaction"
  ));

  const declaredWithoutAsset = clone(diagnosticBundle);
  declaredWithoutAsset.samples[0].assets = declaredWithoutAsset.samples[0].assets
    .filter((asset) => asset.role !== "full_frame");
  const declaredGates = core.bundleGateAssessment(
    declaredWithoutAsset,
    new Date("2026-09-01T00:00:00Z")
  );
  assert.equal(declaredGates.privacy.passed, false);
  assert.ok(declaredGates.privacy.issues.includes(
    "full-frame retention declaration does not match retained assets"
  ));

  const ambiguousFullFrame = clone(diagnosticBundle);
  ambiguousFullFrame.samples[0].assets[0].role = "fullframe";
  ambiguousFullFrame.privacy.full_frame_retention = false;
  ambiguousFullFrame.privacy.redaction_state = "not_required";
  const ambiguousGates = core.bundleGateAssessment(
    ambiguousFullFrame,
    new Date("2026-09-01T00:00:00Z")
  );
  assert.equal(ambiguousGates.contract.passed, false);
  assert.ok(ambiguousGates.contract.issues.includes("samples[0].assets[0].role is invalid"));
  assert.equal(ambiguousGates.privacy.passed, false);
  assert.ok(ambiguousGates.privacy.issues.includes(
    "unrecognized asset roles cannot establish crop-only retention"
  ));
  assert.ok(ambiguousGates.privacy.issues.includes(
    "exported full frames require verified redaction"
  ));
});

test("bundle privacy rejects consent granted after capture", () => {
  const bundle = clone(diagnosticBundle);
  bundle.consent.granted_at = "2026-01-01T12:00:06Z";
  const gates = core.bundleGateAssessment(bundle, new Date("2026-09-01T00:00:00Z"));
  assert.ok(gates.privacy.issues.includes("consent was granted after capture"));

  const afterFrameBeforeBundle = clone(diagnosticBundle);
  afterFrameBeforeBundle.consent.granted_at = "2026-01-01T12:00:03Z";
  const frameGate = core.bundleGateAssessment(afterFrameBeforeBundle, new Date("2026-09-01T00:00:00Z"));
  assert.ok(frameGate.privacy.issues.includes("consent was granted after capture"));
});

test("bundle privacy reconciles declared location precision with retained context", () => {
  const noneWithContext = clone(diagnosticBundle);
  noneWithContext.privacy.location_mode = "none";
  const noneGate = core.bundleGateAssessment(noneWithContext, new Date("2026-09-01T00:00:00Z"));
  assert.ok(noneGate.privacy.issues.includes(
    "location_mode none conflicts with retained road or location context"
  ));

  const coarseWithExactIdentity = clone(diagnosticBundle);
  coarseWithExactIdentity.privacy.location_mode = "coarse";
  const coarseGate = core.bundleGateAssessment(coarseWithExactIdentity, new Date("2026-09-01T00:00:00Z"));
  assert.ok(coarseGate.privacy.issues.includes(
    "location_mode coarse permits only 3-decimal coordinates, 15-degree headings, and no exact way/source identity"
  ));

  const allowedCoarse = clone(diagnosticBundle);
  allowedCoarse.privacy.location_mode = "coarse";
  Object.assign(allowedCoarse.samples[0].capture_context, {
    road_context_complete: false,
    way_id: null,
    latitude: 49.007,
    longitude: 8.404,
    heading_degrees: 75,
    map_context_revision: null,
    map_source_signature: null
  });
  const allowedGate = core.bundleGateAssessment(allowedCoarse, new Date("2026-09-01T00:00:00Z"));
  assert.equal(allowedGate.privacy.issues.some((issue) => issue.startsWith("location_mode coarse")), false);
});

test("event and model-pack preflights keep malformed nested collections fail-closed", () => {
  assert.deepEqual(core.eventGateAssessment(recognitionEvents), { passed: true, issues: [] });
  assert.deepEqual(core.modelPackGateAssessment(modelPack), { passed: true, issues: [] });

  const brokenEvents = clone(recognitionEvents);
  brokenEvents[1].candidate.restrictions = { kind: "weather" };
  const eventGate = core.eventGateAssessment(brokenEvents);
  assert.equal(eventGate.passed, false);
  assert.ok(eventGate.issues.includes("events[1].candidate.restrictions must be an array"));

  const brokenPack = clone(modelPack);
  brokenPack.licenses = "not-an-array";
  brokenPack.detector.artifacts = null;
  const modelGate = core.modelPackGateAssessment(brokenPack);
  assert.equal(modelGate.passed, false);
  assert.ok(modelGate.issues.includes("model_pack.licenses must be a non-empty array"));
  assert.ok(modelGate.issues.includes("model_pack.detector.artifacts must be a non-empty array"));

  const malformedIdentity = clone(modelPack);
  delete malformedIdentity.preprocessing.version;
  malformedIdentity.detector.artifacts[0].platform = "bogus";
  malformedIdentity.detector.artifacts[0].format = "bogus";
  malformedIdentity.class_mapping[0].semantic = { kind: "bogus", value: 30.5, unit: "bananas" };
  const malformedGate = core.modelPackGateAssessment(malformedIdentity);
  assert.equal(malformedGate.passed, false);
  assert.ok(malformedGate.issues.includes("model_pack.preprocessing.version is missing"));
  assert.ok(malformedGate.issues.includes("model_pack.detector.artifacts[0].platform is invalid"));
  assert.ok(malformedGate.issues.includes("model_pack.detector.artifacts[0].format is invalid"));
  assert.ok(malformedGate.issues.includes("model_pack.class_mapping[0].semantic is invalid"));
});

test("model-pack preflight reconciles artifact checkpoint and calibration lineage", () => {
  const mismatched = clone(modelPack);
  mismatched.detector.artifacts[0].source_checkpoint_sha256 = "9".repeat(64);
  mismatched.detector.artifacts[1].calibration_dataset_sha256 = "8".repeat(64);

  const gate = core.modelPackGateAssessment(mismatched);
  assert.equal(gate.passed, false);
  assert.ok(gate.issues.includes(
    "model_pack.detector.artifacts[0].source_checkpoint_sha256 does not match its component"
  ));
  assert.ok(gate.issues.includes(
    "model_pack.detector.artifacts[1].calibration_dataset_sha256 does not match the pack"
  ));
});

test("model-pack preflight rejects unsafe paths, failed parity, and incompatible runtime artifacts", () => {
  const incompatible = clone(modelPack);
  const iosArtifact = incompatible.detector.artifacts[0];
  const androidArtifact = incompatible.detector.artifacts[1];

  iosArtifact.path = "models/../detector.mlmodel";
  iosArtifact.format = "tflite";
  iosArtifact.output_schema = "yolo_nms_xyxy_scores_classes_v1";
  iosArtifact.parity.passed = false;

  androidArtifact.format = "coreml";
  androidArtifact.output_schema = "vision_recognized_objects_v1";
  androidArtifact.parity.tolerance = 0.01;
  androidArtifact.parity.measured_max_abs_difference = 0.011;

  const gate = core.modelPackGateAssessment(incompatible);
  assert.equal(gate.passed, false);
  for (const issue of [
    "model_pack.detector.artifacts[0].path must be a safe relative path",
    "model_pack.detector.artifacts[0].format is incompatible with ios",
    "model_pack.detector.artifacts[0].output_schema is incompatible with ios",
    "model_pack.detector.artifacts[0].parity.passed must be true",
    "model_pack.detector.artifacts[1].format is incompatible with android",
    "model_pack.detector.artifacts[1].output_schema is incompatible with android",
    "model_pack.detector.artifacts[1].parity.measured_max_abs_difference exceeds tolerance"
  ]) {
    assert.ok(gate.issues.includes(issue), issue);
  }
});

test("model-pack preflight enforces ordered thresholds and coherent calibration state", () => {
  const unorderedThresholds = clone(modelPack);
  unorderedThresholds.thresholds.unknown = 0.8;
  unorderedThresholds.thresholds.provisional = 0.7;
  unorderedThresholds.thresholds.confirmed = 0.6;
  assert.ok(core.modelPackGateAssessment(unorderedThresholds).issues.includes(
    "model_pack.thresholds must satisfy unknown <= provisional <= confirmed"
  ));

  const calibratedWithoutMethod = clone(modelPack);
  calibratedWithoutMethod.calibration.kind = "none";
  assert.ok(core.modelPackGateAssessment(calibratedWithoutMethod).issues.includes(
    "model_pack.calibration calibrated packs require a non-none kind"
  ));

  const calibratedRawScore = clone(modelPack);
  calibratedRawScore.calibration.runtime_output = "raw_score";
  assert.ok(core.modelPackGateAssessment(calibratedRawScore).issues.includes(
    "model_pack.calibration calibrated packs must expose calibrated_confidence"
  ));

  const uncalibratedConfidence = clone(modelPack);
  uncalibratedConfidence.calibration.calibrated = false;
  assert.ok(core.modelPackGateAssessment(uncalibratedConfidence).issues.includes(
    "model_pack.calibration uncalibrated packs must expose raw_score"
  ));
});

test("model-pack preflight enforces native semantic, identity, lineage, and pipeline invariants", () => {
  const incompleteSpeed = clone(modelPack);
  incompleteSpeed.class_mapping[0].semantic = { kind: "maximum_speed" };
  const incompleteSpeedGate = core.modelPackGateAssessment(incompleteSpeed);
  assert.ok(incompleteSpeedGate.issues.includes(
    "model_pack.class_mapping[0].semantic requires a positive integer value for maximum_speed"
  ));
  assert.ok(incompleteSpeedGate.issues.includes(
    "model_pack.class_mapping[0].semantic requires km/h or mph for maximum_speed"
  ));

  for (const kind of ["maximum_speed", "zone_start", "temporary"]) {
    const fractionalSpeed = clone(modelPack);
    fractionalSpeed.class_mapping[0].semantic = { kind, value: 30.5, unit: "km/h" };
    assert.ok(core.modelPackGateAssessment(fractionalSpeed).issues.includes(
      `model_pack.class_mapping[0].semantic requires a positive integer value for ${kind}`
    ));
  }

  const validImperialSpeed = clone(modelPack);
  validImperialSpeed.class_mapping[0].semantic.unit = "mph";
  assert.equal(core.modelPackGateAssessment(validImperialSpeed).passed, true);

  for (const kind of [
    "zone_end", "restriction_end", "city_entry", "city_exit",
    "pedestrian_zone_start", "pedestrian_zone_end", "unknown"
  ]) {
    const valuedNonSpeed = clone(modelPack);
    valuedNonSpeed.class_mapping[1].semantic = { kind, value: 30, unit: "km/h" };
    assert.ok(core.modelPackGateAssessment(valuedNonSpeed).issues.includes(
      `model_pack.class_mapping[1].semantic must not carry value or unit for ${kind}`
    ));
  }

  const duplicateClass = clone(modelPack);
  duplicateClass.class_mapping[1].class_id = duplicateClass.class_mapping[0].class_id;
  assert.ok(core.modelPackGateAssessment(duplicateClass).issues.includes(
    "model_pack.class_mapping class_id values must be unique"
  ));

  const duplicateInventory = clone(modelPack);
  duplicateInventory.lineage.dataset_inventory_sha256s.push(
    duplicateInventory.lineage.dataset_inventory_sha256s[0]
  );
  assert.ok(core.modelPackGateAssessment(duplicateInventory).issues.includes(
    "model_pack.lineage.dataset_inventory_sha256s must be unique"
  ));

  const directWithClassifier = clone(modelPack);
  directWithClassifier.classifier = clone(directWithClassifier.detector);
  assert.ok(core.modelPackGateAssessment(directWithClassifier).issues.includes(
    "model_pack.pipeline direct_detection must not declare a classifier"
  ));

  const proposalWithoutClassifier = clone(modelPack);
  proposalWithoutClassifier.pipeline = "proposal_classification";
  assert.ok(core.modelPackGateAssessment(proposalWithoutClassifier).issues.includes(
    "model_pack.pipeline proposal_classification requires a classifier"
  ));
});

test("bundle preflight validates relational sign assemblies used by dataset build", () => {
  const brokenParent = clone(diagnosticBundle);
  brokenParent.samples[0].annotation.objects[1].parent_object_id = "missing-primary";
  const parentGate = core.bundleGateAssessment(brokenParent, new Date("2026-09-01T00:00:00Z"));
  assert.equal(parentGate.contract.passed, false);
  assert.ok(parentGate.contract.issues.includes(
    "samples[0].annotation plate plate-1 must reference a primary sign"
  ));
  assert.ok(core.sampleAssessment(brokenParent.samples[0]).issues.includes(
    "annotation plate plate-1 must reference a primary sign"
  ));

  const brokenCondition = clone(diagnosticBundle);
  brokenCondition.samples[0].annotation.assemblies[0].condition_state = "none";
  const conditionGate = core.bundleGateAssessment(brokenCondition, new Date("2026-09-01T00:00:00Z"));
  assert.ok(conditionGate.contract.issues.includes(
    "samples[0].annotation.assemblies[0].condition_state does not match its plates"
  ));

  const negativeWithLabels = clone(diagnosticBundle);
  negativeWithLabels.samples[0].annotation.status = "negative";
  const negativeGate = core.bundleGateAssessment(negativeWithLabels, new Date("2026-09-01T00:00:00Z"));
  assert.ok(negativeGate.contract.issues.includes(
    "samples[0].annotation negative samples cannot carry positive labels"
  ));

  const numericIDs = clone(diagnosticBundle);
  numericIDs.samples[0].annotation.objects[0].object_id = 123;
  numericIDs.samples[0].annotation.objects[0].assembly_id = 456;
  const numericGate = core.bundleGateAssessment(numericIDs, new Date("2026-09-01T00:00:00Z"));
  assert.equal(numericGate.contract.passed, false);
  assert.ok(numericGate.contract.issues.includes(
    "samples[0].annotation.objects[0].object_id is required"
  ));
});

test("bundle preflight enforces live road context, timezone, unique assets, and prediction roles", () => {
  const incompleteContext = clone(diagnosticBundle);
  incompleteContext.samples[0].capture_context.road_context_complete = false;
  incompleteContext.samples[0].capture_context.way_id = null;
  incompleteContext.samples[0].capture_context.latitude = null;
  incompleteContext.samples[0].capture_context.longitude = null;
  incompleteContext.samples[0].capture_context.heading_degrees = null;
  incompleteContext.samples[0].capture_context.map_context_revision = null;
  incompleteContext.samples[0].capture_context.map_source_signature = null;
  const contextGate = core.bundleGateAssessment(incompleteContext, new Date("2026-09-01T00:00:00Z"));
  assert.equal(contextGate.contract.passed, false);
  assert.ok(contextGate.contract.issues.includes(
    "samples[0].capture_context must contain synchronized road context"
  ));

  const timezoneLess = clone(diagnosticBundle);
  timezoneLess.samples[0].frame_timestamp_utc = "2026-01-01T12:00:00";
  const timezoneGate = core.bundleGateAssessment(timezoneLess, new Date("2026-09-01T00:00:00Z"));
  assert.ok(timezoneGate.contract.issues.includes("samples[0].frame_timestamp_utc is invalid"));

  const impossibleDate = clone(diagnosticBundle);
  impossibleDate.created_at = "2026-02-30T12:00:00Z";
  impossibleDate.consent.retention_expires_at = "2027-02-30T12:00:00Z";
  const impossibleGate = core.bundleGateAssessment(impossibleDate, new Date("2026-09-01T00:00:00Z"));
  assert.ok(impossibleGate.contract.issues.includes("created_at is invalid"));
  assert.ok(impossibleGate.contract.issues.includes("consent.retention_expires_at is invalid"));
  assert.ok(impossibleGate.privacy.issues.includes("retention has expired or is invalid"));

  const duplicateAsset = clone(diagnosticBundle);
  duplicateAsset.samples[0].assets.push(clone(duplicateAsset.samples[0].assets[0]));
  const duplicateGate = core.bundleGateAssessment(duplicateAsset, new Date("2026-09-01T00:00:00Z"));
  assert.ok(duplicateGate.contract.issues.includes(
    "samples[0] repeats asset path frames/frame-0001.ppm"
  ));

  const invalidPredictionRole = clone(diagnosticBundle);
  invalidPredictionRole.samples[0].predictions[0].role = "speed_sign";
  const predictionGate = core.bundleGateAssessment(invalidPredictionRole, new Date("2026-09-01T00:00:00Z"));
  assert.ok(predictionGate.contract.issues.includes("samples[0].predictions[0].role is invalid"));

  const numericPath = clone(diagnosticBundle);
  numericPath.samples[0].assets[0].path = 123;
  const pathGate = core.bundleGateAssessment(numericPath, new Date("2026-09-01T00:00:00Z"));
  assert.ok(pathGate.contract.issues.includes("samples[0].assets[0].path must be a non-empty string"));

  const unlinkedCrop = clone(diagnosticBundle);
  unlinkedCrop.samples[0].assets.push({
    ...clone(unlinkedCrop.samples[0].assets[1]),
    role: "primary_crop",
    path: "crops/unlinked-primary.ppm",
    object_id: "missing-object",
    assembly_id: "assembly-1"
  });
  const cropGate = core.bundleGateAssessment(unlinkedCrop, new Date("2026-09-01T00:00:00Z"));
  assert.ok(cropGate.contract.issues.includes(
    "samples[0].assets[2] must reference a matching annotation object"
  ));
});

test("sampleAssessment reports a clean committed fixture and actionable prediction diffs", () => {
  const clean = core.sampleAssessment(diagnosticBundle.samples[0]);
  assert.equal(clean.status, "clean");
  assert.equal(clean.predictionCount, 2);
  assert.equal(clean.annotationCount, 2);
  assert.equal(clean.matches.length, 2);
  assert.ok(Math.abs(clean.averageIoU - 1) < 1e-12);
  assert.deepEqual(clean.issues, []);

  const changed = clone(diagnosticBundle.samples[0]);
  changed.predictions[0].raw_class_id = "speed_limit_50";
  changed.predictions.pop();
  changed.annotation.assemblies[0].condition_state = "unresolved";
  const review = core.sampleAssessment(changed);
  assert.equal(review.status, "review");
  assert.equal(review.matches.length, 1);
  assert.equal(review.matches[0].classMatches, false);
  assert.ok(review.issues.includes("Class mismatch: speed_limit_50 → speed_limit_30"));
  assert.ok(review.issues.includes("Missed annotation: supplementary_wet"));
  assert.ok(review.issues.includes("Assembly assembly-1 remains unresolved"));
});

test("relatedEventsForSample returns the same-way event timeline in timestamp order", () => {
  const sample = diagnosticBundle.samples[0];
  const otherWay = clone(recognitionEvents[0]);
  otherWay.frame_timestamp_utc = "2026-01-01T12:00:00.200Z";
  otherWay.road_context.way_id = "999999";
  const tooLate = clone(recognitionEvents[1]);
  tooLate.frame_timestamp_utc = "2026-01-01T12:00:10.000Z";
  const future = clone(recognitionEvents[1]);
  future.frame_timestamp_utc = "2026-01-01T12:00:00.500Z";
  const wrongModel = clone(recognitionEvents[0]);
  wrongModel.artifact_sha256 = "9".repeat(64);

  const related = core.relatedEventsForSample(
    sample,
    [tooLate, future, wrongModel, recognitionEvents[1], otherWay, recognitionEvents[0]],
    1,
    diagnosticBundle.active_model
  );
  assert.deepEqual(
    related.map((event) => event.frame_timestamp_utc),
    ["2026-01-01T12:00:00Z", "2026-01-01T12:00:00.400Z"]
  );
  assert.deepEqual(related.map((event) => event.state), ["provisional", "confirmed"]);
});

test("provenance assessment reconciles fixtures and reports mixed model identities", () => {
  assert.deepEqual(core.provenanceAssessment(diagnosticBundle, recognitionEvents, modelPack), {
    passed: true,
    issues: []
  });
  const events = clone(recognitionEvents);
  events[0].pack_id = "other-pack";
  const assessment = core.provenanceAssessment(diagnosticBundle, events, modelPack);
  assert.equal(assessment.passed, false);
  assert.ok(assessment.issues.includes("events[0] model provenance does not match the bundle"));
  assert.ok(assessment.issues.includes("events[0] model provenance does not match the loaded manifest"));

  const wrongPlatformPack = clone(modelPack);
  wrongPlatformPack.detector.artifacts[0].sha256 = "9".repeat(64);
  wrongPlatformPack.detector.artifacts[1].sha256 = diagnosticBundle.active_model.artifact_sha256;
  const wrongPlatform = core.provenanceAssessment(diagnosticBundle, recognitionEvents, wrongPlatformPack);
  assert.equal(wrongPlatform.passed, false);
  assert.ok(wrongPlatform.issues.includes(
    "bundle artifact is absent from the loaded model manifest for ios"
  ));
});

test("override assessment sets unconditional speed and clears on newer conditional confirmation", () => {
  const provisional = core.eventOverrideAssessment(recognitionEvents[0]);
  assert.deepEqual(
    { eligible: provisional.eligible, effect: provisional.effect },
    { eligible: false, effect: "none" }
  );

  const conditional = core.eventOverrideAssessment(recognitionEvents[1]);
  assert.deepEqual(
    { eligible: conditional.eligible, effect: conditional.effect },
    { eligible: false, effect: "clear" }
  );
  assert.match(conditional.reason, /conditional, unresolved, or non-numeric/);

  const unconditionalEvent = clone(recognitionEvents[1]);
  unconditionalEvent.candidate.condition_state = "none";
  unconditionalEvent.candidate.restrictions = [];
  const unconditional = core.eventOverrideAssessment(unconditionalEvent);
  assert.deepEqual(
    { eligible: unconditional.eligible, effect: unconditional.effect, speedKmh: unconditional.speedKmh },
    { eligible: true, effect: "set", speedKmh: 30 }
  );

  unconditionalEvent.source = "diagnostic_import";
  const diagnostic = core.eventOverrideAssessment(unconditionalEvent);
  assert.deepEqual(
    { eligible: diagnostic.eligible, effect: diagnostic.effect },
    { eligible: false, effect: "none" }
  );

  unconditionalEvent.source = "unknown_source";
  const unknownSource = core.eventOverrideAssessment(unconditionalEvent);
  assert.deepEqual(
    { eligible: unknownSource.eligible, effect: unknownSource.effect },
    { eligible: false, effect: "none" }
  );

  const malformed = clone(recognitionEvents[1]);
  malformed.candidate.condition_state = "none";
  malformed.candidate.restrictions = [];
  malformed.candidate.value = "30";
  malformed.road_context.travel_direction = "sideways";
  assert.deepEqual(
    { eligible: core.eventOverrideAssessment(malformed).eligible, effect: core.eventOverrideAssessment(malformed).effect },
    { eligible: false, effect: "none" }
  );

  const missingLocalRevision = clone(recognitionEvents[1]);
  missingLocalRevision.candidate.condition_state = "none";
  missingLocalRevision.candidate.restrictions = [];
  delete missingLocalRevision.road_context.source_signature.local_correction_revision;
  assert.deepEqual(
    {
      eligible: core.eventOverrideAssessment(missingLocalRevision).eligible,
      effect: core.eventOverrideAssessment(missingLocalRevision).effect
    },
    { eligible: false, effect: "none" }
  );

  for (const missingField of ["condition_state", "restrictions"]) {
    const missingCandidateField = clone(recognitionEvents[1]);
    delete missingCandidateField.candidate[missingField];
    assert.deepEqual(
      {
        eligible: core.eventOverrideAssessment(missingCandidateField).eligible,
        effect: core.eventOverrideAssessment(missingCandidateField).effect
      },
      { eligible: false, effect: "none" },
      missingField
    );
  }

  const malformedLocalRevision = clone(recognitionEvents[1]);
  malformedLocalRevision.candidate.condition_state = "none";
  malformedLocalRevision.candidate.restrictions = [];
  malformedLocalRevision.road_context.source_signature.local_correction_revision = { bad: true };
  assert.deepEqual(
    {
      eligible: core.eventOverrideAssessment(malformedLocalRevision).eligible,
      effect: core.eventOverrideAssessment(malformedLocalRevision).effect
    },
    { eligible: false, effect: "none" }
  );
  assert.equal(core.eventGateAssessment([malformedLocalRevision]).passed, false);

  const fractionalSpeed = clone(recognitionEvents[1]);
  fractionalSpeed.candidate.value = 30.5;
  fractionalSpeed.candidate.condition_state = "none";
  fractionalSpeed.candidate.restrictions = [];
  assert.deepEqual(
    {
      eligible: core.eventOverrideAssessment(fractionalSpeed).eligible,
      effect: core.eventOverrideAssessment(fractionalSpeed).effect
    },
    { eligible: false, effect: "none" }
  );
  assert.ok(core.eventGateAssessment([fractionalSpeed]).issues.includes(
    "events[0].candidate.value must be an integer or null"
  ));

  const insufficientEvidence = clone(recognitionEvents[1]);
  insufficientEvidence.candidate.condition_state = "none";
  insufficientEvidence.candidate.restrictions = [];
  insufficientEvidence.candidate.evidence_frames = 0;
  assert.deepEqual(
    {
      eligible: core.eventOverrideAssessment(insufficientEvidence).eligible,
      effect: core.eventOverrideAssessment(insufficientEvidence).effect
    },
    { eligible: false, effect: "none" }
  );

  const malformedStillContext = clone(recognitionEvents[1]);
  malformedStillContext.source = "camera_still";
  malformedStillContext.road_context = { way_id: "123456" };
  assert.ok(core.eventGateAssessment([malformedStillContext]).issues.includes(
    "events[0].road_context is structurally invalid"
  ));
});
