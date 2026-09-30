(function () {
    'use strict';

    if (window.__mlxNobbyRoutingObservatory) return;
    window.__mlxNobbyRoutingObservatory = true;

    const API = '/api/routing/decisions';
    const ROUTES = [
        ['chat', 'Chat'],
        ['image', 'Bild'],
        ['video_generate', 'Video'],
        ['shorts_generate', 'Short'],
        ['agent', 'Agent'],
        ['web_search', 'Websuche']
    ];

    const COPY = {
        de: {
            title: 'Routing Observatory',
            description: 'Zeigt, warum Nobby eine Route gewählt hat. Feedback wird lokal als Regression-Kandidat gespeichert.',
            refresh: 'Aktualisieren',
            loading: 'Routing-Entscheidungen werden geladen …',
            empty: 'Noch keine Routing-Entscheidungen vorhanden.',
            loadError: 'Routing-Daten konnten nicht geladen werden.',
            prompt: 'Prompt',
            route: 'Route',
            confidence: 'Confidence',
            reason: 'Grund',
            feedback: 'Feedback',
            right: 'Richtig',
            wrong: 'Falsch',
            save: 'Speichern',
            cancel: 'Abbrechen',
            total: 'Entscheidungen',
            guarded: 'abgefangen',
            wrongCount: 'Fehler markiert',
            savedRight: 'Als richtig markiert',
            savedWrong: 'Korrektur gespeichert',
            choose: 'Sollte sein …'
        },
        en: {
            title: 'Routing Observatory',
            description: 'Shows why Nobby selected a route. Feedback is stored locally as a regression candidate.',
            refresh: 'Refresh',
            loading: 'Loading routing decisions …',
            empty: 'No routing decisions yet.',
            loadError: 'Routing data could not be loaded.',
            prompt: 'Prompt',
            route: 'Route',
            confidence: 'Confidence',
            reason: 'Reason',
            feedback: 'Feedback',
            right: 'Correct',
            wrong: 'Wrong',
            save: 'Save',
            cancel: 'Cancel',
            total: 'Decisions',
            guarded: 'guarded',
            wrongCount: 'marked wrong',
            savedRight: 'Marked correct',
            savedWrong: 'Correction saved',
            choose: 'Should be …'
        }
    };

    const REASONS = {
        router_decision: { de: 'Router-Entscheidung', en: 'Router decision' },
        high_confidence: { de: 'Hohe Confidence', en: 'High confidence' },
        medium_confidence_explicit_intent: { de: 'Explizite Absicht', en: 'Explicit intent' },
        medium_confidence_requires_explicit_intent: { de: 'Explizite Absicht fehlt', en: 'Explicit intent required' },
        low_confidence_fallback: { de: 'Confidence zu niedrig', en: 'Low confidence fallback' },
        explicit_shorts_intent_required: { de: 'Short-Auftrag nicht explizit', en: 'Explicit Shorts intent required' },
        long_form_chat_fallback: { de: 'Langer Text → Chat', en: 'Long-form chat fallback' },
        conservative_fallback: { de: 'Konservativer Fallback', en: 'Conservative fallback' }
    };

    let card = null;
    let tableBody = null;
    let state = null;
    let status = null;
    let refreshButton = null;
    let initialized = false;
    let retryTimer = null;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function t(key) {
        return COPY[locale()]?.[key] || COPY.en[key] || key;
    }

    function routeLabel(target) {
        const map = {
            chat: 'Chat',
            image: locale() === 'de' ? 'Bild' : 'Image',
            image_edit: locale() === 'de' ? 'Bildbearbeitung' : 'Image edit',
            image_upscale: 'Upscale',
            video: 'Video',
            video_generate: 'Video',
            video_animate: locale() === 'de' ? 'Animation' : 'Animation',
            shorts_generate: 'Short',
            agent: 'Agent',
            coding_agent: 'Agent',
            web_search: locale() === 'de' ? 'Websuche' : 'Web search'
        };
        return map[target] || target || '—';
    }

    function reasonLabel(reason) {
        const item = REASONS[reason];
        return item?.[locale()] || reason || '—';
    }

    function formatConfidence(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return '—';
        return Math.round(number * 100) + ' %';
    }

    function confidenceClass(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return '';
        if (number >= 0.90) return 'is-high';
        if (number >= 0.65) return 'is-medium';
        return 'is-low';
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function buildCard(pane) {
        card = el('section', 'settings-card routing-observatory-card');
        card.id = 'routingObservatory';

        const header = el('div', 'routing-observatory-header');
        const copy = el('div', 'routing-observatory-copy');
        copy.append(
            el('h4', '', t('title')),
            el('p', '', t('description'))
        );

        refreshButton = el('button', 'routing-observatory-refresh', t('refresh'));
        refreshButton.type = 'button';
        refreshButton.addEventListener('click', () => refresh());

        header.append(copy, refreshButton);

        state = el('div', 'routing-observatory-stats');
        status = el('div', 'routing-observatory-status', t('loading'));

        const scroller = el('div', 'routing-observatory-table-wrap');
        const table = el('table', 'routing-observatory-table');
        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        [t('prompt'), t('route'), t('confidence'), t('reason'), t('feedback')].forEach(label => {
            headRow.appendChild(el('th', '', label));
        });
        thead.appendChild(headRow);
        tableBody = document.createElement('tbody');
        table.append(thead, tableBody);
        scroller.appendChild(table);

        card.append(header, state, status, scroller);
        pane.appendChild(card);
    }

    function stat(label, value) {
        const item = el('span', 'routing-observatory-stat');
        item.append(
            el('strong', '', String(value)),
            document.createTextNode(' ' + label)
        );
        return item;
    }

    function renderStats(decisions) {
        if (!state) return;
        const guarded = decisions.filter(item => item.guarded).length;
        const wrong = decisions.filter(item => item.feedback?.correct === false).length;
        state.replaceChildren(
            stat(t('total'), decisions.length),
            stat(t('guarded'), guarded),
            stat(t('wrongCount'), wrong)
        );
    }

    function feedbackSummary(decision) {
        const feedback = decision.feedback;
        if (!feedback) return null;

        const node = el(
            'span',
            'routing-feedback-saved ' + (feedback.correct ? 'is-correct' : 'is-wrong')
        );
        node.textContent = feedback.correct
            ? '✓ ' + t('savedRight')
            : '↪ ' + routeLabel(feedback.expected_target);
        return node;
    }

    async function postFeedback(decision, payload, cell) {
        cell.classList.add('is-busy');
        try {
            const response = await fetch(
                API + '/' + encodeURIComponent(decision.id) + '/feedback',
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                }
            );
            if (!response.ok) throw new Error('HTTP ' + response.status);
            decision.feedback = await response.json().then(item => item.feedback || payload);
            renderFeedback(decision, cell);
            await refresh({ quiet: true });
        } catch (error) {
            console.error('[MLX Routing Observatory] feedback failed', error);
            cell.classList.remove('is-busy');
        }
    }

    function renderCorrectionChooser(decision, cell) {
        cell.replaceChildren();

        const wrapper = el('div', 'routing-feedback-editor');
        const select = document.createElement('select');
        select.setAttribute('aria-label', t('choose'));
        ROUTES.forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        });
        select.value = decision.target === 'chat' ? 'image' : 'chat';

        const actions = el('div', 'routing-feedback-editor-actions');
        const save = el('button', 'routing-feedback-save', t('save'));
        save.type = 'button';
        save.addEventListener('click', () => postFeedback(
            decision,
            { correct: false, expected_target: select.value },
            cell
        ));

        const cancel = el('button', 'routing-feedback-cancel', t('cancel'));
        cancel.type = 'button';
        cancel.addEventListener('click', () => renderFeedback(decision, cell));

        actions.append(save, cancel);
        wrapper.append(select, actions);
        cell.appendChild(wrapper);
    }

    function renderFeedback(decision, cell) {
        cell.classList.remove('is-busy');
        cell.replaceChildren();

        const summary = feedbackSummary(decision);
        if (summary) {
            cell.appendChild(summary);
            return;
        }

        const actions = el('div', 'routing-feedback-actions');
        const correct = el('button', 'routing-feedback-correct', t('right'));
        correct.type = 'button';
        correct.addEventListener('click', () => postFeedback(
            decision,
            { correct: true },
            cell
        ));

        const wrong = el('button', 'routing-feedback-wrong', t('wrong'));
        wrong.type = 'button';
        wrong.addEventListener('click', () => renderCorrectionChooser(decision, cell));

        actions.append(correct, wrong);
        cell.appendChild(actions);
    }

    function renderRow(decision) {
        const row = document.createElement('tr');
        if (decision.guarded) row.classList.add('is-guarded');

        const promptCell = el('td', 'routing-prompt-cell');
        const prompt = el('div', 'routing-prompt-preview', decision.prompt_preview || '—');
        prompt.title = decision.prompt_preview || '';
        const meta = el(
            'div',
            'routing-prompt-meta',
            String(decision.prompt_chars || 0) + ' chars · ' +
                String(decision.prompt_sha256 || '').slice(0, 10)
        );
        promptCell.append(prompt, meta);

        const routeCell = el('td', 'routing-route-cell');
        const route = el('span', 'routing-route-badge', routeLabel(decision.target));
        routeCell.appendChild(route);
        if (decision.guarded && decision.original_target !== decision.target) {
            routeCell.appendChild(el(
                'div',
                'routing-route-original',
                routeLabel(decision.original_target) + ' → ' + routeLabel(decision.target)
            ));
        }

        const confidenceCell = el(
            'td',
            'routing-confidence ' + confidenceClass(decision.confidence),
            formatConfidence(decision.confidence)
        );
        if (decision.confidence_source) {
            confidenceCell.title = decision.confidence_source;
        }

        const reasonCell = el('td', 'routing-reason-cell', reasonLabel(decision.reason));
        if (decision.duration_ms !== null && decision.duration_ms !== undefined) {
            reasonCell.appendChild(el(
                'div',
                'routing-duration',
                Number(decision.duration_ms).toFixed(0) + ' ms'
            ));
        }

        const feedbackCell = el('td', 'routing-feedback-cell');
        renderFeedback(decision, feedbackCell);

        row.append(promptCell, routeCell, confidenceCell, reasonCell, feedbackCell);
        return row;
    }

    function render(decisions) {
        tableBody.replaceChildren();
        renderStats(decisions);

        if (!decisions.length) {
            status.hidden = false;
            status.textContent = t('empty');
            return;
        }

        status.hidden = true;
        decisions.forEach(decision => tableBody.appendChild(renderRow(decision)));
    }

    async function refresh(options = {}) {
        if (!card || !tableBody) return;
        if (!options.quiet) {
            refreshButton.disabled = true;
            status.hidden = false;
            status.textContent = t('loading');
        }

        try {
            const response = await fetch(API + '?limit=50', { cache: 'no-store' });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const payload = await response.json();
            render(Array.isArray(payload.decisions) ? payload.decisions : []);
        } catch (error) {
            console.error('[MLX Routing Observatory] load failed', error);
            status.hidden = false;
            status.textContent = t('loadError');
        } finally {
            if (refreshButton) refreshButton.disabled = false;
        }
    }

    function initialize() {
        if (initialized) return true;
        const pane = document.querySelector('[data-settings-pane="functions"]');
        if (!pane) return false;

        initialized = true;
        buildCard(pane);
        refresh();
        return true;
    }

    function start() {
        let attempts = 0;
        const tryInitialize = () => {
            attempts += 1;
            if (initialize()) return;
            if (attempts < 120) retryTimer = setTimeout(tryInitialize, 50);
        };
        tryInitialize();
    }

    window.MLXRoutingObservatory = {
        refresh,
        initialize
    };

    document.addEventListener('mlx-language-changed', () => {
        if (!card) return;
        card.remove();
        card = null;
        tableBody = null;
        state = null;
        status = null;
        refreshButton = null;
        initialized = false;
        clearTimeout(retryTimer);
        initialize();
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
