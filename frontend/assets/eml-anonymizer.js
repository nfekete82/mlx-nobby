'use strict';
(() => {
    const $ = id => document.getElementById(id);
    const api = '/api/eml-anonymizer';
    let uploading = false;
    const message = text => { $('info').textContent = String(text); };
    async function request(path, options) {
        const response = await fetch(api + path, {cache: 'no-store', ...options});
        if (!response.ok) {
            let detail = response.statusText;
            try { detail = (await response.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return response.json();
    }
    async function status() {
        try {
            const data = await request('/status');
            const c = data.counts || {};
            for (const key of ['queued', 'processing', 'review', 'failed']) {
                $(key).textContent = c[key] || 0;
            }
            const total = Object.values(c).reduce((a, n) => a + n, 0);
            const done = (c.review || 0) + (c.failed || 0);
            $('progress').max = Math.max(1, total);
            $('progress').value = done;
            $('storage').textContent = total + ' E-Mails · ' +
                (data.total_bytes / 1048576).toFixed(1) + ' MiB importiert';
            $('state').textContent = data.running
                ? 'Verarbeitung läuft (immer nur eine E-Mail gleichzeitig)'
                : 'Pausiert / keine aktive Verarbeitung';
            $('export').disabled = data.running || !data.completed;
            $('purge').disabled = data.running || !!c.processing;
            $('start').disabled = uploading;
            $('ai').disabled = data.running;
        } catch (error) { message('Status: ' + error.message); }
    }
    async function addFiles(files) {
        if (uploading) return;
        const selected = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.eml'));
        if (!selected.length) { message('Keine EML-Dateien ausgewählt.'); return; }
        uploading = true;
        $('start').disabled = true;
        let errors = 0;
        for (let i = 0; i < selected.length; i++) {
            const data = new FormData();
            data.append('file', selected[i], selected[i].name);
            $('uploadInfo').textContent = 'Import: ' + (i + 1) + ' / ' + selected.length;
            try {
                const response = await fetch(api + '/upload', {method: 'POST', body: data});
                if (!response.ok) {
                    const result = await response.json().catch(() => ({}));
                    throw new Error(result.detail || 'Upload fehlgeschlagen');
                }
            } catch (error) {
                errors++;
                message('Importfehler bei Datei ' + (i + 1) + ': ' + error.message);
            }
            if (i % 10 === 0) await status();
        }
        uploading = false;
        $('uploadInfo').textContent = selected.length + ' Dateien geprüft, ' +
            (selected.length - errors) + ' importiert, ' + errors + ' fehlgeschlagen';
        $('files').value = '';
        $('folder').value = '';
        await status();
    }
    $('files').addEventListener('change', event => addFiles(event.target.files));
    $('folder').addEventListener('change', event => addFiles(event.target.files));
    const drop = $('drop');
    drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', event => {
        event.preventDefault(); drop.classList.remove('drag');
        addFiles(event.dataTransfer.files);
    });
    $('start').addEventListener('click', async () => {
        try {
            await request('/start', {method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({use_local_ai: $('ai').checked})});
            message('Warteschlange gestartet.');
            await status();
        } catch (error) { message(error.message); }
    });
    $('pause').addEventListener('click', async () => {
        try { await request('/pause', {method:'POST'}); message('Pausierung angefordert.'); await status(); }
        catch (error) { message(error.message); }
    });
    $('refresh').addEventListener('click', status);
    $('retry').addEventListener('click', async () => {
        try {
            const result = await request('/retry', {method:'POST'});
            message(result.requeued + ' fehlgeschlagene E-Mails erneut angestellt.');
            await status();
        } catch (error) { message(error.message); }
    });
    $('export').addEventListener('click', () => {
        window.location.assign(api + '/export');
    });
    $('purge').addEventListener('click', async () => {
        if (!confirm('Alle importierten Originale UND Ergebnisse unwiderruflich löschen?')) return;
        try { await request('/purge', {method:'POST'}); message('Lokale Daten gelöscht.'); await status(); }
        catch (error) { message(error.message); }
    });
    status();
    setInterval(status, 2000);
})();
