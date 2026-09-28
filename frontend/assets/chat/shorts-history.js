(function () {
    'use strict';

    const ACTIVE_STATUSES = new Set([
        'queued',
        'running',
        'video_completed',
        'tts_completed'
    ]);

    const COPY = {
        de: {
            launcher: 'Shorts',
            title: 'Shorts Studio',
            subtitle: 'Projekte',
            close: 'Projektübersicht schließen',
            new_short: '+ Neues Short',
            refresh: 'Aktualisieren',
            all: 'Alle',
            active: 'Aktiv',
            completed: 'Fertig',
            failed: 'Fehler',
            loading: 'Shorts-Projekte werden geladen …',
            empty: 'Noch keine Shorts-Projekte vorhanden.',
            unavailable: 'Shorts-Historie ist momentan nicht verfügbar.',
            open: 'Öffnen',
            video: 'Video',
            scenes: 'Szenen',
            revision: 'Revision',
            revisions: 'Revisionen',
            voice: 'Stimme',
            default_voice: 'Standardstimme',
            created: 'Erstellt',
            status_completed: 'Fertig',
            status_failed: 'Fehler',
            status_cancelled: 'Abgebrochen',
            status_queued: 'Wartet',
            status_running: 'Rendering',
            status_video_completed: 'Video fertig',
            status_tts_completed: 'Stimme fertig',
            status_unknown: 'Unbekannt',
            prompt: 'Erstelle ein 20-sekündiges Short über '
        },
        en: {
            launcher: 'Shorts',
            title: 'Shorts Studio',
            subtitle: 'Projects',
            close: 'Close project browser',
            new_short: '+ New Short',
            refresh: 'Refresh',
            all: 'All',
            active: 'Active',
            completed: 'Completed',
            failed: 'Failed',
            loading: 'Loading Shorts projects …',
            empty: 'No Shorts projects yet.',
            unavailable: 'Shorts history is currently unavailable.',
            open: 'Open',
            video: 'Video',
            scenes: 'scenes',
            revision: 'revision',
            revisions: 'revisions',
            voice: 'Voice',
            default_voice: 'Default voice',
            created: 'Created',
            status_completed: 'Completed',
            status_failed: 'Failed',
            status_cancelled: 'Cancelled',
            status_queued: 'Queued',
            status_running: 'Rendering',
            status_video_completed: 'Video completed',
            status_tts_completed: 'Voice completed',
            status_unknown: 'Unknown',
            prompt: 'Create a 20-second Short about '
        }
    };

    let ui = null;
    let projects = [];
    let filter = 'all';
    let refreshTimer = null;
    let loading = false;

    function language() {
        const configured = String(window.MLXI18n?.getLanguage?.() || '').toLowerCase();
        if (configured === 'de' || configured === 'en') return configured;
        return String(document.documentElement?.lang || '').toLowerCase().startsWith('de')
            ? 'de'
            : 'en';
    }

    function t(key) {
        return COPY[language()]?.[key] || COPY.en[key] || key;
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function loadStyles() {
        if (document.querySelector('link[data-mlx-shorts-history-style]')) return;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/assets/chat/shorts-history.css?v=20260928-shorts-history-v1';
        link.dataset.mlxShortsHistoryStyle = '1';
        document.head.appendChild(link);
    }

    function statusKey(status) {
        const normalized = String(status || 'unknown').toLowerCase();
        return `status_${normalized}`;
    }

    function statusLabel(status) {
        const key = statusKey(status);
        return COPY[language()]?.[key] || COPY.en[key] || String(status || t('status_unknown'));
    }

    function statusClass(status) {
        const normalized = String(status || 'unknown').toLowerCase();
        if (normalized === 'completed') return 'is-completed';
        if (normalized === 'failed') return 'is-failed';
        if (normalized === 'cancelled') return 'is-cancelled';
        if (ACTIVE_STATUSES.has(normalized)) return 'is-active';
        return '';
    }

    function locale() {
        return window.MLXI18n?.getLocale?.() || (language() === 'de' ? 'de-DE' : 'en-US');
    }

    function formatDate(value) {
        const seconds = Number(value || 0);
        if (!Number.isFinite(seconds) || seconds <= 0) return '–';
        return new Intl.DateTimeFormat(locale(), {
            dateStyle: 'medium',
            timeStyle: 'short'
        }).format(new Date(seconds * 1000));
    }

    function visibleProjects() {
        if (filter === 'active') {
            return projects.filter(project => ACTIVE_STATUSES.has(String(project.status || '').toLowerCase()));
        }
        if (filter === 'completed') {
            return projects.filter(project => project.status === 'completed');
        }
        if (filter === 'failed') {
            return projects.filter(project => project.status === 'failed');
        }
        return projects;
    }

    function activeCount() {
        return projects.filter(project => ACTIVE_STATUSES.has(String(project.status || '').toLowerCase())).length;
    }

    function updateLauncher() {
        if (!ui?.launcher) return;
        const count = activeCount();
        ui.launcher.textContent = count > 0
            ? `${t('launcher')} · ${count}`
            : t('launcher');
        ui.launcher.dataset.active = count > 0 ? 'true' : 'false';
    }

    function projectMeta(project) {
        const parts = [];
        if (Number(project.duration) > 0) parts.push(`${project.duration}s`);
        if (Number(project.scene_count) > 0) parts.push(`${project.scene_count} ${t('scenes')}`);
        parts.push(`${t('voice')}: ${project.voice || t('default_voice')}`);
        return parts.join(' · ');
    }

    function projectRevisionText(project) {
        const count = Number(project.revision_count || 0);
        if (!count) return '';
        return `${count} ${t(count === 1 ? 'revision' : 'revisions')}`;
    }

    async function openProject(project) {
        const response = await window.fetch(
            `/api/mlx/shorts-jobs/${encodeURIComponent(project.id)}`,
            { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json().catch(() => ({}));

        for (let attempt = 0; attempt < 20; attempt += 1) {
            if (window.MLXShortsStudio?.getActiveJob?.()?.id === project.id) break;
            await new Promise(resolve => setTimeout(resolve, 25));
        }

        close();
        window.MLXShortsStudio?.open?.();
    }

    function openVideo(project) {
        window.open(
            `/api/mlx/shorts/${encodeURIComponent(project.id)}`,
            '_blank',
            'noopener,noreferrer'
        );
    }

    function renderProject(project) {
        const card = createElement('article', 'mlx-shorts-history-card');
        card.dataset.status = String(project.status || 'unknown');

        const preview = createElement('div', 'mlx-shorts-history-preview');
        if (project.has_video) {
            const video = document.createElement('video');
            video.muted = true;
            video.playsInline = true;
            video.preload = 'metadata';
            video.src = `/api/mlx/shorts/${encodeURIComponent(project.id)}`;
            video.addEventListener('loadedmetadata', () => {
                try {
                    if (video.duration > 0.2) video.currentTime = 0.1;
                } catch (_) {}
            }, { once: true });
            preview.appendChild(video);
        } else {
            preview.appendChild(createElement('span', '', '▶'));
        }

        const body = createElement('div', 'mlx-shorts-history-card-body');
        const top = createElement('div', 'mlx-shorts-history-card-top');
        const title = createElement('strong', 'mlx-shorts-history-card-title', project.title || 'Short');
        const badge = createElement(
            'span',
            `mlx-shorts-history-status ${statusClass(project.status)}`,
            statusLabel(project.status)
        );
        top.append(title, badge);

        const meta = createElement('div', 'mlx-shorts-history-card-meta', projectMeta(project));
        const details = createElement('div', 'mlx-shorts-history-card-details');
        const revision = projectRevisionText(project);
        const date = `${t('created')}: ${formatDate(project.created_at)}`;
        details.textContent = [revision, date].filter(Boolean).join(' · ');

        if (project.status === 'failed' && project.error) {
            const error = createElement('div', 'mlx-shorts-history-error', String(project.error));
            error.title = String(project.error);
            body.append(top, meta, details, error);
        } else {
            body.append(top, meta, details);
        }

        const actions = createElement('div', 'mlx-shorts-history-actions');
        const openButton = createElement('button', '', t('open'));
        openButton.type = 'button';
        openButton.dataset.primary = '1';
        openButton.addEventListener('click', async event => {
            event.stopPropagation();
            openButton.disabled = true;
            try {
                await openProject(project);
            } catch (error) {
                openButton.disabled = false;
                console.error('[Shorts History] open failed:', error);
            }
        });
        actions.appendChild(openButton);

        if (project.has_video) {
            const videoButton = createElement('button', '', t('video'));
            videoButton.type = 'button';
            videoButton.addEventListener('click', event => {
                event.stopPropagation();
                openVideo(project);
            });
            actions.appendChild(videoButton);
        }

        body.appendChild(actions);
        card.append(preview, body);
        card.addEventListener('dblclick', () => openProject(project).catch(() => {}));
        return card;
    }

    function render() {
        if (!ui) return;
        updateLauncher();
        ui.title.textContent = t('title');
        ui.subtitle.textContent = t('subtitle');
        ui.close.setAttribute('aria-label', t('close'));
        ui.newButton.textContent = t('new_short');
        ui.refreshButton.textContent = t('refresh');

        ui.filters.querySelectorAll('[data-filter]').forEach(button => {
            const key = button.dataset.filter;
            button.textContent = t(key);
            button.classList.toggle('is-active', key === filter);
        });

        const list = visibleProjects();
        ui.list.replaceChildren();

        if (!list.length) {
            ui.list.appendChild(createElement('div', 'mlx-shorts-history-empty', t('empty')));
            return;
        }

        list.forEach(project => ui.list.appendChild(renderProject(project)));
    }

    function ensureUi() {
        if (ui || !document.body) return ui;
        loadStyles();

        const launcher = createElement('button', 'mlx-shorts-history-launcher', t('launcher'));
        launcher.type = 'button';
        launcher.setAttribute('aria-label', t('title'));

        const overlay = createElement('div', 'mlx-shorts-history-overlay');
        overlay.hidden = true;
        const panel = createElement('aside', 'mlx-shorts-history-panel');
        const header = createElement('header', 'mlx-shorts-history-header');
        const heading = createElement('div');
        const title = createElement('h2', '', t('title'));
        const subtitle = createElement('div', 'mlx-shorts-history-subtitle', t('subtitle'));
        const closeButton = createElement('button', 'mlx-shorts-history-close', '×');
        closeButton.type = 'button';
        closeButton.setAttribute('aria-label', t('close'));
        heading.append(title, subtitle);
        header.append(heading, closeButton);

        const toolbar = createElement('div', 'mlx-shorts-history-toolbar');
        const filters = createElement('div', 'mlx-shorts-history-filters');
        ['all', 'active', 'completed', 'failed'].forEach(key => {
            const button = createElement('button', '', t(key));
            button.type = 'button';
            button.dataset.filter = key;
            button.addEventListener('click', () => {
                filter = key;
                render();
            });
            filters.appendChild(button);
        });
        const toolbarActions = createElement('div', 'mlx-shorts-history-toolbar-actions');
        const refreshButton = createElement('button', '', t('refresh'));
        const newButton = createElement('button', '', t('new_short'));
        refreshButton.type = 'button';
        newButton.type = 'button';
        newButton.dataset.primary = '1';
        refreshButton.addEventListener('click', () => loadProjects(true));
        newButton.addEventListener('click', () => {
            close();
            const input = document.getElementById('input');
            if (!input) return;
            if (!String(input.value || '').trim()) input.value = t('prompt');
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        });
        toolbarActions.append(refreshButton, newButton);
        toolbar.append(filters, toolbarActions);

        const list = createElement('div', 'mlx-shorts-history-list');
        panel.append(header, toolbar, list);
        overlay.appendChild(panel);
        document.body.append(launcher, overlay);

        launcher.addEventListener('click', open);
        closeButton.addEventListener('click', close);
        overlay.addEventListener('click', event => {
            if (event.target === overlay) close();
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !overlay.hidden) close();
        });

        ui = {
            launcher,
            overlay,
            panel,
            title,
            subtitle,
            close: closeButton,
            filters,
            refreshButton,
            newButton,
            list
        };
        render();
        return ui;
    }

    function scheduleRefresh() {
        if (refreshTimer !== null) clearTimeout(refreshTimer);
        refreshTimer = null;
        if (!ui || ui.overlay.hidden || activeCount() === 0) return;
        refreshTimer = setTimeout(() => {
            refreshTimer = null;
            loadProjects(false);
        }, 3000);
    }

    async function loadProjects(showLoading = false) {
        if (loading) return;
        loading = true;
        const current = ensureUi();
        if (showLoading && current) {
            current.list.replaceChildren(
                createElement('div', 'mlx-shorts-history-empty', t('loading'))
            );
        }

        try {
            const response = await window.fetch('/api/mlx/shorts-jobs?limit=100', {
                cache: 'no-store',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            projects = Array.isArray(payload.projects) ? payload.projects : [];
            render();
        } catch (error) {
            console.error('[Shorts History] load failed:', error);
            if (ui) {
                ui.list.replaceChildren(
                    createElement('div', 'mlx-shorts-history-empty', t('unavailable'))
                );
            }
        } finally {
            loading = false;
            scheduleRefresh();
        }
    }

    function open() {
        const current = ensureUi();
        if (!current) return;
        current.overlay.hidden = false;
        document.body.classList.add('mlx-shorts-history-open');
        loadProjects(true);
    }

    function close() {
        if (!ui) return;
        ui.overlay.hidden = true;
        document.body.classList.remove('mlx-shorts-history-open');
        if (refreshTimer !== null) clearTimeout(refreshTimer);
        refreshTimer = null;
    }

    function refreshLanguage() {
        render();
    }

    function init() {
        ensureUi();
        loadProjects(false);
        document.addEventListener('mlx-language-changed', refreshLanguage);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }

    window.MLXShortsHistory = {
        open,
        close,
        refresh: () => loadProjects(true),
        getProjects: () => projects.slice(),
        __test: {
            statusClass,
            projectRevisionText,
            visibleProjects
        }
    };
})();
