(function () {
    'use strict';

    if (window.__mlxRuntimeReliabilityLoaded) return;
    window.__mlxRuntimeReliabilityLoaded = true;

    const DELAY_NOTICE_MS = 8000;
    const DIAGNOSTICS_REFRESH_MS = 3000;
    const originalFetch = window.fetch.bind(window);
    let activeMonitor = null;
    let refreshTimer = null;
    let refreshing = false;

    function language() {
        return window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    }

    function t(german, english) {
        return language() === 'de' ? german : english;
    }

    function requestUrl(input) {
        try {
            if (input instanceof Request) return new URL(input.url, window.location.href);
            return new URL(String(input), window.location.href);
        } catch (_) {
            return null;
        }
    }

    function isChatStreamRequest(input, init) {
        const url = requestUrl(input);
        if (!url || url.origin !== window.location.origin) return false;
        const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        return method === 'POST' && url.pathname === '/api/chat/stream';
    }

    function reliableInput(input) {
        const url = requestUrl(input);
        if (!url) return input;
        url.pathname = '/api/chat/reliable-stream';

        if (input instanceof Request) {
            return new Request(url.toString(), input);
        }

        if (typeof input === 'string' && input.startsWith('/')) {
            return url.pathname + url.search + url.hash;
        }
        return url.toString();
    }

    function injectStyles() {
        if (document.getElementById('mlxRuntimeReliabilityStyles')) return;
        const style = document.createElement('style');
        style.id = 'mlxRuntimeReliabilityStyles';
        style.textContent = `
            .mlx-chat-reliability-status{
                position:fixed;z-index:1300;max-width:min(520px,calc(100vw - 24px));
                padding:7px 11px;border:1px solid var(--border);border-radius:10px;
                background:color-mix(in srgb,var(--panel) 94%,transparent);color:var(--muted);
                box-shadow:0 8px 28px rgba(0,0,0,.18);backdrop-filter:blur(14px);
                font-size:11px;line-height:1.35;pointer-events:none;transform:translate(-50%,-100%);
            }
            .mlx-chat-reliability-status[hidden]{display:none!important}
            #mlxRuntimeReliability{margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}
            .runtime-reliability-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
            .runtime-reliability-title{color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
            .runtime-reliability-state{font-size:10px;font-weight:700;padding:3px 7px;border:1px solid var(--border);border-radius:999px;color:var(--green)}
            .runtime-reliability-state[data-state="busy"]{color:#e0a84f}
            .runtime-reliability-state[data-state="offline"]{color:var(--red)}
            .runtime-reliability-grid{display:grid;grid-template-columns:1fr auto;gap:5px 12px;color:var(--muted);font-size:12px}
            .runtime-reliability-grid strong{color:var(--text);font-weight:600;text-align:right;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
            .runtime-reliability-hint{margin-top:9px;color:var(--muted);font-size:10px;line-height:1.45}
        `;
        document.head.appendChild(style);
    }

    function ensureStatusNode() {
        let node = document.getElementById('mlxChatReliabilityStatus');
        if (node) return node;
        node = document.createElement('div');
        node.id = 'mlxChatReliabilityStatus';
        node.className = 'mlx-chat-reliability-status';
        node.setAttribute('role', 'status');
        node.setAttribute('aria-live', 'polite');
        node.hidden = true;
        document.body.appendChild(node);
        return node;
    }

    function positionStatus(node) {
        const composer = document.querySelector('.composer');
        if (!node || !composer || node.hidden) return;
        const rect = composer.getBoundingClientRect();
        node.style.left = `${Math.round(rect.left + rect.width / 2)}px`;
        node.style.top = `${Math.max(12, Math.round(rect.top - 10))}px`;
    }

    function showStatus(text) {
        const node = ensureStatusNode();
        node.textContent = text;
        node.hidden = false;
        positionStatus(node);
    }

    function hideStatus() {
        const node = document.getElementById('mlxChatReliabilityStatus');
        if (node) node.hidden = true;
    }

    function ensureRuntimeSection() {
        const popover = document.getElementById('runtimePopover');
        if (!popover) return null;
        let section = document.getElementById('mlxRuntimeReliability');
        if (section) return section;
        section = document.createElement('section');
        section.id = 'mlxRuntimeReliability';
        section.setAttribute('aria-live', 'polite');
        popover.appendChild(section);
        return section;
    }

    function seconds(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return '–';
        if (number < 1) return `${Math.round(number * 1000)} ms`;
        return `${number.toFixed(number < 10 ? 1 : 0)} s`;
    }

    function workloadLabel(value) {
        const labels = {
            chat: t('Chat', 'Chat'),
            image: t('Bild', 'Image'),
            video: t('Video', 'Video'),
            runtime: t('Runtime', 'Runtime')
        };
        return labels[value] || t('Leerlauf', 'Idle');
    }

    function renderDiagnostics(section, data) {
        if (!section) return;
        const runtime = data?.runtime || {};
        const lease = data?.lease || {};
        const recovery = data?.recovery || {};
        const workload = lease.active_workload || null;
        const online = runtime.online !== false && data?.status !== 'unavailable';
        const state = !online ? 'offline' : workload ? 'busy' : 'ready';
        const stateLabel = !online
            ? t('Offline', 'Offline')
            : workload
                ? t('Beschäftigt', 'Busy')
                : t('Bereit', 'Ready');
        const lastRecovery = recovery.last_recovery_at
            ? new Date(Number(recovery.last_recovery_at) * 1000).toLocaleTimeString(
                language() === 'de' ? 'de-DE' : 'en-US',
                { hour: '2-digit', minute: '2-digit', second: '2-digit' }
            )
            : t('keine', 'none');
        const model = String(runtime.model || '–').split('/').pop();

        section.innerHTML = `
            <div class="runtime-reliability-head">
                <div class="runtime-reliability-title">${t('Runtime-Stabilität', 'Runtime reliability')}</div>
                <div class="runtime-reliability-state" data-state="${state}">${stateLabel}</div>
            </div>
            <div class="runtime-reliability-grid">
                <span>${t('Agent', 'Agent')}</span><strong>PID ${data?.agent_pid ?? '–'}</strong>
                <span>${t('Chat-Modell', 'Chat model')}</span><strong title="${model}">${model}</strong>
                <span>${t('Aktive Last', 'Active workload')}</span><strong>${workloadLabel(workload)}</strong>
                <span>${t('Lease-Alter', 'Lease age')}</span><strong>${workload ? seconds(lease.active_age_seconds) : '–'}</strong>
                <span>${t('Wartende Jobs', 'Waiting jobs')}</span><strong>${Number(lease.waiting_count || 0)}</strong>
                <span>${t('Letzte Recovery', 'Last recovery')}</span><strong>${lastRecovery}</strong>
            </div>
            <div class="runtime-reliability-hint">${
                workload === 'image' || workload === 'video'
                    ? t('Chat-Anfragen warten automatisch, bis die schwere Media-Runtime frei ist.', 'Chat requests automatically wait until the heavy media runtime is free.')
                    : t('Hängende Chat-Streams werden erkannt, einmal wiederhergestellt und automatisch erneut versucht.', 'Stalled chat streams are detected, recovered once, and retried automatically.')
            }</div>
        `;
    }

    async function fetchDiagnostics() {
        const response = await originalFetch('/api/mlx/runtime/reliability', {
            cache: 'no-store'
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    async function refreshDiagnostics() {
        const popover = document.getElementById('runtimePopover');
        const section = ensureRuntimeSection();
        if (!section || refreshing) return null;
        if (popover?.hidden && !activeMonitor?.delayed) return null;

        refreshing = true;
        try {
            const data = await fetchDiagnostics();
            renderDiagnostics(section, data);
            return data;
        } catch (_) {
            if (!popover?.hidden) {
                section.innerHTML = `
                    <div class="runtime-reliability-title">${t('Runtime-Stabilität', 'Runtime reliability')}</div>
                    <div class="runtime-reliability-hint">${t('Diagnosedaten sind momentan nicht erreichbar.', 'Diagnostics are currently unavailable.')}</div>
                `;
            }
            return null;
        } finally {
            refreshing = false;
        }
    }

    function delayedCopy(data) {
        const workload = data?.lease?.active_workload;
        if (workload === 'video') {
            return t('Video-Runtime läuft – der Chat wartet kurz …', 'Video runtime is active — chat is waiting …');
        }
        if (workload === 'image') {
            return t('Bild-Runtime läuft – der Chat wartet kurz …', 'Image runtime is active — chat is waiting …');
        }
        if (workload === 'chat') {
            return t('Antwort verzögert sich – Chat-Runtime wird überwacht …', 'Response is delayed — monitoring chat runtime …');
        }
        if (Number(data?.lease?.waiting_count || 0) > 0) {
            return t('Antwort verzögert sich – Runtime-Warteschlange aktiv …', 'Response is delayed — runtime queue is active …');
        }
        return t('Antwort verzögert sich – automatische Prüfung läuft …', 'Response is delayed — running automatic checks …');
    }

    async function updateDelayedStatus(monitor) {
        if (!monitor || monitor.finished || !monitor.delayed) return;
        const data = await refreshDiagnostics();
        if (monitor.finished) return;
        showStatus(delayedCopy(data));
    }

    function startMonitor() {
        if (activeMonitor) finishMonitor(activeMonitor);
        const monitor = {
            delayed: false,
            finished: false,
            timer: null,
            pollTimer: null,
            startedAt: performance.now()
        };
        activeMonitor = monitor;
        monitor.timer = window.setTimeout(() => {
            if (monitor.finished) return;
            monitor.delayed = true;
            showStatus(t('Antwort verzögert sich – automatische Prüfung läuft …', 'Response is delayed — running automatic checks …'));
            document.dispatchEvent(new CustomEvent('mlx:chat-stream-delayed'));
            updateDelayedStatus(monitor);
            monitor.pollTimer = window.setInterval(
                () => updateDelayedStatus(monitor),
                DIAGNOSTICS_REFRESH_MS
            );
        }, DELAY_NOTICE_MS);
        return monitor;
    }

    function firstChunk(monitor) {
        if (!monitor || monitor.finished) return;
        if (monitor.delayed) {
            document.dispatchEvent(new CustomEvent('mlx:chat-stream-recovered', {
                detail: { delay_ms: Math.round(performance.now() - monitor.startedAt) }
            }));
        }
        monitor.delayed = false;
        hideStatus();
        if (monitor.timer !== null) {
            clearTimeout(monitor.timer);
            monitor.timer = null;
        }
        if (monitor.pollTimer !== null) {
            clearInterval(monitor.pollTimer);
            monitor.pollTimer = null;
        }
    }

    function finishMonitor(monitor) {
        if (!monitor || monitor.finished) return;
        monitor.finished = true;
        firstChunk(monitor);
        hideStatus();
        if (activeMonitor === monitor) activeMonitor = null;
    }

    function instrumentResponse(response, monitor) {
        if (!response.body?.getReader || !window.ReadableStream) {
            finishMonitor(monitor);
            return response;
        }

        const reader = response.body.getReader();
        let seenChunk = false;
        const body = new ReadableStream({
            async pull(controller) {
                try {
                    const { value, done } = await reader.read();
                    if (done) {
                        finishMonitor(monitor);
                        controller.close();
                        return;
                    }
                    if (!seenChunk) {
                        seenChunk = true;
                        firstChunk(monitor);
                    }
                    controller.enqueue(value);
                } catch (error) {
                    finishMonitor(monitor);
                    controller.error(error);
                }
            },
            cancel(reason) {
                finishMonitor(monitor);
                return reader.cancel(reason);
            }
        });

        return new Response(body, {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers
        });
    }

    window.fetch = async function mlxReliableFetch(input, init) {
        if (!isChatStreamRequest(input, init)) {
            return originalFetch(input, init);
        }

        const monitor = startMonitor();
        try {
            const response = await originalFetch(reliableInput(input), init);
            if (!response.ok) finishMonitor(monitor);
            return instrumentResponse(response, monitor);
        } catch (error) {
            finishMonitor(monitor);
            throw error;
        }
    };

    function start() {
        injectStyles();
        ensureStatusNode();
        ensureRuntimeSection();

        window.addEventListener('resize', () => {
            positionStatus(document.getElementById('mlxChatReliabilityStatus'));
        });
        window.addEventListener('scroll', () => {
            positionStatus(document.getElementById('mlxChatReliabilityStatus'));
        }, true);

        document.getElementById('runtimeInfoButton')?.addEventListener('click', () => {
            window.setTimeout(refreshDiagnostics, 0);
        });
        document.addEventListener('mlx-language-changed', refreshDiagnostics);
        document.addEventListener('mlx-i18n-ready', refreshDiagnostics);

        if (refreshTimer !== null) clearInterval(refreshTimer);
        refreshTimer = window.setInterval(refreshDiagnostics, DIAGNOSTICS_REFRESH_MS);
    }

    window.MLXRuntimeReliability = {
        refresh: refreshDiagnostics,
        fetchDiagnostics,
        isChatStreamRequest,
        reliableInput,
        originalFetch
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
