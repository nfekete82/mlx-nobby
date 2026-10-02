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
        delete_error: 'Could not delete Shorts project: {message}',
        retry: 'Try again', details: 'Details', duplicate: 'Duplicate', cancel: 'Cancel',
        quality_fast: 'Draft', quality_standard: 'Standard', quality_quality: 'Publication',
        scene_progress: 'Scene {scene} of {count}', elapsed: 'Elapsed', render_duration: 'Render time',
        phase_keyframe: 'Creating keyframe', phase_video: 'Rendering video', phase_tts: 'Generating voice',
        phase_compose: 'Composing final video', phase_queued: 'Waiting for resources',
        error_image: 'The local image generator could not create the keyframe.',
        error_incompatible: 'The keyframe generator is incompatible with the installed MFLUX version.',
        error_video: 'The scene video could not be rendered.', error_tts: 'Voice generation failed.',
        error_voiceover_duration: 'Narration in scene {scene} is too long. {audio} s of speech for a {duration} s scene. Please shorten the text or increase voice speed.',
        error_compose: 'The final video could not be composed.', error_generic: 'The Short could not be rendered.',
        anchor_warning: 'Character anchor unavailable – using regular visual consistency.',
        action_error: 'The action could not be completed.'
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
        link.href = '/assets/chat/shorts-history.css?v=20261002-studio-ui';
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
        parts.push(t('quality_' + (project.quality || 'fast')));
        return parts.join(' · ');
    }

    function projectRevisionText(project) {
        const count = Number(project.revision_count || 0);
        if (!count) return '';
        return `${count} ${t(count === 1 ? 'revision' : 'revisions')}`;
    }

    function voiceoverDurationMessage(job) {
        if (job.error_code !== 'VOICEOVER_TOO_LONG' ||
            !Number.isInteger(job.error_scene_number) || job.error_scene_number < 1 ||
            !Number.isFinite(job.error_audio_duration) || job.error_audio_duration <= 0 ||
            !Number.isFinite(job.error_scene_duration) || job.error_scene_duration <= 0) return null;
        const format = value => value.toLocaleString(language(), {
            minimumFractionDigits: 1, maximumFractionDigits: 1
        });
        return t('error_voiceover_duration', {
            scene: job.error_scene_number,
            audio: format(job.error_audio_duration), duration: format(job.error_scene_duration)
        });
    }

    function renderJobStatus(parent, job) {
        const phase = job.error_stage || job.phase || 'queued';
        const count = job.scene_count || job.project?.scenes?.length || 0;
        const scene = job.error_scene_number || Math.min(Number(job.current_scene || 0) + 1, count);
        if (job.status !== 'completed' && job.status !== 'cancelled') {
            const phaseLabel = t(['keyframe', 'video', 'tts', 'compose'].includes(phase) ? 'phase_' + phase : 'phase_queued');
            parent.appendChild(createElement('div', 'mlx-shorts-history-card-meta',
                (count && ['keyframe', 'video'].includes(phase) ? t('scene_progress', {scene, count}) + ' · ' : '') + phaseLabel));
        }
        if (job.status === 'failed') {
            const code = job.error_code || '';
            const errorKey = code === 'IMAGE_PROVIDER_INCOMPATIBLE' ? 'error_incompatible' :
                ({keyframe:'error_image',video:'error_video',tts:'error_tts',compose:'error_compose'}[phase] || 'error_generic');
            parent.appendChild(createElement('p', 'mlx-shorts-history-error', voiceoverDurationMessage(job) || t(errorKey)));
            const details = createElement('details', 'mlx-shorts-history-diagnosis');
            details.appendChild(createElement('summary', '', t('details')));
            details.appendChild(createElement('p', '', voiceoverDurationMessage(job) || (code === 'IMAGE_PROVIDER_INCOMPATIBLE' ? [t('error_incompatible'), job.error_provider, job.error_model, job.error_detail_safe].filter(Boolean).join(' · ') : t(errorKey))));
            parent.appendChild(details);
        }
        if (ACTIVE_STATUSES.has(job.status)) {
            const raw = job.progress_percent !== undefined ? job.progress_percent / 100 : job.progress;
            const value = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : Math.min(.95, ((job.current_scene || 0) + (job.phase === 'video' ? .25 : 0) + (job.child_progress || 0) * (job.phase === 'keyframe' ? .25 : .75)) / Math.max(1, count) * .8);
            const progress = createElement('progress', 'mlx-shorts-history-progress');
            progress.max = 1; progress.value = value; progress.setAttribute('aria-label', t('active'));
            parent.appendChild(progress);
            parent.appendChild(createElement('span', 'mlx-shorts-history-card-meta', Math.round(value * 100) + '%'));
        }
        if (job.started_at) {
            const elapsed = Math.max(0, Math.round((job.finished_at || Date.now()/1000) - job.started_at));
            parent.appendChild(createElement('div', 'mlx-shorts-history-card-details', `${t(job.finished_at ? 'render_duration' : 'elapsed')}: ${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,'0')}`));
        }
        if ((job.warnings || []).includes('character_anchor_fallback')) parent.appendChild(createElement('p', 'mlx-shorts-studio-warning', t('anchor_warning')));
    }

    function actionButton(parent, label, action) {
        const button = createElement('button', '', t(label)); button.type = 'button';
        button.addEventListener('click', async event => {
            event.stopPropagation(); button.disabled = true;
            try { await action(); } catch (error) { window.alert(t('action_error'));  }
            finally { button.disabled = false; }
        });
        parent.appendChild(button); return button;
    }

    async function retryProject(project) {
        const token = window.MLXShortsStudio?.selectionToken?.();
        const response = await window.fetch(`/api/mlx/shorts-jobs/${encodeURIComponent(project.id)}/retry`, {method:'POST'});
        if (!response.ok) throw new Error(await responseDetail(response));
        const payload = await response.json();
        if (token !== window.MLXShortsStudio?.selectionToken?.()) return;
        window.MLXShortsStudio?.setActiveJob?.(payload.job);
        close(); window.MLXShortsStudio?.openJob?.();
    }

    async function duplicateProject(project) {
        const token = window.MLXShortsStudio?.selectionToken?.();
        const response = await window.fetch(`/api/mlx/shorts-jobs/${encodeURIComponent(project.id)}`);
        if (!response.ok) throw new Error(t('action_error'));
        const payload = await response.json();
        const job = window.MLXShortsStudio?.extractJob?.(payload) || payload.data?.job || payload.result?.job || payload.job || payload;
        if (!job.project || job.id !== project.id) throw new Error(t('action_error'));
        if (token !== window.MLXShortsStudio?.selectionToken?.()) return;
        const draftResponse = await window.fetch('/api/mlx/shorts/drafts', {method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({project:job.project, chat_id:job.chat_id || 'shorts-studio', source_job_id:job.status === 'completed' ? job.id : null})});
        if (!draftResponse.ok) throw new Error(t('action_error'));
        const result = await draftResponse.json();
        if (token !== window.MLXShortsStudio?.selectionToken?.()) return;
        close();
        await window.MLXShortsStudio?.openDraft?.(result.draft);
    }

    async function confirmAction(options) {
        if (typeof window.MLXConfirm === 'function') {
            return window.MLXConfirm(options);
        }
        return window.confirm(options.message || options.title || 'Confirm');
    }

    async function responseDetail(response) {
        return response.status >= 500 ? t('unavailable') : t('action_error');
    }

    async function openProject(project) {
        const opened = await window.MLXShortsStudio?.loadJob?.(project.id);
        if (opened === false) return;
        close();
        if (!opened) {
            projects = projects.filter(item => item.id !== project.id);
            render();
        }
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
        if (!response.ok && response.status !== 404) {
            throw new Error(await responseDetail(response));
        }
        const payload = response.ok ? await response.json().catch(() => ({})) : {};
        window.MLXShortsStudio?.jobsDeleted?.(payload.deleted_job_ids || [project.id]);

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
        const payload = await response.json().catch(() => ({}));
        window.MLXShortsStudio?.jobsDeleted?.(payload.deleted_job_ids || []);
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
        } else if (project.thumbnail_scene_id) {
            const image = createElement('img'); image.alt = project.title || 'Short';
            image.src = `/api/mlx/shorts/jobs/${encodeURIComponent(project.id)}/scenes/${encodeURIComponent(project.thumbnail_scene_id)}/keyframe`;
            preview.appendChild(image);
        } else {
            preview.appendChild(createElement('span', '', '▶'));
        }
        if (project.has_video) {
            const play = actionButton(preview, 'video', () => openVideo(project));
            play.textContent = '▶ ' + t('video');
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

        body.append(top, meta, details);
        renderJobStatus(body, project);

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
        if (['failed','cancelled'].includes(project.status)) actionButton(actions, 'retry', () => retryProject(project));
        if (project.status === 'completed') actionButton(actions, 'duplicate', () => duplicateProject(project));
        if (ACTIVE_STATUSES.has(project.status)) actionButton(actions, 'cancel', async () => {
            const response = await window.fetch(`/api/system/job-queue/shorts/${encodeURIComponent(project.id)}/cancel`, {method:'POST'});
            if (!response.ok) throw new Error(t('action_error'));
            await loadProjects(false);
        });

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
            window.MLXShortsStudio?.newDraft?.();
        });
        toolbarActions.append(deleteFailedButton, refreshButton, newButton);
        toolbar.append(filters, toolbarActions);

        const list = createElement('div', 'mlx-shorts-history-list');
        panel.append(header, toolbar, list);
        overlay.appendChild(panel);
        document.body.append(launcher, overlay);

        launcher.addEventListener('click', () => window.MLXShortsStudio?.open?.());
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
        document.addEventListener('mlx-language-changed', refreshLanguage);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }

    window.MLXShortsHistory = {
        renderJobStatus,
        open,
        close,
        refresh: () => loadProjects(true),
        getProjects: () => projects.slice(),
        __test: {
            openProject, deleteProject, renderProject, retryProject, duplicateProject,
            voiceoverDurationMessage,
            statusClass,
            projectRevisionText,
            visibleProjects,
            activeCount,
            failedCount
        }
    };
})();
