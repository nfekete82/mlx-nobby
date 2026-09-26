(function () {
    'use strict';

    const STORAGE_KEY = 'mlx-nobby-voice-settings-v1';
    const DEFAULTS = {
        voice: 'Pervin',
        speed: 1.0,
        auto_read: false
    };
    const VOICES = [
        { id: 'Pervin', label: 'Pervin', kind: 'clone' },
        { id: 'Serena', label: 'Serena', kind: 'preset' }
    ];
    const SPEEDS = [0.8, 0.9, 1.0, 1.1, 1.25];

    let settings = loadSettings();
    let autoReadTimer = null;
    const autoReadSeen = new Set();
    const nativeFetch = window.fetch.bind(window);

    function normalizeSettings(value) {
        const voice = VOICES.some(item => item.id === value?.voice)
            ? value.voice
            : DEFAULTS.voice;
        const speedValue = Number(value?.speed);
        const speed = SPEEDS.includes(speedValue)
            ? speedValue
            : DEFAULTS.speed;
        return {
            voice,
            speed,
            auto_read: value?.auto_read === true
        };
    }

    function loadSettings() {
        try {
            return normalizeSettings(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'));
        } catch (_) {
            return { ...DEFAULTS };
        }
    }

    function saveSettings() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
        window.dispatchEvent(new CustomEvent('mlx:voice-settings-changed', {
            detail: { ...settings }
        }));
    }

    function voiceLabel() {
        return VOICES.find(item => item.id === settings.voice)?.label || settings.voice;
    }

    function injectStyles() {
        if (document.getElementById('mlxVoiceStyles')) return;
        const style = document.createElement('style');
        style.id = 'mlxVoiceStyles';
        style.textContent = `
            .composer-actions { position: relative; }
            .mlx-voice-button {
                width: 36px; height: 36px; border: 0; border-radius: 10px;
                display: inline-flex; align-items: center; justify-content: center;
                background: transparent; color: inherit; cursor: pointer;
                opacity: .78; transition: background .15s ease, opacity .15s ease;
            }
            .mlx-voice-button:hover, .mlx-voice-button[aria-expanded="true"] {
                background: color-mix(in srgb, currentColor 9%, transparent); opacity: 1;
            }
            .mlx-voice-button.is-auto { opacity: 1; }
            .mlx-voice-button svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
            .mlx-voice-popover {
                position: absolute; right: 46px; bottom: 44px; z-index: 1200;
                width: 250px; padding: 10px; border-radius: 14px;
                border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
                background: var(--panel-bg, var(--background, #151515));
                color: inherit; box-shadow: 0 14px 40px rgba(0,0,0,.28);
            }
            .mlx-voice-popover[hidden] { display: none; }
            .mlx-voice-title { padding: 3px 6px 8px; font-size: 12px; font-weight: 650; opacity: .7; }
            .mlx-voice-option {
                width: 100%; display: flex; align-items: center; gap: 10px;
                padding: 9px 8px; border: 0; border-radius: 9px;
                background: transparent; color: inherit; cursor: pointer; text-align: left;
            }
            .mlx-voice-option:hover { background: color-mix(in srgb, currentColor 8%, transparent); }
            .mlx-voice-dot { width: 14px; height: 14px; border: 1.5px solid currentColor; border-radius: 50%; opacity: .55; position: relative; flex: 0 0 auto; }
            .mlx-voice-option.is-active .mlx-voice-dot { opacity: 1; }
            .mlx-voice-option.is-active .mlx-voice-dot::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: currentColor; }
            .mlx-voice-option-copy { display: flex; flex-direction: column; gap: 1px; }
            .mlx-voice-option-copy small { opacity: .55; font-size: 11px; }
            .mlx-voice-divider { height: 1px; margin: 8px 4px; background: color-mix(in srgb, currentColor 12%, transparent); }
            .mlx-voice-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 6px; font-size: 13px; }
            .mlx-voice-speed { border: 1px solid color-mix(in srgb, currentColor 15%, transparent); border-radius: 8px; background: transparent; color: inherit; padding: 5px 7px; }
            .mlx-voice-toggle { position: relative; width: 34px; height: 20px; flex: 0 0 auto; }
            .mlx-voice-toggle input { position: absolute; opacity: 0; pointer-events: none; }
            .mlx-voice-toggle-track { position: absolute; inset: 0; border-radius: 999px; background: color-mix(in srgb, currentColor 18%, transparent); cursor: pointer; }
            .mlx-voice-toggle-track::after { content: ''; position: absolute; width: 16px; height: 16px; left: 2px; top: 2px; border-radius: 50%; background: currentColor; opacity: .8; transition: transform .15s ease; }
            .mlx-voice-toggle input:checked + .mlx-voice-toggle-track::after { transform: translateX(14px); opacity: 1; }
            .mlx-voice-toggle input:checked + .mlx-voice-toggle-track { background: color-mix(in srgb, currentColor 28%, transparent); }
        `;
        document.head.appendChild(style);
    }

    function buildPopover() {
        const actions = document.querySelector('.composer-actions');
        const dictation = document.getElementById('dictationButton');
        if (!actions || !dictation || document.getElementById('mlxVoiceButton')) return;

        injectStyles();

        const button = document.createElement('button');
        button.id = 'mlxVoiceButton';
        button.className = 'mlx-voice-button';
        button.type = 'button';
        button.setAttribute('aria-haspopup', 'dialog');
        button.setAttribute('aria-expanded', 'false');
        button.innerHTML = `
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M11 5 6 9H3v6h3l5 4Z"></path>
                <path d="M15 9.5a4 4 0 0 1 0 5"></path>
                <path d="M17.5 7a7 7 0 0 1 0 10"></path>
            </svg>`;

        const popover = document.createElement('div');
        popover.id = 'mlxVoicePopover';
        popover.className = 'mlx-voice-popover';
        popover.hidden = true;
        popover.setAttribute('role', 'dialog');
        popover.setAttribute('aria-label', 'Stimme');

        renderPopover(popover);
        actions.insertBefore(button, dictation);
        actions.appendChild(popover);

        const syncButton = () => {
            button.title = `Stimme: ${voiceLabel()}`;
            button.setAttribute('aria-label', button.title);
            button.classList.toggle('is-auto', settings.auto_read);
        };
        syncButton();

        button.addEventListener('click', event => {
            event.stopPropagation();
            popover.hidden = !popover.hidden;
            button.setAttribute('aria-expanded', String(!popover.hidden));
            if (!popover.hidden) renderPopover(popover);
        });

        document.addEventListener('click', event => {
            if (!popover.hidden && !popover.contains(event.target) && event.target !== button) {
                popover.hidden = true;
                button.setAttribute('aria-expanded', 'false');
            }
        });

        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !popover.hidden) {
                popover.hidden = true;
                button.setAttribute('aria-expanded', 'false');
                button.focus();
            }
        });

        window.addEventListener('mlx:voice-settings-changed', () => {
            syncButton();
            if (!popover.hidden) renderPopover(popover);
            syncSpeechStatuses();
        });
    }

    function renderPopover(popover) {
        popover.replaceChildren();
        const title = document.createElement('div');
        title.className = 'mlx-voice-title';
        title.textContent = 'Stimme';
        popover.appendChild(title);

        VOICES.forEach(item => {
            const option = document.createElement('button');
            option.type = 'button';
            option.className = 'mlx-voice-option' + (settings.voice === item.id ? ' is-active' : '');
            option.innerHTML = `
                <span class="mlx-voice-dot"></span>
                <span class="mlx-voice-option-copy">
                    <strong>${item.label}</strong>
                    <small>${item.kind === 'clone' ? 'Geklonte Stimme' : 'Qwen Preset'}</small>
                </span>`;
            option.addEventListener('click', () => {
                settings.voice = item.id;
                saveSettings();
                renderPopover(popover);
            });
            popover.appendChild(option);
        });

        const divider = document.createElement('div');
        divider.className = 'mlx-voice-divider';
        popover.appendChild(divider);

        const speedRow = document.createElement('label');
        speedRow.className = 'mlx-voice-row';
        speedRow.textContent = 'Geschwindigkeit';
        const select = document.createElement('select');
        select.className = 'mlx-voice-speed';
        SPEEDS.forEach(speed => {
            const option = document.createElement('option');
            option.value = String(speed);
            option.textContent = `${speed.toFixed(speed === 1 ? 1 : 2).replace(/0$/, '')}×`;
            option.selected = settings.speed === speed;
            select.appendChild(option);
        });
        select.addEventListener('change', () => {
            settings.speed = Number(select.value);
            saveSettings();
        });
        speedRow.appendChild(select);
        popover.appendChild(speedRow);

        const autoRow = document.createElement('div');
        autoRow.className = 'mlx-voice-row';
        const autoLabel = document.createElement('span');
        autoLabel.textContent = window.MLXI18n?.t(
            'voice.auto_read',
            'Auto-read responses'
        ) || 'Auto-read responses';
        const toggle = document.createElement('label');
        toggle.className = 'mlx-voice-toggle';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = settings.auto_read;
        const track = document.createElement('span');
        track.className = 'mlx-voice-toggle-track';
        checkbox.addEventListener('change', () => {
            settings.auto_read = checkbox.checked;
            saveSettings();
        });
        toggle.append(checkbox, track);
        autoRow.append(autoLabel, toggle);
        popover.appendChild(autoRow);
    }

    function isSpeechRequest(input) {
        const raw = typeof input === 'string' ? input : input?.url;
        if (!raw) return false;
        try {
            const url = new URL(raw, window.location.origin);
            return url.pathname === '/api/mlx/audio/speech';
        } catch (_) {
            return false;
        }
    }

    window.fetch = function mlxVoiceFetch(input, init) {
        if (!isSpeechRequest(input) || !init?.body) {
            return nativeFetch(input, init);
        }
        try {
            const body = JSON.parse(init.body);
            body.voice = settings.voice;
            body.speed = settings.speed;
            if (settings.voice === 'Pervin') {
                body.instruct = '';
            }
            return nativeFetch(input, {
                ...init,
                body: JSON.stringify(body)
            });
        } catch (_) {
            return nativeFetch(input, init);
        }
    };

    function syncSpeechStatuses() {
        const label = voiceLabel();
        document.querySelectorAll('.mlx-message-speech-status').forEach(node => {
            const currentText = node.textContent || '';
            if (!currentText) return;
            const nextText = currentText
                .replace(/^Serena\b/, label)
                .replace(/^Pervin\b/, label);
            if (nextText !== currentText) {
                node.textContent = nextText;
            }
        });
    }

    function extractAssistantText(article) {
        const content = article?.querySelector('.message-content');
        if (!content) return '';
        for (const child of content.children) {
            if (child.tagName === 'DIV' && !child.className) {
                return String(child.innerText || child.textContent || '').trim();
            }
        }
        return '';
    }

    function scheduleAutoRead() {
        syncSpeechStatuses();
        if (!settings.auto_read) return;
        clearTimeout(autoReadTimer);
        autoReadTimer = setTimeout(() => {
            const articles = [...document.querySelectorAll('.message.assistant')];
            const article = articles.at(-1);
            if (!article) return;
            const text = extractAssistantText(article);
            if (!text || text.length < 2 || autoReadSeen.has(text)) return;
            const button = article.querySelector('.mlx-message-speech-button');
            if (!button || button.disabled) return;
            autoReadSeen.add(text);
            while (autoReadSeen.size > 20) {
                autoReadSeen.delete(autoReadSeen.values().next().value);
            }
            button.click();
        }, 1300);
    }

    function init() {
        buildPopover();
        syncSpeechStatuses();
        const messages = document.getElementById('messagesInner');
        if (messages) {
            const observer = new MutationObserver(scheduleAutoRead);
            observer.observe(messages, { childList: true, subtree: true, characterData: true });
        }
    }

    window.MLXVoice = {
        getSettings: () => ({ ...settings }),
        getVoiceLabel: voiceLabel
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
