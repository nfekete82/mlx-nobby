(function () {
    'use strict';

    const FALLBACK = {
        title: 'Model Scout',
        subtitle: 'Find recent MLX models and check whether they fit this Mac before adding them.',
        scan: 'Search for new models',
        scanning: 'Searching Hugging Face…',
        refresh: 'Search again',
        role_all: 'All',
        role_chat: 'Chat',
        role_coding: 'Coding',
        role_vision: 'Vision',
        system: 'System',
        source: 'Source',
        found: '{count} candidates found',
        no_results: 'No matching candidates found.',
        unavailable: 'Model Scout is currently unavailable.',
        candidate: 'Upgrade candidate',
        interesting: 'Interesting',
        installed: 'Installed',
        not_recommended: 'Tight for this system',
        memory: 'Estimated memory',
        unknown: 'unknown',
        params: 'Parameters',
        quant: 'Quantization',
        license: 'License',
        updated: 'Updated',
        downloads: 'Downloads',
        likes: 'Likes',
        details: 'Hugging Face',
        add_test: 'Add for testing',
        adding: 'Adding…',
        added: 'Added to model manager',
        add_failed: 'Could not add model',
        fit_excellent: 'Excellent fit',
        fit_good: 'Good fit',
        fit_tight: 'Tight',
        fit_risky: 'Risky',
        fit_unknown: 'Fit unknown',
        score_hint: 'Discovery score combines freshness, popularity and system fit. It is not a quality benchmark.',
        phase_hint: 'After adding a candidate, use the existing model manager to download and activate it for a real local test.',
        last_scan: 'Last scan: {time}'
    };

    let copy = { ...FALLBACK };
    let mounted = false;
    let lastData = null;

    function text(key, vars = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => {
            value = value.replaceAll('{' + name + '}', String(replacement));
        });
        return value;
    }

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    async function loadCopy() {
        try {
            const response = await fetch('/i18n/model-scout.' + locale() + '.json', { cache: 'no-store' });
            if (!response.ok) return;
            const data = await response.json();
            if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
        } catch (_) {}
    }

    function injectStyles() {
        if (document.getElementById('modelScoutStyles')) return;
        const style = document.createElement('style');
        style.id = 'modelScoutStyles';
        style.textContent = `
            .model-scout { margin: 0 0 16px; padding: 15px; border: 1px solid #293244; border-radius: 13px; background: linear-gradient(145deg, rgba(18,24,35,.92), rgba(10,14,21,.9)); }
            .model-scout-head { display:flex; gap:14px; align-items:flex-start; justify-content:space-between; }
            .model-scout-title { margin:0; font-size:15px; font-weight:750; }
            .model-scout-subtitle { margin:5px 0 0; color:var(--muted); font-size:11px; line-height:1.45; max-width:680px; }
            .model-scout-controls { display:flex; flex-wrap:wrap; gap:7px; align-items:center; margin-top:12px; }
            .model-scout-button,.model-scout-select { min-height:34px; border:1px solid #30394a; border-radius:9px; background:#151b26; color:var(--text); font:inherit; font-size:11px; }
            .model-scout-button { padding:0 11px; cursor:pointer; font-weight:650; }
            .model-scout-button.primary { background:#326fda; border-color:#4f8cff; color:white; }
            .model-scout-button:disabled { opacity:.55; cursor:default; }
            .model-scout-select { padding:0 28px 0 9px; }
            .model-scout-meta { margin-left:auto; color:var(--muted); font-size:10px; }
            .model-scout-status { margin-top:10px; color:#9da9b9; font-size:11px; }
            .model-scout-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:9px; margin-top:12px; }
            .model-scout-card { min-width:0; padding:12px; border:1px solid #283244; border-radius:11px; background:rgba(10,14,20,.55); }
            .model-scout-card[data-status="candidate"] { border-color:rgba(64,214,154,.38); }
            .model-scout-card[data-status="not_recommended"] { border-color:rgba(240,185,103,.38); }
            .model-scout-card-top { display:flex; align-items:flex-start; gap:8px; justify-content:space-between; }
            .model-scout-name { min-width:0; font-size:12px; font-weight:700; overflow-wrap:anywhere; }
            .model-scout-badge { flex:0 0 auto; padding:3px 6px; border-radius:999px; background:#1a2230; color:#aab5c4; font-size:9px; font-weight:700; }
            .model-scout-card[data-status="candidate"] .model-scout-badge { background:rgba(35,126,91,.18); color:#77ddb7; }
            .model-scout-card[data-status="installed"] .model-scout-badge { background:rgba(47,111,234,.17); color:#91b5ff; }
            .model-scout-specs { display:flex; flex-wrap:wrap; gap:5px; margin-top:9px; }
            .model-scout-chip { padding:3px 6px; border:1px solid #293344; border-radius:7px; color:#9ca8b8; font-size:9px; }
            .model-scout-stats { display:grid; grid-template-columns:1fr 1fr; gap:5px 10px; margin-top:10px; color:#8793a4; font-size:10px; }
            .model-scout-stats strong { color:#c7d0dc; font-weight:600; }
            .model-scout-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:11px; }
            .model-scout-actions a { text-decoration:none; display:inline-flex; align-items:center; }
            .model-scout-note { margin-top:10px; color:#6f7b8c; font-size:10px; line-height:1.45; }
            @media(max-width:720px){.model-scout-head{display:block}.model-scout-meta{margin-left:0}.model-scout-grid{grid-template-columns:1fr}}
        `;
        document.head.appendChild(style);
    }

    function formatNumber(value) {
        return new Intl.NumberFormat(locale() === 'de' ? 'de-DE' : 'en-US', { notation: value >= 100000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value || 0);
    }

    function formatDate(value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', { dateStyle: 'medium' }).format(date);
    }

    function statusLabel(status) {
        return text({ candidate: 'candidate', interesting: 'interesting', installed: 'installed', not_recommended: 'not_recommended' }[status] || 'interesting');
    }

    function fitLabel(fit) {
        return text({ excellent: 'fit_excellent', good: 'fit_good', tight: 'fit_tight', risky: 'fit_risky', unknown: 'fit_unknown' }[fit] || 'fit_unknown');
    }

    function createPanel(content) {
        let panel = content.querySelector(':scope > .model-scout');
        if (panel) return panel;

        panel = document.createElement('section');
        panel.className = 'model-scout';
        panel.innerHTML = `
            <div class="model-scout-head">
                <div><h4 class="model-scout-title"></h4><p class="model-scout-subtitle"></p></div>
                <div class="model-scout-meta"></div>
            </div>
            <div class="model-scout-controls">
                <button type="button" class="model-scout-button primary" data-scout-scan></button>
                <select class="model-scout-select" data-scout-role>
                    <option value="all"></option><option value="chat"></option><option value="coding"></option><option value="vision"></option>
                </select>
            </div>
            <div class="model-scout-status" data-scout-status></div>
            <div class="model-scout-grid" data-scout-grid></div>
            <div class="model-scout-note" data-scout-note></div>
        `;
        content.prepend(panel);
        panel.querySelector('.model-scout-title').textContent = text('title');
        panel.querySelector('.model-scout-subtitle').textContent = text('subtitle');
        panel.querySelector('[data-scout-scan]').textContent = text(lastData ? 'refresh' : 'scan');
        const options = panel.querySelectorAll('[data-scout-role] option');
        ['role_all', 'role_chat', 'role_coding', 'role_vision'].forEach((key, index) => { options[index].textContent = text(key); });
        panel.querySelector('[data-scout-note]').textContent = text('score_hint') + ' ' + text('phase_hint');
        panel.querySelector('[data-scout-scan]').addEventListener('click', () => scan(panel));
        panel.querySelector('[data-scout-role]').addEventListener('change', () => scan(panel));
        return panel;
    }

    function renderCard(candidate) {
        const card = document.createElement('article');
        card.className = 'model-scout-card';
        card.dataset.status = candidate.status || 'interesting';

        const memory = candidate.estimated_memory_gb == null ? text('unknown') : candidate.estimated_memory_gb.toFixed(1) + ' GB';
        const params = candidate.parameter_billions == null ? '—' : candidate.parameter_billions + 'B';
        const quant = candidate.quantization_bits == null ? '—' : candidate.quantization_bits + '-bit';

        card.innerHTML = `
            <div class="model-scout-card-top"><div class="model-scout-name"></div><span class="model-scout-badge"></span></div>
            <div class="model-scout-specs"></div>
            <div class="model-scout-stats">
                <span>${text('memory')}: <strong>${memory}</strong></span>
                <span>${text('params')}: <strong>${params}</strong></span>
                <span>${text('quant')}: <strong>${quant}</strong></span>
                <span>${text('license')}: <strong>${candidate.license || '—'}</strong></span>
                <span>${text('updated')}: <strong>${formatDate(candidate.last_modified)}</strong></span>
                <span>${text('downloads')}: <strong>${formatNumber(candidate.downloads)}</strong></span>
                <span>${text('likes')}: <strong>${formatNumber(candidate.likes)}</strong></span>
                <span>${text('system')}: <strong>${fitLabel(candidate.memory_fit)}</strong></span>
            </div>
            <div class="model-scout-actions"></div>
        `;
        card.querySelector('.model-scout-name').textContent = candidate.id;
        card.querySelector('.model-scout-badge').textContent = statusLabel(candidate.status);

        const specs = card.querySelector('.model-scout-specs');
        [candidate.role, 'score ' + candidate.discovery_score].forEach(value => {
            const chip = document.createElement('span');
            chip.className = 'model-scout-chip';
            chip.textContent = value;
            specs.appendChild(chip);
        });

        const actions = card.querySelector('.model-scout-actions');
        const link = document.createElement('a');
        link.className = 'model-scout-button';
        link.href = candidate.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = text('details');
        actions.appendChild(link);

        if (!candidate.installed) {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'model-scout-button';
            add.textContent = text('add_test');
            add.addEventListener('click', () => addCandidate(candidate, add, card));
            actions.appendChild(add);
        }
        return card;
    }

    function render(panel, data) {
        lastData = data;
        const grid = panel.querySelector('[data-scout-grid]');
        grid.innerHTML = '';
        const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
        panel.querySelector('[data-scout-status]').textContent = candidates.length
            ? text('found', { count: candidates.length })
            : text('no_results');
        candidates.forEach(candidate => grid.appendChild(renderCard(candidate)));

        const profile = data?.profile || {};
        const source = Array.isArray(data?.sources) ? data.sources.join(', ') : '—';
        panel.querySelector('.model-scout-meta').textContent =
            (profile.memory_gb ? profile.memory_gb + ' GB · ' : '') + profile.architecture + ' · ' + text('source') + ': ' + source;
        panel.querySelector('[data-scout-scan]').textContent = text('refresh');
        const now = new Date();
        panel.dataset.lastScan = now.toISOString();
        localStorage.setItem('mlx-nobby-model-scout-last-scan', now.toISOString());
    }

    async function scan(panel) {
        const button = panel.querySelector('[data-scout-scan]');
        const status = panel.querySelector('[data-scout-status]');
        const role = panel.querySelector('[data-scout-role]').value || 'all';
        button.disabled = true;
        button.textContent = text('scanning');
        status.textContent = text('scanning');
        try {
            const response = await fetch('/api/mlx/model-scout/discover?limit=36&role=' + encodeURIComponent(role), { cache: 'no-store' });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            render(panel, await response.json());
        } catch (error) {
            console.error('[model-scout] discovery failed:', error);
            status.textContent = text('unavailable');
            button.textContent = text(lastData ? 'refresh' : 'scan');
        } finally {
            button.disabled = false;
        }
    }

    async function addCandidate(candidate, button, card) {
        button.disabled = true;
        button.textContent = text('adding');
        try {
            const response = await fetch('/api/mlx/models/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    alias: candidate.suggested_alias,
                    repo: candidate.id,
                    quantization: candidate.quantization_bits == null ? null : candidate.quantization_bits + 'bit'
                })
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || 'HTTP ' + response.status);
            candidate.installed = true;
            candidate.status = 'installed';
            card.dataset.status = 'installed';
            card.querySelector('.model-scout-badge').textContent = text('installed');
            button.textContent = text('added');
            setTimeout(() => button.remove(), 1400);
        } catch (error) {
            console.error('[model-scout] add failed:', error);
            button.disabled = false;
            button.textContent = text('add_failed');
            button.title = String(error?.message || error);
        }
    }

    async function mount() {
        const content = document.getElementById('modelConsoleContent');
        if (!content) return false;
        injectStyles();
        if (!mounted) {
            await loadCopy();
            mounted = true;
        }
        const panel = createPanel(content);
        const last = localStorage.getItem('mlx-nobby-model-scout-last-scan');
        if (last && !panel.dataset.lastScan) {
            const date = new Date(last);
            if (!Number.isNaN(date.getTime())) {
                panel.querySelector('[data-scout-status]').textContent = text('last_scan', {
                    time: new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', { dateStyle: 'short', timeStyle: 'short' }).format(date)
                });
            }
        }
        return true;
    }

    function init() {
        mount();
        const observer = new MutationObserver(() => mount());
        observer.observe(document.documentElement, { childList: true, subtree: true });
        document.addEventListener('mlx-language-changed', async () => {
            await loadCopy();
            const existing = document.querySelector('#modelConsoleContent > .model-scout');
            existing?.remove();
            mount();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
