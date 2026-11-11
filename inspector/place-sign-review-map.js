(function attachPlaceSignReviewMap(root) {
  "use strict";

  const colors = {area: "#536b81", camera: "#2676b9", proposal: "#7650c4", inventory: "#087847"};
  const positionLabels = {coarse_review: "Grobe Positionshypothese", nominal_review: "Nominale Positionshypothese"};
  const azimuthLabels = {reverse_image_ray_proxy: "Näherung aus Bildsichtstrahlen", road_tangent_with_image_proxy: "Straßenachse mit Bildhinweis", road_tangent_two_sighting: "Straßenachse in Anfahrtrichtung"};
  const earthRadius = 6371008.8;
  const sightlineLength = 100;
  const radians = Math.PI / 180;
  const format = new Intl.NumberFormat("de-DE", {maximumFractionDigits: 1});

  function twoSightingRoadLabel(proposal) {
    return proposal.road_side === "left"
      ? "Zwei Sichtungen · 1 m links der Straße"
      : "Zwei Sichtungen · 1 m rechts der Straße";
  }

  function point(latitude, longitude) {
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) ||
        Math.abs(latitude) > 85 || Math.abs(longitude) > 180) return null;
    return [latitude, longitude];
  }

  const coordinate = entry => entry && point(entry.latitude, entry.longitude);
  const degrees = value => Number.isFinite(value) && value >= 0 && value < 360;
  const positive = value => Number.isFinite(value) && value > 0;

  function displayProposalAzimuth(value) {
    return degrees(value) ? (value + 180) % 360 : null;
  }

  // Leaflet uses latitude/longitude. These offsets use true north and metres.
  function destination([latitude, longitude], bearing, metres) {
    const phi = latitude * radians;
    const theta = bearing * radians;
    const angle = metres / earthRadius;
    const nextPhi = Math.asin(Math.sin(phi) * Math.cos(angle) + Math.cos(phi) * Math.sin(angle) * Math.cos(theta));
    const longitudeDelta = Math.atan2(
      Math.sin(theta) * Math.sin(angle) * Math.cos(phi),
      Math.cos(angle) - Math.sin(phi) * Math.sin(nextPhi),
    );
    return [nextPhi / radians, (longitude + longitudeDelta / radians + 540) % 360 - 180];
  }

  function placeOutline(place) {
    const ring = place?.bounds_ring_wgs84;
    if (Array.isArray(ring) && ring.length >= 4) {
      const coordinates = ring.map(entry => Array.isArray(entry) && point(entry[1], entry[0]));
      if (coordinates.every(Boolean)) return {coordinates, label: "Prüfgebiet · 2 km × 2 km"};
    }
    if (!Array.isArray(place?.bbox_wgs84) || place.bbox_wgs84.length !== 4) return null;
    const [west, south, east, north] = place.bbox_wgs84;
    const coordinates = [point(south, west), point(south, east), point(north, east), point(north, west)];
    if (west >= east || south >= north || !coordinates.every(Boolean)) return null;
    return {coordinates, label: "Geografischer Rahmen des Prüfgebiets"};
  }

  function cameraStyle(selected) {
    const color = colors.camera;
    return {
      marker: {
        radius: selected ? 8 : 5, color: selected ? color : "#fff", weight: selected ? 3 : 1.5,
        fillColor: selected ? "#eaf5ff" : color, fillOpacity: 1,
      },
      gps: {color, weight: selected ? 2 : 1, fillOpacity: selected ? .15 : .05, opacity: selected ? .95 : .55},
      wedge: {color, weight: selected ? 1.5 : 1, fillOpacity: selected ? .18 : .07, opacity: selected ? .85 : .45},
      ray: {color, weight: selected ? 2.5 : 1.5, opacity: selected ? 1 : .72},
    };
  }

  function create(element, {onSelectObservation} = {}) {
    const L = root.L;
    if (!element || !L || !root.YouSpeedInspectorTiles) throw new Error("Karte konnte nicht initialisiert werden.");
    const map = L.map(element, {preferCanvas: true, scrollWheelZoom: false, zoomControl: true});
    root.YouSpeedInspectorTiles.create(L).addTo(map);
    const areaLayers = L.featureGroup().addTo(map);
    const geometryLayers = L.featureGroup().addTo(map);
    const markerLayers = L.featureGroup().addTo(map);
    let areaKey = null;
    let group = null;
    let observations = [];
    let viewport = "place";
    let destroyed = false;

    function tooltip(text) {
      const content = element.ownerDocument.createElement("span");
      content.textContent = text;
      return content;
    }

    function drawAzimuth(position, azimuth, color, dashed = false) {
      if (!degrees(azimuth)) return;
      const tip = destination(position, azimuth, 38);
      const left = destination(tip, azimuth + 150, 10);
      const right = destination(tip, azimuth + 210, 10);
      L.polyline([position, tip, left, tip, right], {
        color, weight: 3, dashArray: dashed ? "5 3" : null, interactive: false,
      }).addTo(geometryLayers);
    }

    function drawInventory(matches) {
      for (const match of matches ?? []) {
        const position = coordinate(match);
        if (!position) continue;
        const azimuth = Number.isFinite(match.orientation_deg) ? match.orientation_deg % 360 : null;
        drawAzimuth(position, azimuth, colors.inventory);
        const heading = degrees(azimuth) ? `${format.format(azimuth)}° (Quelle)` : "Ausrichtung offen";
        const label = `MobiData · ${match.sign_code} · ${heading}`;
        L.circleMarker(position, {radius: 9, color: "#fff", weight: 2, fillColor: colors.inventory, fillOpacity: 1})
          .bindTooltip(tooltip(label), {direction: "right", className: "place-sign-inventory-label"})
          .addTo(markerLayers);
      }
    }

    function drawProposal(proposal, {before = false, after = false} = {}) {
      const position = coordinate(proposal);
      if (!position) return;
      if (proposal.position_status === "challenged_review") {
        L.circleMarker(position, {radius: 8, color: colors.area, weight: 2, dashArray: "3 3", fill: false})
          .bindTooltip(tooltip("Alter Standortvorschlag widerspricht Folgeaufnahmen")).addTo(markerLayers);
        return;
      }
      const color = before ? "#64748b" : colors.proposal;
      const label = before ? "Vorher · Panoramax" : after ? "Nachher · mit mobiler Evidenz"
        : proposal.position_status === "adjacent_track_review"
        ? "Vorgeschlagene Position aus Folgeaufnahmen"
        : proposal.position_status === "two_sighting_road_review"
        ? twoSightingRoadLabel(proposal)
        : positionLabels[proposal.position_status] ?? "Vorgeschlagene Schildposition";
      const radius = proposal.position_radius_m;
      if (positive(radius)) {
        L.circle(position, {radius, color, weight: 1.5, dashArray: "5 4", fillOpacity: before ? 0 : .13, interactive: false})
          .addTo(geometryLayers);
      }
      const azimuth = displayProposalAzimuth(proposal.azimut_deg);
      const roadHeading = ["road_tangent_with_image_proxy", "road_tangent_two_sighting"].includes(proposal.azimut_method) || proposal.azimut_method?.endsWith("_fallback");
      drawAzimuth(position, azimuth, color, before || roadHeading);
      const headingLabel = proposal.azimut_method?.includes("proxy") ? "Azimut-Hinweis" : "Azimut";
      const detail = [label, positive(radius) ? `Positionsradius ${format.format(radius)} m` : "Positionsradius offen",
        degrees(azimuth) && `${headingLabel} ${format.format(azimuth)}°`,
        degrees(azimuth) && azimuthLabels[proposal.azimut_method]].filter(Boolean).join(" · ");
      L.circleMarker(position, {radius: before ? 10 : 8, color: before ? color : "#fff",
        weight: 2, fillColor: color, fillOpacity: before ? 0 : 1})
        .bindTooltip(tooltip(detail)).addTo(markerLayers);
    }

    function drawObservation(observation, index) {
      const position = coordinate(observation);
      if (!position) return null;
      const styles = cameraStyle(false);
      const {horizontal_error_m: error, bearing_deg: bearing, bearing_error_deg: bound, camera_heading_deg: heading} = observation;
      const gps = positive(error) ? L.circle(position, {radius: error, ...styles.gps, interactive: false}).addTo(geometryLayers) : null;
      let wedge = null;
      let ray = null;
      if (degrees(bearing)) {
        if (positive(bound) && bound <= 180) {
          const steps = Math.ceil(bound / 3);
          const arc = Array.from({length: steps + 1}, (_, i) =>
            destination(position, bearing - bound + 2 * bound * i / steps, sightlineLength));
          wedge = L.polygon([position, ...arc], {...styles.wedge, interactive: false}).addTo(geometryLayers);
        }
        ray = L.polyline([position, destination(position, bearing, sightlineLength)], {
          ...styles.ray, dashArray: "5 5", interactive: false,
        }).addTo(geometryLayers);
      }
      const origin = observation.mobile_kind === "crop" ? "Mobiler Crop" : "Mobile Sichtung";
      const detail = [observation.mobile_kind ? `${origin} · vorgeschlagene Zuordnung`
        : observation.frame_offset ? `Folgeaufnahme +${observation.frame_offset}` : `Aufnahme ${index + 1}`,
        degrees(heading) && `Kamerarichtung ${format.format(heading)}°`,
        degrees(bearing) && `Sichtstrahl ${format.format(bearing)}°${positive(bound) ? ` ± ${format.format(bound)}°` : ""}`,
        positive(error) && `GPS-Radius ${format.format(error)} m`].filter(Boolean).join(" · ");
      const marker = L.circleMarker(position, styles.marker).bindTooltip(tooltip(detail))
        .on("click", () => {
          selectObservation(index);
          onSelectObservation?.(index);
        }).addTo(markerLayers);
      return {marker, gps, wedge, ray};
    }

    function drawTracks(entries) {
      const byImage = new Map(entries.map(entry => [entry.image_id, entry]));
      const tracks = new Map();
      for (const entry of entries) {
        if (!entry.anchor_image_id || !byImage.has(entry.anchor_image_id)) continue;
        if (!tracks.has(entry.anchor_image_id)) tracks.set(entry.anchor_image_id, []);
        tracks.get(entry.anchor_image_id).push(entry);
      }
      for (const [id, following] of tracks) {
        const ordered = [byImage.get(id), ...following.sort((a, b) => a.frame_offset - b.frame_offset)];
        const points = ordered.map(coordinate).filter(Boolean);
        if (points.length >= 2) L.polyline(points, {
          color: colors.area, weight: 1.5, opacity: .8, dashArray: "2 4", interactive: false,
        }).addTo(geometryLayers);
      }
    }

    function selectObservation(index) {
      if (destroyed) return;
      observations.forEach((layers, i) => {
        if (!layers) return;
        const styles = cameraStyle(i === index);
        layers.marker.setStyle(styles.marker);
        layers.gps?.setStyle(styles.gps);
        layers.wedge?.setStyle(styles.wedge);
        layers.ray?.setStyle(styles.ray);
      });
      observations[index]?.marker.bringToFront();
    }

    function fit(bounds, maxZoom) {
      if (destroyed || !bounds.isValid()) return;
      map.invalidateSize({pan: false});
      map.fitBounds(bounds, {padding: [20, 20], maxZoom, animate: false});
    }

    function fitPlace() {
      viewport = "place";
      fit(areaLayers.getBounds(), 17);
    }

    function fitGroup() {
      const bounds = geometryLayers.getBounds().extend(markerLayers.getBounds());
      if (!bounds.isValid()) { fitPlace(); return; }
      viewport = "group";
      fit(bounds, 19);
    }

    function show(place, nextGroup, selectedIndex) {
      if (destroyed) return;
      const outline = placeOutline(place);
      const nextAreaKey = JSON.stringify(outline?.coordinates ?? []);
      const areaChanged = areaKey !== nextAreaKey;
      const groupChanged = areaChanged || group !== nextGroup;
      if (areaChanged) {
        areaKey = nextAreaKey;
        areaLayers.clearLayers();
        if (outline) {
          L.polygon(outline.coordinates, {color: colors.area, weight: 2, dashArray: "6 5", fillOpacity: .04})
            .bindTooltip(tooltip(outline.label), {sticky: true}).addTo(areaLayers);
        }
      }
      if (groupChanged) {
        group = nextGroup;
        geometryLayers.clearLayers();
        markerLayers.clearLayers();
        drawTracks(group?.observations ?? []);
        if (group?.challenged_proposal && group.proposal?.position_status !== "challenged_review") {
          drawProposal({...group.challenged_proposal, position_status: "challenged_review"});
        }
        const refinement = group?.mobile_refinement;
        if (refinement?.status === "refined") {
          const before = coordinate(group.proposal);
          const after = coordinate(refinement.proposal);
          if (before && after && refinement.movement_m >= .05) {
            L.polyline([before, after], {color: "#64748b", weight: 2, dashArray: "3 3", interactive: false})
              .addTo(geometryLayers);
          }
          drawProposal(group.proposal, {before: true});
          drawProposal(refinement.proposal, {after: true});
        } else {
          drawProposal(group?.proposal);
        }
        observations = (group?.observations ?? []).map(drawObservation);
        drawInventory(group?.mobidata_matches);
      }
      selectObservation(selectedIndex);
      if (areaChanged) fitPlace();
      else if (groupChanged && viewport === "group") fitGroup();
    }

    return {
      show, selectObservation, fitPlace, fitGroup,
      invalidateSize() { if (!destroyed) map.invalidateSize({pan: false}); },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        observations = [];
        group = null;
        map.remove();
      },
    };
  }

  root.YouSpeedPlaceSignReviewMap = {create, displayProposalAzimuth, twoSightingRoadLabel};
})(window);
