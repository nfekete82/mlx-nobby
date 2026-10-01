'use strict';

(() => {
    if (window.__mlxPerformanceObservatoryV2) return;
    window.__mlxPerformanceObservatoryV2 = true;

    const API_URL = '/api/mlx/performance/observatory?limit=40';
    const REFRESH_MS = 7500;
    const CSS_ID = 'mlx-performance-observatory-css';
    const MOUNT_RETRY_MS = 100;
    const MOUNT_RETRY_LIMIT = 100;

    const FALLBACK = {
        title: 'Performance Observatory',
        subtitle: 'Live latency, throughput, media timing and unified-memory telemetry.',
        refresh: 'Refresh',
        loading: 'Collecting performance data…',
        request_failed: 'Performance data could not be loaded: {message}',
        no_data: 'No measurements yet',
        ttft: 'Chat TTFT',
        tokens_per_second: 'Chat throughput',
        image_time: 'Image generation',
        video_time: 'Video generation',
        headroom: 'RAM headroom',
        swap: 'Swap used',
        p50: 'p50',
        p95: 'p95',
        average: 'Average',
        samples: '{count} samples',
        runtime_title: 'Runtime state',
        runtime_start: 'Runtime start',
        chat: 'Chat',
        image: 'Image',
        video: 'Video',
        shorts: 'Shorts',
        warm: 'Warm',
        cold: 'Cold',
        unavailable: 'Unavailable',
        active: 'Active',
        idle: 'Idle',
        memory_title: 'Unified memory',
        pressure: 'Pressure',
        pressure_normal: 'Normal',
        pressure_elevated: 'Elevated',
        pressure_critical: 'Critical',
        pressure_unknown: 'Unknown',
        available: 'Available estimate',
        used: 'Used estimate',
        free: 'Free',
        reserve: 'Reserve',
        model_calls_title: 'Recent model calls',
        media_jobs_title: 'Recent media jobs',
        purpose: 'Purpose',
        model: 'Model',
        status: 'Status',
        total: 'Total',
        queue: 'Queue',
        generation: 'Generation',
        kind: 'Kind',
        completed: 'Completed',
        failed: 'Failed',
        running: 'Running',
        queued: 'Queued',
        cancelled: 'Cancelled',
        unknown: 'Unknown',
        live_note: 'Warm/cold cards show the current loaded state. Video jobs also record historical warm/cold runtime reuse. Model-call history starts with the current Agent process; media history is durable.',
        checked: 'Updated {time}',
        estimate: 'estimated',
        upstream: 'measured'
    };

    let copy = { ...FALLBACK };
    let root = null;
    let refreshTimer = null;
    let busy = false;
    let mountAttempts = 0;
    let visibilityObserver = null;

    function refreshIfVisible() {
        if (!root || document.hidden || root.closest('[hidden]')) return;
        const settings = root.closest('.settings');
        if (settings && !settings.classList.contains('open')) return;
        return refresh();
    }

    function observeVisibility() {
        if (typeof MutationObserver !== 'undefined') {
            visibilityObserver = new MutationObserver(refreshIfVisible);
            for (let parent = root.parentElement; parent; parent = parent.parentElement) {
                visibilityObserver.observe(parent, {
                    attributes: true,
                    attributeFilter: ['class', 'hidden']
                });
            }
        }
        document.addEventListener('visibilitychange', refreshIfVisible);
    }

    function locale() {
        const current = window.MLXI18n?.getLocale?.()
            || window.MLXI18n?.getLanguage?.()
            || document.documentElement?.lang
            || navigator.language
            || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function t(key, variables = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        for (const [name, replacement] of Object.entries(variables)) {
            value = value.replaceAll('{' + name + '}', String(replacement ?? ''));
        }
        return value;
    }

    function el(tag, className = '', text = null) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function number(value) {
        const result = Number(value);
        return Number.isFinite(result) ? result : null;
    }

    function formatDuration(milliseconds) {
        const value = number(milliseconds);
        if (value == null) return '—';
        if (value < 1000) return Math.round(value) + ' ms';
        if (value < 60000) {
            return (value / 1000).toLocaleString(undefined, {
                maximumFractionDigits: value < 10000 ? 2 : 1
            }) + ' s';
        }
        return (value / 60000).toLocaleString(undefined, {
            maximumFractionDigits: 1
        }) + ' min';
    }

    function formatRate(value) {
        const result = number(value);
        if (result == null) return '—';
        return result.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' tok/s';
    }

    function formatGb(value) {
        const result = number(value);
        if (result == null) return '—';
        return result.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' GB';
    }

    function formatPercent(value) {
        const result = number(value);
        if (result == null) return '—';
        return result.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' %';
    }

    function statusText(status) {
        const value = String(status || 'unknown').toLowerCase();
        return t(value) || value;
    }

    function stateText(state) {
        const value = String(state || 'unavailable').toLowerCase();
        return t(value) || value;
    }

    async function loadCopy() {
        copy = { ...FALLBACK };
        try {
            const response = await fetch(
                '/i18n/performance-observatory.' + locale() + '.json',
                { cache: 'no-store' }
            );
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_error) {}
    }

    function installCss() {
        if (document.getElementById(CSS_ID)) return;
        const link = document.createElement('link');
        link.id = CSS_ID;
        link.rel = 'stylesheet';
        link.href = '/assets/chat/performance-observatory.css?v=20260930-performance-v2';
        document.head.appendChild(link);
    }

    async function requestSnapshot() {
        const response = await fetch(API_URL, { cache: 'no-store' });
        if (!response.ok) {
            let detail = await response.text();
            try {
                detail = JSON.parse(detail)?.detail || detail;
            } catch (_error) {}
            throw new Error(detail || ('HTTP ' + response.status));
        }
        return await response.json();
    }

    function metricValue(metric, formatter) {
        if (!metric || Number(metric.count || 0) === 0) return '—';
        return formatter(metric.p50 ?? metric.average ?? metric.latest);
    }

    function metricDetail(metric, formatter) {
        const count = Number(metric?.count || 0);
        if (!count) return t('no_data');
        const parts = [t('samples', { count })];
        if (metric?.p95 != null) parts.push(t('p95') + ' ' + formatter(metric.p95));
        return parts.join(' · ');
    }

    function videoMetricDetail(summary) {
        const metric = summary?.generation_ms || {};
        const parts = [metricDetail(metric, formatDuration)];
        const warm = Number(summary?.warm_starts || 0);
        const cold = Number(summary?.cold_starts || 0);
        if (warm || cold) {
            parts.push(t('warm') + ' ' + warm + ' · ' + t('cold') + ' ' + cold);
        }
        return parts.join(' · ');
    }

    function kpiCard(label, value, detail, className = '') {
        const card = el('article', 'performance-observatory-kpi ' + className);
        card.append(
            el('span', 'performance-observatory-kpi-label', label),
            el('strong', 'performance-observatory-kpi-value', value),
            el('span', 'performance-observatory-kpi-detail', detail)
        );
        return card;
    }

    function renderKpis(snapshot) {
        const target = root.querySelector('[data-performance-kpis]');
        const model = snapshot?.model?.summary || {};
        const media = snapshot?.media?.summary || {};
        const memory = snapshot?.system?.memory || {};
        const imageMetric = media?.image?.generation_ms || {};
        const videoMetric = media?.video?.generation_ms || {};

        target.replaceChildren(
            kpiCard(
                t('ttft'),
                metricValue(model.ttft_ms, formatDuration),
                metricDetail(model.ttft_ms, formatDuration),
                'metric-chat'
            ),
            kpiCard(
                t('tokens_per_second'),
                metricValue(model.tokens_per_second, formatRate),
                metricDetail(model.tokens_per_second, formatRate),
                'metric-chat'
            ),
            kpiCard(
                t('image_time'),
                imageMetric.count ? formatDuration(imageMetric.average) : '—',
                metricDetail(imageMetric, formatDuration),
                'metric-image'
            ),
            kpiCard(
                t('video_time'),
                videoMetric.count ? formatDuration(videoMetric.average) : '—',
                videoMetricDetail(media?.video),
                'metric-video'
            ),
            kpiCard(
                t('headroom'),
                formatGb(memory.headroom_gb),
                t('pressure') + ': ' + pressureText(memory.pressure),
                'metric-memory'
            ),
            kpiCard(
                t('swap'),
                formatGb(memory.swap_used_gb),
                memory.swap_total_gb != null ? '/ ' + formatGb(memory.swap_total_gb) : t('no_data'),
                'metric-memory'
            )
        );
    }

    function pressureText(pressure) {
        const value = String(pressure || 'unknown').toLowerCase();
        return t('pressure_' + value) || value;
    }

    function runtimeCard(name, runtime) {
        runtime = runtime || {};
        const state = String(runtime.state || 'unavailable').toLowerCase();
        const card = el('article', 'performance-observatory-runtime state-' + state);
        const header = el('div', 'performance-observatory-runtime-header');
        header.append(
            el('strong', '', name),
            el('span', 'performance-observatory-state', stateText(state))
        );
        card.append(header);
        card.append(el(
            'span',
            'performance-observatory-runtime-model',
            runtime.model || '—'
        ));
        card.append(el(
            'span',
            'performance-observatory-runtime-activity',
            runtime.active ? t('active') : t('idle')
        ));
        return card;
    }

    function memoryField(label, value) {
        const item = el('div', 'performance-observatory-memory-item');
        item.append(
            el('span', '', label),
            el('strong', '', value)
        );
        return item;
    }

    function renderRuntimeAndMemory(snapshot) {
        const runtimes = snapshot?.system?.runtimes || {};
        const runtimeTarget = root.querySelector('[data-performance-runtimes]');
        runtimeTarget.replaceChildren(
            runtimeCard(t('chat'), runtimes.chat),
            runtimeCard(t('image'), runtimes.image),
            runtimeCard(t('video'), runtimes.video)
        );

        const memory = snapshot?.system?.memory || {};
        const memoryTarget = root.querySelector('[data-performance-memory]');
        memoryTarget.replaceChildren(
            memoryField(t('pressure'), pressureText(memory.pressure)),
            memoryField(t('used'), formatGb(memory.used_estimate_gb)),
            memoryField(t('available'), formatGb(memory.available_estimate_gb)),
            memoryField(t('headroom'), formatGb(memory.headroom_gb)),
            memoryField(t('free'), formatPercent(memory.free_percent)),
            memoryField(t('reserve'), formatGb(memory.reserve_gb)),
            memoryField(t('swap'), formatGb(memory.swap_used_gb))
        );
    }

    function tableHeader(labels) {
        const row = el('tr');
        labels.forEach(label => row.appendChild(el('th', '', label)));
        return row;
    }

    function tableCell(value, className = '') {
        return el('td', className, value ?? '—');
    }

    function renderModelCalls(snapshot) {
        const table = root.querySelector('[data-performance-model-table]');
        const calls = Array.isArray(snapshot?.model?.recent_calls)
            ? snapshot.model.recent_calls
            : [];
        const head = el('thead');
        head.appendChild(tableHeader([
            t('purpose'), t('model'), t('ttft'), t('tokens_per_second'), t('total'), t('status')
        ]));
        const body = el('tbody');

        for (const call of calls.slice(0, 20)) {
            const row = el('tr');
            const usageMethod = call?.usage?.count_method;
            const rate = call?.tokens_per_second == null
                ? '—'
                : formatRate(call.tokens_per_second) + (
                    usageMethod ? ' · ' + t(usageMethod) : ''
                );
            row.append(
                tableCell(call?.purpose || '—', 'performance-observatory-purpose'),
                tableCell(call?.model?.identifier || call?.model?.role || '—'),
                tableCell(formatDuration(call?.timings_ms?.ttft)),
                tableCell(rate),
                tableCell(formatDuration(call?.timings_ms?.total)),
                tableCell(statusText(call?.status), 'status-' + String(call?.status || 'unknown'))
            );
            body.appendChild(row);
        }

        if (!calls.length) {
            const row = el('tr');
            const cell = tableCell(t('no_data'), 'performance-observatory-empty');
            cell.colSpan = 6;
            row.appendChild(cell);
            body.appendChild(row);
        }
        table.replaceChildren(head, body);
    }

    function renderMediaJobs(snapshot) {
        const table = root.querySelector('[data-performance-media-table]');
        const jobs = Array.isArray(snapshot?.media?.recent_jobs)
            ? snapshot.media.recent_jobs
            : [];
        const head = el('thead');
        head.appendChild(tableHeader([
            t('kind'), t('model'), t('runtime_start'), t('queue'), t('generation'), t('total'), t('status')
        ]));
        const body = el('tbody');

        for (const job of jobs.slice(0, 20)) {
            const row = el('tr');
            row.append(
                tableCell(t(job?.kind) || job?.kind || '—'),
                tableCell(job?.model || '—'),
                tableCell(job?.runtime_start ? stateText(job.runtime_start) : '—'),
                tableCell(formatDuration(job?.queue_wait_ms)),
                tableCell(formatDuration(job?.generation_ms)),
                tableCell(formatDuration(job?.total_ms)),
                tableCell(statusText(job?.status), 'status-' + String(job?.status || 'unknown'))
            );
            body.appendChild(row);
        }

        if (!jobs.length) {
            const row = el('tr');
            const cell = tableCell(t('no_data'), 'performance-observatory-empty');
            cell.colSpan = 7;
            row.appendChild(cell);
            body.appendChild(row);
        }
        table.replaceChildren(head, body);
    }

    function render(snapshot) {
        renderKpis(snapshot);
        renderRuntimeAndMemory(snapshot);
        renderModelCalls(snapshot);
        renderMediaJobs(snapshot);
        const checked = root.querySelector('[data-performance-checked]');
        checked.textContent = t('checked', {
            time: new Date((snapshot?.captured_at || Date.now() / 1000) * 1000)
                .toLocaleTimeString()
        });
        setNotice('');
    }

    function setNotice(message, kind = '') {
        const notice = root?.querySelector('[data-performance-notice]');
        if (!notice) return;
        notice.textContent = message || '';
        notice.hidden = !message;
        notice.className = 'performance-observatory-notice' + (kind ? ' ' + kind : '');
    }

    async function refresh() {
        if (!root || busy) return;
        busy = true;
        const button = root.querySelector('[data-performance-refresh]');
        if (button) button.disabled = true;
        try {
            render(await requestSnapshot());
        } catch (error) {
            setNotice(t('request_failed', { message: error.message }), 'error');
        } finally {
            busy = false;
            if (button) button.disabled = false;
        }
    }

    function sectionBlock(title, className = '') {
        const section = el('section', 'performance-observatory-block ' + className);
        section.appendChild(el('h4', '', title));
        return section;
    }

    function buildRoot() {
        const section = el('section', 'performance-observatory-v2');
        section.id = 'performanceObservatoryV2';

        const header = el('div', 'performance-observatory-heading');
        const text = el('div');
        text.append(
            el('h3', '', t('title')),
            el('p', 'performance-observatory-muted', t('subtitle'))
        );
        const refreshButton = el('button', 'message-action-btn', t('refresh'));
        refreshButton.type = 'button';
        refreshButton.dataset.performanceRefresh = '1';
        refreshButton.addEventListener('click', refresh);
        header.append(text, refreshButton);

        const notice = el('div', 'performance-observatory-notice', t('loading'));
        notice.dataset.performanceNotice = '1';

        const kpis = el('div', 'performance-observatory-kpis');
        kpis.dataset.performanceKpis = '1';

        const live = el('div', 'performance-observatory-live-grid');
        const runtimeBlock = sectionBlock(t('runtime_title'));
        const runtimes = el('div', 'performance-observatory-runtimes');
        runtimes.dataset.performanceRuntimes = '1';
        runtimeBlock.appendChild(runtimes);
        const memoryBlock = sectionBlock(t('memory_title'));
        const memory = el('div', 'performance-observatory-memory');
        memory.dataset.performanceMemory = '1';
        memoryBlock.appendChild(memory);
        live.append(runtimeBlock, memoryBlock);

        const modelBlock = sectionBlock(t('model_calls_title'), 'performance-observatory-table-block');
        const modelWrap = el('div', 'performance-observatory-table-wrap');
        const modelTable = el('table', 'performance-observatory-table');
        modelTable.dataset.performanceModelTable = '1';
        modelWrap.appendChild(modelTable);
        modelBlock.appendChild(modelWrap);

        const mediaBlock = sectionBlock(t('media_jobs_title'), 'performance-observatory-table-block');
        const mediaWrap = el('div', 'performance-observatory-table-wrap');
        const mediaTable = el('table', 'performance-observatory-table');
        mediaTable.dataset.performanceMediaTable = '1';
        mediaWrap.appendChild(mediaTable);
        mediaBlock.appendChild(mediaWrap);

        const footer = el('div', 'performance-observatory-footer');
        footer.append(
            el('span', 'performance-observatory-muted', t('live_note')),
            el('span', 'performance-observatory-checked', '')
        );
        footer.lastChild.dataset.performanceChecked = '1';

        section.append(header, notice, kpis, live, modelBlock, mediaBlock, footer);
        return section;
    }

    async function mount() {
        if (root || document.getElementById('performanceObservatoryV2')) return true;
        const legacyGrid = document.getElementById('serviceHealthGrid');
        if (!legacyGrid?.parentElement) {
            mountAttempts += 1;
            if (mountAttempts < MOUNT_RETRY_LIMIT) {
                setTimeout(mount, MOUNT_RETRY_MS);
            }
            return false;
        }

        await loadCopy();
        installCss();
        root = buildRoot();
        const health = document.getElementById('systemHealthV1');
        legacyGrid.parentElement.insertBefore(root, health || legacyGrid);
        observeVisibility();
        await refreshIfVisible();
        refreshTimer = setInterval(refreshIfVisible, REFRESH_MS);
        return true;
    }

    window.MLXPerformanceObservatory = {
        refresh,
        __test: {
            formatDuration,
            formatRate,
            formatGb,
            metricValue,
            pressureText,
            stateText,
            statusText
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
        mount();
    }

    window.addEventListener?.('beforeunload', () => {
        if (refreshTimer != null) clearInterval(refreshTimer);
        visibilityObserver?.disconnect();
        document.removeEventListener('visibilitychange', refreshIfVisible);
    });
})();
