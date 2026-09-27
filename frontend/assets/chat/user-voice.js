(function () {
    'use strict';

    let activeAudio = null;
    let activeUrl = null;
    let activeArticle = null;
    let activeButton = null;

    function readAloudLabel() {
        return window.MLXI18n?.t?.(
            'rendering.speech_read_aloud',
            'Read aloud'
        ) || 'Read aloud';
    }

    function pauseLabel() {
        return window.MLXI18n?.t?.(
            'rendering.speech_pause',
            'Pause'
        ) || 'Pause';
    }

    function resumeLabel() {
        return window.MLXI18n?.t?.(
            'rendering.speech_resume',
            'Resume'
        ) || 'Resume';
    }

    function copyLabel() {
        return window.MLXI18n?.t?.(
            'rendering.copy',
            'Copy'
        ) || 'Copy';
    }

    function copiedLabel() {
        return window.MLXI18n?.t?.(
            'rendering.copied',
            'Copied'
        ) || 'Copied';
    }

    function extractUserText(article) {
        const content = article?.querySelector('.message-content');
        if (!content) return '';
        return String(content.innerText || content.textContent || '').trim();
    }

    function setButtonLabel(button, label) {
        if (!button) return;
        button.title = label;
        button.setAttribute('aria-label', label);
    }

    async function copyUserMessage(article, button) {
        const text = extractUserText(article);
        if (!text) return;

        const originalLabel = copyLabel();

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                textarea.remove();
            }

            setButtonLabel(button, copiedLabel());
            setTimeout(() => {
                setButtonLabel(button, originalLabel);
            }, 1500);
        } catch (error) {
            console.error('[voice] User message copy failed:', error);
            setButtonLabel(button, String(error?.message || error || originalLabel));
            setTimeout(() => {
                setButtonLabel(button, originalLabel);
            }, 3000);
        }
    }

    function clearActiveAudio() {
        if (activeAudio) {
            try {
                activeAudio.pause();
            } catch (_) {}
        }
        if (activeUrl) {
            URL.revokeObjectURL(activeUrl);
        }
        setButtonLabel(activeButton, readAloudLabel());
        activeAudio = null;
        activeUrl = null;
        activeArticle = null;
        activeButton = null;
    }

    function currentVoiceSettings() {
        const settings = window.MLXVoice?.getSettings?.() || {};
        return {
            voice: String(settings.voice || 'Pervin'),
            speed: Number(settings.speed ?? 1)
        };
    }

    async function playUserMessage(article, button) {
        const text = extractUserText(article);
        if (!text || button.disabled) return;

        if (activeAudio && activeArticle === article) {
            if (activeAudio.paused) {
                await activeAudio.play();
                setButtonLabel(button, pauseLabel());
            } else {
                activeAudio.pause();
                setButtonLabel(button, resumeLabel());
            }
            return;
        }

        clearActiveAudio();

        const originalTitle = button.title;
        const voiceSettings = currentVoiceSettings();
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');

        try {
            const response = await fetch('/api/mlx/audio/speech', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    input: text,
                    language: 'de',
                    response_format: 'mp3',
                    voice: voiceSettings.voice,
                    speed: voiceSettings.speed,
                    instruct: ''
                })
            });

            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const data = await response.json();
                    detail = data?.detail || detail;
                } catch (_) {}
                throw new Error(detail);
            }

            const blob = await response.blob();
            activeUrl = URL.createObjectURL(blob);
            activeAudio = new Audio(activeUrl);
            activeArticle = article;
            activeButton = button;

            const cleanup = () => {
                if (activeUrl) {
                    URL.revokeObjectURL(activeUrl);
                }
                setButtonLabel(button, readAloudLabel());
                activeAudio = null;
                activeUrl = null;
                activeArticle = null;
                activeButton = null;
            };

            activeAudio.addEventListener('ended', cleanup, { once: true });
            activeAudio.addEventListener('error', cleanup, { once: true });
            await activeAudio.play();
            setButtonLabel(button, pauseLabel());
        } catch (error) {
            console.error('[voice] User message playback failed:', error);
            button.title = String(error?.message || error || originalTitle);
            setTimeout(() => {
                setButtonLabel(button, readAloudLabel());
            }, 3000);
            clearActiveAudio();
        } finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
        }
    }

    function makeCopyButton(article) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'message-action-btn message-action-icon mlx-user-copy-button';
        setButtonLabel(button, copyLabel());
        button.innerHTML = `
            <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="10" height="10" rx="2"></rect>
                <path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path>
            </svg>`;
        button.addEventListener('click', () => copyUserMessage(article, button));
        return button;
    }

    function makeSpeechButton(article) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'message-action-btn message-action-icon mlx-user-speech-button';
        setButtonLabel(button, readAloudLabel());
        button.innerHTML = `
            <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M11 5 6 9H3v6h3l5 4Z"></path>
                <path d="M15 9.5a4 4 0 0 1 0 5"></path>
                <path d="M17.5 7a7 7 0 0 1 0 10"></path>
            </svg>`;
        button.addEventListener('click', () => playUserMessage(article, button));
        return button;
    }

    function syncUserActions() {
        document.querySelectorAll('.message.user').forEach(article => {
            const actions = article.querySelector('.message-actions');
            if (!actions) return;

            if (!actions.querySelector('.mlx-user-copy-button')) {
                actions.appendChild(makeCopyButton(article));
            }

            if (!actions.querySelector('.mlx-user-speech-button')) {
                actions.appendChild(makeSpeechButton(article));
            }
        });
    }

    function loadShortsStudio() {
        if (document.querySelector('script[data-mlx-shorts-studio]')) return;
        const script = document.createElement('script');
        script.src = '/assets/chat/shorts-studio.js?v=20260927-shorts-studio-v2';
        script.dataset.mlxShortsStudio = '1';
        script.addEventListener('error', () => {
            console.error('[shorts-studio] Failed to load integration');
        }, { once: true });
        document.head.appendChild(script);
    }

    function init() {
        loadShortsStudio();
        syncUserActions();
        const messages = document.getElementById('messagesInner');
        if (!messages) return;
        const observer = new MutationObserver(syncUserActions);
        observer.observe(messages, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
