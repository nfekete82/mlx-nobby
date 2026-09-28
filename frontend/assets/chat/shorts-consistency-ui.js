(function () {
    'use strict';

    function activeJob() {
        return window.MLXShortsStudio?.getActiveJob?.() || null;
    }

    function selectedScene(job) {
        const buttons = Array.from(document.querySelectorAll('.mlx-shorts-studio-scene'));
        const index = buttons.findIndex(button => button.classList.contains('is-active'));
        const scenes = job?.project?.scenes || [];
        return scenes[index >= 0 ? index : 0] || null;
    }

    function keyframeFor(job, sceneId) {
        return (job?.keyframe_results || []).find(
            item => item.scene_id === sceneId && item.status === 'completed'
        ) || null;
    }

    function buildSettingsPayload(job, values, forceKeyframe = false) {
        const project = job?.project || {};
        const payload = {};
        const mode = Boolean(values.consistency_mode);
        const character = Boolean(values.character_consistency);
        const style = Boolean(values.style_consistency);
        const strength = Number(values.style_strength);

        if (mode !== Boolean(project.consistency_mode)) {
            payload.consistency_mode = mode;
        }
        if (character !== Boolean(project.character_consistency ?? true)) {
            payload.character_consistency = character;
        }
        if (style !== Boolean(project.style_consistency ?? true)) {
            payload.style_consistency = style;
        }
        if (
            Number.isFinite(strength) &&
            strength >= 0 && strength <= 1 &&
            strength !== Number(project.style_strength ?? 0.8)
        ) {
            payload.style_strength = strength;
        }
        if (forceKeyframe) {
            payload.force_regenerate_keyframe = true;
        }
        return payload;
    }

    function loadStyles() {
        if (document.querySelector('link[data-mlx-shorts-consistency-style]')) return;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/assets/chat/shorts-consistency.css?v=20260928-consistency-v1';
        link.dataset.mlxShortsConsistencyStyle = '1';
        document.head.appendChild(link);
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function bibleText(project) {
        const bible = project?.visual_bible;
        if (!bible) return 'No explicit visual bible stored. A project fallback will be used.';
        const lines = [];
        if (bible.style) lines.push(`Style: ${bible.style}`);
        if (bible.character) lines.push(`Character: ${bible.character}`);
        if (bible.environment) lines.push(`Environment: ${bible.environment}`);
        if (bible.palette) lines.push(`Palette: ${bible.palette}`);
        if (bible.camera) lines.push(`Camera: ${bible.camera}`);
        if (Array.isArray(bible.continuity_rules) && bible.continuity_rules.length) {
            lines.push(`Rules: ${bible.continuity_rules.join(' · ')}`);
        }
        return lines.join('\n') || 'Visual bible is empty; project fallback will be used.';
    }

    async function submit(job, scene, payload, feedback) {
        if (!job || !scene || !Object.keys(payload).length) {
            feedback.textContent = 'No consistency changes to render.';
            return;
        }
        feedback.textContent = 'Creating consistency revision…';
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
            feedback.textContent = 'Consistency revision queued.';
        } catch (error) {
            feedback.textContent = error?.message || String(error);
            feedback.classList.add('is-error');
        }
    }

    function augment() {
        const job = activeJob();
        const editor = document.querySelector('.mlx-shorts-studio-editor');
        if (!job || !editor || editor.querySelector('[data-mlx-shorts-consistency]')) return;

        loadStyles();
        const project = job.project || {};
        const scene = selectedScene(job);
        if (!scene) return;

        const section = element('section', 'mlx-shorts-consistency');
        section.dataset.mlxShortsConsistency = '1';
        const heading = element('div', 'mlx-shorts-consistency-heading');
        heading.append(
            element('strong', '', 'Visual consistency'),
            element('span', '', 'Qwen Image keyframe → LTX image-to-video')
        );

        const grid = element('div', 'mlx-shorts-consistency-grid');
        const modeLabel = element('label', 'mlx-shorts-consistency-toggle');
        const mode = document.createElement('input');
        mode.type = 'checkbox';
        mode.checked = Boolean(project.consistency_mode);
        modeLabel.append(mode, document.createTextNode(' Consistency mode'));

        const characterLabel = element('label', 'mlx-shorts-consistency-toggle');
        const character = document.createElement('input');
        character.type = 'checkbox';
        character.checked = Boolean(project.character_consistency ?? true);
        characterLabel.append(character, document.createTextNode(' Character continuity'));

        const styleLabel = element('label', 'mlx-shorts-consistency-toggle');
        const style = document.createElement('input');
        style.type = 'checkbox';
        style.checked = Boolean(project.style_consistency ?? true);
        styleLabel.append(style, document.createTextNode(' Style continuity'));
        grid.append(modeLabel, characterLabel, styleLabel);

        const strengthField = element('label', 'mlx-shorts-consistency-strength');
        const strengthTitle = element('span', '', 'Continuity strength');
        const strengthValue = element('output', '', `${Math.round(Number(project.style_strength ?? 0.8) * 100)}%`);
        const strength = document.createElement('input');
        strength.type = 'range';
        strength.min = '0';
        strength.max = '1';
        strength.step = '0.05';
        strength.value = String(project.style_strength ?? 0.8);
        strength.addEventListener('input', () => {
            strengthValue.textContent = `${Math.round(Number(strength.value) * 100)}%`;
        });
        const strengthHeader = element('div', 'mlx-shorts-consistency-strength-header');
        strengthHeader.append(strengthTitle, strengthValue);
        strengthField.append(strengthHeader, strength);

        const media = element('div', 'mlx-shorts-consistency-media');
        const keyframe = keyframeFor(job, scene.id);
        if (keyframe?.image_id) {
            const image = document.createElement('img');
            image.loading = 'lazy';
            image.alt = `Keyframe for ${scene.id}`;
            image.src = `/api/mlx/images/${encodeURIComponent(keyframe.image_id)}`;
            media.appendChild(image);
        } else {
            media.appendChild(element('div', 'mlx-shorts-consistency-empty', 'No keyframe stored for this scene yet.'));
        }
        const bible = element('pre', 'mlx-shorts-consistency-bible', bibleText(project));
        media.appendChild(bible);

        const actions = element('div', 'mlx-shorts-consistency-actions');
        const apply = element('button', '', 'Apply consistency');
        const regenerate = element('button', '', 'Regenerate keyframe + video');
        const feedback = element('div', 'mlx-shorts-consistency-feedback');
        apply.type = 'button';
        regenerate.type = 'button';
        apply.dataset.primary = '1';
        const editable = job.status === 'completed';
        apply.disabled = !editable;
        regenerate.disabled = !editable;

        function values() {
            return {
                consistency_mode: mode.checked,
                character_consistency: character.checked,
                style_consistency: style.checked,
                style_strength: Number(strength.value)
            };
        }

        apply.addEventListener('click', () => {
            submit(job, scene, buildSettingsPayload(job, values(), false), feedback);
        });
        regenerate.addEventListener('click', () => {
            const payload = buildSettingsPayload(job, values(), true);
            if (!mode.checked) payload.consistency_mode = true;
            const textareas = editor.querySelectorAll('textarea');
            const visualPrompt = String(textareas[1]?.value || '').trim();
            if (visualPrompt && visualPrompt !== String(scene.video_prompt || '').trim()) {
                payload.video_prompt = visualPrompt;
            }
            submit(job, scene, payload, feedback);
        });
        actions.append(apply, regenerate);

        section.append(heading, grid, strengthField, media, actions, feedback);
        editor.prepend(section);
    }

    function init() {
        loadStyles();
        augment();
        const observer = new MutationObserver(augment);
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }

    window.MLXShortsConsistency = {
        buildSettingsPayload,
        keyframeFor
    };
})();
