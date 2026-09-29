'use strict';

(() => {
    const CSS_ID = 'mlx-image-variant-gallery-css';
    const SCRIPT_VERSION = '20260929-gallery-v1';
    const ACTIVE_STATUSES = new Set([
        'queued',
        'loading',
        'running',
        'saving'
    ]);

    const FALLBACK = {
        title: '{count} image variants',
        variant: 'Variant {index}',
        use: 'Use',
        selected: 'Selected',
        more: 'Create {count} more',
        generating: 'Generating …',
        waiting: 'Waiting …',
        failed: 'Generation failed',
        cancelled: 'Cancelled',
        download: 'Download',
        progress: '{percent}% · Step {current}/{total}',
        progress_percent: '{percent}%',
        loading: 'Starting …'
    };

    let dictionary = {};
    let observer = null;
    let collapsing = false;

    function t(key, variables = {}) {
        let value = dictionary[key] || FALLBACK[key] || key;
        for (const [name, replacement] of Object.entries(variables)) {
            value = value.replaceAll(
                '{' + name + '}',
                String(replacement ?? '')
            );
        }
        return value;
    }

    function artifactForMessage(message) {
        const tool = String(message?.tool_result?.tool || '');
        if (!['image_generate', 'image_edit', 'image_upscale'].includes(tool)) {
            return null;
        }
        const artifact = message?.tool_result?.artifacts?.[0];
        return artifact?.image_id ? artifact : null;
    }

    function groupVariantMessages(session) {
        const groups = new Map();
        const messages = Array.isArray(session?.messages)
            ? session.messages
            : [];

        messages.forEach((message, index) => {
            const groupId = String(
                message?.image_variant_group_id || ''
            ).trim();
            const count = Number(message?.image_variant_count);

            if (
                !groupId ||
                message?.role !== 'assistant' ||
                !Number.isInteger(count) ||
                count < 2
            ) {
                return;
            }

            if (!groups.has(groupId)) {
                groups.set(groupId, {
                    id: groupId,
                    count,
                    firstIndex: index,
                    items: []
                });
            }

            const group = groups.get(groupId);
            group.count = Math.max(group.count, count);
            group.firstIndex = Math.min(group.firstIndex, index);
            group.items.push({ message, index });
        });

        return Array.from(groups.values())
            .filter(group => group.items.length >= 2)
            .map(group => ({
                ...group,
                items: group.items.sort((left, right) => {
                    const leftIndex = Number(
                        left.message?.image_variant_index
                    ) || left.index;
                    const rightIndex = Number(
                        right.message?.image_variant_index
                    ) || right.index;
                    return leftIndex - rightIndex;
                })
            }))
            .sort((left, right) => left.firstIndex - right.firstIndex);
    }

    function installCss() {
        if (
            typeof document === 'undefined' ||
            document.getElementById?.(CSS_ID) ||
            !document.head?.appendChild
        ) {
            return;
        }
        const link = document.createElement('link');
        link.id = CSS_ID;
        link.rel = 'stylesheet';
        link.href = '/assets/chat/image-variant-gallery.css?v=' +
            SCRIPT_VERSION;
        document.head.appendChild(link);
    }

    async function loadDictionary() {
        const language = String(
            window.MLXI18n?.getLanguage?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase().startsWith('de') ? 'de' : 'en';

        try {
            const response = await fetch(
                '/i18n/image-variant-gallery.' + language + '.json',
                { cache: 'no-store' }
            );
            if (!response.ok) return;
            const data = await response.json();
            if (data && typeof data === 'object') {
                dictionary = data;
            }
        } catch (_error) {}
    }

    function imageProgress(job) {
        if (!job) return 0;
        const explicit = Number(job.progress);
        if (Number.isFinite(explicit)) {
            return Math.max(
                0,
                Math.min(1, explicit > 1 ? explicit / 100 : explicit)
            );
        }
        const current = Number(job.current_step);
        const total = Number(job.total_steps);
        if (
            Number.isFinite(current) &&
            Number.isFinite(total) &&
            total > 0
        ) {
            return Math.max(0, Math.min(1, current / total));
        }
        return job.status === 'completed' ? 1 : 0;
    }

    function statusText(message) {
        const job = message?.image_job || {};
        const status = String(
            job.status || message?.tool_result?.status || 'queued'
        );

        if (status === 'failed') {
            return String(
                job.error ||
                message?.tool_result?.error ||
                t('failed')
            );
        }
        if (status === 'cancelled') return t('cancelled');
        if (status === 'queued') return t('waiting');
        return t('generating');
    }

    function enhanceOnlyMenu(artifact) {
        const controls = window.MLXChatGeneration
            ?.createImageUpscaleMenu?.(artifact);
        if (!controls) return null;

        if (controls.classList?.contains('image-upscale-menu')) {
            return controls;
        }

        return controls.querySelector?.('.image-upscale-menu') || null;
    }

    function selectArtifact(session, artifact) {
        if (!artifact?.artifact_id) return;
        session.workspace = {
            ...(session.workspace || {}),
            active_artifact_id: artifact.artifact_id
        };
        session.updated = Date.now();
        window.MLXChatSessions?.saveSessions?.();
        window.MLXChatRendering?.renderMessages?.({
            contentUpdated: false
        });
    }

    function renderCompletedSlot(item, session, slot) {
        const artifact = artifactForMessage(item.message);
        if (!artifact) return false;

        const imageUrl = '/api/mlx/images/' +
            encodeURIComponent(artifact.image_id);
        const previewLink = document.createElement('a');
        previewLink.className = 'image-variant-preview-link';
        previewLink.href = imageUrl;
        previewLink.target = '_blank';
        previewLink.rel = 'noopener';

        const image = document.createElement('img');
        image.className = 'image-variant-preview';
        image.src = imageUrl;
        image.alt = artifact.prompt || t('variant', {
            index: item.message.image_variant_index
        });
        image.loading = 'lazy';
        previewLink.appendChild(image);
        slot.appendChild(previewLink);

        const meta = document.createElement('div');
        meta.className = 'image-variant-meta';
        meta.textContent = [
            artifact.model,
            artifact.seed != null ? 'Seed ' + artifact.seed : ''
        ].filter(Boolean).join(' · ');
        if (meta.textContent) slot.appendChild(meta);

        const controls = document.createElement('div');
        controls.className = 'image-variant-actions';

        const download = document.createElement('a');
        download.className = 'message-action-btn';
        download.textContent = t('download');
        download.href = imageUrl + '?download=1';
        controls.appendChild(download);

        const use = document.createElement('button');
        use.type = 'button';
        use.className = 'message-action-btn';
        const selected =
            session?.workspace?.active_artifact_id === artifact.artifact_id;
        use.textContent = selected ? '✓ ' + t('selected') : t('use');
        if (selected) {
            slot.classList.add('is-selected');
            use.disabled = true;
        }
        use.addEventListener('click', () => {
            selectArtifact(session, artifact);
        });
        controls.appendChild(use);

        const enhance = enhanceOnlyMenu(artifact);
        if (enhance) controls.appendChild(enhance);

        slot.appendChild(controls);
        return true;
    }

    function renderPendingSlot(item, slot) {
        const job = item?.message?.image_job || {};
        const status = String(
            job.status || item?.message?.tool_result?.status || 'queued'
        );
        const active = ACTIVE_STATUSES.has(status);
        const progress = imageProgress(job);

        const placeholder = document.createElement('div');
        placeholder.className = 'image-variant-placeholder' +
            (active ? ' is-active' : '');

        const spinner = document.createElement('span');
        spinner.className = 'image-variant-spinner';
        spinner.setAttribute('aria-hidden', 'true');
        if (active) placeholder.appendChild(spinner);

        const statusNode = document.createElement('span');
        statusNode.className = 'image-variant-status';
        statusNode.textContent = statusText(item?.message);
        placeholder.appendChild(statusNode);

        if (active) {
            const progressTrack = document.createElement('div');
            progressTrack.className = 'image-variant-progress';
            const progressFill = document.createElement('div');
            progressFill.className = 'image-variant-progress-fill';
            progressFill.style.width = (progress * 100).toFixed(2) + '%';
            progressTrack.appendChild(progressFill);
            placeholder.appendChild(progressTrack);

            const current = Number(job.current_step);
            const total = Number(job.total_steps);
            const percent = Math.round(progress * 100);
            const progressText = document.createElement('small');
            progressText.className = 'image-variant-progress-text';
            progressText.textContent =
                Number.isFinite(current) &&
                Number.isFinite(total) &&
                current > 0 && total > 0
                    ? t('progress', { percent, current, total })
                    : t('progress_percent', { percent });
            placeholder.appendChild(progressText);
        }

        slot.appendChild(placeholder);
    }

    function renderSlot(item, session, index, count) {
        const slot = document.createElement('section');
        slot.className = 'image-variant-slot';
        slot.dataset.variantIndex = String(index);

        const heading = document.createElement('div');
        heading.className = 'image-variant-slot-title';
        heading.textContent = t('variant', { index }) +
            ' · ' + index + '/' + count;
        slot.appendChild(heading);

        if (!item || !renderCompletedSlot(item, session, slot)) {
            renderPendingSlot(item, slot);
        }
        return slot;
    }

    function buildGalleryArticle(group, session) {
        const article = document.createElement('article');
        article.className =
            'message assistant image-variant-gallery-message';
        article.dataset.variantGroupId = group.id;

        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = 'AI';

        const body = document.createElement('div');
        const author = document.createElement('div');
        author.className = 'message-author';
        author.textContent = 'MLX';

        const content = document.createElement('div');
        content.className = 'message-content';

        const gallery = document.createElement('section');
        gallery.className = 'image-variant-gallery';

        const header = document.createElement('div');
        header.className = 'image-variant-gallery-header';
        const title = document.createElement('strong');
        title.textContent = t('title', { count: group.count });
        const completedCount = group.items.filter(item =>
            Boolean(artifactForMessage(item.message))
        ).length;
        const counter = document.createElement('span');
        counter.textContent = completedCount + '/' + group.count;
        header.append(title, counter);
        gallery.appendChild(header);

        const grid = document.createElement('div');
        grid.className = 'image-variant-grid';

        const byIndex = new Map(group.items.map(item => [
            Number(item.message?.image_variant_index) || 0,
            item
        ]));
        for (let index = 1; index <= group.count; index += 1) {
            grid.appendChild(
                renderSlot(byIndex.get(index), session, index, group.count)
            );
        }
        gallery.appendChild(grid);

        const sourceArtifact = group.items
            .map(item => artifactForMessage(item.message))
            .find(Boolean);
        if (sourceArtifact) {
            const footer = document.createElement('div');
            footer.className = 'image-variant-gallery-footer';
            const more = document.createElement('button');
            more.type = 'button';
            more.className = 'message-action-btn';
            more.textContent = t('more', { count: group.count });
            more.addEventListener('click', async () => {
                more.disabled = true;
                const original = more.textContent;
                more.textContent = t('loading');
                const started = await window.MLXImageRegenerate
                    ?.generateImageVariants?.(sourceArtifact, group.count);
                if (!started && more.isConnected) {
                    more.disabled = false;
                    more.textContent = original;
                }
            });
            footer.appendChild(more);
            gallery.appendChild(footer);
        }

        content.appendChild(gallery);
        body.append(author, content);
        article.append(avatar, body);
        return article;
    }

    function collapseVariantGalleries() {
        if (collapsing || typeof document === 'undefined') return 0;
        const container = document.getElementById?.('messagesInner');
        const session = window.MLXChatSessions?.currentSession?.();
        if (!container || !session) return 0;

        if (container.querySelector?.('.image-variant-gallery-message')) {
            return 0;
        }

        const articles = Array.from(container.children || []).filter(node =>
            node?.matches?.('article.message')
        );
        if (articles.length !== session.messages.length) return 0;

        const groups = groupVariantMessages(session);
        if (!groups.length) return 0;

        collapsing = true;
        let collapsed = 0;
        try {
            for (const group of [...groups].reverse()) {
                const firstArticle = articles[group.firstIndex];
                if (!firstArticle?.parentNode) continue;

                const galleryArticle = buildGalleryArticle(group, session);
                firstArticle.parentNode.replaceChild(
                    galleryArticle,
                    firstArticle
                );

                for (const item of group.items) {
                    if (item.index === group.firstIndex) continue;
                    articles[item.index]?.remove?.();
                }
                collapsed += 1;
            }
        } finally {
            collapsing = false;
        }
        return collapsed;
    }

    function install() {
        const rendering = window.MLXChatRendering;
        if (!rendering || rendering.__imageVariantGalleryInstalled) {
            return false;
        }
        rendering.__imageVariantGalleryInstalled = true;
        installCss();

        const originalRenderMessages =
            rendering.renderMessages.bind(rendering);
        const originalRenderAll = rendering.renderAll.bind(rendering);

        rendering.renderMessages = (...args) => {
            const result = originalRenderMessages(...args);
            collapseVariantGalleries();
            return result;
        };
        rendering.renderAll = (...args) => {
            const result = originalRenderAll(...args);
            collapseVariantGalleries();
            return result;
        };

        const container = document.getElementById?.('messagesInner');
        if (container && typeof MutationObserver !== 'undefined') {
            observer = new MutationObserver(() => {
                if (collapsing) return;
                queueMicrotask(collapseVariantGalleries);
            });
            observer.observe(container, { childList: true });
        }

        loadDictionary().finally(() => {
            collapseVariantGalleries();
        });
        collapseVariantGalleries();
        return true;
    }

    window.MLXImageVariantGallery = {
        collapse: collapseVariantGalleries,
        install,
        __test: {
            artifactForMessage,
            groupVariantMessages,
            imageProgress,
            statusText
        }
    };

    install();

    document.addEventListener?.('mlx-language-changed', async () => {
        dictionary = {};
        await loadDictionary();
        window.MLXChatRendering?.renderMessages?.({
            contentUpdated: false
        });
    });
})();
