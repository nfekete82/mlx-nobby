(() => {
  "use strict";
  const de = () => String(document.documentElement.lang || navigator.language || "de").startsWith("de");
  const t = (g, e) => de() ? g : e;
  const tr = (key, g, e) => window.MLXI18n?.t("video_edit." + key, t(g, e)) || t(g, e);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const style = el("style");
  style.textContent = `
  .nobby-video-edit-resume{position:fixed;bottom:18px;right:18px;z-index:10090;max-width:calc(100vw - 36px);padding:10px 14px;background:#243852;color:#fff;border:1px solid #7187a6;border-radius:10px;cursor:pointer}
  .nobby-video-edit-resume[hidden]{display:none}
  .nobby-video-edit progress{width:100%;accent-color:#60a5fa}
  .nobby-video-edit[hidden]{display:none!important}
  .nobby-video-edit{position:fixed;inset:0;z-index:10100;display:grid;place-items:center;padding:16px;background:rgba(3,8,18,.78)}
  .nobby-video-edit-dialog{background:#111d2d;border:1px solid #42526a;border-radius:16px;color:#edf2fc;
    width:min(540px,100%);max-height:calc(100dvh - 32px);overflow:auto;box-sizing:border-box;padding:22px;display:grid;gap:13px}
  .nobby-video-edit-header{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .nobby-video-edit-header h2{margin:0;font-size:1.2rem}
  .nobby-video-edit-field{display:grid;gap:6px;font-size:.9rem}
  .nobby-video-edit-field input,.nobby-video-edit-field select,.nobby-video-edit-field textarea{
    width:100%;box-sizing:border-box;background:#192941;border:1px solid #53657f;border-radius:8px;color:inherit;
    padding:10px 12px;font:inherit}
  .nobby-video-edit-field textarea{min-height:85px;resize:vertical}
  .nobby-video-edit-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
  .nobby-video-edit-actions button,.nobby-video-edit-actions a,.nobby-video-edit-header button{
    background:#243852;border:1px solid #506582;border-radius:9px;color:inherit;padding:9px 13px;font:inherit;cursor:pointer;text-decoration:none}
  .nobby-video-edit-actions .primary{background:#2563eb;border-color:#3b82f6}
  .nobby-video-edit-actions button:disabled{opacity:.5;cursor:default}
  .nobby-video-edit-status{font-size:.85rem;white-space:pre-wrap;color:#cbd7ea}
  .nobby-video-edit-hint{font-size:.79rem;color:#a8b9d0;line-height:1.45}
  .nobby-video-edit-result[hidden],.nobby-video-edit-retake[hidden],.nobby-video-edit-extend[hidden]{display:none}
  .nobby-video-edit-result{width:100%;max-height:300px;background:#030712;border-radius:8px}
  `;
  document.head.appendChild(style);

  const overlay = el("div", "nobby-video-edit");
  overlay.hidden = true;
  const dialog = el("section", "nobby-video-edit-dialog");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "nobbyVideoEditTitle");
  const header = el("div", "nobby-video-edit-header");
  const title = el("h2", "", "LTX 0.18 Video-Editor");
  title.id = "nobbyVideoEditTitle";
  const close = el("button", "", "×");
  close.type = "button";
  close.setAttribute("aria-label", t("Schließen", "Close"));
  header.append(title, close);
  const form = el("form");
  form.style.display = "grid";
  form.style.gap = "12px";

  function field(label, control, classname = "") {
    const wrap = el("label", "nobby-video-edit-field " + classname);
    wrap.append(el("span", "", label), control);
    return wrap;
  }
  const operation = el("select");
  operation.id = "nobbyVideoEditOperation";
  for (const [value, label] of [
    ["extend", t("Verlängern (Extend)", "Extend video")],
    ["retake", t("Bereich neu generieren (Retake)", "Retake segment")],
  ]) {
    const opt = el("option", "", label);
    opt.value = value;
    operation.append(opt);
  }
  const prompt = el("textarea");
  prompt.required = true;
  prompt.minLength = 3;
  prompt.maxLength = 2000;
  prompt.placeholder = t("Beschreibe die Bewegung oder Veränderung …", "Describe the motion or change …");
  const quality = el("select");
  for (const [value, label] of [
    ["fast", t("Schnell · Distilled (experimentell)", "Fast · Distilled (experimental)")],
    ["classic", t("Direkt · 30 Schritte (langsamer)", "Direct · 30 steps (slower)")],
  ]) {
    const opt = el("option", "", label);
    opt.value = value;
    quality.append(opt);
  }
  const amount = el("select");
  for (const value of [1,2,4,8,12]) {
    const opt = el("option", "", t(`+${value} LTX-Frames (ca. ${(value / 3).toFixed(1)} s)`,
      `+${value} latent frames (~${(value / 3).toFixed(1)} s)`));
    opt.value = String(value);
    amount.append(opt);
  }
  amount.value = "4";
  const start = el("input"); start.type = "number"; start.min = "0"; start.step = "0.01"; start.value = "0";
  const end = el("input"); end.type = "number"; end.min = "0.01"; end.step = "0.01"; end.value = "1";
  const extendField = field(t("Verlängerung", "Added length"), amount, "nobby-video-edit-extend");
  const startField = field(t("Anfang des Bereichs (Sekunden)", "Segment start (seconds)"), start, "nobby-video-edit-retake");
  const endField = field(t("Ende des Bereichs (Sekunden)", "Segment end (seconds)"), end, "nobby-video-edit-retake");
  const hint = el("div", "nobby-video-edit-hint");
  hint.textContent = t(
    "Experimentell. Die Originaldatei bleibt erhalten; das Ergebnis erscheint als neues Video in deiner Bibliothek. Bei Retake bleibt die Tonspur unverändert.",
    "Experimental. The original remains untouched; the result is a new library video. Retake preserves source audio."
  );
  const status = el("div", "nobby-video-edit-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const progress = el("progress");
  progress.max = 1;
  progress.hidden = true;
  progress.setAttribute("aria-label", tr("phase_progress", "Fortschritt der Teilphase", "Current phase progress"));
  const timing = el("div", "nobby-video-edit-hint");
  const backgroundHint = el("div", "nobby-video-edit-hint", tr("background", "Schließen lässt den Auftrag im Hintergrund weiterlaufen. Über den Video-Editor-Button kannst du zurückkehren.", "Closing keeps the job running in the background. Return using the video editor button."));
  const resumeButton = el("button", "nobby-video-edit-resume", tr("resume", "Video-Editor öffnen", "Open video editor"));
  resumeButton.type = "button";
  resumeButton.hidden = true;
  document.body.appendChild(resumeButton);
  resumeButton.addEventListener("click", () => { lastFocus = document.activeElement; overlay.hidden = false; close.focus(); });
  const actions = el("div", "nobby-video-edit-actions");
  const create = el("button", "primary", t("Video bearbeiten", "Edit video"));
  create.type = "submit";
  create.disabled = true;
  const cancel = el("button", "", tr("cancel", "Bearbeitung abbrechen", "Cancel edit"));
  cancel.type = "button";
  cancel.hidden = true;
  const download = el("a", "", t("Ergebnis ansehen", "View result"));
  download.target = "_blank"; download.rel = "noopener noreferrer"; download.hidden = true;
  actions.append(create, cancel, download);
  const result = el("video", "nobby-video-edit-result");
  result.controls = true; result.playsInline = true; result.hidden = true;
  form.append(field(t("Aktion", "Action"), operation),
              field(t("Prompt für die Änderung", "Edit prompt"), prompt),
              field(t("Modus", "Mode"), quality), extendField, startField, endField,
              hint, backgroundHint, progress, timing, status, actions);
  dialog.append(header, form, result);
  overlay.append(dialog);
  document.body.appendChild(overlay);

  let asset = null;
  let jobId = null;
  let running = false;
  let poll = null;
  let pollEpoch = 0;
  let sourceInfo = null;
  let version = 0;
  let lastFocus = null;
  let lastJob = null;
  let cancelPending = false;
  let recovering = null;
  const storageKey = "mlx-video-edit-active-v1";
  const validId = id => /^[a-f0-9]{24}$/.test(String(id || ""));
  function savedId() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (value?.version === 1 && validId(value.id)) return value.id;
      localStorage.removeItem(storageKey);
    } catch (_) { try { localStorage.removeItem(storageKey); } catch (_) {} }
    return null;
  }
  function saveActive(id) {
    try {
      if (id) localStorage.setItem(storageKey, JSON.stringify({version: 1, id}));
      else if (savedId() === jobId) localStorage.removeItem(storageKey);
    } catch (_) { /* Backend discovery also works when storage is disabled. */ }
  }
  function renderTiming() {
    if (!lastJob?.started_at) { timing.textContent = ""; return; }
    const elapsed = Math.max(0, Math.floor((lastJob.finished_at || Date.now()/1000) - lastJob.started_at));
    const activity = lastJob.last_activity_at;
    timing.textContent = tr("elapsed", "Laufzeit", "Elapsed") + `: ${elapsed} s · ` +
      tr("activity", "Letzte bestätigte Aktivität", "Last confirmed activity") + ": " +
      (activity ? new Date(activity * 1000).toLocaleTimeString() : tr("waiting", "noch keine LTX-Ausgabe", "waiting for LTX output"));
  }
  let clock = setInterval(renderTiming, 1000);
  window.addEventListener("pagehide", () => { stopPoll(); clearInterval(clock); clock = null; });
  window.addEventListener("pageshow", () => { if (clock === null) clock = setInterval(renderTiming, 1000); if (jobId && running) { stopPoll(); pollJob(jobId); } });
  window.addEventListener("storage", event => { if (event.key === storageKey) recover(); });


  const stopPoll = () => {pollEpoch++; if (poll !== null) clearTimeout(poll); poll = null;};
  const setStatus = message => {status.textContent = message;};
  function refreshFields() {
    const isRetake = operation.value === "retake";
    extendField.hidden = isRetake;
    startField.hidden = !isRetake;
    endField.hidden = !isRetake;
  }
  operation.addEventListener("change", refreshFields);
  refreshFields();

  function dismiss() {
    overlay.hidden = true;
    lastFocus?.focus?.();
    if (running) resumeButton.hidden = false;
  }
  close.addEventListener("click", dismiss);
  overlay.addEventListener("click", event => {if (event.target === overlay) dismiss();});
  document.addEventListener("keydown", event => {
    if (!overlay.hidden && event.key === "Escape") dismiss();
    if (!overlay.hidden && event.key === "Tab") {
      const nodes = [...dialog.querySelectorAll("button, input, select, textarea, a[href], video")]
        .filter(node => !node.disabled && !node.hidden && node.getClientRects().length);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });

  async function json(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(url, {
        cache: "no-store", ...options, signal: controller.signal,
        headers: {Accept: "application/json", ...(options.body ? {"Content-Type": "application/json"} : {}), ...(options.headers || {})},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(String(payload.detail || `HTTP ${response.status}`));
        error.status = response.status;
        throw error;
      }
      return payload;
    } finally { clearTimeout(timeout); }
  }
  function updateJob(job) {
    if (job.id !== jobId) return;
    lastJob = job;
    running = !["completed", "failed", "cancelled"].includes(job.status);
    cancelPending = running && (Boolean(job.cancel_requested) || job.status === "cancelling");
    cancel.disabled = cancelPending;
    resumeButton.hidden = false;
    if (running) saveActive(jobId); else saveActive(null);
    progress.hidden = !running;
    const fraction = job.phase_progress;
    if (typeof fraction === "number" && Number.isFinite(fraction) && fraction >= 0 && fraction <= 1) {
      progress.value = fraction;
      progress.setAttribute("aria-valuetext", tr("phase_progress", "Fortschritt der Teilphase", "Current phase progress") + `: ${Math.round(fraction * 100)} %`);
    } else {
      progress.removeAttribute("value");
      progress.removeAttribute("aria-valuetext");
    }
    renderTiming();
    create.disabled = running || !sourceInfo;
    cancel.hidden = !running;
    status.textContent = job.status === "completed"
      ? t("Fertig! Das neue Video ist in deiner Bibliothek.", "Done! The new video is in your library.")
      : job.status === "failed"
        ? t("Bearbeitung fehlgeschlagen: ", "Editing failed: ") + (job.error || "")
        : job.status === "cancelled"
          ? t("Abgebrochen.", "Cancelled.")
          : cancelPending
            ? tr("stopping", "Wird beendet …", "Stopping …")
            : phaseText(job) + (Number.isInteger(job.current_step) && Number.isInteger(job.total_steps) && job.total_steps > 0
              ? ` · ${job.current_step}/${job.total_steps} ` + tr("phase_steps", "Schritte (Teilphase)", "steps (current phase)") : "");
    if (job.status === "completed" && job.result?.video_url) {
      result.src = job.result.video_url;
      result.hidden = false;
      download.href = job.result.video_url;
      download.hidden = false;
      window.dispatchEvent(new Event("mlx-video-edit-completed"));
    }
  }
  function phaseText(job) {
    const phases = {
      queued: ["Warte auf LTX", "Waiting for LTX"], preparing: ["Ressourcen werden vorbereitet", "Preparing resources"],
      loading: ["LTX lädt Modelle", "Loading LTX models"], encoding: ["LTX kodiert Eingaben", "LTX is encoding inputs"],
      encoding_prompt: ["LTX kodiert den Prompt", "LTX is encoding the prompt"],
      generating: ["LTX generiert Videoframes", "LTX is generating video frames"], decoding: ["Video wird dekodiert", "Decoding video"],
      saving: ["Video wird gespeichert", "Saving video"], stage_1: ["LTX Generierung · Stage 1", "LTX generation · Stage 1"],
      stage_2: ["LTX Verfeinerung · Stage 2", "LTX refinement · Stage 2"],
    };
    const phase = job.phase || job.status;
    const text = phases[phase] || phases.generating;
    return tr("phase_" + phase, ...text);
  }
  async function recover() {
    if (recovering) return recovering;
    recovering = (async () => {
      const remembered = savedId();
      try {
        const data = await json("/api/mlx/video/edit/jobs");
        let job = (data.jobs || [])[0];
        if (!job && remembered) {
          try { job = await json("/api/mlx/video/edit/jobs/" + remembered); }
          catch (error) { if (error.status === 404) saveActive(null); else throw error; }
        }
        if (job && validId(job.id)) {
          const changed = jobId !== job.id;
          jobId = job.id;
          asset = {kind: job.source_kind, id: job.source_id};
          if (changed) { result.hidden = true; download.hidden = true; cancelPending = false; }
          stopPoll();
          updateJob(job);
          if (running) pollJob(jobId);
        }
      } catch (error) {
        setStatus(tr("recover_error", "Wiederherstellung fehlgeschlagen: ", "Recovery failed: ") + error.message);
        resumeButton.hidden = false;
        stopPoll();
        poll = setTimeout(recover, 3000);
      }
    })();
    try { await recovering; } finally { recovering = null; }
  }
  async function pollJob(id) {
    const epoch = pollEpoch;
    try {
      const job = await json("/api/mlx/video/edit/jobs/" + id);
      if (job.id !== id || typeof job.status !== "string") throw new Error(tr("invalid_status", "Ungültige Statusantwort", "Invalid status response"));
      if (jobId !== id || epoch !== pollEpoch) return;
      updateJob(job);
      if (running) poll = setTimeout(() => pollJob(id), 1700);
    } catch (error) {
      if (jobId !== id || epoch !== pollEpoch) return;
      if (error.status === 404) {
        saveActive(null); running = false; cancel.hidden = true; create.disabled = !sourceInfo;
        progress.hidden = true; setStatus(error.message); return;
      }
      setStatus(t("Statusabfrage fehlgeschlagen: ", "Status check failed: ") + error.message);
      poll = setTimeout(() => pollJob(id), 3000);
    }
  }
  async function open(source, preferred = "extend") {
    await recover();
    if (!source || !["video", "talking_photo"].includes(source.kind) ||
        !/^[a-f0-9]{24}$/.test(String(source.id || ""))) {
      throw new Error(t("Ungültige Videoquelle", "Invalid video source"));
    }
    if (running) {
      overlay.hidden = false;
      close.focus();
      setStatus(t("Ein Edit läuft noch. Du kannst ihn hier verfolgen oder abbrechen.", "An edit is still running. Track or cancel it here."));
      return;
    }
    lastFocus = document.activeElement;
    const token = ++version;
    asset = {kind: source.kind, id: source.id};
    operation.value = preferred === "retake" ? "retake" : "extend";
    refreshFields();
    overlay.hidden = false;
    close.focus();
    result.hidden = true;
    result.removeAttribute("src");
    download.hidden = true;
    sourceInfo = null;
    create.disabled = true;
    setStatus(t("LTX und Quelle werden geprüft …", "Checking LTX and source …"));
    try {
      const params = new URLSearchParams({source_kind: asset.kind, source_id: asset.id});
      const data = await json("/api/mlx/video/edit/status?" + params);
      if (token !== version) return;
      sourceInfo = data.source;
      const duration = data.source.duration_seconds;
      start.max = String(duration);
      end.max = String(duration);
      end.value = String(Math.min(1, duration));
      setStatus(t(`Bereit · Quelle: ${duration.toFixed(2)} s · LTX 0.18`, `Ready · source: ${duration.toFixed(2)} s · LTX 0.18`));
      create.disabled = running;
    } catch (error) {
      if (token === version) setStatus(error.message);
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!sourceInfo || !asset || running) return;
    running = true;
    create.disabled = true;
    setStatus(t("Starte LTX-Job …", "Starting LTX job …"));
    try {
      const job = await json("/api/mlx/video/edit/jobs", {
        method: "POST",
        body: JSON.stringify({
          source_kind: asset.kind,
          source_id: asset.id,
          operation: operation.value,
          prompt: prompt.value.trim(),
          distilled: quality.value === "fast",
          extend_frames: Number(amount.value),
          start_seconds: Number(start.value),
          end_seconds: Number(end.value),
          seed: 42,
        }),
      });
      if (!validId(job.id)) throw new Error(tr("invalid_status", "Ungültige Statusantwort", "Invalid status response"));
      jobId = job.id;
      running = true;
      cancel.hidden = false;
      stopPoll();
      updateJob(job);
      pollJob(jobId);
    } catch (error) {
      running = false;
      setStatus(error.message);
      create.disabled = false;
      await recover();
    }
  });
  cancel.addEventListener("click", async () => {
    if (!jobId || !running || cancelPending) return;
    cancelPending = true;
    stopPoll();
    cancel.disabled = true;
    setStatus(tr("cancel_requested", "Abbruch angefordert …", "Cancellation requested …"));
    try {
      const job = await json("/api/mlx/video/edit/jobs/" + jobId + "/cancel", {method: "POST", body: "{}"});
      updateJob(job);
      stopPoll();
      if (running) pollJob(jobId);
    } catch (error) {
      cancelPending = false;
      cancel.disabled = false;
      poll = setTimeout(() => pollJob(jobId), 1700);
      setStatus(tr("cancel_error", "Abbruch nicht bestätigt; erneut versuchen: ", "Cancellation unconfirmed; retry: ") + error.message);
    }
  });
  recover();
  window.MLXVideoEdit = Object.freeze({open});
})();
