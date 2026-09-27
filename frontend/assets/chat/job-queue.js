(function () {
    const panel = document.getElementById('jobsPanel');
    const content = document.getElementById('jobsPanelContent');
    const openButton = document.getElementById('sidebarJobsButton');
    const closeButton = document.getElementById('jobsPanelClose');

    if (!panel || !content || !openButton) return;

    const ACTIVE_STATES = new Set(['running', 'waiting']);
    let pollTimer = null;
    let refreshGeneration = 0;

    function t(german, english) {
        const language = String(
            window.MLXI18n?.getLanguage?.() || document.documentElement.lang || 'en'
        ).toLowerCase();
        return language.startsWith('de') ? german : english;
    }

    function ensureStyles() {
        if (document.getElementById('mlxUnifiedQueueStyles')) return;
        const style = document.createElement('style');
        style.id = 'mlxUnifiedQueueStyles';
        style.textContent = `
            .mlx-queue-summary{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
            .mlx-queue-pill{font-size:12px;padding:4px 8px;border:1px solid var(--border-color,#334155);border-radius:999px;opacity:.88}
            .mlx-queue-section{display:flex;align-items:center;justify-content:space-between;margin:14px 0 7px;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;opacity:.72}
            .mlx-queue-list{display:grid;gap:8px}
            .mlx-queue-item{display:grid;gap:5px;padding:10px 11px;border:1px solid var(--border-color,#334155);border-radius:10px;background:var(--panel-bg,#111821)}
            .mlx-queue-head{display:flex;align-items:center;gap:8px;min-width:0}
            .mlx-queue-icon{width:23px;flex:0 0 23px;text-align:center}
            .mlx-queue-title{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1}
            .mlx-queue-state{font-size:11px;opacity:.72;white-space:nowrap}
            .mlx-queue-meta{font-size:12px;opacity:.72;display:flex;gap:7px;flex-wrap:wrap}
            .mlx-queue-progress{height:4px;border-radius:999px;overflow:hidden;background:rgba(127,127,127,.18)}
            .mlx-queue-progress>span{display:block;height:100%;background:currentColor;opacity:.65;transition:width .2s ease}
            .mlx-queue-actions{display:flex;justify-content:flex-end}
            .mlx-queue-cancel{font:inherit;font-size:11px;padding:4px 8px;border-radius:7px;border:1px solid var(--border-color,#334155);background:transparent;color:inherit;cursor:pointer}
            .mlx-queue-cancel:hover{background:rgba(127,127,127,.12)}
            .mlx-queue-empty,.mlx-queue-error{font-size:13px;opacity:.72;padding:10px 2px}
        `;
        document.head.appendChild(style);
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function kindInfo(kind) {
        if (kind === 'image') return ['🖼', t('Bild', 'Image')];
        if (kind === 'video') return ['🎬', t('Video', 'Video')];
        if (kind === 'shorts') return ['📱', t('Short', 'Short')];
        return ['⚙', t('Auftrag', 'Job')];
    }

    function stateLabel(job) {
        const state = job.queue_status;
        if (state === 'waiting') {
            const position = Number(job.queue_position);
            return Number.isFinite(position) && position > 0
                ? t(`Wartet · #${position}`, `Waiting · #${position}`)
                : t('Wartet', 'Waiting');
        }
        if (state === 'running') {
            const phase = String(job.phase || '').replaceAll('_', ' ');
            return phase && phase !== 'running'
                ? phase
                : t('Läuft', 'Running');
        }
        if (state === 'completed') return t('Fertig', 'Completed');
        if (state === 'failed') return t('Fehler', 'Failed');
        if (state === 'cancelled') return t('Abgebrochen', 'Cancelled');
        return String(job.status || state || '—');
    }

    function progressValue(job) {
        const value = Number(job.progress);
        if (!Number.isFinite(value)) return null;
        return Math.max(0, Math.min(1, value));
    }

    async function cancelJob(job) {
        const confirmed = window.MLXConfirm
            ? await window.MLXConfirm({
                title: t('Auftrag abbrechen', 'Cancel job'),
                message: t('Möchtest du diesen Auftrag wirklich abbrechen?', 'Do you really want to cancel this job?'),
                confirmLabel: t('Abbrechen', 'Cancel job'),
                cancelLabel: t('Zurück', 'Back')
            })
            : window.confirm(t('Auftrag wirklich abbrechen?', 'Really cancel this job?'));
        if (!confirmed) return;

        const response = await fetch(
            '/api/system/job-queue/' +
            encodeURIComponent(job.kind) + '/' +
            encodeURIComponent(job.id) + '/cancel',
            { method: 'POST' }
        );
        if (!response.ok) {
            let detail = t('Abbruch fehlgeschlagen', 'Cancellation failed');
            try {
                const data = await response.json();
                detail = data.detail || detail;
            } catch (_error) {
                // Keep the compact fallback message.
            }
            throw new Error(detail);
        }
        await refresh();
    }

    function renderMedia(queue, root) {
        const summary = element('div', 'mlx-queue-summary');
        summary.appendChild(element('span', 'mlx-queue-pill', t(`${queue.active_count || 0} aktiv`, `${queue.active_count || 0} active`)));
        summary.appendChild(element('span', 'mlx-queue-pill', t(`${queue.waiting_count || 0} wartend`, `${queue.waiting_count || 0} waiting`)));
        root.appendChild(summary);

        const heading = element('div', 'mlx-queue-section');
        heading.appendChild(element('span', '', t('Medien-Queue', 'Media queue')));
        root.appendChild(heading);

        const jobs = Array.isArray(queue.jobs) ? queue.jobs : [];
        if (!jobs.length) {
            root.appendChild(element('div', 'mlx-queue-empty', t('Keine Medien-Aufträge.', 'No media jobs.')));
            return;
        }

        const list = element('div', 'mlx-queue-list');
        for (const job of jobs) {
            const item = element('div', 'mlx-queue-item');
            item.dataset.jobId = String(job.id || '');
            item.dataset.jobKind = String(job.kind || '');
            item.dataset.jobState = String(job.queue_status || '');

            const head = element('div', 'mlx-queue-head');
            const [icon, kindLabel] = kindInfo(job.kind);
            head.appendChild(element('span', 'mlx-queue-icon', icon));
            head.appendChild(element(
                'span',
                'mlx-queue-title',
                String(job.title || kindLabel)
            ));
            head.appendChild(element('span', 'mlx-queue-state', stateLabel(job)));
            item.appendChild(head);

            const meta = element('div', 'mlx-queue-meta');
            meta.appendChild(element('span', '', kindLabel));
            if (job.operation && job.operation !== 'shorts') {
                meta.appendChild(element('span', '', String(job.operation)));
            }
            if (job.kind === 'shorts' && Number(job.scene_count) > 0) {
                const sceneNumber = Math.min(Number(job.current_scene || 0) + 1, Number(job.scene_count));
                meta.appendChild(element('span', '', t(`Szene ${sceneNumber}/${job.scene_count}`, `Scene ${sceneNumber}/${job.scene_count}`)));
            }
            item.appendChild(meta);

            const progress = progressValue(job);
            if (progress !== null && ACTIVE_STATES.has(job.queue_status)) {
                const track = element('div', 'mlx-queue-progress');
                const fill = document.createElement('span');
                fill.style.width = Math.round(progress * 100) + '%';
                track.appendChild(fill);
                item.appendChild(track);
            }

            if (job.error) {
                item.appendChild(element('div', 'mlx-queue-error', String(job.error)));
            }

            if (job.cancellable) {
                const actions = element('div', 'mlx-queue-actions');
                const button = element('button', 'mlx-queue-cancel', t('Abbrechen', 'Cancel'));
                button.type = 'button';
                button.addEventListener('click', async () => {
                    button.disabled = true;
                    try {
                        await cancelJob(job);
                    } catch (error) {
                        window.alert(error.message || String(error));
                    } finally {
                        button.disabled = false;
                    }
                });
                actions.appendChild(button);
                item.appendChild(actions);
            }

            list.appendChild(item);
        }
        root.appendChild(list);
    }

    function renderBatch(batch, root) {
        const heading = element('div', 'mlx-queue-section');
        heading.appendChild(element('span', '', t('Datei-Aufträge', 'File jobs')));
        root.appendChild(heading);

        const jobs = Array.isArray(batch?.jobs) ? batch.jobs.slice(0, 8) : [];
        if (!jobs.length) {
            root.appendChild(element('div', 'mlx-queue-empty', t('Keine aktiven Datei-Aufträge.', 'No active file jobs.')));
            return;
        }

        const list = element('div', 'mlx-queue-list');
        for (const job of jobs) {
            const item = element('div', 'mlx-queue-item');
            const head = element('div', 'mlx-queue-head');
            head.appendChild(element('span', 'mlx-queue-icon', '📄'));
            head.appendChild(element(
                'span',
                'mlx-queue-title',
                String(job.output_name || job.original_name || job.input_name || t('Datei', 'File'))
            ));
            const active = ['queued', 'running', 'paused'].includes(job.status);
            let status = active ? t('Läuft', 'Running') : t('Fertig', 'Completed');
            if (job.total_chunks) {
                status = Math.round(
                    Number(job.processed_chunks || 0) / Number(job.total_chunks) * 100
                ) + ' %';
            }
            head.appendChild(element('span', 'mlx-queue-state', status));
            item.appendChild(head);
            const meta = element('div', 'mlx-queue-meta');
            meta.appendChild(element('span', '', String(job.operation || t('Dateioperation', 'File operation'))));
            item.appendChild(meta);
            list.appendChild(item);
        }
        root.appendChild(list);
    }

    async function refresh() {
        const generation = ++refreshGeneration;
        const [queueResult, batchResult] = await Promise.allSettled([
            fetch('/api/system/job-queue?limit=40').then(async response => {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            }),
            fetch('/api/mlx/batch').then(async response => {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
        ]);

        if (generation !== refreshGeneration || panel.hidden) return;

        const root = document.createDocumentFragment();
        if (queueResult.status === 'fulfilled') {
            renderMedia(queueResult.value, root);
        } else {
            root.appendChild(element('div', 'mlx-queue-error', t('Medien-Queue ist nicht erreichbar.', 'Media queue is unavailable.')));
        }
        if (batchResult.status === 'fulfilled') {
            renderBatch(batchResult.value, root);
        }

        content.replaceChildren(root);
    }

    function stopPolling() {
        if (pollTimer !== null) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function startPolling() {
        stopPolling();
        pollTimer = window.setInterval(() => {
            if (panel.hidden) {
                stopPolling();
                return;
            }
            refresh();
        }, 2000);
    }

    function openQueue(event) {
        event?.preventDefault?.();
        event?.stopImmediatePropagation?.();
        panel.hidden = false;
        content.textContent = t('Lade Aufträge…', 'Loading jobs…');
        refresh();
        startPolling();
    }

    ensureStyles();
    openButton.addEventListener('click', openQueue, true);
    closeButton?.addEventListener('click', stopPolling);
    document.addEventListener('mlx-language-changed', () => {
        if (!panel.hidden) refresh();
    });

    window.MLXJobQueue = {
        open: () => openQueue(),
        refresh,
        stop: stopPolling
    };
})();
