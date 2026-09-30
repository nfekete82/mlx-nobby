'use strict';

(() => {
    const SCRIPT_VERSION = '20260930-image-count-v4';
    const REQUEST_TTL_MS = 30 * 60 * 1000;
    const CHECK_DELAY_MS = 900;
    const PREWARM_TTL_MS = 60 * 1000;
    const MIN_IMAGE_COUNT = 1;
    const MAX_IMAGE_COUNT = 6;
    const IMAGE_QUALITIES = new Set([
        'fast',
        'standard',
        'quality'
    ]);
    const IMAGE_SIZES_BY_FORMAT = Object.freeze({
        landscape: Object.freeze({ width: 768, height: 432 }),
        portrait: Object.freeze({ width: 432, height: 768 }),
        square: Object.freeze({ width: 512, height: 512 }),
        landscape_4_3: Object.freeze({ width: 576, height: 432 }),
        portrait_3_4: Object.freeze({ width: 432, height: 576 })
    });

    const FALLBACK = {
        count_label: 'Count',
        count_1: '1 image',
        count_2: '2 images',
        count_3: '3 images',
        count_4: '4 images',
        count_5: '5 images',
        count_6: '6 images'
    };

    const pendingRequests = new Map();
    let dictionary = {};
    let pickerObserver = null;
    let checkTimer = null;
    let picker = null;
    let lastPrewarmKey = '';
    let lastPrewarmAt = 0;

    function t(key) {
        return dictionary[key] || FALLBACK[key] || key;
    }

    function normalizeImageCount(value) {
        const number = Math.round(Number(value));
        if (!Number.isFinite(number)) return MIN_IMAGE_COUNT;
        return Math.max(
            MIN_IMAGE_COUNT,
            Math.min(MAX_IMAGE_COUNT, number)
        );
    }

    function resolveLanguage(languageHint = '') {
        const hinted = String(languageHint || '').toLowerCase();
        if (hinted.startsWith('de')) return 'de';
        if (hinted.startsWith('en')) return 'en';

        try {
            const saved = String(
                window.localStorage?.getItem?.('mlx-nobby-language') || ''
            ).toLowerCase();
            if (saved === 'de' || saved === 'en') return saved;
        } catch (_error) {}

        const runtimeLanguage = String(
            window.MLXI18n?.getLanguage?.() ||
            window.MLXI18n?.getLocale?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase();
        return runtimeLanguage.startsWith('de') ? 'de' : 'en';
    }

    function newVariantGroupId() {
        return globalThis.crypto?.randomUUID?.() ||
            'image-count-group-' + Date.now().toString(16) + '-' +
            Math.random().toString(16).slice(2);
    }

    function artifactForMessage(message) {
        if (String(message?.tool_result?.tool || '') !== 'image_generate') {
            return null;
        }
        const artifact = message?.tool_result?.artifacts?.[0];
        return artifact?.image_id ? artifact : null;
    }

    function isInitialImageMessage(message) {
        if (message?.role !== 'assistant') return false;
        if (message?.image_variant_group_id) return false;

        const tool = String(message?.tool_result?.tool || '');
        const operation = String(message?.image_job?.operation || '');

        return tool === 'image_generate' ||
            operation === 'generate' ||
            Boolean(message?.image_generation_pending);
    }

    function mergeInitialImageWithGeneratedVariants(
        firstMessage,
        extraMessages,
        totalCount = 3
    ) {
        const count = normalizeImageCount(totalCount);
        const requiredExtras = count - 1;
        const extras = Array.isArray(extraMessages)
            ? extraMessages.slice(0, requiredExtras)
            : [];

        if (
            count < 2 ||
            !firstMessage ||
            extras.length !== requiredExtras
        ) {
            return null;
        }

        const groupId = String(
            extras.find(message => message?.image_variant_group_id)
                ?.image_variant_group_id ||
            newVariantGroupId()
        ).trim();

        if (!groupId) return null;

        firstMessage.image_variant_group_id = groupId;
        firstMessage.image_variant_index = 1;
        firstMessage.image_variant_count = count;

        extras.forEach((message, index) => {
            message.image_variant_group_id = groupId;
            message.image_variant_index = index + 2;
            message.image_variant_count = count;
        });

        return groupId;
    }

    async function loadDictionary(languageHint = '') {
        if (typeof document === 'undefined') return;
        const language = resolveLanguage(languageHint);

        try {
            const response = await fetch(
                '/i18n/image-count-picker.' + language + '.json',
                { cache: 'no-store' }
            );
            if (!response.ok) return;
            const data = await response.json();
            if (data && typeof data === 'object') dictionary = data;
        } catch (_error) {}
    }

    function updatePickerLabels() {
        if (!picker) return;
        picker.label.textContent = t('count_label');
        picker.select.setAttribute('aria-label', t('count_label'));

        for (
            let count = MIN_IMAGE_COUNT;
            count <= MAX_IMAGE_COUNT;
            count += 1
        ) {
            const option = picker.options.get(count);
            if (option) option.textContent = t('count_' + count);
        }
    }

    function latestImagePrompt(session = currentSession()) {
        const messages = Array.isArray(session?.messages)
            ? session.messages
            : [];
        for (let index = messages.length - 1; index >= 0; index -= 1) {
            const message = messages[index];
            if (message?.role !== 'user') continue;
            const content = typeof message?.content === 'string'
                ? message.content.trim()
                : '';
            if (content) return content.slice(0, 2000);
        }
        return String(
            document.getElementById?.('input')?.value || ''
        ).trim().slice(0, 2000);
    }

    function requestImagePrewarm() {
        const prompt = latestImagePrompt();
        if (!prompt || typeof fetch !== 'function') return false;

        const now = Date.now();
        if (
            prompt === lastPrewarmKey &&
            now - lastPrewarmAt < PREWARM_TTL_MS
        ) {
            return false;
        }
        lastPrewarmKey = prompt;
        lastPrewarmAt = now;

        fetch('/api/image/prewarm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: 'auto', prompt })
        }).catch(() => {});
        return true;
    }

    function syncPickerVisibility() {
        if (!picker) return;

        const modalOpen = !picker.modal.hidden;
        const imageMode = modalOpen && !picker.negativePromptField.hidden;
        const justOpened = modalOpen && !picker.wasModalOpen;

        if (justOpened) {
            picker.select.value = '1';
            if (imageMode) requestImagePrewarm();
        }
        picker.wasModalOpen = modalOpen;

        if (picker.field.hidden === imageMode) {
            picker.field.hidden = !imageMode;
        }
    }

    function currentSession() {
        return window.MLXChatSessions?.currentSession?.() || null;
    }

    function requestKey(session) {
        return String(session?.id || '');
    }

    function selectedImageBatchSettings() {
        const format = String(
            document.getElementById?.('mediaFormat')?.value || 'square'
        );
        const size =
            IMAGE_SIZES_BY_FORMAT[format] ||
            IMAGE_SIZES_BY_FORMAT.square;
        const qualityButtons =
            typeof document.querySelectorAll === 'function'
                ? [...document.querySelectorAll('[data-media-quality]')]
                : [];
        const selectedQuality = qualityButtons.find(button =>
            !button.hidden &&
            (
                button.classList?.contains?.('is-selected') ||
                button.getAttribute?.('aria-pressed') === 'true'
            )
        )?.dataset?.mediaQuality;
        const quality = IMAGE_QUALITIES.has(selectedQuality)
            ? selectedQuality
            : null;
        const negativePrompt = String(
            document.getElementById?.('imageNegativePrompt')?.value || ''
        ).trim();

        return {
            quality,
            format,
            width: size.width,
            height: size.height,
            negativePrompt
        };
    }

    function applyImageBatchSettings(artifact, settings) {
        const prepared = { ...(artifact || {}) };
        if (!settings || typeof settings !== 'object') {
            return prepared;
        }

        const width = Math.round(Number(settings.width));
        const height = Math.round(Number(settings.height));
        if (Number.isFinite(width) && width > 0) prepared.width = width;
        if (Number.isFinite(height) && height > 0) prepared.height = height;

        if (IMAGE_QUALITIES.has(settings.quality)) {
            prepared.quality = settings.quality;
        }

        if (Object.hasOwn(settings, 'negativePrompt')) {
            const negativePrompt = String(settings.negativePrompt || '').trim();
            if (negativePrompt) prepared.negative_prompt = negativePrompt;
            else delete prepared.negative_prompt;
        }

        return prepared;
    }

    function captureSelection() {
        if (!picker || picker.field.hidden) return;

        const session = currentSession();
        const count = normalizeImageCount(picker.select.value);
        if (!session || count <= 1) return;

        const key = requestKey(session);
        if (!key) return;

        pendingRequests.set(key, {
            baselineLength: Array.isArray(session.messages)
                ? session.messages.length
                : 0,
            count,
            settings: selectedImageBatchSettings(),
            createdAt: Date.now(),
            expanding: false
        });
        scheduleCheck(250);
    }

    function firstImageMessageAfter(session, baselineLength) {
        const messages = Array.isArray(session?.messages)
            ? session.messages
            : [];
        return messages
            .slice(Math.max(0, Number(baselineLength) || 0))
            .find(isInitialImageMessage) || null;
    }

    function terminalStatus(message) {
        return String(
            message?.tool_result?.status ||
            message?.image_job?.status ||
            ''
        );
    }

    function regeneratedMessageForArtifact(messages, artifact) {
        const artifactId = String(artifact?.artifact_id || '');
        if (!artifactId) return null;
        return (Array.isArray(messages) ? messages : []).find(message =>
            String(message?.image_regenerated_from_artifact_id || '') ===
                artifactId
        ) || null;
    }

    async function generateAdditionalImages(
        artifact,
        session,
        additionalCount,
        batchSettings = null
    ) {
        const regenerate =
            window.MLXImageRegenerate?.regenerateImageArtifact;
        if (typeof regenerate !== 'function') return [];

        const target = Math.max(
            0,
            Math.min(MAX_IMAGE_COUNT - 1, Number(additionalCount) || 0)
        );
        const extras = [];
        const regenerationArtifact =
            applyImageBatchSettings(artifact, batchSettings);

        for (let index = 0; index < target; index += 1) {
            const before = Array.isArray(session.messages)
                ? session.messages.length
                : 0;

            await regenerate(regenerationArtifact);

            const added = regeneratedMessageForArtifact(
                session.messages.slice(before),
                regenerationArtifact
            );
            if (!added) break;
            extras.push(added);
        }

        return extras;
    }

    async function maybeExpandActiveBatch() {
        const now = Date.now();
        for (const [key, request] of pendingRequests) {
            if (now - Number(request?.createdAt || 0) > REQUEST_TTL_MS) {
                pendingRequests.delete(key);
            }
        }

        const session = currentSession();
        const key = requestKey(session);
        const request = pendingRequests.get(key);
        if (!session || !request || request.expanding) return false;

        const firstMessage = firstImageMessageAfter(
            session,
            request.baselineLength
        );
        if (!firstMessage) return false;

        const status = terminalStatus(firstMessage);
        if (['failed', 'cancelled'].includes(status)) {
            pendingRequests.delete(key);
            return false;
        }

        const artifact = artifactForMessage(firstMessage);
        if (status !== 'completed' || !artifact) return false;

        request.expanding = true;

        try {
            const extras = await generateAdditionalImages(
                artifact,
                session,
                request.count - 1,
                request.settings
            );

            const groupId = mergeInitialImageWithGeneratedVariants(
                firstMessage,
                extras,
                request.count
            );

            if (!groupId) {
                console.warn('[image-count] Could not group image batch.');
                return false;
            }

            session.updated = Date.now();
            window.MLXChatSessions?.saveSessions?.();
            window.MLXChatRendering?.renderAll?.({
                contentUpdated: true
            });
            return true;
        } catch (error) {
            console.warn('[image-count] Image batch expansion failed:', error);
            return false;
        } finally {
            pendingRequests.delete(key);
        }
    }

    function scheduleCheck(delay = CHECK_DELAY_MS) {
        if (
            !pendingRequests.size ||
            checkTimer != null ||
            typeof setTimeout !== 'function'
        ) {
            return;
        }

        checkTimer = setTimeout(async () => {
            checkTimer = null;
            await maybeExpandActiveBatch();
            if (pendingRequests.size) scheduleCheck();
        }, delay);
    }

    function installPicker() {
        if (
            typeof document === 'undefined' ||
            typeof document.getElementById !== 'function' ||
            typeof document.createElement !== 'function'
        ) {
            return false;
        }

        const modal = document.getElementById('mediaQualityModal');
        const confirm = document.getElementById('mediaQualityModalConfirm');
        const negativePromptField = document.getElementById(
            'imageNegativePromptField'
        );

        if (!modal || !confirm || !negativePromptField) return false;
        if (document.getElementById('imageVariantCountField')) return true;

        const field = document.createElement('label');
        field.id = 'imageVariantCountField';
        field.className = 'media-duration-field';
        field.hidden = true;

        const label = document.createElement('span');
        const select = document.createElement('select');
        select.id = 'imageVariantCount';

        const options = new Map();
        for (
            let count = MIN_IMAGE_COUNT;
            count <= MAX_IMAGE_COUNT;
            count += 1
        ) {
            const option = document.createElement('option');
            option.value = String(count);
            option.selected = count === 1;
            options.set(count, option);
            select.appendChild(option);
        }

        field.append(label, select);
        negativePromptField.parentNode?.insertBefore(field, negativePromptField);

        picker = {
            modal,
            confirm,
            negativePromptField,
            field,
            label,
            select,
            options,
            wasModalOpen: false
        };

        updatePickerLabels();
        syncPickerVisibility();

        confirm.addEventListener('click', captureSelection, true);

        if (typeof MutationObserver !== 'undefined') {
            pickerObserver = new MutationObserver(syncPickerVisibility);
            pickerObserver.observe(modal, {
                attributes: true,
                subtree: true,
                attributeFilter: ['hidden', 'aria-hidden']
            });
        }

        return true;
    }

    async function refreshLanguage(event) {
        dictionary = {};
        await loadDictionary(event?.detail?.language || '');
        updatePickerLabels();
    }

    async function mount() {
        await loadDictionary();
        installPicker();
        scheduleCheck();
    }

    window.MLXImageCountPicker = {
        install: installPicker,
        check: maybeExpandActiveBatch,
        prewarm: requestImagePrewarm,
        __test: {
            applyImageBatchSettings,
            artifactForMessage,
            firstImageMessageAfter,
            isInitialImageMessage,
            latestImagePrompt,
            mergeInitialImageWithGeneratedVariants,
            normalizeImageCount,
            regeneratedMessageForArtifact,
            resolveLanguage,
            selectedImageBatchSettings,
            terminalStatus
        }
    };

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', mount, { once: true });
        } else {
            mount();
        }

        document.addEventListener?.('mlx-i18n-ready', refreshLanguage);
        document.addEventListener?.('mlx-language-changed', refreshLanguage);
    }

    window.addEventListener?.('beforeunload', () => {
        pickerObserver?.disconnect?.();
        if (checkTimer != null) clearTimeout(checkTimer);
        checkTimer = null;
    });
})();
