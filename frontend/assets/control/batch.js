(function () {
    const jobsContainer =
        document.getElementById('batchJobs');

    const createButton =
        document.getElementById('batchCreateButton');

    const refreshButton =
        document.getElementById('batchRefreshButton');

    const inputPath =
        document.getElementById('batchInputPath');

    const instruction =
        document.getElementById('batchInstruction');

    const fileType =
        document.getElementById('batchFileType');

    const chunkTokens =
        document.getElementById('batchChunkTokens');

    const fileInput =
        document.getElementById('batchFileInput');

    const fileButton =
        document.getElementById('batchFileButton');

    const uploadStatus =
        document.getElementById('batchUploadStatus');


    async function api(url, options = {}) {
        const response = await fetch(url, options);

        if (!response.ok) {
            const body = await response.text();

            throw new Error(body);
        }

        return response.json();
    }


    function statusLabel(status) {
        switch (status) {
            case 'queued':
                return 'Queued';

            case 'running':
                return 'Running';

            case 'completed':
                return 'Completed';

            case 'failed':
                return 'Error';

            default:
                return status || 'Unknown';
        }
    }


    function statusClasses(status) {
        switch (status) {
            case 'running':
                return 'bg-blue-950 text-blue-300 border-blue-900';

            case 'completed':
                return 'bg-emerald-950 text-emerald-300 border-emerald-900';

            case 'failed':
                return 'bg-red-950 text-red-300 border-red-900';

            default:
                return 'bg-slate-800 text-slate-300 border-slate-700';
        }
    }


    function fileName(path) {
        return String(path || '')
            .split('/')
            .filter(Boolean)
            .pop() || path;
    }


    function renderJobs(jobs) {
        jobsContainer.innerHTML = '';

        if (!jobs.length) {
            const empty =
                document.createElement('div');

            empty.className =
                'text-sm text-slate-500';

            empty.textContent =
                'No batch jobs available.';

            jobsContainer.appendChild(empty);

            return;
        }

        for (const job of jobs) {
            const card =
                document.createElement('div');

            card.className =
                'rounded-xl border border-slate-800 bg-slate-950/70 p-4';

            const header =
                document.createElement('div');

            header.className =
                'flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3';

            const info =
                document.createElement('div');

            info.className = 'min-w-0';

            const title =
                document.createElement('div');

            title.className =
                'font-semibold text-slate-100';

            title.textContent =
                fileName(job.input_path);

            const path =
                document.createElement('div');

            path.className =
                'text-xs text-slate-500 font-mono mt-1 break-all';

            path.textContent =
                job.input_path || '';

            const meta =
                document.createElement('div');

            meta.className =
                'flex flex-wrap gap-2 mt-3';

            const status =
                document.createElement('span');

            status.className =
                'px-2.5 py-1 rounded-lg border text-xs font-semibold ' +
                statusClasses(job.status);

            status.textContent =
                statusLabel(job.status);

            meta.appendChild(status);

            const type =
                document.createElement('span');

            type.className =
                'px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 text-xs';

            type.textContent =
                String(job.file_type || 'auto').toUpperCase();

            meta.appendChild(type);

            const tokens =
                document.createElement('span');

            tokens.className =
                'px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-800 text-slate-300 text-xs';

            tokens.textContent =
                String(
                    job.chunk_tokens ??
                    job.chunk_size ??
                    6000
                ) + ' Tokens';

            meta.appendChild(tokens);

            info.appendChild(title);
            info.appendChild(path);
            info.appendChild(meta);

            header.appendChild(info);

            const actions =
                document.createElement('div');

            actions.className =
                'flex items-center gap-2 shrink-0';

            if (
                job.status === 'queued' ||
                job.status === 'failed'
            ) {
                const start =
                    document.createElement('button');

                start.type = 'button';

                start.className =
                    'px-3 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-semibold';

                start.textContent =
                    job.status === 'failed'
                        ? 'Start again'
                        : 'Start';

                start.addEventListener(
                    'click',
                    () => startJob(job.id)
                );

                actions.appendChild(start);
            }

            if (job.status === 'running') {
                const pause =
                    document.createElement('button');

                pause.type = 'button';

                pause.className =
                    'px-3 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 text-white text-sm font-semibold';

                pause.textContent = 'Pause';

                pause.addEventListener(
                    'click',
                    () => controlJob(
                        job.id,
                        'pause'
                    )
                );

                actions.appendChild(pause);
            }

            if (job.status === 'paused') {
                const resume =
                    document.createElement('button');

                resume.type = 'button';

                resume.className =
                    'px-3 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-semibold';

                resume.textContent =
                    'Resume';

                resume.addEventListener(
                    'click',
                    () => controlJob(
                        job.id,
                        'resume'
                    )
                );

                actions.appendChild(resume);
            }

            if (
                job.status === 'queued' ||
                job.status === 'running' ||
                job.status === 'paused'
            ) {
                const cancel =
                    document.createElement('button');

                cancel.type = 'button';

                cancel.className =
                    'px-3 py-2 rounded-lg bg-red-950 hover:bg-red-900 border border-red-900 text-red-300 text-sm font-semibold';

                cancel.textContent =
                    'Cancel';

                cancel.addEventListener(
                    'click',
                    () => controlJob(
                        job.id,
                        'cancel'
                    )
                );

                actions.appendChild(cancel);
            }

            header.appendChild(actions);

            card.appendChild(header);

            const progressWrap =
                document.createElement('div');

            progressWrap.className = 'mt-4';

            const processed =
                Number(job.processed_chunks || 0);

            const total =
                Number(job.total_chunks || 0);

            const percent =
                total > 0
                    ? Math.min(
                        100,
                        Math.round(
                            processed / total * 100
                        )
                    )
                    : 0;

            const progressText =
                document.createElement('div');

            progressText.className =
                'flex items-center justify-between text-xs text-slate-400 mb-2';

            progressText.innerHTML =
                '<span>' +
                processed +
                ' / ' +
                (total || '–') +
                ' Chunks</span>' +
                '<span>' +
                percent +
                '%</span>';

            const bar =
                document.createElement('div');

            bar.className =
                'h-2 rounded-full bg-slate-800 overflow-hidden';

            const fill =
                document.createElement('div');

            fill.className =
                'h-full bg-blue-600 transition-all duration-300';

            fill.style.width =
                percent + '%';

            bar.appendChild(fill);

            progressWrap.appendChild(progressText);
            progressWrap.appendChild(bar);

            card.appendChild(progressWrap);

            if (job.output_path) {
                const output =
                    document.createElement('div');

                output.className =
                    'text-xs text-slate-500 font-mono mt-3 break-all';

                output.textContent =
                    'Output: ' +
                    job.output_path;

                card.appendChild(output);
            }

            if (job.error) {
                const error =
                    document.createElement('div');

                error.className =
                    'mt-3 rounded-lg border border-red-900 bg-red-950/40 text-red-300 text-sm p-3';

                error.textContent =
                    job.error;

                card.appendChild(error);
            }

            jobsContainer.appendChild(card);
        }
    }


    async function loadJobs() {
        try {
            const data =
                await api('/api/mlx/batch');

            renderJobs(
                Array.isArray(data.jobs)
                    ? data.jobs
                    : []
            );

        } catch (error) {
            console.error(error);

            jobsContainer.innerHTML =
                '<div class="text-sm text-red-400">' +
                'Could not load batch jobs.' +
                '</div>';
        }
    }


    function detectFileType(name) {
        const lower =
            String(name || '').toLowerCase();

        if (lower.endsWith('.sql')) {
            return 'sql';
        }

        if (lower.endsWith('.csv')) {
            return 'csv';
        }

        if (lower.endsWith('.json')) {
            return 'json';
        }

        if (
            lower.endsWith('.txt') ||
            lower.endsWith('.md') ||
            lower.endsWith('.log') ||
            lower.endsWith('.xml') ||
            lower.endsWith('.yml') ||
            lower.endsWith('.yaml')
        ) {
            return 'text';
        }

        return 'auto';
    }


    async function uploadFile(file) {
        if (!file) {
            return;
        }

        uploadStatus.textContent =
            'Uploading file…';

        uploadStatus.className =
            'text-xs text-blue-400 mt-2 min-h-[18px]';

        fileButton.disabled = true;

        const formData =
            new FormData();

        formData.append(
            'file',
            file
        );

        try {
            const response = await fetch(
                '/api/mlx/batch/upload',
                {
                    method: 'POST',
                    body: formData
                }
            );

            const data =
                await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail ||
                    'Upload failed'
                );
            }

            inputPath.value =
                data.path || '';

            fileType.value =
                detectFileType(
                    data.original_name || file.name
                );

            uploadStatus.textContent =
                '✓ ' +
                (data.original_name || file.name) +
                ' uploaded';

            uploadStatus.className =
                'text-xs text-emerald-400 mt-2 min-h-[18px]';

        } catch (error) {
            console.error(error);

            inputPath.value = '';

            uploadStatus.textContent =
                'Error: ' +
                error.message;

            uploadStatus.className =
                'text-xs text-red-400 mt-2 min-h-[18px]';

        } finally {
            fileButton.disabled = false;

            fileInput.value = '';
        }
    }


    async function createJob() {
        const path =
            inputPath.value.trim();

        const prompt =
            instruction.value.trim();

        if (!path) {
            alert('Select an input file.');
            inputPath.focus();
            return;
        }

        if (!prompt) {
            alert('Enter a transformation instruction.');
            instruction.focus();
            return;
        }

        createButton.disabled = true;
        createButton.textContent = 'Creating…';

        try {
            const created =
                await api(
                    '/api/mlx/batch',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type':
                                'application/json'
                        },
                        body: JSON.stringify({
                            input_path: path,
                            instruction: prompt,
                            file_type: fileType.value,
                            chunk_tokens:
                                Number(chunkTokens.value)
                        })
                    }
                );

            const jobId =
                created?.job?.id;

            if (!jobId) {
                throw new Error(
                    'The server response does not contain a job ID'
                );
            }

            await api(
                '/api/mlx/batch/' +
                encodeURIComponent(jobId) +
                '/start',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type':
                            'application/json'
                    },
                    body: '{}'
                }
            );

            instruction.value = '';

            await loadJobs();

        } catch (error) {
            console.error(error);

            alert(
                'Could not create the batch job:\n\n' +
                error.message
            );

        } finally {
            createButton.disabled = false;
            createButton.textContent =
                'Create batch job';
        }
    }


    async function controlJob(jobId, action) {
        if (
            action === 'cancel' &&
            !confirm('Cancel this batch job?')
        ) {
            return;
        }

        try {
            await api(
                '/api/mlx/batch/' +
                encodeURIComponent(jobId) +
                '/' +
                action,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type':
                            'application/json'
                    },
                    body: '{}'
                }
            );

            await loadJobs();

        } catch (error) {
            console.error(error);

            alert(
                'Batch action failed:\n\n' +
                error.message
            );
        }
    }


    async function startJob(jobId) {
        try {
            await api(
                '/api/mlx/batch/' +
                encodeURIComponent(jobId) +
                '/start',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type':
                            'application/json'
                    },
                    body: '{}'
                }
            );

            await loadJobs();

        } catch (error) {
            console.error(error);

            alert(
                'Could not start the batch job:\n\n' +
                error.message
            );
        }
    }


    function init() {
        if (
            !jobsContainer ||
            !createButton ||
            !refreshButton
        ) {
            return;
        }

        fileButton.addEventListener(
            'click',
            () => fileInput.click()
        );

        fileInput.addEventListener(
            'change',
            async event => {
                const file =
                    event.target.files?.[0];

                await uploadFile(file);
            }
        );

        createButton.addEventListener(
            'click',
            createJob
        );

        refreshButton.addEventListener(
            'click',
            loadJobs
        );

        window.MLXHistoryCleanup?.mount(document.getElementById('batchHistoryCleanup'), {
            kind: 'batch', onComplete: loadJobs,
            buttonClass: 'text-red-300 bg-slate-800 hover:bg-red-950 rounded-lg px-3 py-2 text-xs disabled:opacity-40',
        });

        loadJobs();

        setInterval(
            () => {
                loadJobs();
            },
            3000
        );
    }


    window.MLXBatchTransform = {
        init,
        loadJobs
    };
})();
