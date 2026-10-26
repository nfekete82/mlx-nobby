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
        const text = String(prompt || '');
        if (/\b(?:ohne|keine|kein)\s+(?:lokale(?:s|r)?\s+)?(?:ki|qwen|llm|sprachmodell)\b/i.test(text)) return false;
        return /\b(?:mit|durch|per)\s+(?:der\s+)?(?:lokalen?\s+)?(?:ki|qwen|llm|sprachmodell)\b|\bki[- ]?(?:prüfung|erkennung)\b/i.test(text);
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

    async function submit(prompt, files) {
        const emls = Array.from(files || []).filter(item => item.kind === 'eml' && item.file);
        if (!emls.length) return {handled: false};
        if (busy) return {handled: true, success: false, imported: 0, error: 'EML-Import läuft bereits.'};
        if (!wantsRedaction(prompt)) {
            return {
                handled: true, success: false, imported: 0,
                error: window.MLXI18n?.t(
                    'eml_chat.intent_required',
                    'Please explicitly request anonymization of these EML files.'
                ) || 'Please explicitly request anonymization of these EML files.'
            };
        }

        busy = true;
        let imported = 0;
        const total = emls.length;
        const uploaded = [];
        progress(0, total);
        try {
            for (const item of emls) {
                const data = new FormData();
                data.append('file', item.file, item.name);
                await request('/upload', {method: 'POST', body: data});
                uploaded.push(item);
                imported++;
                progress(imported, total);
                if (uploaded.length === 20) {
                    window.MLXChatAttachments.removeAttachments(uploaded.splice(0));
                }
            }
            window.MLXChatAttachments.removeAttachments(uploaded.splice(0));
            const ai = useLocalAI(prompt);
            await request('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_local_ai: ai})
            });
            return {handled: true, success: true, imported, total, useLocalAI: ai};
        } catch (error) {
            return {
                handled: true, success: false, imported, total,
                error: String(error?.message || error)
            };
        } finally {
            if (uploaded.length) window.MLXChatAttachments.removeAttachments(uploaded);
            progress(null, total);
            busy = false;
        }
    }

    function initFolderPicker() {
        document.getElementById('chatFolderFiles')?.addEventListener('change', event => {
            const emls = Array.from(event.target.files || []).filter(file =>
                /\.eml$/i.test(file.name)
            );
            window.MLXChatAttachments?.addFiles(emls);
            event.target.value = '';
        });
        document.getElementById('chatPickFolder')?.addEventListener('click', () => {
            document.getElementById('chatFolderFiles')?.click();
        });
    }

    initFolderPicker();
    return {submit, isBusy: () => busy, __test: {wantsRedaction, useLocalAI}};
})();
