(function () {
    'use strict';

    let activeAudio = null;
    let activeUrl = null;

    function readAloudLabel() {
        return window.MLXI18n?.t?.(
            'rendering.speech_read_aloud',
            'Read aloud'
        ) || 'Read aloud';
    }

    function extractUserText(article) {
        const content = article?.querySelector('.message-content');
        if (!content) return '';
        return String(content.innerText || content.textContent || '').trim();
    }

    function stopActiveAudio() {
        if (activeAudio) {
            try {
                activeAudio.pause();
            } catch (_) {}
            activeAudio = null;
        }
        if (activeUrl) {
            URL.revokeObjectURL(activeUrl);
            activeUrl = null;
        }
    }

    async function playUserMessage(article, button) {
        const text = extractUserText(article);
        if (!text || button.disabled) return;

        const originalTitle = button.title;
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');

        try {
            stopActiveAudio();

            const response = await fetch('/api/mlx/audio/speech', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    input: text,
                    language: 'de',
                    response_format: 'mp3'
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

            const cleanup = () => {
                if (activeUrl) {
                    URL.revokeObjectURL(activeUrl);
                    activeUrl = null;
                }
                activeAudio = null;
            };

            activeAudio.addEventListener('ended', cleanup, { once: true });
            activeAudio.addEventListener('error', cleanup, { once: true });
            await activeAudio.play();
        } catch (error) {
            console.error('[voice] User message playback failed:', error);
            button.title = String(error?.message || error || originalTitle);
            setTimeout(() => {
                button.title = originalTitle;
            }, 3000);
        } finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
        }
    }

    function makeButton(article) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'message-action-btn message-action-icon mlx-user-speech-button';
        button.title = readAloudLabel();
        button.setAttribute('aria-label', button.title);
        button.innerHTML = `
            <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M11 5 6 9H3v6h3l5 4Z"></path>
                <path d="M15 9.5a4 4 0 0 1 0 5"></path>
                <path d="M17.5 7a7 7 0 0 1 0 10"></path>
            </svg>`;
        button.addEventListener('click', () => playUserMessage(article, button));
        return button;
    }

    function syncUserSpeechButtons() {
        document.querySelectorAll('.message.user').forEach(article => {
            const actions = article.querySelector('.message-actions');
            if (!actions || actions.querySelector('.mlx-user-speech-button')) return;
            actions.appendChild(makeButton(article));
        });
    }

    function init() {
        syncUserSpeechButtons();
        const messages = document.getElementById('messagesInner');
        if (!messages) return;
        const observer = new MutationObserver(syncUserSpeechButtons);
        observer.observe(messages, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
