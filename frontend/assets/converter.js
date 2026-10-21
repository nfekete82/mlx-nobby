(() => {
  'use strict';

  const byId = id => document.getElementById(id);

  const german = (() => {
    try { return localStorage.getItem('mlx-nobby-language') === 'de'; }
    catch (_) { return false; }
  })();
  const localText = (de, en) => german ? de : en;
  const staticCopy = [
    ['.back', localText('← Zurück zum Chat', '← Back to chat')],
    ['.eyebrow', localText('WERKZEUGE / LOKAL', 'TOOLS / LOCAL')],
    ['h1', localText('Bild- & Dateikonverter', 'Image & file converter')],
    ['.sub', localText('Viele Bilder auf einmal optimieren oder umwandeln – lokal auf deinem Mac, ohne KI-Modell.',
                'Optimize or convert batches of images locally on your Mac, without loading an AI model.')],
    ['#uploadTitle', localText('Dateien', 'Files')],
    ['.drop-zone strong', localText('Bilder hier hineinziehen', 'Drag images here')],
    ['.drop-zone span', localText('oder klicken, um mehrere Dateien auszuwählen', 'or click to select multiple files')],
    ['.drop-zone small', localText('PNG · JPG · HEIC · HEIF · WebP · TIFF · BMP',
                           'PNG · JPG · HEIC · HEIF · WebP · TIFF · BMP')],
    ['label[for="folderPicker"]', localText('Ordner wählen', 'Choose folder')],
    ['#clearFiles', localText('Auswahl leeren', 'Clear selection')],
    ['#optionsTitle', localText('Einstellungen', 'Settings')],
    ['label[for="target"]', localText('Ausgabeformat', 'Output format')],
    ['#target option[value="webp"]', localText('WebP · gut fürs Web', 'WebP · great for web')],
    ['#target option[value="jpg"]', localText('JPG · universell', 'JPG · universal')],
    ['#target option[value="png"]', localText('PNG · verlustfrei', 'PNG · lossless')],
    ['#target option[value="avif"]', localText('AVIF · hohe Kompression', 'AVIF · efficient')],
    ['label[for="quality"]', localText('Qualität', 'Quality')],
    ['label[for="maxDimension"]', localText('Maximale Bildkante', 'Maximum image dimension')],
    ['#maxDimension option[value="0"]', localText('Originalauflösung', 'Original resolution')],
    ['label[for="background"]', localText('Hintergrundfarbe für JPG-Transparenz', 'Background for transparent JPGs')],
    ['.color-option span', localText('Standard: Weiß', 'Default: white')],
    ['.check', localText(' EXIF- und Farbprofil-Metadaten entfernen', ' Remove EXIF and color-profile metadata')],
    ['#startButton', localText('Jetzt konvertieren', 'Convert now')],
    ['#progressTitle', localText('Verarbeitung', 'Processing')],
    ['#cancelButton', localText('Abbrechen', 'Cancel')],
    ['#downloadAll', localText('↓ Alle Ergebnisse als ZIP laden', '↓ Download all as ZIP')],
    ['#resultHint', localText('Dateien werden temporär gespeichert und nach Ablauf entfernt.',
                      'Files are stored temporarily and removed after expiry.')],
    ['.footer-note', localText('Alle Berechnungen erfolgen auf deinem lokalen MLX-Nobby-Webserver. Die Originaldateien werden nicht verändert. Keine GPU und kein Agent erforderlich.',
                       'All processing runs on your local MLX Nobby web server. Original files are unchanged. No GPU or AI Agent is required.')],
  ];
  staticCopy.forEach(([selector, label]) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = label;
  });
  const metadataCheckbox = byId('stripMetadata');
  byId('stripMetadata').setAttribute('aria-label', localText('Metadaten entfernen', 'Remove metadata'));
  const limitNote = document.querySelector('.options-panel > .hint:last-child');
  if (limitNote) limitNote.textContent = localText(
    'Max. 100 Bilder · 25 MB pro Bild · 220 MB je Auftrag. Animierte Bilder werden als Fehler angezeigt.',
    'Up to 100 images · 25 MB each · 220 MB per batch. Animated images are reported as errors.'
  );

  const files = [];
  const knownExtensions = new Set(['png','jpg','jpeg','heic','heif','webp','tif','tiff','bmp']);
  const maxFiles = 100;
  const maxFileBytes = 25 * 1024 * 1024;
  const maxBatchBytes = 220 * 1024 * 1024;
  let activeJob = null;
  let pollTimer = null;
  let uploading = null;
  let busy = false;

  const size = n => n >= 1048576 ? (n / 1048576).toFixed(2) + ' MB' : (n / 1024).toFixed(1) + ' KB';
  const extension = name => String(name).split('.').pop().toLowerCase();
  const status = text => { byId('progressText').textContent = text; };
  const setProgress = percent => { byId('progressBar').style.width = Math.max(0, Math.min(100, percent)) + '%'; };
  const showError = message => {
    byId('progressPanel').hidden = false;
    status(message);
  };
  const toggleBusy = value => {
    busy = value;
    byId('startButton').disabled = busy || !files.length;
    for (const id of ['target','quality','maxDimension','background','stripMetadata','clearFiles']) {
      byId(id).disabled = busy;
    }
  };
  const clearTimer = () => { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; };

  function renderFiles() {
    byId('fileSummary').textContent = files.length
      ? files.length + localText(' Dateien · ', ' files · ') + size(files.reduce((sum, item) => sum + item.size, 0))
      : localText('Noch keine Dateien ausgewählt', 'No files selected');
    const host = byId('selectedFiles');
    host.replaceChildren();
    files.forEach((file, i) => {
      const row = document.createElement('div');
      row.className = 'file-row';
      const icon = document.createElement('span');
      icon.className = 'file-icon';
      icon.textContent = extension(file.name).toUpperCase().slice(0, 5);
      const info = document.createElement('div');
      info.className = 'file-info';
      const name = document.createElement('div');
      name.className = 'file-name';
      name.textContent = file.name;
      const meta = document.createElement('div');
      meta.className = 'file-details';
      meta.textContent = size(file.size);
      info.append(name, meta);
      const remove = document.createElement('button');
      remove.className = 'remove-file';
      remove.type = 'button';
      remove.textContent = '×';
      remove.title = localText('Datei entfernen', 'Remove file');
      remove.setAttribute('aria-label', localText('Datei ', 'Remove file ') + file.name + localText(' entfernen', ''));
      remove.disabled = busy;
      remove.addEventListener('click', () => {
        if (!busy) { files.splice(i, 1); renderFiles(); }
      });
      row.append(icon, info, remove);
      host.append(row);
    });
    byId('startButton').disabled = busy || !files.length;
  }

  function addFiles(incoming) {
    if (busy) return;
    const rejected = [];
    let batchSize = files.reduce((sum, f) => sum + f.size, 0);
    for (const file of Array.from(incoming || [])) {
      const ext = extension(file.name);
      if (!knownExtensions.has(ext)) { rejected.push(file.name + ' (Format)'); continue; }
      if (!file.size || file.size > maxFileBytes) { rejected.push(file.name + ' (0 oder >25 MB)'); continue; }
      if (files.length >= maxFiles || batchSize + file.size > maxBatchBytes) {
        rejected.push(file.name + ' (Limit)'); continue;
      }
      files.push(file);
      batchSize += file.size;
    }
    renderFiles();
    if (rejected.length) showError(localText('Nicht aufgenommen: ', 'Skipped: ') + rejected.slice(0, 5).join(', ') + (rejected.length > 5 ? ' …' : ''));
  }

  const drop = byId('dropZone');
  drop.addEventListener('click', () => { if (!busy) byId('filePicker').click(); });
  drop.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && !busy) { e.preventDefault(); byId('filePicker').click(); }
  });
  for (const eventName of ['dragenter','dragover']) {
    drop.addEventListener(eventName, e => { e.preventDefault(); if (!busy) drop.classList.add('dragging'); });
  }
  drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('dragging');
    addFiles(e.dataTransfer?.files);
  });
  byId('filePicker').addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });
  byId('folderPicker').addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });
  byId('clearFiles').addEventListener('click', () => { if (!busy) { files.length = 0; renderFiles(); } });

  const quality = byId('quality');
  const format = byId('target');
  const syncQuality = () => {
    byId('qualityValue').textContent = quality.value + ' %';
    const lossless = format.value === 'png';
    quality.disabled = lossless || busy;
    byId('qualityHint').textContent = lossless
      ? localText('PNG verwendet eine verlustfreie Optimierung; der Qualitätsregler hat hier keine Wirkung.', 'PNG is optimized losslessly; quality does not apply.')
      : localText('Niedrigerer Wert = kleinere Datei, weniger Bilddetails.', 'Lower quality means smaller files with less detail.');
  };
  quality.addEventListener('input', syncQuality);
  format.addEventListener('change', syncQuality);
  syncQuality();

  function makeResult(item, index, jobId) {
    const row = document.createElement('div');
    row.className = 'result-row';
    const info = document.createElement('div');
    info.className = 'file-info';
    const name = document.createElement('strong');
    name.textContent = item.output || item.source;
    const meta = document.createElement('div');
    meta.className = 'result-meta';
    if (item.status === 'complete') {
      meta.textContent = size(item.bytes_before) + ' → ' + size(item.bytes_after)
        + ' · ' + item.saved_percent + ' % · ' + item.width + ' × ' + item.height;
      meta.className += ' ok';
    } else {
      meta.textContent = item.error || localText('Konvertierung fehlgeschlagen', 'Conversion failed');
      meta.className += ' failed';
    }
    info.append(name, meta);
    row.append(info);
    if (item.status === 'complete') {
      const link = document.createElement('a');
      link.href = '/api/converter/jobs/' + jobId + '/files/' + index;
      link.download = item.output;
      link.textContent = '↓ Einzeldatei';
      row.append(link);
    }
    return row;
  }

  function renderJob(job) {
    const total = Math.max(1, job.total || files.length);
    setProgress(100 * (job.processed || 0) / total);
    const host = byId('results');
    host.replaceChildren();
    (job.files || []).forEach((item, index) => host.append(makeResult(item, index, job.id)));
    const done = ['complete','failed','cancelled'].includes(job.status);
    if (job.status === 'complete') {
      status(localText('Fertig: ', 'Done: ') + (job.files || []).filter(x => x.status === 'complete').length + localText(' von ', ' of ') + total + localText(' Dateien konvertiert.', ' files converted.'));
      setProgress(100);
    } else if (job.status === 'failed') {
      status(job.error || localText('Keine Bilder konnten konvertiert werden.', 'No images could be converted.'));
    } else if (job.status === 'cancelled') {
      status(localText('Konvertierung abgebrochen.', 'Conversion cancelled.'));
    } else {
      status((job.status === 'queued' ? localText('Warteschlange', 'Queued') : localText('Konvertiere Bilder', 'Converting images')) +
        ': ' + (job.processed || 0) + ' / ' + total);
    }
    byId('downloadAll').hidden = job.status !== 'complete';
    if (job.status === 'complete') {
      byId('downloadAll').href = '/api/converter/jobs/' + job.id + '/download';
    }
    byId('cancelButton').hidden = done;
    if (done) {
      activeJob = null;
      toggleBusy(false);
      syncQuality();
    }
    return done;
  }

  async function poll(jobId) {
    try {
      const response = await fetch('/api/converter/jobs/' + jobId, {cache: 'no-store'});
      if (!response.ok) throw new Error('Status HTTP ' + response.status);
      const job = await response.json();
      if (renderJob(job)) return;
      pollTimer = setTimeout(() => poll(jobId), 500);
    } catch (error) {
      showError(localText('Status konnte nicht geladen werden: ', 'Could not load job status: ') + error.message);
      toggleBusy(false);
    }
  }

  byId('cancelButton').addEventListener('click', async () => {
    if (uploading) { uploading.abort(); return; }
    if (!activeJob) return;
    try {
      const response = await fetch('/api/converter/jobs/' + activeJob + '/cancel', {method:'POST'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      status(localText('Abbruch angefordert – laufendes Bild wird noch abgeschlossen.', 'Cancellation requested; current image is finishing.'));
    } catch (error) { showError(localText('Abbruch fehlgeschlagen: ', 'Cancellation failed: ') + error.message); }
  });

  byId('startButton').addEventListener('click', async () => {
    if (!files.length || busy) return;
    clearTimer();
    toggleBusy(true);
    byId('progressPanel').hidden = false;
    byId('results').replaceChildren();
    byId('downloadAll').hidden = true;
    byId('cancelButton').hidden = false;
    setProgress(0);
    status(localText('Dateien werden hochgeladen …', 'Uploading files…'));
    const body = new FormData();
    files.forEach(file => body.append('files', file, file.name));
    body.append('target', format.value);
    body.append('quality', quality.value);
    body.append('max_dimension', byId('maxDimension').value);
    body.append('background', byId('background').value);
    body.append('strip_metadata', String(byId('stripMetadata').checked));
    const request = new XMLHttpRequest();
    uploading = request;
    request.open('POST', '/api/converter/jobs');
    request.upload.addEventListener('progress', e => {
      if (e.lengthComputable) {
        status(localText('Upload: ', 'Upload: ') + Math.round(e.loaded / e.total * 100) + ' %');
      }
    });
    request.onload = () => {
      uploading = null;
      let data = {};
      try { data = JSON.parse(request.responseText || '{}'); } catch (_) { /* handled below */ }
      if (request.status !== 202 || !/^[0-9a-f]{32}$/.test(data.id || '')) {
        showError(localText('Upload fehlgeschlagen: ', 'Upload failed: ') + (typeof data.detail === 'string' ? data.detail : 'HTTP ' + request.status));
        toggleBusy(false); syncQuality(); return;
      }
      activeJob = data.id;
      poll(activeJob);
    };
    request.onerror = () => {
      uploading = null; showError(localText('Netzwerkfehler beim Upload.', 'Network error during upload.')); toggleBusy(false); syncQuality();
    };
    request.onabort = () => {
      uploading = null; status(localText('Upload abgebrochen.', 'Upload cancelled.')); toggleBusy(false); syncQuality();
      byId('cancelButton').hidden = true;
    };
    request.send(body);
  });

  fetch('/api/converter/capabilities', {cache:'no-store'}).then(r => r.ok ? r.json() : null)
    .then(info => {
      if (info && !info.heic) {
        const small = document.createElement('p');
        small.className = 'hint';
        small.textContent = localText('Hinweis: HEIC ist auf diesem Server derzeit nicht verfügbar.', 'Notice: HEIC is not available on this server.');
        drop.after(small);
      }
    }).catch(() => {});
  renderFiles();
})();
