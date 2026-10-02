/* Durable pre-production editor; the existing Studio owns render job polling. */
(function () {
    'use strict';
    const base = '/api/mlx/shorts';
    function t(key, params = {}) {
        const language = window.MLXI18n?.getLanguage?.() || 'en';
        const translations = window.__MLXShortsStudioTranslations || {};
        const fallback = translations[language]?.[key] || translations.en?.[key] || key;
        let value = window.MLXI18n?.t?.('shorts_studio.' + key, fallback) || fallback;
        for (const [name, replacement] of Object.entries(params)) value = value.replaceAll('{' + name + '}', String(replacement));
        return value;
    }
    let sourceJob = null;
    let draft = null, selected = null, capabilities = null, ui = null, busy = false;
    let sceneCount = 4;
    let providerReadiness = null, saveTimer = null, saveState = 'saved';
    async function refreshReadiness() {
        if (!draft) return;
        providerReadiness = draft.project.consistency_mode ? await api('/drafts/' + draft.id + '/preflight') : {available: true, warnings: []};
    }
    function dirty() {
        saveState = 'dirty';
        if (ui?.saveStatus) ui.saveStatus.textContent = t('editor_unsaved');
        if (saveTimer !== null) window.clearTimeout?.(saveTimer);
        const scheduledDraft = draft;
        saveTimer = window.setTimeout?.(() => {
            saveTimer = null;
            if (!draft || draft !== scheduledDraft) return;
            if (busy) { dirty(); return; }
            return run(() => { if (draft === scheduledDraft && saveState !== 'saved') return save(); });
        }, 1000) ?? null;
    }
    window.addEventListener?.('beforeunload', event => {
        if (!draft || saveState === 'saved') return;
        event.preventDefault(); event.returnValue = '';
    });
    let expertMode = false;
    try { expertMode = window.localStorage?.getItem('mlx-shorts-expert-mode') === 'true'; } catch (_) {}
    function accordion(parent, label) {
        const details = node('details', 'mlx-shorts-expert-section');
        details.append(node('summary', '', label)); parent.append(details); return details;
    }
    let view = 'welcome', draftItems = [];
    let actionQueue = Promise.resolve();
    const clone = value => JSON.parse(JSON.stringify(value));
    const node = (tag, className, text) => {
        const el = document.createElement(tag);
        if (className) el.className = className;
        if (text !== undefined) el.textContent = text;
        return el;
    };
    async function api(path, method = 'GET', body) {
        const response = await fetch(base + path, {
            method, headers: { 'Content-Type': 'application/json' },
            ...(body === undefined ? {} : { body: JSON.stringify(body) })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            let inputHint = t('editor_the_action_could_not_be_completed_please_check');
            if (typeof result.detail === 'string' && result.detail.includes('cannot be divided'))
                inputHint = t('editor_duration_scene_count_and_quality_are_incompatible');
            if (typeof result.detail === 'string' && /Keyframe-Generator|Bildgenerator|Image-Dienst/.test(result.detail))
                inputHint = t('editor_no_compatible_keyframe_generator_available_please_check_the');
            const error = new Error(response.status === 404
                ? t('editor_the_selected_draft_is_no_longer_available')
                : response.status >= 500
                    ? t('editor_the_shorts_service_is_unavailable_please_try_again')
                    : inputHint);
            error.status = response.status;
            throw error;
        }
        return result;
    }
    function button(text, action, parent, disabled = false) {
        const el = node('button', '', text);
        el.type = 'button'; el.disabled = busy || disabled;
        el.addEventListener('click', () => run(action));
        parent.append(el); return el;
    }
    function message(text, error = false) {
        ui.feedback.textContent = text;
        ui.feedback.classList.toggle('is-error', error);
    }
    function run(action) {
        const next = actionQueue.then(() => perform(action));
        actionQueue = next.catch(() => {});
        return next;
    }
    async function perform(action) {
        const before = draft ? {id:draft.id, version:draft.version, project:JSON.stringify(draft.project)} : null;
        busy = true;
        ui.overlay.querySelectorAll('button').forEach(b => { b.disabled = true; });
        // Freeze inputs while planning/saving so an asynchronous result cannot discard edits.
        ui.overlay.querySelectorAll('input,textarea,select').forEach(el => { el.disabled = true; });
        message(t('editor_working'));
        try {
            await action();
            if (before && draft?.id === before.id && draft.version === before.version && JSON.stringify(draft.project) !== before.project) dirty();
            if (ui.feedback.textContent === t('editor_working')) message(t('editor_ready'));
            return true;
        }
        catch (error) {
            if (saveState === 'saving') saveState = 'dirty';
            if (error.status === 404 && !error.keepDraft) reset();
            message(error.status ? error.message : t('editor_shorts_studio_could_not_complete_the_action'), true);
            return false;
        }
        finally { busy = false; ui.overlay.querySelectorAll('button,input,textarea,select').forEach(el => { el.disabled = false; }); render(); }
    }
    function field(parent, label, object, key, type = 'text', options = null) {
        const wrap = node('label', 'mlx-shorts-studio-field');
        wrap.append(node('span', '', label));
        const input = node(options ? 'select' : type === 'textarea' ? 'textarea' : 'input');
        if (options) options.forEach(option => {
            const [value, text] = Array.isArray(option) ? option : [option, option];
            const optionKey = 'editor_option_' + value;
            const optionLabel = window.__MLXShortsStudioTranslations?.en?.[optionKey] ? t(optionKey) : text;
            const el = node('option', '', optionLabel); el.value = value; input.append(el);
        });
        else if (type !== 'textarea') input.type = type;
        if (type === 'checkbox') input.checked = Boolean(object[key]);
        else input.value = object[key] ?? '';
        if (type === 'number') input.step = 'any';
        input.addEventListener('input', () => {
            if (draft && expertMode && ((object === draft.project && key.startsWith('music_')) || draft.project.scenes.some(scene => scene.music === object))) draft.project.music_selection = 'custom';
            object[key] = type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value;
            if (key === 'voice' || key === 'music_track' || key === 'track') object[key] = input.value || null;
            if (key === 'quality' || key === 'music_mode' || key === 'music_track' || key === 'track') render();
            validate();
            if (draft && (object === draft.project || Object.values(draft.project).includes(object) || draft.project.scenes.some(scene => object === scene || Object.values(scene).includes(object)))) dirty();
        });
        wrap.append(input); parent.append(wrap); return input;
    }
    const styles = ['cinematic', 'futuristic', 'dark', 'emotional', 'energetic', 'ambient'];
    function trackOptions(kind) {
        return [['', t('editor_auto')], ...(capabilities?.[kind] || []).map(t => [t.track, t.track])];
    }
    function musicFields(parent, settings, global = false) {
        field(parent, t('editor_enable_music'), settings, global ? 'music_enabled' : 'enabled', 'checkbox');
        field(parent, t('editor_music_style'), settings, global ? 'music_style' : 'style', 'text', styles);
        field(parent, t('editor_track'), settings, global ? 'music_track' : 'track', 'text', trackOptions('music'));
        field(parent, t('editor_volume_0_1'), settings, global ? 'music_volume' : 'volume', 'number');
        if (!global) {
            ['start_offset', 'fade_in', 'fade_out'].forEach(key => field(parent, t('editor_option_' + key) + ' (s)', settings, key, 'number'));
            field(parent, t('editor_duck_under_voice'), settings, 'duck_under_voice', 'checkbox');
        }
        if (!(capabilities?.music || []).length) parent.append(node('p', '', t('editor_music_library_is_empty_add_local_tracks_to')));
        const track = settings[global ? 'music_track' : 'track'];
        if (track) {
            const audio = node('audio'); audio.controls = true; audio.preload = 'none';
            audio.src = base + '/library/music/' + track.split('/').map(encodeURIComponent).join('/'); previewMedia(audio, parent);
        }
    }
    function errors(project) {
        const result = [], allowed = capabilities?.qualities?.[project.quality]?.durations;
        if (!project.scenes.length) result.push(t('editor_add_at_least_one_scene'));
        const total = project.scenes.reduce((sum, scene) => sum + scene.duration, 0);
        if (total !== project.duration) result.push(t('editor_the_total_duration_does_not_match'));
        if (!allowed) result.push(t('editor_loading_quality_profiles'));
        if (!project.title.trim()) result.push(t('editor_please_enter_a_title'));
        if (!/^[a-z]{2}$/.test(project.language)) result.push(t('editor_please_choose_a_valid_language'));
        if (!Number.isInteger(project.duration) || project.duration < 5 || project.duration > 300) result.push(t('editor_choose_a_total_duration_from_5_to_300'));
        if (!Number.isFinite(project.voice_speed) || project.voice_speed < .5 || project.voice_speed > 2) result.push(t('editor_please_check_voice_speed'));
        if (project.voice && !/^[A-Za-z0-9_-]+$/.test(project.voice)) result.push(t('editor_please_check_the_voice_profile'));
        if (project.consistency_mode && !draft?.source_job_id && providerReadiness?.available === false)
            result.push(t('editor_no_compatible_keyframe_generator_available_please_check_the'));
        project.scenes.forEach((scene, i) => {
            if (allowed && !allowed.includes(scene.duration)) result.push(expertMode
                ? t('editor_scene_value1_allowed_durations_value2_s', {value1: i+1, value2: allowed.join(', ')})
                : t('editor_scene_value1_duration_is_not_supported_by_this', {value1: i+1}));
            if (!scene.video_prompt.trim()) result.push(expertMode
                ? t('editor_scene_value1_video_prompt_is_required', {value1: i+1})
                : t('editor_scene_value1_needs_an_ai_plan', {value1: i+1}));
        });
        return result;
    }
    const warningText = key => ({
        music_unavailable: t('editor_no_suitable_local_music_found_rendering_will_continue'),
        music_track_missing: t('editor_music_track_missing_using_auto_or_no_music'),
        sfx_unavailable: t('editor_missing_sound_effect_was_disabled'),
        timeline_normalized: t('editor_scene_durations_were_allocated_to_fit_the_timeline'),
        caption_defaults: t('editor_caption_defaults_were_used'),
        transition_defaults: t('editor_safe_transition_defaults_were_used'),
        music_defaults: t('editor_safe_music_defaults_were_used'),
        sfx_defaults: t('editor_safe_sound_effect_defaults_were_used'),
        character_anchor_fallback: t('editor_character_anchor_unavailable_using_regular_visual_consistency')
    }[key] || '');
    function validate() {
        if (!draft || !ui?.timeline) return;
        const p = draft.project, invalid = errors(p);
        ui.timeline.replaceChildren();
        ui.timeline.append(node('strong', '', invalid.length ? t('editor_not_ready_yet') : t('editor_ready_to_render')));
        ui.timeline.append(node('p', '', t('editor_value1_seconds_value2_scenes', {value1: p.duration, value2: p.scenes.length})));
        (expertMode ? invalid : invalid.slice(0, 3)).forEach(text => ui.timeline.append(node('p', '', text)));
        const warnings = [...(draft.warnings || []), ...(providerReadiness?.warnings || [])].map(warningText).filter(Boolean);
        if (p.music_selection === 'auto' && !(capabilities?.music || []).length && !warnings.length)
            warnings.push(warningText('music_unavailable'));
        (expertMode ? warnings : warnings.slice(0, 1)).forEach(text => ui.timeline.append(node('p', 'mlx-shorts-studio-warning', text)));
        ui.renderButton.disabled = busy || invalid.length > 0;
        ui.timeline.classList.toggle('is-error', invalid.length > 0);
    }
    function ensure() {
        if (ui) return;
        const overlay = node('div', 'mlx-shorts-studio-overlay mlx-shorts-project-overlay');
        overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-label', 'Shorts Studio');
        const panel = node('section', 'mlx-shorts-studio-panel');
        const header = node('header', 'mlx-shorts-studio-header');
        header.append(node('h2', '', t('editor_shorts_studio_pre_production')));
        const actions = node('div', 'mlx-shorts-studio-actions');
        button(t('editor_new_short'), newDraft, actions);
        button(t('editor_my_drafts'), list, actions);
        button(t('editor_my_shorts_history'), async () => { await saveBeforeNavigation(); reset(); overlay.classList.remove('is-open'); window.MLXShortsHistory?.open(); }, actions);
        button(t('editor_close'), async () => { await saveBeforeNavigation(); overlay.classList.remove('is-open'); }, actions);
        const preference = { enabled: expertMode };
        const toggle = field(actions, t('editor_expert_mode'), preference, 'enabled', 'checkbox');
        toggle.addEventListener('input', () => {
            expertMode = preference.enabled;
            try { window.localStorage?.setItem('mlx-shorts-expert-mode', String(expertMode)); } catch (_) {}
            render();
        });
        header.append(actions);
        const feedback = node('div', 'mlx-shorts-studio-feedback');
        const body = node('div', 'mlx-shorts-studio-body');
        panel.append(header, feedback, body); overlay.append(panel); document.body.append(overlay);
        ui = { overlay, body, feedback, headerActions: actions,
            headerLabels: () => [t('editor_new_short'), t('editor_my_drafts'), t('editor_my_shorts_history'), t('editor_close')] };
    }
    function reset() {
        draft = null; sourceJob = null; selected = null;
        sceneCount = 4; view = 'welcome'; draftItems = [];
        providerReadiness = null;
        if (saveTimer !== null) window.clearTimeout?.(saveTimer);
        saveTimer = null; saveState = 'saved';
        if (ui) { ui.timeline = null; ui.renderButton = null; }
    }
    async function saveBeforeNavigation() {
        if (!draft) return;
        if (saveState !== 'saved') await save();
    }
    async function loadDraft(draftId) {
        const value = (await api('/drafts/' + encodeURIComponent(draftId))).draft;
        // A draft selection never implicitly loads its optional source job.
        if (!value || value.kind !== 'shorts_draft') throw new Error(t('editor_invalid_draft'));
        draft = value; sourceJob = null; view = 'editor';
        selected = draft.project.scenes[0].id; sceneCount = draft.project.scenes.length;
        if (!capabilities) capabilities = await api('/capabilities');
        await refreshReadiness();
    }
    async function deleteDraft(draftId) {
        try { await api('/drafts/' + encodeURIComponent(draftId), 'DELETE'); }
        catch (error) { if (error.status !== 404) throw error; }
        draftItems = draftItems.filter(item => item.id !== draftId);
        if (draft?.id === draftId) reset();
    }
    function previewMedia(element, parent) {
        element.addEventListener('error', () => {
            element.hidden = true;
            const hint = node('p', 'mlx-shorts-studio-status', t('editor_preview_unavailable'));
            parent.append(hint);
        }, { once: true });
        parent.append(element);
    }
    async function save() {
        if (!draft) return null;
        if (saveTimer !== null) window.clearTimeout?.(saveTimer);
        saveTimer = null; saveState = 'saving';
        if (ui?.saveStatus) ui.saveStatus.textContent = t('editor_saving');
        const current = draft;
        try {
            const saved = (await api('/drafts/' + current.id, 'PUT', {
                project: clone(current.project), expected_version: current.version
            })).draft;
            if (draft !== current) return saved;
            draft = saved;
            saveState = 'saved';
            if (ui?.saveStatus) ui.saveStatus.textContent = t('editor_saved');
            await refreshReadiness();
            return draft;
        } catch (error) {
            saveState = 'dirty';
            error.keepDraft = true;
            throw error;
        }
    }
    async function newDraft() {
        await saveBeforeNavigation();
        if (!capabilities) capabilities = await api('/capabilities');
        draft = (await api('/drafts', 'POST', {})).draft;
        sourceJob = null; view = 'editor';
        selected = draft.project.scenes[0].id;
        sceneCount = draft.project.scenes.length;
        await refreshReadiness();
        render();
    }
    async function list() {
        await saveBeforeNavigation();
        const data = await api('/drafts');
        reset(); view = 'drafts';
        draftItems = data.drafts || [];
    }
    function renderStart() {
        ui.body.replaceChildren();
        if (view === 'welcome') {
            const welcome = node('section', 'mlx-shorts-studio-editor');

            welcome.dataset.shortsWelcome = '1';
            welcome.append(node('h3', '', t('editor_your_next_short_starts_here')),
                node('p', '', t('editor_create_a_new_draft_or_open_your_drafts')));
            ui.body.append(welcome);
            return;
        }
        if (!draftItems.length) ui.body.append(node('p', '', t('editor_no_drafts_yet')));
        draftItems.forEach(item => {
            const row = node('article', 'mlx-shorts-studio-editor');
            row.append(node('strong', '', item.project.title), node('span', '', `${item.project.duration}s · ${item.project.scenes.length}`));
            const actions = node('div', 'mlx-shorts-studio-actions');
            button(t('editor_load'), () => loadDraft(item.id), actions);
            button(t('editor_duplicate'), async () => {
                draft = (await api('/drafts/' + encodeURIComponent(item.id) + '/duplicate', 'POST', {})).draft;
                sourceJob = null; view = 'editor'; selected = draft.project.scenes[0].id;
                sceneCount = draft.project.scenes.length;
                if (!capabilities) capabilities = await api('/capabilities');
                await refreshReadiness();
            }, actions);
            button(t('editor_delete'), () => deleteDraft(item.id), actions);
            row.append(actions); ui.body.append(row);
        });
    }
    function sceneDefaults() {
        return { id: 'scene-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7), title: '', duration: 5,
            description: '', narration: '', caption: '', video_prompt: '', camera: '', voice_enabled: true,
            transition: { type: 'cut', duration: 0 }, music: null,
            sfx: { enabled: false, track: null, volume: 0.5, offset: 0 } };
    }
    function move(from, to) {
        const scenes = draft.project.scenes;
        if (from < 0 || to < 0 || to >= scenes.length) return;
        scenes.splice(to, 0, scenes.splice(from, 1)[0]); dirty(); render();
    }
    function render() {
        if (ui) ui.headerLabels().forEach((label, i) => { ui.headerActions.children[i].textContent = label; });
        if (!ui) return;
        if (!draft) { renderStart(); return; }
        const p = draft.project;
        ui.body.replaceChildren();
        const bar = node('div', 'mlx-shorts-studio-actions');
        if (expertMode) {
            button(t('editor_save_draft'), save, bar);
            button(t('editor_delete_draft'), () => deleteDraft(draft.id), bar);
        }
        if (expertMode && draft.source_job_id && !sourceJob) {
            button(t('editor_load_source_preview'), async () => {
                const sourceId = draft.source_job_id;
                const response = await fetch('/api/mlx/shorts-jobs/' + encodeURIComponent(sourceId));
                if (response.status === 404) {
                    message(t('editor_source_preview_is_no_longer_available'));
                    return;
                }
                if (!response.ok) throw new Error(t('editor_preview_is_currently_unavailable'));
                const job = window.MLXShortsStudio.extractJob(await response.json());
                if (!job || job.id !== sourceId) throw new Error(t('editor_invalid_preview'));
                sourceJob = job;
            }, bar);
        }
        const planButton = button(t('editor_plan_with_ai'), async () => {
            await save(); draft = (await api('/drafts/' + draft.id + '/plan', 'POST', { scene_count: sceneCount })).draft;
            selected = draft.project.scenes[0].id;
            await refreshReadiness();
        }, bar);
        planButton.classList.add('mlx-shorts-primary');
        ui.saveStatus = node('span', 'mlx-shorts-save-status', saveState === 'saved' ? t('editor_saved') : saveState === 'saving' ? t('editor_saving') : t('editor_unsaved'));
        bar.append(ui.saveStatus);
        ui.renderButton = button(t('editor_render_short'), async () => {
            await save();
            const result = await api('/drafts/' + draft.id + '/render', 'POST', {});
            ui.overlay.classList.remove('is-open');
            window.MLXShortsStudio.setActiveJob(result.job); window.MLXShortsStudio.openJob();
        }, bar);
        ui.renderButton.classList.add('mlx-shorts-primary');
        ui.timeline = node('div', 'mlx-shorts-studio-status');
        ui.body.append(bar, ui.timeline);
        const layout = node('div', 'mlx-shorts-project-layout');
        const settings = node('section', 'mlx-shorts-studio-editor');
        settings.append(node('h3', '', t('editor_project_9_16')));
        field(settings, t('editor_title'), p, 'title');
        field(settings, t('editor_idea_briefing'), p, 'briefing', 'textarea');
        field(settings, t('editor_total_duration_s'), p, 'duration', 'number');
        const count = { value: sceneCount };
        const countInput = field(settings, t('editor_scene_count_for_ai_planning'), count, 'value', 'number');
        countInput.addEventListener('input', () => { sceneCount = count.value; });
        const style = field(settings, t('editor_style'), p, 'style_preset', 'text', [
            ['auto', 'Auto'], ['cinematic', 'Cinematic'], ['luxury_commercial', 'Luxury Commercial'],
            ['funny_meme', 'Funny / Meme'], ['documentary', 'Documentary'], ['futuristic', 'Futuristic'],
            ['product_ad', 'Product Ad'], ['social_viral', 'Social / Viral']]);
        style.addEventListener('input', () => { p.visual_bible = null; });
        field(settings, t('editor_render_quality'), p, 'quality', 'text', [['fast', t('editor_draft')], ['standard', 'Standard'], ['quality', t('editor_publication')]]);
        field(settings, t('editor_enable_voice'), p, 'voice_enabled', 'checkbox');
        field(settings, t('editor_enable_captions'), p, 'subtitles_enabled', 'checkbox');
        const musicChoice = { value: p.music_selection === 'off' || p.music_mode === 'off' ? 'off' : 'auto' };
        const musicInput = field(settings, t('editor_music'), musicChoice, 'value', 'text', [['auto', 'Auto'], ['off', t('editor_off')]]);
        musicInput.addEventListener('input', () => {
            p.music_selection = musicChoice.value; p.music_enabled = musicChoice.value === 'auto';
            p.music_mode = musicChoice.value === 'off' ? 'off' : 'global'; p.music_track = null;
            p.scenes.forEach(scene => { scene.music = null; }); validate();
            dirty();
        });
        if (expertMode) {
        const projectDetails = accordion(settings, t('editor_project_details'));
        if (providerReadiness) {
            const diagnosis = accordion(projectDetails, t('editor_provider_diagnosis'));
            diagnosis.append(node('p', '', providerReadiness.available ? t('editor_keyframe_provider_available') : t('editor_no_keyframe_provider_available')));
            (providerReadiness.models || []).forEach(model => diagnosis.append(node('p', '', `${model.available === false ? '⚠ ' : '✓ '}${model.provider || ''} · ${model.model || ''} · ${model.model_family || ''}${model.cli_version ? ' · MFLUX ' + model.cli_version : ''}${model.reason ? ' · ' + model.reason : ''}`)));
        }
        field(projectDetails, t('editor_language'), p, 'language');
        field(projectDetails, t('editor_voice_profile'), p, 'voice');
        field(projectDetails, t('editor_voice_speed'), p, 'voice_speed', 'number');
        const captionDetails = accordion(projectDetails, t('editor_captions'));
        field(captionDetails, t('editor_caption_position'), p.captions, 'position', 'text', ['bottom', 'center', 'top']);
        field(captionDetails, t('editor_caption_size'), p.captions, 'size', 'number');
        field(captionDetails, t('editor_caption_style'), p.captions, 'style', 'text', ['bold', 'plain']);
        const musicDetails = accordion(projectDetails, t('editor_music'));
        field(musicDetails, t('editor_music_mode'), p, 'music_mode', 'text', [['off', t('editor_off')], ['global', t('editor_entire_short')], ['scene', t('editor_per_scene')]]);
        musicFields(musicDetails, p, true);
        const consistency = node('details'); consistency.open = false;
        consistency.append(node('summary', '', t('editor_visual_consistency')));
        field(consistency, t('editor_consistency_mode'), p, 'consistency_mode', 'checkbox');
        field(consistency, t('editor_keep_character_consistent_across_scenes'), p, 'character_consistency', 'checkbox');
        field(consistency, t('editor_style_consistency'), p, 'style_consistency', 'checkbox');
        field(consistency, t('editor_style_strength'), p, 'style_strength', 'number');
        if (!p.visual_bible) p.visual_bible = { style: '', character: '', environment: '', palette: '', camera: '', continuity_rules: [] };
        ['style', 'character', 'environment', 'palette', 'camera'].forEach(key => field(consistency, t('editor_visual_bible', {field: t('editor_option_' + key)}), p.visual_bible, key, 'textarea'));
        const rules = { value: p.visual_bible.continuity_rules.join('\n') };
        const rulesInput = field(consistency, t('editor_continuity_rules_one_per_line'), rules, 'value', 'textarea');
        rulesInput.addEventListener('input', () => { p.visual_bible.continuity_rules = rules.value.split('\n').map(s => s.trim()).filter(Boolean); dirty(); });
        projectDetails.append(consistency);
        }
        const timeline = node('section', 'mlx-shorts-project-timeline');
        const add = node('div', 'mlx-shorts-studio-actions');
        if (expertMode) button(t('editor_add_scene'), () => { const s = sceneDefaults(); p.scenes.push(s); selected = s.id; }, add, p.scenes.length >= 60);
        timeline.append(add);
        if (sourceJob?.status === 'completed') {
            const preview = node('video'); preview.controls = true; preview.preload = 'metadata';
            preview.src = '/api/mlx/shorts/' + encodeURIComponent(sourceJob.id);
            preview.className = 'mlx-shorts-scene-preview'; previewMedia(preview, timeline);
        }
        p.scenes.forEach((scene, i) => {
            const card = node('button', 'mlx-shorts-studio-scene' + (scene.id === selected ? ' is-active' : ''));
            card.type = 'button'; card.draggable = true;
            const media = sourceJob?.scene_results?.find(r => r.scene_id === scene.id);
            const keyframe = sourceJob?.keyframe_results?.find(r => r.scene_id === scene.id && r.status === 'completed');
            if (keyframe) {
                const thumb = node('img', 'mlx-shorts-scene-thumb'); thumb.alt = t('editor_keyframe');
                thumb.src = base + '/jobs/' + encodeURIComponent(sourceJob.id) + '/scenes/' + encodeURIComponent(scene.id) + '/keyframe';
                card.append(thumb);
            }
            const renderStatus = media?.status === 'completed' ? t('editor_completed') : t('editor_draft');
            card.append(node('strong', '', `${media?.status === 'completed' ? '✓ ' : sourceJob?.error_scene_id === scene.id ? '! ' : ''}${t('editor_scene', {number: i+1})} · ${scene.duration} s`),
                node('span', '', scene.title || scene.description || t('editor_untitled')),
                node('span', '', scene.caption || t('editor_no_caption')));
            if (expertMode) card.append(node('span', '', `${scene.music?.style || p.music_style || 'Auto'} · ${scene.transition.type} · ${renderStatus}`));
            card.addEventListener('click', () => { selected = scene.id; render(); });
            card.addEventListener('dragstart', e => e.dataTransfer.setData('text/plain', scene.id));
            card.addEventListener('dragover', e => e.preventDefault());
            card.addEventListener('drop', e => { e.preventDefault(); move(p.scenes.findIndex(s => s.id === e.dataTransfer.getData('text/plain')), i); });
            timeline.append(card);
        });
        const scene = p.scenes.find(s => s.id === selected) || p.scenes[0]; selected = scene.id;
        const editor = node('section', 'mlx-shorts-studio-editor');
        const i = p.scenes.indexOf(scene);
        editor.append(node('h3', '', t('editor_scene', {number: i + 1})));
        const actions = node('div', 'mlx-shorts-studio-actions');
        if (expertMode) {
        button(t('editor_duplicate'), () => { const copy = clone(scene); copy.id = sceneDefaults().id; p.scenes.splice(i + 1, 0, copy); selected = copy.id; }, actions, p.scenes.length >= 60);
        button(t('editor_delete'), () => { p.scenes.splice(i, 1); selected = p.scenes[0].id; }, actions, p.scenes.length <= 1);
        button('↑', () => move(i, i - 1), actions, i === 0);
        button('↓', () => move(i, i + 1), actions, i === p.scenes.length - 1);
        editor.append(actions);
        }
        field(editor, t('editor_scene_title'), scene, 'title');
        field(editor, t('editor_what_happens'), scene, 'description', 'textarea');
        field(editor, t('editor_caption_visible_text'), scene, 'caption', 'textarea');
        field(editor, t('editor_narration_spoken_text'), scene, 'narration', 'textarea');
        if (expertMode) {
        const sceneDetails = accordion(editor, t('editor_scene_details'));
        field(sceneDetails, t('editor_duration_s'), scene, 'duration', 'number');
        field(sceneDetails, t('editor_video_prompt'), scene, 'video_prompt', 'textarea');
        button(t('editor_improve_prompt_with_ai'), async () => { await save(); draft = (await api('/drafts/' + draft.id + '/scenes/' + scene.id + '/improve', 'POST', {})).draft; }, sceneDetails);
        field(sceneDetails, t('editor_camera_movement'), scene, 'camera');
        field(sceneDetails, t('editor_voiceover_for_this_scene'), scene, 'voice_enabled', 'checkbox');
        if (i < p.scenes.length - 1) {
            const transitionDetails = accordion(sceneDetails, t('editor_transition'));
            const input = field(transitionDetails, t('editor_transition_to_next_scene'), scene.transition, 'type', 'text', capabilities?.transitions || ['cut']);
            input.addEventListener('input', () => { scene.transition.duration = input.value === 'cut' ? 0 : 0.5; render(); });
            field(transitionDetails, t('editor_transition_duration_s_within_timeline'), scene.transition, 'duration', 'number');
        }
        if (p.music_mode === 'scene') {
            const sceneMusic = accordion(sceneDetails, t('editor_scene_music'));
            const enabled = { value: scene.music !== null };
            const input = field(sceneMusic, t('editor_override_music_otherwise_use_global_settings'), enabled, 'value', 'checkbox');
            input.addEventListener('input', () => {
                p.music_selection = 'custom';
                scene.music = enabled.value ? { enabled: p.music_enabled, style: p.music_style || 'cinematic', track: null,
                    volume: p.music_volume, start_offset: 0, fade_in: 0, fade_out: 0, duck_under_voice: true } : null; dirty(); render();
            });
            if (scene.music) musicFields(sceneMusic, scene.music);
        }
        const effectDetails = accordion(sceneDetails, t('editor_sound_effects'));
        field(effectDetails, t('editor_enable_sound_effect'), scene.sfx, 'enabled', 'checkbox');
        field(effectDetails, t('editor_sound_effect_track'), scene.sfx, 'track', 'text', trackOptions('sfx'));
        field(effectDetails, t('editor_sound_effect_volume_0_1'), scene.sfx, 'volume', 'number');
        field(effectDetails, t('editor_sound_effect_offset_s'), scene.sfx, 'offset', 'number');
        if (draft.source_job_id) {
            editor.append(node('p', '', t('editor_keyframe_consistency_source_media_after_prompt_changes_preview')));
            const prefix = base + '/jobs/' + draft.source_job_id + '/scenes/' + encodeURIComponent(scene.id);
            const media = sourceJob?.scene_results?.find(r => r.scene_id === scene.id && r.status === 'completed');
            const frame = sourceJob?.keyframe_results?.find(r => r.scene_id === scene.id && r.status === 'completed');
            editor.append(node('p', '', frame ? t('editor_keyframe_completed') : t('editor_keyframe_pending')));
            if (media) {
                const video = node('video'); video.controls = true; video.preload = 'metadata'; video.src = prefix + '/video';
                video.className = 'mlx-shorts-scene-preview'; previewMedia(video, editor);
            }
            if (frame) {
                const keyframe = node('img'); keyframe.src = prefix + '/keyframe'; keyframe.alt = t('editor_keyframe_consistency');
                keyframe.className = 'mlx-shorts-scene-preview'; previewMedia(keyframe, editor);
            }
            button(t('editor_render_scene_again'), async () => {
                await save(); const result = await api('/drafts/' + draft.id + '/render', 'POST', { force_scene_id: scene.id });
                ui.overlay.classList.remove('is-open'); window.MLXShortsStudio.setActiveJob(result.job); window.MLXShortsStudio.openJob();
            }, editor, errors(p).length > 0);
        }
        }
        layout.append(settings, timeline, editor); ui.body.append(layout); validate();
        ui.overlay.querySelectorAll('input,textarea,select').forEach(el => { el.disabled = busy; });
    }
    async function open(existing = null) {
        ensure(); ui.overlay.classList.add('is-open');
        if (!existing) {
            return run(async () => {
                await saveBeforeNavigation();
                window.MLXShortsStudio?.clearActiveJob?.();
                reset(); message(''); render();
            });
        }
        return run(async () => {
            if (existing.kind !== 'shorts_draft') throw new Error(t('editor_please_select_a_draft'));
            await saveBeforeNavigation();
            await loadDraft(existing.id);
        });
    }
    async function editJob(job) {
        ensure(); ui.overlay.classList.add('is-open');
        await run(async () => {
            capabilities = await api('/capabilities');
            await saveBeforeNavigation();
            const project = clone(job.project);
            if ((project.schema_version || 1) === 1) {
                project.scenes.forEach(scene => { if (scene.caption === undefined) scene.caption = scene.narration || ''; });
            }
            project.schema_version = 2;
            draft = (await api('/drafts', 'POST', { project, source_job_id: job.id, chat_id: job.chat_id })).draft;
            sourceJob = job; view = 'editor';
            selected = draft.project.scenes[0].id; sceneCount = draft.project.scenes.length;
            await refreshReadiness();
        });
    }
    window.MLXShortsProjectEditor = { refreshLanguage: render, open, showNotice(text) { if (ui) message(text); }, resetSelection() { ensure(); return run(async () => { await saveBeforeNavigation(); reset(); render(); }); },
        sourceDeleted(jobIds) { if (draft?.source_job_id && jobIds.includes(draft.source_job_id)) return run(async () => { await saveBeforeNavigation(); reset(); render(); }); },
        newDraft: async () => {
        ensure(); ui.overlay.classList.add('is-open');
        await run(async () => { capabilities = await api('/capabilities'); await newDraft(); });
    }, editJob,
        __test: { errors, move, sceneDefaults, deleteDraft, loadDraft, getState: () => ({ draft, sourceJob, view, selected }) } };
})();

document.addEventListener('mlx-language-changed', () => { if (window.MLXShortsProjectEditor) window.MLXShortsProjectEditor.refreshLanguage?.(); });
