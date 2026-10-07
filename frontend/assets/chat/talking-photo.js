(() => {
    'use strict';

    const BUTTON_ID = 'talkingPhotoButton';
    const MODAL_ID = 'talkingPhotoModal';
    const STYLE_ID = 'talkingPhotoStyles';
    const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
    let pollTimer = null;
    let previewUrl = null;

    function language() {
        return (
            document.documentElement.lang ||
            window.I18n?.currentLanguage ||
            navigator.language ||
            'de'
        ).toLowerCase();
    }

    function localText(de, en) {
        return language().startsWith('de') ? de : en;
    }

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text != null) element.textContent = text;
        return element;
    }

    function requestJson(url, options = {}) {
        return fetch(url, {
            cache: 'no-store',
            ...options,
            headers: {
                Accept: 'application/json',
                ...(options.body ? {'Content-Type': 'application/json'} : {}),
                ...(options.headers || {}),
            },
        }).then(async response => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.detail || `HTTP ${response.status}`);
            }
            return payload;
        });
    }

    function installStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            .mlx-talking-photo-modal {
                position: fixed; inset: 0; z-index: 10020; display: grid;
                place-items: center; padding: 24px;
            }
            .mlx-talking-photo-modal[hidden] { display: none; }
            .mlx-talking-photo-backdrop {
                position: absolute; inset: 0; background: rgba(3, 8, 18, .72);
                backdrop-filter: blur(5px);
            }
            .mlx-talking-photo-dialog {
                position: relative; width: min(760px, 96vw); max-height: 92vh;
                overflow: auto; border: 1px solid rgba(148, 163, 184, .22);
                border-radius: 18px; padding: 22px; background: #0e1623;
                color: #e5edf7; box-shadow: 0 24px 70px rgba(0,0,0,.45);
            }
            .mlx-talking-photo-header {
                display: flex; align-items: center; justify-content: space-between;
                gap: 16px; margin-bottom: 16px;
            }
            .mlx-talking-photo-header h2 { margin: 0; font-size: 1.2rem; }
            .mlx-talking-photo-close {
                border: 0; background: transparent; color: inherit; cursor: pointer;
                font-size: 1.6rem; line-height: 1;
            }
            .mlx-talking-photo-grid {
                display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                gap: 16px;
            }
            .mlx-talking-photo-field { display: grid; gap: 7px; margin-bottom: 13px; }
            .mlx-talking-photo-field > span { font-size: .82rem; opacity: .78; }
            .mlx-talking-photo-field input,
            .mlx-talking-photo-field select,
            .mlx-talking-photo-field textarea {
                width: 100%; box-sizing: border-box; border: 1px solid rgba(148,163,184,.25);
                border-radius: 10px; background: #111d2d; color: inherit; padding: 10px 12px;
            }
            .mlx-talking-photo-field textarea { min-height: 148px; resize: vertical; }
            .mlx-talking-photo-preview {
                width: 100%; min-height: 240px; max-height: 390px; object-fit: contain;
                border-radius: 12px; background: #09111d; border: 1px solid rgba(148,163,184,.18);
            }
            .mlx-talking-photo-status {
                margin: 10px 0 14px; padding: 10px 12px; border-radius: 10px;
                background: rgba(148,163,184,.08); font-size: .86rem; white-space: pre-wrap;
            }
            .mlx-talking-photo-actions {
                display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
            }
            .mlx-talking-photo-actions button,
            .mlx-talking-photo-actions a {
                border: 1px solid rgba(148,163,184,.24); border-radius: 10px;
                padding: 9px 14px; background: #17263a; color: inherit; cursor: pointer;
                text-decoration: none; font: inherit;
            }
            .mlx-talking-photo-actions .primary { background: #2563eb; border-color: #2563eb; }
            .mlx-talking-photo-actions button:disabled { opacity: .45; cursor: not-allowed; }
            .mlx-talking-photo-result {
                width: 100%; margin-top: 16px; border-radius: 12px; background: black;
            }
            .mlx-talking-photo-hint { font-size: .78rem; opacity: .66; margin-top: 5px; }
            @media (max-width: 700px) {
                .mlx-talking-photo-grid { grid-template-columns: 1fr; }
                .mlx-talking-photo-dialog { padding: 16px; }
            }
        `;
        document.head.append(style);
    }

    function clearPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function closeModal() {
        clearPolling();
        const modal = document.getElementById(MODAL_ID);
        if (modal) {
            modal.hidden = true;
            modal.setAttribute('aria-hidden', 'true');
        }
    }

    async function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(reader.error || new Error('FileReader failed'));
            reader.readAsDataURL(file);
        });
    }

    function createModal() {
        const existing = document.getElementById(MODAL_ID);
        if (existing) return existing;

        installStyles();

        const modal = node('div', 'mlx-talking-photo-modal');
        modal.id = MODAL_ID;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');

        const backdrop = node('div', 'mlx-talking-photo-backdrop');
        backdrop.addEventListener('click', closeModal);
        modal.append(backdrop);

        const dialog = node('section', 'mlx-talking-photo-dialog');
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'talkingPhotoTitle');
        modal.append(dialog);

        const header = node('div', 'mlx-talking-photo-header');
        const title = node('h2', '', localText('Talking Photo', 'Talking Photo'));
        title.id = 'talkingPhotoTitle';
        const close = node('button', 'mlx-talking-photo-close', '×');
        close.type = 'button';
        close.setAttribute('aria-label', localText('Schließen', 'Close'));
        close.addEventListener('click', closeModal);
        header.append(title, close);
        dialog.append(header);

        const grid = node('div', 'mlx-talking-photo-grid');
        const left = node('div');
        const right = node('div');
        grid.append(left, right);
        dialog.append(grid);

        const imageLabel = node('label', 'mlx-talking-photo-field');
        imageLabel.append(node('span', '', localText('Foto der Person', 'Photo of the person')));
        const imageInput = document.createElement('input');
        imageInput.id = 'talkingPhotoImage';
        imageInput.type = 'file';
        imageInput.accept = 'image/png,image/jpeg';
        imageLabel.append(imageInput);
        left.append(imageLabel);

        const preview = document.createElement('img');
        preview.id = 'talkingPhotoPreview';
        preview.className = 'mlx-talking-photo-preview';
        preview.alt = localText('Vorschau des Fotos', 'Photo preview');
        preview.hidden = true;
        left.append(preview);
        left.append(node(
            'div',
            'mlx-talking-photo-hint',
            localText(
                'Am besten funktioniert ein gut sichtbares, frontales oder leicht seitliches Gesicht.',
                'A clearly visible frontal or slightly angled face works best.',
            ),
        ));


        const engineLabel = node('label', 'mlx-talking-photo-field');
        engineLabel.append(node('span', '', localText('Engine', 'Engine')));
        const engineSelect = document.createElement('select');
        engineSelect.id = 'talkingPhotoEngine';
        [
            ['ltx', localText('Standard · LTX direkt', 'Default · Direct LTX')],
            ['quality', localText('Hybrid · LTX + MuseTalk', 'Hybrid · LTX + MuseTalk')],
            ['fast', localText('Fast · MuseTalk', 'Fast · MuseTalk')],
        ].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            engineSelect.append(option);
        });
        engineSelect.value = 'ltx';
        engineLabel.append(engineSelect);
        engineLabel.append(node(
            'div',
            'mlx-talking-photo-hint',
            localText(
                'LTX direkt ist der Standard und erhält den natürlich generierten Mund. Hybrid ergänzt bei Bedarf einen MuseTalk-Lippenpass.',
                'Direct LTX is the default and keeps the naturally generated mouth. Hybrid adds a MuseTalk lip pass when needed.',
            ),
        ));
        right.append(engineLabel);

        const voiceLabel = node('label', 'mlx-talking-photo-field');
        voiceLabel.append(node('span', '', localText('Stimme', 'Voice')));
        const voiceSelect = document.createElement('select');
        voiceSelect.id = 'talkingPhotoVoice';
        voiceLabel.append(voiceSelect);
        right.append(voiceLabel);

        const languageLabel = node('label', 'mlx-talking-photo-field');
        languageLabel.append(node('span', '', localText('Sprache', 'Language')));
        const languageSelect = document.createElement('select');
        languageSelect.id = 'talkingPhotoLanguage';
        [['de', localText('Deutsch', 'German')], ['en', localText('Englisch', 'English')]].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            languageSelect.append(option);
        });
        languageSelect.value = language().startsWith('de') ? 'de' : 'en';
        languageLabel.append(languageSelect);
        right.append(languageLabel);

        const textLabel = node('label', 'mlx-talking-photo-field');
        textLabel.append(node('span', '', localText('Text', 'Text')));
        const textarea = document.createElement('textarea');
        textarea.id = 'talkingPhotoText';
        textarea.maxLength = 5000;
        textarea.placeholder = localText(
            'Was soll die Person sagen?',
            'What should the person say?',
        );
        textLabel.append(textarea);
        right.append(textLabel);

        const status = node('div', 'mlx-talking-photo-status', localText(
            'MuseTalk-Status wird geprüft …',
            'Checking MuseTalk status …',
        ));
        status.id = 'talkingPhotoStatus';
        dialog.append(status);

        const actions = node('div', 'mlx-talking-photo-actions');
        const create = node('button', 'primary', localText('Video erstellen', 'Create video'));
        create.id = 'talkingPhotoCreate';
        create.type = 'button';
        create.disabled = true;
        const cancel = node('button', '', localText('Abbrechen', 'Cancel'));
        cancel.id = 'talkingPhotoCancel';
        cancel.type = 'button';
        cancel.hidden = true;
        const download = node('a', '', localText('MP4 speichern', 'Save MP4'));
        download.id = 'talkingPhotoDownload';
        download.hidden = true;
        download.download = 'talking-photo.mp4';
        actions.append(create, cancel, download);
        dialog.append(actions);

        const result = document.createElement('video');
        result.id = 'talkingPhotoResult';
        result.className = 'mlx-talking-photo-result';
        result.controls = true;
        result.playsInline = true;
        result.hidden = true;
        dialog.append(result);

        imageInput.addEventListener('change', () => {
            const file = imageInput.files?.[0];
            if (previewUrl) {
                URL.revokeObjectURL(previewUrl);
                previewUrl = null;
            }
            if (!file) {
                preview.hidden = true;
                preview.removeAttribute('src');
                return;
            }
            previewUrl = URL.createObjectURL(file);
            preview.src = previewUrl;
            preview.hidden = false;
        });

        engineSelect.addEventListener('change', refreshProviderStatus);
        create.addEventListener('click', startJob);
        cancel.addEventListener('click', cancelCurrentJob);
        document.body.append(modal);
        return modal;
    }

    function setStatus(message) {
        const status = document.getElementById('talkingPhotoStatus');
        if (status) status.textContent = message;
    }

    async function loadVoices() {
        const select = document.getElementById('talkingPhotoVoice');
        if (!select) return;
        select.replaceChildren();

        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = localText('Standardstimme', 'Default voice');
        select.append(defaultOption);

        try {
            const payload = await requestJson('/api/mlx/audio/voices/manage');
            const voices = Array.isArray(payload.voices) ? payload.voices : [];
            voices.forEach(voice => {
                const id = String(voice?.id || voice?.label || voice?.name || '').trim();
                if (!id) return;
                const option = document.createElement('option');
                option.value = id;
                option.textContent = String(voice?.label || voice?.name || id);
                select.append(option);
            });
        } catch (error) {
            console.warn('Talking Photo voice list unavailable', error);
        }
    }

    async function refreshProviderStatus() {
        const create = document.getElementById('talkingPhotoCreate');
        const engine = document.getElementById('talkingPhotoEngine')?.value || 'ltx';
        if (create) create.disabled = true;
        try {
            const status = await requestJson('/api/talking-photo/status');
            const provider = status.providers?.[engine] || (
                engine === 'fast' ? status : null
            );
            const labels = {
                quality: 'Hybrid · LTX + MuseTalk',
                ltx: 'Standard · LTX direkt',
                fast: 'MuseTalk',
            };
            const label = labels[engine] || engine;

            if (provider?.ready) {
                setStatus(localText(
                    `${label} bereit${provider.device ? ` · ${provider.device}` : ''}.`,
                    `${label} ready${provider.device ? ` · ${provider.device}` : ''}.`,
                ));
                if (create) create.disabled = false;
            } else {
                setStatus(localText(
                    `${label} ist noch nicht bereit.${provider?.setup_command ? `\nEinmalig im Terminal ausführen: ${provider.setup_command}` : ''}`,
                    `${label} is not ready yet.${provider?.setup_command ? `\nRun once in Terminal: ${provider.setup_command}` : ''}`,
                ));
            }
        } catch (error) {
            setStatus(localText(
                `Renderer-Status konnte nicht geladen werden: ${error.message}`,
                `Could not load renderer status: ${error.message}`,
            ));
        }
    }

    async function openModal() {
        const modal = createModal();
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');

        const result = document.getElementById('talkingPhotoResult');
        const download = document.getElementById('talkingPhotoDownload');
        if (result) {
            result.pause();
            result.removeAttribute('src');
            result.hidden = true;
        }
        if (download) download.hidden = true;

        await Promise.all([loadVoices(), refreshProviderStatus()]);
    }

    async function startJob() {
        const imageInput = document.getElementById('talkingPhotoImage');
        const text = document.getElementById('talkingPhotoText')?.value?.trim() || '';
        const voice = document.getElementById('talkingPhotoVoice')?.value || null;
        const selectedLanguage = document.getElementById('talkingPhotoLanguage')?.value || 'de';
        const engine = document.getElementById('talkingPhotoEngine')?.value || 'ltx';
        const create = document.getElementById('talkingPhotoCreate');
        const cancel = document.getElementById('talkingPhotoCancel');
        const result = document.getElementById('talkingPhotoResult');
        const download = document.getElementById('talkingPhotoDownload');
        const file = imageInput?.files?.[0];

        if (!file) {
            setStatus(localText('Bitte zuerst ein Bild auswählen.', 'Please select an image first.'));
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            setStatus(localText('Das Bild darf maximal 10 MB groß sein.', 'The image may be at most 10 MB.'));
            return;
        }
        if (!['image/png', 'image/jpeg'].includes(file.type)) {
            setStatus(localText('Bitte PNG oder JPEG verwenden.', 'Please use PNG or JPEG.'));
            return;
        }
        if (!text) {
            setStatus(localText('Bitte einen Text eingeben.', 'Please enter text.'));
            return;
        }

        clearPolling();
        if (create) create.disabled = true;
        if (cancel) cancel.hidden = false;
        if (result) result.hidden = true;
        if (download) download.hidden = true;

        try {
            setStatus(localText('Bild wird vorbereitet …', 'Preparing image …'));
            const imageDataUrl = await fileToDataUrl(file);
            const job = await requestJson('/api/talking-photo/jobs', {
                method: 'POST',
                body: JSON.stringify({
                    image_data_url: imageDataUrl,
                    text,
                    voice,
                    language: selectedLanguage,
                    engine,
                    speed: 1.0,
                }),
            });
            if (cancel) cancel.dataset.jobId = job.id;
            pollJob(job.id);
        } catch (error) {
            setStatus(error.message);
            if (create) create.disabled = false;
            if (cancel) cancel.hidden = true;
        }
    }

    async function cancelCurrentJob() {
        const cancel = document.getElementById('talkingPhotoCancel');
        const jobId = cancel?.dataset?.jobId;
        if (!jobId) return;
        cancel.disabled = true;
        try {
            await requestJson(`/api/talking-photo/jobs/${jobId}/cancel`, {
                method: 'POST',
                body: JSON.stringify({}),
            });
            setStatus(localText(
                'Abbruch angefordert …',
                'Cancellation requested …',
            ));
        } catch (error) {
            setStatus(error.message);
        } finally {
            cancel.disabled = false;
        }
    }

    function phaseText(job) {
        const phase = String(job.phase || job.status || '');
        const labels = {
            queued: localText('Wartet auf freien KI-Slot …', 'Waiting for an AI slot …'),
            tts: localText('Stimme wird erzeugt …', 'Generating voice …'),
            lipsync: localText('Lippen werden synchronisiert …', 'Synchronizing lips …'),
            completed: localText('Fertig.', 'Done.'),
            cancelled: localText('Abgebrochen.', 'Cancelled.'),
            failed: localText('Fehlgeschlagen.', 'Failed.'),
        };
        return labels[phase] || phase;
    }

    async function pollJob(jobId) {
        clearPolling();
        const create = document.getElementById('talkingPhotoCreate');
        const cancel = document.getElementById('talkingPhotoCancel');
        const result = document.getElementById('talkingPhotoResult');
        const download = document.getElementById('talkingPhotoDownload');

        try {
            const job = await requestJson(`/api/talking-photo/jobs/${jobId}`);
            setStatus(job.error ? `${phaseText(job)}\n${job.error}` : phaseText(job));

            if (job.status === 'completed' && job.result?.video_url) {
                if (result) {
                    result.src = job.result.video_url;
                    result.hidden = false;
                    result.load();
                }
                if (download) {
                    download.href = job.result.video_url;
                    download.hidden = false;
                }
                if (cancel) {
                    cancel.hidden = true;
                    delete cancel.dataset.jobId;
                }
                if (create) create.disabled = false;
                return;
            }

            if (job.status === 'failed' || job.status === 'cancelled') {
                if (cancel) {
                    cancel.hidden = true;
                    delete cancel.dataset.jobId;
                }
                if (create) create.disabled = false;
                return;
            }

            pollTimer = setTimeout(() => pollJob(jobId), 1000);
        } catch (error) {
            setStatus(error.message);
            if (cancel) cancel.hidden = true;
            if (create) create.disabled = false;
        }
    }

    function mountButton() {
        if (document.getElementById(BUTTON_ID)) return;
        const host = document.querySelector('.top-actions');
        if (!host) return;

        const button = node('button', 'icon-btn', '🗣️');
        button.id = BUTTON_ID;
        button.type = 'button';
        button.title = localText('Talking Photo', 'Talking Photo');
        button.setAttribute('aria-label', localText(
            'Talking Photo öffnen',
            'Open Talking Photo',
        ));
        button.addEventListener('click', openModal);

        const settings = document.getElementById('settingsButton');
        host.insertBefore(button, settings || host.firstChild);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountButton, {once: true});
    } else {
        mountButton();
    }
})();