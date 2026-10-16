(() => {
  "use strict";
  const panel = document.getElementById("nobbyLibrary");
  const grid = document.getElementById("nobbyLibraryGrid");
  const toggle = document.getElementById("sidebarLibraryButton");
  const close = document.getElementById("nobbyLibraryClose");
  if (!panel || !grid || !toggle) return;
  const state = { kind: "all", engine: "all", query: "", assets: [], loaded: false, generation: 0 };
  const metadataCache = new Map();
  let mediaObserver = null;
  const de = () => String(window.MLXI18n?.getLanguage?.() || document.documentElement.lang || "de").startsWith("de");
  const t = (g, e) => de() ? g : e;
  function elt(tag, className, label) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (label !== undefined) element.textContent = label;
    return element;
  }
  function setVisible(visible) {
    if (!visible) closePreview();
    panel.hidden = !visible;
    panel.setAttribute("aria-hidden", String(!visible));
    document.body.classList.toggle("nobby-library-open", visible);
    if (visible) {
      state.loaded = true;
      refresh();
      close?.focus();
    } else {
      ++state.generation;
      toggle.focus();
    }
  }

  const preview = elt("div", "nobby-library-preview");
  preview.hidden = true;
  preview.setAttribute("role", "dialog");
  preview.setAttribute("aria-modal", "true");
  preview.setAttribute("aria-label", t("Medienvorschau", "Media preview"));
  const backdrop = elt("button", "nobby-library-preview-backdrop");
  backdrop.type = "button";
  backdrop.setAttribute("aria-label", t("Vorschau schließen", "Close preview"));
  const shell = elt("div", "nobby-library-preview-shell");
  const previewClose = elt("button", "nobby-library-preview-close", "×");
  previewClose.type = "button";
  previewClose.setAttribute("aria-label", t("Vorschau schließen", "Close preview"));
  const previewBody = elt("div", "nobby-library-preview-body");
  shell.append(previewClose, previewBody);
  preview.append(backdrop, shell);
  document.body.appendChild(preview);
  let previousFocus = null;
  function closePreview() {
    if (preview.hidden) return;
    preview.hidden = true;
    previewBody.querySelector("video")?.pause();
    previewBody.replaceChildren();
    if (previousFocus?.isConnected) previousFocus.focus();
    previousFocus = null;
  }
  async function createFromImage(asset) {
    if (asset.kind !== "image" || !window.MLXTalkingPhoto?.openWithImage) {
      window.alert(t("Talking Photo ist noch nicht bereit.", "Talking Photo is not ready."));
      return;
    }
    try {
      const response = await fetch(asset.url, {cache: "no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const blob = await response.blob();
      if (!blob.size || blob.size > 10 * 1024 * 1024) throw new Error(t("Foto ist zu groß.", "Photo is too large."));
      const file = new File([blob], "nobby-library-" + asset.id + ".png", {type: "image/png"});
      setVisible(false);
      await window.MLXTalkingPhoto.openWithImage(file);
    } catch (error) {
      window.alert(t("Bild konnte nicht geladen werden: ", "Could not load image: ") + error.message);
    }
  }
  function thumbnailUrl(asset) {
    return "/api/library/assets/" + encodeURIComponent(asset.kind) + "/" +
      encodeURIComponent(asset.id) + "/thumbnail";
  }
  function metadataUrl(asset) {
    return "/api/library/assets/" + encodeURIComponent(asset.kind) + "/" +
      encodeURIComponent(asset.id) + "/metadata";
  }
  const formatDuration = seconds => {
    const value = Number(seconds);
    if (!(value > 0 && Number.isFinite(value))) return "";
    return Math.floor(value / 60) + ":" + String(Math.floor(value % 60)).padStart(2, "0") + " min";
  };
  function engineLabel(asset) {
    const engine = asset.engine || metadataCache.get(asset.kind + ":" + asset.id)?.engine;
    return ({
      "ltx-distilled": "LTX Distilled",
      "ltx": "LTX direkt",
      "quality": "LTX + MuseTalk",
      "fast": "MuseTalk",
    })[engine] || (asset.kind === "talking_photo" ? "Talking Photo" : "Video");
  }
  function observeMetadata(asset, target) {
    if (asset.kind === "image") return;
    const key = asset.kind + ":" + asset.id;
    const show = info => {
      if (!target.isConnected) return;
      target.textContent = [engineLabel({...asset, engine: info?.engine || asset.engine}),
        formatDuration(info?.duration_seconds)].filter(Boolean).join(" · ");
    };
    if (metadataCache.has(key)) { show(metadataCache.get(key)); return; }
    target.dataset.metadataUrl = metadataUrl(asset);
    const load = async () => {
      if (target.dataset.requested) return;
      target.dataset.requested = "1";
      try {
        const response = await fetch(metadataUrl(asset), {cache: "no-store"});
        if (!response.ok) return;
        const info = await response.json();
        if (typeof info !== "object" || !info || info.id !== asset.id || info.kind !== asset.kind) return;
        metadataCache.set(key, info);
        show(info);
      } catch (_error) { /* Media metadata is noncritical. */ }
    };
    if (typeof IntersectionObserver === "function") {
      if (!mediaObserver) mediaObserver = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          mediaObserver.unobserve(entry.target);
          entry.target._loadLibraryMetadata?.();
        }
      }, {rootMargin: "160px"});
      target._loadLibraryMetadata = load;
      mediaObserver.observe(target);
    } else { load(); }
  }
  function showPreview(asset) {
    closePreview();
    previousFocus = document.activeElement;
    const media = elt(asset.kind === "image" ? "img" : "video");
    media.src = asset.url;
    if (asset.kind === "image") {
      media.alt = t("Generiertes Bild", "Generated image");
    } else {
      media.controls = true;
      media.playsInline = true;
      media.preload = "metadata";
      media.setAttribute("aria-label", label(asset.kind));
    }
    previewBody.replaceChildren(media);
    if (asset.kind === "image") {
      const reuse = elt("button", "nobby-library-action nobby-library-preview-use", t("Als Talking Photo verwenden", "Use for Talking Photo"));
      reuse.type = "button";
      reuse.addEventListener("click", () => { closePreview(); void createFromImage(asset); });
      previewBody.appendChild(reuse);
    }
    preview.hidden = false;
    previewClose.focus();
  }
  previewClose.addEventListener("click", closePreview);
  backdrop.addEventListener("click", closePreview);
  document.addEventListener("keydown", event => {
    if (preview.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closePreview();
    } else if (event.key === "Tab") {
      const focusable = [previewClose, ...previewBody.querySelectorAll("button, a[href]")];
      if (event.shiftKey && document.activeElement === focusable[0]) {
        event.preventDefault();
        focusable[focusable.length - 1].focus();
      } else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) {
        event.preventDefault();
        focusable[0].focus();
      }
    }
  });
  const formatDate = value => new Date(Number(value) * 1000).toLocaleDateString(de() ? "de-DE" : "en-US");
  function label(kind) {
    if (kind === "image") return t("Bild", "Image");
    if (kind === "talking_photo") return "Talking Photo";
    return "Video";
  }
  function link(url, name, download) {
    const anchor = elt("a", "nobby-library-action", name);
    anchor.href = download ? url + "?download=1" : url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
  }
  async function action(method, asset, suffix = "") {
    const url = "/api/library/assets/" + encodeURIComponent(asset.kind) + "/" +
      encodeURIComponent(asset.id) + suffix;
    const response = await fetch(url, { method });
    if (!response.ok) throw new Error(t("Aktion fehlgeschlagen", "Action failed") + " (HTTP " + response.status + ")");
    return response.json();
  }
  function card(asset) {
    const box = elt("article", "nobby-library-card");
    const media = elt("div", "nobby-library-media");
    if (asset.kind === "image") {
      const image = elt("img");
      image.src = asset.url;
      image.loading = "lazy";
      image.alt = t("Generiertes Bild", "Generated image");
      media.appendChild(image);
    } else {
      const image = elt("img");
      image.src = thumbnailUrl(asset);
      image.loading = "lazy";
      image.alt = t("Videovorschaubild", "Video thumbnail");
      image.addEventListener("error", () => {
        image.hidden = true;
        media.classList.add("nobby-library-no-thumbnail");
      }, {once: true});
      media.appendChild(image);
      media.appendChild(elt("span", "nobby-library-play-icon", "▶"));
    }

    const zoom = elt("button", "nobby-library-zoom");
    zoom.type = "button";
    zoom.title = t("Vorschau öffnen", "Open preview");
    zoom.setAttribute("aria-label", t("Vorschau öffnen: ", "Open preview: ") + label(asset.kind));
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "10.5");
    circle.setAttribute("cy", "10.5");
    circle.setAttribute("r", "6.5");
    const handle = document.createElementNS("http://www.w3.org/2000/svg", "path");
    handle.setAttribute("d", "m15.5 15.5 5 5");
    icon.append(circle, handle);
    zoom.appendChild(icon);
    zoom.addEventListener("click", () => showPreview(asset));
    media.appendChild(zoom);
    box.appendChild(media);
    const text = elt("div", "nobby-library-card-body");
    text.appendChild(elt("strong", "", label(asset.kind)));
    text.appendChild(elt("span", "nobby-library-date", formatDate(asset.created_at) + " · " + (asset.persistent ? t("Dauerhaft", "Permanent") : t("Temporär", "Temporary"))));
    if (asset.kind !== "image") {
      const details = elt("span", "nobby-library-media-details", engineLabel(asset));
      text.appendChild(details);
      observeMetadata(asset, details);
    }
    const buttons = elt("div", "nobby-library-card-actions");
    buttons.append(link(asset.url, t("Download", "Download"), true));
    if (asset.kind === "image") {
      const use = elt("button", "nobby-library-action", t("Talking Photo", "Talking Photo"));
      use.type = "button";
      use.addEventListener("click", () => void createFromImage(asset));
      buttons.append(use);
    }
    const remove = elt("button", "nobby-library-action danger", t("Löschen", "Delete"));
    remove.type = "button";
    remove.addEventListener("click", async () => {
      const confirmed = window.MLXConfirm ? await window.MLXConfirm({
        title: t("Medium löschen", "Delete media"),
        message: t("Datei dauerhaft von diesem Mac löschen?", "Permanently delete this file from this Mac?"),
        confirmLabel: t("Endgültig löschen", "Delete permanently"), cancelLabel: t("Abbrechen", "Cancel")
      }) : window.confirm(t("Datei endgültig löschen?", "Permanently delete file?"));
      if (!confirmed) return;
      remove.disabled = true;
      try { await action("DELETE", asset); await refresh(); }
      catch (error) { remove.disabled = false; window.alert(error.message); }
    });
    buttons.append(remove);
    text.appendChild(buttons);
    box.appendChild(text);
    return box;
  }
  function render() {
    mediaObserver?.disconnect();
    const filter = state.query.trim().toLowerCase();
    const filtered = state.assets.filter(item =>
      (state.kind === "all" || (state.kind === "video" && ["video", "talking_photo"].includes(item.kind)) || item.kind === state.kind) &&
      (state.engine === "all" ||
        (state.engine === "talking_photo" && item.kind === "talking_photo") ||
        (state.engine === "standard" && item.kind === "video") ||
        item.engine === state.engine) &&
      (!filter || [label(item.kind), item.id, formatDate(item.created_at),
        engineLabel(item), formatDuration(metadataCache.get(item.kind + ":" + item.id)?.duration_seconds)]
        .some(value => String(value).toLowerCase().includes(filter)))
    );
    const count = document.getElementById("nobbyLibraryCount");
    if (count) count.textContent = t(filtered.length + " Medien", filtered.length + " items");
    const fragment = document.createDocumentFragment();
    if (!filtered.length) fragment.appendChild(elt("p", "nobby-library-empty",
      t("Keine gespeicherten Medien gefunden.", "No stored media found.")));
    for (const asset of filtered) fragment.appendChild(card(asset));
    grid.replaceChildren(fragment);
  }
  async function refresh() {
    const generation = ++state.generation;
    grid.replaceChildren(elt("p", "nobby-library-empty", t("Bibliothek wird geladen …", "Loading library …")));
    try {
      const response = await fetch("/api/library/assets?limit=1000", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      if (generation !== state.generation || panel.hidden) return;
      state.assets = Array.isArray(data.assets) ? data.assets : [];
      render();
    } catch (error) {
      if (generation === state.generation && !panel.hidden) {
        grid.replaceChildren(elt("p", "nobby-library-empty", t("Bibliothek nicht erreichbar: ", "Library unavailable: ") + error.message));
      }
    }
  }
  toggle.addEventListener("click", () => setVisible(true));
  document.getElementById("railLibrary")?.addEventListener("click", () => setVisible(true));
  close?.addEventListener("click", () => setVisible(false));
  document.getElementById("nobbyLibraryRefresh")?.addEventListener("click", refresh);
  document.getElementById("nobbyLibrarySaveAll")?.addEventListener("click", async event => {
    const pending = state.assets.filter(asset => !asset.persistent);
    if (!pending.length) return;
    const confirmed = window.confirm(t("Alle " + pending.length + " temporären Medien dauerhaft behalten?", "Keep all " + pending.length + " temporary media files permanently?"));
    if (!confirmed) return;
    const button = event.currentTarget;
    button.disabled = true;
    let failed = 0;
    try {
      for (const asset of pending) {
        try { await action("POST", asset, "/save"); asset.persistent = true; }
        catch (_error) { failed++; }
      }
      render();
      if (failed) window.alert(t(`${failed} Medien konnten nicht gespeichert werden.`, `${failed} files could not be saved.`));
    } finally { button.disabled = false; }
  });
  document.getElementById("nobbyLibraryDeleteAll")?.addEventListener("click", async event => {
    const button = event.currentTarget;
    // Bulk deletion intentionally covers the whole local library, not the current search.
    // Re-read the live count, as cached cards can be stale after media cleanup.
    let latest;
    try {
      const response = await fetch("/api/library/assets?limit=1000", {cache:"no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      latest = await response.json();
    } catch (error) { window.alert(error.message); return; }
    const total = Number(latest.total || 0);
    if (!total) return;
    const message = t(`Alle ${total} Bilder und Videos dauerhaft von diesem Mac löschen? Dies kann nicht rückgängig gemacht werden.`, `Permanently delete all ${total} images and videos from this Mac? This cannot be undone.`);
    const confirmed = window.MLXConfirm
      ? await window.MLXConfirm({
          title: t("Alle Medien endgültig löschen", "Permanently delete all media"),
          message, confirmLabel: t("Alle endgültig löschen", "Delete all permanently"),
          cancelLabel: t("Abbrechen", "Cancel")
        })
      : window.confirm(message);
    if (!confirmed) return;
    button.disabled = true;
    try {
      const response = await fetch("/api/library/assets/delete-all", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({kind:"all", confirm:"DELETE_ALL_MEDIA_PERMANENTLY"})
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const result = await response.json();
      await refresh();
      if (result.errors) window.alert(t(`${result.errors} Dateien konnten nicht gelöscht werden.`, `${result.errors} files could not be deleted.`));
    } catch (error) { window.alert(error.message); }
    finally { button.disabled = false; }
  });
  document.getElementById("nobbyLibrarySearch")?.addEventListener("input", event => {
    state.query = event.target.value; render();
  });
  document.getElementById("nobbyLibraryEngine")?.addEventListener("change", event => {
    state.engine = event.target.value; render();
  });
  for (const button of panel.querySelectorAll("[data-library-kind]")) {
    button.addEventListener("click", () => {
      state.kind = button.dataset.libraryKind;
      if (state.kind === "image" && state.engine !== "all") {
        state.engine = "all";
        const engineControl = document.getElementById("nobbyLibraryEngine");
        if (engineControl) engineControl.value = "all";
      }
      for (const item of panel.querySelectorAll("[data-library-kind]")) {
        item.classList.toggle("active", item === button);
        item.setAttribute("aria-pressed", String(item === button));
      }
      render();
    });
  }
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) setVisible(false);
  });
})();
