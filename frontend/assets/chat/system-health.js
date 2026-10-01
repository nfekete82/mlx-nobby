'use strict';

(() => {
    const REFRESH_MS = 10000;
    const CSS_ID = 'mlx-system-health-css';
    const API_ROOT = '/api/mlx/system';
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

    const FALLBACK = {
        title: 'System Health & Self-Healing',
        subtitle: 'Live status of local MLX Nobby services and media jobs.',
        refresh: 'Refresh',
        self_heal: 'Self-heal',
        copy_diagnosis: 'Copy diagnosis',
        copied: 'Diagnosis copied.',
        healthy: 'Healthy',
        degraded: 'Degraded',
        down: 'Down',
        services_ok: '{healthy}/{total} services healthy',
        tracked_memory: 'Tracked RAM: {value}',
        media_jobs: 'Media jobs: {active} active · {waiting} waiting',
        port: 'Port',
        pid: 'PID',
        uptime: 'Uptime',
        memory: 'RAM',
        model: 'Model',
        active_job: 'Active job',
        latency: 'Latency',
        last_error: 'Last error',
        restart: 'Restart',
        restarting: 'Restarting …',
        restart_confirm_title: 'Restart service',
        restart_confirm: 'Restart {name}? Active work in this service may be interrupted.',
        restart_failed: 'Restart failed: {message}',
        self_heal_confirm_title: 'Run self-healing',
        self_heal_confirm: 'Restart unhealthy services and retry media jobs that have made no progress for the configured timeout?',
        self_healing: 'Self-healing is running …',
        self_heal_done: 'Self-healing complete: {services} service restart(s), {jobs} job retry/retries.',
        self_heal_failed: 'Self-healing failed: {message}',
        stuck_title: 'Stuck media jobs',
        stuck_none: 'No stuck media jobs detected.',
        stuck_job: '{kind} · no progress for {duration}',
        no_model: '—',
        unavailable: 'Unavailable',
        never: '—',
        checked: 'Last checked: {time}',
        loading: 'Checking services …',
        request_failed: 'System health could not be loaded: {message}',
        diagnosis_title: 'MLX Nobby system diagnosis',
        service_restarted: '{name} restart requested.',
        seconds: '{value}s',
        minutes: '{value}m',
        hours: '{value}h',
        days: '{value}d'
    };

    let dictionary = {};
    let root = null;
    let lastSnapshot = null;
    let busy = false;
    let timerId = null;

    function t(key, variables = {}) {
        let value = dictionary[key] || FALLBACK[key] || key;
        for (const [name, replacement] of Object.entries(variables)) {
            value = value.replaceAll(
                '{' + name + '}',
                String(replacement ?? '')
            );
        }
        return value;
    }

    function formatBytes(value) {
        const number = Number(value);
        if (!Number.isFinite(number) || number < 0) return '—';
        if (number < 1024) return Math.round(number) + ' B';
        const units = ['KB', 'MB', 'GB', 'TB'];
        let current = number / 1024;
        let unit = units[0];
        for (let index = 1; index < units.length && current >= 1024; index += 1) {
            current /= 1024;
            unit = units[index];
        }
        return current.toLocaleString(undefined, {
            maximumFractionDigits: current >= 100 ? 0 : 1
        }) + ' ' + unit;
    }

    function formatDuration(value) {
        let seconds = Math.max(0, Math.floor(Number(value) || 0));
        if (seconds < 60) return t('seconds', { value: seconds });
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return t('minutes', { value: minutes });
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return t('hours', { value: hours });
        return t('days', { value: Math.floor(hours / 24) });
    }

    function statusLabel(status) {
        return t(
            status === 'healthy'
                ? 'healthy'
                : status === 'degraded'
                    ? 'degraded'
                    : 'down'
        );
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function field(label, value) {
        const row = el('div', 'system-health-field');
        row.append(
            el('span', 'system-health-field-label', label),
            el('strong', 'system-health-field-value', value ?? '—')
        );
        return row;
    }

    async function request(path, options = {}) {
        const response = await fetch(API_ROOT + path, {
            cache: 'no-store',
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {})
            }
        });
        if (!response.ok) {
            let detail = await response.text();
            try {
                const parsed = JSON.parse(detail);
                detail = parsed.detail || detail;
            } catch (_error) {}
            throw new Error(detail || ('HTTP ' + response.status));
        }
        return await response.json();
    }

    function diagnosisText(snapshot) {
        const services = Array.isArray(snapshot?.services)
            ? snapshot.services
            : [];
        const stuck = Array.isArray(snapshot?.stuck_jobs)
            ? snapshot.stuck_jobs
            : [];
        const lines = [
            t('diagnosis_title'),
            new Date((snapshot?.checked_at || Date.now() / 1000) * 1000).toISOString(),
            '',
            ...services.map(service => [
                service.name,
                service.status,
                'port=' + service.port,
                'pid=' + (service.pid ?? '—'),
                'rss=' + formatBytes(service.rss_bytes),
                'uptime=' + formatDuration(service.uptime_seconds),
                'model=' + (service.current_model || '—'),
                'job=' + (service.active_job_id || '—'),
                'latency=' + (service.latency_ms == null ? '—' : service.latency_ms + 'ms'),
                'error=' + (service.last_error || service.detail || '—')
            ].join(' | ')),
            '',
            'stuck_jobs=' + stuck.length,
            ...stuck.map(job => [
                job.kind,
                job.id,
                job.phase || job.status,
                'idle=' + formatDuration(job.idle_seconds),
                'progress=' + (job.progress ?? '—'),
                'step=' + (job.current_step ?? '—') + '/' + (job.total_steps ?? '—')
            ].join(' | '))
        ];
        return lines.join('\n');
    }

    function setNotice(message, kind = '') {
        const notice = root?.querySelector('[data-system-health-notice]');
        if (!notice) return;
        notice.textContent = message || '';
        notice.className = 'system-health-notice' + (kind ? ' ' + kind : '');
        notice.hidden = !message;
    }

    async function confirmAction(title, message, confirmLabel) {
        if (typeof window.MLXConfirm === 'function') {
            return await window.MLXConfirm({
                title,
                message,
                confirmLabel,
                cancelLabel: 'Cancel'
            });
        }
        return globalThis.confirm?.(message) ?? true;
    }

    function applyJobRetries(retries) {
        const session = window.MLXChatSessions?.currentSession?.();
        const generation = window.MLXChatGeneration;
        if (!session || !generation || !Array.isArray(retries)) return;

        let changed = false;
        for (const retry of retries) {
            const message = (session.messages || []).find(item =>
                item?.image_job?.id === retry.old_id ||
                item?.video_job?.id === retry.old_id
            );
            if (!message || !retry?.job) continue;

            const result = {
                type: 'tool_result',
                tool: message.tool_result?.tool ||
                    (retry.kind === 'video' ? 'video_generate' : 'image_generate'),
                status: retry.job.status || 'queued',
                data: { job: retry.job },
                artifacts: [],
                error: null
            };

            if (retry.kind === 'video') {
                generation.updateVideoJobMessage?.(session, message, result);
            } else {
                generation.updateImageJobMessage?.(session, message, result);
            }
            changed = true;
        }

        if (!changed) return;
        window.MLXChatSessions?.saveSessions?.();
        window.MLXChatRendering?.renderAll?.({ contentUpdated: true });
        generation.resumeImageJobsForSession?.(session);
        generation.resumeVideoJobsForSession?.(session);
    }

    async function restartService(service) {
        const confirmed = await confirmAction(
            t('restart_confirm_title'),
            t('restart_confirm', { name: service.name }),
            t('restart')
        );
        if (!confirmed) return;

        setNotice(t('restarting'), 'busy');
        try {
            await request(
                '/services/' + encodeURIComponent(service.id) + '/restart',
                { method: 'POST', body: '{}' }
            );
            setNotice(t('service_restarted', { name: service.name }), 'ok');
            setTimeout(refresh, 1400);
        } catch (error) {
            setNotice(t('restart_failed', { message: error.message }), 'error');
        }
    }

    async function runSelfHeal() {
        const confirmed = await confirmAction(
            t('self_heal_confirm_title'),
            t('self_heal_confirm'),
            t('self_heal')
        );
        if (!confirmed) return;

        setNotice(t('self_healing'), 'busy');
        try {
            const result = await request('/self-heal', {
                method: 'POST',
                body: '{}'
            });
            applyJobRetries(result.job_retries || []);
            setNotice(t('self_heal_done', {
                services: (result.restarted_services || []).length,
                jobs: (result.job_retries || []).length
            }), result.failed_restarts?.length ? 'error' : 'ok');
            setTimeout(refresh, 1400);
        } catch (error) {
            setNotice(t('self_heal_failed', { message: error.message }), 'error');
        }
    }

    async function copyDiagnosis() {
        if (!lastSnapshot) return;
        const text = diagnosisText(lastSnapshot);
        try {
            await navigator.clipboard.writeText(text);
            setNotice(t('copied'), 'ok');
        } catch (_error) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.className = 'system-health-copy-fallback';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand?.('copy');
            textarea.remove();
            setNotice(t('copied'), 'ok');
        }
    }

    function renderService(service) {
        const card = el(
            'article',
            'system-health-service status-' + String(service.status || 'down')
        );
        const header = el('div', 'system-health-service-header');
        const title = el('div', 'system-health-service-title');
        title.append(
            el('strong', '', service.name),
            el('span', 'system-health-port', ':' + service.port)
        );
        header.append(
            title,
            el('span', 'system-health-badge', statusLabel(service.status))
        );
        card.appendChild(header);

        const fields = el('div', 'system-health-fields');
        fields.append(
            field(t('pid'), service.pid ?? '—'),
            field(t('uptime'), service.uptime_seconds == null ? '—' : formatDuration(service.uptime_seconds)),
            field(t('memory'), formatBytes(service.rss_bytes)),
            field(t('latency'), service.latency_ms == null ? '—' : service.latency_ms + ' ms'),
            field(t('model'), service.current_model || t('no_model')),
            field(t('active_job'), service.active_job_id || '—')
        );
        card.appendChild(fields);

        const errorText = service.last_error || service.detail;
        if (errorText) {
            const details = el('details', 'system-health-error-details');
            details.append(
                el('summary', '', t('last_error')),
                el('pre', '', errorText)
            );
            card.appendChild(details);
        }

        if (service.restartable) {
            const actions = el('div', 'system-health-card-actions');
            const restart = el('button', 'message-action-btn', t('restart'));
            restart.type = 'button';
            restart.addEventListener('click', () => restartService(service));
            actions.appendChild(restart);
            card.appendChild(actions);
        }
        return card;
    }

    function renderStuckJobs(jobs) {
        const section = root.querySelector('[data-system-health-stuck]');
        section.replaceChildren();
        section.appendChild(el('h4', '', t('stuck_title')));

        if (!jobs.length) {
            section.appendChild(el('p', 'system-health-muted', t('stuck_none')));
            return;
        }

        for (const job of jobs) {
            const item = el('div', 'system-health-stuck-item');
            item.append(
                el('strong', '', job.title || job.id),
                el('span', '', t('stuck_job', {
                    kind: job.kind || 'media',
                    duration: formatDuration(job.idle_seconds)
                }))
            );
            section.appendChild(item);
        }
    }

    function render(snapshot) {
        lastSnapshot = snapshot;
        const summary = snapshot.summary || {};
        const summaryNode = root.querySelector('[data-system-health-summary]');
        summaryNode.replaceChildren(
            el('strong', '', t('services_ok', {
                healthy: summary.healthy ?? 0,
                total: summary.total ?? 0
            })),
            el('span', '', t('tracked_memory', {
                value: formatBytes(summary.tracked_rss_bytes)
            })),
            el('span', '', t('media_jobs', {
                active: summary.active_media_jobs ?? 0,
                waiting: summary.waiting_media_jobs ?? 0
            }))
        );

        const grid = root.querySelector('[data-system-health-services]');
        grid.replaceChildren(...(snapshot.services || []).map(renderService));
        renderStuckJobs(snapshot.stuck_jobs || []);

        const checked = root.querySelector('[data-system-health-checked]');
        checked.textContent = t('checked', {
            time: new Date((snapshot.checked_at || Date.now() / 1000) * 1000)
                .toLocaleTimeString()
        });
    }

    async function refresh() {
        if (!root || busy) return;
        busy = true;
        const refreshButton = root.querySelector('[data-system-health-refresh]');
        if (refreshButton) refreshButton.disabled = true;

        try {
            const snapshot = await request('/health-v1');
            render(snapshot);
        } catch (error) {
            setNotice(t('request_failed', { message: error.message }), 'error');
        } finally {
            busy = false;
            if (refreshButton) refreshButton.disabled = false;
        }
    }

    function buildRoot() {
        const section = el('section', 'system-health-v1');
        section.id = 'systemHealthV1';

        const heading = el('div', 'system-health-heading');
        const headingText = el('div');
        headingText.append(
            el('h3', '', t('title')),
            el('p', 'system-health-muted', t('subtitle'))
        );
        const actions = el('div', 'system-health-actions');
        const refreshButton = el('button', 'message-action-btn', t('refresh'));
        refreshButton.type = 'button';
        refreshButton.dataset.systemHealthRefresh = '1';
        refreshButton.addEventListener('click', refresh);
        const healButton = el('button', 'message-action-btn system-health-primary', t('self_heal'));
        healButton.type = 'button';
        healButton.addEventListener('click', runSelfHeal);
        const copyButton = el('button', 'message-action-btn', t('copy_diagnosis'));
        copyButton.type = 'button';
        copyButton.addEventListener('click', copyDiagnosis);
        actions.append(refreshButton, healButton, copyButton);
        heading.append(headingText, actions);

        const summary = el('div', 'system-health-summary');
        summary.dataset.systemHealthSummary = '1';
        summary.textContent = t('loading');

        const notice = el('div', 'system-health-notice');
        notice.dataset.systemHealthNotice = '1';
        notice.hidden = true;

        const services = el('div', 'system-health-services');
        services.dataset.systemHealthServices = '1';

        const stuck = el('div', 'system-health-stuck');
        stuck.dataset.systemHealthStuck = '1';

        const checked = el('div', 'system-health-checked');
        checked.dataset.systemHealthChecked = '1';

        section.append(heading, summary, notice, services, stuck, checked);
        return section;
    }

    function installCss() {
        if (document.getElementById(CSS_ID)) return;
        const link = document.createElement('link');
        link.id = CSS_ID;
        link.rel = 'stylesheet';
        link.href = '/assets/chat/system-health.css?v=20260929-system-health-v1';
        document.head.appendChild(link);
    }

    async function loadDictionary() {
        const locale = String(
            window.MLXI18n?.getLocale?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase();
        const language = locale.startsWith('de') ? 'de' : 'en';
        try {
            const response = await fetch(
                '/i18n/system-health.' + language + '.json',
                { cache: 'no-store' }
            );
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') dictionary = data;
            }
        } catch (_error) {}
    }

    async function mount() {
        const legacyGrid = document.getElementById('serviceHealthGrid');
        if (!legacyGrid || document.getElementById('systemHealthV1')) return;

        await loadDictionary();
        installCss();
        root = buildRoot();
        legacyGrid.hidden = true;
        legacyGrid.parentElement?.insertBefore(root, legacyGrid);

        document.getElementById('serviceHealthRefresh')?.addEventListener(
            'click',
            refresh
        );

        observeVisibility();
        await refreshIfVisible();
        timerId = setInterval(refreshIfVisible, REFRESH_MS);
    }

    window.MLXSystemHealth = {
        refresh,
        selfHeal: runSelfHeal,
        copyDiagnosis,
        __test: {
            diagnosisText,
            formatBytes,
            formatDuration,
            statusLabel
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
        mount();
    }

    window.addEventListener?.('beforeunload', () => {
        if (timerId != null) clearInterval(timerId);
        visibilityObserver?.disconnect();
        document.removeEventListener('visibilitychange', refreshIfVisible);
    });
})();
