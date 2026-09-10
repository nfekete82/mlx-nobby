function knowledgeT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${name}}`,
            String(replacement ?? '')
        );
    }

    return value;
}

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

        target.textContent = knowledgeT('knowledge.loading', 'Loading…');

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
                            ${embeddingReady ? knowledgeT('knowledge.active', '● Active') : knowledgeT('knowledge.not_ready', '○ Not ready')}
                        </small>
                    </div>
                    <div class="knowledge-metric">
                        <span>${knowledgeT('knowledge.sources', 'Sources')}</span>
                        <strong>${sources.length}</strong>
                    </div>
                    <div class="knowledge-metric">
                        <span>${knowledgeT('knowledge.documents', 'Documents')}</span>
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
                    <span>${knowledgeT('knowledge.embedding_model', 'Embedding model')}</span>
                    <strong>${escapeHtml(embedding.model || knowledgeT('knowledge.unknown', 'Unknown'))}</strong>
                    <div class="settings-hint">
                        ${embedding.dimensions
            ? ' · ' + knowledgeT(
                'knowledge.dimensions',
                '{count} dimensions',
                { count: escapeHtml(embedding.dimensions) }
            )
            : ''}
                        ${embedding.backend ? ' · ' + escapeHtml(embedding.backend) : ''}
                    </div>
                </div>
            `;

            const sourceList = sources.length
                ? `
                    <section class="knowledge-sources">
                        <div class="knowledge-section-heading">
                            <strong>${knowledgeT('knowledge.sources', 'Sources')}</strong>
                            <span>${knowledgeT(
        'knowledge.indexed_count',
        '{count} indexed',
        { count: sources.length }
    )}</span>
                        </div>
                        <div class="knowledge-source-list">
                            ${sources.map(source => {
                                    const enabled =
                                        Number(source.enabled) === 1;

                                    const sourceId =
                                        escapeHtml(source.source_id || '');

                                    const indexedAt =
                                        source.last_indexed_at
                                            ? new Date(
                                                Number(source.last_indexed_at) * 1000
                                            ).toLocaleString('de-DE')
                                            : knowledgeT('knowledge.not_indexed', 'Not indexed yet');

                                    return `
                                        <div
                                            class="knowledge-source"
                                            data-knowledge-source="${sourceId}"
                                        >
                                            <div class="knowledge-source-main">
                                                <div class="knowledge-source-title">
                                                    <span
                                                        class="knowledge-source-state ${enabled ? 'ready' : 'inactive'}"
                                                    >
                                                        ${enabled ? '●' : '○'}
                                                    </span>

                                                    <strong>
                                                        ${escapeHtml(source.name || knowledgeT('knowledge.source', 'Source'))}
                                                    </strong>

                                                    <span class="settings-hint">
                                                        ${enabled ? knowledgeT('knowledge.active_label', 'Active') : knowledgeT('knowledge.inactive_label', 'Disabled')}
                                                    </span>
                                                </div>

                                                <div class="settings-hint knowledge-source-path">
                                                    ${escapeHtml(source.root_path || '')}
                                                </div>

                                                <div class="settings-hint">
                                                    ${knowledgeT('knowledge.last_indexed', 'Last indexed:')}
                                                    ${escapeHtml(indexedAt)}
                                                </div>
                                            </div>

                                            <div class="knowledge-source-actions">
                                                <button
                                                    class="settings-button"
                                                    type="button"
                                                    data-knowledge-action="reindex"
                                                    data-source-id="${sourceId}"
                                                >
                                                    ${knowledgeT('knowledge.reindex', 'Reindex')}
                                                </button>

                                                <button
                                                    class="settings-button"
                                                    type="button"
                                                    data-knowledge-action="${enabled ? 'disable' : 'enable'}"
                                                    data-source-id="${sourceId}"
                                                >
                                                    ${enabled ? knowledgeT('knowledge.disable', 'Disable') : knowledgeT('knowledge.enable', 'Enable')}
                                                </button>

                                                <button
                                                    class="settings-button danger"
                                                    type="button"
                                                    data-knowledge-action="delete"
                                                    data-source-id="${sourceId}"
                                                >
                                                    ${knowledgeT('notes.delete', 'Delete')}
                                                </button>
                                            </div>
                                        </div>
                                    `;
                                }).join('')}
                        </div>
                    </section>
                `
                : `
                    <div class="knowledge-empty">
                        ${knowledgeT(
                            'knowledge.no_sources',
                            'No sources indexed yet.'
                        )}
                    </div>
                `;

            target.innerHTML =
                cards +
                embeddingInfo +
                sourceList;

        } catch (error) {
            target.textContent =
                knowledgeT('knowledge.unavailable', 'Knowledge base unavailable:') + ' ' + error.message;
        }
    }

    async function manageSource(action, sourceId, button) {
        if (!action || !sourceId) return;

        if (
            action === 'delete' &&
            !window.confirm(
                knowledgeT(
                'knowledge.delete_confirm',
                'Really delete this knowledge source?\n\nThe index for this source will be permanently removed. The original files on the Mac will remain unchanged.'
            )
            )
        ) {
            return;
        }

        const labels = {
            enable: knowledgeT('knowledge.enabling', 'Enabling…'),
            disable: knowledgeT('knowledge.disabling', 'Disabling…'),
            reindex: knowledgeT('knowledge.reindexing', 'Reindexing…'),
            delete: knowledgeT('knowledge.deleting', 'Deleting…')
        };

        const originalText = button?.textContent || '';

        if (button) {
            button.disabled = true;
            button.textContent =
                labels[action] || knowledgeT('knowledge.please_wait', 'Please wait…');
        }

        try {
            const encodedId =
                encodeURIComponent(sourceId);

            const method =
                action === 'delete'
                    ? 'DELETE'
                    : 'POST';

            const suffix =
                action === 'delete'
                    ? ''
                    : '/' + action;

            await request(
                '/api/mlx/knowledge/sources/' +
                encodedId +
                suffix,
                {
                    method
                }
            );

            await loadStatus();
        } catch (error) {
            window.alert(
                knowledgeT('knowledge.manage_failed', 'Could not update the knowledge source:') + ' ' +
                error.message
            );

            if (button) {
                button.disabled = false;
                button.textContent = originalText;
            }
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
            result.textContent = knowledgeT('knowledge.folder_opened', 'Folder picker opened …');
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
                result.textContent = knowledgeT('knowledge.folder_selected', '✓ Folder selected');
            }
        } catch (error) {
            if (result) {
                result.textContent =
                    knowledgeT('knowledge.selection_failed', 'Selection failed:') + ' ' + error.message;
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
            if (result) result.textContent = knowledgeT('knowledge.path_required', 'Enter a path.');
            return;
        }

        if (result) result.textContent = knowledgeT('knowledge.reindexing', 'Reindexing…');

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
                    knowledgeT('knowledge.source_indexed', '✓ Source indexed successfully');
            }

            await loadStatus();

            console.log('[MLX nobby Knowledge]', data);
        } catch (error) {
            if (result) {
                result.textContent =
                    knowledgeT(
                    'knowledge.error',
                    'Error: {message}',
                    { message: error.message }
                );
            }
        }
    }

    async function searchKnowledge() {
        const query = $('knowledgeQuery')?.value.trim();
        const target = $('knowledgeResults');

        if (!query || !target) return;

        target.textContent = knowledgeT('knowledge.searching', 'Searching…');

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
                    knowledgeT('knowledge.no_matches', 'No matching chunks found.') +
                    '</div>';
                return;
            }

            target.innerHTML = results.map((item, index) => {
                const source =
                    item.source ||
                    item.path ||
                    item.name ||
                    knowledgeT('knowledge.source', 'Source');

                const score =
                    item.score ??
                    item.similarity ??
                    '';

                const text =
                    item.snippet ||
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
                knowledgeT('knowledge.search_failed', 'Search failed:') + ' ' + error.message;
        }
    }

    function init() {
        $('knowledgeSelectFolder')
            ?.addEventListener('click', selectKnowledgeFolder);

        $('knowledgeStatus')
            ?.addEventListener('click', event => {
                const button = event.target.closest(
                    '[data-knowledge-action][data-source-id]'
                );

                if (!button) return;

                manageSource(
                    button.dataset.knowledgeAction,
                    button.dataset.sourceId,
                    button
                );
            });

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

    document.addEventListener('mlx-language-changed', loadStatus);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
