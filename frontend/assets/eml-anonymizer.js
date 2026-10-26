'use strict';
(() => {
    const $ = id => document.getElementById(id);
    const api = '/api/eml-anonymizer';
    const t = JSON.parse($('emlUiText').textContent);
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
            $('storage').textContent = total + t.storageUnit +
                (data.total_bytes / 1048576).toFixed(1) + t.storageSuffix;
            $('state').textContent = data.running
                ? t.running
                : t.paused;
            $('export').disabled = data.running || !data.completed;
            $('purge').disabled = data.running || !!c.processing;
            $('start').disabled = uploading;
            $('ai').disabled = data.running;
        } catch (error) { message(t.statusPrefix + error.message); }
    }
    async function addFiles(files) {
        if (uploading) return;
        const selected = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.eml'));
        if (!selected.length) { message(t.noFiles); return; }
        uploading = true;
        $('start').disabled = true;
        let errors = 0;
        for (let i = 0; i < selected.length; i++) {
            const data = new FormData();
            data.append('file', selected[i], selected[i].name);
            $('uploadInfo').textContent = t.uploadPrefix + (i + 1) + ' / ' + selected.length;
            try {
                const response = await fetch(api + '/upload', {method: 'POST', body: data});
                if (!response.ok) {
                    const result = await response.json().catch(() => ({}));
                    throw new Error(result.detail || t.uploadFailed);
                }
            } catch (error) {
                errors++;
                message(t.uploadError + (i + 1) + ': ' + error.message);
            }
            if (i % 10 === 0) await status();
        }
        uploading = false;
        $('uploadInfo').textContent = selected.length + t.uploadSummary +
            (selected.length - errors) + t.imported + errors + t.failed;
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
            message(t.started);
            await status();
        } catch (error) { message(error.message); }
    });
    $('pause').addEventListener('click', async () => {
        try { await request('/pause', {method:'POST'}); message(t.pauseRequested); await status(); }
        catch (error) { message(error.message); }
    });
    $('refresh').addEventListener('click', status);
    $('retry').addEventListener('click', async () => {
        try {
            const result = await request('/retry', {method:'POST'});
            message(result.requeued + t.retryMessage);
            await status();
        } catch (error) { message(error.message); }
    });
    $('export').addEventListener('click', () => {
        window.location.assign(api + '/export');
    });
    $('purge').addEventListener('click', async () => {
        if (!confirm(t.confirmPurge)) return;
        try { await request('/purge', {method:'POST'}); message(t.purged); await status(); }
        catch (error) { message(error.message); }
    });
    status();
    setInterval(status, 2000);
})();
