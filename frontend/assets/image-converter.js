(() => {
  'use strict';

  // Keep translations in the same JSON-driven i18n system as the other studios.
  let messages = {};
  const fallbackEnglish = {
    none: 'No files selected',
    files: ' files, ',
    working: 'Converting images locally…',
    done: ' image(s) converted.',
    error: 'Error: ',
    heic: 'HEIC support is not available on this server.',
    several: 'Several'
  };

  const form = document.getElementById('converterForm');
  const input = document.getElementById('imageFiles');
  const status = document.getElementById('status');
  const selected = document.getElementById('selection');
  const button = document.getElementById('submit');
  const quality = document.getElementById('quality');
  const drop = document.getElementById('dropzone');
  const dropEmpty = document.getElementById('dropzoneEmpty');
  const dropFiles = document.getElementById('dropzoneFiles');
  const previewUrls = [];
  const PREVIEW_LIMIT = 3;

  function initialLanguage() {
    const query = new URLSearchParams(location.search).get('lang');
    if (query === 'de' || query === 'en') return query;
    try {
      const stored = localStorage.getItem('mlx-nobby-language');
      return stored === 'de' ? 'de' : 'en';
    } catch (_) {
      return 'en';
    }
  }

  const localizedError = detail => language === 'en'
    ? messages.errors_en?.[detail] || detail
    : detail;

  let language = initialLanguage();
  let statusKey = '';
  let statusParams = {};
  const t = key => messages[language]?.[key] || messages.en?.[key] || fallbackEnglish[key] || key;

  function readableSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    const unit = bytes < 1048576 ? 'KB' : 'MB';
    const amount = bytes / (unit === 'KB' ? 1024 : 1048576);
    const digits = unit === 'KB' ? 0 : 1;
    return new Intl.NumberFormat(language === 'de' ? 'de-DE' : 'en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }).format(amount) + ' ' + unit;
  }

  function clearPreviewUrls() {
    previewUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
  }

  function renderDropzoneFiles() {
    clearPreviewUrls();
    dropFiles.replaceChildren();
    const files = Array.from(input.files || []);
    const hasFiles = files.length > 0;
    drop.classList.toggle('has-files', hasFiles);
    dropFiles.hidden = !hasFiles;
    dropEmpty.hidden = hasFiles;
    if (!hasFiles) return;

    // Keep the dropzone compact even for large batches, with no extra scrollbar.
    for (const file of files.slice(0, PREVIEW_LIMIT)) {
      const row = document.createElement('span');
      row.className = 'dropzone-file';

      const thumb = document.createElement('span');
      thumb.className = 'dropzone-thumb';
      const fallback = document.createElement('span');
      fallback.className = 'dropzone-thumb-fallback';
      fallback.textContent = 'IMG';
      thumb.appendChild(fallback);

      // Browser-native previews; unsupported HEIC/TIFF still show the filename.
      if (/\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name)) {
        const image = document.createElement('img');
        image.alt = '';
        image.className = 'dropzone-thumb-image';
        const url = URL.createObjectURL(file);
        previewUrls.push(url);
        image.src = url;
        image.addEventListener('load', () => { fallback.hidden = true; }, {once: true});
        image.addEventListener('error', () => { image.hidden = true; }, {once: true});
        thumb.appendChild(image);
      }

      const details = document.createElement('span');
      details.className = 'dropzone-file-details';
      const name = document.createElement('span');
      name.className = 'dropzone-file-name';
      name.textContent = file.name; // Untrusted names are never injected as HTML.
      name.title = file.name;
      const size = document.createElement('span');
      size.className = 'dropzone-file-size';
      size.textContent = readableSize(file.size);
      details.append(name, size);
      row.append(thumb, details);
      dropFiles.appendChild(row);
    }
    if (files.length > PREVIEW_LIMIT) {
      const more = document.createElement('span');
      more.className = 'dropzone-more';
      more.textContent = '+' + (files.length - PREVIEW_LIMIT) + ' ' + t('more');
      dropFiles.appendChild(more);
    }
  }

  function updateSelected() {
    const count = input.files.length;
    if (!count) {
      selected.textContent = t('none');
    } else {
      const total = Array.from(input.files).reduce((sum, file) => sum + file.size, 0);
      selected.textContent = count + t(count === 1 ? 'file' : 'files') + readableSize(total);
    }
    renderDropzoneFiles();
  }

  function setStatus(key, params = {}) {
    statusKey = key;
    statusParams = params;
    renderStatus();
  }

  function renderStatus() {
    if (statusKey === 'working') status.textContent = t('working');
    else if (statusKey === 'done') status.textContent =
      (statusParams.count || t('several')) + t('done');
    else if (statusKey === 'heic') status.textContent = t('heic');
    else if (statusKey === 'error') status.textContent = t('error') + localizedError(statusParams.detail || '');
    else status.textContent = '';
  }

  function setLanguage(nextLanguage) {
    if (nextLanguage !== 'de' && nextLanguage !== 'en') return;
    language = nextLanguage;
    document.documentElement.lang = language;
    if (!messages[language]) return;
    document.title = t('heading') + ' · MLX Nobby';
    document.querySelectorAll('[data-converter-i18n]').forEach(node => {
      node.textContent = t(node.dataset.converterI18n);
    });
    updateSelected();
    renderStatus();
  }

  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (event.data?.type === 'mlx-image-converter-language') setLanguage(event.data.language);
  });

  document.documentElement.lang = language;
  fetch('/i18n/image-converter.json', {cache: 'no-cache'})
    .then(response => {
      if (!response.ok) throw new Error('Could not load converter translations');
      return response.json();
    })
    .then(translations => {
      if (!translations?.en || !translations?.de) {
        throw new Error('Converter language dictionaries are incomplete');
      }
      messages = translations;
      setLanguage(language);
    })
    .catch(error => {
      console.error('[image converter i18n]', error);
      setLanguage('en');
    });

  quality.addEventListener('input', () => {
    document.getElementById('qualityText').textContent = quality.value + ' %';
  });
  input.addEventListener('change', updateSelected);
  window.addEventListener('pagehide', clearPreviewUrls);

  ['dragover', 'dragenter'].forEach(name => drop.addEventListener(name, event => {
    event.preventDefault();
    drop.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(name => drop.addEventListener(name, event => {
    event.preventDefault();
    drop.classList.remove('over');
  }));
  drop.addEventListener('drop', event => {
    if (!event.dataTransfer?.files?.length) return;
    input.files = event.dataTransfer.files;
    input.dispatchEvent(new Event('change'));
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!input.files.length) return;
    const data = new FormData(form);
    button.disabled = true;
    setStatus('working');
    try {
      const response = await fetch('/api/image-converter/batch', {method: 'POST', body: data});
      if (!response.ok) {
        let detail = 'HTTP ' + response.status;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'mlx-nobby-converted.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setStatus('done', {count: response.headers.get('X-Converted-Count')});
    } catch (error) {
      setStatus('error', {detail: error.message});
    } finally {
      button.disabled = false;
    }
  });

  fetch('/api/image-converter/formats').then(r => r.json()).then(data => {
    if (!data.heic_available) setStatus('heic');
  }).catch(() => {});

  // Expose a minimal read-only test hook without altering the conversion API.
  window.MLXImageConverterLocale = Object.freeze({getLanguage: () => language});
})();
