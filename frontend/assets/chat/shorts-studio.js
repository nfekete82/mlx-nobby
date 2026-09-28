(function () {
    'use strict';

    const SHORTS_PATTERN = /\b(?:shorts?|short[\s-]*videos?|youtube[\s-]+shorts?|tiktoks?(?:[\s-]+videos?)?|reels?|kurzvideos?)\b/iu;
    const CREATE_PATTERN = /\b(?:erstelle|erstellen|generiere|generieren|erzeuge|erzeugen|mach|mache|produziere|produzieren|möchte|moechte|will|brauche|create|generate|make|produce|want|need)\b/iu;
    const EXPLICIT_VOICE_PATTERN = /\b(?:stimme|voice|sprecher(?:in)?|speaker|sprechgeschwindigkeit|geschwindigkeit|voice[_ -]?speed|speed)\b/iu;
    const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);
    const previousFetch = window.fetch.bind(window);

    let activeJob = null;
    let activeSceneId = null;
    let pollTimer = null;
    let studio = null;
    const sceneDrafts = new Map();
    const projectDrafts = new Map();

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

    function observeResponse(response) {
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
                if (job) setActiveJob(job);
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
        pollTimer = setTimeout(async () => {
            pollTimer = null;
            try {
                const response = await window.fetch(
                    `/api/mlx/shorts-jobs/${encodeURIComponent(expectedId)}`,
                    { cache: 'no-cache' }
                );
                if (!response.ok) return;
                const payload = await response.json();
                const next = extractJob(payload);
                if (next && activeJob?.id === expectedId) {
                    setActiveJob(next);
                }
            } catch (_) {
                if (activeJob?.id === expectedId) {
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
        link.href = '/assets/chat/shorts-studio.css?v=20260928-shorts-studio-v2';
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

        const launcher = createElement('button', 'mlx-shorts-studio-launcher', 'Shorts Studio');
        launcher.type = 'button';
        launcher.hidden = true;

        const overlay = createElement('div', 'mlx-shorts-studio-overlay');
        const panel = createElement('aside', 'mlx-shorts-studio-panel');
        const header = createElement('div', 'mlx-shorts-studio-header');
        const titleWrap = createElement('div');
        const title = createElement('h2', 'mlx-shorts-studio-title', 'Shorts Studio');
        const meta = createElement('div', 'mlx-shorts-studio-meta');
        const close = createElement('button', 'mlx-shorts-studio-close', '×');
        const body = createElement('div', 'mlx-shorts-studio-body');

        close.type = 'button';
        close.setAttribute('aria-label', 'Close Shorts Studio');
        titleWrap.append(title, meta);
        header.append(titleWrap, close);
        panel.append(header, body);
        overlay.appendChild(panel);
        document.body.append(launcher, overlay);

        launcher.addEventListener('click', () => overlay.classList.add('is-open'));
        close.addEventListener('click', () => overlay.classList.remove('is-open'));
        overlay.addEventListener('click', event => {
            if (event.target === overlay) overlay.classList.remove('is-open');
        });

        studio = { launcher, overlay, panel, title, meta, body };
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
            setFeedback('No changes to render.');
            return;
        }

        if (studio?.applyButton) studio.applyButton.disabled = true;
        if (studio?.regenerateButton) studio.regenerateButton.disabled = true;
        setFeedback('Creating revision…');

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
            if (!response.ok) {
                throw new Error(data?.detail || `Revision failed (${response.status})`);
            }
            const revised = extractJob(data);
            if (!revised) throw new Error('Revision response did not contain a Shorts job.');
            activeSceneId = scene.id;
            setActiveJob(revised);
            setFeedback('Revision queued.');
        } catch (error) {
            setFeedback(error?.message || String(error), true);
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
        ui.title.textContent = project.title || 'Shorts Studio';
        ui.meta.textContent = `${activeJob.status || 'unknown'} · ${project.duration || 0}s · ${scenes.length} scenes`;
        ui.body.replaceChildren();

        const preview = createElement('section', 'mlx-shorts-studio-preview');
        if (activeJob.status === 'completed') {
            const video = document.createElement('video');
            video.controls = true;
            video.preload = 'metadata';
            video.src = `/api/mlx/shorts/${encodeURIComponent(activeJob.id)}`;
            preview.appendChild(video);
        } else {
            const placeholder = createElement('div', 'mlx-shorts-studio-status');
            placeholder.textContent = `Rendering: ${activeJob.phase || activeJob.status || 'queued'}`;
            preview.appendChild(placeholder);
        }
        const status = createElement('div', 'mlx-shorts-studio-status');
        const revisionInfo = activeJob.parent_job_id
            ? `Revision of ${activeJob.parent_job_id}. `
            : '';
        status.textContent = revisionInfo + (
            activeJob.status === 'completed'
                ? 'Select a scene, edit narration or visual prompt, then create a revision. Narration-only changes reuse the existing scene video.'
                : 'The current revision is still rendering. Editing is enabled again after completion.'
        );
        preview.appendChild(status);
        ui.body.appendChild(preview);

        const sceneGrid = createElement('section', 'mlx-shorts-studio-scenes');
        scenes.forEach((scene, index) => {
            const button = createElement('button', 'mlx-shorts-studio-scene');
            button.type = 'button';
            if (scene.id === activeSceneId) button.classList.add('is-active');
            const strong = createElement('strong', '', `Scene ${index + 1}`);
            const info = createElement(
                'span',
                '',
                `${scene.duration}s · ${sceneResultStatus(activeJob, scene.id)}`
            );
            button.append(strong, info);
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

        const narrationField = createElement('div', 'mlx-shorts-studio-field');
        const narrationLabel = createElement('label', '', 'Narration');
        const narration = document.createElement('textarea');
        narration.value = draft.narration;
        narration.addEventListener('input', () => {
            draft.narration = narration.value;
        });
        narrationField.append(narrationLabel, narration);

        const promptField = createElement('div', 'mlx-shorts-studio-field');
        const promptLabel = createElement('label', '', 'Visual prompt');
        const visualPrompt = document.createElement('textarea');
        visualPrompt.value = draft.video_prompt;
        visualPrompt.addEventListener('input', () => {
            draft.video_prompt = visualPrompt.value;
        });
        promptField.append(promptLabel, visualPrompt);

        const controls = createElement('div', 'mlx-shorts-studio-controls');
        const voiceField = createElement('div', 'mlx-shorts-studio-field');
        const voiceLabel = createElement('label', '', 'Voice profile');
        const voice = document.createElement('input');
        voice.type = 'text';
        voice.value = projectDraft.voice;
        voice.placeholder = 'Use current/default voice';
        voice.addEventListener('input', () => {
            projectDraft.voice = voice.value;
        });
        voiceField.append(voiceLabel, voice);

        const speedField = createElement('div', 'mlx-shorts-studio-field');
        const speedLabel = createElement('label', '', 'Voice speed');
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
        const apply = createElement('button', '', 'Apply revision');
        const regenerate = createElement('button', '', 'Regenerate scene video');
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
        activeJob = job;
        if (changedJob && !getScene(job, activeSceneId)) {
            activeSceneId = job.project.scenes[0]?.id || null;
        }
        renderStudio();
        schedulePoll(job);
    }

    window.fetch = async function mlxShortsStudioFetch(input, init) {
        const path = requestPath(input);
        let forwardedInit = init;

        if (path === '/api/mlx/chat/actions' && init?.body) {
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

        const response = await previousFetch(input, forwardedInit);
        if (
            path === '/api/mlx/chat/actions' ||
            path.startsWith('/api/mlx/shorts-jobs/')
        ) {
            observeResponse(response);
        }
        return response;
    };

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', ensureStudio, { once: true });
        } else {
            ensureStudio();
        }
    }

    window.MLXShortsStudio = {
        isShortsPrompt,
        studioVoiceInstruction,
        extractJob,
        revisionPayload,
        getActiveJob() {
            return activeJob;
        },
        open() {
            const ui = ensureStudio();
            if (ui && activeJob) ui.overlay.classList.add('is-open');
        }
    };
})();
