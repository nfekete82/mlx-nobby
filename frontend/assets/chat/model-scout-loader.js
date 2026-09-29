(function () {
    'use strict';

    if (window.__mlxNobbyModelScoutLoader) return;
    window.__mlxNobbyModelScoutLoader = true;

    let observer = null;
    let loading = false;

    function stopWatching() {
        if (observer) {
            observer.disconnect();
            observer = null;
        }
    }

    function loadScout() {
        if (!document.getElementById('modelConsoleContent')) return false;
        if (document.querySelector('script[data-model-scout-runtime]')) {
            stopWatching();
            return true;
        }
        if (loading) return true;

        loading = true;
        stopWatching();

        const script = document.createElement('script');
        script.src = '/assets/chat/model-scout.js?v=20260929-model-scout-v2-tuning';
        script.async = true;
        script.dataset.modelScoutRuntime = 'true';
        script.addEventListener('error', () => {
            loading = false;
            startWatching();
        }, { once: true });
        document.head.appendChild(script);
        return true;
    }

    function startWatching() {
        if (loadScout() || observer) return;

        const root = document.body || document.documentElement;
        if (!root) return;

        observer = new MutationObserver(() => {
            if (document.getElementById('modelConsoleContent')) loadScout();
        });
        observer.observe(root, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startWatching, { once: true });
    } else {
        startWatching();
    }
})();
