'use strict';

// Existing local EML batch service, invoked by the ordinary chat attachments.
// EML bytes never enter model context, chat history or browser storage.
window.MLXChatEml = (() => {
    const API = '/api/eml-anonymizer';
    let busy = false;

    function wantsRedaction(prompt) {
        return /anonymis|anonymiz|pseudonymis|pseudonymiz|redact|personenbezogene\s+daten\s+entfern/i.test(prompt || '') &&
            !/\b(?:nicht|kein(?:e|en|er)?|ohne)\s+(?:die\s+)?(?:eml[- ]?)?(?:dateien\s+)?anonymis/i.test(prompt || '');
    }

    function useLocalAI(prompt) {
        const value = String(prompt || '');
        // Regular expression literals are logic, not untranslated UI strings.
        if (/\b(?:ohne|kein(?:e|en|er|es)?)\s+(?:(?:die|der|dem)\s+)?(?:lokal(?:e|en|er|es)?\s+)?(?:ki|qwen|llm|sprachmodell)\b/i.test(value)) {
            return false;
        }
        return /\b(?:mit|durch|per)\s+(?:(?:der|dem)\s+)?(?:lokal(?:e|en|er|es)?\s+)?(?:ki|qwen|llm|sprachmodell)\b|\bki[- ]?(?:prüfung|erkennung)\b/i.test(value);
    }

    async function request(path, options) {
        const response = await fetch(API + path, {cache: 'no-store', ...options});
        if (!response.ok) {
            const info = await response.json().catch(() => ({}));
            throw new Error(info.detail || ('HTTP ' + response.status));
        }
        return response.json();
    }

    function progress(done, total) {
        const indicator = document.getElementById('emlUploadStatus');
        if (!indicator) return;
        indicator.hidden = done === null;
        indicator.textContent = done === null
            ? ''
            : (window.MLXI18n?.t('eml_chat.import_progress', 'EML-Import: {done}/{total}') ||
                'EML-Import: {done}/{total}')
                .replaceAll('{done}', String(done))
                .replaceAll('{total}', String(total));
    }

    async function submit(prompt, files, onProgress = () => {}) {
        const emls = Array.from(files || []).filter(item => item.kind === 'eml' && item.file);
        if (!emls.length) return {handled: false};
        if (busy) return {handled: true, success: false, imported: 0, error: 'EML import already running.'};
        if (!wantsRedaction(prompt)) {
            return {
                handled: true, success: false, imported: 0,
                error: window.MLXI18n?.t(
                    'eml_chat.intent_required',
                    'Please explicitly request anonymization of these EML files.'
                ) || 'Please explicitly request anonymization of these EML files.'
            };
        }

        const batchId = window.crypto?.randomUUID?.().replaceAll('-', '');
        if (!/^[a-f0-9]{32}$/.test(batchId || '')) {
            return {handled: true, success: false, imported: 0,
                    error: 'Secure batch identifier is unavailable.'};
        }
        busy = true;
        let imported = 0;
        const total = emls.length;
        const uploaded = [];
        const localAI = useLocalAI(prompt);
        try {
            onProgress({phase: 'upload', imported, total});
            for (const item of emls) {
                const data = new FormData();
                data.append('file', item.file, item.name);
                data.append('batch_id', batchId);
                await request('/upload', {method: 'POST', body: data});
                uploaded.push(item);
                imported++;
                progress(imported, total);
                if (imported === total || imported % 5 === 0) {
                    onProgress({phase: 'upload', imported, total});
                }
                if (uploaded.length === 20) {
                    window.MLXChatAttachments.removeAttachments(uploaded.splice(0));
                }
            }
            window.MLXChatAttachments.removeAttachments(uploaded.splice(0));
            onProgress({phase: 'processing', imported, total, completed: 0, failed: 0});
            await request('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_local_ai: localAI})
            });

            // Poll only this batch, not totals from previously imported jobs.
            // The worker survives navigation and browser restarts, but progress
            // shown inside this message is live only while this tab stays open.
            for (;;) {
                const state = await request('/batch/' + batchId + '/status');
                const completed = state.completed || 0;
                const failed = state.failed || 0;
                onProgress({phase: 'processing', imported, total,
                            completed, failed, running: state.running});
                if (state.finished) {
                    return {
                        handled: true, success: true, imported, total,
                        completed, failed, batchId, useLocalAI: localAI,
                        finished: true,
                        downloadUrl: completed
                            ? '/api/eml-anonymizer/batch/' + batchId +
                              (total === 1 ? '/result' : '/export')
                            : ''
                    };
                }
                if (!state.running) {
                    return {handled: true, success: true, imported, total,
                            completed, failed, batchId, finished: false,
                            paused: true, useLocalAI: localAI};
                }
                await new Promise(resolve => setTimeout(resolve, 2000));
            }
        } catch (error) {
            return {
                handled: true, success: false, imported, total,
                error: String(error?.message || error),
                batchId: imported ? batchId : '',
                useLocalAI: localAI
            };
        } finally {
            if (uploaded.length) window.MLXChatAttachments.removeAttachments(uploaded);
            progress(null, total);
            busy = false;
        }
    }

    return {submit, wantsRedaction, isBusy: () => busy, __test: {wantsRedaction, useLocalAI}};
})();
