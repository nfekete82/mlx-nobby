(() => {
    'use strict';

    const state = {
        memories: [],
        consolidations: [],
        status: null,
        busy: false,
        historyOpen: false,
    };
    const FALLBACK = {
        title: 'Memory consolidation',
        description: 'Keep the newest useful preference active and preserve older variants as disabled history.',
        enabled: 'Automatic consolidation active',
        unavailable: 'Consolidation status unavailable',
        events: 'consolidations',
        disabled: 'disabled memories',
        clean: 'Clean up memory',
        cleaning: 'Cleaning up …',
        cleanDone: 'Memory cleanup completed: {absorbed} older variant(s) consolidated.',
        history: 'History',
        hideHistory: 'Hide history',
        historyEmpty: 'No consolidations yet.',
        olderVariant: '1 older variant',
        olderVariants: '{count} older variants',
        replacedBy: 'Replaced by',
        replacedOlder: 'Older variant',
        currentVariant: 'Current variant',
        restore: 'Restore as current',
        restoreTitle: 'Restore older memory?',
        restoreMessage: 'This older memory will become current again. The currently active variant may be disabled automatically.',
        restoreDone: 'Older memory restored as the current variant.',
        cancel: 'Cancel',
        reason_slot_replacement: 'Updated preference',
        reason_semantic_duplicate: 'Semantic duplicate',
        reason_lexical_duplicate: 'Duplicate',
        reason_consolidated: 'Consolidated',
        similarity: 'Similarity',
        loadFailed: 'Could not load consolidation data:',
        error: 'Error:',
    };

    let translations = { en: FALLBACK, de: FALLBACK };
    let listObserver = null;
    let rootObserver = null;

    const $ = id => document.getElementById(id);
    const language = () => window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    const interpolate = (value, values = {}) => Object.entries(values).reduce(
        (result, [key, replacement]) => result.replaceAll(`{${key}}`, String(replacement ?? '')),
        String(value || '')
    );
    const t = (key, values = {}) => interpolate(
        translations[language()]?.[key] || translations.en?.[key] || FALLBACK[key] || key,
        values
    );

    async function request(path, options = {}) {
        const response = await fetch(path, options);
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        return data;
    }

    async function loadTranslations() {
        try {
            const response = await fetch('/i18n/memory-manager-consolidation.json', { cache: 'no-cache' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (payload?.de && payload?.en) translations = payload;
        } catch (error) {
            console.warn('[memory-consolidation] translations unavailable', error);
        }
    }

    function formatDate(value) {
        if (!value) return '';
        try {
            return new Intl.DateTimeFormat(
                window.MLXI18n?.getLocale?.() || undefined,
                { dateStyle: 'medium', timeStyle: 'short' }
            ).format(new Date(Number(value) * 1000));
        } catch (_) { return ''; }
    }

    function reasonLabel(reason) {
        return t(`reason_${String(reason || 'consolidated')}`);
    }

    function injectStyles() {
        if ($('memoryManagerConsolidationStyles')) return;
        const style = document.createElement('style');
        style.id = 'memoryManagerConsolidationStyles';
        style.textContent = `
            .memory-consolidation{margin:0 0 16px;padding:13px;border:1px solid rgba(127,127,127,.22);border-radius:12px;background:rgba(127,127,127,.035)}
            .memory-consolidation-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap}
            .memory-consolidation-copy{display:grid;gap:4px;min-width:min(100%,320px)}
            .memory-consolidation-copy small{color:var(--muted,#7d8794);line-height:1.45}
            .memory-consolidation-actions,.memory-consolidation-stats{display:flex;gap:8px;flex-wrap:wrap}
            .memory-consolidation-stats{margin-top:10px;color:var(--muted,#7d8794);font-size:.76rem}
            .memory-consolidation-stat{padding:3px 7px;border:1px solid rgba(127,127,127,.18);border-radius:999px}
            .memory-consolidation-history{display:grid;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid rgba(127,127,127,.16)}
            .memory-consolidation-event{display:grid;gap:6px;padding:9px 10px;border-radius:9px;background:rgba(127,127,127,.055)}
            .memory-consolidation-event-head{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}
            .memory-consolidation-event-text{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:8px;align-items:center;font-size:.78rem}
            .memory-consolidation-event-text span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
            .memory-consolidation-event-meta{font-size:.72rem;color:var(--muted,#7d8794)}
            .memory-consolidation-relation{display:grid;gap:5px;padding:8px 10px;border-left:3px solid rgba(127,127,127,.28);border-radius:6px;background:rgba(127,127,127,.045);font-size:.76rem;color:var(--muted,#7d8794)}
            .memory-consolidation-relation strong{color:var(--text,inherit);font-weight:600}
            .memory-consolidation-relation-actions{display:flex;justify-content:flex-end;margin-top:2px}
            .memory-manager-badge.consolidated{background:rgba(90,140,255,.13)}
            @media(max-width:700px){.memory-consolidation-event-text{grid-template-columns:1fr}.memory-consolidation-event-arrow{display:none}}
        `;
        document.head.appendChild(style);
    }

    function ensureUi() {
        const summary = $('memoryManagerSummary');
        if (!summary) return null;
        injectStyles();
        let root = $('memoryManagerConsolidation');
        if (root) return root;

        root = document.createElement('section');
        root.id = 'memoryManagerConsolidation';
        root.className = 'memory-consolidation';
        root.innerHTML = `
            <div class="memory-consolidation-head">
                <div class="memory-consolidation-copy">
                    <strong id="memoryConsolidationTitle"></strong>
                    <small id="memoryConsolidationDescription"></small>
                </div>
                <div class="memory-consolidation-actions">
                    <button id="memoryConsolidationRun" class="settings-button" type="button"></button>
                    <button id="memoryConsolidationHistoryToggle" class="settings-button" type="button"></button>
                </div>
            </div>
            <div id="memoryConsolidationStats" class="memory-consolidation-stats"></div>
            <div id="memoryConsolidationHistory" class="memory-consolidation-history" hidden></div>
        `;
        summary.after(root);
        $('memoryConsolidationRun').addEventListener('click', runConsolidation);
        $('memoryConsolidationHistoryToggle').addEventListener('click', () => {
            state.historyOpen = !state.historyOpen;
            renderPanel();
        });

        const tab = $('memoryManagerTab');
        if (tab && tab.dataset.consolidationBound !== '1') {
            tab.dataset.consolidationBound = '1';
            tab.addEventListener('click', () => setTimeout(loadData, 0));
        }
        observeMemoryList();
        renderPanel();
        return root;
    }

    function renderStats() {
        const target = $('memoryConsolidationStats');
        if (!target) return;
        target.replaceChildren();
        const status = state.status || {};
        const values = [
            status.enabled === false ? t('unavailable') : t('enabled'),
            `${Number(status.events ?? state.consolidations.length)} ${t('events')}`,
            `${Number(status.disabled_memories ?? state.memories.filter(item => item.enabled === false).length)} ${t('disabled')}`,
        ];
        for (const value of values) {
            const badge = document.createElement('span');
            badge.className = 'memory-consolidation-stat';
            badge.textContent = value;
            target.appendChild(badge);
        }
    }

    function renderHistory() {
        const target = $('memoryConsolidationHistory');
        if (!target) return;
        target.hidden = !state.historyOpen;
        target.replaceChildren();
        if (!state.historyOpen) return;
        if (!state.consolidations.length) {
            const empty = document.createElement('div');
            empty.className = 'memory-manager-empty';
            empty.textContent = t('historyEmpty');
            target.appendChild(empty);
            return;
        }
        for (const event of state.consolidations) {
            const item = document.createElement('article');
            item.className = 'memory-consolidation-event';
            const head = document.createElement('div');
            head.className = 'memory-consolidation-event-head';
            const badge = document.createElement('span');
            badge.className = 'memory-manager-badge consolidated';
            badge.textContent = reasonLabel(event.reason);
            const date = document.createElement('span');
            date.className = 'memory-consolidation-event-meta';
            date.textContent = formatDate(event.created_at);
            head.append(badge, date);

            const texts = document.createElement('div');
            texts.className = 'memory-consolidation-event-text';
            const oldText = document.createElement('span');
            oldText.title = String(event.absorbed_text || '');
            oldText.textContent = `${t('replacedOlder')}: ${event.absorbed_text || '—'}`;
            const arrow = document.createElement('span');
            arrow.className = 'memory-consolidation-event-arrow';
            arrow.textContent = '→';
            const currentText = document.createElement('span');
            currentText.title = String(event.primary_text || '');
            currentText.textContent = `${t('currentVariant')}: ${event.primary_text || '—'}`;
            texts.append(oldText, arrow, currentText);
            item.append(head, texts);
            if (event.similarity !== null && Number.isFinite(Number(event.similarity))) {
                const meta = document.createElement('div');
                meta.className = 'memory-consolidation-event-meta';
                meta.textContent = `${t('similarity')}: ${(Number(event.similarity) * 100).toFixed(1)} %`;
                item.appendChild(meta);
            }
            target.appendChild(item);
        }
    }

    function latestRelations() {
        const absorbed = new Map();
        for (const event of state.consolidations) {
            const id = String(event.absorbed_memory_id || '');
            if (id && !absorbed.has(id)) absorbed.set(id, event);
        }
        const primary = new Map();
        for (const event of absorbed.values()) {
            const id = String(event.primary_memory_id || '');
            if (!id) continue;
            if (!primary.has(id)) primary.set(id, []);
            primary.get(id).push(event);
        }
        return { absorbed, primary };
    }

    function memoryForCard(card) {
        const text = String(card.querySelector('textarea')?.value || '').trim();
        if (!text) return null;
        const category = card.querySelector('.memory-manager-fields select')?.value;
        const exact = state.memories.filter(item => (
            String(item.text || '').trim() === text
            && (!category || String(item.category || '') === String(category))
        ));
        if (exact.length === 1) return exact[0];
        const byText = state.memories.filter(item => String(item.text || '').trim() === text);
        return byText.length === 1 ? byText[0] : null;
    }

    function relationBadge(label) {
        const badge = document.createElement('span');
        badge.className = 'memory-manager-badge consolidated';
        badge.dataset.memoryConsolidationDecoration = '1';
        badge.textContent = label;
        return badge;
    }

    function decorateCards() {
        const list = $('memoryManagerList');
        if (!list) return;
        const relations = latestRelations();
        for (const card of list.querySelectorAll('.memory-manager-card')) {
            card.querySelectorAll('[data-memory-consolidation-decoration]').forEach(node => node.remove());
            const item = memoryForCard(card);
            if (!item) continue;
            const absorbedEvent = relations.absorbed.get(String(item.id));
            const older = relations.primary.get(String(item.id)) || [];
            const badges = card.querySelector('.memory-manager-badges');

            if (absorbedEvent) {
                badges?.appendChild(relationBadge(reasonLabel(absorbedEvent.reason)));
                const relation = document.createElement('div');
                relation.className = 'memory-consolidation-relation';
                relation.dataset.memoryConsolidationDecoration = '1';
                const label = document.createElement('div');
                const strong = document.createElement('strong');
                strong.textContent = absorbedEvent.primary_text || '—';
                label.append(document.createTextNode(`${t('replacedBy')}: `), strong);
                relation.appendChild(label);
                if (item.enabled === false) {
                    const actions = document.createElement('div');
                    actions.className = 'memory-consolidation-relation-actions';
                    const restore = document.createElement('button');
                    restore.type = 'button';
                    restore.className = 'settings-button';
                    restore.textContent = t('restore');
                    restore.addEventListener('click', () => restoreMemory(item, restore));
                    actions.appendChild(restore);
                    relation.appendChild(actions);
                }
                card.querySelector('.memory-manager-actions')?.before(relation);
                continue;
            }

            if (item.enabled !== false && older.length) {
                const label = older.length === 1
                    ? t('olderVariant')
                    : t('olderVariants', { count: older.length });
                badges?.appendChild(relationBadge(label));
                const relation = document.createElement('div');
                relation.className = 'memory-consolidation-relation';
                relation.dataset.memoryConsolidationDecoration = '1';
                relation.textContent = older.slice(0, 3)
                    .map(event => event.absorbed_text)
                    .filter(Boolean)
                    .join(' · ');
                card.querySelector('.memory-manager-actions')?.before(relation);
            }
        }
    }

    function observeMemoryList() {
        const list = $('memoryManagerList');
        if (!list || listObserver) return;
        listObserver = new MutationObserver(() => queueMicrotask(decorateCards));
        // Only observe cards being replaced. Decorations inside a card must not
        // retrigger the observer and create a render loop.
        listObserver.observe(list, { childList: true });
    }

    function renderPanel() {
        if (!$('memoryManagerConsolidation')) return;
        $('memoryConsolidationTitle').textContent = t('title');
        $('memoryConsolidationDescription').textContent = t('description');
        $('memoryConsolidationRun').textContent = state.busy ? t('cleaning') : t('clean');
        $('memoryConsolidationRun').disabled = state.busy;
        $('memoryConsolidationHistoryToggle').textContent = state.historyOpen ? t('hideHistory') : t('history');
        renderStats();
        renderHistory();
        decorateCards();
    }

    async function confirmRestore() {
        if (window.MLXConfirm) {
            return window.MLXConfirm({
                title: t('restoreTitle'),
                message: t('restoreMessage'),
                confirmLabel: t('restore'),
                cancelLabel: t('cancel'),
            });
        }
        return window.confirm(t('restoreMessage'));
    }

    async function reloadAll() {
        await Promise.all([
            Promise.resolve(window.MLXMemory?.load?.()),
            loadData({ force: true }),
        ]);
    }

    async function restoreMemory(item, button) {
        if (!await confirmRestore()) return;
        button.disabled = true;
        try {
            await request(`/api/mlx/memory/${encodeURIComponent(item.id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: true }),
            });
            await reloadAll();
            if ($('memoryManagerStatus')) $('memoryManagerStatus').textContent = t('restoreDone');
        } catch (error) {
            if ($('memoryManagerStatus')) $('memoryManagerStatus').textContent = `${t('error')} ${error.message}`;
            button.disabled = false;
        }
    }

    async function runConsolidation() {
        if (state.busy) return;
        state.busy = true;
        renderPanel();
        try {
            const result = await request('/api/mlx/memory/consolidate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ limit: 500 }),
            });
            await reloadAll();
            if ($('memoryManagerStatus')) {
                $('memoryManagerStatus').textContent = t('cleanDone', {
                    absorbed: Number(result.absorbed || 0),
                });
            }
        } catch (error) {
            if ($('memoryManagerStatus')) $('memoryManagerStatus').textContent = `${t('error')} ${error.message}`;
        } finally {
            state.busy = false;
            renderPanel();
        }
    }

    async function loadData(options = {}) {
        if (!ensureUi()) return;
        if (state.busy && !options.force) return;
        try {
            const [memories, status, history] = await Promise.all([
                request('/api/mlx/memory?include_disabled=true&limit=500'),
                request('/api/mlx/memory/consolidation-status'),
                request('/api/mlx/memory/consolidations?limit=100'),
            ]);
            state.memories = Array.isArray(memories.memories) ? memories.memories : [];
            state.status = status && typeof status === 'object' ? status : null;
            state.consolidations = Array.isArray(history.consolidations) ? history.consolidations : [];
            renderPanel();
        } catch (error) {
            if ($('memoryManagerStatus')) $('memoryManagerStatus').textContent = `${t('loadFailed')} ${error.message}`;
        }
    }

    function attach() {
        if (!ensureUi()) return false;
        if (location.pathname === '/settings/memory' || !$('memoryManagerPane')?.hidden) loadData();
        return true;
    }

    async function init() {
        await loadTranslations();
        if (attach()) return;
        if (!document.body || typeof MutationObserver === 'undefined') return;
        rootObserver = new MutationObserver(() => {
            if (!attach()) return;
            rootObserver.disconnect();
            rootObserver = null;
        });
        rootObserver.observe(document.body, { childList: true, subtree: true });
    }

    document.addEventListener('mlx-language-changed', renderPanel);
    window.MLXMemoryConsolidation = {
        load: loadData,
        run: runConsolidation,
        getState: () => ({
            memories: state.memories.slice(),
            consolidations: state.consolidations.slice(),
            status: state.status ? { ...state.status } : null,
        }),
    };
    init();
})();
