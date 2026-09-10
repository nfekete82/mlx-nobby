(function () {
    let loading = false;

    function norm(value) {
        return String(value || '').trim().toLowerCase();
    }

    function jobForModel(jobs, alias, repo) {
        const a = norm(alias);
        const r = norm(repo);
        return (jobs || []).find((job) => {
            const t = norm(job.target);
            return t && (t === a || t === r || t.includes(a) || (r && t.includes(r)));
        });
    }

    function makeBadge(text, classes) {
        const el = document.createElement('span');
        el.className = 'px-2.5 py-1 rounded-lg text-xs font-semibold border ' + classes;
        el.textContent = text;
        return el;
    }

    function addButton(parent, text, classes, fn, disabled, title) {
        const b = document.createElement('button');
        b.className = classes + ' disabled:opacity-40 rounded-xl px-3 py-2 text-sm font-semibold';
        b.textContent = text;
        b.disabled = !!disabled;
        if (title) b.title = title;
        if (fn && !disabled) b.addEventListener('click', fn);
        parent.appendChild(b);
    }

    function renderModel(model, cache, job) {
        const active = !!(model && model.active) || !!(cache && cache.active);
        const local = !!cache;
        const complete = cache ? cache.complete !== false : false;
        const running = job && job.status === 'running';
        const alias = (model && model.alias) || (cache && cache.alias) || '';
        const repo = (model && model.repo) || (cache && cache.repo) || job?.target || 'Unknown model';

        const card = document.createElement('div');
        let border = active ? 'border-emerald-700' : 'border-slate-800';
        if (running) border = 'border-blue-700';
        if (local && !complete) border = 'border-amber-700';
        card.className = 'bg-slate-950 border ' + border + ' rounded-2xl p-5';

        const head = document.createElement('div');
        head.className = 'flex items-start justify-between gap-4';
        const info = document.createElement('div');
        info.className = 'min-w-0';
        const title = document.createElement('div');
        title.className = 'text-lg font-semibold break-all';
        title.textContent = alias || repo.split('/').pop();
        info.appendChild(title);
        if (alias) {
            const repoEl = document.createElement('div');
            repoEl.className = 'text-xs text-slate-500 font-mono break-all mt-2';
            repoEl.textContent = repo;
            info.appendChild(repoEl);
        }

        const meta = document.createElement('div');
        meta.className = 'flex flex-wrap items-center gap-2 mt-3';
        if (model) {
            meta.appendChild(makeBadge(
                model.backend === 'vlm' ? (model.vision ? 'VLM · Vision' : 'VLM') : 'LM · Text',
                model.backend === 'vlm' ? 'bg-violet-950 text-violet-300 border-violet-900' : 'bg-slate-800 text-slate-300 border-slate-700'
            ));
            if (model.quantization) meta.appendChild(makeBadge(model.quantization, 'bg-amber-950 text-amber-300 border-amber-900'));
        }
        if (local) meta.appendChild(makeBadge(complete ? '✓ LOCAL' : '⚠ INCOMPLETE', complete ? 'bg-emerald-950 text-emerald-300 border-emerald-900' : 'bg-amber-950 text-amber-300 border-amber-900'));
        else meta.appendChild(makeBadge('Hugging Face', 'bg-blue-950 text-blue-300 border-blue-900'));
        if (cache && cache.size) meta.appendChild(makeBadge(cache.size, 'bg-slate-900 text-slate-300 border-slate-700'));
        info.appendChild(meta);
        head.appendChild(info);

        if (active) head.appendChild(makeBadge('● ACTIVE', 'bg-emerald-950 text-emerald-400 border-emerald-800'));
        else if (running) head.appendChild(makeBadge('⟳ DOWNLOAD', 'bg-blue-950 text-blue-400 border-blue-800'));
        card.appendChild(head);

        if (running) {
            const wrap = document.createElement('div');
            wrap.className = 'mt-4 h-2 bg-slate-800 rounded-full overflow-hidden';
            const bar = document.createElement('div');
            bar.className = 'h-full w-2/3 bg-blue-500 rounded-full animate-pulse';
            wrap.appendChild(bar);
            card.appendChild(wrap);
            const text = document.createElement('div');
            text.className = 'mt-2 text-xs text-blue-400';
            text.textContent = 'Download is running in the background…';
            card.appendChild(text);
        }

        if (cache && !complete) {
            const warning = document.createElement('div');
            warning.className = 'mt-3 text-xs text-amber-400';
            warning.textContent = (cache.incomplete_files || 0) + ' incomplete files' + (cache.incomplete_size ? ' · ' + cache.incomplete_size : '');
            card.appendChild(warning);
        }

        if (job && job.status === 'failed') {
            const err = document.createElement('div');
            err.className = 'mt-3 text-xs text-red-400';
            err.textContent = job.error || 'The last model job failed.';
            card.appendChild(err);
        }

        const actions = document.createElement('div');
        actions.className = 'mt-4 flex flex-wrap items-center gap-2';
        if (model && !active) addButton(actions, 'Start', 'model-btn bg-blue-700 hover:bg-blue-600', () => switchModel(alias), running);
        if (cache && !active && !complete) addButton(actions, '↻ Resume', 'retry-btn bg-amber-700 hover:bg-amber-600', () => retryDownload(alias || repo), running);
        if (cache && !active && complete) addButton(actions, 'Download again', 'redownload-btn bg-slate-800 hover:bg-blue-900 text-slate-300 hover:text-blue-300', () => redownloadModel(alias || repo, repo, cache.size), running);
        if (cache) addButton(actions, active ? 'Active model' : 'Delete cache', 'delete-cache-btn bg-slate-800 hover:bg-red-900 text-slate-300 hover:text-red-300', active ? null : () => deleteModelCache(alias || repo, repo, cache.size), active || running, active ? 'The active model cache cannot be deleted.' : '');
        if (model && !active) addButton(actions, 'Remove alias', 'remove-model-btn bg-slate-800 hover:bg-red-900 text-slate-300 hover:text-red-300', () => removeModelAlias(alias, repo), running);
        if (actions.children.length) card.appendChild(actions);
        return card;
    }

    async function loadModels() {
        if (loading) return;
        loading = true;
        const container = document.getElementById('models');
        const summary = document.getElementById('modelLibrarySummary');
        if (!container) { loading = false; return; }

        try {
            const response = await fetch('/api/mlx/model-library');
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const data = await response.json();
            const models = data.aliases?.models || [];
            const caches = data.cache?.models || [];
            const jobs = data.jobs?.jobs || [];
            const usedCache = new Set();
            const entries = [];

            for (const model of models) {
                const idx = caches.findIndex((c, i) => !usedCache.has(i) && (norm(c.alias) === norm(model.alias) || norm(c.repo) === norm(model.repo)));
                const cache = idx >= 0 ? caches[idx] : null;
                if (idx >= 0) usedCache.add(idx);
                entries.push({ model, cache, job: jobForModel(jobs, model.alias, model.repo) });
            }
            caches.forEach((cache, i) => {
                if (!usedCache.has(i)) entries.push({ model: null, cache, job: jobForModel(jobs, cache.alias, cache.repo) });
            });

            // Include running downloads that have not created a cache or alias entry yet.
            for (const job of jobs.filter(j => j.status === 'running')) {
                const exists = entries.some(e => e.job && e.job.id === job.id);
                if (!exists) entries.unshift({ model: null, cache: null, job });
            }

            entries.sort((a, b) => Number(!!(b.model?.active || b.cache?.active)) - Number(!!(a.model?.active || a.cache?.active)) || Number(b.job?.status === 'running') - Number(a.job?.status === 'running'));
            container.innerHTML = '';
            entries.forEach(e => container.appendChild(renderModel(e.model, e.cache, e.job)));
            if (!entries.length) container.textContent = 'No models available.';

            const active = entries.filter(e => e.model?.active || e.cache?.active).length;
            const running = jobs.filter(j => j.status === 'running').length;
            if (summary) summary.textContent = entries.length + ' models · ' + caches.length + ' local' + (active ? ' · ' + active + ' active' : '') + (running ? ' · ' + running + ' download' + (running === 1 ? '' : 's') : '');
        } catch (error) {
            container.textContent = 'Could not load model management.';
            if (summary) summary.textContent = 'Error';
        } finally {
            loading = false;
        }
    }

    window.MLXModels = { loadModels };
})();
