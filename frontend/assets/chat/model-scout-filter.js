(function () {
    'use strict';

    if (window.__mlxNobbyModelScoutFilter) return;
    window.__mlxNobbyModelScoutFilter = true;

    const FILTER_VALUES = ['all', 'uncensored', 'heretic', 'abliterated', 'orthogonalized', 'unfiltered', 'standard'];
    let selectedFilter = 'all';
    let rootObserver = null;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function labels() {
        if (locale() === 'de') {
            return {
                aria: 'Modelle nach Tuning filtern',
                all: 'Tuning: Alle',
                uncensored: 'Uncensored',
                heretic: 'Heretic',
                abliterated: 'Abliterated',
                orthogonalized: 'Orthogonalized',
                unfiltered: 'Unfiltered',
                standard: 'Standard',
                count: (visible, total) => `${visible}/${total}`,
            };
        }
        return {
            aria: 'Filter models by tuning',
            all: 'Tuning: All',
            uncensored: 'Uncensored',
            heretic: 'Heretic',
            abliterated: 'Abliterated',
            orthogonalized: 'Orthogonalized',
            unfiltered: 'Unfiltered',
            standard: 'Standard',
            count: (visible, total) => `${visible}/${total}`,
        };
    }

    function normalize(value) {
        return String(value || '').trim().toLowerCase();
    }

    function traitsFromCard(card) {
        const traits = new Set();
        const modelId = card?.querySelector?.('.model-scout-name')?.textContent || '';
        const detector = window.MLXModelScout?.tuningTraits;
        if (typeof detector === 'function') {
            try {
                for (const trait of detector({ id: modelId, tags: [] }) || []) {
                    const normalized = normalize(trait);
                    if (normalized) traits.add(normalized);
                }
            } catch (_) {}
        }

        for (const chip of card?.querySelectorAll?.('.model-scout-chip.tuning') || []) {
            const value = normalize(chip.textContent);
            if (!value) continue;
            if (value.includes('uncensored')) traits.add('uncensored');
            if (value.includes('heretic')) traits.add('heretic');
            if (value.includes('abliterated')) traits.add('abliterated');
            if (value.includes('orthogonalized') || value.includes('orthogonalised')) traits.add('orthogonalized');
            if (value.includes('unfiltered')) traits.add('unfiltered');
        }
        return traits;
    }

    function matchesTuningFilter(card, filter) {
        const value = FILTER_VALUES.includes(filter) ? filter : 'all';
        if (value === 'all') return true;
        const traits = traitsFromCard(card);
        if (value === 'standard') return traits.size === 0;
        return traits.has(value);
    }

    function applyFilter(panel) {
        if (!panel) return;
        const select = panel.querySelector('[data-scout-tuning-filter]');
        const grid = panel.querySelector('[data-scout-grid]');
        const counter = panel.querySelector('[data-scout-tuning-count]');
        if (!select || !grid) return;

        const value = FILTER_VALUES.includes(select.value) ? select.value : 'all';
        selectedFilter = value;
        const cards = Array.from(grid.querySelectorAll('.model-scout-card'));
        let visible = 0;
        for (const card of cards) {
            const show = matchesTuningFilter(card, value);
            card.hidden = !show;
            if (show) visible += 1;
        }
        if (counter) counter.textContent = labels().count(visible, cards.length);
    }

    function populateSelect(select) {
        const copy = labels();
        const current = FILTER_VALUES.includes(select.value) ? select.value : selectedFilter;
        select.innerHTML = '';
        for (const value of FILTER_VALUES) {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = copy[value];
            select.appendChild(option);
        }
        select.value = FILTER_VALUES.includes(current) ? current : 'all';
        select.setAttribute('aria-label', copy.aria);
    }

    function mountFilter(panel) {
        if (!panel) return false;
        const controls = panel.querySelector('.model-scout-controls');
        const grid = panel.querySelector('[data-scout-grid]');
        if (!controls || !grid) return false;

        let select = controls.querySelector('[data-scout-tuning-filter]');
        if (!select) {
            select = document.createElement('select');
            select.className = 'model-scout-select';
            select.dataset.scoutTuningFilter = 'true';
            populateSelect(select);
            select.value = selectedFilter;
            select.addEventListener('change', () => applyFilter(panel));

            const roleSelect = controls.querySelector('[data-scout-role]');
            if (roleSelect?.nextSibling) controls.insertBefore(select, roleSelect.nextSibling);
            else controls.appendChild(select);

            const counter = document.createElement('span');
            counter.dataset.scoutTuningCount = 'true';
            counter.className = 'model-scout-meta';
            counter.style.marginLeft = '0';
            controls.insertBefore(counter, select.nextSibling);

            const gridObserver = new MutationObserver(() => applyFilter(panel));
            gridObserver.observe(grid, { childList: true });
            panel.__modelScoutTuningObserver = gridObserver;
        } else {
            populateSelect(select);
            select.value = selectedFilter;
        }

        applyFilter(panel);
        return true;
    }

    function mount() {
        const panel = document.querySelector('#modelConsoleContent > .model-scout');
        return mountFilter(panel);
    }

    function scheduleMount() {
        requestAnimationFrame(() => { mount(); });
    }

    window.MLXModelScout = {
        ...(window.MLXModelScout || {}),
        matchesTuningFilter,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleMount, { once: true });
    } else {
        scheduleMount();
    }

    rootObserver = new MutationObserver(() => {
        const panel = document.querySelector('#modelConsoleContent > .model-scout');
        if (panel && !panel.querySelector('[data-scout-tuning-filter]')) scheduleMount();
    });
    rootObserver.observe(document.documentElement, { childList: true, subtree: true });

    document.addEventListener('mlx-language-changed', () => {
        const panel = document.querySelector('#modelConsoleContent > .model-scout');
        const select = panel?.querySelector('[data-scout-tuning-filter]');
        if (select) {
            populateSelect(select);
            select.value = selectedFilter;
            applyFilter(panel);
        } else {
            scheduleMount();
        }
    });
})();
