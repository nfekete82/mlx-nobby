(() => {
  "use strict";
  const panel = document.getElementById("nobbyLibrary");
  const grid = document.getElementById("nobbyLibraryGrid");
  const toggle = document.getElementById("sidebarLibraryButton");
  const close = document.getElementById("nobbyLibraryClose");
  if (!panel || !grid || !toggle) return;
  const state = { kind: "all", engine: "all", query: "", collection: "all", dateFilter: "all", sort: "newest",
    assets: [], remoteAssets: null, remoteTotal: 0, searchVersion: 0,
    organization: {favorites: [], collections: []}, workflows: {links: {}}, selected: new Set(),
    loaded: false, generation: 0 };
  const assetKey = asset => asset.kind + ":" + asset.id;
  const collectionFilter = document.getElementById("nobbyLibraryCollectionFilter");
  const collectionTarget = document.getElementById("nobbyLibraryCollectionTarget");
  const bulk = document.getElementById("nobbyLibraryBulk");

  let searchTimer = null;
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
  // Keep the preview actions visually consistent without icon fonts or new dependencies.
  function previewAction(label, paths, css = "") {
    const button = elt("button", "nobby-library-action nobby-library-preview-use " + css);
    button.type = "button";
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    for (const d of paths) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    }
    button.append(svg, elt("span", "", label));
    return button;
  }
  const previewIcons = {
    talking: ["M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z",
      "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v3", "M8 22h8"],
    video: ["M4 4h16v16H4z", "M4 9h16", "M4 15h16", "M9 4v5", "M15 15v5"],
    edit: ["M12 20H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
      "M16 4l4 4-9 9-5 1 1-5 9-9Z"],
    info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z",
      "M12 11v6", "M12 7h.01"]
  };
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
      ++state.searchVersion;
      if (searchTimer) clearTimeout(searchTimer);
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
  const previewFull = elt("button", "nobby-library-preview-fullscreen", t("Vollbild", "Fullscreen"));
  previewFull.type = "button";
  previewFull.setAttribute("aria-label", t("Vollbild umschalten", "Toggle fullscreen"));
  previewFull.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement === shell) await document.exitFullscreen();
      else if (shell.requestFullscreen) await shell.requestFullscreen();
    } catch (_error) { /* Fullscreen permission can be denied. */ }
  });
  const previewBody = elt("div", "nobby-library-preview-body");
  shell.append(previewClose, previewFull, previewBody);
  preview.append(backdrop, shell);
  document.body.appendChild(preview);
  let previousFocus = null;
  function closePreview() {
    if (preview.hidden) return;
    preview.hidden = true;
    if (document.fullscreenElement === shell) document.exitFullscreen?.().catch(() => {});
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
      await window.MLXTalkingPhoto.openWithImage(file, {sourceAsset: {kind: "image", id: asset.id}});
    } catch (error) {
      window.alert(t("Bild konnte nicht geladen werden: ", "Could not load image: ") + error.message);
    }
  }
  // Use the existing chat image-to-video pipeline and its quality picker;
  // never start a parallel renderer or silently submit a paid/heavy job.
  async function createVideoFromImage(asset) {
    if (asset.kind !== "image" || !window.MLXChatAttachments?.addFiles) {
      window.alert(t("Bildanhänge sind nicht bereit.", "Image attachments are not ready."));
      return;
    }
    try {
      const response = await fetch(asset.url, {cache: "no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const blob = await response.blob();
      if (!blob.size || blob.size > 10 * 1024 * 1024)
        throw new Error(t("Bild ist zu groß.", "Image is too large."));
      const file = new File([blob], "nobby-video-source-" + asset.id + ".png", {type: "image/png"});
      await window.MLXChatAttachments.addFiles([file]);
      const files = window.MLXChatAttachments.getAttachments?.() || [];
      const attachment = files.find(item => item.file === file && item.kind === "image");
      if (!attachment) throw new Error(t("Bild konnte nicht angehängt werden.", "Could not attach the source image."));
      attachment.library_source = {kind: "image", id: asset.id};
      const input = document.getElementById("input");
      if (!input) throw new Error(t("Chat-Eingabe fehlt.", "Chat composer unavailable."));
      const request = t("Animier dieses Bild als Video: ", "Animate this image into a video: ");
      input.value = input.value.trim()
        ? input.value.trim() + "\n" + request : request;
      input.dispatchEvent(new Event("input", {bubbles: true}));
      setVisible(false);
      input.focus();
    } catch (error) {
      window.alert(t("Video-Vorbereitung fehlgeschlagen: ", "Video preparation failed: ") + error.message);
    }
  }
  function mediaLineage(asset, container) {
    const key = assetKey(asset);
    const links = state.workflows?.links || {};
    const from = links[key];
    if (from) {
      const source = state.assets.find(item => assetKey(item) === from);
      if (source) {
        const go = elt("button", "nobby-library-parent-link",
          t("↖ Ausgangsbild anzeigen", "↖ Show source image"));
        go.type = "button";
        go.addEventListener("click", () => showPreview(source));
        container.appendChild(go);
      }
    } else if (asset.kind === "image") {
      const count = Object.values(links).filter(parent => parent === key).length;
      if (count) container.appendChild(elt("span", "nobby-library-lineage-count",
        t(count + " abgeleitete Videos", count + " derived videos")));
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
    const actions = elt("div", "nobby-library-preview-actions");
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", t("Medienaktionen", "Media actions"));
    if (asset.kind === "image") {
      const reuse = previewAction(t("Als Talking Photo verwenden", "Use for Talking Photo"), previewIcons.talking);
      reuse.addEventListener("click", () => { closePreview(); void createFromImage(asset); });
      const animate = previewAction(t("Als Video animieren", "Animate as video"), previewIcons.video);
      animate.addEventListener("click", () => { closePreview(); void createVideoFromImage(asset); });
      const regionEdit = previewAction(t("Bereich bearbeiten", "Edit region"), previewIcons.edit);
      regionEdit.addEventListener("click", () => {
        closePreview();
        setVisible(false);
        window.MLXRegionEditor?.open?.({image_id: asset.id}).catch(error =>
          window.alert(String(error?.message || error))
        );
      });
      actions.append(reuse, animate, regionEdit);
    }

    const detailsButton = previewAction(t("Details anzeigen", "Show details"), previewIcons.info,
      "nobby-library-preview-info");
    const detailsLabel = detailsButton.querySelector("span");
    detailsButton.setAttribute("aria-expanded", "false");
    detailsButton.setAttribute("aria-controls", "nobby-library-preview-details");
    const detailsPanel = elt("section", "nobby-library-detail-panel");
    detailsPanel.id = "nobby-library-preview-details";
    detailsPanel.hidden = true;
    detailsPanel.setAttribute("aria-live", "polite");
    let detailsLoaded = false;
    let detailsRequest = 0;
    detailsButton.addEventListener("click", async () => {
      if (!detailsPanel.hidden) {
        ++detailsRequest; // Invalidate any pending fetch if the user closes the panel.
        detailsPanel.hidden = true;
        detailsButton.setAttribute("aria-expanded", "false");
        detailsLabel.textContent = t("Details anzeigen", "Show details");
        return;
      }
      detailsPanel.hidden = false;
      detailsButton.setAttribute("aria-expanded", "true");
      detailsLabel.textContent = t("Details ausblenden", "Hide details");
      if (detailsLoaded) return; // Avoid another request when reopening details.
      const request = ++detailsRequest;
      detailsPanel.replaceChildren(elt("p", "", t("Details werden geladen …", "Loading details …")));
      try {
        const url = "/api/library/assets/" + encodeURIComponent(asset.kind) +
          "/" + encodeURIComponent(asset.id) + "/details";
        const response = await fetch(url, {cache: "no-store"});
        if (!response.ok) throw new Error("HTTP " + response.status);
        const info = await response.json();
        if (request !== detailsRequest || detailsPanel.hidden || preview.hidden ||
            !detailsPanel.isConnected || info.kind !== asset.kind || info.id !== asset.id) return;
        detailsPanel.replaceChildren();
        detailsPanel.appendChild(elt("strong", "", t("Mediendetails", "Media details")));
        const fields = [
          [t("Typ", "Type"), label(info.kind)],
          [t("Erstellt", "Created"), formatDate(info.created_at)],
          [t("Dateigröße", "File size"), Number.isFinite(info.size_bytes)
            ? (info.size_bytes / (1024 * 1024)).toFixed(2) + " MB" : ""],
          [t("Modell", "Model"), info.model],
          [t("Engine", "Engine"), info.engine],
          [t("Auflösung", "Resolution"), info.width && info.height
            ? info.width + " × " + info.height : ""],
          [t("Dauer", "Duration"), formatDuration(info.duration_seconds)],
          [t("Prompt", "Prompt"), info.original_prompt || info.prompt],
          [t("Anbieter", "Provider"), info.provider],
          [t("Datei-ID", "File ID"), info.id],
        ];
        for (const [name, value] of fields) {
          if (value === undefined || value === null || value === "") continue;
          const field = elt("div", "nobby-library-detail-row");
          field.appendChild(elt("span", "", name));
          field.appendChild(elt("span", "", String(value)));
          detailsPanel.appendChild(field);
        }
        detailsLoaded = true;
      } catch (_error) {
        if (request === detailsRequest && !detailsPanel.hidden &&
            !preview.hidden && detailsPanel.isConnected) {
          detailsPanel.replaceChildren(elt("p", "", t("Details sind momentan nicht verfügbar.", "Details are currently unavailable.")));
        }
      }
    });
    actions.appendChild(detailsButton);
    previewBody.append(actions);
    mediaLineage(asset, previewBody);
    previewBody.appendChild(detailsPanel);
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
      const focusable = [previewClose, previewFull, ...previewBody.querySelectorAll("button, a[href]")];
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

    const select = elt("label", "nobby-library-select");
    const checkbox = elt("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(assetKey(asset));
    checkbox.setAttribute("aria-label", t("Medium auswählen", "Select media") + ": " + label(asset.kind));
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(assetKey(asset));
      else state.selected.delete(assetKey(asset));
      syncBulk();
    });
    select.append(checkbox);
    media.appendChild(select);
    const star = elt("button", "nobby-library-star",
      state.organization.favorites.includes(assetKey(asset)) ? "★" : "☆");
    star.type = "button";
    star.title = t("Favorit umschalten", "Toggle favorite");
    star.setAttribute("aria-label", star.title);
    star.setAttribute("aria-pressed", String(state.organization.favorites.includes(assetKey(asset))));
    star.addEventListener("click", async () => {
      star.disabled = true;
      try {
        const result = await organizeBatch(
          [asset], state.organization.favorites.includes(assetKey(asset)) ? "unfavorite" : "favorite"
        );
        state.organization = result.organization;
        render();
      } catch (error) { window.alert(error.message); star.disabled = false; }
    });
    media.appendChild(star);
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
    mediaLineage(asset, text);
    const buttons = elt("div", "nobby-library-card-actions");
    buttons.append(link(asset.url, t("Download", "Download"), true));
    if (asset.kind === "image") {
      const use = elt("button", "nobby-library-action", t("Talking Photo", "Talking Photo"));
      use.type = "button";
      use.addEventListener("click", () => void createFromImage(asset));
      buttons.append(use);
      const animate = elt("button", "nobby-library-action", t("Als Video", "As video"));
      animate.type = "button";
      animate.addEventListener("click", () => void createVideoFromImage(asset));
      buttons.append(animate);
      const regionEdit = elt("button", "nobby-library-action", t("Bereich bearbeiten", "Edit region"));
      regionEdit.type = "button";
      regionEdit.addEventListener("click", () => {
        setVisible(false);
        window.MLXRegionEditor?.open?.({image_id: asset.id}).catch(error =>
          window.alert(String(error?.message || error))
        );
      });
      buttons.append(regionEdit);
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
    const infoButton = elt("button", "nobby-library-action",
      t("Details", "Details"));
    infoButton.type = "button";
    infoButton.addEventListener("click", () => {
      showPreview(asset);
      previewBody.querySelector(".nobby-library-preview-info")?.click();
    });
    buttons.append(infoButton);
    buttons.append(remove);
    text.appendChild(buttons);
    box.appendChild(text);
    return box;
  }
  function selectedAssets() {
    const seen = new Set();
    return [...state.assets, ...(state.remoteAssets || [])].filter(asset => {
      const key = assetKey(asset);
      if (!state.selected.has(key) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  function syncBulk() {
    const count = selectedAssets().length;
    if (bulk) bulk.hidden = count === 0;
    const status = document.getElementById("nobbyLibrarySelectedCount");
    if (status) status.textContent = t(`${count} ausgewählt`, `${count} selected`);
    for (const id of ["nobbyLibraryAddSelected", "nobbyLibraryRemoveSelected"]) {
      const button = document.getElementById(id);
      if (button) button.disabled = !count || !collectionTarget?.value;
    }
  }
  function renderCollections() {
    if (!collectionFilter || !collectionTarget) return;
    collectionFilter.replaceChildren();
    for (const [id, name] of [["all", t("Alle Medien", "All media")],
                              ["favorites", t("★ Favoriten", "★ Favorites")],
                              ...state.organization.collections.map(c => [c.id, c.name])]) {
      const option = elt("option", "", name);
      option.value = id;
      collectionFilter.appendChild(option);
    }
    if (!Array.from(collectionFilter.options).some(o => o.value === state.collection)) state.collection = "all";
    collectionFilter.value = state.collection;
    const currentTarget = collectionTarget.value;
    collectionTarget.replaceChildren();
    for (const item of state.organization.collections) {
      const option = elt("option", "", item.name);
      option.value = item.id;
      collectionTarget.appendChild(option);
    }
    if (Array.from(collectionTarget.options).some(o => o.value === currentTarget)) collectionTarget.value = currentTarget;
    const remove = document.getElementById("nobbyLibraryDeleteCollection");
    if (remove) remove.hidden = !state.organization.collections.some(c => c.id === state.collection);
    syncBulk();
  }
  async function organizeBatch(assets, operation, collectionId) {
    const response = await fetch("/api/library/organize/batch", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({items: assets.map(({kind, id}) => ({kind, id})),
        operation, collection_id: collectionId || null})
    });
    if (!response.ok) throw new Error(t("Organisation fehlgeschlagen", "Organization failed") + " (HTTP " + response.status + ")");
    return response.json();
  }
  function visibleAssets() {
    const filter = state.query.trim().toLowerCase();
    const terms = filter.split(/\s+/).filter(Boolean);
    const now = Date.now() / 1000;
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    const dateSince = state.dateFilter === "today" ? midnight.getTime() / 1000 :
      state.dateFilter === "week" ? now - 7 * 86400 :
      state.dateFilter === "month" ? now - 30 * 86400 : 0;
    const collection = state.organization.collections.find(c => c.id === state.collection);
    return (state.remoteAssets || state.assets).filter(item =>
      (state.kind === "all" || (state.kind === "video" && ["video", "talking_photo"].includes(item.kind)) || item.kind === state.kind) &&
      (state.engine === "all" ||
        (state.engine === "talking_photo" && item.kind === "talking_photo") ||
        (state.engine === "standard" && item.kind === "video") ||
        item.engine === state.engine) &&
      (Number(item.created_at) >= dateSince) &&
      (state.collection === "all" ||
        (state.collection === "favorites" && state.organization.favorites.includes(assetKey(item))) ||
        (collection && collection.items.includes(assetKey(item)))) &&
      (!filter || terms.every(term => [label(item.kind), item.id, item.prompt, item.original_prompt, item.model, item.provider, item.operation, formatDate(item.created_at),
        engineLabel(item), formatDuration(metadataCache.get(assetKey(item))?.duration_seconds)]
        .some(value => String(value).toLowerCase().includes(term))))
    ).sort((a, b) => {
      const first = state.sort === "largest" || state.sort === "smallest"
        ? Number(a.size_bytes || 0) - Number(b.size_bytes || 0)
        : Number(a.created_at || 0) - Number(b.created_at || 0);
      const reverse = state.sort === "largest" || state.sort === "newest";
      return (reverse ? -first : first) || assetKey(a).localeCompare(assetKey(b));
    });
  }
  function render() {
    mediaObserver?.disconnect();
    const filtered = visibleAssets();
    const count = document.getElementById("nobbyLibraryCount");
    if (count) {
      const more = state.remoteAssets && state.remoteTotal > state.remoteAssets.length;
      count.textContent = more
        ? t(filtered.length + " von " + state.remoteTotal + " Treffern",
            filtered.length + " of " + state.remoteTotal + " results")
        : t(filtered.length + " Medien", filtered.length + " items");
    }
    const fragment = document.createDocumentFragment();
    if (!filtered.length) fragment.appendChild(elt("p", "nobby-library-empty",
      t("Keine gespeicherten Medien gefunden.", "No stored media found.")));
    for (const asset of filtered) fragment.appendChild(card(asset));
    grid.replaceChildren(fragment);
    syncBulk();
  }
  async function searchRemote(version, query, kind) {
    try {
      const url = "/api/library/search?q=" + encodeURIComponent(query) +
        "&kind=" + encodeURIComponent(kind) + "&limit=500";
      const response = await fetch(url, {cache: "no-store"});
      if (!response.ok) return;
      const data = await response.json();
      if (panel.hidden || version !== state.searchVersion ||
          state.query.trim() !== query || state.kind !== kind ||
          !Array.isArray(data.assets)) return;
      state.remoteAssets = data.assets;
      state.remoteTotal = Number(data.total) || data.assets.length;
      render();
    } catch (_error) { /* Existing local search remains available. */ }
  }

  function scheduleSearch() {
    ++state.searchVersion;
    if (searchTimer) clearTimeout(searchTimer);
    state.remoteAssets = null;
    state.remoteTotal = 0;
    const query = state.query.trim();
    if (!query || panel.hidden) return;
    const version = state.searchVersion;
    const kind = state.kind;
    searchTimer = setTimeout(() => void searchRemote(version, query, kind), 250);
  }

  async function refresh() {
    const generation = ++state.generation;
    grid.replaceChildren(elt("p", "nobby-library-empty", t("Bibliothek wird geladen …", "Loading library …")));
    try {
      const [response, organized, lineage] = await Promise.all([
        fetch("/api/library/assets?limit=1000", {cache: "no-store"}),
        fetch("/api/library/organize", {cache: "no-store"}),
        fetch("/api/library/workflows", {cache: "no-store"})
      ]);
      if (!response.ok || !organized.ok || !lineage.ok)
        throw new Error("HTTP " + (!response.ok ? response.status : !organized.ok ? organized.status : lineage.status));
      const [data, organizedData, lineageData] = await Promise.all([response.json(), organized.json(), lineage.json()]);
      if (generation !== state.generation || panel.hidden) return;
      state.assets = Array.isArray(data.assets) ? data.assets : [];
      scheduleSearch();
      state.organization = organizedData;
      state.workflows = lineageData && typeof lineageData.links === "object" ? lineageData : {links: {}};
      const keys = new Set(state.assets.map(assetKey));
      for (const key of state.selected) if (!keys.has(key)) state.selected.delete(key);
      renderCollections();
      render();
    } catch (error) {
      if (generation === state.generation && !panel.hidden) {
        grid.replaceChildren(elt("p", "nobby-library-empty", t("Bibliothek nicht erreichbar: ", "Library unavailable: ") + error.message));
      }
    }
  }
  collectionFilter?.addEventListener("change", () => {
    state.collection = collectionFilter.value;
    renderCollections();
    render();
  });
  document.getElementById("nobbyLibraryNewCollection")?.addEventListener("click", async () => {
    const name = window.prompt(t("Name der neuen Sammlung:", "New collection name:"));
    if (name === null) return;
    try {
      const response = await fetch("/api/library/organize/collections", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name})
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const created = await response.json();
      state.organization.collections.push(created);
      state.collection = created.id;
      renderCollections();
      render();
    } catch (error) { window.alert(error.message); }
  });
  document.getElementById("nobbyLibraryDeleteCollection")?.addEventListener("click", async () => {
    const item = state.organization.collections.find(c => c.id === state.collection);
    if (!item) return;
    if (!window.confirm(t(`Sammlung „${item.name}“ entfernen? Medien bleiben gespeichert.`, `Remove collection "${item.name}"? Media files stay saved.`))) return;
    try {
      const response = await fetch("/api/library/organize/collections/" + encodeURIComponent(item.id), {method:"DELETE"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      state.organization.collections = state.organization.collections.filter(c => c.id !== item.id);
      state.collection = "all";
      renderCollections(); render();
    } catch (error) { window.alert(error.message); }
  });
  document.getElementById("nobbyLibrarySelectVisible")?.addEventListener("click", () => {
    for (const asset of visibleAssets()) state.selected.add(assetKey(asset));
    render();
  });
  document.getElementById("nobbyLibraryClearSelection")?.addEventListener("click", () => {
    state.selected.clear(); render();
  });
  async function bulkOrganize(operation) {
    const selected = selectedAssets();
    if (!selected.length) return;
    const collectionId = operation.endsWith("_collection") ? collectionTarget?.value : null;
    if (operation.endsWith("_collection") && !collectionId) return;
    try {
      let result;
      for (let i = 0; i < selected.length; i += 100) {
        result = await organizeBatch(selected.slice(i, i + 100), operation, collectionId);
      }
      if (result) state.organization = result.organization;
      if (operation === "favorite" || operation === "add_collection") {
        for (const asset of selected) asset.persistent = true;
      }
      renderCollections(); render();
    } catch (error) { window.alert(error.message); await refresh(); }
  }
  document.getElementById("nobbyLibraryFavoriteSelected")?.addEventListener("click", () => void bulkOrganize("favorite"));
  document.getElementById("nobbyLibraryAddSelected")?.addEventListener("click", () => void bulkOrganize("add_collection"));
  document.getElementById("nobbyLibraryRemoveSelected")?.addEventListener("click", () => void bulkOrganize("remove_collection"));
  document.getElementById("nobbyLibraryDeleteSelected")?.addEventListener("click", async () => {
    const selected = selectedAssets();
    if (!selected.length) return;
    const message = t(`${selected.length} ausgewählte Medien dauerhaft löschen? Dies kann nicht rückgängig gemacht werden.`, `Permanently delete ${selected.length} selected media files? This cannot be undone.`);
    const approved = window.MLXConfirm ? await window.MLXConfirm({
      title: t("Auswahl endgültig löschen", "Delete selection permanently"), message,
      confirmLabel: t("Endgültig löschen", "Delete permanently"), cancelLabel: t("Abbrechen", "Cancel")
    }) : window.confirm(message);
    if (!approved) return;
    let failures = 0;
    for (const asset of selected) {
      try { await action("DELETE", asset); state.selected.delete(assetKey(asset)); }
      catch (_error) { failures++; }
    }
    await refresh();
    if (failures) window.alert(t(`${failures} Medien konnten nicht gelöscht werden.`, `${failures} items could not be deleted.`));
  });
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
  document.getElementById("nobbyLibraryDateFilter")?.addEventListener("change", event => {
    state.dateFilter = event.target.value;
    render();
  });
  document.getElementById("nobbyLibrarySort")?.addEventListener("change", event => {
    state.sort = event.target.value;
    render();
  });
  document.getElementById("nobbyLibrarySearch")?.addEventListener("input", event => {
    state.query = event.target.value;
    scheduleSearch();
    render();
  });
  document.getElementById("nobbyLibraryEngine")?.addEventListener("change", event => {
    state.engine = event.target.value; render();
  });
  for (const button of panel.querySelectorAll("[data-library-kind]")) {
    button.addEventListener("click", () => {
      state.kind = button.dataset.libraryKind;
      scheduleSearch();
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
