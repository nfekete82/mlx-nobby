(function () {
    'use strict';

    const STORAGE_KEY =
        'mlx-web-chat-appearance-v1';

    const DEFAULTS = {
        font_size: 15,
        user_bubble_color: '#2f6fea'
    };


    function normalizeFontSize(value) {
        const size = Number(value);

        if (!Number.isFinite(size)) {
            return DEFAULTS.font_size;
        }

        return Math.min(
            20,
            Math.max(13, Math.round(size))
        );
    }


    function normalizeColor(value) {
        const color =
            String(value || '').trim();

        if (!/^#[0-9a-f]{6}$/i.test(color)) {
            return DEFAULTS.user_bubble_color;
        }

        return color.toLowerCase();
    }


    function loadSettings() {
        try {
            const saved =
                JSON.parse(
                    localStorage.getItem(STORAGE_KEY) ||
                    '{}'
                );

            return {
                font_size:
                    normalizeFontSize(saved.font_size),

                user_bubble_color:
                    normalizeColor(
                        saved.user_bubble_color
                    )
            };
        } catch (_) {
            return { ...DEFAULTS };
        }
    }


    let settings =
        loadSettings();


    function saveSettings() {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify(settings)
        );
    }


    function applySettings() {
        document.documentElement.style.setProperty(
            '--chat-font-size',
            settings.font_size + 'px'
        );

        document.documentElement.style.setProperty(
            '--user-bubble-color',
            settings.user_bubble_color
        );

        const preview =
            document.querySelector(
                '.appearance-bubble-preview'
            );

        if (preview) {
            preview.style.background =
                settings.user_bubble_color;
        }
    }


    function syncControls() {
        const font =
            document.getElementById('chatFontSize');

        const fontValue =
            document.getElementById(
                'chatFontSizeValue'
            );

        const picker =
            document.getElementById(
                'userBubbleColor'
            );

        const hex =
            document.getElementById(
                'userBubbleHex'
            );

        if (font) {
            font.value =
                String(settings.font_size);
        }

        if (fontValue) {
            fontValue.textContent =
                settings.font_size + ' px';
        }

        if (picker) {
            picker.value =
                settings.user_bubble_color;
        }

        if (hex) {
            hex.value =
                settings.user_bubble_color
                    .toUpperCase();
        }
    }


    function updateFont(value) {
        settings.font_size =
            normalizeFontSize(value);

        saveSettings();
        applySettings();
        syncControls();
    }


    function updateColor(value) {
        const color =
            normalizeColor(value);

        settings.user_bubble_color =
            color;

        saveSettings();
        applySettings();
        syncControls();
    }


    function init() {
        applySettings();
        syncControls();

        const font =
            document.getElementById('chatFontSize');

        const picker =
            document.getElementById(
                'userBubbleColor'
            );

        const hex =
            document.getElementById(
                'userBubbleHex'
            );

        const reset =
            document.getElementById(
                'resetAppearance'
            );


        font?.addEventListener(
            'input',
            event => {
                updateFont(event.target.value);
            }
        );


        picker?.addEventListener(
            'input',
            event => {
                updateColor(event.target.value);
            }
        );


        hex?.addEventListener(
            'input',
            event => {
                const value =
                    event.target.value.trim();

                if (
                    /^#[0-9a-f]{6}$/i.test(value)
                ) {
                    updateColor(value);
                }
            }
        );


        hex?.addEventListener(
            'blur',
            () => {
                syncControls();
            }
        );


        hex?.addEventListener(
            'keydown',
            event => {
                if (event.key === 'Enter') {
                    event.preventDefault();

                    updateColor(
                        event.target.value
                    );

                    event.target.blur();
                }
            }
        );


        reset?.addEventListener(
            'click',
            () => {
                settings = {
                    ...DEFAULTS
                };

                saveSettings();
                applySettings();
                syncControls();
            }
        );
    }


    if (
        document.readyState === 'loading'
    ) {
        document.addEventListener(
            'DOMContentLoaded',
            init
        );
    } else {
        init();
    }

})();
