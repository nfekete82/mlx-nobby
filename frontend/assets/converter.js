(() => {
  'use strict';

  const byId = id => document.getElementById(id);
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
      ? files.length + ' Dateien · ' + size(files.reduce((sum, item) => sum + item.size, 0))
      : 'Noch keine Dateien ausgewählt';
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
      remove.title = 'Datei entfernen';
      remove.setAttribute('aria-label', 'Datei ' + file.name + ' entfernen');
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
    if (rejected.length) showError('Nicht aufgenommen: ' + rejected.slice(0, 5).join(', ') + (rejected.length > 5 ? ' …' : ''));
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
      ? 'PNG verwendet eine verlustfreie Optimierung; der Qualitätsregler hat hier keine Wirkung.'
      : 'Niedrigerer Wert = kleinere Datei, weniger Bilddetails.';
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
      meta.textContent = item.error || 'Konvertierung fehlgeschlagen';
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
      status('Fertig: ' + (job.files || []).filter(x => x.status === 'complete').length + ' von ' + total + ' Dateien konvertiert.');
      setProgress(100);
    } else if (job.status === 'failed') {
      status(job.error || 'Keine Bilder konnten konvertiert werden.');
    } else if (job.status === 'cancelled') {
      status('Konvertierung abgebrochen.');
    } else {
      status((job.status === 'queued' ? 'Warteschlange' : 'Konvertiere Bilder') +
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
      showError('Status konnte nicht geladen werden: ' + error.message);
      toggleBusy(false);
    }
  }

  byId('cancelButton').addEventListener('click', async () => {
    if (uploading) { uploading.abort(); return; }
    if (!activeJob) return;
    try {
      const response = await fetch('/api/converter/jobs/' + activeJob + '/cancel', {method:'POST'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      status('Abbruch angefordert – laufendes Bild wird noch abgeschlossen.');
    } catch (error) { showError('Abbruch fehlgeschlagen: ' + error.message); }
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
    status('Dateien werden hochgeladen …');
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
        status('Upload: ' + Math.round(e.loaded / e.total * 100) + ' %');
      }
    });
    request.onload = () => {
      uploading = null;
      let data = {};
      try { data = JSON.parse(request.responseText || '{}'); } catch (_) { /* handled below */ }
      if (request.status !== 202 || !/^[0-9a-f]{32}$/.test(data.id || '')) {
        showError('Upload fehlgeschlagen: ' + (typeof data.detail === 'string' ? data.detail : 'HTTP ' + request.status));
        toggleBusy(false); syncQuality(); return;
      }
      activeJob = data.id;
      poll(activeJob);
    };
    request.onerror = () => {
      uploading = null; showError('Netzwerkfehler beim Upload.'); toggleBusy(false); syncQuality();
    };
    request.onabort = () => {
      uploading = null; status('Upload abgebrochen.'); toggleBusy(false); syncQuality();
      byId('cancelButton').hidden = true;
    };
    request.send(body);
  });

  fetch('/api/converter/capabilities', {cache:'no-store'}).then(r => r.ok ? r.json() : null)
    .then(info => {
      if (info && !info.heic) {
        const small = document.createElement('p');
        small.className = 'hint';
        small.textContent = 'Hinweis: HEIC ist auf diesem Server derzeit nicht verfügbar.';
        drop.after(small);
      }
    }).catch(() => {});
  renderFiles();
})();
