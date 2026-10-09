(() => {
    'use strict';

    const BUTTON_ID = 'talkingPhotoButton';
    const MODAL_ID = 'talkingPhotoModal';
    const STYLE_ID = 'talkingPhotoStyles';
    const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
    const JOB_STORAGE_KEY = 'mlxTalkingPhotoCurrentJob';
    const TERMINAL_STATES = new Set(['completed', 'cancelled', 'failed']);
    let pollTimer = null;
    let pollInFlight = false;
    let elapsedTicker = null;
    let previewUrl = null;
    let currentJobId = null;
    let lastJob = null;
    let preparing = false;

    function jobIsBusy() {
        return preparing || Boolean(currentJobId && (!lastJob || !TERMINAL_STATES.has(lastJob.status)));
    }

    function rememberJob(id) {
        currentJobId = id;
        lastJob = null;
        try {
            sessionStorage.setItem(JOB_STORAGE_KEY, id);
        } catch (_error) {
            // Session storage may be disabled; the in-memory job still works.
        }
        updateButtonIndicator();
    }

    function forgetJob() {
        currentJobId = null;
        lastJob = null;
        try {
            sessionStorage.removeItem(JOB_STORAGE_KEY);
        } catch (_error) {
            // Storage is optional.
        }
        updateButtonIndicator();
    }

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
                const error = new Error(payload.detail || `HTTP ${response.status}`);
                error.httpStatus = response.status;
                throw error;
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
                position: relative; box-sizing: border-box;
                width: min(1640px, calc(100vw - 36px));
                max-height: calc(100vh - 28px);
                max-height: calc(100dvh - 28px);
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
                display: grid;
                grid-template-columns: minmax(0, .94fr) minmax(0, 1.06fr) minmax(0, 1fr);
                align-items: start; gap: 18px;
            }
            .mlx-talking-photo-grid > * { min-width: 0; }
            .mlx-talking-photo-output {
                min-width: 0; border: 1px solid rgba(148,163,184,.22);
                border-radius: 14px; background: rgba(17,29,45,.55);
                padding: 14px; display: grid; align-content: start; gap: 12px;
            }
            .mlx-talking-photo-output h3 {
                margin: 0; font-size: 1.03rem; line-height: 1.4;
            }
            .mlx-talking-photo-result-frame {
                min-height: 270px; border: 1px solid rgba(148,163,184,.18);
                border-radius: 12px; background: #070e19;
                display: grid; place-items: center; overflow: hidden;
            }
            .mlx-talking-photo-result-placeholder {
                padding: 24px 14px; text-align: center; font-size: .86rem;
                color: #a8b9d0; line-height: 1.5;
            }
            .mlx-talking-photo-result-placeholder[hidden] { display: none; }
            .mlx-talking-photo-placeholder-icon {
                display: block; font-size: 2rem; opacity: .6; margin-bottom: 10px;
            }
            .mlx-talking-photo-field { display: grid; gap: 7px; margin-bottom: 13px; }
            .mlx-talking-photo-field[hidden] { display: none; }
            .mlx-talking-photo-field > span { font-size: .82rem; opacity: .78; }
            .mlx-talking-photo-field input,
            .mlx-talking-photo-field select,
            .mlx-talking-photo-field textarea {
                width: 100%; box-sizing: border-box; border: 1px solid rgba(148,163,184,.25);
                border-radius: 10px; background: #111d2d; color: inherit; padding: 10px 12px;
            }
            .mlx-talking-photo-field textarea { min-height: 148px; resize: vertical; }
            .mlx-talking-photo-preview {
                display: block; box-sizing: border-box; width: 100%;
                min-height: 200px; max-height: min(57vh, 610px);
                object-fit: contain; border-radius: 12px; background: #09111d;
                border: 1px solid rgba(148,163,184,.18);
            }
            .mlx-talking-photo-preview[hidden] { display: none; }
            .mlx-talking-photo-status {
                margin: 0; padding: 10px 12px; border-radius: 10px;
                background: rgba(148,163,184,.08); font-size: .86rem; white-space: pre-wrap;
            }
            .mlx-talking-photo-activity {
                display: grid; gap: 10px; margin: 0; padding: 14px;
                background: rgba(37, 99, 235, .09); border: 1px solid rgba(96, 165, 250, .24);
                border-radius: 12px;
            }
            .mlx-talking-photo-activity[hidden] { display: none; }
            .mlx-talking-photo-activity-title { display: flex; align-items: center; gap: 10px; }
            .mlx-talking-photo-activity-title strong { font-size: .91rem; font-weight: 600; }
            .mlx-talking-photo-spinner {
                flex: 0 0 auto; width: 17px; height: 17px; border-radius: 50%;
                border: 2px solid rgba(147, 197, 253, .25); border-top-color: #93c5fd;
                animation: mlx-talking-photo-spin .85s linear infinite;
            }
            .mlx-talking-photo-spinner[hidden] { display: none; }
            @keyframes mlx-talking-photo-spin { to { transform: rotate(360deg); } }
            .mlx-talking-photo-track {
                height: 7px; overflow: hidden; border-radius: 999px;
                background: rgba(148, 163, 184, .18);
            }
            .mlx-talking-photo-fill {
                height: 100%; width: 0; border-radius: inherit; background: #60a5fa;
                transition: width .3s ease;
            }
            .mlx-talking-photo-track.is-indeterminate .mlx-talking-photo-fill {
                width: 35%; animation: mlx-talking-photo-travel 1.6s ease-in-out infinite alternate;
            }
            @keyframes mlx-talking-photo-travel {
                from { transform: translateX(-100%); }
                to { transform: translateX(285%); }
            }
            .mlx-talking-photo-activity-meta {
                display: flex; flex-wrap: wrap; justify-content: space-between;
                gap: 8px; font-size: .77rem; color: #bacbe0;
            }
            #talkingPhotoButton.is-generating { position: relative; }
            #talkingPhotoButton.is-generating::after,
            #talkingPhotoButton.is-finished::after {
                content: ''; position: absolute; top: 3px; right: 3px;
                width: 8px; height: 8px; border-radius: 50%; background: #60a5fa;
                box-shadow: 0 0 0 2px #0e1623;
            }
            #talkingPhotoButton.is-generating::after { animation: mlx-talking-photo-pulse 1.4s ease-in-out infinite; }
            #talkingPhotoButton.is-finished::after { background: #34d399; }
            @keyframes mlx-talking-photo-pulse { 50% { opacity: .35; } }
            @media (prefers-reduced-motion: reduce) {
                .mlx-talking-photo-spinner, .mlx-talking-photo-track.is-indeterminate .mlx-talking-photo-fill,
                #talkingPhotoButton.is-generating::after { animation: none; }
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
                display: block; width: 100%; height: auto;
                max-height: min(52vh, 540px); max-height: min(52dvh, 540px);
                object-fit: contain; background: #000;
            }
            .mlx-talking-photo-result[hidden] { display: none; }
            .mlx-talking-photo-hint { font-size: .78rem; opacity: .66; margin-top: 5px; }
            @media (min-width: 1101px) {
                .mlx-talking-photo-output { position: sticky; top: 0; }
            }
            @media (max-width: 1100px) {
                .mlx-talking-photo-grid {
                    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                }
                .mlx-talking-photo-output { grid-column: 1 / -1; }
                .mlx-talking-photo-result-frame { min-height: 240px; }
                .mlx-talking-photo-result { max-height: 420px; }
            }
            @media (max-width: 700px) {
                .mlx-talking-photo-modal { padding: 10px; }
                .mlx-talking-photo-dialog {
                    width: 100%; max-height: calc(100dvh - 20px); padding: 16px;
                }
                .mlx-talking-photo-grid { grid-template-columns: minmax(0, 1fr); }
                .mlx-talking-photo-output { grid-column: 1; padding: 12px; }
                .mlx-talking-photo-result-frame { min-height: 220px; }
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
        // The media-lifecycle listener discards a finished, unsaved result
        // on closing. Keep only genuinely active jobs in the background.
        if (lastJob && TERMINAL_STATES.has(lastJob.status)) {
            clearPolling();
            stopElapsedTicker();
            forgetJob();
        }
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
        const left = node('div', 'mlx-talking-photo-source');
        const right = node('div', 'mlx-talking-photo-settings');
        const output = node('aside', 'mlx-talking-photo-output');
        output.id = 'talkingPhotoOutput';
        output.setAttribute('aria-label', localText('Ergebnis und Fortschritt', 'Result and progress'));
        output.append(node('h3', '', localText('Ergebnis & Fortschritt', 'Result & progress')));

        const resultFrame = node('div', 'mlx-talking-photo-result-frame');
        resultFrame.id = 'talkingPhotoResultFrame';
        const placeholder = node('div', 'mlx-talking-photo-result-placeholder');
        placeholder.id = 'talkingPhotoResultPlaceholder';
        const placeholderIcon = node('span', 'mlx-talking-photo-placeholder-icon', '▶');
        placeholderIcon.setAttribute('aria-hidden', 'true');
        placeholder.append(placeholderIcon, node(
            'span', '', localText(
                'Dein fertiges Video erscheint hier. Während der Erstellung siehst du darunter den Fortschritt.',
                'Your finished video will appear here. During generation, progress is shown below.',
            ),
        ));
        resultFrame.append(placeholder);
        output.append(resultFrame);

        grid.append(left, right, output);
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

        const leadInLabel = node('label', 'mlx-talking-photo-field');
        leadInLabel.id = 'talkingPhotoLeadInField';
        leadInLabel.append(node('span', '', localText(
            'Audiovorlauf · Testoption', 'Audio lead-in · experiment',
        )));
        const leadInSelect = document.createElement('select');
        leadInSelect.id = 'talkingPhotoLeadIn';
        [
            ['0', localText('Aus · bisheriges Verhalten', 'Off · existing behavior')],
            ['500', localText('0,5 Sekunden Stille vor der Sprache', '0.5 seconds of silence before speech')],
        ].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            leadInSelect.append(option);
        });
        leadInSelect.value = '0';
        leadInLabel.append(leadInSelect);
        leadInLabel.append(node(
            'div', 'mlx-talking-photo-hint',
            localText(
                'Experiment gegen verschluckte Lippenbewegungen am Satzanfang. Ton und LTX-Video erhalten denselben Vorlauf; das Audio darf zusammen maximal 20 Sekunden lang sein.',
                'Experiment for missed lip movements at the start. Audio and LTX video share the same lead-in; combined audio may be at most 20 seconds.',
            ),
        ));
        right.append(leadInLabel);

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
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        output.append(status);

        const activity = node('section', 'mlx-talking-photo-activity');
        activity.id = 'talkingPhotoActivity';
        activity.hidden = true;
        activity.setAttribute('aria-label', localText('Bearbeitungsstatus', 'Processing status'));
        const activityTitle = node('div', 'mlx-talking-photo-activity-title');
        const spinner = node('span', 'mlx-talking-photo-spinner');
        spinner.id = 'talkingPhotoSpinner';
        spinner.setAttribute('aria-hidden', 'true');
        const activityPhase = node('strong', '', '');
        activityPhase.id = 'talkingPhotoActivityPhase';
        activityTitle.append(spinner, activityPhase);
        const track = node('div', 'mlx-talking-photo-track');
        track.id = 'talkingPhotoProgressTrack';
        track.setAttribute('role', 'progressbar');
        track.setAttribute('aria-valuemin', '0');
        track.setAttribute('aria-valuemax', '100');
        const fill = node('div', 'mlx-talking-photo-fill');
        fill.id = 'talkingPhotoProgressFill';
        track.append(fill);
        const meta = node('div', 'mlx-talking-photo-activity-meta');
        const progressLabel = node('span', '', '');
        progressLabel.id = 'talkingPhotoProgressLabel';
        const elapsed = node('span', '', '');
        elapsed.id = 'talkingPhotoElapsed';
        meta.append(progressLabel, elapsed);
        activity.append(activityTitle, track, meta);
        output.append(activity);

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
        output.append(actions);

        const result = document.createElement('video');
        result.id = 'talkingPhotoResult';
        result.className = 'mlx-talking-photo-result';
        result.controls = true;
        result.playsInline = true;
        result.hidden = true;
        resultFrame.append(result);

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

        engineSelect.addEventListener('change', () => {
            leadInLabel.hidden = engineSelect.value === 'fast';
            if (leadInLabel.hidden) leadInSelect.value = '0';
            refreshProviderStatus();
        });
        create.addEventListener('click', startJob);
        cancel.addEventListener('click', cancelCurrentJob);
        document.body.append(modal);
        return modal;
    }

    function setStatus(message) {
        const status = document.getElementById('talkingPhotoStatus');
        if (status && status.textContent !== message) status.textContent = message;
    }

    function updateButtonIndicator() {
        const button = document.getElementById(BUTTON_ID);
        if (!button) return;
        const busy = jobIsBusy();
        const finished = lastJob?.status === 'completed';
        button.classList.toggle('is-generating', busy);
        button.classList.toggle('is-finished', finished);
        button.setAttribute('aria-busy', busy ? 'true' : 'false');
        button.setAttribute('aria-label', busy
            ? localText('Talking Photo wird erstellt – Fortschritt anzeigen', 'Talking Photo generating – show progress')
            : finished
                ? localText('Talking Photo fertig – Video ansehen', 'Talking Photo ready – view video')
                : localText('Talking Photo öffnen', 'Open Talking Photo'));
        button.title = busy
            ? localText('Talking Photo wird erstellt', 'Talking Photo generating')
            : finished
                ? localText('Talking Photo fertig', 'Talking Photo ready')
                : 'Talking Photo';
    }

    function renderElapsed() {
        const elapsed = document.getElementById('talkingPhotoElapsed');
        if (!elapsed || !lastJob) return;
        const start = Number(lastJob.started_at || lastJob.created_at) || Date.now() / 1000;
        const end = TERMINAL_STATES.has(lastJob.status)
            ? (Number(lastJob.finished_at) || Date.now() / 1000)
            : Date.now() / 1000;
        const seconds = Math.max(0, Math.floor(end - start));
        const minutes = Math.floor(seconds / 60);
        const clock = String(seconds % 60).padStart(2, '0');
        elapsed.textContent = localText(
            `Laufzeit: ${minutes}:${clock}`,
            `Elapsed: ${minutes}:${clock}`,
        );
    }

    function stopElapsedTicker() {
        if (elapsedTicker) clearInterval(elapsedTicker);
        elapsedTicker = null;
    }

    function renderActivity(job) {
        const activity = document.getElementById('talkingPhotoActivity');
        if (!activity) return;
        activity.hidden = false;
        const terminal = TERMINAL_STATES.has(job.status);
        const spinner = document.getElementById('talkingPhotoSpinner');
        if (spinner) spinner.hidden = terminal;
        const phase = document.getElementById('talkingPhotoActivityPhase');
        if (phase) phase.textContent = phaseText(job);
        const progress = terminal && job.status === 'completed'
            ? 1
            : Number(job.progress);
        const measurable = (terminal && job.status === 'completed')
            || (!terminal && Number.isFinite(progress) && progress > 0);
        const percent = measurable ? Math.min(100, Math.max(0, Math.round(progress * 100))) : 0;
        const track = document.getElementById('talkingPhotoProgressTrack');
        const fill = document.getElementById('talkingPhotoProgressFill');
        if (track) {
            track.classList.toggle('is-indeterminate', !terminal && !measurable);
            if (measurable) {
                track.setAttribute('aria-valuenow', String(percent));
                track.setAttribute('aria-valuetext', terminal
                    ? localText('Abgeschlossen', 'Completed')
                    : localText(`Geschätzt ${percent} Prozent`, `Estimated ${percent} percent`));
            } else {
                track.removeAttribute('aria-valuenow');
                track.setAttribute('aria-valuetext', terminal
                    ? phaseText(job)
                    : localText('Wird bearbeitet, Fortschritt noch nicht messbar', 'Processing, progress not yet measurable'));
            }
        }
        if (fill) fill.style.width = measurable ? `${percent}%` : '';
        const progressLabel = document.getElementById('talkingPhotoProgressLabel');
        if (progressLabel) progressLabel.textContent = terminal
            ? phaseText(job)
            : measurable
                ? localText(`Etwa ${percent} % · geschätzt`, `About ${percent}% · estimated`)
                : localText('Wird bearbeitet …', 'Processing …');
        const elapsed = document.getElementById('talkingPhotoElapsed');
        if (!lastJob && elapsed) elapsed.textContent = localText('Laufzeit: 0:00', 'Elapsed: 0:00');
        renderElapsed();
        if (terminal) {
            stopElapsedTicker();
        } else if (!elapsedTicker) {
            elapsedTicker = setInterval(renderElapsed, 1000);
        }
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
        if (jobIsBusy()) return;
        const create = document.getElementById('talkingPhotoCreate');
        const engine = document.getElementById('talkingPhotoEngine')?.value || 'ltx';
        if (create) create.disabled = true;
        try {
            const status = await requestJson('/api/talking-photo/status');
            if (jobIsBusy()) return;
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
            if (jobIsBusy()) return;
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
        if (!currentJobId) {
            if (result) {
                result.pause();
                result.removeAttribute('src');
                result.hidden = true;
            }
            if (download) download.hidden = true;
        }

        if (lastJob) renderJob(lastJob);
        else if (currentJobId) renderActivity({status: 'queued', phase: 'queued'});
        else if (preparing) renderActivity({status: 'queued', phase: 'queued'});
        const voices = loadVoices();
        if (currentJobId) {
            if (!pollInFlight && !pollTimer) pollJob(currentJobId);
        } else if (!preparing) {
            await refreshProviderStatus();
        }
        await voices;
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
        if (jobIsBusy()) return;

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
        stopElapsedTicker();
        forgetJob(); // A finished/failed job may be replaced by a new request.
        preparing = true;
        updateButtonIndicator();
        if (create) create.disabled = true;
        if (cancel) {
            cancel.hidden = false;
            cancel.disabled = true; // Job ID not assigned yet.
            delete cancel.dataset.jobId;
        }
        if (result) {
            result.pause();
            result.removeAttribute('src');
            result.hidden = true;
        }
        if (download) download.hidden = true;
        renderActivity({status: 'queued', phase: 'preparing'});

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
                    lead_in_ms: Number(document.getElementById('talkingPhotoLeadIn')?.value || 0),
                    speed: 1.0,
                }),
            });
            if (!/^[a-f0-9]{24}$/.test(String(job.id || ''))) {
                throw new Error(localText('Ungültige Job-ID vom Server', 'Invalid server job ID'));
            }
            preparing = false;
            rememberJob(job.id);
            lastJob = job;
            if (cancel) {
                cancel.dataset.jobId = job.id;
                cancel.disabled = false;
            }
            renderJob(job);
            pollJob(job.id);
        } catch (error) {
            preparing = false;
            setStatus(error.message);
            const activity = document.getElementById('talkingPhotoActivity');
            if (activity) activity.hidden = true;
            if (create) create.disabled = false;
            if (cancel) cancel.hidden = true;
            updateButtonIndicator();
            if (document.getElementById(MODAL_ID) && !document.getElementById(MODAL_ID).hidden) {
                refreshProviderStatus();
            }
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
            setStatus(localText('Abbruch angefordert …', 'Cancellation requested …'));
            if (lastJob) lastJob.cancel_requested = true;
        } catch (error) {
            setStatus(error.message);
            cancel.disabled = false;
        }
    }

    function phaseText(job) {
        if (job.cancel_requested && !TERMINAL_STATES.has(job.status)) {
            return localText('Abbruch wird ausgeführt …', 'Cancelling …');
        }
        const phase = String(job.phase || job.status || '');
        const labels = {
            preparing: localText('Bild wird vorbereitet …', 'Preparing image …'),
            queued: localText('Wartet auf freien KI-Slot …', 'Waiting for an AI slot …'),
            tts: localText('Stimme wird erzeugt …', 'Generating voice …'),
            motion: localText('Natürliche Bewegung wird gerendert …', 'Rendering natural motion …'),
            quality: localText('LTX 2.5 rendert das Video …', 'LTX 2.5 rendering video …'),
            lipsync: localText('Lippen werden synchronisiert …', 'Synchronizing lips …'),
            completed: localText('Video ist fertig.', 'Video is ready.'),
            cancelled: localText('Abgebrochen.', 'Cancelled.'),
            failed: localText('Fehlgeschlagen.', 'Failed.'),
        };
        return labels[phase] || localText('Video wird bearbeitet …', 'Processing video …');
    }

    function renderJob(job) {
        const create = document.getElementById('talkingPhotoCreate');
        const cancel = document.getElementById('talkingPhotoCancel');
        const result = document.getElementById('talkingPhotoResult');
        const download = document.getElementById('talkingPhotoDownload');
        const terminal = TERMINAL_STATES.has(job.status);
        lastJob = job;
        setStatus(job.error ? `${phaseText(job)}\n${job.error}` : phaseText(job));
        renderActivity(job);
        updateButtonIndicator();
        if (create) create.disabled = !terminal;
        if (cancel) {
            cancel.hidden = terminal;
            cancel.disabled = Boolean(job.cancel_requested);
            if (!terminal) cancel.dataset.jobId = job.id;
            else delete cancel.dataset.jobId;
        }
        if (terminal) {
            clearPolling();
            if (job.status === 'completed' && job.result?.video_url) {
                if (result) {
                    if (result.getAttribute('src') !== job.result.video_url) {
                        result.src = job.result.video_url;
                        result.load();
                    }
                    result.hidden = false;
                }
                if (download) {
                    download.href = job.result.video_url;
                    download.hidden = false;
                }
            }
        }
    }

    async function pollJob(jobId) {
        if (!jobId || jobId !== currentJobId || pollInFlight) return;
        clearPolling();
        pollInFlight = true;
        try {
            const job = await requestJson(`/api/talking-photo/jobs/${jobId}`);
            if (currentJobId !== jobId) return;
            renderJob(job);
            if (TERMINAL_STATES.has(job.status)) return;
            pollTimer = setTimeout(() => pollJob(jobId), 1000);
        } catch (error) {
            if (currentJobId !== jobId) return;
            if (error.httpStatus === 404) {
                clearPolling();
                stopElapsedTicker();
                forgetJob();
                setStatus(localText(
                    'Der vorherige Job wurde nicht gefunden. Bitte neu starten.',
                    'Previous job not found. Please start again.',
                ));
                const activity = document.getElementById('talkingPhotoActivity');
                if (activity) activity.hidden = true;
                const cancel = document.getElementById('talkingPhotoCancel');
                if (cancel) cancel.hidden = true;
                const create = document.getElementById('talkingPhotoCreate');
                if (create) create.disabled = false;
                return;
            }
            setStatus(localText(
                'Verbindung unterbrochen – Status wird erneut abgefragt. ' + error.message,
                'Connection interrupted – retrying status. ' + error.message,
            ));
            pollTimer = setTimeout(() => pollJob(jobId), 2500);
        } finally {
            pollInFlight = false;
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
        try {
            const remembered = sessionStorage.getItem(JOB_STORAGE_KEY);
            if (remembered && /^[a-f0-9]{24}$/.test(remembered)) {
                currentJobId = remembered;
                pollJob(remembered);
            }
        } catch (_error) {
            // The feature remains usable without session storage.
        }
        updateButtonIndicator();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountButton, {once: true});
    } else {
        mountButton();
    }
})();