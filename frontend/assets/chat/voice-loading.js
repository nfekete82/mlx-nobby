(function () {
    'use strict';

    if (!document.getElementById('mlxSpeechLoadingStyles')) {
        const style = document.createElement('style');
        style.id = 'mlxSpeechLoadingStyles';
        style.textContent = `
            @keyframes mlx-speech-loading-spin {
                to { transform: rotate(360deg); }
            }

            .mlx-message-speech-button:disabled {
                opacity: 1 !important;
                cursor: progress;
            }

            .mlx-message-speech-button:disabled svg {
                animation: mlx-speech-loading-spin .8s linear infinite;
                transform-origin: 50% 50%;
                transform-box: fill-box;
            }

            @media (prefers-reduced-motion: reduce) {
                .mlx-message-speech-button:disabled svg {
                    animation: none;
                    opacity: .55;
                }
            }
        `;
        document.head.appendChild(style);
    }

    if (!document.querySelector('script[data-mlx-assistant-read-aloud]')) {
        const script = document.createElement('script');
        script.src = '/assets/chat/assistant-read-aloud.js?v=20261003-read-aloud-reliability';
        script.async = false;
        script.dataset.mlxAssistantReadAloud = '1';
        script.addEventListener('error', () => {
            console.error('[assistant-read-aloud] Failed to load stability controller');
        }, { once: true });
        document.head.appendChild(script);
    }
})();
