(function () {
    'use strict';

    if (document.getElementById('mlxSpeechLoadingStyles')) return;

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
})();
