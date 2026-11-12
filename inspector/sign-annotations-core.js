(function attachSignAnnotationsCore(root) {
  "use strict";
  const finite = Number.isFinite;
  function validBox(box, width, height) {
    return Array.isArray(box) && box.length === 4 && box.every(Number.isInteger)
      && box[0] >= 0 && box[1] >= 0 && box[0] < box[2] && box[1] < box[3]
      && box[2] <= width && box[3] <= height;
  }
  // Coordinates remain in the native image, including when the preview is letterboxed.
  function imagePoint(clientX, clientY, rect, width, height) {
    if (![clientX, clientY, rect.left, rect.top, rect.width, rect.height, width, height].every(finite)
        || Math.min(rect.width, rect.height, width, height) <= 0) return null;
    const scale = Math.min(rect.width / width, rect.height / height);
    const x = (clientX - rect.left - (rect.width - width * scale) / 2) / scale;
    const y = (clientY - rect.top - (rect.height - height * scale) / 2) / scale;
    if (x < 0 || y < 0 || x > width || y > height) return null;
    return [Math.round(x), Math.round(y)];
  }
  function dragBox(start, end, width, height) {
    if (!start || !end) return null;
    const box = [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
      Math.max(start[0], end[0]), Math.max(start[1], end[1])];
    return validBox(box, width, height) ? box : null;
  }
  function classCode(value) {
    const code = String(value || "").trim().toUpperCase().replace(/X/g, "x");
    return /^DE:[0-9]{3,4}(?:[.-][0-9x]{1,3})*(?:,[0-9]{1,2})?$/.test(code) ? code : null;
  }
  function changed(original, draft) {
    if (!draft) return false;
    return !original || draft.sign_code !== original.sign_code
      || (draft.class_id || null) !== (original.class_id || null)
      || JSON.stringify(draft.box_xyxy) !== JSON.stringify(original.box_xyxy);
  }
  const fold = value => String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ß/g, "ss");
  function catalogEntries(catalog) {
    const signs = (catalog?.signs || []).map(sign => ({
      code: sign.sign_code || null, class_id: sign.class_id,
      label: sign.label?.de || sign.class_id,
      icon: sign.display_eligible && /^tsr\/sign-pictograms\/png\/de-[a-z0-9.,-]+\.png$/.test(sign.image_path || "")
        ? "/shared/" + sign.image_path : null
    }));
    const classes = (catalog?.class_labels || []).map(id => signs.find(item => item.class_id === id)
      || {class_id: id, label: id, code: null, icon: null});
    const seen = new Set();
    const search = signs.filter(item => {
      const key = item.code || item.class_id;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
    return {classes, search};
  }
  function searchClasses(entries, value, limit = 30) {
    const query = fold(value).trim();
    if (!query) return [];
    const terms = query.split(/\s+/);
    return entries.filter(item => terms.every(term => fold(`${item.code || ""} ${item.label} ${item.class_id}`).includes(term)))
      .sort((a, b) => Number(fold(b.code).replace(/^de:/, "") === query) - Number(fold(a.code).replace(/^de:/, "") === query)
        || a.label.localeCompare(b.label, "de", {numeric: true})).slice(0, limit);
  }
  function groupPictures(observations) {
    const unique = new Map();
    for (const item of observations || []) {
      if (!item.mobile_kind && item.image_id && !unique.has(item.image_id)) unique.set(item.image_id, item);
    }
    return [...unique.values()].sort((a, b) => String(a.sequence_id).localeCompare(String(b.sequence_id))
      || (finite(a.sequence_rank) && finite(b.sequence_rank) ? a.sequence_rank - b.sequence_rank : 0)
      || String(a.captured_at).localeCompare(String(b.captured_at)) || a.image_id.localeCompare(b.image_id));
  }
  const api = {validBox, imagePoint, dragBox, classCode, changed, groupPictures, catalogEntries, searchClasses};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.YouSpeedSignAnnotationsCore = api;
})(typeof window === "undefined" ? globalThis : window);
