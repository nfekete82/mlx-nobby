(function () {
    'use strict';

    const FALLBACKS = {
        manage: 'Manage voices',
        title: 'Voice Manager',
        subtitle: 'Manage, test and tune local voices',
        close: 'Close Voice Manager',
        add: '+ Add voice',
        refresh: 'Refresh',
        loading: 'Loading voices …',
        unavailable: 'Voice Manager is currently unavailable.',
        empty: 'No local voices yet.',
        preset: 'Preset',
        clone: 'Clone',
        default_badge: 'Default',
        duration: 'Reference duration',
        size: 'File size',
        quality: 'Quality',
        quality_stable: 'Stable',
        quality_natural: 'Natural',
        quality_expressive: 'Expressive',
        test: 'Test',
        reference: 'Play reference',
        set_default: 'Set as default',
        edit: 'Edit',
        delete: 'Delete',
        save: 'Save',
        cancel: 'Cancel',
        name: 'Name',
        transcript: 'Transcript',
        audio: 'Reference audio',
        import_title: 'Add voice',
        edit_title: 'Edit voice',
        import_hint: 'Supports WAV, MP3, M4A, OPUS, OGG, FLAC, AAC and WebM up to 50 MB.',
        import: 'Import voice',
        delete_title: 'Delete voice?',
        delete_message: 'Permanently delete the local voice “{name}”, including its reference and transcript?',
        delete_confirm: 'Delete voice',
        error: 'Action failed: {message}',
        imported: 'Voice imported.',
        updated: 'Voice updated.',
        deleted: 'Voice deleted.',
        default_set: '{name} is now the default voice.',
        test_text: 'Hello, I am your local voice. This short test checks tone, naturalness and voice similarity.',
        no_transcript: 'No transcript',
        seconds: 's'
    };

    let translations = {};
    let translationPromise = null;
    let ui = null;
    let voices = [];
    let activeAudio = null;
    let activeAudioUrl = null;
    let loading = false;

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
        return interpolate(
            translations?.[language()]?.[key] || FALLBACKS[key] || key,
            params
        );
    }

    async function loadTranslations() {
        if (translationPromise) return translationPromise;
        translationPromise = fetch('/i18n/voice-manager.json', { cache: 'no-store' })
            .then(response => response.ok ? response.json() : {})
            .then(payload => {
                translations = payload && typeof payload === 'object' ? payload : {};
                ensureManageButton(true);
                return translations;
            })
            .catch(() => ({}));
        return translationPromise;
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function loadStyles() {
        if (document.querySelector('link[data-mlx-voice-manager-style]')) return;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/assets/chat/voice-manager.css?v=20260928-voice-manager-v1';
        link.dataset.mlxVoiceManagerStyle = '1';
        document.head.appendChild(link);
    }

    function stopAudio() {
        if (activeAudio) {
            try { activeAudio.pause(); } catch (_) {}
        }
        if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
        activeAudio = null;
        activeAudioUrl = null;
    }

    async function playBlob(blob) {
        stopAudio();
        activeAudioUrl = URL.createObjectURL(blob);
        activeAudio = new Audio(activeAudioUrl);
        const cleanup = () => stopAudio();
        activeAudio.addEventListener('ended', cleanup, { once: true });
        activeAudio.addEventListener('error', cleanup, { once: true });
        await activeAudio.play();
    }

    function formatBytes(value) {
        const bytes = Number(value || 0);
        if (!Number.isFinite(bytes) || bytes <= 0) return '–';
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
        return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function qualityLabel(mode) {
        return t(`quality_${String(mode || 'natural')}`);
    }

    async function responseDetail(response) {
        try {
            const payload = await response.json();
            return payload?.detail || payload?.error || `HTTP ${response.status}`;
        } catch (_) {
            return `HTTP ${response.status}`;
        }
    }

    function setStatus(text) {
        if (ui?.status) ui.status.textContent = String(text || '');
    }

    async function confirmAction(options) {
        if (typeof window.MLXConfirm === 'function') return window.MLXConfirm(options);
        return window.confirm(options.message || options.title || 'Confirm');
    }

    async function refreshVoicePicker(preferredVoice) {
        await window.MLXVoice?.refreshVoices?.();
        if (preferredVoice) window.MLXVoice?.setVoice?.(preferredVoice);
    }

    async function loadVoices() {
        if (loading) return;
        loading = true;
        setStatus(t('loading'));
        try {
            const response = await fetch('/api/mlx/audio/voices/manage', {
                cache: 'no-store',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) throw new Error(await responseDetail(response));
            const payload = await response.json();
            voices = Array.isArray(payload?.voices) ? payload.voices : [];
            renderCards();
            setStatus('');
        } catch (error) {
            console.error('[voice-manager] Failed to load voices:', error);
            voices = [];
            if (ui?.list) ui.list.replaceChildren(element('div', 'mlx-vm-meta', t('unavailable')));
            setStatus(t('error', { message: error?.message || String(error) }));
        } finally {
            loading = false;
        }
    }

    async function setDefaultVoice(voice) {
        const response = await fetch('/api/mlx/audio/voice-default', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voice: voice.id })
        });
        if (!response.ok) throw new Error(await responseDetail(response));
        const payload = await response.json();
        await refreshVoicePicker(payload.default || voice.id);
        await loadVoices();
        setStatus(t('default_set', { name: payload.default || voice.label }));
    }

    async function updateQuality(voice, quality) {
        const response = await fetch(`/api/mlx/audio/voices/${encodeURIComponent(voice.id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quality })
        });
        if (!response.ok) throw new Error(await responseDetail(response));
        await loadVoices();
        window.MLXVoiceStreaming?.clearCache?.();
        setStatus(t('updated'));
    }

    async function testVoice(voice) {
        const previous = window.MLXVoice?.getSettings?.()?.voice || null;
        if (!window.MLXVoice?.setVoice?.(voice.id)) {
            await refreshVoicePicker(voice.id);
        }
        try {
            const response = await fetch('/api/mlx/audio/speech', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input: t('test_text'),
                    voice: voice.id,
                    language: language() === 'de' ? 'de' : 'en',
                    speed: 1.0,
                    response_format: 'mp3',
                    instruct: voice.kind === 'clone' ? '' : undefined
                })
            });
            if (!response.ok) throw new Error(await responseDetail(response));
            await playBlob(await response.blob());
        } finally {
            if (previous && previous !== voice.id) window.MLXVoice?.setVoice?.(previous);
        }
    }

    async function playReference(voice) {
        const response = await fetch(
            `/api/mlx/audio/voices/${encodeURIComponent(voice.id)}/reference`,
            { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(await responseDetail(response));
        await playBlob(await response.blob());
    }

    async function deleteVoice(voice) {
        const confirmed = await confirmAction({
            title: t('delete_title'),
            message: t('delete_message', { name: voice.label }),
            confirmLabel: t('delete_confirm'),
            cancelLabel: t('cancel')
        });
        if (!confirmed) return;
        const response = await fetch(`/api/mlx/audio/voices/${encodeURIComponent(voice.id)}`, {
            method: 'DELETE'
        });
        if (!response.ok) throw new Error(await responseDetail(response));
        await refreshVoicePicker();
        await loadVoices();
        setStatus(t('deleted'));
    }

    function actionButton(label, handler, className = '') {
        const button = element('button', `mlx-vm-button ${className}`.trim(), label);
        button.type = 'button';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                await handler();
            } catch (error) {
                console.error('[voice-manager] Action failed:', error);
                setStatus(t('error', { message: error?.message || String(error) }));
            } finally {
                button.disabled = false;
            }
        });
        return button;
    }

    function renderCards() {
        if (!ui?.list) return;
        ui.list.replaceChildren();
        if (!voices.length) {
            ui.list.appendChild(element('div', 'mlx-vm-meta', t('empty')));
            return;
        }

        for (const voice of voices) {
            const card = element('section', 'mlx-vm-card');
            const head = element('div', 'mlx-vm-card-head');
            const name = element('div', 'mlx-vm-name', voice.label || voice.id);
            const badges = element('div', 'mlx-vm-badges');
            badges.appendChild(element('span', 'mlx-vm-badge', t(voice.kind === 'clone' ? 'clone' : 'preset')));
            if (voice.is_default) badges.appendChild(element('span', 'mlx-vm-badge', t('default_badge')));
            head.append(name, badges);
            card.appendChild(head);

            if (voice.kind === 'clone') {
                const meta = element('div', 'mlx-vm-meta');
                const duration = Number(voice.duration_seconds);
                meta.textContent = `${t('duration')}: ${Number.isFinite(duration) ? duration.toFixed(1) + ' ' + t('seconds') : '–'} · ${t('size')}: ${formatBytes(voice.size_bytes)}`;
                card.appendChild(meta);

                if (voice.sampling) {
                    card.appendChild(element(
                        'div',
                        'mlx-vm-sampling',
                        `temperature ${voice.sampling.temperature} · top_k ${voice.sampling.top_k} · top_p ${voice.sampling.top_p}`
                    ));
                }

                const qualityRow = element('label', 'mlx-vm-quality-row');
                qualityRow.appendChild(element('span', '', t('quality')));
                const select = element('select', 'mlx-vm-select');
                for (const mode of ['stable', 'natural', 'expressive']) {
                    const option = document.createElement('option');
                    option.value = mode;
                    option.textContent = qualityLabel(mode);
                    option.selected = voice.quality === mode;
                    select.appendChild(option);
                }
                select.addEventListener('change', async () => {
                    select.disabled = true;
                    try {
                        await updateQuality(voice, select.value);
                    } catch (error) {
                        setStatus(t('error', { message: error?.message || String(error) }));
                        select.value = voice.quality || 'natural';
                    } finally {
                        select.disabled = false;
                    }
                });
                qualityRow.appendChild(select);
                card.appendChild(qualityRow);
            }

            const actions = element('div', 'mlx-vm-actions');
            actions.appendChild(actionButton(t('test'), () => testVoice(voice), 'is-primary'));
            if (voice.kind === 'clone') {
                actions.appendChild(actionButton(t('reference'), () => playReference(voice)));
            }
            if (!voice.is_default) {
                actions.appendChild(actionButton(t('set_default'), () => setDefaultVoice(voice)));
            }
            if (voice.kind === 'clone') {
                actions.appendChild(actionButton(t('edit'), () => showEditor(voice)));
                actions.appendChild(actionButton(t('delete'), () => deleteVoice(voice), 'is-danger'));
            }
            card.appendChild(actions);
            ui.list.appendChild(card);
        }
    }

    function buildField(labelText, control) {
        const field = element('label', 'mlx-vm-field');
        field.append(element('span', '', labelText), control);
        return field;
    }

    function showEditor(voice = null) {
        if (!ui?.editor) return;
        const editing = Boolean(voice);
        const editor = ui.editor;
        editor.replaceChildren();
        editor.hidden = false;
        editor.appendChild(element('h3', '', t(editing ? 'edit_title' : 'import_title')));

        const nameInput = element('input', 'mlx-vm-input');
        nameInput.type = 'text';
        nameInput.maxLength = 80;
        nameInput.value = voice?.label || '';
        nameInput.required = true;
        editor.appendChild(buildField(t('name'), nameInput));

        const transcript = element('textarea', 'mlx-vm-textarea');
        transcript.maxLength = 20000;
        transcript.value = voice?.transcript || '';
        transcript.required = true;
        editor.appendChild(buildField(t('transcript'), transcript));

        const quality = element('select', 'mlx-vm-select');
        for (const mode of ['stable', 'natural', 'expressive']) {
            const option = document.createElement('option');
            option.value = mode;
            option.textContent = qualityLabel(mode);
            option.selected = (voice?.quality || 'natural') === mode;
            quality.appendChild(option);
        }
        editor.appendChild(buildField(t('quality'), quality));

        let fileInput = null;
        if (!editing) {
            fileInput = element('input', 'mlx-vm-input');
            fileInput.type = 'file';
            fileInput.accept = '.wav,.mp3,.m4a,.mp4,.opus,.ogg,.oga,.flac,.aac,.webm,audio/*';
            fileInput.required = true;
            editor.appendChild(buildField(t('audio'), fileInput));
            editor.appendChild(element('div', 'mlx-vm-meta', t('import_hint')));
        }

        const actions = element('div', 'mlx-vm-editor-actions');
        const cancel = element('button', 'mlx-vm-button', t('cancel'));
        cancel.type = 'button';
        cancel.addEventListener('click', () => { editor.hidden = true; });
        const save = element('button', 'mlx-vm-button is-primary', t(editing ? 'save' : 'import'));
        save.type = 'button';
        save.addEventListener('click', async () => {
            save.disabled = true;
            try {
                const nameValue = nameInput.value.trim();
                const transcriptValue = transcript.value.trim();
                if (!nameValue || !transcriptValue) throw new Error('Missing required fields');

                let response;
                if (editing) {
                    const currentSelected = window.MLXVoice?.getSettings?.()?.voice;
                    response = await fetch(`/api/mlx/audio/voices/${encodeURIComponent(voice.id)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name: nameValue,
                            transcript: transcriptValue,
                            quality: quality.value
                        })
                    });
                    if (!response.ok) throw new Error(await responseDetail(response));
                    const updated = await response.json();
                    await refreshVoicePicker(currentSelected === voice.id ? updated.id : null);
                    setStatus(t('updated'));
                } else {
                    if (!fileInput?.files?.[0]) throw new Error('Missing reference audio');
                    const form = new FormData();
                    form.append('name', nameValue);
                    form.append('transcript', transcriptValue);
                    form.append('quality', quality.value);
                    form.append('file', fileInput.files[0]);
                    response = await fetch('/api/mlx/audio/voices/import', {
                        method: 'POST',
                        body: form
                    });
                    if (!response.ok) throw new Error(await responseDetail(response));
                    await response.json();
                    await refreshVoicePicker();
                    setStatus(t('imported'));
                }
                editor.hidden = true;
                window.MLXVoiceStreaming?.clearCache?.();
                await loadVoices();
            } catch (error) {
                console.error('[voice-manager] Save failed:', error);
                setStatus(t('error', { message: error?.message || String(error) }));
            } finally {
                save.disabled = false;
            }
        });
        actions.append(cancel, save);
        editor.appendChild(actions);
        nameInput.focus();
    }

    function createUI() {
        if (ui) return ui;
        const backdrop = element('div', 'mlx-vm-backdrop');
        backdrop.hidden = true;
        const panel = element('section', 'mlx-vm-panel');
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');

        const header = element('header', 'mlx-vm-header');
        const headingWrap = element('div');
        const title = element('h2', 'mlx-vm-title', t('title'));
        const subtitle = element('div', 'mlx-vm-subtitle', t('subtitle'));
        headingWrap.append(title, subtitle);
        const closeButton = element('button', 'mlx-vm-close', '×');
        closeButton.type = 'button';
        closeButton.title = t('close');
        closeButton.setAttribute('aria-label', t('close'));
        closeButton.addEventListener('click', close);
        header.append(headingWrap, closeButton);

        const toolbar = element('div', 'mlx-vm-toolbar');
        toolbar.append(
            actionButton(t('add'), () => showEditor()),
            actionButton(t('refresh'), loadVoices)
        );
        const status = element('div', 'mlx-vm-status');
        const editor = element('section', 'mlx-vm-editor');
        editor.hidden = true;
        const list = element('div', 'mlx-vm-list');
        panel.append(header, toolbar, status, editor, list);
        backdrop.appendChild(panel);
        backdrop.addEventListener('click', event => {
            if (event.target === backdrop) close();
        });
        document.body.appendChild(backdrop);
        ui = { backdrop, panel, status, editor, list };
        return ui;
    }

    async function open() {
        await loadTranslations();
        loadStyles();
        createUI();
        ui.backdrop.hidden = false;
        await loadVoices();
    }

    function close() {
        stopAudio();
        if (ui) {
            ui.backdrop.hidden = true;
            ui.editor.hidden = true;
        }
    }

    function ensureManageButton(forceText = false) {
        const popover = document.getElementById('mlxVoicePopover');
        if (!popover) return;
        let button = popover.querySelector('.mlx-vm-manage-button');
        if (!button) {
            const divider = element('div', 'mlx-voice-divider');
            button = element('button', 'mlx-voice-preview mlx-vm-manage-button', t('manage'));
            button.type = 'button';
            button.addEventListener('click', event => {
                event.preventDefault();
                event.stopPropagation();
                open().catch(error => {
                    console.error('[voice-manager] Open failed:', error);
                });
            });
            popover.append(divider, button);
        } else if (forceText) {
            button.textContent = t('manage');
        }
    }

    function init() {
        loadStyles();
        loadTranslations();
        ensureManageButton();
        const observer = new MutationObserver(() => ensureManageButton());
        observer.observe(document.body, { childList: true, subtree: true });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && ui && !ui.backdrop.hidden) close();
        });
    }

    window.MLXVoiceManager = {
        open,
        close,
        refresh: loadVoices,
        getVoices: () => voices.map(voice => ({ ...voice }))
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
