(() => {
    'use strict';

    const state = {
        data: null,
        loading: false,
    };

    const FALLBACK = {
        en: {
            title: 'Context Inspector',
            description: 'Test which memories Nobby would inject for a specific user message. This diagnostic does not change memory usage counters.',
            query: 'User message',
            placeholder: 'e.g. Which model should I use for coding?',
            limit: 'Max. memories',
            inspect: 'Inspect context',
            inspecting: 'Inspecting …',
            modeHybrid: 'Hybrid retrieval',
            modeLexical: 'Lexical fallback',
            selected: '{count} selected',
            eligible: '{count} eligible',
            none: 'No memory would be injected for this message.',
            score: 'Score',
            semantic: 'Semantic',
            lexical: 'Lexical',
            importance: 'Importance',
            confidence: 'Confidence',
            recency: 'Recency',
            pinned: 'Pinned bonus',
            context: 'Injected context preview',
            error: 'Inspector error:',
        },
        de: {
            title: 'Context Inspector',
            description: 'Prüft, welche Memories Nobby für eine konkrete Nutzernachricht injizieren würde. Die Diagnose verändert keine Nutzungszähler.',
            query: 'Nutzernachricht',
            placeholder: 'z. B. Welches Modell soll ich fürs Coding nehmen?',
            limit: 'Max. Memories',
            inspect: 'Context prüfen',
            inspecting: 'Prüfe …',
            modeHybrid: 'Hybride Suche',
            modeLexical: 'Lexikalischer Fallback',
            selected: '{count} ausgewählt',
            eligible: '{count} relevant',
            none: 'Für diese Nachricht würde keine Memory injiziert.',
            score: 'Score',
            semantic: 'Semantisch',
            lexical: 'Lexikalisch',
            importance: 'Wichtigkeit',
            confidence: 'Konfidenz',
            recency: 'Aktualität',
            pinned: 'Pin-Bonus',
            context: 'Vorschau des injizierten Contexts',
            error: 'Inspector-Fehler:',
        },
    };

    let copy = FALLBACK;
    let rootObserver = null;

    const $ = id => document.getElementById(id);
    const language = () => (
        window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en'
    );
    const interpolate = (value, values = {}) => {
        let result = String(value || '');
        for (const [key, replacement] of Object.entries(values)) {
            result = result.replaceAll(`{${key}}`, String(replacement ?? ''));
        }
        return result;
    };
    const t = (key, values = {}) => interpolate(
        copy[language()]?.[key]
        || copy.en?.[key]
        || FALLBACK[language()]?.[key]
        || FALLBACK.en[key]
        || key,
        values
    );

    async function request(path) {
        const response = await fetch(path, { cache: 'no-store' });
        let data = {};
        try {
            data = await response.json();
        } catch (_) {}
        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }
        return data;
    }

    async function loadTranslations() {
        try {
            const response = await fetch('/i18n/memory-context-inspector.json', {
                cache: 'no-cache',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (payload?.de && payload?.en) copy = payload;
        } catch (error) {
            console.warn('[memory-context-inspector] translations unavailable', error);
        }
    }

    function injectStyles() {
        if ($('memoryContextInspectorStyles')) return;
        const style = document.createElement('style');
        style.id = 'memoryContextInspectorStyles';
        style.textContent = `
            .memory-context-inspector{margin:0 0 16px;padding:13px;border:1px solid rgba(127,127,127,.22);border-radius:12px;background:rgba(127,127,127,.035);display:grid;gap:12px}
            .memory-context-inspector-copy{display:grid;gap:4px}
            .memory-context-inspector-copy small{color:var(--muted,#7d8794);line-height:1.45}
            .memory-context-inspector-form{display:grid;grid-template-columns:minmax(0,1fr) 120px auto;gap:10px;align-items:end}
            .memory-context-inspector-field{display:grid;gap:5px;font-size:.78rem;color:var(--muted,#7d8794)}
            .memory-context-inspector-field textarea,.memory-context-inspector-field select{width:100%;box-sizing:border-box}
            .memory-context-inspector-field textarea{min-height:70px;resize:vertical}
            .memory-context-inspector-meta{display:flex;gap:7px;flex-wrap:wrap;color:var(--muted,#7d8794);font-size:.76rem}
            .memory-context-inspector-pill{padding:3px 7px;border:1px solid rgba(127,127,127,.18);border-radius:999px}
            .memory-context-inspector-results{display:grid;gap:8px}
            .memory-context-inspector-result{display:grid;gap:7px;padding:10px;border-radius:9px;background:rgba(127,127,127,.055)}
            .memory-context-inspector-result-head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
            .memory-context-inspector-result-text{font-size:.84rem;line-height:1.45}
            .memory-context-inspector-score{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
            .memory-context-inspector-breakdown{display:flex;gap:6px;flex-wrap:wrap;color:var(--muted,#7d8794);font-size:.72rem}
            .memory-context-inspector-breakdown span{padding:2px 6px;border-radius:999px;background:rgba(127,127,127,.08)}
            .memory-context-inspector-context{font-size:.76rem;color:var(--muted,#7d8794)}
            .memory-context-inspector-context pre{white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;padding:10px;border-radius:8px;background:rgba(127,127,127,.06);color:var(--text,inherit)}
            .memory-context-inspector-empty{padding:14px 4px;text-align:center;color:var(--muted,#7d8794);font-size:.82rem}
            @media(max-width:760px){.memory-context-inspector-form{grid-template-columns:1fr}.memory-context-inspector-form button{justify-self:start}}
        `;
        document.head.appendChild(style);
    }

    function ensureUi() {
        if ($('memoryContextInspector')) return $('memoryContextInspector');
        const summary = $('memoryManagerSummary');
        if (!summary) return null;

        injectStyles();
        const root = document.createElement('section');
        root.id = 'memoryContextInspector';
        root.className = 'memory-context-inspector';
        root.innerHTML = `
            <div class="memory-context-inspector-copy">
                <strong id="memoryContextInspectorTitle"></strong>
                <small id="memoryContextInspectorDescription"></small>
            </div>
            <div class="memory-context-inspector-form">
                <label class="memory-context-inspector-field">
                    <span id="memoryContextInspectorQueryLabel"></span>
                    <textarea id="memoryContextInspectorQuery" rows="2" maxlength="4000"></textarea>
                </label>
                <label class="memory-context-inspector-field">
                    <span id="memoryContextInspectorLimitLabel"></span>
                    <select id="memoryContextInspectorLimit">
                        <option value="3">3</option>
                        <option value="6" selected>6</option>
                        <option value="12">12</option>
                    </select>
                </label>
                <button id="memoryContextInspectorRun" class="settings-button" type="button"></button>
            </div>
            <div id="memoryContextInspectorMeta" class="memory-context-inspector-meta"></div>
            <div id="memoryContextInspectorResults" class="memory-context-inspector-results"></div>
            <details id="memoryContextInspectorContext" class="memory-context-inspector-context" hidden>
                <summary id="memoryContextInspectorContextLabel"></summary>
                <pre id="memoryContextInspectorContextText"></pre>
            </details>
        `;

        const consolidation = $('memoryManagerConsolidation');
        if (consolidation) consolidation.after(root);
        else summary.after(root);

        $('memoryContextInspectorRun').addEventListener('click', () => inspect());
        $('memoryContextInspectorQuery').addEventListener('keydown', event => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                inspect();
            }
        });
        render();
        return root;
    }

    function pill(text) {
        const node = document.createElement('span');
        node.className = 'memory-context-inspector-pill';
        node.textContent = text;
        return node;
    }

    function formatMetric(value) {
        if (value == null || !Number.isFinite(Number(value))) return '—';
        return Number(value).toFixed(3);
    }

    function renderMeta() {
        const target = $('memoryContextInspectorMeta');
        if (!target) return;
        target.replaceChildren();
        const data = state.data;
        if (!data) return;
        target.append(
            pill(data.mode === 'hybrid' ? t('modeHybrid') : t('modeLexical')),
            pill(t('selected', { count: data.selected?.length || 0 })),
            pill(t('eligible', { count: data.eligible_count || 0 }))
        );
    }

    function resultCard(entry) {
        const card = document.createElement('article');
        card.className = 'memory-context-inspector-result';

        const head = document.createElement('div');
        head.className = 'memory-context-inspector-result-head';
        const text = document.createElement('div');
        text.className = 'memory-context-inspector-result-text';
        text.textContent = entry.memory?.text || '—';
        const score = document.createElement('span');
        score.className = 'memory-context-inspector-score';
        score.textContent = `${t('score')}: ${formatMetric(entry.score)}`;
        head.append(text, score);

        const breakdown = document.createElement('div');
        breakdown.className = 'memory-context-inspector-breakdown';
        const metrics = [
            [t('semantic'), entry.semantic],
            [t('lexical'), entry.lexical],
            [t('importance'), entry.importance],
            [t('confidence'), entry.confidence],
            [t('recency'), entry.recency],
        ];
        if (Number(entry.pinned_bonus || 0) > 0) {
            metrics.push([t('pinned'), entry.pinned_bonus]);
        }
        for (const [label, value] of metrics) {
            const item = document.createElement('span');
            item.textContent = `${label}: ${formatMetric(value)}`;
            breakdown.appendChild(item);
        }

        card.append(head, breakdown);
        return card;
    }

    function renderResults() {
        const target = $('memoryContextInspectorResults');
        const details = $('memoryContextInspectorContext');
        if (!target || !details) return;
        target.replaceChildren();
        const data = state.data;
        if (!data) {
            details.hidden = true;
            return;
        }

        const selected = Array.isArray(data.selected) ? data.selected : [];
        if (!selected.length) {
            const empty = document.createElement('div');
            empty.className = 'memory-context-inspector-empty';
            empty.textContent = t('none');
            target.appendChild(empty);
        } else {
            selected.forEach(entry => target.appendChild(resultCard(entry)));
        }

        details.hidden = !data.context;
        $('memoryContextInspectorContextLabel').textContent = t('context');
        $('memoryContextInspectorContextText').textContent = data.context || '';
    }

    function render() {
        if (!$('memoryContextInspector')) return;
        $('memoryContextInspectorTitle').textContent = t('title');
        $('memoryContextInspectorDescription').textContent = t('description');
        $('memoryContextInspectorQueryLabel').textContent = t('query');
        $('memoryContextInspectorQuery').placeholder = t('placeholder');
        $('memoryContextInspectorLimitLabel').textContent = t('limit');
        const run = $('memoryContextInspectorRun');
        run.textContent = state.loading ? t('inspecting') : t('inspect');
        run.disabled = state.loading;
        renderMeta();
        renderResults();
    }

    async function inspect(queryOverride) {
        const root = ensureUi();
        if (!root || state.loading) return null;
        const input = $('memoryContextInspectorQuery');
        if (queryOverride != null) input.value = String(queryOverride);
        const query = String(input.value || '').trim();
        if (!query) {
            input.focus();
            return null;
        }

        state.loading = true;
        render();
        try {
            const limit = Number($('memoryContextInspectorLimit').value || 6);
            const params = new URLSearchParams({
                query,
                limit: String(limit),
            });
            state.data = await request(`/api/mlx/memory/inspect?${params}`);
            render();
            return state.data;
        } catch (error) {
            state.data = null;
            render();
            const target = $('memoryContextInspectorResults');
            if (target) {
                const message = document.createElement('div');
                message.className = 'memory-context-inspector-empty';
                message.textContent = `${t('error')} ${error.message}`;
                target.replaceChildren(message);
            }
            return null;
        } finally {
            state.loading = false;
            render();
        }
    }

    function initWhenReady() {
        if (ensureUi()) return;
        if (!document.body || typeof MutationObserver === 'undefined') return;
        rootObserver = new MutationObserver(() => {
            if (!ensureUi()) return;
            rootObserver.disconnect();
            rootObserver = null;
        });
        rootObserver.observe(document.body, { childList: true, subtree: true });
    }

    async function init() {
        await loadTranslations();
        initWhenReady();
        render();
    }

    document.addEventListener('mlx-language-changed', render);
    window.MLXMemoryInspector = {
        inspect,
        getLastResult: () => state.data,
    };
    init();
})();
