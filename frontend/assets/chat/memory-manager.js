(() => {
    'use strict';

    const requestedAtBoot = location.pathname === '/settings/memory';
    const state = {
        memories: [],
        query: '',
        filter: 'all',
        loading: false,
    };

    const COPY = {
        de: {
            tab: 'Memory',
            title: 'Nobby Memory',
            description: 'Dauerhafte Erinnerungen verwalten, die Nobby bei passenden Anfragen automatisch berücksichtigt.',
            add: '+ Erinnerung',
            search: 'Erinnerungen durchsuchen …',
            all: 'Alle',
            active: 'Aktiv',
            pinned: 'Angeheftet',
            disabled: 'Deaktiviert',
            empty: 'Noch keine Erinnerungen vorhanden.',
            noResults: 'Keine passenden Erinnerungen gefunden.',
            loading: 'Memory wird geladen …',
            loadFailed: 'Memory konnte nicht geladen werden:',
            newTitle: 'Neue Erinnerung',
            memoryText: 'Erinnerung',
            memoryPlaceholder: 'z. B. Für Coding bevorzuge ich Qwen3.8-27B.',
            category: 'Kategorie',
            importance: 'Wichtigkeit',
            confidence: 'Konfidenz',
            pinnedLabel: 'Anheften',
            enabled: 'Aktiv',
            cancel: 'Abbrechen',
            create: 'Speichern',
            save: 'Speichern',
            saved: 'Gespeichert',
            pin: 'Anheften',
            unpin: 'Lösen',
            remove: 'Löschen',
            deleteTitle: 'Erinnerung löschen?',
            deleteMessage: 'Diese Erinnerung wird dauerhaft aus Nobby Memory entfernt.',
            deleted: 'Erinnerung gelöscht.',
            created: 'Erinnerung gespeichert.',
            updated: 'Aktualisiert',
            used: 'Verwendet',
            never: 'noch nie',
            memories: 'Erinnerungen',
            activeCount: 'aktiv',
            pinnedCount: 'angeheftet',
            disabledCount: 'deaktiviert',
            error: 'Fehler:',
        },
        en: {
            tab: 'Memory',
            title: 'Nobby Memory',
            description: 'Manage long-term memories that Nobby automatically uses when they are relevant.',
            add: '+ Memory',
            search: 'Search memories …',
            all: 'All',
            active: 'Active',
            pinned: 'Pinned',
            disabled: 'Disabled',
            empty: 'No memories yet.',
            noResults: 'No matching memories found.',
            loading: 'Loading memory …',
            loadFailed: 'Could not load memory:',
            newTitle: 'New memory',
            memoryText: 'Memory',
            memoryPlaceholder: 'e.g. For coding I prefer Qwen3.8-27B.',
            category: 'Category',
            importance: 'Importance',
            confidence: 'Confidence',
            pinnedLabel: 'Pin',
            enabled: 'Active',
            cancel: 'Cancel',
            create: 'Save',
            save: 'Save',
            saved: 'Saved',
            pin: 'Pin',
            unpin: 'Unpin',
            remove: 'Delete',
            deleteTitle: 'Delete memory?',
            deleteMessage: 'This memory will be permanently removed from Nobby Memory.',
            deleted: 'Memory deleted.',
            created: 'Memory saved.',
            updated: 'Updated',
            used: 'Used',
            never: 'never',
            memories: 'memories',
            activeCount: 'active',
            pinnedCount: 'pinned',
            disabledCount: 'disabled',
            error: 'Error:',
        },
    };

    const CATEGORY_LABELS = {
        preference: { de: 'Präferenz', en: 'Preference' },
        communication: { de: 'Kommunikation', en: 'Communication' },
        coding: { de: 'Coding', en: 'Coding' },
        ai_models: { de: 'KI & Modelle', en: 'AI & Models' },
        work: { de: 'Arbeit', en: 'Work' },
        other: { de: 'Sonstiges', en: 'Other' },
    };

    const language = () => window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    const t = key => COPY[language()][key] || COPY.en[key] || key;
    const categoryLabel = value => (
        CATEGORY_LABELS[value]?.[language()] || value || CATEGORY_LABELS.other[language()]
    );
    const $ = id => document.getElementById(id);

    let tab = null;
    let pane = null;

    async function request(path, options = {}) {
        const response = await fetch(path, options);
        let data = {};
        try {
            data = await response.json();
        } catch (_) {}
        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }
        return data;
    }

    function injectStyles() {
        if ($('memoryManagerStyles')) return;
        const style = document.createElement('style');
        style.id = 'memoryManagerStyles';
        style.textContent = `
            .memory-manager-toolbar{display:grid;grid-template-columns:minmax(180px,1fr) auto auto;gap:10px;align-items:center;margin:14px 0}
            .memory-manager-toolbar input,.memory-manager-toolbar select,.memory-manager-card textarea,.memory-manager-card select,.memory-manager-create textarea,.memory-manager-create select{width:100%;box-sizing:border-box}
            .memory-manager-summary{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 16px;color:var(--muted,#7d8794);font-size:.82rem}
            .memory-manager-summary span{padding:4px 8px;border:1px solid rgba(127,127,127,.2);border-radius:999px}
            .memory-manager-create{display:grid;gap:12px;margin-bottom:14px}
            .memory-manager-create-grid,.memory-manager-fields{display:grid;grid-template-columns:minmax(140px,.7fr) minmax(180px,1fr);gap:12px}
            .memory-manager-create-actions,.memory-manager-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
            .memory-manager-list{display:grid;gap:10px}
            .memory-manager-card{border:1px solid rgba(127,127,127,.22);border-radius:12px;padding:12px;background:rgba(127,127,127,.035);display:grid;gap:10px}
            .memory-manager-card.is-disabled{opacity:.62}
            .memory-manager-card-head{display:flex;gap:8px;align-items:center;justify-content:space-between}
            .memory-manager-badges{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
            .memory-manager-badge{font-size:.72rem;padding:3px 7px;border-radius:999px;background:rgba(127,127,127,.13)}
            .memory-manager-badge.pin{font-weight:700}
            .memory-manager-card textarea{min-height:72px;resize:vertical}
            .memory-manager-field{display:grid;gap:5px;font-size:.78rem;color:var(--muted,#7d8794)}
            .memory-manager-field output{font-variant-numeric:tabular-nums}
            .memory-manager-meta{font-size:.74rem;color:var(--muted,#7d8794);display:flex;gap:12px;flex-wrap:wrap}
            .memory-manager-status{min-height:1.3em;margin-top:8px;color:var(--muted,#7d8794);font-size:.82rem}
            .memory-manager-empty{padding:24px 8px;text-align:center;color:var(--muted,#7d8794)}
            .memory-manager-switch{display:flex;gap:6px;align-items:center;font-size:.78rem;white-space:nowrap}
            @media(max-width:760px){.memory-manager-toolbar{grid-template-columns:1fr}.memory-manager-create-grid,.memory-manager-fields{grid-template-columns:1fr}}
        `;
        document.head.appendChild(style);
    }

    function buildUi() {
        if ($('memoryManagerPane')) {
            tab = $('memoryManagerTab');
            pane = $('memoryManagerPane');
            return;
        }

        const settings = $('settings');
        const tabs = settings?.querySelector('.settings-tabs');
        const profileTab = settings?.querySelector('[data-settings-tab="profile"]');
        const profilePane = settings?.querySelector('[data-settings-pane="profile"]');
        if (!settings || !tabs || !profilePane) return;

        injectStyles();

        tab = document.createElement('button');
        tab.id = 'memoryManagerTab';
        tab.type = 'button';
        tab.setAttribute('aria-selected', 'false');
        tab.textContent = t('tab');
        profileTab?.after(tab);
        if (!tab.isConnected) tabs.appendChild(tab);

        pane = document.createElement('div');
        pane.id = 'memoryManagerPane';
        pane.className = 'settings-pane';
        pane.dataset.settingsPane = 'memory';
        pane.hidden = true;
        pane.innerHTML = `
            <div class="settings-page-intro">
                <h4 id="memoryManagerTitle"></h4>
                <p id="memoryManagerDescription"></p>
            </div>
            <section class="settings-card">
                <div class="memory-manager-toolbar">
                    <input id="memoryManagerSearch" type="search" autocomplete="off">
                    <select id="memoryManagerFilter">
                        <option value="all"></option>
                        <option value="active"></option>
                        <option value="pinned"></option>
                        <option value="disabled"></option>
                    </select>
                    <button id="memoryManagerAdd" class="settings-button" type="button"></button>
                </div>
                <div id="memoryManagerSummary" class="memory-manager-summary"></div>
                <div id="memoryManagerCreate" class="memory-manager-create" hidden>
                    <strong id="memoryManagerNewTitle"></strong>
                    <label class="memory-manager-field">
                        <span id="memoryManagerTextLabel"></span>
                        <textarea id="memoryManagerNewText" rows="3" maxlength="1200"></textarea>
                    </label>
                    <div class="memory-manager-create-grid">
                        <label class="memory-manager-field">
                            <span id="memoryManagerCategoryLabel"></span>
                            <select id="memoryManagerNewCategory"></select>
                        </label>
                        <label class="memory-manager-field">
                            <span><span id="memoryManagerImportanceLabel"></span> · <output id="memoryManagerNewImportanceValue">0.80</output></span>
                            <input id="memoryManagerNewImportance" type="range" min="0" max="1" step="0.05" value="0.8">
                        </label>
                    </div>
                    <label class="memory-manager-switch"><input id="memoryManagerNewPinned" type="checkbox"> <span id="memoryManagerPinnedLabel"></span></label>
                    <div class="memory-manager-create-actions">
                        <button id="memoryManagerCreateCancel" class="settings-button" type="button"></button>
                        <button id="memoryManagerCreateSave" class="settings-button" type="button"></button>
                    </div>
                </div>
                <div id="memoryManagerList" class="memory-manager-list"></div>
                <div id="memoryManagerStatus" class="memory-manager-status" role="status" aria-live="polite"></div>
            </section>
        `;
        profilePane.after(pane);

        bindEvents();
        updateStaticLabels();
    }

    function categories(select, selected = 'preference') {
        select.innerHTML = '';
        for (const value of Object.keys(CATEGORY_LABELS)) {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = categoryLabel(value);
            select.appendChild(option);
        }
        select.value = Object.hasOwn(CATEGORY_LABELS, selected) ? selected : 'other';
    }

    function updateStaticLabels() {
        if (!pane) return;
        tab.textContent = t('tab');
        $('memoryManagerTitle').textContent = t('title');
        $('memoryManagerDescription').textContent = t('description');
        $('memoryManagerSearch').placeholder = t('search');
        $('memoryManagerAdd').textContent = t('add');
        $('memoryManagerFilter').options[0].textContent = t('all');
        $('memoryManagerFilter').options[1].textContent = t('active');
        $('memoryManagerFilter').options[2].textContent = t('pinned');
        $('memoryManagerFilter').options[3].textContent = t('disabled');
        $('memoryManagerNewTitle').textContent = t('newTitle');
        $('memoryManagerTextLabel').textContent = t('memoryText');
        $('memoryManagerNewText').placeholder = t('memoryPlaceholder');
        $('memoryManagerCategoryLabel').textContent = t('category');
        $('memoryManagerImportanceLabel').textContent = t('importance');
        $('memoryManagerPinnedLabel').textContent = t('pinnedLabel');
        $('memoryManagerCreateCancel').textContent = t('cancel');
        $('memoryManagerCreateSave').textContent = t('create');
        categories($('memoryManagerNewCategory'), $('memoryManagerNewCategory').value || 'preference');
        render();
    }

    function setStatus(message = '', error = false) {
        const element = $('memoryManagerStatus');
        if (!element) return;
        element.textContent = message;
        element.classList.toggle('error', error);
    }

    function filteredMemories() {
        const query = state.query.trim().toLocaleLowerCase();
        return state.memories.filter(item => {
            if (state.filter === 'active' && item.enabled === false) return false;
            if (state.filter === 'pinned' && item.pinned !== true) return false;
            if (state.filter === 'disabled' && item.enabled !== false) return false;
            if (!query) return true;
            return `${item.text || ''} ${item.category || ''}`.toLocaleLowerCase().includes(query);
        });
    }

    function formatDate(value) {
        if (!value) return t('never');
        try {
            return new Intl.DateTimeFormat(
                window.MLXI18n?.getLocale?.() || undefined,
                { dateStyle: 'medium', timeStyle: 'short' }
            ).format(new Date(Number(value) * 1000));
        } catch (_) {
            return t('never');
        }
    }

    function renderSummary() {
        const target = $('memoryManagerSummary');
        if (!target) return;
        const active = state.memories.filter(item => item.enabled !== false).length;
        const pinned = state.memories.filter(item => item.pinned === true).length;
        const disabled = state.memories.length - active;
        target.innerHTML = '';
        for (const text of [
            `${state.memories.length} ${t('memories')}`,
            `${active} ${t('activeCount')}`,
            `${pinned} ${t('pinnedCount')}`,
            `${disabled} ${t('disabledCount')}`,
        ]) {
            const badge = document.createElement('span');
            badge.textContent = text;
            target.appendChild(badge);
        }
    }

    function makeButton(label, className = 'settings-button') {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = label;
        return button;
    }

    function renderCard(item) {
        const card = document.createElement('article');
        card.className = 'memory-manager-card';
        card.classList.toggle('is-disabled', item.enabled === false);

        const head = document.createElement('div');
        head.className = 'memory-manager-card-head';
        const badges = document.createElement('div');
        badges.className = 'memory-manager-badges';

        const categoryBadge = document.createElement('span');
        categoryBadge.className = 'memory-manager-badge';
        categoryBadge.textContent = categoryLabel(item.category);
        badges.appendChild(categoryBadge);
        if (item.pinned) {
            const pinBadge = document.createElement('span');
            pinBadge.className = 'memory-manager-badge pin';
            pinBadge.textContent = '📌 ' + t('pinned');
            badges.appendChild(pinBadge);
        }

        const enabledLabel = document.createElement('label');
        enabledLabel.className = 'memory-manager-switch';
        const enabled = document.createElement('input');
        enabled.type = 'checkbox';
        enabled.checked = item.enabled !== false;
        enabledLabel.append(enabled, document.createTextNode(' ' + t('enabled')));
        head.append(badges, enabledLabel);

        const text = document.createElement('textarea');
        text.value = item.text || '';
        text.maxLength = 1200;

        const fields = document.createElement('div');
        fields.className = 'memory-manager-fields';
        const categoryField = document.createElement('label');
        categoryField.className = 'memory-manager-field';
        const categoryCaption = document.createElement('span');
        categoryCaption.textContent = t('category');
        const category = document.createElement('select');
        categories(category, item.category);
        categoryField.append(categoryCaption, category);

        const importanceField = document.createElement('label');
        importanceField.className = 'memory-manager-field';
        const importanceCaption = document.createElement('span');
        const importanceValue = document.createElement('output');
        importanceValue.textContent = Number(item.importance ?? 0.7).toFixed(2);
        importanceCaption.append(
            document.createTextNode(t('importance') + ' · '),
            importanceValue
        );
        const importance = document.createElement('input');
        importance.type = 'range';
        importance.min = '0';
        importance.max = '1';
        importance.step = '0.05';
        importance.value = String(item.importance ?? 0.7);
        importance.addEventListener('input', () => {
            importanceValue.textContent = Number(importance.value).toFixed(2);
        });
        importanceField.append(importanceCaption, importance);
        fields.append(categoryField, importanceField);

        const meta = document.createElement('div');
        meta.className = 'memory-manager-meta';
        meta.textContent = `${t('confidence')}: ${Number(item.confidence ?? 0).toFixed(2)} · ${t('updated')}: ${formatDate(item.updated_at)} · ${t('used')}: ${item.use_count || 0}`;

        const actions = document.createElement('div');
        actions.className = 'memory-manager-actions';
        const save = makeButton(t('save'));
        const pin = makeButton(item.pinned ? t('unpin') : t('pin'));
        const remove = makeButton(t('remove'), 'settings-button danger');
        actions.append(save, pin, remove);

        enabled.addEventListener('change', async () => {
            enabled.disabled = true;
            try {
                const data = await patch(item.id, { enabled: enabled.checked });
                replaceMemory(data.memory);
                render();
            } catch (error) {
                enabled.checked = !enabled.checked;
                setStatus(`${t('error')} ${error.message}`, true);
            } finally {
                enabled.disabled = false;
            }
        });

        save.addEventListener('click', async () => {
            save.disabled = true;
            try {
                const data = await patch(item.id, {
                    text: text.value.trim(),
                    category: category.value,
                    importance: Number(importance.value),
                });
                replaceMemory(data.memory);
                setStatus(t('saved'));
                render();
            } catch (error) {
                setStatus(`${t('error')} ${error.message}`, true);
            } finally {
                save.disabled = false;
            }
        });

        pin.addEventListener('click', async () => {
            pin.disabled = true;
            try {
                const data = await patch(item.id, { pinned: !item.pinned });
                replaceMemory(data.memory);
                render();
            } catch (error) {
                setStatus(`${t('error')} ${error.message}`, true);
            } finally {
                pin.disabled = false;
            }
        });

        remove.addEventListener('click', async () => {
            const confirmed = window.MLXConfirm
                ? await window.MLXConfirm({
                    title: t('deleteTitle'),
                    message: t('deleteMessage'),
                    confirmLabel: t('remove'),
                    cancelLabel: t('cancel'),
                })
                : window.confirm(t('deleteMessage'));
            if (!confirmed) return;
            remove.disabled = true;
            try {
                await request(`/api/mlx/memory/${encodeURIComponent(item.id)}`, {
                    method: 'DELETE',
                });
                state.memories = state.memories.filter(memory => memory.id !== item.id);
                setStatus(t('deleted'));
                render();
            } catch (error) {
                setStatus(`${t('error')} ${error.message}`, true);
                remove.disabled = false;
            }
        });

        card.append(head, text, fields, meta, actions);
        return card;
    }

    function render() {
        if (!pane) return;
        renderSummary();
        const target = $('memoryManagerList');
        if (!target) return;
        target.innerHTML = '';

        if (state.loading) {
            const empty = document.createElement('div');
            empty.className = 'memory-manager-empty';
            empty.textContent = t('loading');
            target.appendChild(empty);
            return;
        }

        const items = filteredMemories();
        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'memory-manager-empty';
            empty.textContent = state.memories.length ? t('noResults') : t('empty');
            target.appendChild(empty);
            return;
        }

        for (const item of items) target.appendChild(renderCard(item));
    }

    function replaceMemory(memory) {
        const index = state.memories.findIndex(item => item.id === memory.id);
        if (index >= 0) state.memories[index] = memory;
        else state.memories.unshift(memory);
    }

    function patch(id, payload) {
        return request(`/api/mlx/memory/${encodeURIComponent(id)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
    }

    async function load() {
        if (!pane || state.loading) return;
        state.loading = true;
        setStatus('');
        render();
        try {
            const data = await request('/api/mlx/memory?include_disabled=true&limit=500');
            state.memories = Array.isArray(data.memories) ? data.memories : [];
        } catch (error) {
            setStatus(`${t('loadFailed')} ${error.message}`, true);
        } finally {
            state.loading = false;
            render();
        }
    }

    async function createMemory() {
        const text = $('memoryManagerNewText').value.trim();
        if (!text) {
            $('memoryManagerNewText').focus();
            return;
        }
        const button = $('memoryManagerCreateSave');
        button.disabled = true;
        try {
            const data = await request('/api/mlx/memory', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text,
                    category: $('memoryManagerNewCategory').value,
                    importance: Number($('memoryManagerNewImportance').value),
                    confidence: 0.95,
                    pinned: $('memoryManagerNewPinned').checked,
                }),
            });
            replaceMemory(data.memory);
            $('memoryManagerNewText').value = '';
            $('memoryManagerNewPinned').checked = false;
            $('memoryManagerCreate').hidden = true;
            setStatus(t('created'));
            render();
        } catch (error) {
            setStatus(`${t('error')} ${error.message}`, true);
        } finally {
            button.disabled = false;
        }
    }

    function deactivateTab() {
        if (!tab) return;
        tab.classList.remove('active');
        tab.setAttribute('aria-selected', 'false');
    }

    function activate() {
        buildUi();
        const settings = $('settings');
        if (!settings || !pane || !tab) return;
        settings.classList.add('open');
        settings.querySelectorAll('[data-settings-pane]').forEach(item => {
            item.hidden = item !== pane;
        });
        settings.querySelectorAll('[data-settings-tab]').forEach(button => {
            button.classList.remove('active');
            button.setAttribute('aria-selected', 'false');
        });
        settings.querySelector('.settings-subtabs')?.setAttribute('hidden', '');
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        pane.hidden = false;
        window.MLXModelConsole?.close?.();
        history.replaceState(null, '', '/settings/memory');
        load();
    }

    function bindEvents() {
        tab.addEventListener('click', activate);
        $('memoryManagerSearch').addEventListener('input', event => {
            state.query = event.target.value;
            render();
        });
        $('memoryManagerFilter').addEventListener('change', event => {
            state.filter = event.target.value;
            render();
        });
        $('memoryManagerAdd').addEventListener('click', () => {
            $('memoryManagerCreate').hidden = false;
            $('memoryManagerNewText').focus();
        });
        $('memoryManagerCreateCancel').addEventListener('click', () => {
            $('memoryManagerCreate').hidden = true;
        });
        $('memoryManagerCreateSave').addEventListener('click', createMemory);
        $('memoryManagerNewImportance').addEventListener('input', event => {
            $('memoryManagerNewImportanceValue').textContent = Number(event.target.value).toFixed(2);
        });

        document.querySelectorAll('[data-settings-tab]').forEach(button => {
            button.addEventListener('click', deactivateTab, true);
        });
        for (const id of ['settingsButton', 'sidebarSettingsButton', 'railSettings']) {
            $(id)?.addEventListener('click', deactivateTab, true);
        }
    }

    function init() {
        buildUi();
        if (requestedAtBoot) {
            setTimeout(activate, 0);
        }
    }

    init();

    document.addEventListener('mlx-language-changed', () => {
        updateStaticLabels();
    });

    window.MLXMemory = { load, activate };
})();
