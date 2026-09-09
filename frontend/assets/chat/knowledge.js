(() => {
    const $ = id => document.getElementById(id);

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    async function request(path, options = {}) {
        const response = await fetch(path, options);

        let data = {};
        try {
            data = await response.json();
        } catch (_) {}

        if (!response.ok) {
            throw new Error(
                data.detail ||
                data.error ||
                `HTTP ${response.status}`
            );
        }

        return data;
    }

    async function loadStatus() {
        const target = $('knowledgeStatus');
        if (!target) return;

        target.textContent = 'Wird geladen…';

        try {
            const data = await request('/api/mlx/knowledge/status');

            const sources = Array.isArray(data.sources)
                ? data.sources
                : [];

            const documents = Number(data.documents ?? 0);
            const chunks = Number(data.chunks ?? 0);

            const mode =
                String(data.mode || 'unknown').toLowerCase() === 'hybrid'
                    ? 'Hybrid Retrieval'
                    : String(data.mode || 'Retrieval');

            const embedding = data.embedding || {};
            const embeddingReady =
                embedding.ok === true ||
                embedding.status === 'ready';

            const cards = `
                <div class="knowledge-metrics">
                    <div class="knowledge-metric">
                        <span>Retrieval</span>
                        <strong>${escapeHtml(mode)}</strong>
                        <small class="${embeddingReady ? 'ready' : 'inactive'}">
                            ${embeddingReady ? '● Aktiv' : '○ Nicht bereit'}
                        </small>
                    </div>
                    <div class="knowledge-metric">
                        <span>Quellen</span>
                        <strong>${sources.length}</strong>
                    </div>
                    <div class="knowledge-metric">
                        <span>Dokumente</span>
                        <strong>${documents}</strong>
                    </div>
                    <div class="knowledge-metric">
                        <span>Chunks</span>
                        <strong>${chunks}</strong>
                    </div>
                </div>
            `;

            const embeddingInfo = `
                <div class="knowledge-embedding">
                    <span>Embedding-Modell</span>
                    <strong>${escapeHtml(embedding.model || 'Unbekannt')}</strong>
                    <div class="settings-hint">
                        ${embedding.dimensions ? ' · ' + escapeHtml(embedding.dimensions) + ' Dimensionen' : ''}
                        ${embedding.backend ? ' · ' + escapeHtml(embedding.backend) : ''}
                    </div>
                </div>
            `;

            const sourceList = sources.length
                ? `
                    <section class="knowledge-sources">
                        <div class="knowledge-section-heading">
                            <strong>Quellen</strong>
                            <span>${sources.length} indexiert</span>
                        </div>
                        <div class="knowledge-source-list">
                            ${sources.map(source => `
                                <div class="knowledge-source">
                                    <strong>${escapeHtml(source.name || 'Quelle')}</strong>
                                    <div class="settings-hint">
                                        ${escapeHtml(source.root_path || '')}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </section>
                `
                : `
                    <div class="knowledge-empty">
                        Noch keine Quellen indexiert.
                    </div>
                `;

            target.innerHTML =
                cards +
                embeddingInfo +
                sourceList;

        } catch (error) {
            target.textContent =
                'Wissensbasis nicht erreichbar: ' + error.message;
        }
    }

    async function selectKnowledgeFolder() {
        const pathInput = $('knowledgePath');
        const nameInput = $('knowledgeName');
        const result = $('knowledgeIndexResult');
        const button = $('knowledgeSelectFolder');

        if (!pathInput || !button) return;

        button.disabled = true;

        if (result) {
            result.textContent = 'Ordnerauswahl geöffnet …';
        }

        try {
            const data = await request(
                '/api/mlx/knowledge/select-folder'
            );

            if (data.cancelled) {
                if (result) result.textContent = '';
                return;
            }

            if (data.path) {
                pathInput.value = data.path;
            }

            if (
                nameInput &&
                !nameInput.value.trim() &&
                data.name
            ) {
                nameInput.value = data.name;
            }

            if (result) {
                result.textContent = '✓ Ordner ausgewählt';
            }
        } catch (error) {
            if (result) {
                result.textContent =
                    'Auswahl fehlgeschlagen: ' + error.message;
            }
        } finally {
            button.disabled = false;
        }
    }

    async function indexSource() {
        const path = $('knowledgePath')?.value.trim();
        const name = $('knowledgeName')?.value.trim();
        const result = $('knowledgeIndexResult');

        if (!path) {
            if (result) result.textContent = 'Bitte einen Pfad angeben.';
            return;
        }

        if (result) result.textContent = 'Indexiere…';

        try {
            const data = await request(
                '/api/mlx/knowledge/sources',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        path,
                        name: name || null,
                        force: false
                    })
                }
            );

            if (result) {
                result.textContent =
                    '✓ Quelle erfolgreich indexiert';
            }

            await loadStatus();

            console.log('[NobbyMLX Knowledge]', data);
        } catch (error) {
            if (result) {
                result.textContent =
                    'Fehler: ' + error.message;
            }
        }
    }

    async function searchKnowledge() {
        const query = $('knowledgeQuery')?.value.trim();
        const target = $('knowledgeResults');

        if (!query || !target) return;

        target.textContent = 'Suche…';

        try {
            const data = await request(
                '/api/mlx/knowledge/search',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        query,
                        scope: null
                    })
                }
            );

            const results =
                data.results ||
                data.matches ||
                [];

            if (!results.length) {
                target.innerHTML =
                    '<div class="knowledge-empty">' +
                    'Keine passenden Chunks gefunden.' +
                    '</div>';
                return;
            }

            target.innerHTML = results.map((item, index) => {
                const source =
                    item.source ||
                    item.path ||
                    item.name ||
                    'Quelle';

                const score =
                    item.score ??
                    item.similarity ??
                    '';

                const text =
                    item.text ||
                    item.content ||
                    item.chunk ||
                    '';

                const scoreText =
                    score === ''
                        ? ''
                        : ' · Score ' +
                          Number(score).toFixed(3);

                return (
                    '<article class="knowledge-result">' +
                        '<div class="knowledge-result-heading"><strong>' +
                            (index + 1) + '. ' +
                            escapeHtml(source) +
                        '</strong>' +
                        '<span class="settings-hint">' +
                            escapeHtml(scoreText) +
                        '</span></div>' +
                        '<div class="knowledge-result-text">' +
                            escapeHtml(text).slice(0, 1200) +
                        '</div>' +
                    '</article>'
                );
            }).join('');
        } catch (error) {
            target.textContent =
                'Suche fehlgeschlagen: ' + error.message;
        }
    }

    function init() {
        $('knowledgeSelectFolder')
            ?.addEventListener('click', selectKnowledgeFolder);

        $('knowledgeIndex')
            ?.addEventListener('click', indexSource);

        $('knowledgeSearch')
            ?.addEventListener('click', searchKnowledge);

        $('knowledgeQuery')
            ?.addEventListener('keydown', event => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    searchKnowledge();
                }
            });

        loadStatus();
    }

    window.MLXKnowledge = { loadStatus };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
