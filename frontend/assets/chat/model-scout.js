(function () {
    'use strict';

    const FALLBACK = {
        title: 'Model Scout', subtitle: 'Find recent MLX models, check system fit and compare local candidates directly with the active model.',
        scan: 'Search for new models', scanning: 'Searching Hugging Face…', refresh: 'Search again', role_all: 'All', role_chat: 'Chat', role_coding: 'Coding', role_vision: 'Vision',
        system: 'System', source: 'Source', found: '{count} candidates found', no_results: 'No matching candidates found.', unavailable: 'Model Scout is currently unavailable.',
        candidate: 'Upgrade candidate', interesting: 'Interesting', installed: 'Installed', not_recommended: 'Tight for this system', memory: 'Estimated memory', unknown: 'unknown', params: 'Parameters', quant: 'Quantization', license: 'License', updated: 'Updated', downloads: 'Downloads', likes: 'Likes', details: 'Hugging Face',
        add_test: 'Add for testing', adding: 'Adding…', added: 'Added to model manager', add_failed: 'Could not add model', fit_excellent: 'Excellent fit', fit_good: 'Good fit', fit_tight: 'Tight', fit_risky: 'Risky', fit_unknown: 'Fit unknown',
        score_hint: 'The discovery score combines freshness, popularity and system fit. It is not a quality benchmark.', phase_hint: 'Local candidates can be compared with the active model. The A/B test temporarily switches the runtime and restores the original model afterwards.',
        benchmark: 'Run A/B test', benchmark_download_first: 'Download locally first', benchmark_starting: 'Starting benchmark…', benchmark_running: 'A/B test: {phase} · {progress}%', benchmark_failed: 'Benchmark failed', benchmark_result: 'Local A/B quick test',
        benchmark_quality: 'Quality', benchmark_generation: 'Generation', benchmark_prefill: 'Effective prefill', benchmark_ttft: 'TTFT', benchmark_memory: 'Runtime RSS', benchmark_baseline: 'Current', benchmark_candidate: 'Candidate', benchmark_delta: 'Delta',
        benchmark_suite_note: 'The quality score comes from a small deterministic micro-suite and is not a general leaderboard score.', signal_strong_candidate: 'Strong candidate', signal_promising: 'Promising', signal_mixed: 'Mixed result', signal_quality_regression: 'Quality regression',
        phase_queued: 'queued', phase_waiting_runtime: 'reserving runtime', phase_baseline: 'testing active model', phase_switching_candidate: 'loading candidate', phase_candidate: 'testing candidate', phase_restoring: 'restoring original model', phase_restoring_after_error: 'restoring runtime', phase_completed: 'done'
    };

    let copy = { ...FALLBACK };
    let copyLoaded = false;
    let lastData = null;

    function text(key, vars = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => { value = value.replaceAll('{' + name + '}', String(replacement)); });
        return value;
    }

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    async function loadCopy(force = false) {
        if (copyLoaded && !force) return;
        copy = { ...FALLBACK };
        try {
            const response = await fetch('/i18n/model-scout.' + locale() + '.json', { cache: 'no-store' });
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_) {}
        copyLoaded = true;
    }

    function injectStyles() {
        if (document.getElementById('modelScoutStyles')) return;
        const style = document.createElement('style');
        style.id = 'modelScoutStyles';
        style.textContent = `
            .model-scout{margin:0 0 16px;padding:15px;border:1px solid #293244;border-radius:13px;background:linear-gradient(145deg,rgba(18,24,35,.92),rgba(10,14,21,.9))}.model-scout-head{display:flex;gap:14px;align-items:flex-start;justify-content:space-between}.model-scout-title{margin:0;font-size:15px;font-weight:750}.model-scout-subtitle{margin:5px 0 0;color:var(--muted);font-size:11px;line-height:1.45;max-width:720px}
            .model-scout-controls{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-top:12px}.model-scout-button,.model-scout-select{min-height:34px;border:1px solid #30394a;border-radius:9px;background:#151b26;color:var(--text);font:inherit;font-size:11px}.model-scout-button{padding:0 11px;cursor:pointer;font-weight:650}.model-scout-button.primary{background:#326fda;border-color:#4f8cff;color:white}.model-scout-button:disabled{opacity:.5;cursor:default}.model-scout-select{padding:0 28px 0 9px}.model-scout-meta{margin-left:auto;color:var(--muted);font-size:10px}.model-scout-status{margin-top:10px;color:#9da9b9;font-size:11px}.model-scout-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:9px;margin-top:12px}
            .model-scout-card{min-width:0;padding:12px;border:1px solid #283244;border-radius:11px;background:rgba(10,14,20,.55)}.model-scout-card[data-status="candidate"]{border-color:rgba(64,214,154,.38)}.model-scout-card[data-status="not_recommended"]{border-color:rgba(240,185,103,.38)}.model-scout-card-top{display:flex;align-items:flex-start;gap:8px;justify-content:space-between}.model-scout-name{min-width:0;font-size:12px;font-weight:700;overflow-wrap:anywhere}.model-scout-badge{flex:0 0 auto;padding:3px 6px;border-radius:999px;background:#1a2230;color:#aab5c4;font-size:9px;font-weight:700}.model-scout-card[data-status="candidate"] .model-scout-badge{background:rgba(35,126,91,.18);color:#77ddb7}.model-scout-card[data-status="installed"] .model-scout-badge{background:rgba(47,111,234,.17);color:#91b5ff}
            .model-scout-specs{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}.model-scout-chip{padding:3px 6px;border:1px solid #293344;border-radius:7px;color:#9ca8b8;font-size:9px}.model-scout-stats{display:grid;grid-template-columns:1fr 1fr;gap:5px 10px;margin-top:10px;color:#8793a4;font-size:10px}.model-scout-stats strong{color:#c7d0dc;font-weight:600}.model-scout-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}.model-scout-actions a{text-decoration:none;display:inline-flex;align-items:center}.model-scout-note{margin-top:10px;color:#6f7b8c;font-size:10px;line-height:1.45}
            .model-scout-benchmark{margin-top:12px;padding:10px;border:1px solid #2c3749;border-radius:10px;background:rgba(16,22,32,.75)}.model-scout-benchmark-head{display:flex;gap:8px;align-items:center;justify-content:space-between}.model-scout-benchmark-title{font-size:11px;font-weight:750}.model-scout-signal{padding:3px 7px;border-radius:999px;background:rgba(47,111,234,.16);color:#9bb9ff;font-size:9px;font-weight:750}.model-scout-benchmark-table{display:grid;grid-template-columns:minmax(90px,1.2fr) repeat(3,minmax(70px,1fr));gap:5px 8px;margin-top:9px;font-size:9px;color:#8290a1}.model-scout-benchmark-table strong{color:#c8d2df;font-weight:650}.model-scout-benchmark-table .head{color:#6f7c8e;font-weight:700}.model-scout-benchmark-note{margin-top:8px;color:#687587;font-size:9px;line-height:1.4}
            @media(max-width:720px){.model-scout-head{display:block}.model-scout-meta{margin-left:0}.model-scout-grid{grid-template-columns:1fr}.model-scout-benchmark-table{grid-template-columns:minmax(80px,1.2fr) repeat(3,minmax(58px,1fr))}}
        `;
        document.head.appendChild(style);
    }

    function formatNumber(value) {
        return new Intl.NumberFormat(locale() === 'de' ? 'de-DE' : 'en-US', { notation: Number(value) >= 100000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(Number(value) || 0);
    }

    function formatDate(value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', { dateStyle: 'medium' }).format(date);
    }

    function statusLabel(status) { return text({ candidate: 'candidate', interesting: 'interesting', installed: 'installed', not_recommended: 'not_recommended' }[status] || 'interesting'); }
    function fitLabel(fit) { return text({ excellent: 'fit_excellent', good: 'fit_good', tight: 'fit_tight', risky: 'fit_risky', unknown: 'fit_unknown' }[fit] || 'fit_unknown'); }
    function signalLabel(signal) { return text({ strong_candidate: 'signal_strong_candidate', promising: 'signal_promising', mixed: 'signal_mixed', quality_regression: 'signal_quality_regression' }[signal] || 'signal_mixed'); }
    function phaseLabel(phase) { return text('phase_' + String(phase || 'queued')); }

    function createPanel(content) {
        let panel = content.querySelector(':scope > .model-scout');
        if (panel) return panel;
        panel = document.createElement('section');
        panel.className = 'model-scout';
        panel.innerHTML = `<div class="model-scout-head"><div><h4 class="model-scout-title"></h4><p class="model-scout-subtitle"></p></div><div class="model-scout-meta"></div></div><div class="model-scout-controls"><button type="button" class="model-scout-button primary" data-scout-scan></button><select class="model-scout-select" data-scout-role><option value="all"></option><option value="chat"></option><option value="coding"></option><option value="vision"></option></select></div><div class="model-scout-status" data-scout-status></div><div class="model-scout-grid" data-scout-grid></div><div class="model-scout-note" data-scout-note></div>`;
        content.prepend(panel);
        applyPanelCopy(panel);
        panel.querySelector('[data-scout-scan]').addEventListener('click', () => scan(panel));
        panel.querySelector('[data-scout-role]').addEventListener('change', () => scan(panel));
        return panel;
    }

    function applyPanelCopy(panel) {
        panel.querySelector('.model-scout-title').textContent = text('title');
        panel.querySelector('.model-scout-subtitle').textContent = text('subtitle');
        panel.querySelector('[data-scout-scan]').textContent = text(lastData ? 'refresh' : 'scan');
        const options = panel.querySelectorAll('[data-scout-role] option');
        ['role_all', 'role_chat', 'role_coding', 'role_vision'].forEach((key, index) => { if (options[index]) options[index].textContent = text(key); });
        panel.querySelector('[data-scout-note]').textContent = text('score_hint') + ' ' + text('phase_hint');
    }

    function addStat(container, label, value) {
        const span = document.createElement('span');
        span.append(document.createTextNode(label + ': '));
        const strong = document.createElement('strong');
        strong.textContent = value;
        span.appendChild(strong);
        container.appendChild(span);
    }

    function renderCard(candidate) {
        const card = document.createElement('article');
        card.className = 'model-scout-card';
        card.dataset.status = candidate.status || 'interesting';
        const top = document.createElement('div'); top.className = 'model-scout-card-top';
        const name = document.createElement('div'); name.className = 'model-scout-name'; name.textContent = candidate.id;
        const badge = document.createElement('span'); badge.className = 'model-scout-badge'; badge.textContent = statusLabel(candidate.status);
        top.append(name, badge); card.appendChild(top);
        const specs = document.createElement('div'); specs.className = 'model-scout-specs';
        [candidate.role, 'score ' + candidate.discovery_score].forEach(value => { const chip = document.createElement('span'); chip.className = 'model-scout-chip'; chip.textContent = value; specs.appendChild(chip); });
        card.appendChild(specs);
        const stats = document.createElement('div'); stats.className = 'model-scout-stats';
        addStat(stats, text('memory'), candidate.estimated_memory_gb == null ? text('unknown') : Number(candidate.estimated_memory_gb).toFixed(1) + ' GB');
        addStat(stats, text('params'), candidate.parameter_billions == null ? '—' : candidate.parameter_billions + 'B'); addStat(stats, text('quant'), candidate.quantization_bits == null ? '—' : candidate.quantization_bits + '-bit'); addStat(stats, text('license'), candidate.license || '—'); addStat(stats, text('updated'), formatDate(candidate.last_modified)); addStat(stats, text('downloads'), formatNumber(candidate.downloads)); addStat(stats, text('likes'), formatNumber(candidate.likes)); addStat(stats, text('system'), fitLabel(candidate.memory_fit)); card.appendChild(stats);
        const actions = document.createElement('div'); actions.className = 'model-scout-actions';
        const link = document.createElement('a'); link.className = 'model-scout-button'; link.href = candidate.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = text('details'); actions.appendChild(link);
        if (!candidate.installed) {
            const add = document.createElement('button'); add.type = 'button'; add.className = 'model-scout-button'; add.textContent = text('add_test'); add.addEventListener('click', () => addCandidate(candidate, add, card)); actions.appendChild(add);
        } else {
            const benchmark = document.createElement('button'); benchmark.type = 'button'; benchmark.className = 'model-scout-button'; benchmark.textContent = candidate.benchmark_ready ? text('benchmark') : text('benchmark_download_first'); benchmark.disabled = !candidate.benchmark_ready || !candidate.installed_alias;
            if (!benchmark.disabled) benchmark.addEventListener('click', () => startBenchmark(candidate, benchmark, card)); actions.appendChild(benchmark);
        }
        card.appendChild(actions); return card;
    }

    function render(panel, data) {
        lastData = data;
        const grid = panel.querySelector('[data-scout-grid]'); grid.innerHTML = '';
        const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
        panel.querySelector('[data-scout-status]').textContent = candidates.length ? text('found', { count: candidates.length }) : text('no_results');
        candidates.forEach(candidate => grid.appendChild(renderCard(candidate)));
        const profile = data?.profile || {}; const source = Array.isArray(data?.sources) ? data.sources.join(', ') : '—';
        panel.querySelector('.model-scout-meta').textContent = (profile.memory_gb ? profile.memory_gb + ' GB · ' : '') + (profile.architecture || '—') + ' · ' + text('source') + ': ' + source;
        panel.querySelector('[data-scout-scan]').textContent = text('refresh');
        localStorage.setItem('mlx-nobby-model-scout-last-scan', new Date().toISOString());
    }

    async function scan(panel) {
        const button = panel.querySelector('[data-scout-scan]'); const status = panel.querySelector('[data-scout-status]'); const role = panel.querySelector('[data-scout-role]').value || 'all';
        button.disabled = true; button.textContent = text('scanning'); status.textContent = text('scanning');
        try { const response = await fetch('/api/mlx/model-scout/discover?limit=36&role=' + encodeURIComponent(role), { cache: 'no-store' }); if (!response.ok) throw new Error('HTTP ' + response.status); render(panel, await response.json()); }
        catch (error) { console.error('[model-scout] discovery failed:', error); status.textContent = text('unavailable'); button.textContent = text(lastData ? 'refresh' : 'scan'); }
        finally { button.disabled = false; }
    }

    async function addCandidate(candidate, button, card) {
        button.disabled = true; button.textContent = text('adding');
        try {
            const response = await fetch('/api/mlx/models/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ alias: candidate.suggested_alias, repo: candidate.id, quantization: null }) });
            const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || 'HTTP ' + response.status);
            candidate.installed = true; candidate.installed_alias = candidate.suggested_alias; candidate.status = 'installed'; card.dataset.status = 'installed'; card.querySelector('.model-scout-badge').textContent = text('installed'); button.textContent = text('added');
            const panel = card.closest('.model-scout'); setTimeout(() => { if (panel) scan(panel); }, 700);
        } catch (error) { console.error('[model-scout] add failed:', error); button.disabled = false; button.textContent = text('add_failed'); button.title = String(error?.message || error); }
    }

    function formatDelta(value, suffix = '%') { if (value == null || Number.isNaN(Number(value))) return '—'; const number = Number(value); return (number > 0 ? '+' : '') + number.toFixed(1) + suffix; }
    function formatMetric(value, suffix, digits = 1) { if (value == null || Number.isNaN(Number(value))) return '—'; return Number(value).toFixed(digits) + suffix; }
    function appendBenchmarkRow(table, label, baseline, candidate, delta) { [label, baseline, candidate, delta].forEach((value, index) => { const cell = document.createElement(index === 0 ? 'strong' : 'span'); cell.textContent = value; table.appendChild(cell); }); }

    function renderBenchmarkResult(card, result) {
        card.querySelector('.model-scout-benchmark')?.remove();
        const comparison = result?.comparison || {}, baseline = result?.baseline || {}, candidate = result?.candidate || {}, basePerf = baseline.performance || {}, candPerf = candidate.performance || {};
        const box = document.createElement('div'); box.className = 'model-scout-benchmark';
        const head = document.createElement('div'); head.className = 'model-scout-benchmark-head'; const title = document.createElement('div'); title.className = 'model-scout-benchmark-title'; title.textContent = text('benchmark_result'); const signal = document.createElement('span'); signal.className = 'model-scout-signal'; signal.textContent = signalLabel(comparison.signal); head.append(title, signal); box.appendChild(head);
        const table = document.createElement('div'); table.className = 'model-scout-benchmark-table'; ['', text('benchmark_baseline'), text('benchmark_candidate'), text('benchmark_delta')].forEach(value => { const cell = document.createElement('span'); cell.className = 'head'; cell.textContent = value; table.appendChild(cell); });
        appendBenchmarkRow(table, text('benchmark_quality'), formatMetric(baseline.quality?.score, '%'), formatMetric(candidate.quality?.score, '%'), formatDelta(comparison.quality_delta_points, ' P'));
        appendBenchmarkRow(table, text('benchmark_generation'), formatMetric(basePerf.generation_tps, ' tok/s'), formatMetric(candPerf.generation_tps, ' tok/s'), formatDelta(comparison.generation_tps_delta_pct));
        appendBenchmarkRow(table, text('benchmark_prefill'), formatMetric(basePerf.effective_prefill_tps, ' tok/s'), formatMetric(candPerf.effective_prefill_tps, ' tok/s'), formatDelta(comparison.prefill_tps_delta_pct));
        appendBenchmarkRow(table, text('benchmark_ttft'), formatMetric(basePerf.ttft_seconds, ' s', 3), formatMetric(candPerf.ttft_seconds, ' s', 3), formatDelta(comparison.ttft_delta_pct));
        appendBenchmarkRow(table, text('benchmark_memory'), formatMetric(basePerf.runtime_rss_gb, ' GB', 2), formatMetric(candPerf.runtime_rss_gb, ' GB', 2), formatDelta(comparison.runtime_rss_delta_pct)); box.appendChild(table);
        const note = document.createElement('div'); note.className = 'model-scout-benchmark-note'; note.textContent = text('benchmark_suite_note'); box.appendChild(note); card.appendChild(box);
    }

    async function startBenchmark(candidate, button, card) {
        button.disabled = true; button.textContent = text('benchmark_starting');
        try {
            const response = await fetch('/api/mlx/model-scout/benchmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ candidate_alias: candidate.installed_alias }) });
            const job = await response.json().catch(() => ({})); if (!response.ok) throw new Error(job.detail || 'HTTP ' + response.status); await pollBenchmark(job.id, button, card);
        } catch (error) { console.error('[model-scout] benchmark failed:', error); button.disabled = false; button.textContent = text('benchmark_failed'); button.title = String(error?.message || error); }
    }

    async function pollBenchmark(jobId, button, card) {
        for (;;) {
            await new Promise(resolve => setTimeout(resolve, 1200));
            const response = await fetch('/api/mlx/model-scout/benchmarks/' + encodeURIComponent(jobId), { cache: 'no-store' }); const job = await response.json().catch(() => ({})); if (!response.ok) throw new Error(job.detail || 'HTTP ' + response.status);
            button.textContent = text('benchmark_running', { phase: phaseLabel(job.phase), progress: Math.round(Number(job.progress) || 0) });
            if (job.status === 'completed') { renderBenchmarkResult(card, job.result); button.disabled = false; button.textContent = text('benchmark'); return; }
            if (job.status === 'failed') throw new Error(job.error || text('benchmark_failed'));
        }
    }

    async function mount() {
        const content = document.getElementById('modelConsoleContent'); if (!content) return false; injectStyles(); await loadCopy(); const panel = createPanel(content); applyPanelCopy(panel); if (lastData && !panel.querySelector('[data-scout-grid]').children.length) render(panel, lastData); return true;
    }

    function scheduleMount() { requestAnimationFrame(() => { mount(); }); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scheduleMount, { once: true }); else scheduleMount();
    const observer = new MutationObserver(() => { if (!document.querySelector('#modelConsoleContent > .model-scout')) scheduleMount(); }); observer.observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener('mlx-language-changed', async () => { copyLoaded = false; await loadCopy(true); const panel = document.querySelector('#modelConsoleContent > .model-scout'); if (!panel) return; const role = panel.querySelector('[data-scout-role]')?.value || 'all'; panel.remove(); const content = document.getElementById('modelConsoleContent'); if (!content) return; const replacement = createPanel(content); replacement.querySelector('[data-scout-role]').value = role; if (lastData) render(replacement, lastData); });
})();
