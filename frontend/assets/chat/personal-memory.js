/* Opt-in private facts & conflict review. No remote endpoints or unsafe HTML. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const state = { facts: [], conflicts: [], enabled: false, showHistory: false };
    const text = {
        en: {
            title: 'Private personal memory',
            description: 'Locally saved facts about you, relationships, family and projects. Each fact has a source. The full chat archive is managed above. Nothing is uploaded.',
            toggle: 'Automatically learn facts from my local conversations',
            warning: 'Disabled by default. Turning this off erases extracted facts and pending questions, not original chats or separately managed Nobby Memory.',
            add: 'Add a fact', search: 'Search saved facts…',
            history: 'Show older versions', rebuild: 'Rebuild facts from local chats',
            pending: 'Questions requiring clarification',
            empty: 'No saved facts yet.', none: 'No unanswered questions.',
            edit: 'Edit', remove: 'Delete', source: 'Source',
            date: 'Saved', sensitive: 'Private', status: 'Status',
            old: 'Keep previous', latest: 'Use new', custom: 'Correct…',
            value: 'Value', subject: 'Person or topic', field: 'Attribute',
            confirmDelete: 'Delete this derived memory? The original chat remains.',
            error: 'Error', disabled: 'Private memory is disabled.',
            count: 'active facts', conflictCount: 'open questions',
            reload: 'Refresh', ask: 'Confirm the right value',
            required: 'A value is required',
        },
        de: {},
    };
    const t = key => text[window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en'][key]
        || text.en[key] || key;
    const api = async (path, options = {}) => {
        const response = await fetch('/api/mlx/memory/personal/' + path, options);
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(body.detail || body.error || 'HTTP ' + response.status);
        return body;
    };
    const json = (method, obj) => ({
        method, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(obj),
    });
    const status = msg => { if ($('privateMemoryNotice')) $('privateMemoryNotice').textContent = msg; };
    const el = (tag, value = '', cls = '') => {
        const item = document.createElement(tag);
        item.textContent = value;
        if (cls) item.className = cls;
        return item;
    };
    const action = (label, cb) => {
        const button = el('button', label, 'settings-button');
        button.type = 'button';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try { await cb(); } catch (error) { status(t('error') + ': ' + error.message); }
            finally { button.disabled = false; }
        });
        return button;
    };
    const entry = (title, description = '') => {
        const card = el('div', '', 'memory-manager-card');
        card.append(el('strong', title), el('p', description));
        return card;
    };
    function render() {
        if (!$('privateMemoryPanel')) return;
        $('privateMemoryTitle').textContent = t('title');
        $('privateMemoryDescription').textContent = t('description');
        $('privateMemoryToggleLabel').textContent = t('toggle');
        $('privateMemoryWarning').textContent = t('warning');
        $('privateMemoryAdd').textContent = t('add');
        $('privateMemoryRebuild').textContent = t('rebuild');
        $('privateMemoryReload').textContent = t('reload');
        $('privateMemoryHistoryLabel').textContent = t('history');
        $('privateMemoryQuery').placeholder = t('search');
        $('privateMemoryPendingTitle').textContent = t('pending');
        $('privateMemoryEnabled').checked = state.enabled;
        $('privateMemoryAdd').disabled = !state.enabled;
        $('privateMemoryRebuild').disabled = !state.enabled;
        $('privateMemoryHistory').disabled = !state.enabled;
        const search = $('privateMemoryQuery').value.toLocaleLowerCase();
        const facts = $('privateMemoryFacts');
        facts.replaceChildren();
        const shown = state.facts.filter(f => (
            !search || [f.subject, f.field, f.value, f.source_chat_id]
                .join(' ').toLocaleLowerCase().includes(search)
        ));
        for (const fact of shown) {
            const card = entry(fact.subject + ' · ' + fact.field, fact.value);
            const metadata = [
                t('source') + ': ' + (fact.source_chat_id || 'manual'),
                t('date') + ': ' + new Date(fact.updated_at * 1000).toLocaleString(),
                t('status') + ': ' + fact.status,
                fact.sensitive ? t('sensitive') : '',
            ].filter(Boolean);
            card.append(el('small', metadata.join(' · ')));
            const buttons = el('div', '', 'memory-manager-actions');
            if (fact.status === 'active') {
                buttons.append(action(t('edit'), async () => {
                    const subject = prompt(t('subject'), fact.subject);
                    if (subject === null) return;
                    const field = prompt(t('field'), fact.field);
                    if (field === null) return;
                    const value = prompt(t('value'), fact.value);
                    if (value === null) return;
                    await api('facts/' + encodeURIComponent(fact.id),
                        json('PATCH', {subject, field, value}));
                    await refresh();
                }));
            }
            buttons.append(action(t('remove'), async () => {
                if (!confirm(t('confirmDelete'))) return;
                await api('facts/' + encodeURIComponent(fact.id), {method:'DELETE'});
                await refresh();
            }));
            card.append(buttons);
            facts.append(card);
        }
        if (!shown.length) facts.append(el('p', t('empty')));
        const pending = $('privateMemoryConflicts');
        pending.replaceChildren();
        for (const question of state.conflicts) {
            const card = entry(question.subject + ' · ' + question.field,
                t('ask') + ': ' + question.previous_value +
                '  ↔  ' + question.proposed_value);
            card.append(el('small', t('source') + ': ' +
                (question.source_chat_id || 'manual')));
            const buttons = el('div', '', 'memory-manager-actions');
            buttons.append(action(t('old'), async () => {
                await api('conflicts/' + encodeURIComponent(question.id) + '/resolve',
                    json('POST', {decision:'old'}));
                await refresh();
            }));
            buttons.append(action(t('latest'), async () => {
                await api('conflicts/' + encodeURIComponent(question.id) + '/resolve',
                    json('POST', {decision:'new'}));
                await refresh();
            }));
            buttons.append(action(t('custom'), async () => {
                const value = prompt(t('value'), question.proposed_value);
                if (value === null) return;
                await api('conflicts/' + encodeURIComponent(question.id) + '/resolve',
                    json('POST', {decision:'custom', value}));
                await refresh();
            }));
            card.append(buttons);
            pending.append(card);
        }
        if (!state.conflicts.length) pending.append(el('p', t('none')));
        if (!state.enabled) status(t('disabled'));
        else status(state.facts.filter(f=>f.status==='active').length + ' ' +
            t('count') + ' · ' + state.conflicts.length + ' ' + t('conflictCount'));
    }
    async function refresh() {
        const current = await api('status');
        state.enabled = current.enabled;
        if (state.enabled) {
            const [facts, conflicts] = await Promise.all([
                api('facts?history=' + state.showHistory + '&limit=250'),
                api('conflicts'),
            ]);
            state.facts = facts.facts || [];
            state.conflicts = conflicts.conflicts || [];
        } else {
            state.facts = [];
            state.conflicts = [];
        }
        render();
    }
    async function toggle() {
        const enabled = $('privateMemoryEnabled').checked;
        $('privateMemoryEnabled').disabled = true;
        try {
            await api('config', json('POST', {enabled}));
            await refresh();
        } catch (error) {
            status(t('error') + ': ' + error.message);
            $('privateMemoryEnabled').checked = !enabled;
        } finally { $('privateMemoryEnabled').disabled = false; }
    }
    function mount() {
        if ($('privateMemoryPanel')) return;
        const host = $('memoryManagerPane');
        if (!host) return;
        const panel = el('section', '', 'settings-card');
        panel.id = 'privateMemoryPanel';
        const title = el('h4'); title.id = 'privateMemoryTitle';
        const description = el('p'); description.id = 'privateMemoryDescription';
        const toggle = el('label', '', 'memory-manager-switch');
        const input = document.createElement('input');
        input.id = 'privateMemoryEnabled'; input.type = 'checkbox';
        const toggleText = el('span'); toggleText.id = 'privateMemoryToggleLabel';
        toggle.append(input, toggleText);
        const warning = el('p'); warning.id = 'privateMemoryWarning';
        warning.style.opacity = '.75';
        const toolbar = el('div', '', 'memory-manager-toolbar');
        const query = document.createElement('input');
        query.id = 'privateMemoryQuery'; query.type = 'search';
        const add = action('', async () => {
            const subject = prompt(t('subject'), 'ich');
            if (subject === null) return;
            const field = prompt(t('field'), '');
            if (field === null) return;
            const value = prompt(t('value'), '');
            if (value === null) return;
            await api('facts', json('POST', {subject, field, value, sensitive:true}));
            await refresh();
        }); add.id = 'privateMemoryAdd';
        const reload = action('', refresh); reload.id = 'privateMemoryReload';
        toolbar.append(query, add, reload);
        const history = el('label', '', 'memory-manager-switch');
        const historyCheck = document.createElement('input');
        historyCheck.id = 'privateMemoryHistory'; historyCheck.type = 'checkbox';
        const historyLabel = el('span'); historyLabel.id = 'privateMemoryHistoryLabel';
        history.append(historyCheck, historyLabel);
        const rebuild = action('', async () => {
            await api('rebuild', json('POST', {}));
            await refresh();
        }); rebuild.id = 'privateMemoryRebuild';
        const notice = el('p'); notice.id = 'privateMemoryNotice';
        notice.setAttribute('role', 'status');
        const pendingTitle = el('h4'); pendingTitle.id = 'privateMemoryPendingTitle';
        const conflicts = el('div'); conflicts.id = 'privateMemoryConflicts';
        const facts = el('div'); facts.id = 'privateMemoryFacts';
        panel.append(title, description, toggle, warning,
            toolbar, history, rebuild, notice, pendingTitle, conflicts, facts);
        host.append(panel);
        input.addEventListener('change', toggle);
        query.addEventListener('input', render);
        historyCheck.addEventListener('change', () => {
            state.showHistory = historyCheck.checked;
            refresh().catch(e => status(t('error') + ': ' + e.message));
        });
        $('memoryManagerTab')?.addEventListener('click', () => {
            refresh().catch(e => status(t('error') + ': ' + e.message));
        });
        if (location.pathname === '/settings/memory')
            refresh().catch(e => status(t('error') + ': ' + e.message));
        render();
    }
    fetch('/i18n/personal-memory.json')
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data?.de) text.de = data.de; if ($('privateMemoryPanel')) render(); })
        .catch(() => {});
    const observer = new MutationObserver(() => {
        if ($('privateMemoryPanel')) observer.disconnect();
        else mount();
    });
    observer.observe(document.documentElement, {childList:true, subtree:true});
    document.addEventListener('mlx-language-changed', render);
    mount();
})();
