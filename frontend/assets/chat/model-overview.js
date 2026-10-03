(function () {
    'use strict';

    const state = {
        query: '',
        filter: 'all',
        sort: 'active',
        scheduled: false,
    };

    function t(key, fallback, variables = {}) {
        let value = window.MLXI18n?.t(`models.overview.${key}`, fallback) ?? fallback;
        Object.entries(variables).forEach(([name, replacement]) => {
            value = value.replaceAll(`{${name}}`, String(replacement));
        });
        return value;
    }

    function injectStyles() {
        if (document.getElementById('modelOverviewStyles')) return;

        const style = document.createElement('style');
        style.id = 'modelOverviewStyles';
        style.textContent = `
            #modelConsoleContent.model-overview-enhanced {
                gap: 14px;
            }

            .model-overview-toolbar {
                display: grid;
                grid-template-columns: minmax(180px, 1fr) auto auto;
                gap: 9px;
                align-items: center;
                padding: 10px 0 12px;
            }

            .model-overview-search,
            .model-overview-select {
                height: 34px;
                min-width: 0;
                border: 1px solid #30394a;
                border-radius: 9px;
                background: #111722;
                color: var(--text);
                font: inherit;
                font-size: 12px;
            }

            .model-overview-search {
                width: 100%;
                padding: 0 11px;
            }

            .model-overview-select {
                padding: 0 28px 0 10px;
                cursor: pointer;
            }

            .model-overview-search:focus,
            .model-overview-select:focus {
                outline: 2px solid rgba(117, 161, 255, .55);
                outline-offset: 1px;
                border-color: #4f6f9f;
            }

            .model-overview-summary {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                padding: 0 0 10px;
            }

            .model-overview-summary-chip {
                display: inline-flex;
                align-items: center;
                min-height: 24px;
                padding: 4px 8px;
                border: 1px solid #2b3444;
                border-radius: 999px;
                background: rgba(17, 23, 34, .62);
                color: #9ca9ba;
                font-size: 10px;
                font-weight: 650;
                white-space: nowrap;
            }

            .model-overview-summary-chip.active {
                border-color: rgba(64, 214, 154, .25);
                background: rgba(24, 86, 66, .13);
                color: #76deb7;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-list {
                border-top: 0;
                display: grid;
                gap: 6px;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row {
                padding: 11px 10px;
                border: 1px solid #252e3d;
                border-radius: 10px;
                background: rgba(12, 16, 23, .36);
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row:hover {
                border-color: #364258;
                background: rgba(22, 28, 39, .62);
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row.active {
                border-color: rgba(64, 214, 154, .29);
                background: rgba(24, 86, 66, .10);
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row-title strong {
                font-size: 13px;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row-meta {
                margin-top: 5px;
                gap: 5px;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row-meta .model-console-badge {
                padding: 2px 6px;
                font-size: 9px;
                opacity: .9;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-availability {
                margin-top: 5px;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row-actions {
                gap: 6px;
            }

            #modelConsoleContent.model-overview-enhanced .model-console-row[hidden] {
                display: none;
            }

            .model-overview-empty {
                padding: 18px 10px;
                border: 1px dashed #30394a;
                border-radius: 10px;
                color: var(--muted);
                text-align: center;
                font-size: 12px;
            }

            @media (max-width: 720px) {
                .model-overview-toolbar {
                    grid-template-columns: 1fr 1fr;
                }

                .model-overview-search {
                    grid-column: 1 / -1;
                }

                #modelConsoleContent.model-overview-enhanced .model-console-row {
                    grid-template-columns: minmax(0, 1fr);
                    gap: 9px;
                }

                #modelConsoleContent.model-overview-enhanced .model-console-row-actions {
                    justify-content: flex-start;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function rowInfo(row) {
        const text = (row.textContent || '').toLowerCase();
        const badges = Array.from(row.querySelectorAll('.model-console-badge'))
            .map(item => (item.textContent || '').trim().toLowerCase());
        const alias = (row.querySelector('.model-console-alias')?.textContent || '').trim().toLowerCase();
        const name = (row.querySelector('.model-console-row-title strong')?.textContent || '').trim().toLowerCase();
        const activeLabel = (window.MLXI18n?.t('models.status.active', 'Active') || 'Active').toLowerCase();
        const localLabel = (window.MLXI18n?.t('models.status.local', 'Local') || 'Local').toLowerCase();

        return {
            text,
            alias,
            name,
            active: row.classList.contains('active') || badges.some(item => item.includes('active') || item.includes(activeLabel)),
            vision: badges.some(item => item === 'vision'),
            vlm: badges.some(item => item === 'vlm'),
            llm: badges.some(item => item === 'llm'),
            local: badges.some(item => item === 'local' || item === localLabel),
            hf: badges.some(item => item.includes('hugging face')),
        };
    }

    function matchesFilter(info) {
        switch (state.filter) {
            case 'active': return info.active;
            case 'vision': return info.vision || info.vlm;
            case 'text': return info.llm && !info.vision;
            case 'local': return info.local;
            case 'hf': return info.hf;
            default: return true;
        }
    }

    function sortRows(rows) {
        const sorted = [...rows].sort((a, b) => {
            const ai = rowInfo(a);
            const bi = rowInfo(b);

            if (state.sort === 'active' && ai.active !== bi.active) {
                return ai.active ? -1 : 1;
            }

            if (state.sort === 'alias') {
                return ai.alias.localeCompare(bi.alias, undefined, { sensitivity: 'base' });
            }

            return ai.name.localeCompare(bi.name, undefined, { sensitivity: 'base' });
        });

        const list = rows[0]?.parentElement;
        if (!list) return;

        const current = Array.from(list.children).filter(item => item.classList.contains('model-console-row'));
        const changed = sorted.some((row, index) => current[index] !== row);
        if (changed) sorted.forEach(row => list.appendChild(row));
    }

    function createToolbar(section) {
        let toolbar = section.querySelector(':scope > .model-overview-toolbar');
        if (toolbar) return toolbar;

        toolbar = document.createElement('div');
        toolbar.className = 'model-overview-toolbar';

        const search = document.createElement('input');
        search.type = 'search';
        search.className = 'model-overview-search';
        search.placeholder = t('search', 'Search models …');
        search.setAttribute('aria-label', search.placeholder);
        search.value = state.query;
        search.addEventListener('input', event => {
            state.query = event.target.value || '';
            applyOverview();
        });

        const filter = document.createElement('select');
        filter.className = 'model-overview-select';
        filter.setAttribute('aria-label', t('filter', 'Filter models'));
        [
            ['all', t('all', 'All models')],
            ['active', t('active_only', 'Active only')],
            ['vision', t('vision_filter', 'Vision / VLM')],
            ['text', t('text_only', 'Text / LLM only')],
            ['local', t('local_filter', 'Local')],
            ['hf', t('hf_filter', 'Hugging Face')],
        ].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            filter.appendChild(option);
        });
        filter.value = state.filter;
        filter.addEventListener('change', event => {
            state.filter = event.target.value;
            applyOverview();
        });

        const sort = document.createElement('select');
        sort.className = 'model-overview-select';
        sort.setAttribute('aria-label', t('sort', 'Sort models'));
        [
            ['active', t('active_first', 'Active first')],
            ['name', t('by_name', 'By name')],
            ['alias', t('by_alias', 'By alias')],
        ].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            sort.appendChild(option);
        });
        sort.value = state.sort;
        sort.addEventListener('change', event => {
            state.sort = event.target.value;
            applyOverview();
        });

        toolbar.append(search, filter, sort);
        const summary = section.querySelector(':scope > summary');
        summary?.insertAdjacentElement('afterend', toolbar);
        return toolbar;
    }

    function renderSummary(section, rows) {
        let summary = section.querySelector(':scope > .model-overview-summary');
        if (!summary) {
            summary = document.createElement('div');
            summary.className = 'model-overview-summary';
            const toolbar = section.querySelector(':scope > .model-overview-toolbar');
            toolbar?.insertAdjacentElement('afterend', summary);
        }

        const infos = rows.map(rowInfo);
        const active = infos.filter(item => item.active).length;
        const vision = infos.filter(item => item.vision || item.vlm).length;
        const local = infos.filter(item => item.local).length;
        const visible = rows.filter(row => !row.hidden).length;

        const filtered = Boolean(state.query.trim()) || state.filter !== 'all';
        const chips = [
            [t('installed', '{count} installed', { count: rows.length }), false],
            ...(filtered ? [[t('visible', '{count} of {total} visible', { count: visible, total: rows.length }), false]] : []),
            [t('vision', '{count} Vision', { count: vision }), false],
            [t('local', '{count} local', { count: local }), false],
            [t('active', '{count} active', { count: active }), active > 0],
        ];
        // Avoid retriggering the DOM observer when the summary has not changed.
        const signature = JSON.stringify(chips);
        if (summary.dataset.signature === signature) return;
        summary.dataset.signature = signature;
        summary.replaceChildren();
        chips.forEach(([label, isActive]) => {
            const chip = document.createElement('span');
            chip.className = 'model-overview-summary-chip' + (isActive ? ' active' : '');
            chip.textContent = label;
            summary.appendChild(chip);
        });
    }

    function renderEmpty(list, hasVisible) {
        let empty = list.querySelector(':scope > .model-overview-empty');
        if (hasVisible) {
            empty?.remove();
            return;
        }
        if (!empty) {
            empty = document.createElement('div');
            empty.className = 'model-overview-empty';
            list.appendChild(empty);
        }
        const label = t('empty', 'No models match the current search and filter.');
        if (empty.textContent !== label) empty.textContent = label;
    }

    function applyOverview() {
        const content = document.getElementById('modelConsoleContent');
        if (!content) return;

        const section = Array.from(content.querySelectorAll('.model-console-collapsible'))
            .find(item => item.querySelector('.model-console-list > .model-console-row'));

        if (!section) {
            content.classList.remove('model-overview-enhanced');
            return;
        }

        injectStyles();
        content.classList.add('model-overview-enhanced');
        createToolbar(section);

        const rows = Array.from(section.querySelectorAll('.model-console-list > .model-console-row'));
        const query = state.query.trim().toLowerCase();

        rows.forEach(row => {
            const info = rowInfo(row);
            const matchesQuery = !query || info.text.includes(query);
            row.hidden = !(matchesQuery && matchesFilter(info));
        });

        sortRows(rows);
        renderSummary(section, rows);
        renderEmpty(section.querySelector('.model-console-list'), rows.some(row => !row.hidden));
    }

    function scheduleOverview() {
        if (state.scheduled) return;
        state.scheduled = true;
        requestAnimationFrame(() => {
            state.scheduled = false;
            applyOverview();
        });
    }

    function init() {
        injectStyles();
        const content = document.getElementById('modelConsoleContent');
        if (!content) {
            setTimeout(init, 250);
            return;
        }

        const observer = new MutationObserver(scheduleOverview);
        observer.observe(content, { childList: true, subtree: true });
        scheduleOverview();

        document.addEventListener('mlx-language-changed', () => {
            content.querySelectorAll('.model-overview-toolbar').forEach(toolbar => toolbar.remove());
            scheduleOverview();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();