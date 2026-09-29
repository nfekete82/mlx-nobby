'use strict';

(() => {
    let attempts = 0;
    const MAX_ATTEMPTS = 80;

    function currentLanguage() {
        try {
            const saved = String(
                window.localStorage?.getItem?.('mlx-nobby-language') || ''
            ).toLowerCase();
            if (saved === 'de' || saved === 'en') return saved;
        } catch (_error) {}

        const runtimeLanguage = String(
            window.MLXI18n?.getLanguage?.() ||
            window.MLXI18n?.getLocale?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase();

        return runtimeLanguage.startsWith('de') ? 'de' : 'en';
    }

    function syncGalleryLanguage() {
        if (!window.MLXImageVariantGallery) {
            attempts += 1;
            if (attempts <= MAX_ATTEMPTS) {
                setTimeout(syncGalleryLanguage, 100);
            }
            return;
        }

        document.dispatchEvent(new CustomEvent('mlx-language-changed', {
            detail: { language: currentLanguage() }
        }));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', syncGalleryLanguage, {
            once: true
        });
    } else {
        syncGalleryLanguage();
    }

    document.addEventListener('mlx-i18n-ready', syncGalleryLanguage, {
        once: true
    });
})();
