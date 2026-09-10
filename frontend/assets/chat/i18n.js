(function () {
    'use strict';

    const STORAGE_KEY = 'mlx-nobby-language';
    const DEFAULT_LANGUAGE = 'en';
    const SUPPORTED_LANGUAGES = new Set(['de', 'en']);

    let language = DEFAULT_LANGUAGE;
    let translations = {};

    function getNestedValue(object, path) {
        return String(path || '')
            .split('.')
            .reduce((value, key) => {
                if (
                    value &&
                    typeof value === 'object' &&
                    Object.prototype.hasOwnProperty.call(value, key)
                ) {
                    return value[key];
                }

                return undefined;
            }, object);
    }

    function detectLanguage() {
        const saved = localStorage.getItem(STORAGE_KEY);

        if (SUPPORTED_LANGUAGES.has(saved)) {
            return saved;
        }

        return DEFAULT_LANGUAGE;
    }

    async function loadTranslations(nextLanguage) {
        const safeLanguage = SUPPORTED_LANGUAGES.has(nextLanguage)
            ? nextLanguage
            : DEFAULT_LANGUAGE;

        const response = await fetch(
            `/i18n/${safeLanguage}.json`,
            { cache: 'no-cache' }
        );

        if (!response.ok) {
            throw new Error(
                `Could not load language file: ${safeLanguage}`
            );
        }

        translations = await response.json();
        language = safeLanguage;

        document.documentElement.lang = language;

        return translations;
    }

    function t(key, fallback = '') {
        const directValue = translations &&
            Object.prototype.hasOwnProperty.call(translations, key)
            ? translations[key]
            : undefined;
        const value = typeof directValue === 'string'
            ? directValue
            : getNestedValue(translations, key);

        return typeof value === 'string'
            ? value
            : fallback || key;
    }

    function applyTranslations(root = document) {
        root.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.dataset.i18n;
            const translated = t(key);

            if (translated !== key) {
                element.textContent = translated;
            }
        });

        root.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
            const key = element.dataset.i18nPlaceholder;
            const translated = t(key);

            if (translated !== key) {
                element.setAttribute('placeholder', translated);
            }
        });

        root.querySelectorAll('[data-i18n-title]').forEach(element => {
            const key = element.dataset.i18nTitle;
            const translated = t(key);

            if (translated !== key) {
                element.setAttribute('title', translated);
            }
        });

        root.querySelectorAll('[data-i18n-aria-label]').forEach(element => {
            const key = element.dataset.i18nAriaLabel;
            const translated = t(key);

            if (translated !== key) {
                element.setAttribute('aria-label', translated);
            }
        });
    }

    async function setLanguage(nextLanguage) {
        if (!SUPPORTED_LANGUAGES.has(nextLanguage)) {
            return;
        }

        localStorage.setItem(STORAGE_KEY, nextLanguage);

        await loadTranslations(nextLanguage);
        applyTranslations();

        document.dispatchEvent(
            new CustomEvent('mlx-language-changed', {
                detail: {
                    language
                }
            })
        );
    }

    async function init() {
        const initialLanguage = detectLanguage();

        try {
            await loadTranslations(initialLanguage);
        } catch (error) {
            console.error('[i18n]', error);

            if (initialLanguage !== DEFAULT_LANGUAGE) {
                await loadTranslations(DEFAULT_LANGUAGE);
            }
        }

        applyTranslations();

        document.dispatchEvent(
            new CustomEvent('mlx-i18n-ready', {
                detail: {
                    language
                }
            })
        );
    }

    window.MLXI18n = {
        init,
        t,
        applyTranslations,
        setLanguage,
        getLanguage() {
            return language;
        },
        getLocale() {
            return language === 'de' ? 'de-DE' : 'en-US';
        },
        supportedLanguages: ['de', 'en']
    };
})();


// Keep static and dynamically rendered UI translated.
function applyCurrentTranslations(root = document) {
    window.MLXI18n?.applyTranslations?.(root);
}

function startI18nDomObserver() {
    if (window.__mlxI18nObserverStarted) {
        return;
    }

    if (
        typeof MutationObserver === 'undefined' ||
        typeof Element === 'undefined'
    ) {
        return;
    }

    window.__mlxI18nObserverStarted = true;

    const observer = new MutationObserver(mutations => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (!(node instanceof Element)) {
                    continue;
                }

                if (
                    node.matches?.(
                        '[data-i18n], ' +
                        '[data-i18n-placeholder], ' +
                        '[data-i18n-title], ' +
                        '[data-i18n-aria-label]'
                    )
                ) {
                    applyCurrentTranslations(node.parentElement || node);
                    continue;
                }

                if (
                    node.querySelector?.(
                        '[data-i18n], ' +
                        '[data-i18n-placeholder], ' +
                        '[data-i18n-title], ' +
                        '[data-i18n-aria-label]'
                    )
                ) {
                    applyCurrentTranslations(node);
                }
            }
        }
    });

    observer.observe(document.documentElement, {
        childList: true,
        subtree: true
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        applyCurrentTranslations();
        startI18nDomObserver();
    }, { once: true });
} else {
    applyCurrentTranslations();
    startI18nDomObserver();
}

// Language selector integration.
document.addEventListener('mlx-i18n-ready', event => {
    applyCurrentTranslations();

    const selector = document.getElementById('interfaceLanguage');

    if (!selector) {
        return;
    }

    selector.value = event.detail.language;

    selector.addEventListener('change', async () => {
        await window.MLXI18n.setLanguage(selector.value);
    });
});

document.addEventListener('mlx-language-changed', event => {
    applyCurrentTranslations();

    const selector = document.getElementById('interfaceLanguage');

    if (selector) {
        selector.value = event.detail.language;
    }
});
