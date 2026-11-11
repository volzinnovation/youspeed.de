(function initializePlaceSignReview() {
  "use strict";
  const element = name => document.getElementById("place-sign-" + name);
  if (!element("map")) return;

  const labels = {
    bounded_review: "Bedingter Standortvorschlag",
    coarse_review: "Grober Standortvorschlag",
    nominal_review: "Vorläufiger Standort aus den Sichtstrahlen",
    adjacent_review: "Standortvorschlag aus Folgeaufnahmen"
  };
  const angle = value => Number.isFinite(value) ? `${value.toFixed(1)}°` : "offen";
  const meters = value => Number.isFinite(value) ? `${value.toFixed(1)} m` : "offen";
  const observationId = observation => observation?.evidence_id || observation?.annotation_id;
  const time = new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "Europe/Berlin"
  });
  let request, data, map, group, observations = [], selectedIndex = -1;

  function status(message) {
    element("status").textContent = message;
    element("status").hidden = !message;
  }

  function reset() {
    request?.abort();
    request = null;
    map?.destroy();
    map = data = group = null;
    observations = [];
    selectedIndex = -1;
    element("stage").replaceChildren();
    element("gallery").replaceChildren();
    element("follow-gallery").replaceChildren();
    element("mobile-gallery").replaceChildren();
    element("mobile").hidden = true;
    element("follow-ons").hidden = true;
    element("identity").hidden = true;
    element("copy-status").textContent = "";
    element("group").replaceChildren();
    element("group").disabled = true;
    element("filter").disabled = true;
    element("filter").value = "";
    element("mobidata-only").disabled = true;
    element("mobidata-only").checked = false;
    element("mobile-only").disabled = true;
    element("mobile-only").checked = false;
    element("content").hidden = true;
    element("title").textContent = "Verkehrszeichen vor Ort";
    element("scope").textContent = "";
    status("");
  }

  function updateLink(historyMode) {
    const params = new URLSearchParams({group: group.id});
    const photo = observationId(observations[selectedIndex]);
    if (photo) params.set("photo", photo);
    const hash = "#place-signs?" + params;
    element("group-id").textContent = group.id;
    element("permalink").href = new URL(window.location.pathname + hash, window.location.origin).href;
    element("copy-status").textContent = "";
    element("identity").hidden = false;
    if (historyMode && window.location.hash !== hash) history[historyMode](null, "", hash);
  }

  function mediaUrl(value) {
    if (typeof value !== "string" || !value) return null;
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin && url.pathname.startsWith("/inspector/api/") ? url.href : null;
    } catch {
      return null;
    }
  }

  function message(text) {
    const node = document.createElement("p");
    node.textContent = text;
    return node;
  }

  function showBox(image, observation) {
    const {box_xyxy: box, image_width: width, image_height: height} = observation;
    if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)
        || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
    const [left, top, right, bottom] = box;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("aria-hidden", "true");
    const rectangle = document.createElementNS(svg.namespaceURI, "rect");
    rectangle.setAttribute("x", left);
    rectangle.setAttribute("y", top);
    rectangle.setAttribute("width", right - left);
    rectangle.setAttribute("height", bottom - top);
    svg.append(rectangle);
    image.after(svg);
  }

  function showImage(observation, index) {
    const stage = element("stage");
    const photo = mediaUrl(observation.photo_url);
    const crop = mediaUrl(observation.crop_url);
    if (!photo && !crop) {
      stage.replaceChildren(message(observation.mobile_kind === "sighting"
        ? "Mobile Sichtung mit Zeitstempel, GPS und Sichtstrahl. Das zugeordnete Panoramax-Bild lässt sich unten öffnen."
        : "Für diese Aufnahme steht kein Bild zur Verfügung."));
      return;
    }
    const image = document.createElement("img");
    const loading = message("Aufnahme wird geladen …");
    image.alt = observation.mobile_kind ? "Mobiler Zeichenausschnitt" : `Panoramax-Aufnahme ${index + 1}`;
    image.referrerPolicy = "no-referrer";
    image.hidden = true;
    let fullFrame = Boolean(photo);
    image.addEventListener("load", () => {
      if (image.parentNode !== stage) return;
      loading.remove();
      image.hidden = false;
      if (fullFrame) showBox(image, observation);
      else image.alt = `Zeichenausschnitt aus Aufnahme ${index + 1}`;
    });
    image.addEventListener("error", () => {
      if (image.parentNode !== stage) return;
      if (fullFrame && crop && crop !== photo) {
        fullFrame = false;
        image.src = crop;
      } else {
        stage.replaceChildren(message("Diese Aufnahme konnte nicht geladen werden."));
      }
    });
    stage.replaceChildren(loading, image);
    image.src = photo || crop;
  }

  function showImageMeta(observation, index) {
    const date = new Date(observation.captured_at);
    element("image-label").textContent = [
      `Aufnahme ${index + 1} von ${observations.length}`,
      observation.frame_offset ? observationLabel(observation, index) : "",
      Number.isFinite(date.getTime()) ? time.format(date) : "",
      observation.in_review_window === false ? "Außerhalb des Suchfensters" : ""
    ].filter(Boolean).join(" · ");
    const rawGps = observation.gps_accuracy_m;
    const fields = [
      ["GPS-Bereich", `± ${meters(observation.horizontal_error_m)}`],
      ["Kamerakurs", angle(observation.camera_heading_deg)],
      ["Sichtstrahl", `${angle(observation.bearing_deg)} ± ${angle(observation.bearing_error_deg)}`]
    ];
    if (Number.isFinite(rawGps)) fields.splice(1, 0, ["GPS-Angabe", meters(rawGps)]);
    if (observation.mobile_kind) {
      element("image-label").textContent = `${observationLabel(observation, index)} · ${time.format(date)}${observation.in_review_window === false ? " · Außerhalb des Suchfensters" : ""}`;
      const way = observation.phone_road_match;
      if (way) fields.push(["Aufgezeichneter OSM-Way", `${way.osm_way_id} · ${way.travel_direction}`]);
    }
    element("image-meta").replaceChildren(...fields.map(([label, value]) => {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      item.append(term, detail);
      return item;
    }));
    const association = observation.association;
    const detail = element("association");
    detail.replaceChildren();
    detail.hidden = !association;
    element("compare").hidden = !association;
    if (association) {
      if (observation.gallery_only) {
        detail.textContent = "Weitere Evidenz derselben Sichtung · zur Bildprüfung";
        return;
      }
      const timing = association.independence_status === "different_capture_day"
        ? "Andere Fahrt · Sichtstrahl mit Standort vereinbar"
        : `Δt ${association.time_delta_s.toFixed(3)} s · Gleiche Aufnahme oder Fahrt möglich`;
      detail.append(`Zuordnung vorgeschlagen · ${timing} · Kameraabstand ${meters(association.camera_distance_m)} · Sichtstrahl-Differenz ${angle(association.bearing_delta_deg)}.`);
      const alternatives = association.candidate_group_ids.filter(id => id !== group.id);
      if (alternatives.length) {
        detail.append(" Weitere Kandidatengruppen ");
        for (const id of alternatives) {
          const link = document.createElement("a");
          link.href = "#place-signs?" + new URLSearchParams({group: id, photo: observationId(observation)});
          link.textContent = id.slice(0, 6);
          detail.append(link, " ");
        }
      }
      if (association.shared_panoramax_group_ids.length > 1) {
        detail.append(` · Panoramax-Annotation in ${association.shared_panoramax_group_ids.length} Prüfgruppen verwendet.`);
      }
    }
  }

  function selectObservation(index, historyMode = "replaceState") {
    const observation = observations[index];
    if (!observation) return;
    if (selectedIndex !== index) {
      selectedIndex = index;
      [...element("gallery").children, ...element("follow-gallery").children, ...element("mobile-gallery").children].forEach((button, i) => {
        button.setAttribute("aria-pressed", String(i === index));
      });
      showImage(observation, index);
      showImageMeta(observation, index);
      map?.selectObservation(index);
    }
    updateLink(historyMode);
  }

  function observationLabel(observation, index) {
    if (observation.mobile_kind) {
      const number = observations.filter(item => item.mobile_kind === observation.mobile_kind).indexOf(observation) + 1;
      return `${observation.mobile_kind === "crop" ? "Mobiler Crop" : "Mobile Sichtung"} ${number}`;
    }
    if (!observation.frame_offset) return `Bild ${index + 1}`;
    const anchor = group.observations.findIndex(item => item.image_id === observation.anchor_image_id);
    return `+${observation.frame_offset}${anchor >= 0 ? " zu Bild " + (anchor + 1) : ""}`;
  }

  function thumbnail(observation, index) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "place-sign-thumbnail";
    const label = observationLabel(observation, index);
    button.setAttribute("aria-label", `${observation.frame_offset ? "Folgeaufnahme " : ""}${label} auswählen`);
    const photo = mediaUrl(observation.photo_url);
    const crop = mediaUrl(observation.crop_url);
    const placeholder = document.createElement("span");
    placeholder.className = "place-sign-thumbnail-image";
    placeholder.textContent = label;
    if (photo || crop) {
      const image = document.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => {
        if (photo && image.src !== photo) image.src = photo;
        else image.replaceWith(placeholder);
      });
      image.src = crop || photo;
      button.append(image);
    } else {
      button.append(placeholder);
    }
    const caption = document.createElement("small");
    caption.textContent = `${label} · ${angle(observation.bearing_deg)}`;
    button.append(caption);
    button.addEventListener("click", () => selectObservation(index));
    return button;
  }

  function showProposal(proposal) {
    const diagnostic = group.follow_on_diagnostic;
    const adjacent = /adjacent|track/.test(proposal?.position_method || "");
    if (!adjacent && diagnostic?.proposal_consistency === "nominal_point_conflicts_with_follow_ons") {
      element("proposal").textContent = "Die Folgeaufnahmen widersprechen dem früheren Standortvorschlag. Standort und Azimut sind offen.";
      return;
    }
    if (!proposal) {
      element("proposal").textContent = group.follow_on_observations?.length
        ? "Aus den Folgeaufnahmen ergibt sich kein ausreichend stabiler Standort oder Azimut."
        : "Standort und Azimut sind für diese Gruppe noch offen.";
      return;
    }
    const title = adjacent ? labels.adjacent_review : labels[proposal.position_status] || "Standortvorschlag";
    const point = `${proposal.latitude.toFixed(6)}, ${proposal.longitude.toFixed(6)}`;
    const radius = Number.isFinite(proposal.position_radius_m)
      ? `${adjacent ? "Bedingter Radius " : "± "}${meters(proposal.position_radius_m)}` : "Positionsunsicherheit offen";
    const method = proposal.azimut_method || "";
    const basis = /road|osm|way/.test(method) ? " · Straßenverlauf"
      : /image|view|bearing/.test(method) ? " · Bildsicht" : "";
    const scope = proposal.in_review_window === false ? " · Außerhalb des Suchfensters" : "";
    const track = diagnostic?.adjacent_track_diagnostics;
    const support = adjacent && track?.support_sequence_count
      ? ` · ${track.support_sequence_count} Sequenzen, ${track.support_pair_count} aufeinanderfolgende Bildpaare` : "";
    const headingLabel = method.includes("proxy") ? "Azimut-Hinweis" : "Azimut";
    const azimuth = window.YouSpeedPlaceSignReviewMap.displayProposalAzimuth(proposal.azimut_deg);
    element("proposal").textContent = `${title} · ${point} · ${radius} · ${headingLabel} ${angle(azimuth)}${basis}${scope}${support}`;
  }

  function showInventory() {
    const matches = group.mobidata_matches || [];
    const panel = element("inventory");
    panel.replaceChildren();
    panel.hidden = !matches.length;
    element("inventory-legend").hidden = !matches.length;
    if (!matches.length) return;
    panel.append(message(matches.length === 1
      ? "MobiData-Referenzkandidat · gleiche Zeichenklasse und nahe am Standortvorschlag"
      : `${matches.length} MobiData-Referenzkandidaten · Zuordnung mehrdeutig`));
    for (const match of matches) {
      const detail = message(`${match.sign_code} · ${match.latitude.toFixed(6)}, ${match.longitude.toFixed(6)} · Abstand zum Vorschlag ${meters(match.distance_m)} · Ausrichtung ${angle(match.orientation_deg)} (Quelle)`);
      const identity = document.createElement("small");
      identity.textContent = `MobiData-Gruppe ${match.source_group_id} · Standort ${match.location_id} · Datensatz ${match.record_key}`;
      detail.append(identity);
      panel.append(detail);
    }
    const source = data.mobidata_reference;
    if (source) {
      const credit = message(`${source.publisher} · Stand ${source.snapshot_timestamp || "unbekannt"} · `);
      const link = document.createElement("a");
      link.href = "https://mobidata-bw.de/dataset/verkehrszeichen-baden-wurttemberg";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "MobiData BW";
      const license = document.createElement("a");
      license.href = "https://www.govdata.de/dl-de/by-2-0";
      license.target = "_blank";
      license.rel = "noopener noreferrer";
      license.textContent = "Datenlizenz Deutschland – Namensnennung 2.0";
      credit.append(link, " · ", license);
      panel.append(credit);
    }
  }

  function showRefinement() {
    const result = group.mobile_refinement;
    const elementText = element("refinement");
    elementText.hidden = !result;
    element("before-legend").hidden = result?.status !== "refined" || !group.proposal;
    if (!result) return;
    const duplicates = result.duplicate_mobile_count
      ? ` · ${result.duplicate_mobile_count} mobile Wiederholungen zusammengefasst` : "";
    if (result.status !== "refined") {
      elementText.textContent = `Nachher · Keine ausreichend gestützte Änderung${duplicates}`;
      return;
    }
    const before = group.proposal;
    const after = result.proposal;
    const azimuth = pose => angle(window.YouSpeedPlaceSignReviewMap.displayProposalAzimuth(pose?.azimut_deg));
    const location = `${after.latitude.toFixed(6)}, ${after.longitude.toFixed(6)}`;
    const movement = Number.isFinite(result.movement_m) ? ` · Verschiebung ${meters(result.movement_m)}` : "";
    const radius = Number.isFinite(after.position_radius_m) ? ` · Bedingter Radius ${meters(after.position_radius_m)}` : "";
    elementText.textContent = `Nachher mit mobiler Evidenz · ${location}${radius}${movement} · Azimut ${azimuth(before)} → ${azimuth(after)} · ${result.mobile_evidence_ids.length} mobile Ansichten · ${result.drive_count} Fahrten${duplicates}`;
  }

  function showGroup(id, {photo = null, historyMode = "replaceState", exact = false} = {}) {
    const changed = group?.id !== id;
    group = data.groups.find(item => item.id === id);
    element("content").hidden = !group;
    if (!group) {
      selectedIndex = -1;
      observations = [];
      element("identity").hidden = true;
      status(exact ? "Die verlinkte Zeichengruppe ist in diesen Ortsdaten nicht vorhanden." : "Keine passende Zeichengruppe.");
      return;
    }
    status("");
    if (changed) {
      const following = group.follow_on_observations || [];
      const mobile = group.mobile_observations || [];
      observations = [...group.observations, ...following, ...mobile];
      selectedIndex = -1;
      element("photo-count").textContent = following.length
        ? `${group.sign_code} · ${observations.length} Bilder aus ${group.observations.length} Sequenzen`
        : `${group.sign_code} · ${observations.length} Aufnahmen`;
      if (mobile.length) element("photo-count").textContent = `${group.sign_code} · ${group.observations.length + following.length} Panoramax · ${mobile.length} mobile Kandidaten`;
      element("gallery").replaceChildren(...group.observations.map(thumbnail));
      element("follow-gallery").replaceChildren(...following.map((item, i) => thumbnail(item, group.observations.length + i)));
      element("follow-ons").hidden = !following.length;
      element("mobile-gallery").replaceChildren(...mobile.map((item, i) => thumbnail(item, group.observations.length + following.length + i)));
      element("mobile").hidden = !mobile.length;
      element("mobile-summary").textContent = "Kandidaten aus zeitnahen Aufnahmen und anderen Fahrten mit passendem Sichtstrahl. Wiederholte Aufnahmen zählen zusammen.";
      showProposal(group.proposal);
      showRefinement();
      showInventory();
      if (!map && window.L && window.YouSpeedPlaceSignReviewMap) {
        map = window.YouSpeedPlaceSignReviewMap.create(element("map"), {
          onSelectObservation: selectObservation
        });
      }
      if (map) {
        let proposal = group.proposal;
        if (group.follow_on_diagnostic?.proposal_consistency === "nominal_point_conflicts_with_follow_ons"
            && !/adjacent|track/.test(proposal?.position_method || "")) {
          const previous = group.challenged_proposal || proposal;
          proposal = previous ? {...previous, position_status: "challenged_review", azimut_deg: null} : null;
        }
        map.show(data.place, {...group, observations, proposal}, 0);
        map.fitGroup();
      } else {
        element("map").textContent = "Die Kartenbibliothek ist derzeit nicht verfügbar.";
      }
    }
    const index = photo === null ? 0 : observations.findIndex(item => observationId(item) === photo);
    selectObservation(Math.max(0, index), index >= 0 ? historyMode : null);
    if (index < 0) element("copy-status").textContent = "Die verlinkte Aufnahme ist in dieser Gruppe nicht mehr vorhanden.";
  }

  function fillGroups(preferredId, options = {}) {
    const filter = element("filter").value.trim().toLowerCase();
    const mobidataOnly = element("mobidata-only").checked;
    const mobileOnly = element("mobile-only").checked;
    const groups = data.groups.filter(item =>
      item.sign_code.toLowerCase().includes(filter) && (!mobidataOnly || item.mobidata_matches?.length)
        && (!mobileOnly || item.mobile_observations?.length)
    );
    const input = element("group");
    input.replaceChildren(...groups.map(item => {
      const option = document.createElement("option");
      option.value = item.id;
      const prefix = (item.mobile_observations?.length ? "+ Mobil · " : "") + (item.mobidata_matches?.length ? "+ MobiData · " : "");
      option.textContent = `${prefix}${item.sign_code} · ${item.observations.length} Bilder · ${item.id.slice(0, 6)}`;
      return option;
    }));
    input.disabled = !groups.length;
    const preferred = groups.some(item => item.id === preferredId);
    if (preferred) input.value = preferredId;
    if (options.exact && !preferred) input.value = "";
    showGroup(input.value, {...options, photo: preferred ? options.photo : null});
  }

  function applyLocation() {
    const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
    const id = params.get("group");
    element("filter").value = "";
    element("mobidata-only").checked = false;
    element("mobile-only").checked = false;
    fillGroups(id ?? data.default_group_id, {
      photo: params.get("photo"),
      exact: id !== null,
      historyMode: id === null ? "replaceState" : null
    });
  }

  async function load() {
    reset();
    const controller = new AbortController();
    request = controller;
    status("Zeichengruppen werden geladen …");
    try {
      const response = await fetch("./api/place-sign-review", {cache: "no-store", signal: controller.signal});
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || "Für diesen Inspector sind keine Ortsdaten eingerichtet.");
      }
      const payload = await response.json();
      if (request !== controller) return;
      if (!payload.place?.name || !Array.isArray(payload.groups)) throw new Error("Ungültige Ortsdaten.");
      data = payload;
      element("title").textContent = data.place.name;
      element("scope").textContent = `2 km × 2 km um die Ortsmitte · ${data.groups.length} Zeichengruppen`;
      const counts = data.mobile_reference?.collection_counts;
      if (counts) element("scope").textContent += ` · ${counts.crop} Crops und ${counts.sighting} Sichtungen erfasst`;
      element("filter").disabled = false;
      element("mobidata-only").disabled = false;
      element("mobile-only").disabled = false;
      applyLocation();
      if (data.mobile_reference && data.mobile_reference.availability !== "available") {
        status("Mobile Kandidaten warten auf aktuelle Quelldaten sowie Freigabe- und Löschkontrollen. Panoramax-Gruppen sind verfügbar.");
      }
    } catch (error) {
      if (request === controller && error.name !== "AbortError") status(error.message);
    } finally {
      if (request === controller) request = null;
    }
  }

  element("group").addEventListener("change", event => showGroup(event.target.value, {historyMode: "pushState"}));
  function filterGroups() {
    fillGroups(group?.id, {photo: observationId(observations[selectedIndex])});
  }
  element("filter").addEventListener("input", filterGroups);
  element("mobidata-only").addEventListener("change", filterGroups);
  element("mobile-only").addEventListener("change", filterGroups);
  element("compare").addEventListener("click", () => {
    const matched = observations[selectedIndex]?.association?.matched_annotation_id;
    const index = observations.findIndex(item => item.annotation_id === matched);
    if (index >= 0) selectObservation(index);
  });
  element("copy-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(element("permalink").href);
      element("copy-status").textContent = "Link kopiert.";
    } catch {
      element("copy-status").textContent = "Den Direktlink über das Kontextmenü kopieren.";
    }
  });
  element("refresh").addEventListener("click", () => void load());
  element("fit-area").addEventListener("click", () => map?.fitPlace());
  element("fit-group").addEventListener("click", () => map?.fitGroup());
  function activate() {
    if (data) applyLocation();
    else if (!request) void load();
  }
  window.addEventListener("youspeed:mode", event => {
    if (event.detail === "place-signs") activate();
    else reset();
  });
  window.addEventListener("pagehide", reset);
  window.addEventListener("pageshow", event => {
    if (event.persisted && document.body.dataset.inspectorMode === "place-signs") activate();
  });
  if (document.body.dataset.inspectorMode === "place-signs") activate();
})();
