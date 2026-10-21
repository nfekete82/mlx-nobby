(() => {
 "use strict";
 const form = document.getElementById("converterForm");
 const input = document.getElementById("imageFiles");
 const status = document.getElementById("status");
 const selected = document.getElementById("selection");
 const button = document.getElementById("submit");
 const quality = document.getElementById("quality");
 const drop = document.getElementById("dropzone");
 quality.addEventListener("input", () => {
   document.getElementById("qualityText").textContent = quality.value + " %";
 });
 input.addEventListener("change", () => {
   const total = Array.from(input.files).reduce((sum, f) => sum + f.size, 0);
   selected.textContent = input.files.length + " Dateien, " + (total / 1048576).toFixed(1) + " MB";
 });
 ["dragover", "dragenter"].forEach(name => drop.addEventListener(name, event => {
   event.preventDefault(); drop.classList.add("over");
 }));
 ["dragleave", "drop"].forEach(name => drop.addEventListener(name, event => {
   event.preventDefault(); drop.classList.remove("over");
 }));
 drop.addEventListener("drop", event => {
   if (!event.dataTransfer || !event.dataTransfer.files.length) return;
   input.files = event.dataTransfer.files;
   input.dispatchEvent(new Event("change"));
 });
 form.addEventListener("submit", async event => {
   event.preventDefault();
   if (!input.files.length) return;
   const data = new FormData(form);
   button.disabled = true;
   status.textContent = "Bilder werden lokal konvertiert…";
   try {
     const response = await fetch("/api/image-converter/batch", { method: "POST", body: data });
     if (!response.ok) {
       let detail = "HTTP " + response.status;
       try { detail = (await response.json()).detail || detail; } catch (_) {}
       throw new Error(detail);
     }
     const blob = await response.blob();
     const url = URL.createObjectURL(blob);
     const a = document.createElement("a");
     a.href = url;
     a.download = "mlx-nobby-converted.zip";
     document.body.appendChild(a);
     a.click();
     a.remove();
     setTimeout(() => URL.revokeObjectURL(url), 5000);
     status.textContent = (response.headers.get("X-Converted-Count") || "Mehrere") + " Bild(er) fertig.";
   } catch (error) {
     status.textContent = "Fehler: " + error.message;
   } finally {
     button.disabled = false;
   }
 });
 fetch("/api/image-converter/formats").then(r => r.json()).then(data => {
   if (!data.heic_available) {
     status.textContent = "Hinweis: HEIC ist auf diesem Server noch nicht verfügbar.";
   }
 }).catch(() => {});
})();
