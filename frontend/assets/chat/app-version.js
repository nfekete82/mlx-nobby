'use strict';

(() => {
    let versionInfo = null;
    let observer = null;

    function label(info) {
        const version = String(info?.version || '').trim() || '0.0.0';
        const commit = String(info?.commit || '').trim();
        return 'MLX Nobby v' + version + (commit ? ' · Build ' + commit : '');
    }

    function mount() {
        if (!versionInfo) return false;
        const root = document.getElementById('systemHealthV1');
        if (!root) return false;

        let node = root.querySelector('[data-mlx-app-version]');
        if (!node) {
            node = document.createElement('p');
            node.className = 'system-health-muted';
            node.dataset.mlxAppVersion = '1';

            const heading = root.querySelector('.system-health-heading > div');
            if (heading) {
                heading.appendChild(node);
            } else {
                root.prepend(node);
            }
        }

        node.textContent = label(versionInfo);
        return true;
    }

    async function load() {
        try {
            const response = await fetch('/api/version', { cache: 'no-store' });
            if (!response.ok) return;
            const data = await response.json();
            if (!data || typeof data !== 'object') return;
            versionInfo = data;
            window.MLXAppVersion = data;
            if (mount()) observer?.disconnect?.();
        } catch (_error) {}
    }

    function watch() {
        if (mount() || typeof MutationObserver === 'undefined') return;
        observer = new MutationObserver(() => {
            if (mount()) observer?.disconnect?.();
        });
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });
    }

    load().finally(watch);
})();
