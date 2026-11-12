(() => {
  "use strict";
  const cities = {
    "bad-herrenalb": {ags: "08235033", center: [48.7978, 8.4364]},
    "pforzheim": {ags: "08231000", center: [48.89, 8.698]},
  };
  const select = document.getElementById("feed-city");
  const source = document.getElementById("feed-source");
  const status = document.getElementById("feed-status");
  if (!window.L) {
    status.textContent = "Karte konnte nicht geladen werden.";
    return;
  }
  const map = L.map("feed-map");
  YouSpeedInspectorTiles.create(L).addTo(map);
  const signs = L.featureGroup().addTo(map);
  const angle = new Intl.NumberFormat("de", {maximumFractionDigits: 1});
  const coordinates = new Intl.NumberFormat("de", {minimumFractionDigits: 6, maximumFractionDigits: 6});
  const catalog = fetch("../shared/tsr/prolix-de-class-catalog-v1.json")
    .then(response => response.ok ? response.json() : null)
    .catch(() => null)
    .then(document => {
      const exact = YouSpeedTrafficSignInventory.artworkIndex(document);
      return {exact, examples: YouSpeedTrafficSignInventory.referenceExampleIndex(document, exact)};
    });
  let request;

  function feedURL(ags) {
    const filter = `<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:PropertyIsEqualTo><fes:ValueReference>gemeinde_ags</fes:ValueReference><fes:Literal>${ags}</fes:Literal></fes:PropertyIsEqualTo></fes:Filter>`;
    const query = new URLSearchParams({
      SERVICE: "WFS", VERSION: "2.0.0", REQUEST: "GetFeature",
      TYPENAMES: "youspeed:verkehrszeichen", OUTPUTFORMAT: "geojson", FILTER: filter,
    });
    return `./api/sign-wfs?${query}`;
  }

  function addSign(feature, artwork) {
    if (feature.geometry?.type !== "Point") return;
    const [longitude, latitude] = feature.geometry.coordinates;
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    const fields = feature.properties;
    const code = fields.stvo_nr;
    const azimuth = Number.isFinite(fields.azimut) ? `${angle.format(fields.azimut)}°` : "Offen";
    const example = artwork.examples.get(code);
    const art = artwork.exact.get(code) ?? example;
    const pictogram = document.createElement(art ? "img" : "span");
    let iconContent = pictogram;
    if (art) {
      pictogram.src = art.url;
      pictogram.alt = example ? `Beispiel für ${art.label}` : art.label;
      pictogram.style.transform = Number.isFinite(fields.azimut) ? `rotate(${fields.azimut}deg)` : "";
      if (example) {
        iconContent = document.createElement("div");
        iconContent.className = "feed-reference-icon";
        const badge = document.createElement("b");
        badge.textContent = "?";
        badge.setAttribute("aria-hidden", "true");
        iconContent.append(pictogram, badge);
      }
    } else {
      pictogram.textContent = code;
    }
    const icon = L.divIcon({className: "feed-icon", html: iconContent, iconSize: [30, 30]});
    const detail = document.createElement("div");
    detail.className = "feed-detail";
    const title = document.createElement("strong");
    title.textContent = art ? `${code} · ${art.label}` : code;
    const list = document.createElement("dl");
    for (const [key, value] of [
      ["Azimut", azimuth],
      ["Position", `${coordinates.format(latitude)}, ${coordinates.format(longitude)}`],
      ["Erstmals erfasst (UTC)", fields.first_discovered_on],
      ["Gruppe", fields.id],
      ...(example ? [["Piktogramm", `Beispiel ${example.code} · Wert oder Variante offen`]] : []),
    ]) {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = key;
      description.textContent = value ?? "Offen";
      list.append(term, description);
    }
    const compare = document.createElement("a");
    compare.href = "./route-review.html?" + new URLSearchParams({group: fields.id});
    compare.textContent = "Gruppe im Fahrtvergleich öffnen";
    detail.append(title, list, compare);
    const tooltip = document.createElement("span");
    tooltip.textContent = `${code} · ${azimuth}${example ? " · Beispielpiktogramm" : ""}`;
    const marker = L.marker([latitude, longitude], {icon, title: tooltip.textContent})
      .bindPopup(detail).bindTooltip(tooltip).addTo(signs);
    marker.on("popupopen", () => {
      const url = new URL(location.href);
      url.searchParams.set("city", select.value);
      url.searchParams.set("group", fields.id);
      history.replaceState(null, "", url);
    });
    return marker;
  }

  async function loadCity(slug) {
    request?.abort();
    const controller = new AbortController();
    request = controller;
    const {ags, center} = cities[slug];
    select.value = slug;
    signs.clearLayers();
    map.setView(center, 14);
    source.href = feedURL(ags);
    status.textContent = "WFS wird geladen …";
    try {
      const [collection, artwork] = await Promise.all([
        fetch(source.href, {signal: controller.signal}).then(response => {
          if (!response.ok) throw new Error("WFS request failed");
          return response.json();
        }),
        catalog,
      ]);
      if (controller.signal.aborted) return;
      if (collection.type !== "FeatureCollection" || !Array.isArray(collection.features)) {
        throw new Error("Invalid WFS response");
      }
      const group = new URLSearchParams(location.search).get("group");
      let selectedMarker;
      for (const feature of collection.features) {
        const marker = addSign(feature, artwork);
        if (feature.properties?.id === group) selectedMarker = marker;
      }
      if (signs.getBounds().isValid()) {
        map.fitBounds(signs.getBounds(), {padding: [30, 30], maxZoom: 16, animate: false});
      }
      if (selectedMarker) {
        map.setView(selectedMarker.getLatLng(), 18);
        selectedMarker.openPopup();
      }
      status.textContent = `${signs.getLayers().length} Zeichen`;
    } catch {
      if (!controller.signal.aborted) status.textContent = "WFS-Snapshot konnte nicht geladen werden.";
    }
  }

  function selectedCity() {
    const slug = new URLSearchParams(location.search).get("city");
    return Object.hasOwn(cities, slug) ? slug : "bad-herrenalb";
  }
  select.addEventListener("change", () => {
    const url = new URL(location.href);
    url.searchParams.set("city", select.value);
    url.searchParams.delete("group");
    history.pushState(null, "", url);
    loadCity(select.value);
  });
  window.addEventListener("popstate", () => loadCity(selectedCity()));
  loadCity(selectedCity());
})();
