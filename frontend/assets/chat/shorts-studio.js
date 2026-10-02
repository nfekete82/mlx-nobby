(function () {
    'use strict';

    const SHORTS_PATTERN = /\b(?:shorts?|short[\s-]*videos?|youtube[\s-]+shorts?|tiktoks?(?:[\s-]+videos?)?|reels?|kurzvideos?)\b/iu;
    const CREATE_PATTERN = /\b(?:erstelle|erstellen|generiere|generieren|erzeuge|erzeugen|mach|mache|produziere|produzieren|möchte|moechte|will|brauche|create|generate|make|produce|want|need)\b/iu;
    const EXPLICIT_VOICE_PATTERN = /\b(?:stimme|voice|sprecher(?:in)?|speaker|sprechgeschwindigkeit|geschwindigkeit|voice[_ -]?speed|speed)\b/iu;
    const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);
    const previousFetch = window.fetch.bind(window);

    const ENGLISH_FALLBACKS = {
        title: 'Shorts Studio',
        close: 'Close Shorts Studio',
        scene: 'Scene',
        scenes: 'scenes',
        narration: 'Narration',
        visual_prompt: 'Visual prompt',
        voice_profile: 'Voice profile',
        voice_placeholder: 'Use current/default voice',
        voice_speed: 'Voice speed',
        apply_revision: 'Apply revision',
        regenerate_video: 'Regenerate scene video',
        rendering_prefix: 'Rendering',
        revision_of: 'Revision of {id}.',
        help_completed: 'Select a scene, edit narration or visual prompt, then create a revision. Narration-only changes reuse the existing scene video.',
        help_rendering: 'The current revision is still rendering. Editing is enabled again after completion.',
        feedback_no_changes: 'No changes to render.',
        feedback_creating: 'Creating revision…',
        feedback_queued: 'Revision queued.',
        error_revision_failed: 'Revision failed ({status})',
        error_missing_job: 'Revision response did not contain a Shorts job.',
        missing_job: 'The previously selected Short is no longer available.',
        preview_unavailable: 'Preview unavailable.',
        error_service_unavailable: 'The Shorts service is unavailable. Please try again.',
        status_unknown: 'Unknown',
        status_ready: 'Ready',
        status_rendering: 'Rendering',
        status_pending: 'Pending',
        status_completed: 'Completed',
        status_failed: 'Failed',
        status_cancelled: 'Cancelled',
        status_queued: 'Queued',
        status_running: 'Running',
        status_dispatching: 'Dispatching',
        status_loading: 'Loading',
        status_encoding: 'Encoding',
        status_generating: 'Generating',
        status_upscaling: 'Upscaling',
        status_decoding: 'Decoding',
        status_muxing: 'Muxing',
        status_saving: 'Saving',
        status_keyframe: 'Keyframe',
        status_video: 'Video',
        status_tts: 'Voice',
        status_compose: 'Composing',
        status_video_completed: 'Video completed',
        status_tts_completed: 'Voice completed'
    };

    let activeJob = null;
    let selectionEpoch = 0;
    let activeSceneId = null;
    let pollTimer = null;
    let studio = null;
    let studioTranslations = window.__MLXShortsStudioTranslations || {};
    let translationsPromise = null;
    const sceneDrafts = new Map();
    const projectDrafts = new Map();

    function currentLanguage() {
        const configured = String(window.MLXI18n?.getLanguage?.() || '').toLowerCase();
        if (configured === 'de' || configured === 'en') return configured;
        if (typeof document !== 'undefined') {
            const documentLanguage = String(document.documentElement?.lang || '').toLowerCase();
            if (documentLanguage.startsWith('de')) return 'de';
        }
        return 'en';
    }

    function interpolate(value, params) {
        return String(value || '').replace(/\{([a-z0-9_]+)\}/giu, (match, key) => (
            Object.prototype.hasOwnProperty.call(params || {}, key)
                ? String(params[key])
                : match
        ));
    }

    function translate(key, params = {}) {
        const language = currentLanguage();
        const localized = studioTranslations?.[language]?.[key];
        const fallback = localized || ENGLISH_FALLBACKS[key] || key;
        const value = window.MLXI18n?.t?.(`shorts_studio.${key}`, fallback) || fallback;
        return interpolate(value, params);
    }

    function statusLabel(status) {
        const normalized = String(status || 'unknown').trim().toLowerCase();
        const key = `status_${normalized}`;
        const translated = translate(key);
        return translated === key ? normalized : translated;
    }

    function requestPath(input) {
        const raw = typeof input === 'string' ? input : input?.url;
        if (!raw) return '';
        try {
            return new URL(raw, window.location.origin).pathname;
        } catch (_) {
            return '';
        }
    }

    function isShortsPrompt(prompt) {
        const value = String(prompt || '');
        return SHORTS_PATTERN.test(value) && CREATE_PATTERN.test(value);
    }

    function studioVoiceInstruction(prompt) {
        if (!isShortsPrompt(prompt) || EXPLICIT_VOICE_PATTERN.test(String(prompt || ''))) {
            return '';
        }

        const settings = window.MLXVoice?.getSettings?.();
        const voice = String(settings?.voice || '').trim();
        const speed = Number(settings?.speed);

        if (!voice || !Number.isFinite(speed) || speed < 0.5 || speed > 2.0) {
            return '';
        }

        return `\n\nShorts Studio settings (apply exactly, do not mention in the title or narration): voice=${voice}; voice_speed=${speed}.`;
    }

    function isShortsJob(candidate) {
        return Boolean(
            candidate &&
            typeof candidate === 'object' &&
            candidate.kind !== 'shorts_draft' &&
            typeof candidate.id === 'string' &&
            candidate.project &&
            Array.isArray(candidate.project.scenes)
        );
    }

    function extractJob(payload) {
        const candidates = [
            payload?.data?.job,
            payload?.result?.job,
            payload?.job,
            payload
        ];
        return candidates.find(isShortsJob) || null;
    }

    function observeResponse(response, epoch) {
        if (response.ok === false) return;
        if (!response || typeof response.clone !== 'function') return;
        let cloned;
        try {
            cloned = response.clone();
        } catch (_) {
            return;
        }
        if (!cloned || typeof cloned.json !== 'function') return;
        cloned.json()
            .then(payload => {
                const job = extractJob(payload);
                if (job && epoch === selectionEpoch && (!activeJob || activeJob.id === job.id)) setActiveJob(job);
            })
            .catch(() => {});
    }

    function sceneDraftKey(jobId, sceneId) {
        return `${jobId}:${sceneId}`;
    }

    function getScene(job, sceneId) {
        return (job?.project?.scenes || []).find(scene => scene.id === sceneId) || null;
    }

    function getSceneDraft(job, scene) {
        const key = sceneDraftKey(job.id, scene.id);
        if (!sceneDrafts.has(key)) {
            sceneDrafts.set(key, {
                narration: String(scene.narration || ''),
                video_prompt: String(scene.video_prompt || '')
            });
        }
        return sceneDrafts.get(key);
    }

    function getProjectDraft(job) {
        if (!projectDrafts.has(job.id)) {
            projectDrafts.set(job.id, {
                voice: String(job.project?.voice || ''),
                voice_speed: Number(job.project?.voice_speed ?? 1)
            });
        }
        return projectDrafts.get(job.id);
    }

    function revisionPayload(job, sceneId, draft, projectDraft, forceRegenerateVideo = false) {
        const scene = getScene(job, sceneId);
        if (!scene) return null;

        const payload = {
            force_regenerate_video: Boolean(forceRegenerateVideo)
        };
        const narration = String(draft?.narration ?? '').trim();
        const videoPrompt = String(draft?.video_prompt ?? '').trim();
        const originalNarration = String(scene.narration || '').trim();
        const originalVideoPrompt = String(scene.video_prompt || '').trim();

        if (narration && narration !== originalNarration) {
            payload.narration = narration;
        }
        if (videoPrompt && videoPrompt !== originalVideoPrompt) {
            payload.video_prompt = videoPrompt;
        }

        const voice = String(projectDraft?.voice ?? '').trim();
        const originalVoice = String(job.project?.voice || '').trim();
        if (voice && voice !== originalVoice) {
            payload.voice = voice;
        }

        const speed = Number(projectDraft?.voice_speed);
        const originalSpeed = Number(job.project?.voice_speed ?? 1);
        if (Number.isFinite(speed) && speed >= 0.5 && speed <= 2 && speed !== originalSpeed) {
            payload.voice_speed = speed;
        }

        if (
            !payload.force_regenerate_video &&
            payload.narration === undefined &&
            payload.video_prompt === undefined &&
            payload.voice === undefined &&
            payload.voice_speed === undefined
        ) {
            return null;
        }
        return payload;
    }

    function clearPollTimer() {
        if (pollTimer !== null) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function schedulePoll(job) {
        clearPollTimer();
        if (!job || TERMINAL_STATUSES.has(String(job.status || ''))) return;
        const expectedId = job.id;
        const epoch = selectionEpoch;
        pollTimer = setTimeout(async () => {
            pollTimer = null;
            try {
                const response = await window.fetch(
                    `/api/mlx/shorts-jobs/${encodeURIComponent(expectedId)}`,
                    { cache: 'no-cache' }
                );
                if (response.status === 404) {
                    if (epoch === selectionEpoch && activeJob?.id === expectedId) await recoverMissingJob();
                    return;
                }
                if (!response.ok) { if (epoch === selectionEpoch && activeJob?.id === expectedId) { setFeedback(translate('error_service_unavailable'), true); schedulePoll(activeJob); } return; }
                const payload = await response.json();
                const next = extractJob(payload);
                if (next?.id === expectedId && epoch === selectionEpoch && activeJob?.id === expectedId) {
                    setActiveJob(next);
                }
            } catch (_) {
                if (epoch === selectionEpoch && activeJob?.id === expectedId) {
                    schedulePoll(activeJob);
                }
            }
        }, 1800);
    }

    function loadStyles() {
        if (typeof document === 'undefined') return;
        if (document.querySelector('link[data-mlx-shorts-studio-style]')) return;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/assets/chat/shorts-studio.css?v=20261002-studio-ui';
        link.dataset.mlxShortsStudioStyle = '1';
        document.head.appendChild(link);
    }

    function createElement(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function ensureStudio() {
        if (studio || typeof document === 'undefined' || !document.body) return studio;
        loadStyles();

        const launcher = createElement('button', 'mlx-shorts-studio-launcher', translate('title'));
        launcher.type = 'button';
        launcher.hidden = true;

        const overlay = createElement('div', 'mlx-shorts-studio-overlay');
        const panel = createElement('aside', 'mlx-shorts-studio-panel');
        const header = createElement('div', 'mlx-shorts-studio-header');
        const titleWrap = createElement('div');
        const title = createElement('h2', 'mlx-shorts-studio-title', translate('title'));
        const meta = createElement('div', 'mlx-shorts-studio-meta');
        const close = createElement('button', 'mlx-shorts-studio-close', '×');
        const body = createElement('div', 'mlx-shorts-studio-body');

        close.type = 'button';
        close.setAttribute('aria-label', translate('close'));
        titleWrap.append(title, meta);
        header.append(titleWrap, close);
        panel.append(header, body);
        overlay.appendChild(panel);
        document.body.append(launcher, overlay);

        launcher.addEventListener('click', () => openProjectEditor());
        close.addEventListener('click', () => overlay.classList.remove('is-open'));
        overlay.addEventListener('click', event => {
            if (event.target === overlay) overlay.classList.remove('is-open');
        });

        studio = { launcher, overlay, panel, title, meta, close, body };
        return studio;
    }

    function sceneResultStatus(job, sceneId) {
        const result = (job.scene_results || []).find(item => item.scene_id === sceneId);
        if (result?.status === 'completed') return 'ready';
        if (job.revision_scene_id === sceneId && !TERMINAL_STATUSES.has(String(job.status || ''))) {
            return 'rendering';
        }
        return 'pending';
    }

    function setFeedback(message, isError = false) {
        if (!studio?.feedback) return;
        studio.feedback.textContent = String(message || '');
        studio.feedback.style.color = isError ? '#ff7d7d' : '';
    }

    async function submitRevision(forceRegenerateVideo) {
        const job = activeJob;
        const epoch = selectionEpoch;
        const scene = getScene(job, activeSceneId);
        if (!job || !scene || job.status !== 'completed') return;

        const draft = getSceneDraft(job, scene);
        const projectDraft = getProjectDraft(job);
        const payload = revisionPayload(
            job,
            scene.id,
            draft,
            projectDraft,
            forceRegenerateVideo
        );
        if (!payload) {
            setFeedback(translate('feedback_no_changes'));
            return;
        }

        if (studio?.applyButton) studio.applyButton.disabled = true;
        if (studio?.regenerateButton) studio.regenerateButton.disabled = true;
        setFeedback(translate('feedback_creating'));

        try {
            const response = await window.fetch(
                `/api/mlx/shorts-jobs/${encodeURIComponent(job.id)}/scenes/${encodeURIComponent(scene.id)}/revise`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }
            );
            const data = await response.json().catch(() => ({}));
            if (epoch !== selectionEpoch || activeJob?.id !== job.id) return;
            if (response.status === 404) { await recoverMissingJob(); return; }
            if (!response.ok) {
                throw new Error(
                    translate('error_revision_failed', { status: response.status })
                );
            }
            const revised = extractJob(data);
            if (!revised) throw new Error(translate('error_missing_job'));
            activeSceneId = scene.id;
            setActiveJob(revised);
            setFeedback(translate('feedback_queued'));
        } catch (error) {
            if (epoch !== selectionEpoch || activeJob?.id !== job.id) return;
            setFeedback(translate('error_service_unavailable'), true);
            renderStudio();
        }
    }

    function renderStudio() {
        const ui = ensureStudio();
        if (!ui || !activeJob) return;

        const project = activeJob.project || {};
        const scenes = Array.isArray(project.scenes) ? project.scenes : [];
        if (!scenes.length) return;
        if (!getScene(activeJob, activeSceneId)) activeSceneId = scenes[0].id;

        ui.launcher.hidden = false;
        ui.launcher.textContent = translate('title');
        ui.close.setAttribute('aria-label', translate('close'));
        ui.title.textContent = project.title || translate('title');
        ui.meta.textContent = `${statusLabel(activeJob.status)} · ${project.duration || 0}s · ${scenes.length} ${translate(scenes.length === 1 ? 'scene' : 'scenes')}`;
        ui.body.replaceChildren();

        const preview = createElement('section', 'mlx-shorts-studio-preview');
        if (activeJob.status === 'completed') {
            const video = document.createElement('video');
            video.controls = true;
            video.preload = 'metadata';
            video.src = `/api/mlx/shorts/${encodeURIComponent(activeJob.id)}`;
            video.addEventListener('error', () => { video.hidden = true; preview.append(createElement('p', 'mlx-shorts-studio-status', translate('preview_unavailable'))); }, { once: true });
            preview.appendChild(video);
        } else {
            const placeholder = createElement('div', 'mlx-shorts-studio-status');
            placeholder.textContent = TERMINAL_STATUSES.has(activeJob.status) ? statusLabel(activeJob.status) : `${translate('rendering_prefix')}: ${statusLabel(activeJob.phase || activeJob.status || 'queued')}`;
            preview.appendChild(placeholder);
        }
        const status = createElement('div', 'mlx-shorts-studio-status');
        const revisionInfo = activeJob.parent_job_id
            ? `${translate('revision_of', { id: activeJob.parent_job_id })} `
            : '';
        status.textContent = revisionInfo + (
            activeJob.status === 'completed'
                ? translate('help_completed')
                : TERMINAL_STATUSES.has(activeJob.status) ? '' : translate('help_rendering')
        );
        preview.appendChild(status);
        window.MLXShortsHistory?.renderJobStatus?.(preview, activeJob);
        ui.body.appendChild(preview);
        const projectActions = createElement('div', 'mlx-shorts-studio-actions');
        const editProject = createElement('button', '', translate('edit_project'));
        editProject.disabled = activeJob.status !== 'completed';
        editProject.addEventListener('click', async () => {
            await loadProjectEditor();
            ui.overlay.classList.remove('is-open');
            window.MLXShortsProjectEditor.editJob(activeJob);
        });
        projectActions.append(editProject);
        if (['failed', 'cancelled'].includes(activeJob.status)) {
            const retry = createElement('button', '', translate('history_retry'));
            retry.addEventListener('click', async () => {
                retry.disabled = true;
                const expectedId = activeJob.id, epoch = selectionEpoch;
                try {
                    const response = await fetch(`/api/mlx/shorts-jobs/${encodeURIComponent(expectedId)}/retry`, {method:'POST'});
                    if (!response.ok) throw new Error(translate('error_service_unavailable'));
                    const next = extractJob(await response.json());
                    if (epoch === selectionEpoch && activeJob?.id === expectedId) setActiveJob(next);
                } catch (_) { if (epoch === selectionEpoch && activeJob?.id === expectedId) setFeedback(translate('error_service_unavailable'), true); retry.disabled = false; }
            });
            projectActions.append(retry);
        }
        ui.body.append(projectActions);

        const sceneGrid = createElement('section', 'mlx-shorts-studio-scenes');
        scenes.forEach((scene, index) => {
            const button = createElement('button', 'mlx-shorts-studio-scene');
            button.type = 'button';
            if (scene.id === activeSceneId) button.classList.add('is-active');
            const strong = createElement('strong', '', `${translate('scene')} ${index + 1}${scene.title ? ' · ' + scene.title : ''}`);
            const info = createElement(
                'span',
                '',
                `${scene.duration}s · ${statusLabel(sceneResultStatus(activeJob, scene.id))}`
            );
            button.append(strong, info);
            if (scene.caption) button.append(createElement('span', '', scene.caption));
            if (scene.transition) button.append(createElement('span', '', `${scene.music?.style || project.music_style || 'Auto'} · ${scene.transition.type}`));
            button.addEventListener('click', () => {
                activeSceneId = scene.id;
                renderStudio();
            });
            sceneGrid.appendChild(button);
        });
        ui.body.appendChild(sceneGrid);

        const selected = getScene(activeJob, activeSceneId) || scenes[0];
        const draft = getSceneDraft(activeJob, selected);
        const projectDraft = getProjectDraft(activeJob);
        const editor = createElement('section', 'mlx-shorts-studio-editor');
        const completedMedia = (activeJob.scene_results || []).find(result => result.scene_id === selected.id && result.status === 'completed');
        if (completedMedia?.path) {
            const scenePreview = document.createElement('video');
            scenePreview.controls = true;
            scenePreview.preload = 'metadata';
            scenePreview.className = 'mlx-shorts-scene-preview';
            scenePreview.src = `/api/mlx/shorts/jobs/${encodeURIComponent(activeJob.id)}/scenes/${encodeURIComponent(selected.id)}/video`;
            scenePreview.addEventListener('error', () => { scenePreview.hidden = true; editor.append(createElement('p', 'mlx-shorts-studio-status', translate('preview_unavailable'))); }, { once: true });
            editor.append(scenePreview);
        }

        const narrationField = createElement('div', 'mlx-shorts-studio-field');
        const narrationLabel = createElement('label', '', translate('narration'));
        const narration = document.createElement('textarea');
        narration.value = draft.narration;
        narration.addEventListener('input', () => {
            draft.narration = narration.value;
        });
        narrationField.append(narrationLabel, narration);

        const promptField = createElement('div', 'mlx-shorts-studio-field');
        const promptLabel = createElement('label', '', translate('visual_prompt'));
        const visualPrompt = document.createElement('textarea');
        visualPrompt.value = draft.video_prompt;
        visualPrompt.addEventListener('input', () => {
            draft.video_prompt = visualPrompt.value;
        });
        promptField.append(promptLabel, visualPrompt);

        const controls = createElement('div', 'mlx-shorts-studio-controls');
        const voiceField = createElement('div', 'mlx-shorts-studio-field');
        const voiceLabel = createElement('label', '', translate('voice_profile'));
        const voice = document.createElement('input');
        voice.type = 'text';
        voice.value = projectDraft.voice;
        voice.placeholder = translate('voice_placeholder');
        voice.addEventListener('input', () => {
            projectDraft.voice = voice.value;
        });
        voiceField.append(voiceLabel, voice);

        const speedField = createElement('div', 'mlx-shorts-studio-field');
        const speedLabel = createElement('label', '', translate('voice_speed'));
        const speed = document.createElement('input');
        speed.type = 'number';
        speed.min = '0.5';
        speed.max = '2';
        speed.step = '0.05';
        speed.value = String(projectDraft.voice_speed || 1);
        speed.addEventListener('input', () => {
            projectDraft.voice_speed = Number(speed.value);
        });
        speedField.append(speedLabel, speed);
        controls.append(voiceField, speedField);

        const actions = createElement('div', 'mlx-shorts-studio-actions');
        const apply = createElement('button', '', translate('apply_revision'));
        const regenerate = createElement('button', '', translate('regenerate_video'));
        apply.type = 'button';
        regenerate.type = 'button';
        apply.dataset.primary = '1';
        const editable = activeJob.status === 'completed';
        apply.disabled = !editable;
        regenerate.disabled = !editable;
        apply.addEventListener('click', () => submitRevision(false));
        regenerate.addEventListener('click', () => submitRevision(true));
        actions.append(apply, regenerate);

        const feedback = createElement('div', 'mlx-shorts-studio-feedback');
        editor.append(narrationField, promptField, controls, actions, feedback);
        ui.body.appendChild(editor);
        ui.feedback = feedback;
        ui.applyButton = apply;
        ui.regenerateButton = regenerate;
    }

    function setActiveJob(job) {
        if (!isShortsJob(job)) return;
        const changedJob = activeJob?.id !== job.id;
        if (changedJob) selectionEpoch += 1;
        activeJob = job;
        if (changedJob && !getScene(job, activeSceneId)) {
            activeSceneId = job.project.scenes[0]?.id || null;
        }
        renderStudio();
        schedulePoll(job);
    }

    function refreshLanguage() {
        const ui = ensureStudio();
        if (ui) {
            ui.launcher.textContent = translate('title');
            ui.close.setAttribute('aria-label', translate('close'));
            if (!activeJob) ui.title.textContent = translate('title');
        }
        if (activeJob) renderStudio();
    }

    function loadStudioTranslations() {
        if (translationsPromise) return translationsPromise;
        if (window.__MLXShortsStudioTranslations) return Promise.resolve(studioTranslations);
        translationsPromise = previousFetch('/i18n/shorts-studio.json', { cache: 'no-cache' })
            .then(response => {
                if (!response.ok || typeof response.json !== 'function') {
                    throw new Error('Could not load Shorts Studio translations.');
                }
                return response.json();
            })
            .then(payload => {
                if (payload && typeof payload === 'object') {
                    studioTranslations = payload;
                    window.__MLXShortsStudioTranslations = payload;
                }
                refreshLanguage();
                return studioTranslations;
            })
            .catch(error => {
                console.warn('[Shorts Studio i18n]', error);
                return studioTranslations;
            });
        return translationsPromise;
    }

    window.fetch = async function mlxShortsStudioFetch(input, init) {
        const path = requestPath(input);
        let forwardedInit = init;

        if (['/api/mlx/chat/actions', '/api/mlx/shorts/plan'].includes(path) && init?.body) {
            try {
                const body = JSON.parse(init.body);
                const instruction = studioVoiceInstruction(body?.prompt);
                if (instruction) {
                    forwardedInit = {
                        ...init,
                        body: JSON.stringify({
                            ...body,
                            prompt: String(body.prompt || '') + instruction
                        })
                    };
                }
            } catch (_) {}
        }

        const epoch = selectionEpoch;
        const response = await previousFetch(input, forwardedInit);
        if (
            path === '/api/mlx/chat/actions'
        ) {
            observeResponse(response, epoch);
        }
        return response;
    };

    if (typeof document !== 'undefined') {
        document.addEventListener('mlx-i18n-ready', () => {
            loadStudioTranslations();
            refreshLanguage();
        });
        document.addEventListener('mlx-language-changed', refreshLanguage);
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                ensureStudio();
                loadStudioTranslations();
            }, { once: true });
        } else {
            ensureStudio();
            loadStudioTranslations();
        }
    }


    let editorPromise = null;
    function loadProjectEditor() {
        if (window.MLXShortsProjectEditor) return Promise.resolve();
        if (!editorPromise) editorPromise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = '/assets/chat/shorts-project-editor.js?v=20261002-studio-ui';
            script.onload = resolve;
            script.onerror = () => { editorPromise = null; reject(new Error(translate('error_service_unavailable'))); };
            document.head.append(script);
        });
        return editorPromise;
    }
    function clearActiveJob() {
        selectionEpoch += 1;
        clearPollTimer(); activeJob = null; activeSceneId = null;
        sceneDrafts.clear(); projectDrafts.clear();
        if (studio) { studio.overlay.classList.remove('is-open'); studio.body.replaceChildren(); studio.meta.textContent = ''; }
    }
    async function recoverMissingJob() {
        clearActiveJob();
        await openProjectEditor();
        window.MLXShortsProjectEditor?.showNotice?.(translate('missing_job'));
    }
    async function loadJob(jobId) {
        if (typeof jobId !== 'string' || !jobId.trim()) { await recoverMissingJob(); return false; }
        if (await window.MLXShortsProjectEditor?.resetSelection?.() === false) return false;
        clearActiveJob();
        const epoch = selectionEpoch;
        const response = await window.fetch('/api/mlx/shorts-jobs/' + encodeURIComponent(jobId), { cache: 'no-store' });
        if (epoch !== selectionEpoch) return false;
        if (response.status === 404) { await recoverMissingJob(); return false; }
        if (!response.ok) {
            await openProjectEditor();
            window.MLXShortsProjectEditor?.showNotice?.(translate('error_service_unavailable'));
            throw new Error(translate('error_service_unavailable'));
        }
        const job = extractJob(await response.json());
        if (epoch !== selectionEpoch) return false;
        if (!job || job.id !== jobId) throw new Error(translate('error_missing_job'));
        setActiveJob(job);
        window.MLXShortsStudio.openJob();
        return true;
    }
    function jobsDeleted(jobIds) {
        window.MLXShortsProjectEditor?.sourceDeleted?.(jobIds);
        if (activeJob && jobIds.includes(activeJob.id)) {
            clearActiveJob();
            window.MLXShortsProjectEditor?.resetSelection?.();
        }
    }
    async function openProjectEditor(draft = null) {
        clearActiveJob();
        ensureStudio();
        await Promise.all([loadProjectEditor(), loadStudioTranslations()]);
        return window.MLXShortsProjectEditor.open(draft);
    }

    window.MLXShortsStudio = {
        setActiveJob, clearActiveJob, loadJob, jobsDeleted,
        selectionToken: () => selectionEpoch,
        openDraft: openProjectEditor,
        async newDraft() { ensureStudio(); await Promise.all([loadProjectEditor(), loadStudioTranslations()]); return window.MLXShortsProjectEditor.newDraft(); },
        openJob() { const ui = ensureStudio(); if (ui && activeJob) ui.overlay.classList.add('is-open'); },
        isShortsPrompt,
        studioVoiceInstruction,
        extractJob,
        revisionPayload,
        translate,
        statusLabel,
        getActiveJob() {
            return activeJob;
        },
        open() { return openProjectEditor(); }
    };
})();
