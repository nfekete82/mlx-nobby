(() => {
  'use strict';

  const messages = {
    de: {
      header: 'Lokaler Bildkonverter',
      heading: 'Bilder konvertieren & komprimieren',
      intro: 'Bis zu 40 Bilder gleichzeitig. Keine KI, kein Cloud-Upload. Originaldateien bleiben unverändert.',
      drop: 'Bilder hier ablegen oder auswählen',
      format: 'Zielformat',
      png: 'PNG (verlustfrei)',
      quality: 'Qualität',
      maxEdge: 'Maximale Kantenlänge',
      original: 'Originalauflösung',
      alpha: 'Transparenz bei JPG',
      submit: 'Konvertieren und ZIP herunterladen',
      footer: 'Das ZIP enthält conversion-report.json mit Dateigrößen und eventuellen Fehlern einzelner Bilder.',
      none: 'Noch keine Dateien ausgewählt',
      files: ' Dateien, ',
      working: 'Bilder werden lokal konvertiert…',
      done: ' Bild(er) fertig.',
      error: 'Fehler: ',
      heic: 'Hinweis: HEIC ist auf diesem Server noch nicht verfügbar.',
      several: 'Mehrere',
    },
    en: {
      header: 'Local image converter',
      heading: 'Convert and compress images',
      intro: 'Up to 40 images at once. No AI, no cloud upload. Originals remain unchanged.',
      drop: 'Drop images here or choose files',
      format: 'Output format',
      png: 'PNG (lossless)',
      quality: 'Quality',
      maxEdge: 'Maximum edge length',
      original: 'Original resolution',
      alpha: 'Transparency for JPG',
      submit: 'Convert and download ZIP',
      footer: 'The ZIP includes conversion-report.json with image sizes and any per-file errors.',
      none: 'No files selected',
      files: ' files, ',
      working: 'Converting images locally…',
      done: ' image(s) converted.',
      error: 'Error: ',
      heic: 'HEIC support is not available on this server.',
      several: 'Several',
    }
  };

  const form = document.getElementById('converterForm');
  const input = document.getElementById('imageFiles');
  const status = document.getElementById('status');
  const selected = document.getElementById('selection');
  const button = document.getElementById('submit');
  const quality = document.getElementById('quality');
  const drop = document.getElementById('dropzone');

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

  let language = initialLanguage();
  let statusKey = '';
  let statusParams = {};
  const t = key => messages[language][key] || key;

  function updateSelected() {
    if (!input.files.length) {
      selected.textContent = t('none');
      return;
    }
    const total = Array.from(input.files).reduce((sum, file) => sum + file.size, 0);
    selected.textContent = input.files.length + t('files') + (total / 1048576).toFixed(1) + ' MB';
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
    else if (statusKey === 'error') status.textContent = t('error') + (statusParams.detail || '');
    else status.textContent = '';
  }

  function setLanguage(nextLanguage) {
    if (nextLanguage !== 'de' && nextLanguage !== 'en') return;
    language = nextLanguage;
    document.documentElement.lang = language;
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

  setLanguage(language);
  quality.addEventListener('input', () => {
    document.getElementById('qualityText').textContent = quality.value + ' %';
  });
  input.addEventListener('change', updateSelected);

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
