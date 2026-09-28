(function () {
    'use strict';

    const ACTIVE_STATUSES = new Set([
        'queued',
        'running',
        'video_completed',
        'tts_completed'
    ]);

    const FALLBACKS = {
        launcher: 'Shorts',
        title: 'Shorts Studio',
        subtitle: 'Projects',
        close: 'Close project browser',
        new_short: '+ New Short',
        refresh: 'Refresh',
        delete_failed: 'Delete failed',
        all: 'All',
        active: 'Active',
        completed: 'Completed',
        failed: 'Failed',
        loading: 'Loading Shorts projects …',
        empty: 'No Shorts projects yet.',
        unavailable: 'Shorts history is currently unavailable.',
        open: 'Open',
        video: 'Video',
        delete: 'Delete',
        scenes: 'scenes',
        revision: 'revision',
        revisions: 'revisions',
        voice: 'Voice',
        default_voice: 'Default voice',
        created: 'Created',
        prompt: 'Create a 20-second Short about ',
        delete_title: 'Delete Short?',
        delete_message: 'Permanently delete “{title}” and all of its revisions and Shorts-owned files?',
        delete_confirm: 'Delete project',
        delete_failed_title: 'Delete failed Shorts?',
        delete_failed_message: 'Permanently delete {count} failed Shorts project(s), including revisions and Shorts-owned files?',
        delete_failed_confirm: 'Delete failed',
        delete_error: 'Could not delete Shorts project: {message}'
    };

    let ui = null;
    let projects = [];
    let filter = 'all';
    let refreshTimer = null;
    let loading = false;
    let translations = window.__MLXShortsStudioTranslations || {};
    let translationsPromise = null;

    function language() {
        const configured = String(window.MLXI18n?.getLanguage?.() || '').toLowerCase();
        if (configured === 'de' || configured === 'en') return configured;
        return String(document.documentElement?.lang || '').toLowerCase().startsWith('de')
            ? 'de'
            : 'en';
    }

    function interpolate(value, params = {}) {
        let result = String(value || '');
        for (const [key, replacement] of Object.entries(params)) {
            result = result.replaceAll(`{${key}}`, String(replacement ?? ''));
        }
        return result;
    }

    function t(key, params = {}) {
        const fullKey = `history_${key}`;
        const localized = translations?.[language()]?.[fullKey];
        const fallback = localized || FALLBACKS[key] || key;
        const value = window.MLXI18n?.t?.(`shorts_studio.${fullKey}`, fallback) || fallback;
        return interpolate(value, params);
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

    function statusLabel(status) {
        const normalized = String(status || 'unknown').trim().toLowerCase();
        const localized = translations?.[language()]?.[`status_${normalized}`];
        if (localized) return localized;
        return window.MLXShortsStudio?.statusLabel?.(normalized) || normalized;
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

    function failedCount() {
        return projects.filter(project => String(project.status || '').toLowerCase() === 'failed').length;
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

    async function confirmAction(options) {
        if (typeof window.MLXConfirm === 'function') {
            return window.MLXConfirm(options);
        }
        return window.confirm(options.message || options.title || 'Confirm');
    }

    async function responseDetail(response) {
        try {
            const payload = await response.json();
            return payload?.detail || payload?.error || `HTTP ${response.status}`;
        } catch (_) {
            return `HTTP ${response.status}`;
        }
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

    async function deleteProject(project) {
        const status = String(project?.status || '').toLowerCase();
        if (!project?.id || ACTIVE_STATUSES.has(status)) return;

        const confirmed = await confirmAction({
            title: t('delete_title'),
            message: t('delete_message', { title: project.title || 'Short' }),
            confirmLabel: t('delete_confirm'),
            cancelLabel: window.MLXI18n?.t?.('common.cancel', 'Cancel') || 'Cancel'
        });
        if (!confirmed) return;

        const response = await window.fetch(
            `/api/mlx/shorts-jobs/${encodeURIComponent(project.id)}`,
            { method: 'DELETE' }
        );
        if (!response.ok) {
            throw new Error(await responseDetail(response));
        }

        const rootId = String(project.root_job_id || project.id);
        projects = projects.filter(item => String(item.root_job_id || item.id) !== rootId);
        render();
        await loadProjects(false);
    }

    async function deleteFailedProjects() {
        const count = failedCount();
        if (!count) return;

        const confirmed = await confirmAction({
            title: t('delete_failed_title'),
            message: t('delete_failed_message', { count }),
            confirmLabel: t('delete_failed_confirm'),
            cancelLabel: window.MLXI18n?.t?.('common.cancel', 'Cancel') || 'Cancel'
        });
        if (!confirmed) return;

        const response = await window.fetch('/api/mlx/shorts-jobs/failed', {
            method: 'DELETE'
        });
        if (!response.ok) {
            throw new Error(await responseDetail(response));
        }
        await loadProjects(false);
    }

    function reportDeleteError(error) {
        const message = error?.message || String(error);
        console.error('[Shorts History] delete failed:', error);
        window.alert(t('delete_error', { message }));
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

        if (!ACTIVE_STATUSES.has(String(project.status || '').toLowerCase())) {
            const deleteButton = createElement('button', '', t('delete'));
            deleteButton.type = 'button';
            deleteButton.dataset.danger = '1';
            deleteButton.addEventListener('click', async event => {
                event.stopPropagation();
                deleteButton.disabled = true;
                try {
                    await deleteProject(project);
                } catch (error) {
                    deleteButton.disabled = false;
                    reportDeleteError(error);
                }
            });
            actions.appendChild(deleteButton);
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

        const failed = failedCount();
        ui.deleteFailedButton.textContent = failed > 0
            ? `${t('delete_failed')} (${failed})`
            : t('delete_failed');
        ui.deleteFailedButton.hidden = failed === 0;
        ui.deleteFailedButton.disabled = failed === 0;

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
        const deleteFailedButton = createElement('button', '', t('delete_failed'));
        const refreshButton = createElement('button', '', t('refresh'));
        const newButton = createElement('button', '', t('new_short'));
        deleteFailedButton.type = 'button';
        deleteFailedButton.dataset.danger = '1';
        refreshButton.type = 'button';
        newButton.type = 'button';
        newButton.dataset.primary = '1';
        deleteFailedButton.addEventListener('click', async () => {
            deleteFailedButton.disabled = true;
            try {
                await deleteFailedProjects();
            } catch (error) {
                reportDeleteError(error);
            } finally {
                deleteFailedButton.disabled = failedCount() === 0;
            }
        });
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
        toolbarActions.append(deleteFailedButton, refreshButton, newButton);
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
            deleteFailedButton,
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

    function loadTranslations() {
        if (translationsPromise) return translationsPromise;
        translationsPromise = window.fetch('/i18n/shorts-studio.json', { cache: 'no-cache' })
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(payload => {
                if (payload && typeof payload === 'object') translations = payload;
                render();
                return translations;
            })
            .catch(error => {
                console.warn('[Shorts History i18n]', error);
                return translations;
            });
        return translationsPromise;
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
        loadTranslations();
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
            visibleProjects,
            activeCount,
            failedCount
        }
    };
})();
