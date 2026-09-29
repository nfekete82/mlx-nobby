(function () {
    'use strict';

    if (window.__mlxNobbyModelScoutV3) return;
    window.__mlxNobbyModelScoutV3 = true;

    const SORT_VALUES = ['score', 'newest', 'downloads', 'memory', 'quality', 'speed'];
    const STORAGE_KEY = 'mlx-nobby-model-scout-sort';
    const FALLBACK = {
        sort_label: 'Sort',
        sort_score: 'Discovery score',
        sort_newest: 'Newest',
        sort_downloads: 'Downloads',
        sort_memory: 'Memory',
        sort_quality: 'Benchmark quality',
        sort_speed: 'Generation speed',
        history_title: 'Benchmark history',
        history_empty: 'No local A/B benchmarks yet.',
        tested: 'Tested',
        tested_at: 'Tested {time}',
        adopt: 'Use as chat model',
        adopting: 'Switching model…',
        adopted: 'Active model',
        adopt_failed: 'Model switch failed',
        adopt_confirm: 'Switch the chat runtime to {model}? The previous model is restored automatically if the switch fails.',
        adopt_warning_license: 'License metadata is missing.',
        adopt_warning_regression: 'The latest quick test reported a quality regression.',
        adopt_block_benchmark: 'Run a local A/B test first.',
        adopt_block_local: 'The model must be available locally first.',
        adopt_block_memory: 'The estimated memory fit is risky for this system.',
        batch: 'Test top 3',
        batch_running: 'Testing {current}/{total}…',
        batch_done: '{count} models tested',
        batch_none: 'No eligible local candidates are visible.',
        batch_failed: 'Batch benchmark stopped',
        quality_short: 'Quality',
        speed_short: 'Gen.',
        memory_short: 'RAM',
        current_short: 'Current',
        candidate_short: 'Candidate',
        delta_short: 'Delta',
        rollback_failed: 'Rollback also failed: {error}'
    };

    let copy = { ...FALLBACK };
    let candidateIndex = new Map();
    let history = [];
    let selectedSort = SORT_VALUES.includes(localStorage.getItem(STORAGE_KEY))
        ? localStorage.getItem(STORAGE_KEY)
        : 'score';
    let refreshTimer = null;
    let busyBatch = false;
    let busySwitch = false;
    let rootObserver = null;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function text(key, vars = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => {
            value = String(value).replaceAll('{' + name + '}', String(replacement));
        });
        return value;
    }

    async function loadCopy() {
        copy = { ...FALLBACK };
        try {
            const response = await fetch('/i18n/model-scout.' + locale() + '.json', { cache: 'no-store' });
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_) {}
    }

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.error || ('HTTP ' + response.status));
        return data;
    }

    function numberOrNull(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function latestBenchmarkFor(candidate, entries = history) {
        if (!candidate) return null;
        const repo = String(candidate.id || candidate.repo || '');
        const alias = String(candidate.installed_alias || candidate.alias || '');
        return (entries || []).find(item =>
            (repo && String(item?.candidate_repo || '') === repo) ||
            (alias && String(item?.candidate_alias || '') === alias)
        ) || null;
    }

    function sortCandidates(candidates, sort = selectedSort, entries = history) {
        const list = [...(candidates || [])];
        const metric = candidate => {
            const benchmark = latestBenchmarkFor(candidate, entries);
            if (sort === 'newest') {
                const value = new Date(candidate.last_modified || 0).getTime();
                return Number.isFinite(value) ? value : -Infinity;
            }
            if (sort === 'downloads') return numberOrNull(candidate.downloads) ?? -Infinity;
            if (sort === 'memory') return numberOrNull(candidate.estimated_memory_gb) ?? Infinity;
            if (sort === 'quality') return numberOrNull(benchmark?.candidate?.quality?.score) ?? -Infinity;
            if (sort === 'speed') return numberOrNull(benchmark?.candidate?.performance?.generation_tps) ?? -Infinity;
            return numberOrNull(candidate.discovery_score) ?? -Infinity;
        };
        list.sort((a, b) => {
            const av = metric(a);
            const bv = metric(b);
            if (sort === 'memory') {
                if (av !== bv) return av - bv;
            } else if (av !== bv) {
                return bv - av;
            }
            return String(a.id || '').localeCompare(String(b.id || ''));
        });
        return list;
    }

    function preflightCandidate(candidate, benchmark) {
        const blockers = [];
        const warnings = [];
        if (!candidate?.installed || !candidate?.installed_alias || !candidate?.benchmark_ready) blockers.push('local');
        if (candidate?.memory_fit === 'risky') blockers.push('memory');
        if (!benchmark) blockers.push('benchmark');
        if (!candidate?.license) warnings.push('license');
        if (benchmark?.comparison?.signal === 'quality_regression') warnings.push('quality_regression');
        return { ok: blockers.length === 0, blockers, warnings };
    }

    function candidateForCard(card) {
        const id = String(card?.querySelector?.('.model-scout-name')?.textContent || '').trim();
        return candidateIndex.get(id) || null;
    }

    function signalLabel(signal) {
        const map = {
            strong_candidate: 'signal_strong_candidate',
            promising: 'signal_promising',
            mixed: 'signal_mixed',
            quality_regression: 'signal_quality_regression'
        };
        return text(map[signal] || 'signal_mixed');
    }

    function formatDate(value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', {
            dateStyle: 'short', timeStyle: 'short'
        }).format(date);
    }

    function formatDelta(value, suffix = '%') {
        const number = numberOrNull(value);
        if (number === null) return '—';
        return (number > 0 ? '+' : '') + number.toFixed(1) + suffix;
    }

    function injectStyles() {
        if (document.getElementById('modelScoutV3Styles')) return;
        const style = document.createElement('style');
        style.id = 'modelScoutV3Styles';
        style.textContent = `
            .model-scout-v3-count{color:#778397;font-size:9px;white-space:nowrap}.model-scout-tested{border-color:rgba(52,211,153,.35)!important;background:rgba(16,185,129,.08)!important;color:#83e6bf!important}.model-scout-adopt{border-color:rgba(52,211,153,.42)!important}.model-scout-adopt.primary{background:rgba(30,138,96,.9)!important;border-color:rgba(72,205,151,.72)!important}.model-scout-history{margin-top:12px;border:1px solid #293344;border-radius:10px;background:rgba(9,13,20,.42);overflow:hidden}.model-scout-history>summary{padding:10px 12px;cursor:pointer;font-size:11px;font-weight:700;color:#b7c2d1}.model-scout-history-list{display:grid;gap:1px;background:#252e3d}.model-scout-history-row{display:grid;grid-template-columns:minmax(150px,1.7fr) repeat(4,minmax(62px,.7fr));gap:8px;padding:9px 12px;background:#0f151f;align-items:center;font-size:9px;color:#8c99aa}.model-scout-history-row strong{color:#c8d2df;overflow-wrap:anywhere}.model-scout-history-signal{justify-self:end;padding:3px 6px;border-radius:999px;background:rgba(47,111,234,.14);color:#a8c0ff;font-weight:700}.model-scout-v3-message{margin-top:8px;font-size:10px;color:#92a0b2}.model-scout-v3-message.error{color:#f0a5a5}@media(max-width:760px){.model-scout-history-row{grid-template-columns:1fr 1fr}.model-scout-history-signal{justify-self:start}}
        `;
        document.head.appendChild(style);
    }

    function ensureControls(panel) {
        const controls = panel?.querySelector('.model-scout-controls');
        if (!controls) return;
        let sort = controls.querySelector('[data-scout-sort]');
        if (!sort) {
            sort = document.createElement('select');
            sort.className = 'model-scout-select';
            sort.dataset.scoutSort = 'true';
            for (const value of SORT_VALUES) {
                const option = document.createElement('option');
                option.value = value;
                sort.appendChild(option);
            }
            sort.value = selectedSort;
            sort.addEventListener('change', () => {
                selectedSort = SORT_VALUES.includes(sort.value) ? sort.value : 'score';
                localStorage.setItem(STORAGE_KEY, selectedSort);
                applySort(panel);
            });
            controls.appendChild(sort);
        }
        const sortKeys = ['sort_score', 'sort_newest', 'sort_downloads', 'sort_memory', 'sort_quality', 'sort_speed'];
        Array.from(sort.options).forEach((option, index) => { option.textContent = text(sortKeys[index]); });
        sort.setAttribute('aria-label', text('sort_label'));
        sort.value = selectedSort;

        let batch = controls.querySelector('[data-scout-batch]');
        if (!batch) {
            batch = document.createElement('button');
            batch.type = 'button';
            batch.className = 'model-scout-button';
            batch.dataset.scoutBatch = 'true';
            batch.addEventListener('click', () => runTopThree(panel, batch));
            controls.appendChild(batch);
        }
        if (!busyBatch) batch.textContent = text('batch');
    }

    function applySort(panel) {
        const grid = panel?.querySelector('[data-scout-grid]');
        if (!grid) return;
        const cards = Array.from(grid.querySelectorAll('.model-scout-card'));
        if (cards.length < 2) return;
        const sortedIds = sortCandidates(cards.map(candidateForCard).filter(Boolean), selectedSort, history).map(item => item.id);
        const cardById = new Map(cards.map(card => [String(card.querySelector('.model-scout-name')?.textContent || '').trim(), card]));
        const sortedCards = sortedIds.map(id => cardById.get(id)).filter(Boolean);
        cards.forEach(card => { if (!sortedCards.includes(card)) sortedCards.push(card); });
        const unchanged = sortedCards.every((card, index) => card === cards[index]);
        if (unchanged) return;
        const fragment = document.createDocumentFragment();
        sortedCards.forEach(card => fragment.appendChild(card));
        grid.appendChild(fragment);
    }

    function blockersText(preflight) {
        return preflight.blockers.map(item => text({
            local: 'adopt_block_local',
            memory: 'adopt_block_memory',
            benchmark: 'adopt_block_benchmark'
        }[item])).join(' ');
    }

    function warningsText(preflight) {
        return preflight.warnings.map(item => text({
            license: 'adopt_warning_license',
            quality_regression: 'adopt_warning_regression'
        }[item])).join(' ');
    }

    function enhanceCard(card) {
        const candidate = candidateForCard(card);
        if (!candidate) return;
        const benchmark = latestBenchmarkFor(candidate);
        const specs = card.querySelector('.model-scout-specs');
        if (benchmark && specs && !specs.querySelector('[data-scout-tested]')) {
            const chip = document.createElement('span');
            chip.className = 'model-scout-chip model-scout-tested';
            chip.dataset.scoutTested = 'true';
            chip.textContent = text('tested');
            chip.title = text('tested_at', { time: formatDate(benchmark.finished_at || benchmark.created_at) });
            specs.appendChild(chip);
        }

        const actions = card.querySelector('.model-scout-actions');
        if (!actions) return;
        const preflight = preflightCandidate(candidate, benchmark);
        let adopt = actions.querySelector('[data-scout-adopt]');
        if (!adopt && candidate.installed) {
            adopt = document.createElement('button');
            adopt.type = 'button';
            adopt.className = 'model-scout-button model-scout-adopt';
            adopt.dataset.scoutAdopt = candidate.id;
            adopt.addEventListener('click', () => adoptCandidate(candidate, adopt));
            actions.appendChild(adopt);
        }
        if (adopt) {
            adopt.textContent = text('adopt');
            adopt.disabled = !preflight.ok || busySwitch || busyBatch;
            adopt.title = preflight.ok ? warningsText(preflight) : blockersText(preflight);
            if (benchmark?.comparison?.signal === 'strong_candidate' || benchmark?.comparison?.signal === 'promising') adopt.classList.add('primary');
            else adopt.classList.remove('primary');
        }
    }

    function enhanceCards(panel) {
        panel?.querySelectorAll('.model-scout-card').forEach(enhanceCard);
        applySort(panel);
    }

    function ensureHistory(panel) {
        if (!panel) return;
        let box = panel.querySelector('[data-scout-history]');
        if (!box) {
            box = document.createElement('details');
            box.className = 'model-scout-history';
            box.dataset.scoutHistory = 'true';
            const summary = document.createElement('summary');
            summary.dataset.scoutHistoryTitle = 'true';
            const list = document.createElement('div');
            list.className = 'model-scout-history-list';
            list.dataset.scoutHistoryList = 'true';
            box.append(summary, list);
            panel.appendChild(box);
        }
        box.querySelector('[data-scout-history-title]').textContent = text('history_title') + ' · ' + history.length;
        const list = box.querySelector('[data-scout-history-list]');
        list.innerHTML = '';
        if (!history.length) {
            const row = document.createElement('div');
            row.className = 'model-scout-history-row';
            row.textContent = text('history_empty');
            list.appendChild(row);
            return;
        }
        history.slice(0, 10).forEach(item => {
            const row = document.createElement('div');
            row.className = 'model-scout-history-row';
            const name = document.createElement('strong');
            name.textContent = item.candidate_alias || item.candidate_repo || '—';
            const quality = document.createElement('span');
            quality.textContent = text('quality_short') + ' ' + formatDelta(item.comparison?.quality_delta_points, ' P');
            const speed = document.createElement('span');
            speed.textContent = text('speed_short') + ' ' + formatDelta(item.comparison?.generation_tps_delta_pct);
            const date = document.createElement('span');
            date.textContent = formatDate(item.finished_at || item.created_at);
            const signal = document.createElement('span');
            signal.className = 'model-scout-history-signal';
            signal.textContent = signalLabel(item.comparison?.signal);
            row.append(name, quality, speed, date, signal);
            list.appendChild(row);
        });
    }

    async function refreshData(panel) {
        const role = panel?.querySelector('[data-scout-role]')?.value || 'all';
        try {
            const [discovery, historyData] = await Promise.all([
                requestJson('/api/mlx/model-scout/discover?limit=36&role=' + encodeURIComponent(role), { cache: 'no-store' }),
                requestJson('/api/mlx/model-scout/benchmarks', { cache: 'no-store' })
            ]);
            candidateIndex = new Map((discovery.candidates || []).map(item => [String(item.id), item]));
            history = Array.isArray(historyData.benchmarks) ? historyData.benchmarks : [];
        } catch (error) {
            console.error('[model-scout-v3] refresh failed:', error);
        }
        ensureControls(panel);
        ensureHistory(panel);
        enhanceCards(panel);
    }

    function scheduleRefresh(panel, delay = 120) {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(() => refreshData(panel), delay);
    }

    async function pollBenchmark(jobId, onProgress) {
        for (;;) {
            await new Promise(resolve => setTimeout(resolve, 1200));
            const job = await requestJson('/api/mlx/model-scout/benchmarks/' + encodeURIComponent(jobId), { cache: 'no-store' });
            onProgress?.(job);
            if (job.status === 'completed') return job.result;
            if (job.status === 'failed') throw new Error(job.error || text('benchmark_failed'));
        }
    }

    async function runTopThree(panel, button) {
        if (busyBatch || busySwitch) return;
        const cards = Array.from(panel.querySelectorAll('.model-scout-card')).filter(card => !card.hidden);
        const status = await requestJson('/api/mlx/status', { cache: 'no-store' }).catch(() => ({}));
        const eligible = cards
            .map(candidateForCard)
            .filter(candidate => candidate?.installed && candidate?.benchmark_ready && candidate?.installed_alias && candidate.id !== status.model)
            .slice(0, 3);
        if (!eligible.length) {
            button.textContent = text('batch_none');
            setTimeout(() => { button.textContent = text('batch'); }, 2200);
            return;
        }
        busyBatch = true;
        button.disabled = true;
        let completed = 0;
        enhanceCards(panel);
        try {
            for (let index = 0; index < eligible.length; index += 1) {
                button.textContent = text('batch_running', { current: index + 1, total: eligible.length });
                const job = await requestJson('/api/mlx/model-scout/benchmarks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ candidate_alias: eligible[index].installed_alias })
                });
                await pollBenchmark(job.id, progress => {
                    button.textContent = text('batch_running', {
                        current: index + 1,
                        total: eligible.length
                    }) + ' ' + Math.round(Number(progress.progress) || 0) + '%';
                });
                completed += 1;
                await refreshData(panel);
            }
            button.textContent = text('batch_done', { count: completed });
        } catch (error) {
            console.error('[model-scout-v3] batch benchmark failed:', error);
            button.textContent = text('batch_failed');
            button.title = String(error?.message || error);
        } finally {
            busyBatch = false;
            button.disabled = false;
            enhanceCards(panel);
            setTimeout(() => { if (!busyBatch) button.textContent = text('batch'); }, 1800);
        }
    }

    async function waitForModel(repo, timeoutMs = 125000) {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
            const status = await requestJson('/api/mlx/status', { cache: 'no-store' }).catch(() => null);
            if (status?.online && (!repo || status.model === repo)) return status;
            await new Promise(resolve => setTimeout(resolve, 900));
        }
        throw new Error('Runtime confirmation timeout');
    }

    async function adoptCandidate(candidate, button) {
        if (busySwitch || busyBatch) return;
        const benchmark = latestBenchmarkFor(candidate);
        const preflight = preflightCandidate(candidate, benchmark);
        if (!preflight.ok) return;
        const warnings = warningsText(preflight);
        const prompt = text('adopt_confirm', { model: candidate.installed_alias || candidate.id }) + (warnings ? '\n\n' + warnings : '');
        if (!window.confirm(prompt)) return;

        busySwitch = true;
        const originalText = text('adopt');
        button.disabled = true;
        button.textContent = text('adopting');
        window.MLXChatRuntime?.setExternalRuntimeBusy?.(true);
        let previous = null;
        try {
            const [aliases, status] = await Promise.all([
                requestJson('/api/mlx/aliases', { cache: 'no-store' }),
                requestJson('/api/mlx/status', { cache: 'no-store' })
            ]);
            const models = Array.isArray(aliases.models) ? aliases.models : [];
            previous = models.find(model => model.repo === status.model) || models.find(model => model.active) || null;
            const target = models.find(model => model.alias === candidate.installed_alias) || null;
            if (!target?.repo) throw new Error(text('adopt_block_local'));
            if (status.online && status.model === target.repo) {
                button.textContent = text('adopted');
                return;
            }
            await requestJson('/api/mlx/model/' + encodeURIComponent(candidate.installed_alias), { method: 'POST' });
            await waitForModel(target.repo);
            button.textContent = text('adopted');
            await window.MLXModelConsole?.load?.({ force: true });
            window.MLXChatRuntime?.refreshModelState?.().catch(() => {});
        } catch (error) {
            let message = String(error?.message || error);
            if (previous?.alias && previous.alias !== candidate.installed_alias) {
                try {
                    await requestJson('/api/mlx/model/' + encodeURIComponent(previous.alias), { method: 'POST' });
                    await waitForModel(previous.repo);
                } catch (rollbackError) {
                    message += ' | ' + text('rollback_failed', { error: String(rollbackError?.message || rollbackError) });
                }
            }
            console.error('[model-scout-v3] adopt failed:', error);
            button.textContent = text('adopt_failed');
            button.title = message;
        } finally {
            busySwitch = false;
            window.MLXChatRuntime?.setExternalRuntimeBusy?.(false);
            setTimeout(() => {
                if (button.isConnected && button.textContent !== text('adopted')) button.textContent = originalText;
                const panel = document.querySelector('#modelConsoleContent > .model-scout');
                if (panel) scheduleRefresh(panel, 0);
            }, 1800);
        }
    }

    function wirePanel(panel) {
        if (!panel || panel.dataset.scoutV3Wired === 'true') return;
        panel.dataset.scoutV3Wired = 'true';
        const grid = panel.querySelector('[data-scout-grid]');
        if (grid) {
            const observer = new MutationObserver(mutations => {
                const changedCards = mutations.some(mutation => Array.from(mutation.addedNodes || []).some(node => node?.classList?.contains?.('model-scout-card')));
                const benchmarkAdded = mutations.some(mutation => Array.from(mutation.addedNodes || []).some(node => node?.classList?.contains?.('model-scout-benchmark')));
                if (changedCards || benchmarkAdded) scheduleRefresh(panel, benchmarkAdded ? 0 : 180);
            });
            observer.observe(grid, { childList: true, subtree: true });
            panel.__modelScoutV3GridObserver = observer;
        }
        panel.addEventListener('change', event => {
            if (event.target?.matches?.('[data-scout-role]')) scheduleRefresh(panel, 250);
        });
        panel.addEventListener('click', event => {
            if (event.target?.closest?.('[data-scout-scan]')) scheduleRefresh(panel, 450);
        });
    }

    async function mount() {
        const panel = document.querySelector('#modelConsoleContent > .model-scout');
        if (!panel) return false;
        injectStyles();
        await loadCopy();
        wirePanel(panel);
        ensureControls(panel);
        await refreshData(panel);
        return true;
    }

    function scheduleMount() {
        requestAnimationFrame(() => { mount(); });
    }

    window.MLXModelScoutV3 = {
        sortCandidates,
        latestBenchmarkFor,
        preflightCandidate,
        refresh: () => {
            const panel = document.querySelector('#modelConsoleContent > .model-scout');
            if (panel) return refreshData(panel);
            return Promise.resolve();
        }
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scheduleMount, { once: true });
    else scheduleMount();

    rootObserver = new MutationObserver(() => {
        const panel = document.querySelector('#modelConsoleContent > .model-scout');
        if (panel && panel.dataset.scoutV3Wired !== 'true') scheduleMount();
    });
    rootObserver.observe(document.documentElement, { childList: true, subtree: true });

    document.addEventListener('mlx-language-changed', () => {
        loadCopy().then(() => {
            const panel = document.querySelector('#modelConsoleContent > .model-scout');
            if (!panel) return;
            ensureControls(panel);
            ensureHistory(panel);
            enhanceCards(panel);
        });
    });
})();
