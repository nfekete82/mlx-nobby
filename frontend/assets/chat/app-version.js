'use strict';

(() => {
    let versionInfo = null;
    let observer = null;
    let chatObserver = null;

    function label(info) {
        const version = String(info?.version || '').trim() || '0.0.0';
        const commit = String(info?.commit || '').trim();
        return 'MLX Nobby v' + version + (commit ? ' · Build ' + commit : '');
    }

    function chatHasUserMessage(session) {
        return Boolean(
            session &&
            Array.isArray(session.messages) &&
            session.messages.some(message => message?.role === 'user')
        );
    }

    function fixCollapsedStartScreenPosition() {
        const style = document.getElementById('mlxChatHistoryPolish');
        if (!style) return;

        /*
         * Keep the empty-state content visually anchored when the 280 px
         * sidebar collapses to the 56 px rail. Use the individual
         * `translate` property so we do not overwrite any existing
         * transform that controls the vertical start-screen layout.
         */
        style.textContent = [
            '@media (min-width:901px){',
            '.app.sidebar-collapsed .empty{',
            'translate:112px 0;',
            '}',
            '}'
        ].join('');
    }

    function syncDraftChatVisibility() {
        const list = document.getElementById('chatList');
        const sessions = window.MLXChatSessions;
        if (!list || !sessions?.currentSession) return false;

        const activeEntry = list.querySelector('.chat-entry.active');
        const activeWrap = activeEntry?.closest('.chat-entry-wrap');
        const current = sessions.currentSession();

        if (activeWrap) {
            /*
             * A new chat is only a draft until the first user message.
             * It must not appear in the history before that point.
             */
            activeWrap.hidden = !chatHasUserMessage(current);
        }

        return true;
    }

    function mountChatUiFixes() {
        fixCollapsedStartScreenPosition();

        const list = document.getElementById('chatList');
        if (!list) return;

        syncDraftChatVisibility();

        if (chatObserver || typeof MutationObserver === 'undefined') return;

        chatObserver = new MutationObserver(() => {
            syncDraftChatVisibility();
            fixCollapsedStartScreenPosition();
        });

        chatObserver.observe(list, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    function mount() {
        mountChatUiFixes();

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
            mount();
        } catch (_error) {
            mountChatUiFixes();
        }
    }

    function watch() {
        mountChatUiFixes();
        if (mount() || typeof MutationObserver === 'undefined') return;
        observer = new MutationObserver(() => {
            mountChatUiFixes();
            if (mount()) observer?.disconnect?.();
        });
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });
    }

    load().finally(watch);
})();
