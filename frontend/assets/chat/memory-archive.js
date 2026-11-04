/* Local chat-archive controls, mounted into the existing Memory settings pane. */
(() => {
    'use strict';
    let mounted = false;
    const $ = id => document.getElementById(id);
    const lang = () => window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    const words = {
        en: {
            title: 'On-device chat memory 2.0',
            explanation: 'Searchable chat index stored only on this Mac. Disabled by default. No chat content is sent to GitHub or external services.',
            toggle: 'Enable automatic local indexing',
            rebuild: 'Rebuild full index',
            search: 'Search previous chats …',
            go: 'Search',
            disabled: 'Disabled – no additional chat index is created.',
            count: 'indexed messages',
            saved: 'Settings saved.',
            error: 'Error',
            remove: 'Exclude this chat from memory',
            empty: 'No matching prior messages.',
            warning: 'Turning off removes the derived search index, not the original chats.',
        },
        de: {},
    };
    const t = key => (words[lang()][key] || words.en[key] || key);
    fetch('/i18n/memory-archive.json')
        .then(response => response.ok ? response.json() : null)
        .then(data => {
            if (data?.de) words.de = data.de;
            labels();
        })
        .catch(() => {});

    const html = `
        <section class="settings-card" id="localArchivePanel">
            <h4 id="localArchiveTitle"></h4>
            <p id="localArchiveDescription"></p>
            <label class="memory-manager-switch">
                <input type="checkbox" id="localArchiveEnabled">
                <span id="localArchiveToggleLabel"></span>
            </label>
            <p id="localArchiveWarning" style="font-size:.82rem;opacity:.7"></p>
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0">
                <button class="settings-button" id="localArchiveRebuild" type="button"></button>
                <span id="localArchiveStatus" role="status"></span>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <input id="localArchiveQuery" type="search" style="flex:1;min-width:180px">
                <button class="settings-button" id="localArchiveSearch" type="button"></button>
            </div>
            <div id="localArchiveResults" style="display:grid;gap:10px;margin-top:12px"></div>
        </section>`;
    async function api(path, options) {
        const response = await fetch(path, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'HTTP ' + response.status);
        return data;
    }
    const post = (path, payload) => api(path, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
    });
    const status = (message) => { $('localArchiveStatus').textContent = message; };
    async function refresh() {
        const data = await api('/api/mlx/memory/archive/status');
        $('localArchiveEnabled').checked = data.enabled;
        $('localArchiveRebuild').disabled = !data.enabled;
        status(data.enabled ? (data.indexed_messages + ' ' + t('count')) : t('disabled'));
    }
    async function toggle() {
        const checkbox = $('localArchiveEnabled');
        const enabled = checkbox.checked;
        checkbox.disabled = true;
        try {
            const data = await post('/api/mlx/memory/archive/config', {enabled});
            status(data.enabled ? (data.indexed_messages + ' ' + t('count')) : t('disabled'));
            $('localArchiveRebuild').disabled = !data.enabled;
            $('localArchiveResults').replaceChildren();
        } catch (error) {
            checkbox.checked = !enabled;
            status(t('error') + ': ' + error.message);
        } finally { checkbox.disabled = false; }
    }
    async function rebuild() {
        const button = $('localArchiveRebuild');
        button.disabled = true;
        try {
            const data = await post('/api/mlx/memory/archive/rebuild', {});
            status((data.indexed_messages + ' ' + t('count')));
        } catch (error) {
            status(t('error') + ': ' + error.message);
        } finally { button.disabled = false; }
    }
    async function search() {
        const target = $('localArchiveResults');
        const query = $('localArchiveQuery').value.trim();
        target.replaceChildren();
        if (!query) return;
        try {
            const data = await api('/api/mlx/memory/archive/search?query=' +
                encodeURIComponent(query) + '&limit=8');
            for (const item of data.results || []) {
                const card = document.createElement('div');
                card.className = 'memory-manager-card';
                const heading = document.createElement('strong');
                heading.textContent = item.chat_id + ' · #' + item.message_index +
                    ' · ' + item.role;
                const excerpt = document.createElement('p');
                excerpt.textContent = item.excerpt;
                const hide = document.createElement('button');
                hide.className = 'settings-button';
                hide.type = 'button';
                hide.textContent = t('remove');
                hide.addEventListener('click', async () => {
                    hide.disabled = true;
                    try {
                        await post('/api/mlx/memory/archive/exclude/' +
                            encodeURIComponent(item.chat_id), {});
                        await search();
                    } catch (error) {
                        status(t('error') + ': ' + error.message);
                        hide.disabled = false;
                    }
                });
                card.append(heading, excerpt, hide);
                target.append(card);
            }
            if (!target.childElementCount) target.textContent = t('empty');
        } catch (error) { status(t('error') + ': ' + error.message); }
    }
    function labels() {
        if (!mounted) return;
        $('localArchiveTitle').textContent = t('title');
        $('localArchiveDescription').textContent = t('explanation');
        $('localArchiveToggleLabel').textContent = t('toggle');
        $('localArchiveWarning').textContent = t('warning');
        $('localArchiveRebuild').textContent = t('rebuild');
        $('localArchiveQuery').placeholder = t('search');
        $('localArchiveSearch').textContent = t('go');
    }
    function mount() {
        if (mounted) return;
        const pane = $('memoryManagerPane');
        if (!pane) return;
        pane.insertAdjacentHTML('beforeend', html);
        mounted = true;
        labels();
        $('localArchiveEnabled').addEventListener('change', toggle);
        $('localArchiveRebuild').addEventListener('click', rebuild);
        $('localArchiveSearch').addEventListener('click', search);
        $('localArchiveQuery').addEventListener('keydown', event => {
            if (event.key === 'Enter') search();
        });
        // A normal chat load must not hit archive API endpoints. The archive
        // UI initializes lazily when Memory settings are actually opened.
        const activateRefresh = () => {
            refresh().catch(error => status(t('error') + ': ' + error.message));
        };
        $('memoryManagerTab')?.addEventListener('click', activateRefresh);
        if (location.pathname === '/settings/memory') activateRefresh();
    }
    const observer = new MutationObserver(() => { if (mounted) observer.disconnect(); else mount(); });
    observer.observe(document.documentElement, {childList:true, subtree:true});
    document.addEventListener('mlx-language-changed', labels);
    mount();
})();
