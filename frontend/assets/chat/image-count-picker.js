'use strict';

(() => {
    const SCRIPT_VERSION = '20260929-image-count-v1';
    const REQUEST_TTL_MS = 30 * 60 * 1000;
    const CHECK_DELAY_MS = 900;

    const FALLBACK = {
        count_label: 'Count',
        count_one: '1 image',
        count_three: '3 variants'
    };

    const pendingRequests = new Map();
    let dictionary = {};
    let pickerObserver = null;
    let checkTimer = null;
    let picker = null;

    function t(key) {
        return dictionary[key] || FALLBACK[key] || key;
    }

    function normalizeImageCount(value) {
        return Number(value) === 3 ? 3 : 1;
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

        if (!firstMessage || extras.length !== requiredExtras) {
            return null;
        }

        const groupId = String(
            extras.find(message => message?.image_variant_group_id)
                ?.image_variant_group_id || ''
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

    async function loadDictionary() {
        if (typeof document === 'undefined') return;
        const language = String(
            window.MLXI18n?.getLanguage?.() ||
            window.MLXI18n?.getLocale?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase().startsWith('de') ? 'de' : 'en';

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
        picker.one.textContent = t('count_one');
        picker.three.textContent = t('count_three');
    }

    function syncPickerVisibility() {
        if (!picker) return;

        const modalOpen = !picker.modal.hidden;
        const imageMode = modalOpen && !picker.negativePromptField.hidden;

        if (modalOpen && !picker.wasModalOpen) {
            picker.select.value = '1';
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

    function captureSelection() {
        if (!picker || picker.field.hidden) return;

        const session = currentSession();
        const count = normalizeImageCount(picker.select.value);
        if (!session || count !== 3) return;

        const key = requestKey(session);
        if (!key) return;

        pendingRequests.set(key, {
            baselineLength: Array.isArray(session.messages)
                ? session.messages.length
                : 0,
            count,
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

        const generator = window.MLXImageRegenerate?.generateImageVariants;
        if (typeof generator !== 'function') return false;

        request.expanding = true;
        const before = session.messages.length;

        try {
            await generator(artifact, request.count - 1);

            const extras = session.messages
                .slice(before)
                .filter(message => Boolean(message?.image_variant_group_id))
                .slice(0, request.count - 1);

            const groupId = mergeInitialImageWithGeneratedVariants(
                firstMessage,
                extras,
                request.count
            );

            if (!groupId) {
                console.warn('[image-count] Could not group initial variants.');
                return false;
            }

            session.updated = Date.now();
            window.MLXChatSessions?.saveSessions?.();
            window.MLXChatRendering?.renderAll?.({
                contentUpdated: true
            });
            return true;
        } catch (error) {
            console.warn('[image-count] Variant expansion failed:', error);
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

        const one = document.createElement('option');
        one.value = '1';
        one.selected = true;

        const three = document.createElement('option');
        three.value = '3';

        select.append(one, three);
        field.append(label, select);
        negativePromptField.parentNode?.insertBefore(field, negativePromptField);

        picker = {
            modal,
            confirm,
            negativePromptField,
            field,
            label,
            select,
            one,
            three,
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

    async function mount() {
        await loadDictionary();
        installPicker();
        scheduleCheck();
    }

    window.MLXImageCountPicker = {
        install: installPicker,
        check: maybeExpandActiveBatch,
        __test: {
            artifactForMessage,
            firstImageMessageAfter,
            isInitialImageMessage,
            mergeInitialImageWithGeneratedVariants,
            normalizeImageCount,
            terminalStatus
        }
    };

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', mount, { once: true });
        } else {
            mount();
        }

        document.addEventListener?.('mlx-language-changed', async () => {
            dictionary = {};
            await loadDictionary();
            updatePickerLabels();
        });
    }

    window.addEventListener?.('beforeunload', () => {
        pickerObserver?.disconnect?.();
        if (checkTimer != null) clearTimeout(checkTimer);
        checkTimer = null;
    });
})();
