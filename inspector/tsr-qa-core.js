(function attachTSRQACore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.YouSpeedTSRQACore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function makeTSRQACore() {
  "use strict";

  const actionableSemantics = new Set(["maximum_speed", "zone_start", "temporary"]);
  const conditionStates = new Set(["none", "resolving", "resolved", "unresolved"]);
  const restrictionKinds = new Set([
    "weather", "time_window", "days_of_week", "vehicle", "max_weight", "school",
    "resident", "exception", "distance", "direction", "extent", "text", "other", "unknown"
  ]);
  const annotationStatuses = new Set(["unreviewed", "accepted", "corrected", "rejected", "negative"]);
  const annotationRoles = new Set(["primary_sign", "supplementary_plate"]);
  const semanticKinds = new Set([
    "maximum_speed", "zone_start", "zone_end", "restriction_end", "city_entry", "city_exit",
    "pedestrian_zone_start", "pedestrian_zone_end", "temporary", "unknown"
  ]);
  const assetRoles = new Set(["full_frame", "assembly_crop", "primary_crop", "supplementary_crop"]);
  const assetMediaTypes = new Set(["image/jpeg", "image/png", "image/heic", "image/x-portable-pixmap"]);
  const safeClassID = /^[a-z0-9][a-z0-9._-]*$/;
  const artifactRuntimeContracts = {
    ios: {
      format: "coreml",
      outputSchemas: new Set(["vision_recognized_objects_v1"])
    },
    android: {
      format: "tflite",
      outputSchemas: new Set(["yolo_nms_xyxy_scores_classes_v1"])
    },
    reference: {
      format: "onnx",
      outputSchemas: new Set([
        "vision_recognized_objects_v1",
        "yolo_nms_xyxy_scores_classes_v1"
      ])
    }
  };

  function safeString(value) {
    if (value == null) {
      return null;
    }
    const text = String(value).trim();
    return text.length ? text : null;
  }

  function nonEmptyString(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function finiteNumber(value) {
    const numeric = typeof value === "number" ? value : Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function jsonNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function parseJSONOrNDJSON(rawText) {
    const text = String(rawText ?? "").trim();
    if (!text) {
      return [];
    }
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed;
      }
      if (Array.isArray(parsed?.events)) {
        return parsed.events;
      }
      return parsed && typeof parsed === "object" ? [parsed] : [];
    } catch (jsonError) {
      const entries = [];
      for (const [index, line] of text.split(/\r?\n/).entries()) {
        const trimmed = line.trim();
        if (!trimmed) {
          continue;
        }
        try {
          entries.push(JSON.parse(trimmed));
        } catch {
          throw new Error(`Invalid JSON on line ${index + 1}: ${jsonError.message}`);
        }
      }
      return entries;
    }
  }

  function normalizedBox(rawBox) {
    if (!rawBox || typeof rawBox !== "object") {
      return null;
    }
    const x = jsonNumber(rawBox.x);
    const y = jsonNumber(rawBox.y);
    const width = jsonNumber(rawBox.width);
    const height = jsonNumber(rawBox.height);
    if (x == null || y == null || width == null || height == null) {
      return null;
    }
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1 || y + height > 1) {
      return null;
    }
    return { x, y, width, height };
  }

  function intersectionOverUnion(leftRaw, rightRaw) {
    const left = normalizedBox(leftRaw);
    const right = normalizedBox(rightRaw);
    if (!left || !right) {
      return 0;
    }
    const x1 = Math.max(left.x, right.x);
    const y1 = Math.max(left.y, right.y);
    const x2 = Math.min(left.x + left.width, right.x + right.width);
    const y2 = Math.min(left.y + left.height, right.y + right.height);
    const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    const union = left.width * left.height + right.width * right.height - intersection;
    return union > 0 ? intersection / union : 0;
  }

  function assetPathIsSafe(rawPath) {
    const path = safeString(rawPath);
    if (!path) {
      return false;
    }
    let decodedPath;
    try {
      decodedPath = decodeURIComponent(path);
    } catch {
      return false;
    }
    return [path, decodedPath].every((candidate) => {
      if (candidate.startsWith("/")
          || candidate.includes("\\")
          || /[\u0000-\u001f\u007f]/.test(candidate)
          || /^[a-z][a-z0-9+.-]*:/i.test(candidate)) {
        return false;
      }
      const segments = candidate.split("/");
      return segments.every((segment) => segment && segment !== "." && segment !== "..");
    });
  }

  function eventContextIsComplete(context) {
    const latitude = jsonNumber(context?.latitude);
    const longitude = jsonNumber(context?.longitude);
    const heading = jsonNumber(context?.heading_degrees);
    const direction = safeString(context?.travel_direction);
    return Boolean(
      nonEmptyString(context?.way_id)
      && latitude != null && latitude >= -90 && latitude <= 90
      && longitude != null && longitude >= -180 && longitude <= 180
      && heading != null && heading >= 0 && heading < 360
      && ["forward", "reverse", "unknown"].includes(direction)
      && isRecord(context?.source_signature)
      && nonEmptyString(context?.source_signature?.osm_revision)
      && Object.hasOwn(context.source_signature, "local_correction_revision")
      && (context.source_signature.local_correction_revision === null
        || nonEmptyString(context.source_signature.local_correction_revision))
    );
  }

  function eventOverrideAssessment(event) {
    if (safeString(event?.state) !== "confirmed") {
      return {
        eligible: false,
        effect: "none",
        reason: "Only a confirmed detection can change the transient speed source."
      };
    }
    const source = safeString(event?.source);
    if (source !== "live_frame" && source !== "camera_still") {
      return {
        eligible: false,
        effect: "none",
        reason: "Only live-frame and camera-still detections can affect the live speed source."
      };
    }
    const contract = eventGateAssessment([event]);
    if (!contract.passed) {
      return {
        eligible: false,
        effect: "none",
        reason: "The confirmed result does not pass the recognition-event contract."
      };
    }
    if (!nonEmptyString(event?.pack_id)
        || !sha256IsValid(event?.artifact_sha256)
        || !nonEmptyString(event?.preprocessing_version)) {
      return {
        eligible: false,
        effect: "none",
        reason: "The model-pack, artifact, or preprocessing identity is incomplete."
      };
    }
    const context = event?.road_context;
    if (!eventContextIsComplete(context)) {
      return {
        eligible: false,
        effect: "none",
        reason: "The exact frame-time road context is incomplete."
      };
    }
    if (safeString(context?.travel_direction) === "unknown") {
      return {
        eligible: false,
        effect: "none",
        reason: "Travel direction is unknown."
      };
    }

    const candidate = event?.candidate;
    const condition = safeString(candidate?.condition_state);
    if (!isRecord(candidate)
        || !conditionStates.has(condition)
        || !Array.isArray(candidate.restrictions)) {
      return {
        eligible: false,
        effect: "none",
        reason: "The confirmed result has an invalid condition or restrictions contract."
      };
    }
    if ((candidate.value != null && !Number.isInteger(candidate.value))
        || (candidate.unit != null && typeof candidate.unit !== "string")) {
      return {
        eligible: false,
        effect: "none",
        reason: "The confirmed result has an invalid value or unit contract."
      };
    }
    const semantic = safeString(candidate?.semantic_kind);
    const value = jsonNumber(candidate?.value);
    const restrictions = candidate.restrictions;
    const actionable = actionableSemantics.has(semantic)
      && value != null && Number.isInteger(value) && value > 0
      && safeString(candidate?.unit) === "km/h"
      && normalizedBox(candidate?.bounding_box)
      && condition === "none"
      && restrictions.length === 0;
    if (!actionable) {
      return {
        eligible: false,
        effect: "clear",
        reason: "This newer confirmed result clears an older camera override but is conditional, unresolved, or non-numeric."
      };
    }
    return {
      eligible: true,
      effect: "set",
      speedKmh: value,
      reason: "Eligible when this frame's source signature is still current."
    };
  }

  function bestMatchForPrediction(prediction, annotations, claimedIndices) {
    let best = null;
    annotations.forEach((annotation, index) => {
      if (claimedIndices.has(index) || safeString(annotation?.role) !== safeString(prediction?.role)) {
        return;
      }
      const iou = intersectionOverUnion(prediction?.bounding_box, annotation?.bounding_box);
      if (!best || iou > best.iou) {
        best = { annotation, index, iou };
      }
    });
    return best;
  }

  function sampleAssessment(sample) {
    const predictions = Array.isArray(sample?.predictions) ? sample.predictions : [];
    const annotations = Array.isArray(sample?.annotation?.objects) ? sample.annotation.objects : [];
    const issues = [];
    const matches = [];
    const claimedAnnotations = new Set();

    for (const prediction of predictions) {
      const match = bestMatchForPrediction(prediction, annotations, claimedAnnotations);
      if (!match || match.iou < 0.1) {
        issues.push(`Unmatched prediction: ${safeString(prediction?.raw_class_id) ?? "unknown class"}`);
        continue;
      }
      claimedAnnotations.add(match.index);
      const predictedClass = safeString(prediction?.raw_class_id);
      const annotatedClass = safeString(match.annotation?.class_id);
      const classMatches = predictedClass === annotatedClass;
      if (!classMatches) {
        issues.push(`Class mismatch: ${predictedClass ?? "unknown"} → ${annotatedClass ?? "unknown"}`);
      }
      if (match.iou < 0.5) {
        issues.push(`Low box overlap (${Math.round(match.iou * 100)}% IoU) for ${annotatedClass ?? predictedClass ?? "object"}`);
      }
      matches.push({ prediction, annotation: match.annotation, iou: match.iou, classMatches });
    }

    annotations.forEach((annotation, index) => {
      if (!claimedAnnotations.has(index)) {
        issues.push(`Missed annotation: ${safeString(annotation?.class_id) ?? "unknown class"}`);
      }
    });

    const context = sample?.capture_context;
    validateCaptureContext(context, "capture_context", issues, {
      requireComplete: sample?.source === "live_shared_frame"
        && ["candidate", "uncertainty"].includes(sample?.trigger)
    });
    const assemblies = Array.isArray(sample?.annotation?.assemblies) ? sample.annotation.assemblies : [];
    for (const assembly of assemblies) {
      if (["resolving", "unresolved"].includes(safeString(assembly?.condition_state))) {
        issues.push(`Assembly ${safeString(assembly?.assembly_id) ?? "unknown"} remains ${assembly.condition_state}`);
      }
    }
    validateAnnotation(sample?.annotation, "annotation", issues);

    const averageIoU = matches.length
      ? matches.reduce((sum, match) => sum + match.iou, 0) / matches.length
      : null;
    return {
      issues,
      matches,
      averageIoU,
      predictionCount: predictions.length,
      annotationCount: annotations.length,
      status: issues.length ? "review" : "clean"
    };
  }

  function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function requireFields(record, fields, prefix, issues) {
    if (!isRecord(record)) {
      issues.push(`${prefix} must be an object`);
      return false;
    }
    for (const field of fields) {
      if (!Object.hasOwn(record, field)) {
        issues.push(`${prefix}.${field} is missing`);
      }
    }
    return true;
  }

  function dateIsValid(value) {
    if (typeof value !== "string") return false;
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/i);
    if (!match) return false;
    const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone, zoneHourText, zoneMinuteText] = match;
    const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
    if (year < 1 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return false;
    if (zone.toUpperCase() !== "Z" && (Number(zoneHourText) > 23 || Number(zoneMinuteText) > 59)) return false;
    const calendar = new Date(0);
    calendar.setUTCFullYear(year, month - 1, day);
    calendar.setUTCHours(hour, minute, second, 0);
    return calendar.getUTCFullYear() === year
      && calendar.getUTCMonth() === month - 1
      && calendar.getUTCDate() === day
      && Number.isFinite(new Date(value).getTime());
  }

  function sha256IsValid(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }

  function validateRestriction(restriction, prefix, issues) {
    if (!requireFields(restriction, ["kind", "normalized_value"], prefix, issues)) return;
    if (!restrictionKinds.has(restriction.kind)) issues.push(`${prefix}.kind is invalid`);
    if (!nonEmptyString(restriction.normalized_value)) issues.push(`${prefix}.normalized_value is missing`);
  }

  function eventGateAssessment(events) {
    const issues = [];
    if (!Array.isArray(events)) {
      return { passed: false, issues: ["events must be an array"] };
    }
    events.forEach((event, index) => {
      const prefix = `events[${index}]`;
      const required = [
        "schema_version", "pack_id", "artifact_sha256", "preprocessing_version",
        "source", "frame_timestamp_utc", "state", "road_context", "latency_ms"
      ];
      if (!requireFields(event, required, prefix, issues)) return;
      if (event.schema_version !== 1) issues.push(`${prefix}.schema_version must be 1`);
      if (!nonEmptyString(event.pack_id)) issues.push(`${prefix}.pack_id is missing`);
      if (!sha256IsValid(event.artifact_sha256)) issues.push(`${prefix}.artifact_sha256 is invalid`);
      if (!nonEmptyString(event.preprocessing_version)) issues.push(`${prefix}.preprocessing_version is missing`);
      if (!["live_frame", "camera_still", "diagnostic_import"].includes(event.source)) issues.push(`${prefix}.source is invalid`);
      if (!dateIsValid(event.frame_timestamp_utc)) issues.push(`${prefix}.frame_timestamp_utc is invalid`);
      if (!["no_recognition", "provisional", "confirmed", "unknown", "unavailable"].includes(event.state)) {
        issues.push(`${prefix}.state is invalid`);
      }
      if (jsonNumber(event.latency_ms) == null || event.latency_ms < 0) issues.push(`${prefix}.latency_ms is invalid`);

      const candidateRequired = ["provisional", "confirmed", "unknown"].includes(event.state);
      const candidateForbidden = ["no_recognition", "unavailable"].includes(event.state);
      if (candidateRequired && !isRecord(event.candidate)) {
        issues.push(`${prefix}.candidate is required for ${event.state}`);
      } else if (candidateForbidden && event.candidate != null) {
        issues.push(`${prefix}.candidate must be null for ${event.state}`);
      }
      if (isRecord(event.candidate)) {
        const candidatePrefix = `${prefix}.candidate`;
        const requiredCandidateFields = [
          "raw_class_id", "raw_label", "semantic_kind", "raw_score", "bounding_box",
          "evidence_frames", "assembly_id", "condition_state", "restrictions"
        ];
        requireFields(event.candidate, requiredCandidateFields, candidatePrefix, issues);
        if (!nonEmptyString(event.candidate.raw_class_id)) issues.push(`${candidatePrefix}.raw_class_id is missing`);
        if (!nonEmptyString(event.candidate.raw_label)) issues.push(`${candidatePrefix}.raw_label is missing`);
        if (!nonEmptyString(event.candidate.semantic_kind)) issues.push(`${candidatePrefix}.semantic_kind is missing`);
        if (event.candidate.value != null && !Number.isInteger(event.candidate.value)) {
          issues.push(`${candidatePrefix}.value must be an integer or null`);
        }
        if (event.candidate.unit != null && typeof event.candidate.unit !== "string") {
          issues.push(`${candidatePrefix}.unit must be a string or null`);
        }
        if (jsonNumber(event.candidate.raw_score) == null) issues.push(`${candidatePrefix}.raw_score is invalid`);
        if (event.candidate.calibrated_confidence != null
            && (jsonNumber(event.candidate.calibrated_confidence) == null
              || event.candidate.calibrated_confidence < 0
              || event.candidate.calibrated_confidence > 1)) {
          issues.push(`${candidatePrefix}.calibrated_confidence is invalid`);
        }
        if (!normalizedBox(event.candidate.bounding_box)) issues.push(`${candidatePrefix}.bounding_box is invalid`);
        if (!Number.isInteger(event.candidate.evidence_frames) || event.candidate.evidence_frames < 1) {
          issues.push(`${candidatePrefix}.evidence_frames is invalid`);
        }
        if (!conditionStates.has(event.candidate.condition_state)) issues.push(`${candidatePrefix}.condition_state is invalid`);
        if (event.candidate.track_id != null && typeof event.candidate.track_id !== "string") {
          issues.push(`${candidatePrefix}.track_id must be a string or null`);
        }
        if (event.candidate.assembly_id != null && !nonEmptyString(event.candidate.assembly_id)) {
          issues.push(`${candidatePrefix}.assembly_id must be a non-empty string or null`);
        }
        if (!Array.isArray(event.candidate.restrictions)) {
          issues.push(`${candidatePrefix}.restrictions must be an array`);
        } else {
          event.candidate.restrictions.forEach((restriction, restrictionIndex) => {
            validateRestriction(restriction, `${candidatePrefix}.restrictions[${restrictionIndex}]`, issues);
          });
        }
      }
      if (event.road_context != null && !eventContextIsComplete(event.road_context)) {
        issues.push(`${prefix}.road_context is structurally invalid`);
      }
      if (event.source === "live_frame" && ["provisional", "confirmed"].includes(event.state)
          && !eventContextIsComplete(event.road_context)) {
        issues.push(`${prefix}.road_context is incomplete for a live detection`);
      }
    });
    return { passed: issues.length === 0, issues };
  }

  function numberInRange(value, minimum, maximum) {
    return jsonNumber(value) != null && value >= minimum && value <= maximum;
  }

  function validateModelComponent(component, prefix, calibrationDatasetSha256, issues) {
    if (!requireFields(component, ["component_id", "source_checkpoint", "artifacts"], prefix, issues)) return;
    if (!nonEmptyString(component.component_id)) issues.push(`${prefix}.component_id is missing`);
    const checkpointPrefix = `${prefix}.source_checkpoint`;
    if (requireFields(component.source_checkpoint, ["uri", "revision", "sha256"], checkpointPrefix, issues)) {
      if (!nonEmptyString(component.source_checkpoint.uri)) issues.push(`${checkpointPrefix}.uri is missing`);
      if (!nonEmptyString(component.source_checkpoint.revision)) issues.push(`${checkpointPrefix}.revision is missing`);
      if (!sha256IsValid(component.source_checkpoint.sha256)) issues.push(`${checkpointPrefix}.sha256 is invalid`);
    }
    if (!Array.isArray(component.artifacts) || !component.artifacts.length) {
      issues.push(`${prefix}.artifacts must be a non-empty array`);
      return;
    }
    component.artifacts.forEach((artifact, index) => {
      const artifactPrefix = `${prefix}.artifacts[${index}]`;
      const required = [
        "platform", "minimum_runtime", "format", "precision", "input_shape", "output_schema",
        "path", "sha256", "source_checkpoint_sha256", "exporter", "calibration_dataset_sha256", "parity"
      ];
      if (!requireFields(artifact, required, artifactPrefix, issues)) return;
      if (!["ios", "android", "reference"].includes(artifact.platform)) issues.push(`${artifactPrefix}.platform is invalid`);
      if (!["coreml", "tflite", "onnx"].includes(artifact.format)) issues.push(`${artifactPrefix}.format is invalid`);
      const runtimeContract = artifactRuntimeContracts[artifact.platform];
      if (runtimeContract && ["coreml", "tflite", "onnx"].includes(artifact.format)
          && artifact.format !== runtimeContract.format) {
        issues.push(`${artifactPrefix}.format is incompatible with ${artifact.platform}`);
      }
      if (!["float32", "float16", "int8", "uint8"].includes(artifact.precision)) issues.push(`${artifactPrefix}.precision is invalid`);
      if (!nonEmptyString(artifact.minimum_runtime)) issues.push(`${artifactPrefix}.minimum_runtime is missing`);
      if (!Array.isArray(artifact.input_shape)
          || artifact.input_shape.length < 3 || artifact.input_shape.length > 4
          || artifact.input_shape.some((dimension) => !Number.isInteger(dimension) || dimension < 1)) {
        issues.push(`${artifactPrefix}.input_shape is invalid`);
      }
      if (!nonEmptyString(artifact.output_schema)) {
        issues.push(`${artifactPrefix}.output_schema is missing`);
      } else if (runtimeContract && !runtimeContract.outputSchemas.has(artifact.output_schema)) {
        issues.push(`${artifactPrefix}.output_schema is incompatible with ${artifact.platform}`);
      }
      if (!nonEmptyString(artifact.path)) {
        issues.push(`${artifactPrefix}.path is missing`);
      } else if (!assetPathIsSafe(artifact.path)) {
        issues.push(`${artifactPrefix}.path must be a safe relative path`);
      }
      if (!sha256IsValid(artifact.sha256)) issues.push(`${artifactPrefix}.sha256 is invalid`);
      if (!sha256IsValid(artifact.source_checkpoint_sha256)) issues.push(`${artifactPrefix}.source_checkpoint_sha256 is invalid`);
      if (artifact.source_checkpoint_sha256 !== component.source_checkpoint?.sha256) {
        issues.push(`${artifactPrefix}.source_checkpoint_sha256 does not match its component`);
      }
      if (!sha256IsValid(artifact.calibration_dataset_sha256)) issues.push(`${artifactPrefix}.calibration_dataset_sha256 is invalid`);
      if (artifact.calibration_dataset_sha256 !== calibrationDatasetSha256) {
        issues.push(`${artifactPrefix}.calibration_dataset_sha256 does not match the pack`);
      }
      if (requireFields(artifact.exporter, ["name", "version", "configuration"], `${artifactPrefix}.exporter`, issues)) {
        for (const field of ["name", "version", "configuration"]) {
          if (!nonEmptyString(artifact.exporter[field])) issues.push(`${artifactPrefix}.exporter.${field} is missing`);
        }
      }
      if (requireFields(artifact.parity, ["tolerance", "measured_max_abs_difference", "passed"], `${artifactPrefix}.parity`, issues)) {
        const tolerance = jsonNumber(artifact.parity.tolerance);
        const measuredDifference = jsonNumber(artifact.parity.measured_max_abs_difference);
        if (tolerance == null || tolerance < 0) issues.push(`${artifactPrefix}.parity.tolerance is invalid`);
        if (measuredDifference == null || measuredDifference < 0) {
          issues.push(`${artifactPrefix}.parity.measured_max_abs_difference is invalid`);
        }
        if (typeof artifact.parity.passed !== "boolean") {
          issues.push(`${artifactPrefix}.parity.passed must be boolean`);
        } else if (!artifact.parity.passed) {
          issues.push(`${artifactPrefix}.parity.passed must be true`);
        }
        if (tolerance != null && tolerance >= 0
            && measuredDifference != null && measuredDifference >= 0
            && measuredDifference > tolerance) {
          issues.push(`${artifactPrefix}.parity.measured_max_abs_difference exceeds tolerance`);
        }
      }
    });
  }

  function modelPackGateAssessment(pack) {
    const issues = [];
    const required = [
      "schema_version", "pack_id", "countries", "pipeline", "taxonomy_version",
      "preprocessing", "thresholds", "calibration", "class_mapping", "detector",
      "lineage", "licenses", "minimum_app_version"
    ];
    if (!requireFields(pack, required, "model_pack", issues)) return { passed: false, issues };
    if (pack.schema_version !== 1) issues.push("model_pack.schema_version must be 1");
    if (!nonEmptyString(pack.pack_id)) issues.push("model_pack.pack_id is missing");
    if (!Array.isArray(pack.countries) || !pack.countries.length
        || pack.countries.some((country) => typeof country !== "string" || !/^[A-Z]{2}$/.test(country))
        || new Set(pack.countries).size !== pack.countries.length) {
      issues.push("model_pack.countries must be unique ISO alpha-2 codes");
    }
    if (!["direct_detection", "proposal_classification"].includes(pack.pipeline)) issues.push("model_pack.pipeline is invalid");
    if (pack.taxonomy_version !== "tsr-semantic-v1") issues.push("model_pack.taxonomy_version is invalid");
    if (requireFields(pack.preprocessing, ["version", "input_width", "input_height", "color_space", "resize", "orientation"], "model_pack.preprocessing", issues)) {
      if (!nonEmptyString(pack.preprocessing.version)) issues.push("model_pack.preprocessing.version is missing");
      if (!Number.isInteger(pack.preprocessing.input_width) || pack.preprocessing.input_width < 1) issues.push("model_pack.preprocessing.input_width is invalid");
      if (!Number.isInteger(pack.preprocessing.input_height) || pack.preprocessing.input_height < 1) issues.push("model_pack.preprocessing.input_height is invalid");
      if (!["rgb", "bgr"].includes(pack.preprocessing.color_space)) issues.push("model_pack.preprocessing.color_space is invalid");
      if (!["scale_fit_letterbox", "scale_fill"].includes(pack.preprocessing.resize)) issues.push("model_pack.preprocessing.resize is invalid");
      if (pack.preprocessing.orientation !== "normalize_exif_and_mirroring") issues.push("model_pack.preprocessing.orientation is invalid");
    }
    if (requireFields(pack.thresholds, ["provisional", "confirmed", "unknown", "confirmation_frames", "confirmation_window_ms", "minimum_track_iou"], "model_pack.thresholds", issues)) {
      for (const field of ["provisional", "confirmed", "unknown", "minimum_track_iou"]) {
        if (!numberInRange(pack.thresholds[field], 0, 1)) issues.push(`model_pack.thresholds.${field} is invalid`);
      }
      const unknownThreshold = jsonNumber(pack.thresholds.unknown);
      const provisionalThreshold = jsonNumber(pack.thresholds.provisional);
      const confirmedThreshold = jsonNumber(pack.thresholds.confirmed);
      if (unknownThreshold != null && provisionalThreshold != null && confirmedThreshold != null
          && (unknownThreshold > provisionalThreshold || provisionalThreshold > confirmedThreshold)) {
        issues.push("model_pack.thresholds must satisfy unknown <= provisional <= confirmed");
      }
      if (!Number.isInteger(pack.thresholds.confirmation_frames) || pack.thresholds.confirmation_frames < 2) issues.push("model_pack.thresholds.confirmation_frames is invalid");
      if (!Number.isInteger(pack.thresholds.confirmation_window_ms) || pack.thresholds.confirmation_window_ms < 1) issues.push("model_pack.thresholds.confirmation_window_ms is invalid");
    }
    if (requireFields(pack.calibration, ["kind", "revision", "dataset_sha256", "calibrated", "runtime_output"], "model_pack.calibration", issues)) {
      if (!["none", "temperature_scaling", "isotonic", "platt"].includes(pack.calibration.kind)) issues.push("model_pack.calibration.kind is invalid");
      if (!nonEmptyString(pack.calibration.revision)) issues.push("model_pack.calibration.revision is missing");
      if (!sha256IsValid(pack.calibration.dataset_sha256)) issues.push("model_pack.calibration.dataset_sha256 is invalid");
      if (typeof pack.calibration.calibrated !== "boolean") issues.push("model_pack.calibration.calibrated must be boolean");
      if (!["raw_score", "calibrated_confidence"].includes(pack.calibration.runtime_output)) issues.push("model_pack.calibration.runtime_output is invalid");
      if (pack.calibration.calibrated === true) {
        if (pack.calibration.kind === "none") {
          issues.push("model_pack.calibration calibrated packs require a non-none kind");
        }
        if (pack.calibration.runtime_output !== "calibrated_confidence") {
          issues.push("model_pack.calibration calibrated packs must expose calibrated_confidence");
        }
      } else if (pack.calibration.calibrated === false
          && pack.calibration.runtime_output !== "raw_score") {
        issues.push("model_pack.calibration uncalibrated packs must expose raw_score");
      }
    }
    if (!Array.isArray(pack.class_mapping) || !pack.class_mapping.length) {
      issues.push("model_pack.class_mapping must be a non-empty array");
    } else {
      const classIDs = pack.class_mapping
        .filter(isRecord)
        .map((mapping) => mapping.class_id)
        .filter(nonEmptyString);
      if (new Set(classIDs).size !== classIDs.length) {
        issues.push("model_pack.class_mapping class_id values must be unique");
      }
      pack.class_mapping.forEach((mapping, index) => {
        const prefix = `model_pack.class_mapping[${index}]`;
        if (!requireFields(mapping, ["class_id", "label", "semantic", "threshold"], prefix, issues)) return;
        if (!nonEmptyString(mapping.class_id)) issues.push(`${prefix}.class_id is missing`);
        if (!nonEmptyString(mapping.label)) issues.push(`${prefix}.label is missing`);
        if (!isRecord(mapping.semantic) || !semanticKinds.has(mapping.semantic.kind)) {
          issues.push(`${prefix}.semantic is invalid`);
        } else {
          if (actionableSemantics.has(mapping.semantic.kind)) {
            if (!Number.isInteger(mapping.semantic.value) || mapping.semantic.value < 1) {
              issues.push(`${prefix}.semantic requires a positive integer value for ${mapping.semantic.kind}`);
            }
            if (!["km/h", "mph"].includes(mapping.semantic.unit)) {
              issues.push(`${prefix}.semantic requires km/h or mph for ${mapping.semantic.kind}`);
            }
          } else if (mapping.semantic.value != null || mapping.semantic.unit != null) {
            issues.push(`${prefix}.semantic must not carry value or unit for ${mapping.semantic.kind}`);
          }
        }
        if (!numberInRange(mapping.threshold, 0, 1)) issues.push(`${prefix}.threshold is invalid`);
        const role = mapping.sign_role ?? "primary_sign";
        if (!annotationRoles.has(role)) issues.push(`${prefix}.sign_role is invalid`);
        if (role === "supplementary_plate") {
          if (mapping.semantic?.kind !== "unknown" || mapping.semantic?.value != null || mapping.semantic?.unit != null) {
            issues.push(`${prefix}.semantic must be unknown and valueless for a supplementary plate`);
          }
          validateRestriction(mapping.restriction, `${prefix}.restriction`, issues);
        }
        if (role !== "supplementary_plate" && mapping.restriction != null) issues.push(`${prefix}.restriction must be null for a primary sign`);
      });
    }
    if (pack.pipeline === "direct_detection" && pack.classifier != null) {
      issues.push("model_pack.pipeline direct_detection must not declare a classifier");
    }
    if (pack.pipeline === "proposal_classification" && !isRecord(pack.classifier)) {
      issues.push("model_pack.pipeline proposal_classification requires a classifier");
    }
    const calibrationDatasetSha256 = pack.calibration?.dataset_sha256;
    validateModelComponent(pack.detector, "model_pack.detector", calibrationDatasetSha256, issues);
    if (pack.classifier != null) {
      validateModelComponent(pack.classifier, "model_pack.classifier", calibrationDatasetSha256, issues);
    }
    const lineageFields = ["source_manifest_sha256", "dataset_inventory_sha256s", "training_run_id", "training_run_sha256", "evaluation_report_sha256", "parity_report_sha256"];
    if (requireFields(pack.lineage, lineageFields, "model_pack.lineage", issues)) {
      for (const field of ["source_manifest_sha256", "training_run_sha256", "evaluation_report_sha256", "parity_report_sha256"]) {
        if (!sha256IsValid(pack.lineage[field])) issues.push(`model_pack.lineage.${field} is invalid`);
      }
      if (!Array.isArray(pack.lineage.dataset_inventory_sha256s) || !pack.lineage.dataset_inventory_sha256s.length
          || pack.lineage.dataset_inventory_sha256s.some((hash) => !sha256IsValid(hash))) {
        issues.push("model_pack.lineage.dataset_inventory_sha256s is invalid");
      } else if (new Set(pack.lineage.dataset_inventory_sha256s).size
          !== pack.lineage.dataset_inventory_sha256s.length) {
        issues.push("model_pack.lineage.dataset_inventory_sha256s must be unique");
      }
      if (!nonEmptyString(pack.lineage.training_run_id)) issues.push("model_pack.lineage.training_run_id is missing");
    }
    if (!Array.isArray(pack.licenses) || !pack.licenses.length) {
      issues.push("model_pack.licenses must be a non-empty array");
    } else {
      pack.licenses.forEach((license, index) => {
        const prefix = `model_pack.licenses[${index}]`;
        if (!requireFields(license, ["name", "spdx", "source"], prefix, issues)) return;
        for (const field of ["name", "spdx", "source"]) if (!nonEmptyString(license[field])) issues.push(`${prefix}.${field} is missing`);
      });
    }
    if (!/^\d+\.\d+\.\d+$/.test(pack.minimum_app_version)) issues.push("model_pack.minimum_app_version is invalid");
    if (pack.signature != null) {
      if (requireFields(pack.signature, ["algorithm", "key_id", "value"], "model_pack.signature", issues)) {
        if (pack.signature.algorithm !== "ed25519") issues.push("model_pack.signature.algorithm is invalid");
        if (!nonEmptyString(pack.signature.key_id)) issues.push("model_pack.signature.key_id is missing");
        if (!nonEmptyString(pack.signature.value)) issues.push("model_pack.signature.value is missing");
      }
    }
    return { passed: issues.length === 0, issues };
  }

  function validateCaptureContext(context, prefix, issues, options = {}) {
    const required = [
      "road_context_complete", "way_id", "latitude", "longitude", "heading_degrees",
      "travel_direction", "speed_kmh", "map_context_revision", "map_source_signature"
    ];
    if (!requireFields(context, required, prefix, issues)) return;
    if (typeof context.road_context_complete !== "boolean") {
      issues.push(`${prefix}.road_context_complete must be boolean`);
    }
    if (!["forward", "reverse", "unknown"].includes(context.travel_direction)) {
      issues.push(`${prefix}.travel_direction is invalid`);
    }
    for (const [field, minimum, maximum] of [
      ["latitude", -90, 90], ["longitude", -180, 180], ["heading_degrees", 0, 360], ["speed_kmh", 0, Infinity]
    ]) {
      const value = context[field];
      const aboveMaximum = field === "heading_degrees" ? value >= maximum : value > maximum;
      if (value != null && (jsonNumber(value) == null || value < minimum || aboveMaximum)) {
        issues.push(`${prefix}.${field} is invalid`);
      }
    }
    if (context.map_context_revision != null
        && (!Number.isInteger(context.map_context_revision) || context.map_context_revision < 0)) {
      issues.push(`${prefix}.map_context_revision is invalid`);
    }
    if (options.requireComplete && context.road_context_complete !== true) {
      issues.push(`${prefix} must contain synchronized road context`);
    }
    if (context.road_context_complete === true) {
      const complete = nonEmptyString(context.way_id)
        && jsonNumber(context.latitude) != null && context.latitude >= -90 && context.latitude <= 90
        && jsonNumber(context.longitude) != null && context.longitude >= -180 && context.longitude <= 180
        && jsonNumber(context.heading_degrees) != null && context.heading_degrees >= 0 && context.heading_degrees < 360
        && Number.isInteger(context.map_context_revision) && context.map_context_revision >= 0
        && nonEmptyString(context.map_source_signature);
      if (!complete) issues.push(`${prefix} is marked complete but lacks exact way, coordinate, heading, or source revision`);
    }
  }

  function validateAsset(asset, prefix, issues) {
    const required = ["role", "path", "sha256", "media_type", "width", "height"];
    if (!requireFields(asset, required, prefix, issues)) return;
    if (!assetRoles.has(asset.role)) issues.push(`${prefix}.role is invalid`);
    if (!assetMediaTypes.has(asset.media_type)) issues.push(`${prefix}.media_type is invalid`);
    if (!nonEmptyString(asset.path)) {
      issues.push(`${prefix}.path must be a non-empty string`);
    } else if (!assetPathIsSafe(asset.path)) {
      issues.push(`${prefix}.path is unsafe`);
    }
    for (const field of ["assembly_id", "object_id"]) {
      if (asset[field] != null && !nonEmptyString(asset[field])) issues.push(`${prefix}.${field} must be a string or null`);
    }
    if (!sha256IsValid(asset.sha256)) issues.push(`${prefix}.sha256 is invalid`);
    if (!Number.isInteger(asset.width) || asset.width < 1 || !Number.isInteger(asset.height) || asset.height < 1) {
      issues.push(`${prefix} dimensions are invalid`);
    }
    if (asset.source_bounding_box != null && !normalizedBox(asset.source_bounding_box)) {
      issues.push(`${prefix}.source_bounding_box is invalid`);
    }
  }

  function validateAssetReferences(sample, prefix, issues) {
    const assets = Array.isArray(sample?.assets) ? sample.assets : [];
    const objects = Array.isArray(sample?.annotation?.objects) ? sample.annotation.objects : [];
    const assemblies = Array.isArray(sample?.annotation?.assemblies) ? sample.annotation.assemblies : [];
    const objectsByID = new Map(objects
      .filter((item) => nonEmptyString(item?.object_id))
      .map((item) => [item.object_id, item]));
    const assembliesByID = new Map(assemblies
      .filter((assembly) => nonEmptyString(assembly?.assembly_id))
      .map((assembly) => [assembly.assembly_id, assembly]));
    assets.forEach((asset, index) => {
      if (!isRecord(asset)) return;
      const assetPrefix = `${prefix}.assets[${index}]`;
      if (asset.role === "full_frame") {
        if (asset.object_id != null || asset.assembly_id != null) {
          issues.push(`${assetPrefix} full frames cannot reference an object or assembly`);
        }
        return;
      }
      if (asset.role === "assembly_crop") {
        if (!nonEmptyString(asset.assembly_id) || !assembliesByID.has(asset.assembly_id)) {
          issues.push(`${assetPrefix} must reference an annotation assembly`);
        }
        if (asset.object_id != null) issues.push(`${assetPrefix} assembly crops cannot reference an object`);
        return;
      }
      if (!["primary_crop", "supplementary_crop"].includes(asset.role)) return;
      const object = nonEmptyString(asset.object_id) ? objectsByID.get(asset.object_id) : null;
      const expectedRole = asset.role === "primary_crop" ? "primary_sign" : "supplementary_plate";
      if (!object || object.role !== expectedRole) {
        issues.push(`${assetPrefix} must reference a matching annotation object`);
        return;
      }
      if (!nonEmptyString(asset.assembly_id)
          || !assembliesByID.has(asset.assembly_id)
          || asset.assembly_id !== object.assembly_id) {
        issues.push(`${assetPrefix} must reference the object's annotation assembly`);
      }
    });
  }

  function validateAnnotation(annotation, prefix, issues) {
    if (!requireFields(annotation, ["status", "reviewed_at", "objects", "assemblies"], prefix, issues)) return;
    const status = safeString(annotation.status);
    if (!annotationStatuses.has(status)) issues.push(`${prefix}.status is invalid`);
    const objects = Array.isArray(annotation.objects) ? annotation.objects : [];
    const assemblies = Array.isArray(annotation.assemblies) ? annotation.assemblies : [];
    if (!Array.isArray(annotation.objects)) issues.push(`${prefix}.objects must be an array`);
    if (!Array.isArray(annotation.assemblies)) issues.push(`${prefix}.assemblies must be an array`);
    if (status === "negative" && (objects.length || assemblies.length)) {
      issues.push(`${prefix} negative samples cannot carry positive labels`);
    }
    if (["accepted", "corrected"].includes(status) && (!objects.length || !assemblies.length)) {
      issues.push(`${prefix} reviewed positive samples need an assembly`);
    }

    const objectsByID = new Map();
    objects.forEach((item, index) => {
      const itemPrefix = `${prefix}.objects[${index}]`;
      if (!requireFields(item, ["object_id", "assembly_id", "role", "class_id", "bounding_box"], itemPrefix, issues)) return;
      const objectID = nonEmptyString(item.object_id) ? item.object_id : null;
      if (!objectID) {
        issues.push(`${itemPrefix}.object_id is required`);
      } else if (objectsByID.has(objectID)) {
        issues.push(`${prefix} contains duplicate object_id ${objectID}`);
      } else {
        objectsByID.set(objectID, item);
      }
      if (!annotationRoles.has(item.role)) issues.push(`${itemPrefix}.role is invalid`);
      if (!nonEmptyString(item.class_id) || !safeClassID.test(item.class_id)) issues.push(`${itemPrefix}.class_id is unsafe`);
      if (!nonEmptyString(item.assembly_id)) issues.push(`${itemPrefix}.assembly_id is required`);
      if (!normalizedBox(item.bounding_box)) issues.push(`${itemPrefix}.bounding_box is invalid`);
      if (item.role === "primary_sign") {
        if (!isRecord(item.primary_semantic) || !nonEmptyString(item.primary_semantic.kind)) {
          issues.push(`${itemPrefix}.primary_semantic is required`);
        }
        if (item.restriction != null) issues.push(`${itemPrefix} primary signs cannot carry a plate restriction`);
      } else if (item.role === "supplementary_plate") {
        if (!nonEmptyString(item.parent_object_id)) issues.push(`${itemPrefix}.parent_object_id is required`);
        validateRestriction(item.restriction, `${itemPrefix}.restriction`, issues);
        if (item.primary_semantic != null) issues.push(`${itemPrefix} supplementary plates cannot carry a primary semantic`);
      }
    });

    for (const [objectID, item] of objectsByID) {
      if (item.role !== "supplementary_plate") continue;
      const parent = objectsByID.get(nonEmptyString(item.parent_object_id) ? item.parent_object_id : null);
      if (!parent || parent.role !== "primary_sign") {
        issues.push(`${prefix} plate ${objectID} must reference a primary sign`);
      } else if (parent.assembly_id !== item.assembly_id) {
        issues.push(`${prefix} plate ${objectID} crosses assemblies`);
      }
    }

    const assemblyIDs = new Set();
    assemblies.forEach((assembly, index) => {
      const assemblyPrefix = `${prefix}.assemblies[${index}]`;
      const required = ["assembly_id", "bounding_box", "primary_object_id", "supplementary_object_ids", "condition_state"];
      if (!requireFields(assembly, required, assemblyPrefix, issues)) return;
      const assemblyID = nonEmptyString(assembly.assembly_id) ? assembly.assembly_id : null;
      if (!assemblyID) {
        issues.push(`${assemblyPrefix}.assembly_id is required`);
      } else if (assemblyIDs.has(assemblyID)) {
        issues.push(`${prefix} contains duplicate assembly_id ${assemblyID}`);
      } else {
        assemblyIDs.add(assemblyID);
      }
      if (!normalizedBox(assembly.bounding_box)) issues.push(`${assemblyPrefix}.bounding_box is invalid`);
      const primaryID = nonEmptyString(assembly.primary_object_id) ? assembly.primary_object_id : null;
      const primary = objectsByID.get(primaryID);
      if (!primary || primary.role !== "primary_sign") {
        issues.push(`${assemblyPrefix} must reference a primary sign`);
      } else if (primary.assembly_id !== assemblyID) {
        issues.push(`${assemblyPrefix} primary belongs to another assembly`);
      }
      const supplementaryIDs = Array.isArray(assembly.supplementary_object_ids)
        ? assembly.supplementary_object_ids
        : [];
      if (!Array.isArray(assembly.supplementary_object_ids)) {
        issues.push(`${assemblyPrefix}.supplementary_object_ids must be an array`);
      } else if (new Set(supplementaryIDs).size !== supplementaryIDs.length) {
        issues.push(`${assemblyPrefix} repeats a supplementary object`);
      }
      supplementaryIDs.forEach((supplementaryID) => {
        if (!nonEmptyString(supplementaryID)) {
          issues.push(`${assemblyPrefix} references a non-string plate ID`);
          return;
        }
        const plate = objectsByID.get(supplementaryID);
        if (!plate || plate.role !== "supplementary_plate") {
          issues.push(`${assemblyPrefix} references a non-plate`);
        } else if (plate.assembly_id !== assemblyID) {
          issues.push(`${assemblyPrefix} plate belongs to another assembly`);
        } else if (plate.parent_object_id !== primaryID) {
          issues.push(`${assemblyPrefix} plate references another primary`);
        }
      });
      const allowedConditions = supplementaryIDs.length ? new Set(["resolved", "unresolved"]) : new Set(["none"]);
      if (!allowedConditions.has(assembly.condition_state)) {
        issues.push(`${assemblyPrefix}.condition_state does not match its plates`);
      }
    });
  }

  function validateSample(sample, index, sampleIDs, issues) {
    const prefix = `samples[${index}]`;
    const required = [
      "sample_id", "source", "frame_timestamp_utc", "monotonic_timestamp_ns", "trigger",
      "capture_context", "assets", "predictions", "annotation"
    ];
    if (!requireFields(sample, required, prefix, issues)) return;
    const sampleID = nonEmptyString(sample.sample_id) ? sample.sample_id : null;
    if (!sampleID || sampleIDs.has(sampleID)) issues.push("sample IDs must be present and unique");
    if (sampleID) sampleIDs.add(sampleID);
    if (!["live_shared_frame", "dashcam_replay", "imported_still"].includes(sample.source)) {
      issues.push(`${prefix}.source is invalid`);
    }
    if (!["candidate", "uncertainty", "hard_negative", "manual", "periodic_negative"].includes(sample.trigger)) {
      issues.push(`${prefix}.trigger is invalid`);
    }
    if (!dateIsValid(sample.frame_timestamp_utc)) issues.push(`${prefix}.frame_timestamp_utc is invalid`);
    if (sample.monotonic_timestamp_ns != null
        && (!Number.isInteger(sample.monotonic_timestamp_ns) || sample.monotonic_timestamp_ns < 0)) {
      issues.push(`${prefix}.monotonic_timestamp_ns is invalid`);
    }
    validateCaptureContext(sample.capture_context, `${prefix}.capture_context`, issues, {
      requireComplete: sample.source === "live_shared_frame"
        && ["candidate", "uncertainty"].includes(sample.trigger)
    });
    if (!Array.isArray(sample.assets) || !sample.assets.length) {
      issues.push(`${prefix}.assets must be a non-empty array`);
    } else {
      const assetPaths = new Set();
      sample.assets.forEach((asset, assetIndex) => {
        validateAsset(asset, `${prefix}.assets[${assetIndex}]`, issues);
        const path = typeof asset?.path === "string" ? asset.path : null;
        if (path && assetPaths.has(path)) issues.push(`${prefix} repeats asset path ${path}`);
        if (path) assetPaths.add(path);
      });
    }
    if (!Array.isArray(sample.predictions)) {
      issues.push(`${prefix}.predictions must be an array`);
    } else {
      sample.predictions.forEach((prediction, predictionIndex) => {
        const predictionPrefix = `${prefix}.predictions[${predictionIndex}]`;
        if (requireFields(prediction, ["object_id", "role", "raw_class_id", "raw_score", "bounding_box"], predictionPrefix, issues)) {
          if (!annotationRoles.has(prediction.role)) issues.push(`${predictionPrefix}.role is invalid`);
          if (!normalizedBox(prediction.bounding_box)) issues.push(`${predictionPrefix}.bounding_box is invalid`);
        }
      });
    }
    validateAnnotation(sample.annotation, `${prefix}.annotation`, issues);
    validateAssetReferences(sample, prefix, issues);
  }

  function bundleGateAssessment(bundle, now = new Date()) {
    const contractIssues = [];
    const topLevelRequired = [
      "schema_version", "bundle_id", "capture_group_id", "purpose", "created_at",
      "producer", "consent", "privacy", "samples"
    ];
    requireFields(bundle, topLevelRequired, "bundle", contractIssues);
    if (bundle?.schema_version !== 1) contractIssues.push("schema_version must be 1");
    if (!nonEmptyString(bundle?.bundle_id)) contractIssues.push("bundle_id is missing");
    if (!nonEmptyString(bundle?.capture_group_id)) contractIssues.push("capture_group_id is missing");
    if (!["training", "evaluation", "replay"].includes(bundle?.purpose)) contractIssues.push("purpose is invalid");
    if (!dateIsValid(bundle?.created_at)) contractIssues.push("created_at is invalid");
    requireFields(bundle?.producer, ["platform", "app_version", "build", "device_tier"], "producer", contractIssues);
    requireFields(bundle?.consent, ["scope", "policy_version", "granted_at", "export_approved", "retention_expires_at"], "consent", contractIssues);
    requireFields(bundle?.privacy, ["full_frame_retention", "location_mode", "redaction_state", "raw_dashcam_video_included", "direct_device_identifier_included"], "privacy", contractIssues);
    if (!["ios", "android", "desktop"].includes(bundle?.producer?.platform)) contractIssues.push("producer.platform is invalid");
    for (const field of ["app_version", "build", "device_tier"]) {
      if (!nonEmptyString(bundle?.producer?.[field])) contractIssues.push(`producer.${field} is missing`);
    }
    if (!nonEmptyString(bundle?.consent?.policy_version)) contractIssues.push("consent.policy_version is missing");
    if (typeof bundle?.consent?.export_approved !== "boolean") contractIssues.push("consent.export_approved must be boolean");
    if (typeof bundle?.privacy?.full_frame_retention !== "boolean") contractIssues.push("privacy.full_frame_retention must be boolean");
    if (!["none", "coarse", "exact_local_encrypted"].includes(bundle?.privacy?.location_mode)) contractIssues.push("privacy.location_mode is invalid");
    if (!["not_required", "pending", "applied", "verified"].includes(bundle?.privacy?.redaction_state)) contractIssues.push("privacy.redaction_state is invalid");
    if (!dateIsValid(bundle?.consent?.granted_at)) contractIssues.push("consent.granted_at is invalid");
    if (!dateIsValid(bundle?.consent?.retention_expires_at)) contractIssues.push("consent.retention_expires_at is invalid");
    if (bundle?.active_model != null) {
      requireFields(bundle.active_model, ["pack_id", "artifact_sha256", "preprocessing_version"], "active_model", contractIssues);
      if (!nonEmptyString(bundle.active_model?.pack_id)) contractIssues.push("active_model.pack_id is missing");
      if (!sha256IsValid(bundle.active_model?.artifact_sha256)) contractIssues.push("active_model.artifact_sha256 is invalid");
      if (!nonEmptyString(bundle.active_model?.preprocessing_version)) contractIssues.push("active_model.preprocessing_version is missing");
    }
    const samples = Array.isArray(bundle?.samples) ? bundle.samples : [];
    if (!samples.length) contractIssues.push("samples must be a non-empty array");
    const sampleIDs = new Set();
    samples.forEach((sample, index) => validateSample(sample, index, sampleIDs, contractIssues));

    const privacyIssues = [];
    const hasFullFrameAsset = samples.some((sample) => Array.isArray(sample?.assets)
      && sample.assets.some((asset) => safeString(asset?.role) === "full_frame"));
    const hasAmbiguousAssetRole = samples.some((sample) => Array.isArray(sample?.assets)
      && sample.assets.some((asset) => !assetRoles.has(asset?.role)));
    const declaresFullFrameRetention = bundle?.privacy?.full_frame_retention === true;
    const locationMode = bundle?.privacy?.location_mode;
    const contexts = samples.map((sample) => sample?.capture_context).filter(isRecord);
    const retainsLocationIdentity = contexts.some((context) => [
      context.way_id, context.latitude, context.longitude, context.heading_degrees,
      context.map_source_signature
    ].some((value) => value != null));
    if (safeString(bundle?.consent?.scope) !== "tsr_diagnostic_dataset") privacyIssues.push("consent scope is invalid");
    if (bundle?.consent?.export_approved !== true) privacyIssues.push("export is not approved");
    if (typeof bundle?.privacy?.full_frame_retention === "boolean"
        && declaresFullFrameRetention !== hasFullFrameAsset) {
      privacyIssues.push("full-frame retention declaration does not match retained assets");
    }
    if (hasAmbiguousAssetRole) {
      privacyIssues.push("unrecognized asset roles cannot establish crop-only retention");
    }
    if ((declaresFullFrameRetention || hasFullFrameAsset || hasAmbiguousAssetRole)
        && safeString(bundle?.privacy?.redaction_state) !== "verified") {
      privacyIssues.push("exported full frames require verified redaction");
    }
    if (locationMode === "none" && retainsLocationIdentity) {
      privacyIssues.push("location_mode none conflicts with retained road or location context");
    }
    if (locationMode === "coarse") {
      const coarseContextIsInvalid = contexts.some((context) => {
        const latitude = jsonNumber(context.latitude);
        const longitude = jsonNumber(context.longitude);
        const heading = jsonNumber(context.heading_degrees);
        const rounded = (value, scale) => value == null || Math.abs(value * scale - Math.round(value * scale)) < 1e-8;
        return context.way_id != null
          || context.map_source_signature != null
          || !rounded(latitude, 1_000)
          || !rounded(longitude, 1_000)
          || (heading != null && (!Number.isInteger(heading) || heading % 15 !== 0));
      });
      if (coarseContextIsInvalid) {
        privacyIssues.push("location_mode coarse permits only 3-decimal coordinates, 15-degree headings, and no exact way/source identity");
      }
    }
    if (bundle?.privacy?.raw_dashcam_video_included !== false) privacyIssues.push("raw dashcam video is present or unspecified");
    if (bundle?.privacy?.direct_device_identifier_included !== false) privacyIssues.push("direct device identity is present or unspecified");
    const createdDate = dateIsValid(bundle?.created_at) ? new Date(bundle.created_at) : new Date(NaN);
    const grantedDate = dateIsValid(bundle?.consent?.granted_at) ? new Date(bundle.consent.granted_at) : new Date(NaN);
    const retentionDate = dateIsValid(bundle?.consent?.retention_expires_at)
      ? new Date(bundle.consent.retention_expires_at)
      : new Date(NaN);
    const sampleDates = samples
      .map((sample) => dateIsValid(sample?.frame_timestamp_utc) ? new Date(sample.frame_timestamp_utc) : null)
      .filter(Boolean);
    const captureDates = [createdDate, ...sampleDates].filter((date) => Number.isFinite(date.getTime()));
    if (Number.isFinite(grantedDate.getTime()) && captureDates.some((date) => grantedDate > date)) {
      privacyIssues.push("consent was granted after capture");
    }
    if (Number.isFinite(retentionDate.getTime()) && captureDates.some((date) => retentionDate <= date)) {
      privacyIssues.push("retention does not extend beyond capture");
    }
    if (!Number.isFinite(retentionDate.getTime()) || retentionDate <= now) privacyIssues.push("retention has expired or is invalid");

    return {
      contract: { passed: contractIssues.length === 0, issues: contractIssues },
      privacy: { passed: privacyIssues.length === 0, issues: privacyIssues }
    };
  }

  function identityFromEvent(event) {
    return {
      pack_id: nonEmptyString(event?.pack_id) ? event.pack_id : null,
      artifact_sha256: sha256IsValid(event?.artifact_sha256) ? event.artifact_sha256 : null,
      preprocessing_version: nonEmptyString(event?.preprocessing_version) ? event.preprocessing_version : null
    };
  }

  function modelIdentityMatches(left, right) {
    if (!left || !right) return false;
    return ["pack_id", "artifact_sha256", "preprocessing_version"]
      .every((field) => typeof left[field] === "string" && left[field].length > 0 && left[field] === right[field]);
  }

  function modelArtifactHashes(pack, platform = null) {
    return [pack?.detector, pack?.classifier]
      .flatMap((component) => Array.isArray(component?.artifacts) ? component.artifacts : [])
      .filter((artifact) => !platform || safeString(artifact?.platform) === platform)
      .map((artifact) => safeString(artifact?.sha256))
      .filter(Boolean);
  }

  function provenanceAssessment(bundle, events, pack) {
    const issues = [];
    const bundleModel = isRecord(bundle?.active_model) ? bundle.active_model : null;
    const artifactHashes = modelArtifactHashes(pack);
    if (bundleModel && pack) {
      const producerPlatform = safeString(bundle?.producer?.platform);
      const artifactPlatform = producerPlatform === "desktop" ? "reference" : producerPlatform;
      const platformArtifactHashes = modelArtifactHashes(pack, artifactPlatform);
      if (safeString(pack.pack_id) !== safeString(bundleModel.pack_id)) issues.push("loaded model manifest pack_id does not match the bundle");
      if (safeString(pack?.preprocessing?.version) !== safeString(bundleModel.preprocessing_version)) issues.push("loaded model preprocessing does not match the bundle");
      if (!platformArtifactHashes.includes(safeString(bundleModel.artifact_sha256))) {
        issues.push(`bundle artifact is absent from the loaded model manifest for ${artifactPlatform ?? "its producer platform"}`);
      }
    }
    (Array.isArray(events) ? events : []).forEach((event, index) => {
      const identity = identityFromEvent(event);
      if (!identity.pack_id || !sha256IsValid(identity.artifact_sha256) || !identity.preprocessing_version) {
        issues.push(`events[${index}] has incomplete model provenance`);
        return;
      }
      if (bundleModel && !modelIdentityMatches(identity, bundleModel)) {
        issues.push(`events[${index}] model provenance does not match the bundle`);
      }
      if (pack && (identity.pack_id !== safeString(pack.pack_id)
          || identity.preprocessing_version !== safeString(pack?.preprocessing?.version)
          || !artifactHashes.includes(identity.artifact_sha256))) {
        issues.push(`events[${index}] model provenance does not match the loaded manifest`);
      }
    });
    return { passed: issues.length === 0, issues };
  }

  function headingDifference(left, right) {
    const difference = Math.abs(left - right) % 360;
    return Math.min(difference, 360 - difference);
  }

  function approximateDistanceMeters(left, right) {
    const leftLat = jsonNumber(left?.latitude);
    const leftLon = jsonNumber(left?.longitude);
    const rightLat = jsonNumber(right?.latitude);
    const rightLon = jsonNumber(right?.longitude);
    if ([leftLat, leftLon, rightLat, rightLon].some((value) => value == null)) return null;
    const latitudeScale = 111_320;
    const longitudeScale = latitudeScale * Math.cos((leftLat + rightLat) * Math.PI / 360);
    return Math.hypot((leftLat - rightLat) * latitudeScale, (leftLon - rightLon) * longitudeScale);
  }

  function relatedEventsForSample(sample, events, toleranceSeconds = 1.5, expectedModel = null) {
    const timestamp = new Date(sample?.frame_timestamp_utc).getTime();
    const context = sample?.capture_context;
    const wayID = safeString(context?.way_id);
    return (Array.isArray(events) ? events : [])
      .filter((event) => {
        const eventTimestamp = new Date(event?.frame_timestamp_utc).getTime();
        if (!Number.isFinite(timestamp) || !Number.isFinite(eventTimestamp)) return false;
        const ageMilliseconds = timestamp - eventTimestamp;
        if (ageMilliseconds < 0 || ageMilliseconds > toleranceSeconds * 1000) return false;
        const eventContext = event?.road_context;
        if (!wayID || safeString(eventContext?.way_id) !== wayID) return false;
        if (safeString(context?.travel_direction) !== safeString(eventContext?.travel_direction)) return false;
        const distance = approximateDistanceMeters(context, eventContext);
        if (distance == null || distance > 40) return false;
        const sampleHeading = jsonNumber(context?.heading_degrees);
        const eventHeading = jsonNumber(eventContext?.heading_degrees);
        if (sampleHeading == null || eventHeading == null || headingDifference(sampleHeading, eventHeading) > 35) return false;
        return !expectedModel || modelIdentityMatches(identityFromEvent(event), expectedModel);
      })
      .sort((left, right) => new Date(left.frame_timestamp_utc) - new Date(right.frame_timestamp_utc));
  }

  function summarize(bundle, events) {
    const samples = Array.isArray(bundle?.samples) ? bundle.samples : [];
    const assessments = samples.map(sampleAssessment);
    const eventList = Array.isArray(events) ? events : [];
    const confidences = eventList
      .map((event) => finiteNumber(event?.candidate?.calibrated_confidence))
      .filter((value) => value != null);
    return {
      samples: samples.length,
      reviewSamples: assessments.filter((assessment) => assessment.status === "review").length,
      reviewedSamples: samples.filter((sample) => safeString(sample?.annotation?.status) && sample.annotation.status !== "unreviewed").length,
      events: eventList.length,
      confirmedEvents: eventList.filter((event) => event?.state === "confirmed").length,
      averageConfidence: confidences.length
        ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
        : null
    };
  }

  return Object.freeze({
    actionableSemantics,
    assetPathIsSafe,
    bundleGateAssessment,
    clamp,
    eventContextIsComplete,
    eventGateAssessment,
    eventOverrideAssessment,
    finiteNumber,
    identityFromEvent,
    intersectionOverUnion,
    jsonNumber,
    modelIdentityMatches,
    modelPackGateAssessment,
    normalizedBox,
    parseJSONOrNDJSON,
    provenanceAssessment,
    relatedEventsForSample,
    safeString,
    sampleAssessment,
    summarize
  });
});
