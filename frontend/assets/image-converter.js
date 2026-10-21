(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const MAX_FILES = 50, MAX_TOTAL = 200 * 1024 * 1024, MAX_EACH = 25 * 1024 * 1024;
  const allowed = /\.(png|jpe?g|webp|heic|heif)$/i;
  const files = [];
  let busy = false;
  const size = bytes => bytes < 1024 * 1024
    ? (bytes / 1024).toFixed(0) + " KB"
    : (bytes / (1024 * 1024)).toFixed(1) + " MB";

  function status(message, error = false) {
    $("status").textContent = message;
    $("status").classList.toggle("error", error);
  }
  function render() {
    const container = $("fileList");
    container.replaceChildren();
    files.forEach((file, index) => {
      const row = document.createElement("div");
      row.className = "file";
      const icon = document.createElement("span");
      icon.className = "file-icon";
      icon.textContent = "▧";
      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = file.name;
      name.title = file.name;
      const amount = document.createElement("span");
      amount.className = "file-size";
      amount.textContent = size(file.size);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = "Datei entfernen";
      remove.setAttribute("aria-label", file.name + " entfernen");
      remove.disabled = busy;
      remove.addEventListener("click", () => {
        files.splice(index, 1);
        render();
      });
      row.append(icon, name, amount, remove);
      container.append(row);
    });
    if (!files.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Noch keine Dateien ausgewählt.";
      container.append(empty);
    }
    $("fileCount").textContent = String(files.length);
    const total = files.reduce((n, f) => n + f.size, 0);
    $("inputTotal").textContent = files.length ? "Eingabe gesamt: " + size(total) : "";
    $("clear").disabled = !files.length || busy;
    $("convert").disabled = !files.length || busy;
  }
  function add(list) {
    if (busy) return;
    const incoming = Array.from(list || []);
    let rejected = 0;
    for (const file of incoming) {
      const total = files.reduce((n, f) => n + f.size, 0);
      if (!allowed.test(file.name) || !file.size || file.size > MAX_EACH ||
          files.length >= MAX_FILES || total + file.size > MAX_TOTAL) {
        rejected++;
        continue;
      }
      files.push(file);
    }
    $("result").hidden = true;
    status(rejected ? rejected + " Datei(en) übersprungen: Format, Dateigröße oder Stapellimit." : "");
    render();
  }
  const drop = $("dropzone");
  drop.addEventListener("click", () => { if (!busy) $("files").click(); });
  drop.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!busy) $("files").click();
    }
  });
  drop.addEventListener("dragover", event => {
    event.preventDefault();
    if (!busy) drop.classList.add("hover");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("hover"));
  drop.addEventListener("drop", event => {
    event.preventDefault();
    drop.classList.remove("hover");
    add(event.dataTransfer.files);
  });
  $("files").addEventListener("change", event => {
    add(event.target.files);
    event.target.value = "";
  });
  $("clear").addEventListener("click", () => {
    files.length = 0;
    status("");
    $("result").hidden = true;
    render();
  });
  function refreshFormat() {
    const fmt = $("outputFormat").value;
    const isPng = fmt === "png";
    $("quality").disabled = busy || isPng;
    $("qualityValue").textContent = isPng ? "verlustfrei" : $("quality").value + " %";
    $("formatHint").textContent = isPng
      ? "PNG wird verlustfrei optimiert. Der Qualitätsregler hat hier keine Wirkung."
      : fmt === "jpeg"
      ? "JPG ist verlustbehaftet und eignet sich besonders für Fotos."
      : "WebP ist verlustbehaftet und behält Transparenz bei.";
  }
  $("outputFormat").addEventListener("change", refreshFormat);
  $("quality").addEventListener("input", refreshFormat);

  $("convertForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !files.length) return;
    busy = true;
    $("result").hidden = true;
    $("outputFormat").disabled = true;
    $("maxDimension").disabled = true;
    $("quality").disabled = true;
    $("actionLabel").textContent = "Bilder werden verarbeitet…";
    status("Hochladen und lokal konvertieren. Bei großen Stapeln kann das etwas dauern.");
    render();
    try {
      const form = new FormData();
      for (const file of files) form.append("files", file, file.name);
      form.append("format", $("outputFormat").value);
      form.append("quality", $("quality").value);
      form.append("max_dimension", $("maxDimension").value);
      const response = await fetch("/api/converter/images", { method: "POST", body: form });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "HTTP " + response.status);
      }
      const blob = await response.blob();
      const address = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = address;
      a.download = "mlx-nobby-bilder.zip";
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(address), 60000);
      const done = Number(response.headers.get("X-Converted-Count") || 0);
      const failed = Number(response.headers.get("X-Failed-Count") || 0);
      const inputBytes = Number(response.headers.get("X-Input-Bytes") || 0);
      const outputBytes = Number(response.headers.get("X-Output-Bytes") || 0);
      const pct = inputBytes ? Math.round((1 - outputBytes / inputBytes) * 100) : 0;
      $("result").textContent = done + " Bild(er) konvertiert · " + size(inputBytes) +
        " → " + size(outputBytes) + (pct >= 0 ? " · " + pct + " % kleiner" : " · " + (-pct) + " % größer") +
        (failed ? " · " + failed + " übersprungen (Details im ZIP-Bericht)" : "");
      $("result").hidden = false;
      status("Fertig. ZIP-Download wurde gestartet.");
    } catch (error) {
      status("Umwandlung fehlgeschlagen: " + (error.message || "Unbekannter Fehler"), true);
    } finally {
      busy = false;
      $("outputFormat").disabled = false;
      $("maxDimension").disabled = false;
      $("actionLabel").textContent = "Bilder umwandeln und ZIP herunterladen";
      refreshFormat();
      render();
    }
  });
  refreshFormat();
  render();
})();
