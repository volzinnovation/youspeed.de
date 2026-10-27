(function attachCropReview(root) {
  "use strict";
  const core = root.YouSpeedCropReviewCore;
  root.YouSpeedCropReview = {create};
  function create(getJSON, onReview = () => {}) {
    const el = id => document.getElementById("crops-" + id);
    const verdictButtons = [...document.querySelectorAll("[data-crop-verdict]")];
    let row = null, history = null, taxonomy = null, choices = [], verdict = null;
    let generation = 0, pending = null, saving = false, page = [], scope = "live";
    const token = () => el("review-token").value.trim();
    function status(text) { el("review-status").textContent = text; }
    function readOnlyMessage() {
      if (scope === "legacy") return "Nur ansehen · Altbestand ohne Analyse- oder Schreibzugriff";
      if (core.replayEvidence(row)) return "Nur ansehen · Archiv- oder Replay-Aufnahme";
      return "Nur ansehen · Herkunft nicht für die Live-Analyse freigegeben";
    }
    async function request(name, body) {
      if (!token()) throw new Error("Bitte den persönlichen Prüfschlüssel eingeben.");
      return getJSON("./api/crops/review/" + name, {method: body === undefined ? "GET" : "POST",
        headers: {Authorization: "Bearer " + token(), ...(body === undefined ? {} : {"Content-Type": "application/json"})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    }
    function setVerdict(value) {
      verdict = value; pending = null;
      for (const button of verdictButtons) button.setAttribute("aria-pressed", String(button.dataset.cropVerdict === value));
      el("review-correction").hidden = value !== "wrong_class";
    }
    function selectedChoice() { return choices.find(choice => choice.id === el("review-class").value) || null; }
    function previewChoice() {
      const choice = selectedChoice(), classification = choice?.classification;
      const artwork = core.safeArtwork(choice?.image_url);
      el("review-artwork").hidden = !artwork;
      if (artwork) el("review-artwork").src = artwork;
      else el("review-artwork").removeAttribute("src");
      el("review-value").value = classification?.value ?? "";
      el("review-unit").textContent = classification?.unit || "";
      pending = null;
    }
    function filterChoices() {
      const previous = el("review-class").value;
      const country = el("review-country").value;
      const search = el("review-search").value.trim().toLocaleLowerCase();
      const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Ersatzklasse noch unbekannt";
      const options = [empty];
      for (const choice of choices) {
        const c = choice.classification;
        if ((country && c.country !== country) || (search && !`${choice.label} ${core.classificationLabel(c)}`.toLocaleLowerCase().includes(search))) continue;
        const option = document.createElement("option"); option.value = choice.id;
        option.textContent = `${choice.label || c.canonical_code} · ${core.classificationLabel(c)}`;
        options.push(option);
      }
      el("review-class").replaceChildren(...options);
      el("review-class").value = options.some(option => option.value === previous) ? previous : "";
      previewChoice();
    }
    function installTaxonomy(data) {
      taxonomy = data;
      if (!Array.isArray(data.entries)) throw new Error("Klassenregister nicht verfügbar.");
      choices = data.entries.map((entry, index) => ({...entry, id: String(index),
        image_url: entry.image_url || (entry.image_path ? "/shared/" + entry.image_path : null),
        classification: core.validateClassification(entry.classification)}));
      const countries = [...new Set(choices.map(choice => choice.classification.country))].sort();
      const all = document.createElement("option"); all.value = ""; all.textContent = "Alle Länder";
      const options = countries.map(country => {const option = document.createElement("option"); option.value = country; option.textContent = country; return option;});
      el("review-country").replaceChildren(all, ...options);
      el("review-country").value = countries.includes(row?.observation?.classification?.country) ? row.observation.classification.country : "";
      filterChoices();
    }
    function updateExport() {
      const count = core.exportMembers(page, scope).length;
      el("export").disabled = !count || !token() || saving;
      el("export").textContent = `Geprüfte Seite exportieren (${count})`;
    }
    function showHistory(value) {
      history = value;
      el("review-current").textContent = `${core.reviewLabel(value.current_review)} · Revision ${value.current_revision}`;
      el("review-fields").disabled = !core.eligible(row, scope) || value.eligible !== true || saving;
      el("review-undo").disabled = !value.current_review || value.current_review.verdict === "unreviewed";
      el("review-history").replaceChildren();
      for (const item of value.history || []) {
        const li = document.createElement("li");
        li.textContent = `Revision ${item.revision} · ${core.reviewLabel(item)} · ${item.reviewer || "—"} · ${item.reviewed_at || item.created_at || "—"}${item.reason ? " · " + item.reason : ""}`;
        el("review-history").append(li);
      }
      if (value.eligible !== true) el("review-eligibility").textContent = readOnlyMessage();
      else el("review-eligibility").textContent = "Live-Aufnahme · Prüfung dieses einzelnen Crops";
      row.current_revision = value.current_revision;
      row.current_review = value.current_review;
      onReview(row);
      updateExport();
    }
    function clear() {
      ++generation; row = null; history = null; pending = null; saving = false; setVerdict(null);
      el("review-fields").disabled = true;
      el("review-original").textContent = "—"; el("review-current").textContent = "—";
      el("review-eligibility").textContent = "Crop auswählen.";
      el("review-history").replaceChildren(); el("review-reason").value = "";
      el("review-search").value = ""; el("review-class").value = ""; previewChoice(); status("");
      el("exit-status").textContent = "Noch kein Crop ausgewählt."; el("exit-provenance").textContent = "";
    }
    async function select(value) {
      clear(); row = value; const current = generation;
      el("review-original").textContent = core.classificationLabel(row.observation?.classification);
      el("review-current").textContent = core.reviewLabel(row.current_review);
      const context = row.exit_context;
      const state = typeof context === "string" ? context : context?.result || context?.status || "not_computed";
      const explanation = core.exitReasons[context?.reason];
      el("exit-status").textContent = (core.exitLabels[state] || state) + (explanation ? " · " + explanation : "")
        + " · keine Aussage zur Straßenzuordnung des Zeichens";
      el("exit-provenance").textContent = context ? JSON.stringify(context, null, 2) : "";
      if (!core.eligible(row, scope)) {
        el("review-eligibility").textContent = readOnlyMessage();
        return;
      }
      el("review-eligibility").textContent = "Live-Aufnahme · Prüfstand noch nicht geladen";
      if (!token()) { status("Prüfschlüssel eingeben und Prüfstand laden."); return; }
      status("Prüfstand wird geladen …");
      try {
        const [loaded, classes] = await Promise.all([request("history", core.identity(value)), taxonomy ? Promise.resolve(taxonomy) : request("taxonomy")]);
        if (current !== generation) return;
        installTaxonomy(classes); showHistory(loaded); status("Prüfstand geladen. Originalerkennung bleibt unverändert.");
      } catch (error) { if (current === generation) status(error.message); }
    }
    async function save(undo = false) {
      if (saving || !row || !history) return;
      const current = generation, selected = row;
      try {
        const form = {verdict: undo ? "unreviewed" : verdict, corrected: selectedChoice()?.classification || null,
          reviewer: el("reviewer").value, reason: el("review-reason").value};
        // Keep the same UUID after an uncertain network result. Explicit form
        // edits/new selections invalidate it; retries cannot append duplicates.
        if (!pending || pending.verdict !== form.verdict) pending = core.decision(selected, history, form, crypto.randomUUID(), scope);
        saving = true; el("review-fields").disabled = true; updateExport(); status("Prüfung wird gespeichert …");
        await request("save", {decision: pending});
        if (current !== generation) return;
        pending = null;
        const latest = await request("history", core.identity(selected));
        if (current !== generation) return;
        saving = false; showHistory(latest); setVerdict(null);
        status(undo ? "Prüfung zurückgenommen. Der Verlauf bleibt erhalten." : "Prüfung gespeichert und erneut geladen. Originalerkennung unverändert.");
      } catch (error) {
        if (current !== generation) return;
        if (error.status === 409) {
          pending = null; history = null;
          status("Inzwischen wurde eine andere Prüfung gespeichert. Prüfstand neu laden und Ihre Entscheidung erneut prüfen.");
        } else status(error.message + " Bei unklarer Übertragung denselben Speichervorgang erneut versuchen.");
      } finally {
        if (current === generation) {saving = false; el("review-fields").disabled = !history || !core.eligible(row, scope) || history.eligible !== true; updateExport();}
      }
    }
    async function exportPage() {
      const members = core.exportMembers(page, scope);
      if (!members.length || members.length > 100) return;
      el("export").disabled = true; el("export-status").textContent = "Geprüfte Revisionen werden exportiert …";
      try {
        const result = await request("export", {members});
        const blob = new Blob([JSON.stringify(result, null, 2) + "\n"], {type: "application/json"});
        const url = URL.createObjectURL(blob), link = document.createElement("a");
        link.href = url; link.download = "youspeed-reviewed-crops.json"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        el("export-status").textContent = `${members.length} explizite Quellidentitäten und Prüfrevisionen exportiert. Kein automatischer Trainings- oder Akzeptanzsplit.`;
      } catch (error) { el("export-status").textContent = error.message; }
      finally { updateExport(); }
    }
    for (const button of verdictButtons) button.addEventListener("click", () => setVerdict(button.dataset.cropVerdict));
    for (const name of ["review-country", "review-search"]) el(name).addEventListener("input", filterChoices);
    el("review-class").addEventListener("change", previewChoice);
    for (const name of ["reviewer", "review-reason"]) el(name).addEventListener("input", () => {pending = null;});
    el("review-connect").addEventListener("click", () => {taxonomy = null; if (row) void select(row);});
    el("review-token").addEventListener("input", () => {pending = null; taxonomy = null; ++generation; history = null; el("review-fields").disabled = true; updateExport();});
    el("review-form").addEventListener("submit", event => {event.preventDefault(); void save();});
    el("review-undo").addEventListener("click", () => void save(true));
    el("export").addEventListener("click", () => void exportPage());
    window.addEventListener("pagehide", () => {el("review-token").value = ""; clear();});
    return {select, clear, setPage(rows, selectedScope) {page = rows; scope = selectedScope || "live"; updateExport();},
      core};
  }
})(window);
