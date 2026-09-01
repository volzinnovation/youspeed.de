(function initializeTSRQA() {
  "use strict";

  const core = window.YouSpeedTSRQACore;
  if (!core) {
    console.error("TSR QA core is unavailable.");
    return;
  }

  const byID = (id) => document.getElementById(id);
  const elements = {
    matcherMode: byID("matcher-mode-btn"),
    tsrMode: byID("tsr-mode-btn"),
    matcherPanel: byID("matcher-panel-content"),
    tsrPanel: byID("tsr-panel-content"),
    matcherWorkspace: byID("matcher-workspace"),
    workspace: byID("tsr-workspace"),
    modelTruth: byID("tsr-model-truth"),
    fixtureTruth: byID("tsr-fixture-truth"),
    intakeStatus: byID("tsr-intake-status"),
    loadFixture: byID("tsr-load-fixture-btn"),
    modelInput: byID("tsr-model-pack-input"),
    eventInput: byID("tsr-event-file-input"),
    bundleInput: byID("tsr-bundle-directory-input"),
    stateFilter: byID("tsr-state-filter"),
    reviewFilter: byID("tsr-review-filter"),
    summary: byID("tsr-summary"),
    overview: byID("tsr-overview"),
    queueSummary: byID("tsr-queue-summary"),
    queue: byID("tsr-queue"),
    evidenceTitle: byID("tsr-evidence-title"),
    evidenceSubtitle: byID("tsr-evidence-subtitle"),
    previous: byID("tsr-prev-btn"),
    next: byID("tsr-next-btn"),
    assetSelect: byID("tsr-asset-select"),
    showPredictions: byID("tsr-show-predictions"),
    showAnnotations: byID("tsr-show-annotations"),
    evidenceStage: byID("tsr-evidence-stage"),
    evidenceEmpty: byID("tsr-evidence-empty"),
    canvas: byID("tsr-evidence-canvas"),
    evidenceLegend: byID("tsr-evidence-legend"),
    eventTimeline: byID("tsr-event-timeline"),
    detailSummary: byID("tsr-detail-summary"),
    detailModel: byID("tsr-detail-model"),
    detailDetection: byID("tsr-detail-detection"),
    detailContext: byID("tsr-detail-context"),
    detailReview: byID("tsr-detail-review"),
    detailRaw: byID("tsr-detail-raw"),
    focusMap: byID("tsr-focus-map-btn"),
    verdictCorrect: byID("tsr-verdict-correct"),
    verdictReview: byID("tsr-verdict-review"),
    verdictReject: byID("tsr-verdict-reject"),
    reviewNote: byID("tsr-review-note"),
    exportReport: byID("tsr-export-report-btn")
  };

  if (!elements.workspace || !elements.queue || !elements.canvas) {
    console.error("TSR QA markup is incomplete.");
    return;
  }

  const fixtureURLs = {
    model: new URL("../shared/tsr/fixtures/de-direct-pack-v1.json", window.location.href),
    events: new URL("../shared/tsr/fixtures/recognition-events-v1.json", window.location.href),
    bundle: new URL("../shared/tsr/fixtures/diagnostic-bundle-v1/manifest.json", window.location.href)
  };
  const maximumRasterPixels = 20_000_000;
  const maximumRasterDimension = 8_192;
  const maximumAssetBytes = 64 * 1024 * 1024;
  const maximumP3Bytes = 16 * 1024 * 1024;
  const maximumP3Pixels = 250_000;

  const state = {
    mode: "matcher",
    bundle: null,
    bundleLabel: null,
    bundleManifestSha256: null,
    bundleBaseURL: null,
    bundleFiles: new Map(),
    assetBytes: new Map(),
    assetGate: { state: "idle", issues: [] },
    modelPack: null,
    modelLabel: null,
    modelManifestSha256: null,
    modelIsFixture: false,
    fixtureSetActive: false,
    events: [],
    eventsLabel: null,
    eventsFileSha256: null,
    selectedKey: null,
    selectedAssetPath: null,
    queueItems: [],
    filteredItems: [],
    raster: null,
    showPredictions: true,
    showAnnotations: true,
    decisions: new Map(),
    sourceLoadGeneration: 0,
    modelLoadGeneration: 0,
    eventLoadGeneration: 0,
    bundleLoadGeneration: 0,
    assetVerificationToken: 0,
    evidenceRenderToken: 0
  };

  function escapeHTML(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatTimestamp(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) {
      return "n/a";
    }
    return new Intl.DateTimeFormat("de-DE", {
      dateStyle: "short",
      timeStyle: "medium",
      timeZone: "UTC"
    }).format(date) + " UTC";
  }

  function formatPercent(value) {
    const numeric = core.finiteNumber(value);
    return numeric == null ? "n/a" : Math.round(numeric * 100) + "%";
  }

  function formatNumber(value, digits = 1) {
    const numeric = core.finiteNumber(value);
    return numeric == null ? "n/a" : numeric.toFixed(digits);
  }

  function shortHash(value) {
    const hash = core.safeString(value);
    if (!hash) {
      return "n/a";
    }
    return hash.length > 18 ? hash.slice(0, 10) + "…" + hash.slice(-6) : hash;
  }

  function statusPill(label, kind = "neutral") {
    return '<span class="pill ' + escapeHTML(kind) + '">' + escapeHTML(label) + "</span>";
  }

  function setIntakeStatus(message, kind = "neutral") {
    if (!elements.intakeStatus) {
      return;
    }
    elements.intakeStatus.textContent = message;
    elements.intakeStatus.dataset.state = kind;
    elements.intakeStatus.classList.toggle("error", kind === "error");
  }

  function renderKeyValues(container, rows) {
    if (!container) {
      return;
    }
    container.innerHTML = '<dl class="tsr-kv">' + rows
      .filter((row) => row && row[1] != null)
      .map((row) => (
        "<div><dt>" + escapeHTML(row[0]) + "</dt><dd>" + escapeHTML(row[1]) + "</dd></div>"
      ))
      .join("") + "</dl>";
  }

  function setMode(mode, options = {}) {
    state.mode = mode === "tsr" ? "tsr" : "matcher";
    const tsrActive = state.mode === "tsr";
    document.body.dataset.inspectorMode = state.mode;
    elements.matcherMode?.classList.toggle("active", !tsrActive);
    elements.tsrMode?.classList.toggle("active", tsrActive);
    elements.matcherMode?.setAttribute("aria-selected", String(!tsrActive));
    elements.tsrMode?.setAttribute("aria-selected", String(tsrActive));
    if (elements.matcherPanel) elements.matcherPanel.hidden = tsrActive;
    if (elements.tsrPanel) elements.tsrPanel.hidden = !tsrActive;
    if (elements.matcherWorkspace) elements.matcherWorkspace.hidden = tsrActive;
    elements.workspace.hidden = !tsrActive;
    if (!options.preserveHash) {
      history.replaceState(null, "", tsrActive ? "#tsr" : "#matcher");
    }
    if (!tsrActive) {
      window.YouSpeedInspectorBridge?.ensureMapTiles();
      window.setTimeout(() => window.YouSpeedInspectorBridge?.invalidateMap(), 0);
      void window.YouSpeedInspectorBridge?.ensureMatcherData();
    }
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("HTTP " + response.status + " for " + url.pathname);
    }
    const bytes = await response.arrayBuffer();
    const rawText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return {
      value: JSON.parse(rawText),
      sha256: await sha256Hex(bytes)
    };
  }

  function normalizeRelativePath(path) {
    return String(path ?? "").replaceAll("\\", "/").replace(/^\.?\//, "");
  }

  function clearFixtureSetForRealInput() {
    if (!state.fixtureSetActive) return;
    state.assetVerificationToken += 1;
    state.evidenceRenderToken += 1;
    state.raster?.bitmap?.close?.();
    state.raster = null;
    state.bundle = null;
    state.bundleLabel = null;
    state.bundleManifestSha256 = null;
    state.bundleBaseURL = null;
    state.bundleFiles = new Map();
    state.assetBytes = new Map();
    state.assetGate = { state: "idle", issues: [] };
    state.modelPack = null;
    state.modelLabel = null;
    state.modelManifestSha256 = null;
    state.modelIsFixture = false;
    state.events = [];
    state.eventsLabel = null;
    state.eventsFileSha256 = null;
    state.selectedKey = null;
    state.selectedAssetPath = null;
    state.decisions.clear();
    state.fixtureSetActive = false;
  }

  async function loadFixtureSet() {
    const loadGeneration = ++state.sourceLoadGeneration;
    state.modelLoadGeneration += 1;
    state.eventLoadGeneration += 1;
    state.bundleLoadGeneration += 1;
    setIntakeStatus("Synthetic QA fixture is loading…", "loading");
    try {
      const [modelResource, eventsResource, bundleResource] = await Promise.all([
        fetchJSON(fixtureURLs.model),
        fetchJSON(fixtureURLs.events),
        fetchJSON(fixtureURLs.bundle)
      ]);
      const modelPack = modelResource.value;
      const events = eventsResource.value;
      const bundle = bundleResource.value;
      if (loadGeneration !== state.sourceLoadGeneration) return;
      const fixtureModelGate = core.modelPackGateAssessment(modelPack);
      const fixtureEventGate = core.eventGateAssessment(events);
      const fixtureBundleGate = core.bundleGateAssessment(bundle);
      if (!fixtureModelGate.passed || !fixtureEventGate.passed || !fixtureBundleGate.contract.passed) {
        throw new Error("Repository TSR fixture failed contract preflight.");
      }
      state.modelPack = modelPack;
      state.modelLabel = "Repository contract fixture";
      state.modelManifestSha256 = modelResource.sha256;
      state.modelIsFixture = true;
      state.fixtureSetActive = true;
      state.events = Array.isArray(events) ? events : [];
      state.eventsLabel = "Repository recognition-event fixture";
      state.eventsFileSha256 = eventsResource.sha256;
      state.bundle = bundle;
      state.bundleLabel = "Repository diagnostic fixture";
      state.bundleManifestSha256 = bundleResource.sha256;
      state.bundleBaseURL = new URL("./", fixtureURLs.bundle);
      state.bundleFiles = new Map();
      state.assetBytes = new Map();
      state.selectedKey = null;
      state.selectedAssetPath = null;
      state.decisions.clear();
      renderAll();
      await verifyBundleAssets();
      if (loadGeneration !== state.sourceLoadGeneration) return;
      setIntakeStatus("Fixture loaded. It is synthetic and is not an active runtime model.", "fixture");
    } catch (error) {
      if (loadGeneration !== state.sourceLoadGeneration) return;
      setIntakeStatus("Fixture could not be loaded: " + error.message, "error");
    }
  }

  async function loadModelPackFile(file) {
    state.sourceLoadGeneration += 1;
    const loadGeneration = ++state.modelLoadGeneration;
    const bytes = await file.arrayBuffer();
    if (loadGeneration !== state.modelLoadGeneration) return null;
    const rawText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const modelPack = JSON.parse(rawText);
    if (modelPack?.schema_version !== 1 || !core.safeString(modelPack?.pack_id)) {
      throw new Error("This is not a TSR model-pack v1 manifest.");
    }
    const gate = core.modelPackGateAssessment(modelPack);
    if (!gate.passed) {
      throw new Error("Model manifest contract preflight failed: " + gate.issues[0]);
    }
    const manifestSha256 = await sha256Hex(bytes);
    if (loadGeneration !== state.modelLoadGeneration) return null;
    clearFixtureSetForRealInput();
    state.modelPack = modelPack;
    state.modelLabel = file.name + " · manifest only";
    state.modelManifestSha256 = manifestSha256;
    state.modelIsFixture = String(modelPack.pack_id).includes("fixture");
    state.selectedKey = null;
    state.selectedAssetPath = null;
    state.decisions.clear();
    renderAll();
    return gate;
  }

  async function loadEventFile(file) {
    state.sourceLoadGeneration += 1;
    const loadGeneration = ++state.eventLoadGeneration;
    const bytes = await file.arrayBuffer();
    if (loadGeneration !== state.eventLoadGeneration) return null;
    const rawText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const events = core.parseJSONOrNDJSON(rawText);
    if (!events.length) {
      throw new Error("The event file contains no entries.");
    }
    const gate = core.eventGateAssessment(events);
    if (!gate.passed) {
      throw new Error("Recognition-event contract preflight failed: " + gate.issues[0]);
    }
    const eventsSha256 = await sha256Hex(bytes);
    if (loadGeneration !== state.eventLoadGeneration) return null;
    clearFixtureSetForRealInput();
    state.events = events;
    state.eventsLabel = file.name;
    state.eventsFileSha256 = eventsSha256;
    state.selectedKey = null;
    state.selectedAssetPath = null;
    state.decisions.clear();
    renderAll();
    return gate;
  }

  async function loadBundleDirectory(files) {
    state.sourceLoadGeneration += 1;
    const loadGeneration = ++state.bundleLoadGeneration;
    const fileList = Array.from(files ?? []);
    const candidates = [];
    for (const file of fileList.filter((entry) => entry.name.toLowerCase().endsWith(".json"))) {
      try {
        const bytes = await file.arrayBuffer();
        const rawText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        const parsed = JSON.parse(rawText);
        if (parsed?.schema_version === 1 && Array.isArray(parsed?.samples) && parsed?.bundle_id) {
          candidates.push({ file, parsed, bytes });
        }
      } catch {
        // A non-manifest JSON file in the selected directory is irrelevant.
      }
    }
    if (loadGeneration !== state.bundleLoadGeneration) return null;
    if (candidates.length !== 1) {
      throw new Error(
        candidates.length
          ? "Select one diagnostic bundle directory at a time."
          : "No diagnostic manifest with samples was found in this directory."
      );
    }
    const { file: manifestFile, parsed: bundle, bytes: manifestBytes } = candidates[0];
    const manifestRelativePath = normalizeRelativePath(manifestFile.webkitRelativePath || manifestFile.name);
    const manifestSuffix = normalizeRelativePath(manifestFile.name);
    const rootPrefix = manifestRelativePath.endsWith(manifestSuffix)
      ? manifestRelativePath.slice(0, -manifestSuffix.length)
      : "";
    const assetFiles = new Map();
    for (const assetFile of fileList) {
      const relativePath = normalizeRelativePath(assetFile.webkitRelativePath || assetFile.name);
      const bundlePath = relativePath.startsWith(rootPrefix)
        ? relativePath.slice(rootPrefix.length)
        : relativePath;
      assetFiles.set(bundlePath, assetFile);
    }
    const manifestSha256 = await sha256Hex(manifestBytes);
    if (loadGeneration !== state.bundleLoadGeneration) return null;

    clearFixtureSetForRealInput();
    state.bundle = bundle;
    state.bundleLabel = manifestRelativePath || manifestFile.name;
    state.bundleManifestSha256 = manifestSha256;
    state.bundleBaseURL = null;
    state.bundleFiles = assetFiles;
    state.assetBytes = new Map();
    state.selectedKey = null;
    state.selectedAssetPath = null;
    state.decisions.clear();
    renderAll();
    await verifyBundleAssets();
    if (loadGeneration !== state.bundleLoadGeneration) return null;
    return core.bundleGateAssessment(bundle);
  }

  async function resolveAssetBytes(path) {
    const normalizedPath = normalizeRelativePath(path);
    if (!core.assetPathIsSafe(normalizedPath)) {
      throw new Error("Unsafe asset path: " + normalizedPath);
    }
    if (state.assetBytes.has(normalizedPath)) {
      return state.assetBytes.get(normalizedPath);
    }
    let promise;
    const localFile = state.bundleFiles.get(normalizedPath);
    if (localFile) {
      if (localFile.size > maximumAssetBytes) {
        throw new Error("Asset exceeds the 64 MiB QA safety limit: " + normalizedPath);
      }
      promise = localFile.arrayBuffer();
    } else if (state.bundleBaseURL) {
      promise = fetch(new URL(normalizedPath, state.bundleBaseURL)).then((response) => {
        if (!response.ok) {
          throw new Error("HTTP " + response.status + " for " + normalizedPath);
        }
        const declaredLength = Number(response.headers.get("content-length"));
        if (Number.isFinite(declaredLength) && declaredLength > maximumAssetBytes) {
          throw new Error("Asset exceeds the 64 MiB QA safety limit: " + normalizedPath);
        }
        return response.arrayBuffer();
      });
    } else {
      throw new Error("Asset was not included in the selected directory: " + normalizedPath);
    }
    promise = promise.then((bytes) => {
      if (bytes.byteLength > maximumAssetBytes) {
        throw new Error("Asset exceeds the 64 MiB QA safety limit: " + normalizedPath);
      }
      return bytes;
    });
    state.assetBytes.set(normalizedPath, promise);
    while (state.assetBytes.size > 2) {
      state.assetBytes.delete(state.assetBytes.keys().next().value);
    }
    void promise.catch(() => {
      if (state.assetBytes.get(normalizedPath) === promise) {
        state.assetBytes.delete(normalizedPath);
      }
    });
    return promise;
  }

  async function sha256Hex(bytes) {
    if (!window.crypto?.subtle) {
      throw new Error("WebCrypto SHA-256 is unavailable in this browser context.");
    }
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function verifyBundleAssets() {
    if (!state.bundle) {
      state.assetGate = { state: "idle", issues: [] };
      renderOverview();
      return;
    }
    const verificationToken = ++state.assetVerificationToken;
    state.assetGate = { state: "checking", issues: [] };
    renderOverview();
    const issues = [];
    const samples = Array.isArray(state.bundle.samples) ? state.bundle.samples : [];
    const assets = samples.flatMap((sample) => Array.isArray(sample?.assets) ? sample.assets : []);
    for (const asset of assets) {
      try {
        const path = core.safeString(asset?.path);
        if (!path) throw new Error("Asset path is missing.");
        const bytes = await resolveAssetBytes(path);
        const digest = await sha256Hex(bytes);
        if (digest.toLowerCase() !== String(asset.sha256 ?? "").toLowerCase()) {
          issues.push(path + ": SHA-256 mismatch");
          continue;
        }
        const raster = await decodeRaster(bytes, asset);
        raster.bitmap?.close?.();
      } catch (error) {
        issues.push((core.safeString(asset?.path) ?? "invalid asset") + ": " + error.message);
      }
    }
    if (verificationToken !== state.assetVerificationToken) {
      return;
    }
    state.assetGate = {
      state: issues.length ? "failed" : "passed",
      issues
    };
    renderOverview();
    renderReview();
  }

  function eventItem(event, index) {
    const timestamp = core.safeString(event?.frame_timestamp_utc) ?? "unknown-time";
    return {
      kind: "event",
      key: "event:" + index + ":" + timestamp,
      label: core.safeString(event?.candidate?.raw_label) ?? core.safeString(event?.state) ?? "Event",
      timestamp,
      event,
      sourceIndex: index
    };
  }

  function sampleItem(sample, index) {
    return {
      kind: "sample",
      key: "sample:" + index + ":" + (core.safeString(sample?.sample_id) ?? "missing-id"),
      label: core.safeString(sample?.sample_id) ?? "Sample " + (index + 1),
      timestamp: core.safeString(sample?.frame_timestamp_utc) ?? "unknown-time",
      sample,
      sourceIndex: index
    };
  }

  function allItems() {
    const samples = Array.isArray(state.bundle?.samples) ? state.bundle.samples : [];
    const sampleItems = samples.map(sampleItem);
    if (!samples.length) return state.events.map(eventItem);

    const eventIndexByObject = new Map(state.events.map((event, index) => [event, index]));
    const eventsByRoad = new Map();
    state.events.forEach((event) => {
      const context = event?.road_context;
      const wayID = core.safeString(context?.way_id);
      const direction = core.safeString(context?.travel_direction);
      if (!wayID || !direction) return;
      const key = wayID + "\u0000" + direction;
      const entries = eventsByRoad.get(key) ?? [];
      entries.push(event);
      eventsByRoad.set(key, entries);
    });
    const linkedEventIndices = new Set();
    samples.forEach((sample) => {
      const context = sample?.capture_context;
      const wayID = core.safeString(context?.way_id);
      const direction = core.safeString(context?.travel_direction);
      if (!wayID || !direction) return;
      const candidates = eventsByRoad.get(wayID + "\u0000" + direction) ?? [];
      core.relatedEventsForSample(sample, candidates, 1.5, state.bundle?.active_model ?? null)
        .forEach((event) => linkedEventIndices.add(eventIndexByObject.get(event)));
    });
    const unlinkedEventItems = state.events
      .map((event, index) => ({ event, index }))
      .filter(({ index }) => !linkedEventIndices.has(index))
      .map(({ event, index }) => eventItem(event, index));
    return sampleItems.concat(unlinkedEventItems);
  }

  function relatedEvents(item) {
    if (!item) {
      return [];
    }
    if (item.kind === "event") {
      return [item.event];
    }
    return core.relatedEventsForSample(item.sample, state.events, 1.5, state.bundle?.active_model ?? null);
  }

  function itemContext(item) {
    if (!item) {
      return null;
    }
    if (item.kind === "event") {
      return item.event?.road_context ?? null;
    }
    const context = item.sample?.capture_context;
    if (!context) {
      return null;
    }
    return {
      way_id: context.way_id,
      latitude: context.latitude,
      longitude: context.longitude,
      heading_degrees: context.heading_degrees,
      travel_direction: context.travel_direction,
      source_signature: {
        osm_revision: context.map_source_signature,
        local_correction_revision: null
      }
    };
  }

  function itemReviewState(item) {
    if (item?.kind === "sample") {
      return core.safeString(item.sample?.annotation?.status) ?? "unreviewed";
    }
    return "event_only";
  }

  function itemEventState(item) {
    const events = relatedEvents(item);
    return core.safeString(events.at(-1)?.state) ?? "no_event";
  }

  function itemNeedsReview(item) {
    if (item?.kind === "sample") {
      return core.sampleAssessment(item.sample).issues.length > 0;
    }
    return !core.eventGateAssessment([item?.event]).passed;
  }

  function contractPreflight() {
    const assessments = [];
    if (state.bundle) assessments.push(core.bundleGateAssessment(state.bundle).contract);
    if (state.eventsLabel || state.events.length) assessments.push(core.eventGateAssessment(state.events));
    if (state.modelPack) assessments.push(core.modelPackGateAssessment(state.modelPack));
    if (!assessments.length) return null;
    const issues = assessments.flatMap((assessment) => assessment.issues);
    return { passed: assessments.every((assessment) => assessment.passed), issues };
  }

  function applyFilters(items) {
    const stateFilter = elements.stateFilter?.value ?? "all";
    const reviewFilter = elements.reviewFilter?.value ?? "all";
    return items.filter((item) => {
      if (stateFilter !== "all" && itemEventState(item) !== stateFilter) {
        return false;
      }
      const decision = state.decisions.get(item.key);
      if (reviewFilter === "open" && decision) {
        return false;
      }
      if (["correct", "review", "reject"].includes(reviewFilter)
          && decision?.verdict !== reviewFilter) {
        return false;
      }
      return true;
    });
  }

  function selectedItem() {
    return state.filteredItems.find((item) => item.key === state.selectedKey) ?? state.filteredItems[0] ?? null;
  }

  function ensureSelection() {
    if (!state.filteredItems.some((item) => item.key === state.selectedKey)) {
      state.selectedKey = state.filteredItems[0]?.key ?? null;
      state.selectedAssetPath = null;
    }
  }

  function renderModelTruth() {
    const pack = state.modelPack;
    if (elements.modelTruth) {
      elements.modelTruth.textContent = "No installed model · inspector only";
      elements.modelTruth.className = "truth-badge inactive";
    }
    if (elements.fixtureTruth) {
      if (!pack) {
        elements.fixtureTruth.textContent = "No model manifest loaded";
        elements.fixtureTruth.className = "truth-badge inactive";
      } else if (state.modelIsFixture) {
        elements.fixtureTruth.textContent = "Fixture · unsigned · no artifact";
        elements.fixtureTruth.className = "truth-badge fixture";
      } else {
        const signatureState = pack.signature ? "signature declared" : "unsigned";
        elements.fixtureTruth.textContent = "Manifest only · " + signatureState;
        elements.fixtureTruth.className = "truth-badge " + (pack.signature ? "fixture" : "inactive");
      }
    }
  }

  function renderOverview() {
    const summary = core.summarize(state.bundle, state.events);
    const gates = state.bundle ? core.bundleGateAssessment(state.bundle) : null;
    const preflight = contractPreflight();
    const provenance = core.provenanceAssessment(state.bundle, state.events, state.modelPack);
    const provenanceIsComparable = Boolean(
      (state.bundle?.active_model && state.modelPack)
      || (state.events.length && (state.bundle?.active_model || state.modelPack))
    );
    const gatePill = (label, gate) => {
      if (!gate) return statusPill(label + " n/a", "neutral");
      return statusPill(label + " " + (gate.passed ? "pass" : "fail"), gate.passed ? "ok" : "error");
    };
    const assetPill = state.assetGate.state === "passed"
      ? statusPill("assets pass", "ok")
      : state.assetGate.state === "failed"
        ? statusPill("assets fail", "error")
        : state.assetGate.state === "checking"
          ? statusPill("assets checking", "warn")
          : statusPill("assets n/a", "neutral");
    if (elements.summary) {
      elements.summary.textContent = summary.samples + " samples";
    }
    if (elements.overview) {
      const cards = [
        ["Samples", summary.samples],
        ["Needs review", summary.reviewSamples],
        ["Events", summary.events],
        ["Unlinked events", state.queueItems.filter((item) => item.kind === "event").length],
        ["Confirmed", summary.confirmedEvents],
        ["Avg. calibrated", summary.averageConfidence == null ? "n/a" : formatPercent(summary.averageConfidence)]
      ];
      const gateRow = '<div class="tsr-gate-row">' + [
        gatePill("contract preflight", preflight),
        gatePill("privacy", gates?.privacy),
        assetPill,
        gatePill("provenance", provenanceIsComparable ? provenance : null),
        statusPill(state.modelPack?.signature ? "signature declared" : "trust not verified", "warn"),
        statusPill("release not evidenced", "neutral")
      ].join(" ") + "</div>";
      elements.overview.innerHTML = gateRow + cards.map((card) => (
        '<div class="tsr-overview-stat"><strong>' + escapeHTML(card[1])
        + '</strong><span>' + escapeHTML(card[0]) + "</span></div>"
      )).join("");
    }
  }

  function renderQueue() {
    state.filteredItems = applyFilters(state.queueItems);
    ensureSelection();
    if (elements.queueSummary) {
      elements.queueSummary.textContent = state.filteredItems.length
        ? state.filteredItems.length + " QA items · keyboard ←/→"
        : "No items match the current filters.";
    }
    elements.queue.innerHTML = state.filteredItems.map((item) => {
      const active = item.key === state.selectedKey;
      const reviewState = itemReviewState(item);
      const eventState = itemEventState(item);
      const issue = itemNeedsReview(item);
      const decision = state.decisions.get(item.key);
      const context = itemContext(item);
      const wayID = core.safeString(context?.way_id);
      return '<button type="button" class="tsr-queue-item' + (active ? " active" : "")
        + '" role="option" aria-selected="' + String(active) + '" data-tsr-item-key="' + escapeHTML(item.key) + '">'
        + '<span class="tsr-queue-item-title"><strong>' + escapeHTML(item.label) + "</strong>"
        + statusPill(eventState.replaceAll("_", " "), eventState === "confirmed" ? "ok" : "neutral")
        + "</span>"
        + '<span class="tsr-queue-item-meta"><span>' + escapeHTML(formatTimestamp(item.timestamp))
        + (wayID ? " · way " + escapeHTML(wayID) : "") + "</span><span>"
        + statusPill(reviewState, "neutral")
        + (decision ? statusPill("QA " + decision.verdict, decision.verdict === "correct" ? "ok" : decision.verdict === "reject" ? "error" : "warn") : "")
        + (issue ? statusPill("inspect", "warn") : statusPill("aligned", "ok")) + "</span></span>"
        + "</button>";
    }).join("");
  }

  function setAssetOptions(item) {
    if (!elements.assetSelect) {
      return;
    }
    const assets = item?.kind === "sample" && Array.isArray(item.sample?.assets)
      ? item.sample.assets.filter((asset) => core.safeString(asset?.path))
      : [];
    if (!assets.length) {
      elements.assetSelect.innerHTML = '<option value="">No retained image</option>';
      elements.assetSelect.disabled = true;
      state.selectedAssetPath = null;
      return;
    }
    if (!assets.some((asset) => asset.path === state.selectedAssetPath)) {
      const preferred = assets.find((asset) => asset.role === "full_frame") ?? assets[0];
      state.selectedAssetPath = preferred.path;
    }
    elements.assetSelect.disabled = false;
    elements.assetSelect.innerHTML = assets.map((asset) => (
      '<option value="' + escapeHTML(asset.path) + '"'
      + (asset.path === state.selectedAssetPath ? " selected" : "") + ">"
      + escapeHTML((asset.role ?? "asset") + " · " + asset.path) + "</option>"
    )).join("");
  }

  function selectedAsset(item) {
    if (item?.kind !== "sample") {
      return null;
    }
    const assets = Array.isArray(item.sample?.assets) ? item.sample.assets : [];
    return assets.find((asset) => asset?.path === state.selectedAssetPath) ?? null;
  }

  function ppmTokens(bytes) {
    const text = new TextDecoder("ascii").decode(bytes);
    return text.replace(/#[^\r\n]*/g, " ").trim().split(/\s+/);
  }

  function validateRasterDimensions(width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height)
        || width <= 0 || height <= 0
        || width > maximumRasterDimension || height > maximumRasterDimension
        || width * height > maximumRasterPixels) {
      throw new Error("Raster dimensions are invalid or exceed the QA safety limit.");
    }
  }

  function requireManifestDimensions(width, height, asset) {
    if (Number.isInteger(asset?.width) && Number.isInteger(asset?.height)
        && (width !== asset.width || height !== asset.height)) {
      throw new Error(`Decoded dimensions ${width}×${height} do not match manifest ${asset.width}×${asset.height}.`);
    }
  }

  function decodeP3(bytes) {
    if (bytes.byteLength > maximumP3Bytes) {
      throw new Error("P3 evidence exceeds the 16 MiB safety limit; use P6, JPEG, or PNG.");
    }
    const tokens = ppmTokens(bytes);
    if (tokens.shift() !== "P3") {
      throw new Error("Only P3/P6 PPM is supported.");
    }
    const width = Number(tokens.shift());
    const height = Number(tokens.shift());
    const maximum = Number(tokens.shift());
    validateRasterDimensions(width, height);
    if (width * height > maximumP3Pixels) {
      throw new Error("P3 evidence exceeds the 250,000-pixel safety limit; use P6, JPEG, or PNG.");
    }
    if (!Number.isInteger(maximum) || maximum <= 0 || maximum > 65_535) {
      throw new Error("Invalid PPM header.");
    }
    const expectedSamples = width * height * 3;
    if (tokens.length !== expectedSamples) {
      throw new Error(`P3 raster has ${tokens.length} samples; expected ${expectedSamples}.`);
    }
    const samples = tokens.map((token) => Number(token));
    if (samples.some((sample) => !Number.isInteger(sample) || sample < 0 || sample > maximum)) {
      throw new Error("P3 raster contains an invalid sample value.");
    }
    const rgba = new Uint8ClampedArray(width * height * 4);
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      rgba[pixel * 4] = Math.round(samples[pixel * 3] * 255 / maximum);
      rgba[pixel * 4 + 1] = Math.round(samples[pixel * 3 + 1] * 255 / maximum);
      rgba[pixel * 4 + 2] = Math.round(samples[pixel * 3 + 2] * 255 / maximum);
      rgba[pixel * 4 + 3] = 255;
    }
    return { width, height, imageData: new ImageData(rgba, width, height) };
  }

  function readPPMToken(bytes, cursor) {
    const data = new Uint8Array(bytes);
    let index = cursor;
    while (index < data.length) {
      if (data[index] === 35) {
        while (index < data.length && data[index] !== 10 && data[index] !== 13) index += 1;
      } else if (data[index] <= 32) {
        index += 1;
      } else {
        break;
      }
    }
    const start = index;
    while (index < data.length && data[index] > 32 && data[index] !== 35) index += 1;
    return { token: new TextDecoder("ascii").decode(data.slice(start, index)), cursor: index };
  }

  function decodeP6(bytes) {
    let cursor = 0;
    const magic = readPPMToken(bytes, cursor); cursor = magic.cursor;
    const widthToken = readPPMToken(bytes, cursor); cursor = widthToken.cursor;
    const heightToken = readPPMToken(bytes, cursor); cursor = heightToken.cursor;
    const maximumToken = readPPMToken(bytes, cursor); cursor = maximumToken.cursor;
    if (magic.token !== "P6") throw new Error("Invalid binary PPM.");
    const width = Number(widthToken.token);
    const height = Number(heightToken.token);
    const maximum = Number(maximumToken.token);
    const data = new Uint8Array(bytes);
    if (cursor >= data.length) {
      throw new Error("P6 raster is missing its pixel payload.");
    }
    if (data[cursor] === 13 && data[cursor + 1] === 10) {
      cursor += 2;
    } else if (data[cursor] <= 32) {
      cursor += 1;
    } else {
      throw new Error("P6 header is not separated from its pixel payload.");
    }
    validateRasterDimensions(width, height);
    if (!Number.isInteger(maximum) || maximum <= 0 || maximum > 255) {
      throw new Error("Invalid PPM header.");
    }
    const expectedBytes = width * height * 3;
    if (data.length - cursor !== expectedBytes) {
      throw new Error(`P6 raster has ${data.length - cursor} bytes; expected ${expectedBytes}.`);
    }
    for (let index = cursor; index < data.length; index += 1) {
      if (data[index] > maximum) throw new Error("P6 raster contains a sample above maxval.");
    }
    const rgba = new Uint8ClampedArray(width * height * 4);
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      rgba[pixel * 4] = Math.round((data[cursor++] ?? 0) * 255 / maximum);
      rgba[pixel * 4 + 1] = Math.round((data[cursor++] ?? 0) * 255 / maximum);
      rgba[pixel * 4 + 2] = Math.round((data[cursor++] ?? 0) * 255 / maximum);
      rgba[pixel * 4 + 3] = 255;
    }
    return { width, height, imageData: new ImageData(rgba, width, height) };
  }

  async function decodeRaster(bytes, asset) {
    const data = new Uint8Array(bytes);
    const magic = String.fromCharCode(data[0] ?? 0, data[1] ?? 0);
    if (magic === "P3" || magic === "P6") {
      const raster = magic === "P3" ? decodeP3(bytes) : decodeP6(bytes);
      requireManifestDimensions(raster.width, raster.height, asset);
      return raster;
    }
    const blob = new Blob([bytes], { type: asset?.media_type ?? "application/octet-stream" });
    try {
      const bitmap = await createImageBitmap(blob);
      try {
        validateRasterDimensions(bitmap.width, bitmap.height);
        requireManifestDimensions(bitmap.width, bitmap.height, asset);
      } catch (error) {
        bitmap.close?.();
        throw error;
      }
      return { width: bitmap.width, height: bitmap.height, bitmap };
    } catch {
      throw new Error("This browser cannot decode " + (asset?.media_type ?? asset?.path ?? "the image") + ".");
    }
  }

  function boxForAsset(rawBox, asset) {
    const box = core.normalizedBox(rawBox);
    if (!box) {
      return null;
    }
    if (asset?.role === "full_frame" || !asset?.source_bounding_box) {
      return box;
    }
    const source = core.normalizedBox(asset.source_bounding_box);
    if (!source) {
      return null;
    }
    const x1 = Math.max(box.x, source.x);
    const y1 = Math.max(box.y, source.y);
    const x2 = Math.min(box.x + box.width, source.x + source.width);
    const y2 = Math.min(box.y + box.height, source.y + source.height);
    if (x2 <= x1 || y2 <= y1) {
      return null;
    }
    return {
      x: (x1 - source.x) / source.width,
      y: (y1 - source.y) / source.height,
      width: (x2 - x1) / source.width,
      height: (y2 - y1) / source.height
    };
  }

  function drawBoxes(context, width, height, items, asset, style) {
    context.save();
    context.font = "600 " + Math.max(11, Math.round(width / 70)) + "px SFMono-Regular, monospace";
    context.lineWidth = Math.max(2, width / 360);
    context.setLineDash(style.dash ?? []);
    for (const item of items) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      const box = boxForAsset(item.bounding_box, asset);
      if (!box) continue;
      const x = box.x * width;
      const y = box.y * height;
      const boxWidth = box.width * width;
      const boxHeight = box.height * height;
      context.fillStyle = style.fill;
      context.fillRect(x, y, boxWidth, boxHeight);
      context.strokeStyle = style.stroke;
      context.strokeRect(x, y, boxWidth, boxHeight);
      const label = core.safeString(item.raw_class_id ?? item.class_id ?? item.role) ?? "object";
      const metrics = context.measureText(label);
      const labelHeight = Math.max(18, width / 42);
      const labelY = Math.max(0, y - labelHeight);
      context.fillStyle = style.stroke;
      context.fillRect(x, labelY, metrics.width + 12, labelHeight);
      context.fillStyle = "#071018";
      context.fillText(label, x + 6, labelY + labelHeight * 0.72);
    }
    context.restore();
  }

  function paintEvidence(item, asset) {
    if (!state.raster || !item || item.kind !== "sample") {
      return;
    }
    const naturalWidth = state.raster.width;
    const naturalHeight = state.raster.height;
    const scale = naturalWidth < 320 ? Math.min(120, 640 / naturalWidth) : 1;
    const width = Math.round(naturalWidth * scale);
    const height = Math.round(naturalHeight * scale);
    elements.canvas.width = width;
    elements.canvas.height = height;
    const context = elements.canvas.getContext("2d");
    context.clearRect(0, 0, width, height);
    context.imageSmoothingEnabled = naturalWidth >= 64;
    if (state.raster.bitmap) {
      context.drawImage(state.raster.bitmap, 0, 0, width, height);
    } else {
      const sourceCanvas = document.createElement("canvas");
      sourceCanvas.width = naturalWidth;
      sourceCanvas.height = naturalHeight;
      sourceCanvas.getContext("2d").putImageData(state.raster.imageData, 0, 0);
      context.drawImage(sourceCanvas, 0, 0, width, height);
    }
    if (state.showPredictions) {
      drawBoxes(context, width, height, Array.isArray(item.sample?.predictions) ? item.sample.predictions : [], asset, {
        stroke: "#ffb454",
        fill: "rgba(255,180,84,0.12)",
        dash: [10, 6]
      });
    }
    if (state.showAnnotations) {
      drawBoxes(context, width, height, Array.isArray(item.sample?.annotation?.objects) ? item.sample.annotation.objects : [], asset, {
        stroke: "#7fda8b",
        fill: "rgba(127,218,139,0.10)",
        dash: []
      });
    }
  }

  async function renderEvidence() {
    const token = ++state.evidenceRenderToken;
    const item = selectedItem();
    setAssetOptions(item);
    const asset = selectedAsset(item);
    elements.evidenceStage?.setAttribute("aria-busy", asset ? "true" : "false");
    if (elements.evidenceTitle) {
      elements.evidenceTitle.textContent = item?.label ?? "No TSR evidence";
    }
    if (elements.evidenceSubtitle) {
      elements.evidenceSubtitle.textContent = item
        ? formatTimestamp(item.timestamp) + " · " + (state.bundleLabel ?? state.eventsLabel ?? "local input")
        : "Load a diagnostic bundle directory or recognition-event file.";
    }
    if (elements.previous) elements.previous.disabled = !item || state.filteredItems.length < 2;
    if (elements.next) elements.next.disabled = !item || state.filteredItems.length < 2;
    if (!asset) {
      state.raster?.bitmap?.close?.();
      state.raster = null;
      elements.canvas.hidden = true;
      if (elements.evidenceEmpty) {
        elements.evidenceEmpty.hidden = false;
        elements.evidenceEmpty.textContent = item?.kind === "event"
          ? "Event-only QA: this recognition event intentionally contains no pixels."
          : "No retained image is available for this sample.";
      }
      if (elements.evidenceLegend) {
        elements.evidenceLegend.innerHTML = statusPill("No pixels retained", "neutral");
      }
      elements.evidenceStage?.setAttribute("aria-busy", "false");
      return;
    }

    elements.canvas.hidden = true;
    if (elements.evidenceEmpty) {
      elements.evidenceEmpty.hidden = false;
      elements.evidenceEmpty.textContent = "Decoding " + asset.path + "…";
    }
    try {
      const bytes = await resolveAssetBytes(asset.path);
      const raster = await decodeRaster(bytes, asset);
      if (token !== state.evidenceRenderToken) {
        raster.bitmap?.close?.();
        return;
      }
      state.raster?.bitmap?.close?.();
      state.raster = raster;
      elements.canvas.hidden = false;
      if (elements.evidenceEmpty) elements.evidenceEmpty.hidden = true;
      paintEvidence(item, asset);
      if (elements.evidenceLegend) {
        elements.evidenceLegend.innerHTML = [
          state.showPredictions ? '<span class="tsr-legend prediction">Prediction</span>' : "",
          state.showAnnotations ? '<span class="tsr-legend annotation">Annotation</span>' : "",
          '<span class="muted">' + escapeHTML(raster.width + "×" + raster.height + " source") + "</span>"
        ].join(" ");
      }
      elements.evidenceStage?.setAttribute("aria-busy", "false");
    } catch (error) {
      if (token !== state.evidenceRenderToken) return;
      state.raster?.bitmap?.close?.();
      state.raster = null;
      elements.canvas.hidden = true;
      if (elements.evidenceEmpty) {
        elements.evidenceEmpty.hidden = false;
        elements.evidenceEmpty.textContent = error.message;
      }
      elements.evidenceStage?.setAttribute("aria-busy", "false");
    }
  }

  function renderTimeline(item) {
    if (!elements.eventTimeline) {
      return;
    }
    const events = relatedEvents(item);
    if (!events.length) {
      elements.eventTimeline.innerHTML = '<p class="trace-empty">No recognition event is linked to this frame.</p>';
      return;
    }
    elements.eventTimeline.innerHTML = events.map((event) => {
      const candidate = event?.candidate;
      const assessment = core.eventOverrideAssessment(event);
      const effectKind = assessment.effect === "set" ? "ok" : assessment.effect === "clear" ? "warn" : "neutral";
      return '<div class="tsr-event-step">'
        + '<span class="tsr-event-time">' + escapeHTML(formatTimestamp(event?.frame_timestamp_utc)) + "</span>"
        + '<span class="tsr-event-main"><strong>' + escapeHTML(event?.state ?? "unknown")
        + (candidate?.value ? " · " + escapeHTML(candidate.value + " " + (candidate.unit ?? "")) : "")
        + '</strong><span class="muted">'
        + escapeHTML((candidate?.raw_class_id ?? "no candidate")
          + (candidate?.evidence_frames ? " · " + candidate.evidence_frames + " frames" : "")
          + (event?.latency_ms != null ? " · " + formatNumber(event.latency_ms) + " ms" : ""))
        + "</span></span>"
        + statusPill(assessment.effect === "set" ? "override eligible" : assessment.effect, effectKind)
        + "</div>";
    }).join("");
  }

  function modelArtifacts(pack) {
    return [pack?.detector, pack?.classifier].flatMap((component) => (
      Array.isArray(component?.artifacts)
        ? component.artifacts
          .filter((artifact) => artifact && typeof artifact === "object" && !Array.isArray(artifact))
          .map((artifact) => ({ ...artifact, component_id: component.component_id }))
        : []
    ));
  }

  function renderModelDetails(item) {
    const pack = state.modelPack;
    const latestEvent = item?.kind === "event" ? item.event : relatedEvents(item).at(-1);
    const evidenceModel = state.bundle?.active_model ?? (latestEvent ? core.identityFromEvent(latestEvent) : null);
    const provenance = core.provenanceAssessment(state.bundle, state.events, pack);
    if (!elements.detailModel) return;
    if (!pack && !evidenceModel) {
      elements.detailModel.innerHTML = '<p class="trace-empty">No model-pack manifest loaded.</p>';
      return;
    }
    const artifacts = modelArtifacts(pack);
    const producerPlatform = state.bundle?.producer?.platform === "desktop"
      ? "reference"
      : state.bundle?.producer?.platform;
    const evidenceArtifact = artifacts.find((artifact) => artifact.sha256 === evidenceModel?.artifact_sha256
      && (!producerPlatform || artifact.platform === producerPlatform)) ?? null;
    const artifactDescription = evidenceArtifact
      ? [evidenceArtifact.component_id, evidenceArtifact.platform, evidenceArtifact.format, evidenceArtifact.precision].filter(Boolean).join(" · ")
      : artifacts.length
        ? artifacts.map((artifact) => [artifact.component_id, artifact.platform, artifact.format].filter(Boolean).join("/")).join(", ")
        : "not loaded";
    const input = pack?.preprocessing
      ? pack.preprocessing.input_width + "×" + pack.preprocessing.input_height + " · " + pack.preprocessing.resize
      : null;
    renderKeyValues(elements.detailModel, [
      ["Runtime state", "No installed model; inspector input only"],
      ["Manifest SHA", shortHash(state.modelManifestSha256)],
      ["Evidence pack", evidenceModel?.pack_id ?? "n/a"],
      ["Manifest pack", pack?.pack_id ?? "not loaded"],
      ["Provenance", provenance.passed ? "reconciled" : "mismatch · inspect QA flags"],
      ["Input", input],
      ["Pipeline", pack?.pipeline],
      ["Taxonomy", pack?.taxonomy_version],
      ["Artifact", artifactDescription],
      ["Evidence artifact SHA", shortHash(evidenceModel?.artifact_sha256)],
      ["Preprocessing", evidenceModel?.preprocessing_version ?? pack?.preprocessing?.version],
      ["Calibration", pack?.calibration?.calibrated === true ? pack.calibration.kind + " · declared calibrated" : "not calibrated / unknown"],
      ["Confirmation", pack?.thresholds ? pack.thresholds.confirmation_frames + " frames / " + pack.thresholds.confirmation_window_ms + " ms" : null],
      ["Parity", evidenceArtifact?.parity ? (evidenceArtifact.parity.passed ? "declared pass" : "declared fail") + " · max Δ " + evidenceArtifact.parity.measured_max_abs_difference : null],
      ["Source checkpoint", pack?.detector?.source_checkpoint ? pack.detector.source_checkpoint.revision + " · " + shortHash(pack.detector.source_checkpoint.sha256) : null],
      ["Exporter", evidenceArtifact?.exporter ? evidenceArtifact.exporter.name + " " + evidenceArtifact.exporter.version : null],
      ["Training run", pack?.lineage?.training_run_id],
      ["Evaluation", shortHash(pack?.lineage?.evaluation_report_sha256)],
      ["License", Array.isArray(pack?.licenses) ? pack.licenses.map((license) => license?.spdx ?? license?.name ?? "invalid").join(", ") : null],
      ["Minimum app", pack?.minimum_app_version],
      ["Signature", pack?.signature ? "declared; not browser-verified" : "none"],
      ["Source", state.modelLabel ?? "bundle identity only"]
    ]);
  }

  function renderDetection(item) {
    if (!elements.detailDetection) return;
    const events = relatedEvents(item);
    const latest = events.at(-1);
    const predictions = item?.kind === "sample" && Array.isArray(item.sample?.predictions) ? item.sample.predictions : [];
    const candidate = latest?.candidate;
    const restrictions = Array.isArray(candidate?.restrictions) ? candidate.restrictions : [];
    const rows = [
      ["State", latest?.state ?? (predictions.length ? "diagnostic predictions" : "n/a")],
      ["Class", candidate?.raw_class_id ?? (predictions.map((prediction) => prediction?.raw_class_id ?? "invalid").join(", ") || "n/a")],
      ["Semantic", candidate?.semantic_kind],
      ["Value", candidate?.value != null ? candidate.value + " " + (candidate.unit ?? "") : null],
      ["Raw score", candidate?.raw_score != null ? formatNumber(candidate.raw_score, 3) + " · not a probability" : null],
      ["Calibrated confidence", candidate?.calibrated_confidence != null ? formatPercent(candidate.calibrated_confidence) : null],
      ["Track / evidence", candidate?.track_id ? candidate.track_id + " · " + (candidate.evidence_frames ?? 0) + " frames" : null],
      ["Assembly", candidate?.assembly_id],
      ["Condition", candidate?.condition_state],
      ["Restrictions", restrictions.length ? restrictions.map((entry) => (entry?.kind ?? "invalid") + "=" + (entry?.normalized_value ?? "invalid")).join(", ") : "none"],
      ["Latency / thermal", latest ? formatNumber(latest.latency_ms) + " ms · " + (latest.thermal_state ?? "n/a") : null]
    ];
    renderKeyValues(elements.detailDetection, rows);
  }

  function renderContext(item) {
    const context = itemContext(item);
    if (!elements.detailContext) return;
    if (!context) {
      elements.detailContext.innerHTML = '<p class="trace-empty">No frame-time road context.</p>';
      if (elements.focusMap) elements.focusMap.disabled = true;
      return;
    }
    const sampleContext = item?.kind === "sample" ? item.sample?.capture_context : null;
    renderKeyValues(elements.detailContext, [
      ["Way ID", context.way_id],
      ["Coordinate", formatNumber(context.latitude, 6) + ", " + formatNumber(context.longitude, 6)],
      ["Heading", formatNumber(context.heading_degrees, 1) + "° · " + (context.travel_direction ?? "unknown")],
      ["Frame speed", sampleContext?.speed_kmh != null ? formatNumber(sampleContext.speed_kmh) + " km/h" : null],
      ["Map generation", sampleContext?.map_context_revision],
      ["OSM/source revision", context.source_signature?.osm_revision],
      ["Local correction revision", context.source_signature?.local_correction_revision ?? "none"],
      ["Context complete", sampleContext ? String(sampleContext.road_context_complete === true) : String(core.eventContextIsComplete(context))]
    ]);
    if (elements.focusMap) elements.focusMap.disabled = false;
  }

  function renderReview() {
    const item = selectedItem();
    if (!elements.detailReview) return;
    const sampleAssessment = item?.kind === "sample" ? core.sampleAssessment(item.sample) : null;
    const eventAssessment = relatedEvents(item).at(-1)
      ? core.eventOverrideAssessment(relatedEvents(item).at(-1))
      : null;
    const gates = state.bundle ? core.bundleGateAssessment(state.bundle) : null;
    const eventGate = (state.eventsLabel || state.events.length) ? core.eventGateAssessment(state.events) : null;
    const modelGate = state.modelPack ? core.modelPackGateAssessment(state.modelPack) : null;
    const provenance = core.provenanceAssessment(state.bundle, state.events, state.modelPack);
    const issues = [
      ...(sampleAssessment?.issues ?? []),
      ...(gates?.contract?.issues ?? []),
      ...(gates?.privacy?.issues ?? []),
      ...(eventGate?.issues ?? []),
      ...(modelGate?.issues ?? []),
      ...(provenance.issues ?? []),
      ...(state.assetGate.issues ?? [])
    ];
    const automatic = [
      sampleAssessment
        ? statusPill(sampleAssessment.status === "clean" ? "prediction ↔ annotation aligned" : "automatic review flags", sampleAssessment.status === "clean" ? "ok" : "warn")
        : statusPill("event-only", "neutral"),
      sampleAssessment?.averageIoU != null ? statusPill("mean IoU " + formatPercent(sampleAssessment.averageIoU), sampleAssessment.averageIoU >= 0.5 ? "ok" : "warn") : "",
      eventAssessment ? statusPill("override " + eventAssessment.effect, eventAssessment.effect === "set" ? "ok" : "warn") : ""
    ].join(" ");
    elements.detailReview.innerHTML = '<div class="pill-row tsr-review-flags">' + automatic + "</div>"
      + (eventAssessment ? '<p class="hint compact">' + escapeHTML(eventAssessment.reason) + "</p>" : "")
      + (issues.length
        ? '<ul class="tsr-issue-list">' + issues.map((issue) => "<li>" + escapeHTML(issue) + "</li>").join("") + "</ul>"
        : '<p class="trace-empty">No automatic contract, privacy, integrity, class, or box issue found.</p>');
  }

  function renderDecision(item) {
    const decision = item ? state.decisions.get(item.key) : null;
    const buttons = [
      [elements.verdictCorrect, "correct"],
      [elements.verdictReview, "review"],
      [elements.verdictReject, "reject"]
    ];
    for (const [button, verdict] of buttons) {
      if (!button) continue;
      button.disabled = !item;
      button.classList.toggle("active", decision?.verdict === verdict);
      button.setAttribute("aria-pressed", String(decision?.verdict === verdict));
    }
    if (elements.reviewNote) {
      elements.reviewNote.disabled = !item;
      elements.reviewNote.value = decision?.note ?? "";
    }
    if (elements.exportReport) {
      elements.exportReport.disabled = state.decisions.size === 0;
    }
  }

  function renderDetails() {
    const item = selectedItem();
    if (elements.detailSummary) {
      if (!item) {
        elements.detailSummary.innerHTML = '<p class="trace-empty">Select a QA item.</p>';
      } else {
        const context = itemContext(item);
        const status = item?.kind === "sample" ? item.sample?.annotation?.status ?? "unreviewed" : "event only";
        elements.detailSummary.innerHTML = '<span class="tsr-selected-heading"><strong>'
          + escapeHTML(item.label) + "</strong>"
          + statusPill(status, "neutral") + "</span>"
          + '<span class="muted">' + escapeHTML(formatTimestamp(item.timestamp))
          + (context?.way_id ? " · way " + escapeHTML(context.way_id) : "") + "</span>";
      }
    }
    renderModelDetails(item);
    renderDetection(item);
    renderContext(item);
    renderReview();
    renderDecision(item);
    renderTimeline(item);
    if (elements.detailRaw) {
      elements.detailRaw.textContent = item
        ? JSON.stringify(item.kind === "sample" ? item.sample : item.event, null, 2)
        : "";
    }
  }

  function renderAll() {
    state.queueItems = allItems();
    renderModelTruth();
    renderOverview();
    renderQueue();
    renderDetails();
    void renderEvidence();
  }

  function selectRelative(offset) {
    if (!state.filteredItems.length) return;
    const currentIndex = Math.max(0, state.filteredItems.findIndex((item) => item.key === state.selectedKey));
    const nextIndex = (currentIndex + offset + state.filteredItems.length) % state.filteredItems.length;
    state.selectedKey = state.filteredItems[nextIndex].key;
    state.selectedAssetPath = null;
    renderQueue();
    renderDetails();
    void renderEvidence();
  }

  function setVerdict(verdict) {
    const item = selectedItem();
    if (!item) return;
    const existing = state.decisions.get(item.key);
    state.decisions.set(item.key, {
      item_key: item.key,
      sample_id: item.kind === "sample" ? item.sample?.sample_id ?? null : null,
      event_timestamp_utc: item.timestamp,
      verdict,
      note: existing?.note ?? elements.reviewNote?.value.trim() ?? "",
      reviewed_at: new Date().toISOString()
    });
    renderAll();
  }

  function saveDecisionNote() {
    const item = selectedItem();
    if (!item || !elements.reviewNote) return;
    const existing = state.decisions.get(item.key);
    if (!existing && !elements.reviewNote.value.trim()) return;
    state.decisions.set(item.key, {
      item_key: item.key,
      sample_id: item.kind === "sample" ? item.sample?.sample_id ?? null : null,
      event_timestamp_utc: item.timestamp,
      verdict: existing?.verdict ?? "review",
      note: elements.reviewNote.value.trim(),
      reviewed_at: new Date().toISOString()
    });
    renderDecision(item);
  }

  function exportQAReport() {
    if (!state.decisions.size) return;
    const bundleGates = state.bundle ? core.bundleGateAssessment(state.bundle) : null;
    const eventGate = (state.eventsLabel || state.events.length) ? core.eventGateAssessment(state.events) : null;
    const modelGate = state.modelPack ? core.modelPackGateAssessment(state.modelPack) : null;
    const provenance = core.provenanceAssessment(state.bundle, state.events, state.modelPack);
    const report = {
      schema_version: 1,
      report_type: "youspeed_tsr_qa_report",
      generated_at: new Date().toISOString(),
      note: "This report is separate from the diagnostic-bundle annotation schema and does not mutate source evidence.",
      source: {
        bundle: {
          bundle_id: state.bundle?.bundle_id ?? null,
          capture_group_id: state.bundle?.capture_group_id ?? null,
          label: state.bundleLabel,
          manifest_sha256: state.bundleManifestSha256,
          active_model: state.bundle?.active_model ?? null
        },
        events: {
          label: state.eventsLabel,
          file_sha256: state.eventsFileSha256,
          model_identities: Array.from(new Map(state.events.map((event) => {
            const identity = core.identityFromEvent(event);
            return [JSON.stringify(identity), identity];
          })).values())
        },
        model_manifest: {
          label: state.modelLabel,
          manifest_sha256: state.modelManifestSha256,
          pack_id: state.modelPack?.pack_id ?? null
        },
        provenance
      },
      verification_snapshot: {
        contract_preflight: contractPreflight(),
        bundle_privacy: bundleGates?.privacy ?? null,
        asset_integrity: {
          state: state.assetGate.state,
          issues: [...(state.assetGate.issues ?? [])]
        },
        event_contract: eventGate,
        model_contract: modelGate,
        provenance
      },
      decisions: Array.from(state.decisions.values())
    };
    const blob = new Blob([JSON.stringify(report, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = (state.bundle?.bundle_id ?? "tsr") + "-qa-report.json";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  elements.matcherMode?.addEventListener("click", () => setMode("matcher"));
  elements.tsrMode?.addEventListener("click", () => setMode("tsr"));
  elements.loadFixture?.addEventListener("click", () => void loadFixtureSet());
  elements.modelInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const gate = await loadModelPackFile(file);
      if (!gate) return;
      setIntakeStatus(
        gate.passed
          ? "Model manifest loaded for QA. It is not an installed runtime artifact."
          : `Model manifest loaded with ${gate.issues.length} contract-preflight issue(s).`,
        gate.passed ? "ok" : "error"
      );
    } catch (error) {
      setIntakeStatus(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });
  elements.eventInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const gate = await loadEventFile(file);
      if (!gate) return;
      setIntakeStatus(
        state.events.length + " recognition events loaded"
          + (gate.passed ? "." : ` with ${gate.issues.length} contract-preflight issue(s).`),
        gate.passed ? "ok" : "error"
      );
    } catch (error) {
      setIntakeStatus(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });
  elements.bundleInput?.addEventListener("change", async (event) => {
    if (!event.target.files?.length) return;
    setIntakeStatus("Diagnostic bundle is being validated…", "loading");
    try {
      const gates = await loadBundleDirectory(event.target.files);
      if (!gates) return;
      setIntakeStatus(
        gates.contract.passed
          ? "Diagnostic bundle loaded; basic contract, privacy, and asset gates evaluated."
          : `Diagnostic bundle loaded with ${gates.contract.issues.length} contract-preflight issue(s).`,
        gates.contract.passed ? "ok" : "error"
      );
    } catch (error) {
      setIntakeStatus(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });
  elements.stateFilter?.addEventListener("change", renderAll);
  elements.reviewFilter?.addEventListener("change", renderAll);
  elements.queue.addEventListener("click", (event) => {
    const button = event.target.closest("[data-tsr-item-key]");
    if (!button) return;
    state.selectedKey = button.getAttribute("data-tsr-item-key");
    state.selectedAssetPath = null;
    renderQueue();
    renderDetails();
    void renderEvidence();
  });
  elements.previous?.addEventListener("click", () => selectRelative(-1));
  elements.next?.addEventListener("click", () => selectRelative(1));
  elements.assetSelect?.addEventListener("change", (event) => {
    state.selectedAssetPath = event.target.value;
    void renderEvidence();
  });
  elements.showPredictions?.addEventListener("change", (event) => {
    state.showPredictions = event.target.checked;
    paintEvidence(selectedItem(), selectedAsset(selectedItem()));
    void renderEvidence();
  });
  elements.showAnnotations?.addEventListener("change", (event) => {
    state.showAnnotations = event.target.checked;
    paintEvidence(selectedItem(), selectedAsset(selectedItem()));
    void renderEvidence();
  });
  elements.focusMap?.addEventListener("click", () => {
    const context = itemContext(selectedItem());
    if (!context) return;
    const approved = window.confirm(
      "Die Kartenprüfung lädt OpenStreetMap-Kacheln. Dabei werden die Umgebung der exakten "
      + "Sample-Koordinate und Ihre IP-Adresse an den Kacheldienst übertragen. Fortfahren?"
    );
    if (!approved) return;
    setMode("matcher");
    const matcherData = window.YouSpeedInspectorBridge?.ensureMatcherData();
    void Promise.resolve(matcherData).then(() => {
      window.YouSpeedInspectorBridge?.focusTSRContext(context);
    });
  });
  elements.verdictCorrect?.addEventListener("click", () => setVerdict("correct"));
  elements.verdictReview?.addEventListener("click", () => setVerdict("review"));
  elements.verdictReject?.addEventListener("click", () => setVerdict("reject"));
  elements.reviewNote?.addEventListener("change", saveDecisionNote);
  elements.exportReport?.addEventListener("click", exportQAReport);

  document.addEventListener("keydown", (event) => {
    if (state.mode !== "tsr" || event.metaKey || event.ctrlKey || event.altKey) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectRelative(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      selectRelative(1);
    } else if (event.key === "1") {
      setVerdict("correct");
    } else if (event.key === "2") {
      setVerdict("review");
    } else if (event.key === "3") {
      setVerdict("reject");
    }
  });

  window.addEventListener("hashchange", () => {
    setMode(window.location.hash === "#tsr" ? "tsr" : "matcher", { preserveHash: true });
  });

  setMode(window.location.hash === "#tsr" ? "tsr" : "matcher", { preserveHash: true });
  renderAll();
  void loadFixtureSet();
})();
