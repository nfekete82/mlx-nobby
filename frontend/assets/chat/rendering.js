(function () {

    function rt(key, fallback = '', variables = {}) {
        let value = window.MLXI18n?.t(
            `rendering.${key}`,
            fallback
        ) ?? fallback;

        Object.entries(variables).forEach(([name, replacement]) => {
            value = value.replaceAll(
                `{${name}}`,
                String(replacement ?? '')
            );
        });

        return value;
    }

    let state;
    let currentSession;
    let isGenerating;
    let selectSession;
    let renameSession;
    let deleteSession;
    let updateContext;
    let startEditMessage;
    let regenerateLastAnswer;

    const messagesInner = document.getElementById('messagesInner');

    function configure(options) {
        state = options.state;
        currentSession = options.currentSession;
        isGenerating = options.isGenerating;
        selectSession = options.selectSession;
        renameSession = options.renameSession;
        deleteSession = options.deleteSession;
        updateContext = options.updateContext;
        startEditMessage = options.startEditMessage;
        regenerateLastAnswer = options.regenerateLastAnswer;
    }

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
}


function renderSidebar() {
    const list =
        document.getElementById('chatList');

    list.innerHTML = '';

    for (const session of state.sessions) {

        const wrap =
            document.createElement('div');

        wrap.className =
            'chat-entry-wrap';

        const entry =
            document.createElement('div');

        entry.className =
            'chat-entry' +
            (session.id === state.activeId
                ? ' active'
                : '');

        entry.textContent =
            session.title || rt('new_chat', 'New chat');

        entry.title =
            session.title || rt('new_chat', 'New chat');

        entry.addEventListener(
            'click',
            () => {
                selectSession(session.id);
            }
        );

        const menuButton =
            document.createElement('button');

        menuButton.className =
            'chat-menu-button';

        menuButton.textContent = '⋯';

        const menu =
            document.createElement('div');

        menu.className =
            'chat-menu';

        const rename =
            document.createElement('button');

        rename.className =
            'chat-menu-item';

        rename.textContent =
            'Umbenennen';

        rename.addEventListener(
            'click',
            event => {
                event.stopPropagation();

                renameSession(
                    session.id
                );
            }
        );

        const remove =
            document.createElement('button');

        remove.className =
            'chat-menu-item danger';

        remove.textContent =
            rt('delete', 'Delete');

        remove.addEventListener(
            'click',
            event => {
                event.stopPropagation();

                deleteSession(
                    session.id
                );
            }
        );

        menuButton.addEventListener(
            'click',
            event => {
                event.stopPropagation();

                document
                    .querySelectorAll(
                        '.chat-menu.open'
                    )
                    .forEach(other => {
                        if (other !== menu) {
                            other.classList.remove(
                                'open'
                            );
                        }
                    });

                menu.classList.toggle(
                    'open'
                );
            }
        );

        menu.appendChild(rename);
        menu.appendChild(remove);

        wrap.appendChild(entry);
        wrap.appendChild(menuButton);
        wrap.appendChild(menu);

        list.appendChild(wrap);
    }
}


function markdownHtml(text) {
    const html = marked.parse(text || '');

    return DOMPurify.sanitize(html);
}


function enhanceCodeBlocks(container) {
    container.querySelectorAll(
        'pre code'
    ).forEach(code => {
        try {
            hljs.highlightElement(code);
        } catch {}

        const pre = code.parentElement;

        if (
            pre.querySelector('.copy-code')
        ) {
            return;
        }

        const button =
            document.createElement('button');

        button.className = 'copy-code';
        button.textContent = 'Kopieren';

        button.addEventListener(
            'click',
            async () => {
                await navigator.clipboard.writeText(
                    code.textContent
                );

                button.textContent = 'Kopiert';

                setTimeout(() => {
                    button.textContent = 'Kopieren';
                }, 1200);
            }
        );

        pre.appendChild(button);
    });
}



function renderToolCard(message) {
    const result = message?.tool_result;

    if (!result) {
        return null;
    }

    const card = document.createElement('div');
    card.className = 'tool-card';

    const header = document.createElement('div');
    header.className = 'tool-card-header';

    const toolNames = {
        web_search: rt('web_search', 'Web search'),
        model_list: rt('models', 'Models'),
        model_switch: rt('model_switch', 'Model switch'),
        model_restart: rt('mlx_restart', 'Restart MLX'),
        system_status: rt('system_status', 'System status'),
        batch_status: rt('file_jobs', 'File jobs'),
        logs_query: 'Logs',
        pii_audit: 'PII-Audit',
        thinking_on: 'Thinking',
        thinking_off: 'Thinking',
        image_generate: rt('image_generation', 'Image generation'),
        knowledge_search: rt('knowledge_base', 'Knowledge base')
    };

    header.textContent =
        toolNames[result.tool] ||
        result.tool ||
        'Tool';

    const status = document.createElement('span');
    status.className = 'tool-card-status';

    if (result.status === 'completed') {
        status.textContent = '✓';
    } else if (result.status === 'failed') {
        status.textContent = rt('error', 'Error');
    } else if (result.status) {
        status.textContent = result.status;
    }

    header.appendChild(status);
    card.appendChild(header);

    return card;
}

function agentStepLabel(step) {
    const action =
        String(step?.action || '');

    const query =
        String(step?.query || '');

    const result = step?.result || {};
    const summary =
        result.summary ||
        result.apply_result?.summary ||
        {};
    const fileCount = Number(summary.files || 0);

    if (action === 'shell_read') {
        if (/docker\s+ps/i.test(query)) {
            return rt('check_docker', 'Check Docker containers');
        }

        if (/docker\s+logs/i.test(query)) {
            return rt('check_logs', 'Check logs');
        }

        if (/docker\s+inspect/i.test(query)) {
            return rt('check_containers', 'Check containers');
        }

        if (/curl/i.test(query)) {
            return rt('check_reachability', 'Check reachability');
        }

        return rt('check_system', 'Check system');
    }

    const labels = {
        system_status: rt('check_system_status', 'Check system status'),
        process_usage: rt('check_cpu_ram', 'Check CPU- and RAM-intensive processes'),
        logs_query: rt('check_logs', 'Check logs'),
        batch_status: rt('check_file_jobs', 'Check file jobs'),
        knowledge_search: rt('search_knowledge', 'Search knowledge base'),
        code_search: rt('search_relevant_code', 'Search relevant code'),
        code_files: rt('analyze_project_structure', 'Analyze project structure'),
        code_read: rt('relevant_file_checked', 'Relevant file inspected'),
        code_patch: fileCount
            ? rt(
                'files_prepared',
                '{count} changes prepared',
                { count: fileCount }
            )
            : rt('changes_prepared', 'Changes prepared'),
        code_diff: fileCount
            ? rt(
                'total_diff_files',
                'Total diff created for {count} files',
                { count: fileCount }
            )
            : rt('total_diff_created', 'Total diff created'),
        code_test: result.passed === true
            ? (fileCount
                ? rt('files_tested', '{count} files tested · Tests passed', { count: fileCount })
                : 'Tests bestanden')
            : 'Change-Set getestet',
        code_apply: fileCount
            ? rt('files_applied', '{count} files applied', { count: fileCount })
            : 'Change-Set angewendet',
        agent_plan: rt('plan_next', 'Plan next step'),
        agent_error: rt('agent_error', 'Agent error'),
        web_search: 'Web durchsuchen',
        search_web: 'Web durchsuchen',
        fetch_url: rt('open_source', 'Open source'),
        docker_restart: rt('restart_container', 'Restart container'),
        verify_change: rt('review_change', 'Review change'),
        rejected_by_user: 'Aktion abgelehnt'
    };

    return labels[action] ||
        action.replace(/_/g, ' ') ||
        'Agent-Aktion';
}


function renderAgentCard(message) {
    const run = message?.agent_run;

    if (!run) return null;

    const card =
        document.createElement('section');

    card.className = 'agent-card';

    const header =
        document.createElement('div');

    header.className =
        'agent-card-header';

    header.textContent =
        '🤖 Agent';

    card.appendChild(header);

    const steps =
        Array.isArray(run.steps)
            ? run.steps
            : [];

    for (const step of steps) {
        const row =
            document.createElement('div');

        row.className =
            'agent-step';

        const icon =
            document.createElement('div');

        icon.className =
            'agent-step-icon';

        if (step.status === 'failed') {
            icon.textContent = '⚠';
        } else if (step.status === 'running') {
            icon.textContent = '●';
        } else if (
            step.action === 'rejected_by_user'
        ) {
            icon.textContent = '–';
        } else {
            icon.textContent = '✓';
        }

        const body =
            document.createElement('div');

        const title =
            document.createElement('div');

        title.className =
            'agent-step-title';

        title.textContent =
            agentStepLabel(step);

        body.appendChild(title);

        if (step.reason) {
            const reason =
                document.createElement('div');

            reason.className =
                'agent-step-reason';

            reason.textContent =
                step.reason;

            body.appendChild(reason);
        }

        if (Array.isArray(step.plan) && step.plan.length) {
            const plan = document.createElement('div');
            plan.className = 'agent-step-plan';
            plan.textContent = 'Plan: ' + step.plan.join(' · ');
            body.appendChild(plan);
        }

        if (step.query || step.result) {
            const details =
                document.createElement('details');

            details.className =
                'agent-step-details';

            const summary =
                document.createElement('summary');

            summary.textContent =
                'Technische Details';

            const pre =
                document.createElement('pre');

            pre.textContent =
                JSON.stringify(
                    {
                        command:
                            step.query || undefined,
                        result:
                            step.result || undefined
                    },
                    null,
                    2
                ).slice(0, 12000);

            details.appendChild(summary);
            details.appendChild(pre);

            body.appendChild(details);
        }

        row.appendChild(icon);
        row.appendChild(body);

        card.appendChild(row);
    }

    if (run.status === 'running') {
        const running =
            document.createElement('div');

        running.className =
            'agent-running';

        const currentStep = [...steps].reverse().find(
            step => step?.status === 'running'
        );
        running.textContent = currentStep
            ? '● ' + agentStepLabel(currentStep) + ' …'
            : '● Agent arbeitet …';

        card.appendChild(running);
    }

    const pending =
        run.pending_action;

    if (pending) {
        const approval =
            document.createElement('div');

        approval.className =
            'agent-approval';

        const title =
            document.createElement('div');

        title.className =
            'agent-approval-title';

        title.textContent =
            rt('approval_required', '⚠ Action requires approval');

        approval.appendChild(title);

        const operation =
            document.createElement('div');

        operation.className =
            'agent-approval-operation';

        const changeSummary = pending.summary || {};
        const approvalFileCount = Number(
            changeSummary.files || 0
        );

        operation.textContent = pending.operation === 'docker_restart'
            ? rt(
                'restart_target',
                'Restart {target}',
                { target: pending.target || 'Container' }
            )
            : pending.operation === 'code_apply' && approvalFileCount
                ? rt('apply_files', 'Apply {count} files', { count: approvalFileCount })
                : String(pending.operation || 'Aktion').replace(/_/g, ' ');

        approval.appendChild(operation);

        if (pending.operation === 'code_apply' && approvalFileCount) {
            const summary = document.createElement('div');
            summary.className = 'agent-change-summary';

            const counts = document.createElement('div');
            counts.className = 'agent-change-counts';
            counts.textContent = [
                rt(
                    'created_count',
                    '+ {count} new',
                    { count: Number(changeSummary.create || 0) }
                ),
                rt(
                    'modified_count',
                    '~ {count} modified',
                    { count: Number(changeSummary.modify || 0) }
                ),
                rt(
                    'deleted_count',
                    '− {count} deleted',
                    { count: Number(changeSummary.delete || 0) }
                )
            ].join('  ·  ');
            summary.appendChild(counts);

            const testStatus = document.createElement('div');
            testStatus.className = 'agent-change-tests';
            testStatus.textContent = pending.tests?.passed
                ? '✓ Tests bestanden'
                : rt('tests_unconfirmed', '⚠ Tests not confirmed');
            summary.appendChild(testStatus);

            const lineDelta = document.createElement('div');
            lineDelta.className = 'agent-change-lines';
            lineDelta.textContent = '+' + Number(
                changeSummary.added_lines || 0
            ) + ' / −' + Number(
                changeSummary.removed_lines || 0
            ) + ' Zeilen';
            summary.appendChild(lineDelta);

            if (Array.isArray(pending.files) && pending.files.length) {
                const details = document.createElement('details');
                details.className = 'agent-step-details';
                const detailsTitle = document.createElement('summary');
                detailsTitle.textContent = rt('affected_files', 'Affected files');
                const fileList = document.createElement('pre');
                fileList.textContent = pending.files.map(file =>
                    String(file.operation || '') + '  ' + String(file.path || '')
                ).join('\n');
                details.appendChild(detailsTitle);
                details.appendChild(fileList);
                summary.appendChild(details);
            }

            approval.appendChild(summary);
        }

        if (
            pending.operation === 'docker_restart' &&
            pending.target
        ) {
            const command =
                document.createElement('div');

            command.className =
                'agent-approval-command';

            command.textContent =
                'docker restart ' +
                pending.target;

            approval.appendChild(command);
        }

        if (pending.reason) {
            const reason =
                document.createElement('div');

            reason.className =
                'agent-approval-reason';

            reason.textContent =
                pending.reason;

            approval.appendChild(reason);
        }

        const actions =
            document.createElement('div');

        actions.className =
            'agent-approval-actions';

        const reject =
            document.createElement('button');

        reject.type = 'button';
        reject.className =
            'agent-approval-button';

        reject.textContent =
            'Ablehnen';

        reject.addEventListener(
            'click',
            () =>
                window.MLXChatGeneration
                    ?.approveAgentAction(
                        message,
                        false
                    )
        );

        const execute =
            document.createElement('button');

        execute.type = 'button';
        execute.className =
            'agent-approval-button execute';

        execute.textContent =
            pending.operation === 'code_apply'
                ? 'Freigeben'
                : rt('execute', 'Run');

        execute.addEventListener(
            'click',
            () =>
                window.MLXChatGeneration
                    ?.approveAgentAction(
                        message,
                        true
                    )
        );

        actions.appendChild(reject);
        actions.appendChild(execute);

        approval.appendChild(actions);
        card.appendChild(approval);
    }

    return card;
}

function renderArtifactCard(message) {
    const artifact = message.file_artifact;
    if (!artifact) return null;
    const card = document.createElement('section');
    card.className = 'batch-chat-card artifact-card';
    const title = document.createElement('strong'); title.textContent = artifact.name || rt('generated_file', 'Generated file');
    const details = document.createElement('div'); details.className = 'batch-chat-details';
    details.textContent = [
        artifact.size != null ? formatBytes(artifact.size) : '',
        artifact.extension ? artifact.extension.toUpperCase() : '',
        message.batch_job?.processing_mode ? message.batch_job.processing_mode.toUpperCase() : '',
        message.batch_job?.pii_audit ? rt('pii_available', 'PII audit available') : ''
    ].filter(Boolean).join(' · ');
    card.appendChild(title); card.appendChild(details);
    const controls = document.createElement('div'); controls.className = 'batch-chat-controls';
    const download = document.createElement('a'); download.className = 'message-action-btn'; download.textContent = 'Download'; download.href = '/api/mlx/batch/' + encodeURIComponent(artifact.last_job_id) + '/download'; controls.appendChild(download);
    ['Ergebnis analysieren', 'Ergebnis zusammenfassen', 'PII Audit'].forEach(label => {
        const button = document.createElement('button'); button.className = 'message-action-btn'; button.textContent = label;
        button.addEventListener('click', () => {
            const input = document.getElementById('input');
            input.value = label === 'Ergebnis analysieren' ? 'Analysiere das Ergebnis.' : label === 'Ergebnis zusammenfassen' ? 'Summarize the generated file.' : 'Mach einen PII Audit.';
            window.MLXChatGeneration.sendMessage();
        });
        controls.appendChild(button);
    });
    card.appendChild(controls); return card;
}

function renderMetrics(metrics) {
    if (
        !metrics ||
        !Number.isFinite(metrics.total_ms)
    ) {
        return null;
    }

    const formatNumber = value =>
        value.toLocaleString('de-DE', {
            maximumFractionDigits: 1
        });

    const mode =
        window.MLXChatRuntime?.generationMetricsMode?.() ||
        'compact';

    if (mode === 'off') {
        return null;
    }

    const compactParts = [];

    if (Number.isFinite(metrics.estimated_tokens)) {
        compactParts.push(
            formatNumber(metrics.estimated_tokens) +
            ' Tokens'
        );
    }

    if (Number.isFinite(metrics.tokens_per_second)) {
        compactParts.push(
            formatNumber(metrics.tokens_per_second) +
            ' tok/s'
        );
    }

    if (Number.isFinite(metrics.total_ms)) {
        compactParts.push(
            formatNumber(metrics.total_ms / 1000) +
            ' s'
        );
    }

    const details =
        document.createElement('details');

    details.className =
        'message-metrics';

    if (mode === 'full') {
        details.open = true;
    }

    const summary =
        document.createElement('summary');

    summary.className =
        'message-metrics-summary';

    const summaryText =
        document.createElement('span');

    summaryText.textContent =
        compactParts.join(' · ');

    summary.appendChild(summaryText);

    if (mode === 'compact') {
        const arrow =
            document.createElement('span');

        arrow.className =
            'message-metrics-arrow';

        arrow.textContent = '›';

        summary.appendChild(arrow);
    }

    details.appendChild(summary);

    const full =
        document.createElement('div');

    full.className =
        'message-metrics-details';

    const rows = [
        [
            'Tokens',
            Number.isFinite(metrics.estimated_tokens)
                ? formatNumber(metrics.estimated_tokens)
                : '–'
        ],
        [
            'Geschwindigkeit',
            Number.isFinite(metrics.tokens_per_second)
                ? formatNumber(metrics.tokens_per_second) + ' tok/s'
                : '–'
        ],
        [
            'Gesamtzeit',
            Number.isFinite(metrics.total_ms)
                ? formatNumber(metrics.total_ms / 1000) + ' s'
                : '–'
        ],
        [
            'First Token',
            Number.isFinite(metrics.first_content_ms)
                ? formatNumber(metrics.first_content_ms / 1000) + ' s'
                : '–'
        ],
        [
            'Thinking',
            Number.isFinite(metrics.thinking_ms)
                ? formatNumber(metrics.thinking_ms / 1000) + ' s'
                : '–'
        ],
        [
            'Zeichen',
            Number.isFinite(metrics.output_chars)
                ? formatNumber(metrics.output_chars)
                : '–'
        ]
    ];

    for (const [label, value] of rows) {
        if (label === 'Thinking' && value === '–') {
            continue;
        }

        const row =
            document.createElement('div');

        row.className =
            'message-metrics-row';

        const key =
            document.createElement('span');

        key.textContent = label;

        const val =
            document.createElement('strong');

        val.textContent = value;

        row.appendChild(key);
        row.appendChild(val);
        full.appendChild(row);
    }

    details.appendChild(full);

    return details;
}

function renderBatchCard(message) {
    const job = message.batch_job;
    if (!job) return null;
    const card = document.createElement('section');
    card.className = 'batch-chat-card';
    const total = Number(job.total_chunks || 0);
    const done = Number(job.processed_chunks || 0);

    const progressPercent =
        total > 0
            ? Math.min(100, (done / total) * 100)
            : 0;
    const percent = total ? ((done / total) * 100).toFixed(1) : '0.0';
    const title = document.createElement('strong');
    const analysisJob = job.kind === 'file_analysis';
    title.textContent = job.status === 'completed' ? (analysisJob ? rt('analysis_completed', '✓ Analysis completed') : rt('processing_completed', '✓ Processing completed')) :
        job.status === 'failed' ? (analysisJob ? rt('analysis_failed', 'Analysis failed') : rt('processing_failed', 'Processing failed')) :
        (analysisJob ? rt('analyzing_file', 'Analyzing file') : rt('processing_file', 'Processing file'));
    const details = document.createElement('div');
    details.className = 'batch-chat-details';
    const eta = Number(job.eta_seconds || 0);
    details.textContent = [
        rt('file_prefix', 'File:') + ' ' + (message.batch_filename || rt('attachment', 'Attachment')),
        analysisJob ? rt('operation', 'Operation:') + ' ' + ({ inspect: rt('inspection', 'Inspection'), analyze: rt('analysis', 'Analysis'), summarize: rt('summary', 'Summary') }[job.operation] || rt('analysis', 'Analysis')) :
            rt('mode', 'Mode:') + ' ' + String(job.processing_mode || job.instruction_plan?.mode || rt('determining', 'determining')).toUpperCase(),
        rt('progress', 'Progress:') + ' ' + done + ' / ' + (total || '…') + ' (' + percent + ' %)',
        rt('mlx_calls', 'MLX calls:') + ' ' +
        Number(job.mlx_calls || 0),
        rt('llm_skipped_count', 'LLM skipped:') + ' ' +
        Number(job.skipped_llm_chunks || 0),
        job.pii_audit ? 'PII audit: ' + (Object.values(job.pii_audit).every(value => value === 0) ? rt('pii_no_hits', 'no obvious matches') : rt('pii_hits_remaining', 'remaining matches found')) : '',
        eta ? 'ETA: ' + Math.ceil(eta / 60) + ' ' + rt('minutes', 'minutes') : ''
    ].filter(Boolean).join('\n');
    card.appendChild(title);
    card.appendChild(details);

    const progressWrap =
        document.createElement('div');

    progressWrap.className =
        'batch-progress-wrap';

    const progressBar =
        document.createElement('div');

    progressBar.className =
        'batch-progress-bar';

    const progressFill =
        document.createElement('div');

    progressFill.className =
        'batch-progress-fill';

    progressFill.style.width =
        progressPercent.toFixed(2) + '%';

    progressBar.appendChild(
        progressFill
    );

    const progressText =
        document.createElement('div');

    progressText.className =
        'batch-progress-text';

    let statusText =
        job.status || rt('unknown', 'unknown');

    if (
        job.status === 'queued' &&
        job.requires_start_choice
    ) {
        action(rt('start_controlled', 'Start controlled'), 'start');
        action(rt('automatic_all', 'Process all automatically'), 'automatic-start');
        action(rt('cancel', 'Cancel'), 'cancel');
    } else if (
        job.status === 'paused' &&
        job.waiting_for_user
    ) {
        action(rt('continue', 'Continue'), 'resume');
        action(rt('automatic_remaining', 'Process remaining automatically'), 'automatic');
        action(rt('cancel', 'Cancel'), 'cancel');
    } else {
        if (
            job.status === 'running' ||
            job.status === 'queued'
        ) {
            action('Pause', 'pause');
        }

        if (
            job.status === 'paused' ||
            job.status === 'interrupted'
        ) {
            action(rt('resume', 'Resume'), 'resume');
        }

        if (
            job.status === 'running' ||
            job.status === 'queued' ||
            job.status === 'paused'
        ) {
            action(rt('cancel', 'Cancel'), 'cancel');
        }
    }

    card.appendChild(controls); return card;
}

function renderImageArtifactCard(message) {
    const artifact = message.tool_result?.tool === 'image_generate'
        ? message.tool_result.artifacts?.[0]
        : null;
    if (!artifact?.image_id) return null;
    const card = document.createElement('section');
    card.className = 'batch-chat-card image-artifact-card';
    const title = document.createElement('strong'); title.textContent = rt('local_image', 'Local image');
    const image = document.createElement('img');
    image.className = 'image-artifact-preview';
    image.src = '/api/mlx/images/' + encodeURIComponent(artifact.image_id);
    image.alt = artifact.prompt || rt('generated_image', 'Generated image');
    image.loading = 'lazy';
    const details = document.createElement('div'); details.className = 'batch-chat-details';
    details.textContent = [
        artifact.model,
        artifact.provider,
        artifact.width && artifact.height ? artifact.width + ' × ' + artifact.height : '',
        artifact.steps ? artifact.steps + ' Steps' : '',
        artifact.seed != null ? 'Seed ' + artifact.seed : ''
    ].filter(Boolean).join(' · ');
    const controls = document.createElement('div'); controls.className = 'batch-chat-controls';
    const download = document.createElement('a');
    download.className = 'message-action-btn'; download.textContent = 'Download';
    download.href = '/api/mlx/images/' + encodeURIComponent(artifact.image_id) + '?download=1';
    controls.appendChild(download);
    const variation = document.createElement('button');
    variation.className = 'message-action-btn'; variation.textContent = 'Variation';
    variation.addEventListener('click', () => {
        const input = document.getElementById('input');
        input.value = 'Create an image of ' + (artifact.prompt || 'diesem Motiv');
        window.MLXChatGeneration.sendMessage({ image: {
            prompt: artifact.prompt || 'dieses Motiv',
            model: artifact.model || 'FLUX.1-schnell',
            width: artifact.width || 512, height: artifact.height || 512,
            steps: artifact.steps || 4, guidance: artifact.guidance ?? 0, seed: null
        }});
    });
    controls.appendChild(variation);
    card.appendChild(title); card.appendChild(image); card.appendChild(details); card.appendChild(controls);
    return card;
}

function renderArtifactChoice(message) {
    const choice = message.artifact_choice;
    if (!choice) return null;
    const card = document.createElement('section'); card.className = 'batch-chat-card artifact-choice-card';
    for (const artifact of choice.candidates || []) {
        const button = document.createElement('button'); button.className = 'message-action-btn artifact-choice-button';
        button.textContent = artifact.name || artifact.output_name || rt('generated_file', 'Generated file');
        button.addEventListener('click', () => {
            const session = MLXChatSessions.currentSession();
            session.workspace = { ...(session.workspace || {}), active_artifact_id: artifact.artifact_id };
            MLXChatSessions.saveSessions();
            document.getElementById('input').value = choice.prompt;
            window.MLXChatGeneration.sendMessage();
        });
        card.appendChild(button);
    }
    return card;
}


function renderMessages(options = {}) {
    const session = currentSession();
    const scrollSnapshot =
        MLXChatRuntime.beforeMessagesRender();

    messagesInner.innerHTML = '';

    if (
        !session ||
        session.messages.length === 0
    ) {
        messagesInner.innerHTML = `
            <div class="empty">
                <div class="empty-logo"><img src="/assets/mlx-nobby.svg" alt="MLX nobby"></div>
                <h1>${rt('ready_next_idea', 'Ready for your next great idea?')}</h1>
                <p>
                    <span>${rt('empty_prompt', 'Ask, dictate, or upload — Nobby is ready. 😎')}</span>
                    <span class="empty-local">${rt('empty_local', 'Everything runs locally on your Mac.')}</span>
                </p>
            </div>
        `;

        updateContext();
        MLXChatRuntime.afterMessagesRender(
            scrollSnapshot,
            options
        );

        return;
    }

    for (
        let index = 0;
        index < session.messages.length;
        index++
    ) {
        const message =
            session.messages[index];

        const article =
            document.createElement('article');

        article.className =
            'message ' + message.role;

        const avatar =
            document.createElement('div');

        avatar.className = 'avatar';

        avatar.textContent =
            message.role === 'assistant'
                ? 'AI'
                : 'DU';

        const body =
            document.createElement('div');

        const author =
            document.createElement('div');

        author.className = 'message-author';

        author.textContent =
            message.role === 'assistant'
                ? 'MLX'
                : 'Du';

        const content =
            document.createElement('div');

        content.className = 'message-content';

        if (message.role === 'assistant') {

            if (
                message.reasoning &&
                MLXChatRuntime.showRuntimeThinkingInfo()
            ) {

                const thinking =
                    document.createElement('div');

                thinking.className =
                    'thinking-block';

                const header =
                    document.createElement('button');

                header.className =
                    'thinking-header';

                const title =
                    document.createElement('div');

                title.className =
                    'thinking-title';

                const arrow =
                    document.createElement('span');

                arrow.className =
                    'thinking-arrow';

                arrow.textContent = '›';

                const label =
                    document.createElement('span');

                let thinkingLabel =
                    'Thinking';

                if (
                    message.thinking_seconds !== null &&
                    message.thinking_seconds !== undefined
                ) {
                    thinkingLabel +=
                        ' · ' +
                        message.thinking_seconds.toFixed(1) +
                        ' s';
                }

                label.textContent =
                    thinkingLabel;

                title.appendChild(arrow);
                title.appendChild(label);

                header.appendChild(title);

                const thinkingContent =
                    document.createElement('div');

                thinkingContent.className =
                    'thinking-content';

                thinkingContent.textContent =
                    message.reasoning;

                header.addEventListener(
                    'click',
                    () => {
                        thinking.classList.toggle(
                            'open'
                        );
                    }
                );

                thinking.appendChild(header);
                thinking.appendChild(
                    thinkingContent
                );

                content.appendChild(thinking);
            }

            if (
                message.response_pending &&
                !message.content
            ) {
                const waitingDot =
                    document.createElement('span');

                waitingDot.className =
                    'assistant-thinking-dot';

                waitingDot.setAttribute(
                    'role',
                    'status'
                );

                waitingDot.setAttribute(
                    'aria-label',
                    'MLX nobby denkt'
                );

                content.appendChild(waitingDot);
            }

            const answer =
                document.createElement('div');

            answer.innerHTML =
                markdownHtml(message.content);

            content.appendChild(answer);

            if (
                Array.isArray(message.sources) &&
                message.sources.length > 0
            ) {
                const sources = document.createElement('div');
                sources.className = 'message-rag-sources';

                const sourcesHeader =
                    document.createElement('div');
                sourcesHeader.className =
                    'message-rag-sources-header';
                sourcesHeader.textContent = rt('knowledge_sources', 'Knowledge sources');

                const sourcesList =
                    document.createElement('div');
                sourcesList.className =
                    'message-rag-sources-list';

                message.sources.forEach(source => {
                    if (!source || typeof source !== 'object') {
                        return;
                    }

                    const sourceName =
                        String(
                            source.source ||
                            rt('local_knowledge_base', 'Local knowledge base')
                        ).trim();

                    const documentPath =
                        String(
                            source.document || ''
                        ).trim();

                    const fileName =
                        documentPath
                            .split(/[\\/]/)
                            .pop();

                    const item =
                        document.createElement('div');
                    item.className =
                        'message-rag-source';

                    const icon =
                        document.createElement('span');
                    icon.className =
                        'message-rag-source-icon';
                    icon.textContent = '▣';

                    const label =
                        document.createElement('span');

                    label.textContent =
                        fileName
                            ? sourceName + ' · ' + fileName
                            : sourceName;

                    item.appendChild(icon);
                    item.appendChild(label);
                    sourcesList.appendChild(item);
                });

                if (sourcesList.childElementCount > 0) {
                    sources.appendChild(sourcesHeader);
                    sources.appendChild(sourcesList);
                    content.appendChild(sources);
                }
            }

            const batchCard = renderBatchCard(message);
            if (batchCard) content.appendChild(batchCard);

            const toolCard = renderToolCard(message);
            if (toolCard) content.appendChild(toolCard);

            const agentCard = renderAgentCard(message);
            if (agentCard) content.appendChild(agentCard);

            const imageArtifactCard = renderImageArtifactCard(message);
            if (imageArtifactCard) content.appendChild(imageArtifactCard);

            const artifactCard = renderArtifactCard(message);
            if (artifactCard) content.appendChild(artifactCard);

            const artifactChoice = renderArtifactChoice(message);
            if (artifactChoice) content.appendChild(artifactChoice);

            const metrics =
                MLXChatRuntime.showGenerationMetrics()
                    ? renderMetrics(message.metrics)
                    : null;

            enhanceCodeBlocks(content);

            const actions =
                document.createElement('div');

            actions.className =
                'message-actions';

            const copy =
                document.createElement('button');

            copy.className =
                'message-action-btn message-action-icon';
            copy.type = 'button';
            copy.title = 'Kopieren';
            copy.setAttribute('aria-label', 'Kopieren');

            const copyIcon = `
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2"></rect>
                    <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"></path>
                </svg>
            `;

            const copiedIcon = `
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4 4L19 6.5"></path>
                </svg>
            `;

            copy.innerHTML = copyIcon;

            copy.addEventListener(
                'click',
                async () => {
                    await navigator.clipboard.writeText(
                        message.content
                    );

                    copy.innerHTML = copiedIcon;
                    copy.title = 'Kopiert';

                    setTimeout(
                        () => {
                            copy.innerHTML = copyIcon;
                            copy.title = 'Kopieren';
                        },
                        1200
                    );
                }
            );

            actions.appendChild(copy);

            const info =
                document.createElement('button');

            info.className =
                'message-action-btn message-action-icon message-info-btn';

            info.type = 'button';
            info.setAttribute(
                'aria-label',
                rt('response_information', 'Response information')
            );

            info.innerHTML = `
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="12" r="9"></circle>
                    <path d="M12 10v6"></path>
                    <path d="M12 7h.01"></path>
                </svg>
            `;

            const tooltip =
                document.createElement('div');

            tooltip.className =
                'message-info-tooltip';

            const metricData =
                message.metrics || {};

            const formatMetric = (value, digits = 1) =>
                Number(value).toLocaleString(
                    'de-DE',
                    {
                        maximumFractionDigits: digits
                    }
                );

            const rows = [];

            if (Number.isFinite(metricData.estimated_tokens)) {
                rows.push([
                    'Tokens',
                    formatMetric(
                        metricData.estimated_tokens,
                        0
                    )
                ]);
            }

            if (Number.isFinite(metricData.tokens_per_second)) {
                rows.push([
                    'Geschwindigkeit',
                    formatMetric(
                        metricData.tokens_per_second
                    ) + ' tok/s'
                ]);
            }

            if (Number.isFinite(metricData.total_ms)) {
                rows.push([
                    'Gesamtzeit',
                    formatMetric(
                        metricData.total_ms / 1000
                    ) + ' s'
                ]);
            }

            if (Number.isFinite(metricData.first_content_ms)) {
                rows.push([
                    'First Token',
                    formatMetric(
                        metricData.first_content_ms / 1000
                    ) + ' s'
                ]);
            }

            if (Number.isFinite(metricData.thinking_ms)) {
                rows.push([
                    'Thinking',
                    formatMetric(
                        metricData.thinking_ms / 1000
                    ) + ' s'
                ]);
            }

            const list =
                document.createElement('div');

            list.className =
                'message-info-list';

            if (rows.length === 0) {
                const empty =
                    document.createElement('div');

                empty.className =
                    'message-info-empty';

                empty.textContent =
                    rt('no_metrics', 'No metrics available');

                list.appendChild(empty);
            } else {
                for (const [label, value] of rows) {
                    const row =
                        document.createElement('div');

                    row.className =
                        'message-info-row';

                    const key =
                        document.createElement('span');

                    key.textContent = label;

                    const val =
                        document.createElement('strong');

                    val.textContent = value;

                    row.appendChild(key);
                    row.appendChild(val);
                    list.appendChild(row);
                }
            }

            tooltip.appendChild(list);
            info.appendChild(tooltip);
            actions.appendChild(info);

            const isLast =
                index ===
                session.messages.length - 1;

            if (isLast) {
                const regenerate =
                    document.createElement('button');

                regenerate.className =
                    'message-action-btn message-action-icon';
                regenerate.type = 'button';
                regenerate.title = rt('regenerate', 'Regenerate');
                regenerate.setAttribute(
                    'aria-label',
                    rt('regenerate', 'Regenerate')
                );
                regenerate.innerHTML = `
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M20 11a8 8 0 0 0-14.9-4"></path>
                        <path d="M5 3v5h5"></path>
                        <path d="M4 13a8 8 0 0 0 14.9 4"></path>
                        <path d="M19 21v-5h-5"></path>
                    </svg>
                `;

                regenerate.addEventListener(
                    'click',
                    regenerateLastAnswer
                );

                actions.appendChild(
                    regenerate
                );
            }

            body.appendChild(author);
            body.appendChild(content);
            body.appendChild(actions);

            article.appendChild(avatar);
            article.appendChild(body);

            messagesInner.appendChild(article);

            continue;

        } else {

            const visibleText =
                message.display_content ??
                message.content;

            content.innerHTML =
                `<div>${escapeHtml(visibleText)
                    .replace(/\n/g, '<br>')}</div>`;

            if (
                message.attachments &&
                message.attachments.length
            ) {
                const files =
                    document.createElement(
                        'div'
                    );

                files.className =
                    'attachment-bar visible';

                files.style.padding =
                    '16px 0 0';

                for (
                    const file of
                    message.attachments
                ) {
                    const chip =
                        document.createElement(
                            'div'
                        );

                    chip.className =
                        'attachment-chip message-attachment-chip';

                    if (
                        file.kind === 'image' &&
                        file.data_url
                    ) {
                        const preview =
                            document.createElement('img');

                        preview.className =
                            'message-attachment-preview';

                        preview.src =
                            file.data_url;

                        preview.alt =
                            file.name || rt('image', 'Image');

                        chip.appendChild(
                            preview
                        );
                    }

                    const meta =
                        document.createElement('div');

                    meta.className =
                        'message-attachment-meta';

                    const title =
                        document.createElement('div');

                    title.className =
                        'message-attachment-title';

                    title.textContent =
                        file.name || rt('file', 'File');

                    const details =
                        document.createElement('div');

                    details.className =
                        'message-attachment-details';

                    details.textContent =
                        formatBytes(file.size) +
                        (file.extension
                            ? ' · ' + file.extension.toUpperCase()
                            : '') +
                        (
                            Number.isFinite(file.record_count)
                                ? ' · ' +
                                  file.record_count.toLocaleString(
            window.MLXI18n?.getLocale?.() || 'en-US'
        ) +
                                  rt('records_suffix', ' records')
                                : ''
                        );

                    meta.appendChild(title);
                    meta.appendChild(details);

                    chip.appendChild(
                        meta
                    );

                    files.appendChild(
                        chip
                    );
                }

                content.appendChild(
                    files
                );
            }

            const actions =
                document.createElement('div');

            actions.className =
                'message-actions';

            const edit =
                document.createElement('button');

            edit.className =
                'message-action-btn message-action-icon';
            edit.type = 'button';
            edit.title = rt('edit', 'Edit');
            edit.setAttribute(
                'aria-label',
                rt('edit', 'Edit')
            );
            edit.innerHTML = `
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 20h9"></path>
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"></path>
                </svg>
            `;

            edit.addEventListener(
                'click',
                () => {
                    startEditMessage(
                        index,
                        article
                    );
                }
            );

            actions.appendChild(edit);

            body.appendChild(author);
            body.appendChild(content);
            body.appendChild(actions);

            article.appendChild(avatar);
            article.appendChild(body);

            messagesInner.appendChild(article);

            continue;
        }

        body.appendChild(author);
        body.appendChild(content);

        article.appendChild(avatar);
        article.appendChild(body);

        messagesInner.appendChild(article);
    }

    updateContext();
    MLXChatRuntime.afterMessagesRender(
        scrollSnapshot,
        options
    );
}


function renderAll(options = {}) {
    renderSidebar();
    renderMessages(options);
}


    window.MLXChatRendering = {
        configure: configure,
        renderSidebar: renderSidebar,
        renderMessages: renderMessages,
        renderAll: renderAll
    };

    document.addEventListener('mlx-language-changed', () => {
        if (typeof window.renderMessages === 'function') {
            window.renderMessages();
        }
    });

})();
