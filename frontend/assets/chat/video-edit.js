(() => {
  "use strict";
  const de = () => String(document.documentElement.lang || navigator.language || "de").startsWith("de");
  const t = (g, e) => de() ? g : e;
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const style = el("style");
  style.textContent = `
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
  const actions = el("div", "nobby-video-edit-actions");
  const create = el("button", "primary", t("Video bearbeiten", "Edit video"));
  create.type = "submit";
  create.disabled = true;
  const cancel = el("button", "", t("Abbrechen", "Cancel"));
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
              hint, status, actions);
  dialog.append(header, form, result);
  overlay.append(dialog);
  document.body.appendChild(overlay);

  let asset = null;
  let jobId = null;
  let running = false;
  let poll = null;
  let sourceInfo = null;
  let version = 0;
  let lastFocus = null;

  const stopPoll = () => {if (poll !== null) clearTimeout(poll); poll = null;};
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
  }
  close.addEventListener("click", dismiss);
  overlay.addEventListener("click", event => {if (event.target === overlay) dismiss();});
  document.addEventListener("keydown", event => {
    if (!overlay.hidden && event.key === "Escape") dismiss();
  });

  async function json(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
      headers: {Accept: "application/json", ...(options.body ? {"Content-Type": "application/json"} : {}), ...(options.headers || {})},
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(String(payload.detail || `HTTP ${response.status}`));
    return payload;
  }
  function updateJob(job) {
    if (job.id !== jobId) return;
    running = !["completed", "failed", "cancelled"].includes(job.status);
    create.disabled = running || !sourceInfo;
    cancel.hidden = !running;
    status.textContent = job.status === "completed"
      ? t("Fertig! Das neue Video ist in deiner Bibliothek.", "Done! The new video is in your library.")
      : job.status === "failed"
        ? t("Bearbeitung fehlgeschlagen: ", "Editing failed: ") + (job.error || "")
        : job.status === "cancelled"
          ? t("Abgebrochen.", "Cancelled.")
          : t("LTX verarbeitet das Video … Der Vorgang kann mehrere Minuten dauern. ", "LTX is processing the video … This may take several minutes. ") + job.status;
    if (job.status === "completed" && job.result?.video_url) {
      result.src = job.result.video_url;
      result.hidden = false;
      download.href = job.result.video_url;
      download.hidden = false;
      window.dispatchEvent(new Event("mlx-video-edit-completed"));
    }
  }
  async function pollJob(id) {
    try {
      const job = await json("/api/mlx/video/edit/jobs/" + id);
      if (jobId !== id) return;
      updateJob(job);
      if (running) poll = setTimeout(() => pollJob(id), 1700);
    } catch (error) {
      if (jobId !== id) return;
      setStatus(t("Statusabfrage fehlgeschlagen: ", "Status check failed: ") + error.message);
      poll = setTimeout(() => pollJob(id), 3000);
    }
  }
  async function open(source, preferred = "extend") {
    if (!source || !["video", "talking_photo"].includes(source.kind) ||
        !/^[a-f0-9]{24}$/.test(String(source.id || ""))) {
      throw new Error(t("Ungültige Videoquelle", "Invalid video source"));
    }
    lastFocus = document.activeElement;
    const token = ++version;
    asset = {kind: source.kind, id: source.id};
    operation.value = preferred === "retake" ? "retake" : "extend";
    refreshFields();
    overlay.hidden = false;
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
      setStatus(t(`Bereit · Quelle: ${duration.toFixed(2)} s · LTX 0.18`,
                  `Ready · source: ${duration.toFixed(2)} s · LTX 0.18`));
      create.disabled = running;
    } catch (error) {
      if (token === version) setStatus(error.message);
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!sourceInfo || !asset || running) return;
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
      jobId = job.id;
      running = true;
      cancel.hidden = false;
      stopPoll();
      updateJob(job);
      pollJob(jobId);
    } catch (error) {
      setStatus(error.message);
      create.disabled = false;
    }
  });
  cancel.addEventListener("click", async () => {
    if (!jobId || !running) return;
    cancel.disabled = true;
    try {
      await json("/api/mlx/video/edit/jobs/" + jobId + "/cancel", {method: "POST", body: "{}"});
      setStatus(t("Abbruch angefordert …", "Cancellation requested …"));
    } catch (error) {
      setStatus(error.message);
    } finally {
      cancel.disabled = false;
    }
  });
  window.MLXVideoEdit = Object.freeze({open});
})();
