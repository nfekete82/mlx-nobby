(() => {
    'use strict';

    const assets = new Map();
    let scanQueued = false;

    function key(ref) {
        return `${ref.kind}:${ref.id}`;
    }

    function parseAssetUrl(value) {
        if (!value) return null;
        let url;
        try {
            url = new URL(String(value), window.location.href);
        } catch (_) {
            return null;
        }
        const path = url.pathname;
        const patterns = [
            [/^\/api\/(?:mlx\/)?images\/(\d{10}-[0-9a-f]{12})$/, 'image'],
            [/^\/api\/(?:mlx\/)?videos\/([0-9a-f]{24})$/, 'video'],
            [/^\/api\/talking-photo\/videos\/([0-9a-f]{24})$/, 'talking_photo'],
        ];
        for (const [pattern, kind] of patterns) {
            const match = path.match(pattern);
            if (match) return {kind, id: match[1]};
        }
        return null;
    }

    function remember(ref) {
        if (!ref) return;
        const id = key(ref);
        if (!assets.has(id)) {
            assets.set(id, {...ref, saved: false});
        }
    }

    function scan() {
        scanQueued = false;
        document.querySelectorAll('a[href], img[src], video[src], source[src]').forEach(element => {
            remember(parseAssetUrl(element.href || element.src));
        });

        document.querySelectorAll('a[href*="/api/mlx/images/"], a[href*="/api/mlx/videos/"]').forEach(link => {
            if (!link.title) {
                link.title = document.documentElement.lang?.toLowerCase().startsWith('de')
                    ? 'Speichern – danach bleibt die Datei erhalten'
                    : 'Save – the file will be kept afterward';
            }
        });

        const modal = document.getElementById('talkingPhotoModal');
        if (modal && !modal.querySelector('[data-media-lifecycle-hint]')) {
            const actions = modal.querySelector('.mlx-talking-photo-actions');
            if (actions) {
                const hint = document.createElement('div');
                hint.dataset.mediaLifecycleHint = '1';
                hint.className = 'mlx-talking-photo-hint';
                hint.textContent = document.documentElement.lang?.toLowerCase().startsWith('de')
                    ? 'Nicht gespeicherte Ergebnisse werden beim Schließen automatisch gelöscht.'
                    : 'Unsaved results are deleted automatically when you close this dialog.';
                actions.insertAdjacentElement('afterend', hint);
            }
        }
    }

    function queueScan() {
        if (scanQueued) return;
        scanQueued = true;
        queueMicrotask(scan);
    }

    function post(path, payload, {beacon = false} = {}) {
        const body = JSON.stringify(payload);
        if (beacon && navigator.sendBeacon) {
            try {
                return navigator.sendBeacon(
                    path,
                    new Blob([body], {type: 'application/json'})
                );
            } catch (_) {
                // Fall through to keepalive fetch.
            }
        }
        fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', Accept: 'application/json'},
            body,
            cache: 'no-store',
            keepalive: beacon,
        }).catch(() => {});
        return true;
    }

    function persist(ref) {
        if (!ref) return;
        remember(ref);
        const stored = assets.get(key(ref));
        if (stored) stored.saved = true;
        post('/api/mlx/media-lifecycle/persist', {assets: [ref]});
    }

    function discard(ref, {beacon = false} = {}) {
        if (!ref) return;
        const stored = assets.get(key(ref));
        if (stored?.saved) return;
        post('/api/mlx/media-lifecycle/discard', {assets: [ref]}, {beacon});
        assets.delete(key(ref));
    }

    function currentTalkingPhotoRef() {
        const result = document.getElementById('talkingPhotoResult');
        return parseAssetUrl(result?.getAttribute('src') || result?.src || '');
    }

    function discardTalkingPhoto({beacon = false} = {}) {
        const cancel = document.getElementById('talkingPhotoCancel');
        const activeJobId = String(cancel?.dataset?.jobId || '');
        if (/^[0-9a-f]{24}$/.test(activeJobId) && !cancel.hidden) {
            post(`/api/talking-photo/jobs/${encodeURIComponent(activeJobId)}/cancel`, {}, {beacon});
            return;
        }
        discard(currentTalkingPhotoRef(), {beacon});
    }

    document.addEventListener('click', event => {
        const link = event.target?.closest?.('a[href]');
        if (link) {
            const ref = parseAssetUrl(link.href);
            if (ref && (
                link.hasAttribute('download') ||
                new URL(link.href, window.location.href).searchParams.has('download')
            )) {
                persist(ref);
                if (ref.kind === 'talking_photo') {
                    const url = new URL(link.href, window.location.href);
                    url.searchParams.set('download', '1');
                    link.href = url.pathname + url.search;
                }
            }
        }

        const close = event.target?.closest?.('.mlx-talking-photo-close, .mlx-talking-photo-backdrop');
        if (close) {
            discardTalkingPhoto();
        }

        const create = event.target?.closest?.('#talkingPhotoCreate');
        if (create) {
            discard(currentTalkingPhotoRef());
        }
    }, true);

    window.addEventListener('pagehide', () => {
        scan();
        const temporary = [...assets.values()]
            .filter(item => !item.saved)
            .map(({kind, id}) => ({kind, id}));
        if (temporary.length) {
            post('/api/mlx/media-lifecycle/discard', {assets: temporary}, {beacon: true});
        }
        discardTalkingPhoto({beacon: true});
    });

    const observer = new MutationObserver(queueScan);
    observer.observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['src', 'href'],
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scan, {once: true});
    } else {
        scan();
    }

    window.MLXMediaLifecycle = Object.freeze({
        discard,
        parseAssetUrl,
        persist,
        scan,
    });
})();
