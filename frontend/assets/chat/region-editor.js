/* Local mask-by-brush editor. No external image uploads or model downloads. */
(() => {
  'use strict';
  if (window.MLXRegionEditor) return;

  const ID = /^\d{10}-[a-f0-9]{12}$/i;
  const localText = (de, en) =>
    String(window.MLXI18n?.getLanguage?.() || document.documentElement.lang || 'de')
      .startsWith('de') ? de : en;
  const node = (tag, cls, value) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  };
  let active = null;

  function paintPath(ctx, points, size, color) {
    if (!points.length) return;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = size;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.arc(points[0][0], points[0][1], size / 2, 0, Math.PI * 2);
    ctx.fill();
    if (points.length > 1) {
      ctx.beginPath();
      ctx.moveTo(points[0][0], points[0][1]);
      for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
      ctx.stroke();
    }
  }

  function maskHasSelection(strokes) {
    // Erasing everything must not submit a full-image edit.
    return strokes.some(stroke => !stroke.erase);
  }

  async function open(source) {
    const id = String(source?.image_id || source?.id || '').trim();
    if (!ID.test(id)) throw new Error(localText('Ungültige Bild-ID', 'Invalid image ID'));
    if (active) active.close();
    const opener = document.activeElement;
    const overlay = node('div', 'nobby-region-editor');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', localText('Bereich bearbeiten', 'Edit selected region'));
    const frame = node('div', 'nobby-region-editor-frame');
    const header = node('header', 'nobby-region-editor-header');
    const heading = node('h2', '', localText('Bereich bearbeiten', 'Edit selected region'));
    const dismiss = node('button', 'message-action-btn', '×');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', localText('Schließen', 'Close'));
    header.append(heading, dismiss);
    const help = node('p', 'nobby-region-editor-help',
      localText('Male über den Bereich, den die KI verändern soll. Rot markiert die Auswahl.',
           'Brush over the area to change. Red indicates the selection.'));
    const imageWrap = node('div', 'nobby-region-editor-image');
    const image = node('img');
    image.alt = localText('Originalbild', 'Original image');
    const display = node('canvas', 'nobby-region-editor-overlay');
    display.setAttribute('aria-label', localText('Bereich mit Maus oder Touch markieren', 'Mark region with mouse or touch'));
    // Keep the image and its overlaid canvas in one zoomed pixel coordinate system.
    const imageStage = node('div', 'nobby-region-editor-stage');
    imageStage.append(image, display);
    imageWrap.append(imageStage);
    const toolbar = node('div', 'nobby-region-editor-toolbar');
    const sizeLabel = node('label', '');
    sizeLabel.textContent = localText('Pinselgröße', 'Brush size');
    const size = node('input');
    size.type = 'range';
    size.min = '4'; size.max = '128'; size.step = '2'; size.value = '32';
    try {
      const remembered = Number(window.localStorage?.getItem('nobby-region-brush-size'));
      if (remembered >= 4 && remembered <= 128 && Number.isInteger(remembered))
        size.value = String(remembered);
    } catch (_) { /* Private browsing or blocked storage: use the safe default. */ }
    size.addEventListener('input', () => {
      try { window.localStorage?.setItem('nobby-region-brush-size', size.value); }
      catch (_) { /* Brush size still works for this session. */ }
    });
    sizeLabel.append(size);
    const brush = node('button', 'message-action-btn is-active', localText('Pinsel', 'Brush'));
    const erase = node('button', 'message-action-btn', localText('Radierer', 'Eraser'));
    const undo = node('button', 'message-action-btn', localText('Rückgängig', 'Undo'));
    const clear = node('button', 'message-action-btn', localText('Zurücksetzen', 'Reset'));
    for (const b of [brush, erase, undo, clear]) b.type = 'button';
    toolbar.append(sizeLabel, brush, erase, undo, clear);

    const featherLabel = node('label', 'nobby-region-editor-slider-label');
    featherLabel.textContent = localText('Weiche Kante', 'Soft edge');
    const feather = node('input');
    feather.type = 'range'; feather.min = '0'; feather.max = '12';
    feather.step = '1'; feather.value = '3';
    const featherValue = node('output', 'nobby-region-editor-feather-value', '3 px');
    feather.addEventListener('input', () => {
      featherValue.textContent = feather.value + ' px';
    });
    featherLabel.append(feather, featherValue);
    toolbar.append(featherLabel);

    const zoomToolbar = node('div', 'nobby-region-editor-zoom');
    const zoomLabel = node('span', '', localText('Ansicht', 'View'));
    const zoomOut = node('button', 'message-action-btn', '−');
    const zoomFit = node('button', 'message-action-btn', localText('Einpassen', 'Fit'));
    const zoomIn = node('button', 'message-action-btn', '+');
    const zoomValue = node('output', 'nobby-region-editor-zoom-value', '100 %');
    for (const button of [zoomOut, zoomFit, zoomIn]) button.type = 'button';
    zoomOut.setAttribute('aria-label', localText('Verkleinern', 'Zoom out'));
    zoomIn.setAttribute('aria-label', localText('Vergrößern', 'Zoom in'));
    zoomToolbar.append(zoomLabel, zoomOut, zoomFit, zoomIn, zoomValue);

    const presetRow = node('div', 'nobby-region-editor-presets');
    const presetLabel = node('span', '', localText('Schnellvorlagen', 'Quick prompts'));
    presetRow.append(presetLabel);
    const presetValues = [
      [localText('Augenfarbe', 'Eye color'),
       'Change only the selected eye color to natural blue, preserving realistic reflections and everything else.'],
      [localText('Hautdetails', 'Skin details'),
       'Refine only the selected skin texture with natural pores and subtle realistic details. Preserve identity and lighting.'],
      [localText('Objekt entfernen', 'Remove object'),
       'Remove only the selected object and realistically reconstruct the background. Keep everything else unchanged.'],
      [localText('Kleidung ändern', 'Change clothing'),
       'Change only the selected clothing to dark blue fabric, maintaining realistic folds, pose and lighting.']
    ];
    const promptLabel = node('label', 'nobby-region-editor-prompt');
    promptLabel.textContent = localText('Was soll sich im markierten Bereich ändern?', 'What should change in the selected area?');
    const prompt = node('textarea');
    prompt.rows = 3; prompt.maxLength = 2000;
    prompt.placeholder = localText('z. B. natürlichere Augen und Hauttextur, alles andere beibehalten',
      'e.g. more realistic eyes and skin texture, preserve everything else');
    promptLabel.append(prompt);
    for (const [label, instruction] of presetValues) {
      const button = node('button', 'message-action-btn', label);
      button.type = 'button';
      button.addEventListener('click', () => {
        if (busy) return;
        prompt.value = instruction;
        update();
        prompt.focus();
      });
      presetRow.append(button);
    }
    const status = node('p', 'nobby-region-editor-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const buttons = node('div', 'nobby-region-editor-actions');
    const cancel = node('button', 'message-action-btn', localText('Abbrechen', 'Cancel'));
    const send = node('button', 'message-action-btn nobby-region-editor-submit', localText('Bereich überarbeiten', 'Edit selected region'));
    cancel.type = 'button'; send.type = 'button';
    send.disabled = true;
    buttons.append(cancel, send);
    frame.append(header, help, imageWrap, zoomToolbar, toolbar,
      presetRow, promptLabel, status, buttons);
    overlay.append(frame);
    document.body.append(overlay);

    let closed = false, busy = false, ready = false, eraseMode = false, drawing = null;
    let fitWidth = 1, fitHeight = 1, zoom = 1;
    const strokes = [];

    function setZoom(next) {
      if (!ready || busy) return;
      const value = Math.min(3, Math.max(1, next));
      const oldWidth = imageStage.getBoundingClientRect().width || fitWidth;
      const oldHeight = imageStage.getBoundingClientRect().height || fitHeight;
      const centerX = (imageWrap.scrollLeft + imageWrap.clientWidth / 2) / oldWidth;
      const centerY = (imageWrap.scrollTop + imageWrap.clientHeight / 2) / oldHeight;
      zoom = value;
      imageStage.style.width = Math.round(fitWidth * zoom) + 'px';
      imageStage.style.height = Math.round(fitHeight * zoom) + 'px';
      zoomValue.textContent = Math.round(zoom * 100) + ' %';
      zoomOut.disabled = zoom <= 1;
      zoomIn.disabled = zoom >= 3;
      requestAnimationFrame(() => {
        if (closed) return;
        imageWrap.scrollLeft = centerX * imageStage.clientWidth - imageWrap.clientWidth / 2;
        imageWrap.scrollTop = centerY * imageStage.clientHeight - imageWrap.clientHeight / 2;
      });
    }

    zoomOut.addEventListener('click', () => setZoom(zoom - 0.5));
    zoomIn.addEventListener('click', () => setZoom(zoom + 0.5));
    zoomFit.addEventListener('click', () => setZoom(1));
    const mask = document.createElement('canvas');
    const finish = () => {
      if (closed || busy) return;
      closed = true;
      overlay.remove();
      document.removeEventListener('keydown', onKey);
      if (opener?.isConnected) opener.focus();
      if (active?.overlay === overlay) active = null;
    };
    const onKey = event => {
      if (event.key === 'Escape' && !busy) { event.preventDefault(); finish(); return; }
      if (busy || !ready) return;
      const editing = event.target?.matches?.('input, textarea, select, [contenteditable="true"]');
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !editing) {
        event.preventDefault();
        if (strokes.length) { strokes.pop(); redraw(); }
        return;
      }
      if (editing || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key.toLowerCase() === 'b') { eraseMode = false; update(); }
      if (event.key.toLowerCase() === 'e') { eraseMode = true; update(); }
      if (event.key === '+' || event.key === '=') setZoom(zoom + 0.5);
      if (event.key === '-') setZoom(zoom - 0.5);
      if (event.key === '0') setZoom(1);
    };
    active = {overlay, close: finish};
    document.addEventListener('keydown', onKey);
    dismiss.addEventListener('click', finish);
    cancel.addEventListener('click', finish);
    overlay.addEventListener('click', event => { if (event.target === overlay) finish(); });
    function update() {
      send.disabled = !ready || busy || !maskHasSelection(strokes) || !prompt.value.trim();
      undo.disabled = !strokes.length || busy;
      clear.disabled = !strokes.length || busy;
      brush.classList.toggle('is-active', !eraseMode);
      erase.classList.toggle('is-active', eraseMode);
    }
    function redraw() {
      if (!ready) return;
      const ctx = mask.getContext('2d', {willReadFrequently: true});
      const overlayCtx = display.getContext('2d');
      ctx.clearRect(0, 0, mask.width, mask.height);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, mask.width, mask.height);
      overlayCtx.clearRect(0, 0, display.width, display.height);
      for (const stroke of strokes) {
        paintPath(ctx, stroke.points, stroke.size, stroke.erase ? '#000' : '#fff');
        if (stroke.erase) {
          overlayCtx.globalCompositeOperation = 'destination-out';
          paintPath(overlayCtx, stroke.points, stroke.size, '#000');
          overlayCtx.globalCompositeOperation = 'source-over';
        } else {
          paintPath(overlayCtx, stroke.points, stroke.size, 'rgba(255, 65, 65, .48)');
        }
      }
      update();
    }
    function coordinates(event) {
      const rect = display.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      return [
        Math.min(display.width, Math.max(0, (event.clientX - rect.left) * display.width / rect.width)),
        Math.min(display.height, Math.max(0, (event.clientY - rect.top) * display.height / rect.height))
      ];
    }
    display.addEventListener('pointerdown', event => {
      if (!ready || busy || (event.pointerType === 'mouse' && event.button !== 0)) return;
      const point = coordinates(event);
      if (!point) return;
      event.preventDefault();
      display.setPointerCapture?.(event.pointerId);
      drawing = {erase: eraseMode, size: Number(size.value), points: [point]};
      strokes.push(drawing);
      redraw();
    });
    display.addEventListener('pointermove', event => {
      if (!drawing || busy) return;
      const point = coordinates(event);
      if (!point) return;
      event.preventDefault();
      drawing.points.push(point);
      redraw();
    });
    const stopDrawing = () => { drawing = null; };
    display.addEventListener('pointerup', stopDrawing);
    display.addEventListener('pointercancel', stopDrawing);
    brush.addEventListener('click', () => { eraseMode = false; update(); });
    erase.addEventListener('click', () => { eraseMode = true; update(); });
    undo.addEventListener('click', () => { if (!busy) { strokes.pop(); redraw(); } });
    clear.addEventListener('click', () => { if (!busy) { strokes.length = 0; redraw(); } });
    prompt.addEventListener('input', update);
    image.addEventListener('load', () => {
      if (closed) return;
      if (image.naturalWidth < 64 || image.naturalHeight < 64 ||
          image.naturalWidth * image.naturalHeight > 16_000_000) {
        status.textContent = localText('Bildgröße nicht unterstützt', 'Unsupported image size');
        return;
      }
      mask.width = display.width = image.naturalWidth;
      mask.height = display.height = image.naturalHeight;
      const maxWidth = Math.max(200, imageWrap.clientWidth);
      const maxHeight = Math.max(200, Math.min(window.innerHeight * 0.55, 620));
      const scale = Math.min(1, maxWidth / image.naturalWidth, maxHeight / image.naturalHeight);
      fitWidth = Math.max(1, Math.round(image.naturalWidth * scale));
      fitHeight = Math.max(1, Math.round(image.naturalHeight * scale));
      imageStage.style.width = fitWidth + 'px';
      imageStage.style.height = fitHeight + 'px';
      ready = true;
      setZoom(1);
      redraw();
    }, {once: true});
    image.addEventListener('error', () => {
      status.textContent = localText('Originalbild nicht verfügbar', 'Source image unavailable');
    }, {once: true});
    image.src = '/api/mlx/images/' + encodeURIComponent(id);

    send.addEventListener('click', async () => {
      if (busy || !ready || !maskHasSelection(strokes) || !prompt.value.trim()) return;
      busy = true; update();
      status.textContent = localText('Maske wird übertragen …', 'Uploading mask …');
      try {
        const blob = await new Promise((resolve, reject) =>
          mask.toBlob(value => value ? resolve(value) : reject(new Error('PNG export failed')), 'image/png'));
        if (closed || !blob.size || blob.size > 16 * 1024 * 1024)
          throw new Error(localText('Maske konnte nicht gespeichert werden', 'Mask could not be saved'));
        const file = new File([blob], 'nobby-region-mask.png', {type: 'image/png'});
        const result = await window.MLXChatAttachments?.uploadImageAttachments?.([
          {file, name: file.name, kind: 'image'}
        ]);
        const path = result?.[0]?.upload?.path;
        if (!path) throw new Error(localText('Masken-Upload fehlgeschlagen', 'Mask upload failed'));
        status.textContent = localText('KI-Bearbeitung wird gestartet …', 'Starting local image edit …');
        const accepted = await window.MLXChatGeneration?.startRegionImageEdit?.({
          image_id: id,
          artifact_id: 'image-' + id,
          mask_path: path,
          region_feather_px: Number(feather.value),
          prompt: prompt.value.trim()
        });
        if (!accepted) throw new Error(localText('Bearbeitung konnte nicht gestartet werden', 'Edit could not be started'));
        busy = false; finish();
      } catch (error) {
        busy = false;
        status.textContent = String(error?.message || error);
        update();
      }
    });
    update();
    requestAnimationFrame(() => prompt.focus());
  }

  window.MLXRegionEditor = {open, maskHasSelection, paintPath};
})();
