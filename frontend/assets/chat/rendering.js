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
    let imageJobUiTimer = null;
    const agentDetailsExpanded = new WeakMap();

    const ACTIVE_IMAGE_JOB_STATUSES = new Set([
        'queued',
        'loading',
        'running',
        'saving'
    ]);
    const IMAGE_JOB_STALE_SECONDS = 25;
    const IMAGE_JOB_UI_TICK_MS = 1000;

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

    function imageJobHasStep(job) {
        const currentStep = Number(job?.current_step);
        const totalSteps = Number(job?.total_steps);

        return job?.current_step != null &&
            job?.total_steps != null &&
            Number.isInteger(currentStep) &&
            Number.isInteger(totalSteps) &&
            currentStep > 0 &&
            totalSteps > 0 &&
            currentStep <= totalSteps;
    }

    function imageJobElapsedSeconds(job, nowSeconds) {
        const startedAt = Number(job?.started_at);
        const createdAt = Number(job?.created_at);
        const start = Number.isFinite(startedAt) && startedAt > 0
            ? startedAt
            : Number.isFinite(createdAt) && createdAt > 0
                ? createdAt
                : null;

        return start == null
            ? null
            : Math.max(0, Math.floor(nowSeconds - start));
    }

    function formatImageJobDuration(seconds) {
        const safeSeconds = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(safeSeconds / 60);
        const remainder = Math.floor(safeSeconds % 60);

        return String(minutes).padStart(2, '0') + ':' +
            String(remainder).padStart(2, '0');
    }

    function imageJobPresentation(
        job,
        nowSeconds = Date.now() / 1000
    ) {
        const status = String(job?.status || 'queued');
        const active = ACTIVE_IMAGE_JOB_STATUSES.has(status);
        const hasStepProgress = imageJobHasStep(job);
        const statusFallback = {
            queued: 'Image job waiting …',
            loading: 'Loading model …',
            running: 'Image is being processed …',
            saving: 'Saving image …',
            cancelled: 'Cancelled',
            failed: 'Failed'
        }[status] || status;
        const progressUpdatedAt = Number(job?.progress_updated_at);
        const fallbackProgressUpdatedAt = Number(
            job?.started_at || job?.created_at
        );
        const lastProgressAt =
            Number.isFinite(progressUpdatedAt) && progressUpdatedAt > 0
                ? progressUpdatedAt
                : Number.isFinite(fallbackProgressUpdatedAt) &&
                    fallbackProgressUpdatedAt > 0
                    ? fallbackProgressUpdatedAt
                    : null;
        const stale =
            status === 'running' &&
            hasStepProgress &&
            lastProgressAt != null &&
            nowSeconds - lastProgressAt >= IMAGE_JOB_STALE_SECONDS;

        let title;
        if (status === 'cancelled') {
            title = rt('image_job_cancelled', 'Image job cancelled');
        } else if (status === 'failed') {
            title = rt('image_job_failed', 'Image job failed');
        } else if (status === 'running' && stale) {
            title = rt(
                'image_job_status_running_stale',
                'Image processing continues …'
            );
        } else if (status === 'running' && hasStepProgress) {
            if (job.operation === 'edit') {
                title = rt('image_editing', 'Editing image …');
            } else if (job.operation === 'upscale') {
                title = rt('image_upscaling', 'Enhancing image …');
            } else {
                title = rt('image_generating', 'Generating image …');
            }
        } else {
            title = rt(
                'image_job_status_' + status,
                statusFallback
            );
        }

        const details = [];
        if (status === 'running' && hasStepProgress) {
            details.push(rt(
                stale ? 'image_step_last' : 'image_step',
                stale
                    ? 'Last reported step: {current}/{total}'
                    : 'Step {current}/{total}',
                {
                    current: Number(job.current_step),
                    total: Number(job.total_steps)
                }
            ));
        } else if (!active) {
            details.push(rt(
                'image_job_status_' + status,
                statusFallback
            ));
        }

        const elapsed = active
            ? imageJobElapsedSeconds(job, nowSeconds)
            : null;
        if (elapsed != null) {
            details.push(rt(
                'image_elapsed',
                'Elapsed: {duration}',
                { duration: formatImageJobDuration(elapsed) }
            ));
        }

        return {
            active,
            details: details.join('\n'),
            elapsed,
            hasStepProgress,
            stale,
            title
        };
    }

    function sessionNeedsImageJobUiTimer(session) {
        return Boolean(session?.messages?.some(message => (
            ACTIVE_IMAGE_JOB_STATUSES.has(message?.image_job?.status) &&
            !window.MLXChatGeneration?.isWatchingImageJob?.(
                message
            )
        )));
    }

    function syncImageJobUiTimer() {
        const needsTimer = sessionNeedsImageJobUiTimer(
            currentSession?.()
        );

        if (
            needsTimer &&
            imageJobUiTimer == null &&
            typeof setInterval === 'function'
        ) {
            imageJobUiTimer = setInterval(() => {
                if (!sessionNeedsImageJobUiTimer(currentSession?.())) {
                    syncImageJobUiTimer();
                    return;
                }
                renderMessages({ contentUpdated: false });
            }, IMAGE_JOB_UI_TICK_MS);
        } else if (
            !needsTimer &&
            imageJobUiTimer != null &&
            typeof clearInterval === 'function'
        ) {
            clearInterval(imageJobUiTimer);
            imageJobUiTimer = null;
        }
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
    const source = String(text || '');

    if (
        typeof katex === 'undefined'
        || !katex
        || typeof katex.renderToString !== 'function'
    ) {
        const html = marked.parse(source);
        return DOMPurify.sanitize(html);
    }

    const protectedParts = [];

    function protect(entry) {
        const token =
            `MLXPROTECTEDTOKEN${protectedParts.length}END`;

        protectedParts.push(entry);

        return token;
    }

    let prepared = source;

    /*
     * Protect fenced and inline code before parsing math.
     * Dollar signs inside code must remain literal.
     */
    prepared = prepared.replace(
        /```[\s\S]*?```/g,
        match => protect({
            type: 'raw',
            value: match,
        }),
    );

    prepared = prepared.replace(
        /`[^`\n]+`/g,
        match => protect({
            type: 'raw',
            value: match,
        }),
    );

    /*
     * Display math:
     * $$...$$
     * \[...\]
     */
    prepared = prepared.replace(
        /\$\$([\s\S]+?)\$\$/g,
        (_match, expression) => protect({
            type: 'math',
            displayMode: true,
            value: expression.trim(),
        }),
    );

    prepared = prepared.replace(
        /\\\[([\s\S]+?)\\\]/g,
        (_match, expression) => protect({
            type: 'math',
            displayMode: true,
            value: expression.trim(),
        }),
    );

    /*
     * Inline math:
     * $...$
     * \(...\)
     */
    prepared = prepared.replace(
        /(^|[^\\$])\$([^\n$]*?\S[^\n$]*?)\$/g,
        (_match, prefix, expression) =>
            prefix + protect({
                type: 'math',
                displayMode: false,
                value: expression.trim(),
            }),
    );

    prepared = prepared.replace(
        /\\\(([\s\S]+?)\\\)/g,
        (_match, expression) => protect({
            type: 'math',
            displayMode: false,
            value: expression.trim(),
        }),
    );

    let html = marked.parse(prepared);

    html = DOMPurify.sanitize(html);

    protectedParts.forEach((entry, index) => {
        const token = `MLXPROTECTEDTOKEN${index}END`;

        let replacement;

        if (entry.type === 'raw') {
            replacement = DOMPurify.sanitize(
                marked.parse(entry.value)
            );
        } else {
            try {
                replacement = katex.renderToString(
                    entry.value,
                    {
                        displayMode: entry.displayMode,
                        throwOnError: false,
                        strict: 'ignore',
                        trust: false,
                    },
                );
            } catch {
                replacement = escapeHtml(entry.value);
            }
        }

        html = html.replaceAll(token, replacement);
    });

    return html;
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
    if (
        message?.tool_result?.tool === 'image_generate' &&
        message?.tool_result?.status === 'completed'
    ) {
        return null;
    }
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
        image_edit: rt('image_editing', 'Image editing'),
        image_upscale: rt('image_upscale', 'Image enhancement'),
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

function codeTestEvidence(result = {}) {
    const results = Array.isArray(result.results)
        ? result.results.filter(entry => entry && typeof entry === 'object')
        : [];
    const reportedChecks = Number(result.checks_run);
    const checksRun = Number.isInteger(reportedChecks) && reportedChecks >= 0
        ? reportedChecks
        : results.filter(entry => ['passed', 'failed'].includes(entry.status)).length;
    const failedCount = results.filter(
        entry => ['failed', 'unavailable'].includes(entry.status)
    ).length;
    const relevantCount = results.filter(
        entry => entry.status !== 'skipped'
    ).length;
    const reportedStatus = String(result.test_status || '').toLowerCase();
    let status = 'no_checks';

    if (reportedStatus === 'no_checks') {
        status = 'no_checks';
    } else if (reportedStatus === 'failed' || failedCount > 0) {
        status = 'failed';
    } else if (
        reportedStatus === 'passed' &&
        result.passed === true &&
        checksRun > 0
    ) {
        status = 'passed';
    } else if (
        !reportedStatus &&
        result.passed === true &&
        checksRun > 0
    ) {
        status = 'passed';
    }

    return {
        status,
        checksRun,
        failedCount,
        totalCount: Math.max(checksRun, relevantCount),
        results,
    };
}

function codeTestEvidenceLabel(result = {}) {
    const evidence = codeTestEvidence(result);

    if (evidence.status === 'passed') {
        return rt(
            'tests_passed_checks',
            'Tests passed · {count} checks run',
            { count: evidence.checksRun }
        );
    }

    if (evidence.status === 'failed') {
        return rt(
            'tests_failed_checks',
            'Tests failed · {failed} of {total} checks failed',
            {
                failed: Math.max(1, evidence.failedCount),
                total: Math.max(1, evidence.totalCount),
            }
        );
    }

    return rt(
        'tests_no_checks',
        'Not tested · No suitable test is configured for this workspace.'
    );
}

function codeApplyEvidenceValid(pending = {}) {
    if (pending.operation !== 'code_apply') return true;
    return codeTestEvidence(pending.tests || {}).status === 'passed';
}

function renderCodeTestEvidence(result = {}) {
    const evidence = codeTestEvidence(result);
    const panel = document.createElement('div');
    panel.className = 'agent-test-evidence ' + evidence.status;

    const heading = document.createElement('div');
    heading.className = 'agent-test-evidence-title';
    heading.textContent = codeTestEvidenceLabel(result);
    panel.appendChild(heading);

    if (evidence.status === 'no_checks') {
        const explanation = document.createElement('div');
        explanation.className = 'agent-test-evidence-message';
        explanation.textContent = rt(
            'tests_no_checks_apply_blocked',
            'This change cannot be applied yet because no real test could be run.'
        );
        panel.appendChild(explanation);

        const configure = document.createElement('button');
        configure.type = 'button';
        configure.className = 'message-action-btn agent-test-configure';
        configure.textContent = rt('configure_tests', 'Configure tests');
        configure.addEventListener('click', () => {
            if (window.MLXChatWorkspace?.openTestConfiguration) {
                window.MLXChatWorkspace.openTestConfiguration();
                return;
            }
            window.MLXChatSettings?.open?.('general');
        });
        panel.appendChild(configure);
    }

    if (evidence.results.length) {
        const list = document.createElement('div');
        list.className = 'agent-test-results';

        evidence.results.forEach((entry, index) => {
            const item = document.createElement('div');
            const itemStatus = String(entry.status || 'unknown').toLowerCase();
            item.className = 'agent-test-result ' + itemStatus;

            const label = document.createElement('span');
            label.className = 'agent-test-result-label';
            label.textContent = entry.path ||
                (Array.isArray(entry.command) ? entry.command.join(' ') : '') ||
                rt('test_check_number', 'Check {count}', { count: index + 1 });

            const status = document.createElement('span');
            status.className = 'agent-test-result-status';
            status.textContent = rt(
                'test_result_' + itemStatus,
                itemStatus.replace(/_/g, ' ')
            );

            item.appendChild(label);
            item.appendChild(status);

            if (
                ['failed', 'unavailable'].includes(itemStatus) &&
                String(entry.output || '').trim()
            ) {
                const output = document.createElement('pre');
                output.className = 'agent-test-result-output';
                output.textContent = String(entry.output).trim().slice(0, 2000);
                item.appendChild(output);
            }

            list.appendChild(item);
        });

        panel.appendChild(list);
    }

    return panel;
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
        disk_usage: rt('check_disk_usage', 'Analyze disk usage'),
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
        code_test: codeTestEvidenceLabel(result),
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

    const steps =
        Array.isArray(run.steps)
            ? run.steps
            : [];

    const header =
        document.createElement('div');

    header.className =
        'agent-card-header';

    const title = document.createElement('span');
    title.textContent = '🤖 Agent';

    const statusNames = {
        running: ['●', rt('agent_status_running', 'Running')],
        completed: ['✓', rt('agent_status_completed', 'Completed')],
        failed: ['⚠', rt('agent_status_failed', 'Failed')],
        cancelled: ['–', rt('agent_status_cancelled', 'Cancelled')],
        approval_required: [
            '⚠',
            rt('agent_status_approval_required', 'Approval required')
        ],
        max_steps: ['○', rt('agent_status_max_steps', 'Step limit reached')]
    };
    const status = statusNames[run.status] || [
        '○',
        String(run.status || rt('agent_status_completed', 'Completed'))
    ];
    const stepCount = steps.length === 1
        ? rt('agent_step_count_one', '1 step')
        : rt(
            'agent_step_count_many',
            '{count} steps',
            { count: steps.length }
        );
    const metadata = document.createElement('span');
    metadata.className = 'agent-card-metadata';
    metadata.textContent = stepCount + ' · ' + status.join(' ');

    header.appendChild(title);
    header.appendChild(metadata);

    card.appendChild(header);

    if (run.goal) {
        const summary = document.createElement('div');
        summary.className = 'agent-card-summary';
        summary.textContent = String(run.goal).slice(0, 180);
        card.appendChild(summary);
    }

    const detailsContainer = document.createElement('div');
    detailsContainer.className = 'agent-card-details';
    const detailsAreExpanded = agentDetailsExpanded.get(message) === true;
    detailsContainer.hidden = !detailsAreExpanded;

    if (steps.length) {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'agent-card-toggle';

        const updateToggle = expanded => {
            toggle.setAttribute('aria-expanded', String(expanded));
            toggle.textContent = expanded
                ? rt('agent_details_hide', 'Hide details') + ' ▴'
                : rt('agent_details_show', 'Show details') + ' ▾';
        };

        updateToggle(detailsAreExpanded);
        toggle.addEventListener('click', () => {
            const expanded = detailsContainer.hidden;
            detailsContainer.hidden = !expanded;
            agentDetailsExpanded.set(message, expanded);
            updateToggle(expanded);
        });
        card.appendChild(toggle);
    }

    for (const step of steps) {
        const row =
            document.createElement('div');

        row.className =
            'agent-step';

        const icon =
            document.createElement('div');

        icon.className =
            'agent-step-icon';

        const testEvidence = step.action === 'code_test'
            ? codeTestEvidence(step.result || {})
            : null;

        if (step.status === 'failed' || testEvidence?.status === 'failed') {
            icon.textContent = '⚠';
        } else if (testEvidence?.status === 'no_checks') {
            icon.textContent = '○';
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

        if (step.action === 'code_test' && step.result) {
            body.appendChild(renderCodeTestEvidence(step.result));
        }

        if (step.query || step.result) {
            const details =
                document.createElement('details');

            details.className =
                'agent-step-details';

            const summary =
                document.createElement('summary');

            summary.textContent =
                rt('technical_details', 'Technical details');

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

        detailsContainer.appendChild(row);
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

        detailsContainer.appendChild(running);
    }

    if (steps.length) {
        card.appendChild(detailsContainer);
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
            testStatus.textContent = codeTestEvidenceLabel(pending.tests || {});
            testStatus.classList.add(
                codeTestEvidence(pending.tests || {}).status
            );
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
                ? rt('approve', 'Approve')
                : rt('execute', 'Run');

        if (!codeApplyEvidenceValid(pending)) {
            execute.disabled = true;
            execute.title = rt(
                'apply_blocked_without_tests',
                'Apply is blocked until a real test has passed.'
            );
        }

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

function batchFailureDetail(job = {}) {
    if (job.status !== 'failed' || !job.error) return '';
    const value = String(job.error);
    const tracebackAt = value.indexOf('\nTraceback (most recent call last):');
    return (tracebackAt >= 0 ? value.slice(0, tracebackAt) : value)
        .trim()
        .slice(0, 1200);
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
        batchFailureDetail(job),
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

    progressText.textContent = statusText;
    progressWrap.appendChild(progressBar);
    progressWrap.appendChild(progressText);
    card.appendChild(progressWrap);

    const controls = document.createElement('div');
    controls.className = 'batch-chat-controls';

    const action = (label, operation) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'message-action-btn';
        button.textContent = label;

        button.addEventListener('click', async () => {
            const originalLabel = button.textContent;

            button.disabled = true;

            try {
                const request = async endpoint => {
                    const response = await fetch(
                        '/api/mlx/batch/' +
                        encodeURIComponent(job.id) +
                        '/' +
                        endpoint,
                        {
                            method: 'POST'
                        }
                    );

                    if (!response.ok) {
                        throw new Error(
                            await response.text()
                        );
                    }

                    return response;
                };

                if (operation === 'automatic-start') {
                    await request('automatic');
                    await request('start');
                } else {
                    await request(operation);
                }

                const statusResponse =
                    await fetch('/api/mlx/batch');

                if (!statusResponse.ok) {
                    throw new Error(
                        await statusResponse.text()
                    );
                }

                const data =
                    await statusResponse.json();

                const updatedJob =
                    (data.jobs || []).find(
                        item => item.id === job.id
                    );

                if (updatedJob) {
                    message.batch_job = updatedJob;
                }

                MLXChatSessions.saveSessions();

                renderMessages({
                    contentUpdated: true
                });

            } catch (error) {
                console.warn(
                    'Batch action failed',
                    operation,
                    error
                );

                button.disabled = false;
                button.textContent = originalLabel;
            }
        });

        controls.appendChild(button);
    };

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
    const artifact = [
        'image_generate',
        'image_edit',
        'image_upscale'
    ].includes(message.tool_result?.tool)
        ? message.tool_result.artifacts?.[0]
        : null;
    if (!artifact?.image_id) return null;
    const card = document.createElement('section');
    card.className = 'batch-chat-card image-artifact-card';
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
        artifact.scale ? artifact.scale + '×' : '',
        artifact.steps ? artifact.steps + ' Steps' : '',
        artifact.seed != null ? 'Seed ' + artifact.seed : ''
    ].filter(Boolean).join(' · ');
    const controls = document.createElement('div'); controls.className = 'batch-chat-controls';
    const download = document.createElement('a');
    download.className = 'message-action-btn'; download.textContent = 'Download';
    download.href = '/api/mlx/images/' + encodeURIComponent(artifact.image_id) + '?download=1';
    controls.appendChild(download);
    const enhanceMenu = window.MLXChatGeneration
        ?.createImageUpscaleMenu?.(artifact);
    if (enhanceMenu) {
        controls.appendChild(enhanceMenu);
    }
    card.appendChild(image);
    card.appendChild(details);
    card.appendChild(controls);
    return card;
}

function renderImageJobCard(message) {
    const job = message.image_job;
    if (!job || job.status === 'completed') return null;
    const presentation = imageJobPresentation(job);

    const card = document.createElement('section');
    card.className = 'batch-chat-card image-job-card';
    const title = document.createElement('strong');
    title.textContent = presentation.title;
    card.appendChild(title);

    const details = document.createElement('div');
    details.className = 'batch-chat-details';
    const currentStep = Number(job.current_step);
    const totalSteps = Number(job.total_steps);
    details.textContent = presentation.details;
    card.appendChild(details);

    if (presentation.hasStepProgress) {
        const progressWrap = document.createElement('div');
        progressWrap.className = 'batch-progress-wrap';
        const progressBar = document.createElement('div');
        progressBar.className = 'batch-progress-bar';
        const progressFill = document.createElement('div');
        progressFill.className = 'batch-progress-fill';
        progressFill.style.width =
            Math.min(100, (currentStep / totalSteps) * 100).toFixed(2) + '%';
        progressBar.appendChild(progressFill);
        progressWrap.appendChild(progressBar);
        card.appendChild(progressWrap);
    }

    if ([
        'queued',
        'loading',
        'running',
        'saving'
    ].includes(job.status)) {
        const controls = document.createElement('div');
        controls.className = 'batch-chat-controls';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'message-action-btn';
        cancel.textContent = rt('cancel', 'Cancel');
        cancel.addEventListener('click', async () => {
            cancel.disabled = true;
            try {
                const response = await fetch(
                    '/api/mlx/image-jobs/' +
                    encodeURIComponent(job.id) +
                    '/cancel',
                    { method: 'POST' }
                );
                if (!response.ok) {
                    throw new Error(await response.text());
                }
                const toolResult = await response.json();
                const session = MLXChatSessions.currentSession();
                window.MLXChatGeneration.updateImageJobMessage(
                    session,
                    message,
                    toolResult
                );
                MLXChatSessions.saveSessions();
                renderMessages({ contentUpdated: true });
            } catch (error) {
                console.warn('Image job cancellation failed', error);
                cancel.disabled = false;
            }
        });
        controls.appendChild(cancel);
        card.appendChild(controls);
    }

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
    syncImageJobUiTimer();
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
                <h1 data-i18n="ui.ready_next_idea">${rt('ready_next_idea', 'Ready for your next great idea?')}</h1>
                <p>
                    <span data-i18n="ui.empty_prompt">${rt('empty_prompt', 'Ask, dictate, or upload — Nobby is ready. 😎')}</span>
                    <span class="empty-local" data-i18n="ui.empty_local">${rt('empty_local', 'Everything runs locally on your Mac.')}</span>
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

            const imageJobCard = renderImageJobCard(message);
            if (imageJobCard) content.appendChild(imageJobCard);

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
        renderAll: renderAll,
        syncImageJobUiTimer: syncImageJobUiTimer,
        __test: {
            markdownHtml,
            codeTestEvidence,
            codeTestEvidenceLabel,
            codeApplyEvidenceValid,
            renderCodeTestEvidence,
            batchFailureDetail,
            formatImageJobDuration,
            imageJobPresentation,
            sessionNeedsImageJobUiTimer,
            syncImageJobUiTimer,
            renderImageArtifactCard,
            renderImageJobCard,
            renderAgentCard,
        }
    };

    document.addEventListener('mlx-language-changed', () => {
        window.MLXChatRendering?.renderMessages?.({
            contentUpdated: false
        });
    });

})();

/* Large hover preview for image attachments in chat messages. */
(function initImageAttachmentHoverPreview() {
    function removePreview() {
        document.querySelectorAll('.image-hover-preview')
            .forEach(element => element.remove());
    }

    document.addEventListener('mouseover', event => {
        const image = event.target.closest?.('.message-attachment-preview');
        if (!image) return;

        removePreview();

        const preview = document.createElement('img');
        preview.className = 'image-hover-preview';
        preview.src = image.src;
        preview.alt = image.alt || '';
        document.body.appendChild(preview);
    });

    document.addEventListener('mouseout', event => {
        const image = event.target.closest?.('.message-attachment-preview');
        if (!image) return;

        removePreview();
    });
})();
