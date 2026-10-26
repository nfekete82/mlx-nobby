'use strict';

// Chat composer integration for the existing local EML queue.
// File bytes are never copied into chat history, prompt context, or localStorage.
window.MLXChatEml = (() => {
    const API = '/api/eml-anonymizer';
    const MAX_FILE = 30 * 1024 * 1024;
    const MAX_BATCH = 10000;
    const selected = [];
    const seen = new Set();
    let uploading = false;
    let queueVisible = false;
    let lastStatus = null;

    const el = id => document.getElementById(id);
    const t = (key, fallback, params = {}) => {
        let label = window.MLXI18n?.t('eml_chat.' + key, fallback) ?? fallback;
        for (const [name, value] of Object.entries(params)) {
            label = label.replaceAll('{' + name + '}', String(value));
        }
        return label;
    };
    const isEml = file => file && /\.eml$/i.test(String(file.name || ''));
    const wantsRedaction = prompt => /anonymisier|anonymis|anonymiz|pseudonymisier|pseudonymiz|redact|personenbezogene\s+daten\s+entfern/i.test(prompt || '');
    const fileKey = file => [file.webkitRelativePath || file.name, file.size, file.lastModified || 0].join('\u0000');

    function render(message = '') {
        const tray = el('emlChatTray');
        if (!tray) return;
        tray.hidden = !selected.length && !uploading && !queueVisible;
        const stage = el('emlChatSelected');
        if (stage) {
            stage.textContent = selected.length
                ? t('selected', '{count} EML-Dateien vorgemerkt', {count: selected.length})
                : t('no_selection', 'Keine neuen EML-Dateien vorgemerkt');
        }
        const note = el('emlChatStatus');
        if (note) {
            const c = lastStatus?.counts || {};
            const counts = queueVisible
                ? t('counts', 'Wartend {queued} · In Arbeit {active} · Zur Prüfung {review} · Fehler {failed}', {
                    queued: c.queued || 0, active: c.processing || 0,
                    review: c.review || 0, failed: c.failed || 0
                })
                : '';
            note.textContent = message || counts;
        }
        const remove = el('emlChatClear');
        if (remove) remove.disabled = uploading || !selected.length;
        const pick = el('emlChatAI');
        if (pick) pick.disabled = uploading;
    }

    function stageFiles(files) {
        if (uploading) return {accepted: 0, rejected: Array.from(files || []).length};
        let accepted = 0;
        let rejected = 0;
        for (const file of Array.from(files || [])) {
            if (!isEml(file) || file.size < 10 || file.size > MAX_FILE || selected.length >= MAX_BATCH) {
                rejected++;
                continue;
            }
            const key = fileKey(file);
            if (seen.has(key)) continue;
            seen.add(key);
            selected.push(file);
            accepted++;
        }
        if (accepted && el('input') && !el('input').value.trim()) {
            el('input').value = t('suggested_prompt', 'Anonymisiere diese EML-Dateien.');
            el('input').dispatchEvent(new Event('input', {bubbles: true}));
        }
        render(rejected ? t('rejected', '{count} Dateien übersprungen (nur gültige EML bis 30 MiB)', {count: rejected}) : '');
        return {accepted, rejected};
    }

    function clear() {
        if (uploading) return;
        selected.length = 0;
        seen.clear();
        render();
    }

    async function request(path, options) {
        const response = await fetch(API + path, {cache: 'no-store', ...options});
        if (!response.ok) {
            const details = await response.json().catch(() => ({}));
            throw new Error(details.detail || ('HTTP ' + response.status));
        }
        return response.json();
    }

    async function refresh() {
        try {
            lastStatus = await request('/status');
            const c = lastStatus.counts || {};
            queueVisible = queueVisible ||
                !!(c.queued || c.processing || c.review || c.failed);
            render();
            return lastStatus;
        } catch (_) {
            // Unavailable status should not interrupt ordinary chat.
            return null;
        }
    }

    async function submit(prompt) {
        if (!selected.length) return {handled: false};
        if (uploading) return {handled: true, success: false, error: t('busy', 'Der EML-Import läuft bereits.')};
        if (!wantsRedaction(prompt)) {
            return {handled: true, success: false, error: t('intent_required', 'Bitte ausdrücklich „Anonymisiere diese E-Mails“ schreiben.')};
        }
        uploading = true;
        let imported = 0;
        let error = '';
        const total = selected.length;
        try {
            // Upload one file per request: no large multipart requests and no
            // file bytes in the chat model's context.
            for (const file of [...selected]) {
                render(t('import_progress', 'EML-Import: {done}/{total}', {done: imported + 1, total}));
                const data = new FormData();
                data.append('file', file, file.name);
                await request('/upload', {method: 'POST', body: data});
                imported++;
                // Do not upload successfully stored EMLs twice after an error.
                selected.shift();
                seen.delete(fileKey(file));
            }
            const useLocalAI = !!el('emlChatAI')?.checked;
            await request('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({use_local_ai: useLocalAI})
            });
            queueVisible = true;
            return {
                handled: true, success: true, imported, total,
                useLocalAI
            };
        } catch (cause) {
            error = cause?.message || String(cause);
            return {
                handled: true, success: false, imported, total, error
            };
        } finally {
            uploading = false;
            render(error
                ? t('import_error', 'Import/Start fehlgeschlagen: {error}', {error})
                : '');
            if (imported) await refresh();
        }
    }

    function init() {
        el('emlChatFiles')?.addEventListener('change', event => {
            stageFiles(event.target.files);
            event.target.value = '';
        });
        el('emlChatFolder')?.addEventListener('change', event => {
            stageFiles(event.target.files);
            event.target.value = '';
        });
        el('emlChatPickFiles')?.addEventListener('click', () => el('emlChatFiles')?.click());
        el('emlChatPickFolder')?.addEventListener('click', () => el('emlChatFolder')?.click());
        el('emlChatClear')?.addEventListener('click', clear);
        refresh();
        setInterval(() => { if (queueVisible) refresh(); }, 5000);
    }

    return {
        init, stageFiles, hasStaged: () => selected.length > 0, submit, refresh,
        __test: {isEml, wantsRedaction, clear, pendingCount: () => selected.length}
    };
})();

window.MLXChatEml.init();
