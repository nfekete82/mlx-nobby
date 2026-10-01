(function () {
    'use strict';

    if (window.__mlxNobbyRoutingObservatory) return;
    window.__mlxNobbyRoutingObservatory = true;

    const API = '/api/routing/decisions';
    const EVENTS_API = '/api/routing/events';
    const ROUTES = [
        'chat',
        'image',
        'video_generate',
        'shorts_generate',
        'agent',
        'web_search'
    ];

    const FALLBACK = {
        en: {
            title: 'Routing Observatory',
            time: 'Time', model: 'Model', duration: 'Routing time', status: 'Status', details: 'Details',
            fallbackRate: 'Fallback Rate', errorRate: 'Error Rate', medianTime: 'Median Routing Time',
            all: 'All', filter_route: 'Route', filter_source: 'Source', filter_success: 'Success',
            filter_fallback: 'Fallback', filter_model_role: 'Model role',
            description: 'Shows the router decision, final route, confidence and guard reason. Feedback is stored locally as a regression candidate.',
            refresh: 'Refresh',
            loading: 'Loading routing decisions …',
            empty: 'No routing decisions yet.',
            loadError: 'Routing data could not be loaded.',
            prompt: 'Prompt',
            originalRoute: 'Original route',
            finalRoute: 'Final route',
            confidence: 'Confidence',
            guardReason: 'Guard / reason',
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
            choose: 'Should be …',
            route_chat: 'Chat',
            route_image: 'Image',
            route_image_edit: 'Image edit',
            route_image_upscale: 'Upscale',
            route_video: 'Video',
            route_video_generate: 'Video',
            route_video_animate: 'Animation',
            route_shorts_generate: 'Short',
            route_agent: 'Agent',
            route_coding_agent: 'Agent',
            route_web_search: 'Web search',
            reason_router_decision: 'Router decision',
            reason_high_confidence: 'High confidence',
            reason_medium_confidence_explicit_intent: 'Explicit intent',
            reason_medium_confidence_requires_explicit_intent: 'Explicit intent required',
            reason_low_confidence_fallback: 'Low confidence fallback',
            reason_explicit_shorts_intent_required: 'Explicit Shorts intent required',
            reason_long_form_chat_fallback: 'Long-form chat fallback',
            reason_instructional_portrait_question: 'Instructional portrait question → chat',
            reason_text_request_priority: 'Text request takes priority → chat',
            reason_execution_required: 'No explicit media execution → chat',
            reason_central_media_intent: 'Central intent decision',
            reason_conservative_fallback: 'Conservative fallback'
        },
        de: {}
    };

    let copy = FALLBACK;
    let card = null;
    let tableBody = null;
    let state = null;
    let status = null;
    let refreshButton = null;
    let initialized = false;
    let retryTimer = null;
    let visibilityObserver = null;
    let liveTimer = null;
    let busy = false;
    let lastRefresh = 0;
    let filters = null;

    function visible() {
        if (!card || document.hidden || card.closest('[hidden]')) return false;
        const settings = card.closest('.settings');
        return !settings || settings.classList.contains('open');
    }

    function visibilityChanged() {
        clearTimeout(liveTimer);
        liveTimer = null;
        if (visible()) refresh({ quiet: true });
    }

    function observeVisibility() {
        visibilityObserver?.disconnect();
        if (typeof MutationObserver !== 'undefined') {
            visibilityObserver = new MutationObserver(visibilityChanged);
            for (let parent = card.parentElement; parent; parent = parent.parentElement) {
                visibilityObserver.observe(parent, { attributes: true, attributeFilter: ['hidden', 'class'] });
            }
        }
    }

    function locale() {
        const current = window.MLXI18n?.getLanguage?.()
            || window.MLXI18n?.getLocale?.()
            || navigator.language
            || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function t(key) {
        return copy[locale()]?.[key]
            || copy.en?.[key]
            || FALLBACK.en[key]
            || key;
    }

    async function loadTranslations() {
        try {
            const response = await fetch('/i18n/routing-observatory.json', {
                cache: 'no-cache'
            });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const payload = await response.json();
            if (payload?.de && payload?.en) copy = payload;
        } catch (error) {
            console.warn('[MLX Routing Observatory] translations unavailable', error);
        }
    }

    function routeLabel(target) {
        if (!target) return '—';
        const key = 'route_' + target;
        const translated = t(key);
        return translated === key ? target : translated;
    }

    function reasonLabel(reason) {
        if (!reason) return '—';
        const key = 'reason_' + reason;
        const translated = t(key);
        return translated === key ? reason : translated;
    }

    function formatConfidence(value) {
        if (value === null || value === undefined || value === '') return '—';
        const number = Number(value);
        if (!Number.isFinite(number)) return '—';
        return Math.round(number * 100) + ' %';
    }

    function confidenceClass(value) {
        if (value === null || value === undefined || value === '') return '';
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
        const copyBlock = el('div', 'routing-observatory-copy');
        copyBlock.append(
            el('h4', '', t('title')),
            el('p', '', t('description'))
        );

        refreshButton = el('button', 'routing-observatory-refresh', t('refresh'));
        refreshButton.type = 'button';
        refreshButton.addEventListener('click', () => refresh());
        header.append(copyBlock, refreshButton);

        state = el('div', 'routing-observatory-stats');
        status = el('div', 'routing-observatory-status', t('loading'));

        const scroller = el('div', 'routing-observatory-table-wrap');
        const table = el('table', 'routing-observatory-table');
        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        [
            t('time'),
            t('prompt'),
            t('finalRoute'),
            t('model'),
            t('confidence'),
            t('guardReason'),
            t('duration'),
            t('status'),
            t('feedback')
        ].forEach(label => headRow.appendChild(el('th', '', label)));
        thead.appendChild(headRow);
        tableBody = document.createElement('tbody');
        table.append(thead, tableBody);
        scroller.appendChild(table);

        filters = el('form', 'routing-observatory-filters');
        for (const [name, choices] of Object.entries({
            route: [...ROUTES, 'image_edit', 'video', 'video_animate'], source: ['chat', 'vision', 'media', 'agent', 'image', 'video', 'router'],
            success: ['true', 'false'], fallback: ['true', 'false'],
            model_role: ['chat', 'vision', 'vision_uncensored', 'agent', 'router', 'image', 'video']
        })) {
            const label = el('label', '', t('filter_' + name) + ' ');
            const select = el('select', '');
            select.name = name;
            const all = el('option', '', t('all'));
            all.value = '';
            select.appendChild(all);
            choices.forEach(value => {
                const option = el('option', '', value);
                option.value = value;
                select.appendChild(option);
            });
            select.addEventListener('change', () => { lastRefresh = 0; refresh(); });
            label.appendChild(select);
            filters.appendChild(label);
        }
        filters.addEventListener('submit', event => event.preventDefault());
        card.append(header, state, filters, status, scroller);
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

    function renderStats(summary) {
        if (!state) return;
        const percent = value => (100 * (value || 0)).toFixed(1) + ' %';
        state.replaceChildren(
            stat(t('total'), summary.total_events || 0),
            stat(t('fallbackRate'), percent(summary.fallback_rate)),
            stat(t('errorRate'), percent(summary.error_rate)),
            stat(t('medianTime'), summary.routing_p50_ms == null ? '—' : Number(summary.routing_p50_ms).toFixed(1) + ' ms')
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
        ROUTES.forEach(value => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = routeLabel(value);
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

    function renderRouteCell(target, className) {
        const cell = el('td', 'routing-route-cell ' + className);
        cell.appendChild(el('span', 'routing-route-badge', routeLabel(target)));
        return cell;
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

        const originalRoute = decision.original_target || decision.target;
        const finalCell = renderRouteCell(decision.target, 'is-final');
        if (decision.guarded && originalRoute !== decision.target) {
            finalCell.classList.add('is-changed');
            finalCell.appendChild(el('div', 'routing-route-change', '← ' + routeLabel(originalRoute)));
        }

        const confidenceCell = el(
            'td',
            'routing-confidence ' + confidenceClass(decision.confidence),
            formatConfidence(decision.confidence)
        );
        if (decision.confidence_source) {
            confidenceCell.appendChild(el(
                'div',
                'routing-confidence-source',
                decision.confidence_source
            ));
        }

        const reasonCell = el('td', 'routing-reason-cell');
        if (decision.guarded) {
            reasonCell.appendChild(el('span', 'routing-guard-badge', t('guarded')));
        }
        reasonCell.appendChild(el('div', 'routing-reason-text', reasonLabel(decision.reason)));

        const reasonMeta = [];
        if (decision.intent) reasonMeta.push(decision.intent);
        if (decision.duration_ms !== null && decision.duration_ms !== undefined) {
            reasonMeta.push(Number(decision.duration_ms).toFixed(0) + ' ms');
        }
        if (reasonMeta.length) {
            reasonCell.appendChild(el('div', 'routing-reason-meta', reasonMeta.join(' · ')));
        }

        const feedbackCell = el('td', 'routing-feedback-cell');
        renderFeedback(decision, feedbackCell);

        const details = el('details', 'routing-event-details');
        details.appendChild(el('summary', '', t('details')));
        details.appendChild(el('pre', '', JSON.stringify({
            phase: decision.phase, source: decision.source,
            intent_signals: decision.intent_signals, guards: decision.guards,
            attachment_types: decision.attachment_types, attachment_count: decision.attachment_count,
            fallback: decision.fallback, fallback_reason: decision.fallback_reason,
            runtime_wait_ms: decision.latency_ms?.runtime_wait,
            first_semantic_output_ms: decision.latency_ms?.first_semantic_output,
            total_ms: decision.latency_ms?.total,
            selected_tool: decision.selected_tool, router_model: decision.router_model,
            model: decision.model, model_role: decision.selected_model_role,
            request_id: decision.request_id, original_route: originalRoute,
            error_code: decision.error_code
        }, null, 2)));
        reasonCell.appendChild(details);
        const outcome = decision.success == null ? '—' : decision.success ? '✓' : '✕';
        row.append(
            el('td', '', new Date((decision.timestamp || decision.created_at) * 1000).toLocaleTimeString()),
            promptCell,
            finalCell,
            el('td', '', decision.model || decision.selected_model_role || '—'),
            confidenceCell,
            reasonCell,
            el('td', '', decision.latency_ms?.routing == null ? '—' : Number(decision.latency_ms.routing).toFixed(1) + ' ms'),
            el('td', '', outcome + ' ' + (decision.phase || '')),
            feedbackCell
        );
        return row;
    }

    function render(decisions, summary) {
        tableBody.replaceChildren();
        renderStats(summary);

        if (!decisions.length) {
            status.hidden = false;
            status.textContent = t('empty');
            return;
        }

        status.hidden = true;
        decisions.forEach(decision => tableBody.appendChild(renderRow(decision)));
    }

    async function refresh(options = {}) {
        if (!card || !tableBody || !visible() || busy) return;
        if (options.quiet && Date.now() - lastRefresh < 10000) return;
        busy = true;
        lastRefresh = Date.now();
        clearTimeout(liveTimer);
        if (!options.quiet) {
            refreshButton.disabled = true;
            status.hidden = false;
            status.textContent = t('loading');
        }

        try {
            const query = new URLSearchParams();
            for (const select of filters.querySelectorAll('select')) {
                if (select.value) query.set(select.name, select.value);
            }
            const [response, statsResponse] = await Promise.all([
                fetch(EVENTS_API + '?' + query + '&limit=50', { cache: 'no-store' }),
                fetch('/api/routing/stats?' + query, { cache: 'no-store' })
            ]);
            if (!response.ok || !statsResponse.ok) throw new Error('Routing API failed');
            const payload = await response.json();
            render(Array.isArray(payload.events) ? payload.events : [], await statsResponse.json());
        } catch (error) {
            console.error('[MLX Routing Observatory] load failed', error);
            status.hidden = false;
            status.textContent = t('loadError');
        } finally {
            busy = false;
            if (refreshButton) refreshButton.disabled = false;
            if (visible()) liveTimer = setTimeout(() => refresh({ quiet: true }), 10000);
        }
    }

    function initialize() {
        if (initialized) return true;
        const pane = document.querySelector('[data-settings-pane="functions"]');
        if (!pane) return false;

        initialized = true;
        buildCard(pane);
        observeVisibility();
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
        loadTranslations().finally(tryInitialize);
    }

    window.MLXRoutingObservatory = {
        refresh,
        initialize
    };

    document.addEventListener('visibilitychange', visibilityChanged);

    document.addEventListener('mlx-language-changed', () => {
        loadTranslations().finally(() => {
            if (!card) return;
            card.remove();
            card = null;
            tableBody = null;
            state = null;
            status = null;
            refreshButton = null;
            initialized = false;
            clearTimeout(retryTimer);
            clearTimeout(liveTimer);
            lastRefresh = 0;
            initialize();
        });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();