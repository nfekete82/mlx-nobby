/* Unified on-device memory dashboard. No remote services and no unsafe HTML. */
(() => {
    'use strict';
    if (window.MLXMemoryOverview) return;
    const $ = id => document.getElementById(id);
    const defaults = {
        title: 'Your memory',
        description: 'Everything Nobby has retained, in one place. All data stays on this device.',
        pause: 'Pause memory',
        resume: 'Resume memory',
        paused: 'Paused: no automatic recall or learning. Saved data is preserved.',
        active: 'Active: existing enabled memory layers can be used by Nobby.',
        note: 'Pausing does not delete anything. Old messages can be reindexed using advanced tools after resuming.',
        search: 'Search saved information…',
        all: 'All',
        personal: 'Personal facts',
        legacy: 'Saved memories',
        archive: 'Chat excerpts',
        showMore: 'Show more',
        details: 'Advanced settings and maintenance',
        edit: 'Edit',
        remove: 'Delete',
        exclude: 'Exclude chat from index',
        excludedNotice: 'The entire chat will be excluded from the search index. Original chat messages remain saved.',
        confirmDelete: 'Delete this saved memory and its revisions?',
        confirmLegacyDelete: 'Delete this saved memory?',
        noItems: 'Nothing saved in this category.',
        source: 'Source',
        manual: 'Manually saved',
        unknown: 'Unknown',
        preserved: 'Your original chats are stored separately. Deleting an extracted fact does not delete its original chat.',
        error: 'Could not load memory:',
        count: 'entries',
        layersOff: 'The two optional memory layers are currently disabled. Enable them under Advanced settings to learn from older chats.',
        original: 'Original chat preserved',
        cancel: 'Cancel',
        save: 'Save',
    };
    let translations = {en: defaults, de: {}};
    const t = key => translations[window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en'][key]
        || defaults[key] || key;
    const sources = ['personal', 'legacy', 'archive'];
    const state = {paused:false, layers:{}, counts:{}, query:'', filter:'all',
        pages:{personal:[],legacy:[],archive:[]}, total:{}, busy:false, epoch:0};
    const api = async (path, options = {}) => {
        const response = await fetch(path, options);
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(result.detail || result.error || 'HTTP ' + response.status);
        return result;
    };
    const post = (path, payload) => api(path, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
    });
    function element(tag, label = '', css = '') {
        const node = document.createElement(tag);
        if (label) node.textContent = String(label);
        if (css) node.className = css;
        return node;
    }
    function action(label, handler, css = 'settings-button') {
        const button = element('button', label, css);
        button.type = 'button';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try { await handler(); }
            catch (error) { notice(t('error') + ' ' + error.message); }
            finally { button.disabled = false; }
        });
        return button;
    }
    const notice = value => {
        if ($('memoryOverviewNotice')) $('memoryOverviewNotice').textContent = String(value);
    };
    function syncLabels() {
        if (!$('memoryOverview')) return;
        $('memoryOverviewTitle').textContent = t('title');
        $('memoryOverviewDescription').textContent = t('description');
        $('memoryOverviewNote').textContent = t('note');
        $('memoryOverviewSearch').placeholder = t('search');
        $('memoryOverviewWarning').textContent = t('preserved');
        $('memoryOverviewAdvancedLabel').textContent = t('details');
        const filter = $('memoryOverviewFilter');
        for (const option of filter.options) option.textContent = t(option.value);
        renderStatus();
        renderItems();
    }
    function renderStatus() {
        if (!$('memoryOverview')) return;
        $('memoryOverviewToggle').textContent = state.paused ? t('resume') : t('pause');
        $('memoryOverviewMode').textContent = t(state.paused ? 'paused' : 'active');
        const sum = $('memoryOverviewCounts');
        sum.replaceChildren();
        for (const source of sources) {
            sum.append(element('span', t(source) + ': ' + (state.counts[source] || 0),
                'memory-overview-count'));
        }
        $('memoryOverviewLayers').textContent = (
            !state.layers.personal && !state.layers.archive ? t('layersOff') : ''
        );
    }
    function itemBody(item, source) {
        if (source === 'personal') return item.value;
        if (source === 'legacy') return item.text;
        return item.content;
    }
    function itemTitle(item, source) {
        if (source === 'personal') return item.subject + ' · ' + item.field;
        if (source === 'legacy') return item.category || t('legacy');
        return 'Chat ' + item.chat_id + ' · #' + item.ordinal + ' (' + item.role + ')';
    }
    function provenance(item, source) {
        if (source === 'personal' || source === 'legacy') {
            return item.source_chat_id
                ? (t('source') + ': ' + item.source_chat_id
                  + (item.source_ordinal === null || item.source_ordinal === undefined
                    ? '' : ' · #' + item.source_ordinal))
                : t('manual');
        }
        return t('source') + ': ' + item.chat_id;
    }
    async function modify(item, source, mode) {
        const id = encodeURIComponent(item.id);
        if (mode === 'edit') {
            const value = window.prompt(t('edit'), itemBody(item, source));
            if (value === null || !value.trim()) return;
            if (source === 'personal') {
                await api('/api/mlx/memory/personal/facts/' + id, {
                    method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({value:value.trim()}),
                });
            } else {
                await api('/api/mlx/memory/' + id, {
                    method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({text:value.trim()}),
                });
            }
        } else if (source === 'archive') {
            if (!window.confirm(t('excludedNotice'))) return;
            await post('/api/mlx/memory/archive/exclude/' + encodeURIComponent(item.chat_id), {});
        } else {
            if (!window.confirm(t(source === 'personal' ? 'confirmDelete' : 'confirmLegacyDelete'))) return;
            const path = source === 'personal'
                ? '/api/mlx/memory/personal/facts/' + id : '/api/mlx/memory/' + id;
            await api(path, {method:'DELETE'});
        }
        await refresh();
    }
    function renderItems() {
        if (!$('memoryOverview')) return;
        const container = $('memoryOverviewItems');
        container.replaceChildren();
        const visible = state.filter === 'all' ? sources : [state.filter];
        for (const source of visible) {
            const group = element('div', '', 'memory-overview-group');
            const heading = element('h4', t(source) + ' (' +
                (state.total[source] ?? state.counts[source] ?? 0) + ')');
            group.append(heading);
            const values = state.pages[source] || [];
            if (!values.length) group.append(element('p', t('noItems'), 'memory-overview-empty'));
            for (const item of values) {
                const card = element('div', '', 'memory-overview-item');
                const label = element('strong', itemTitle(item, source));
                const raw = String(itemBody(item, source) || '');
                const detail = element('details');
                const excerpt = element('summary', raw.length > 280
                    ? raw.slice(0, 280) + '…' : raw);
                detail.append(excerpt);
                if (raw.length > 280) detail.append(element('p', raw));
                const meta = element('small', provenance(item, source), 'memory-overview-meta');
                const actions = element('div', '', 'memory-overview-actions');
                if (source !== 'archive') {
                    actions.append(action(t('edit'), () => modify(item, source, 'edit')));
                }
                actions.append(action(t(source === 'archive' ? 'exclude' : 'remove'),
                    () => modify(item, source, 'delete'),
                    'settings-button memory-overview-danger'));
                card.append(label, detail, meta, actions);
                group.append(card);
            }
            if (values.length < (state.total[source] || 0)) {
                group.append(action(t('showMore'), () => loadPage(source, true)));
            }
            container.append(group);
        }
    }
    async function loadPage(source, append = false) {
        const epoch = state.epoch;
        const current = append ? state.pages[source].length : 0;
        const url = '/api/mlx/memory/dashboard/items?source=' + encodeURIComponent(source)
            + '&query=' + encodeURIComponent(state.query)
            + '&offset=' + current + '&limit=20';
        const data = await api(url);
        if (state.epoch !== epoch) return;
        state.pages[source] = append
            ? [...state.pages[source], ...(data.items || [])] : (data.items || []);
        state.total[source] = data.total || 0;
        renderItems();
    }
    async function refresh() {
        if (!$('memoryOverview')) return;
        const epoch = ++state.epoch;
        notice('');
        const selected = state.filter === 'all' ? sources : [state.filter];
        try {
            const info = await api('/api/mlx/memory/dashboard/status');
            if (epoch !== state.epoch) return;
            state.paused = Boolean(info.paused);
            state.counts = info.counts || {};
            state.layers = info.layers || {};
            state.pages = {personal:[],legacy:[],archive:[]};
            state.total = {};
            renderStatus();
            await Promise.all(selected.map(source => loadPage(source)));
        } catch (error) {
            if (epoch === state.epoch) notice(t('error') + ' ' + error.message);
        }
    }
    async function togglePause() {
        const button = $('memoryOverviewToggle');
        const next = !state.paused;
        button.disabled = true;
        try {
            const result = await post('/api/mlx/memory/dashboard/pause', {paused:next});
            state.paused = result.paused;
            renderStatus();
            notice(t(state.paused ? 'paused' : 'active'));
        } catch (error) {
            notice(t('error') + ' ' + error.message);
        } finally { button.disabled = false; }
    }
    function foldExpertPanels(pane, advanced) {
        const candidates = [
            ...Array.from(pane.children).filter(el =>
                el.classList.contains('settings-card') && el.id !== 'memoryOverview'),
        ];
        for (const section of candidates) advanced.append(section);
    }
    function mount() {
        const pane = $('memoryManagerPane');
        if (!pane || $('memoryOverview')) return;
        const style = element('style');
        style.textContent = `
            #memoryOverview{display:grid;gap:13px}
            #memoryOverview .memory-overview-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
            #memoryOverview .memory-overview-top h3{font-size:1.2rem;margin:0}
            #memoryOverview .memory-overview-counts{display:flex;gap:6px;flex-wrap:wrap}
            #memoryOverview .memory-overview-count{padding:5px 10px;border:1px solid rgba(127,127,127,.25);border-radius:20px;font-size:.8rem}
            #memoryOverview .memory-overview-search{display:flex;gap:8px;flex-wrap:wrap}
            #memoryOverviewSearch{flex:1;min-width:160px}
            #memoryOverview .memory-overview-group{display:grid;gap:9px;padding-top:8px}
            #memoryOverview .memory-overview-group h4{font-size:.95rem;margin:8px 0 2px}
            #memoryOverview .memory-overview-item{border:1px solid rgba(127,127,127,.2);border-radius:10px;padding:12px;display:grid;gap:6px}
            #memoryOverview .memory-overview-item details{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}
            #memoryOverview .memory-overview-item summary{cursor:pointer}
            #memoryOverview .memory-overview-meta{color:var(--muted,#94a3b8)}
            #memoryOverview .memory-overview-actions{display:flex;justify-content:flex-end;gap:6px}
            #memoryOverview .memory-overview-danger{opacity:.75}
            #memoryOverview .memory-overview-empty{font-size:.82rem;color:var(--muted,#94a3b8)}
            #memoryOverviewAdvanced{margin-top:14px}
            #memoryOverviewAdvanced>summary{cursor:pointer;padding:12px;border:1px solid rgba(127,127,127,.25);border-radius:9px}
            #memoryOverviewAdvanced>.settings-card{margin-top:10px}
        `;
        document.head.append(style);
        const panel = element('section', '', 'settings-card');
        panel.id = 'memoryOverview';
        const top = element('div', '', 'memory-overview-top');
        const headings = element('div');
        const title = element('h3'); title.id = 'memoryOverviewTitle';
        const description = element('p'); description.id = 'memoryOverviewDescription';
        headings.append(title, description);
        const toggle = action('', togglePause);
        toggle.id = 'memoryOverviewToggle';
        top.append(headings, toggle);
        const mode = element('p'); mode.id = 'memoryOverviewMode';
        const counts = element('div', '', 'memory-overview-counts'); counts.id = 'memoryOverviewCounts';
        const warning = element('small'); warning.id = 'memoryOverviewWarning';
        const layers = element('small'); layers.id = 'memoryOverviewLayers';
        const note = element('small'); note.id = 'memoryOverviewNote';
        const search = element('div', '', 'memory-overview-search');
        const input = element('input'); input.id = 'memoryOverviewSearch'; input.type = 'search';
        const filter = document.createElement('select'); filter.id = 'memoryOverviewFilter';
        for (const source of ['all', ...sources]) {
            const option = document.createElement('option');
            option.value = source; filter.append(option);
        }
        search.append(input, filter);
        const items = element('div'); items.id = 'memoryOverviewItems';
        const status = element('p'); status.id = 'memoryOverviewNotice';
        status.setAttribute('role', 'status');
        panel.append(top, mode, counts, layers, search, items, warning, note, status);
        const advanced = element('details'); advanced.id = 'memoryOverviewAdvanced';
        const advancedLabel = element('summary'); advancedLabel.id = 'memoryOverviewAdvancedLabel';
        advanced.append(advancedLabel);
        const insertion = pane.querySelector('.settings-card');
        pane.insertBefore(panel, insertion || null);
        pane.append(advanced);
        foldExpertPanels(pane, advanced);
        const observer = new MutationObserver(() => foldExpertPanels(pane, advanced));
        observer.observe(pane, {childList:true});
        input.addEventListener('input', () => {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(() => {
                state.query = input.value.trim();
                refresh();
            }, 250);
        });
        filter.addEventListener('change', () => {
            state.filter = filter.value;
            refresh();
        });
        $('memoryManagerTab')?.addEventListener('click', () => { refresh(); });
        document.querySelector('[data-organizer-section="memory"]')
            ?.addEventListener('click', () => refresh());
        syncLabels();
        if (location.pathname === '/settings/memory') refresh();
    }
    fetch('/i18n/memory-overview.json')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data?.de) translations = {en:{...defaults,...(data.en || {})},de:data.de};
            syncLabels();
        })
        .catch(() => {});
    const observer = new MutationObserver(() => {
        if ($('memoryOverview')) observer.disconnect();
        else mount();
    });
    observer.observe(document.documentElement, {childList:true,subtree:true});
    document.addEventListener('mlx-language-changed', syncLabels);
    window.MLXMemoryOverview = {refresh};
    mount();
})();
