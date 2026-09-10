(function () {
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
            session.title || 'Neuer Chat';

        entry.title =
            session.title || 'Neuer Chat';

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
            'Löschen';

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
        web_search: 'Websuche',
        model_list: 'Modelle',
        model_switch: 'Modellwechsel',
        model_restart: 'MLX-Neustart',
        system_status: 'Systemstatus',
        batch_status: 'Datei-Jobs',
        logs_query: 'Logs',
        pii_audit: 'PII-Audit',
        thinking_on: 'Thinking',
        thinking_off: 'Thinking',
        image_generate: 'Bildgenerierung',
        knowledge_search: 'Wissensbasis'
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
        status.textContent = 'Fehler';
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
            return 'Docker-Container prüfen';
        }

        if (/docker\s+logs/i.test(query)) {
            return 'Logs prüfen';
        }

        if (/docker\s+inspect/i.test(query)) {
            return 'Container prüfen';
        }

        if (/curl/i.test(query)) {
            return 'Erreichbarkeit prüfen';
        }

        return 'System prüfen';
    }

    const labels = {
        system_status: 'Systemstatus prüfen',
        process_usage: 'CPU- und RAM-intensive Prozesse prüfen',
        logs_query: 'Logs prüfen',
        batch_status: 'Datei-Jobs prüfen',
        knowledge_search: 'Wissensbasis durchsuchen',
        code_search: 'Relevanten Code suchen',
        code_files: 'Projektstruktur analysiert',
        code_read: 'Relevante Datei untersucht',
        code_patch: fileCount
            ? fileCount + ' Änderungen vorbereitet'
            : 'Änderungen vorbereitet',
        code_diff: fileCount
            ? 'Gesamt-Diff für ' + fileCount + ' Dateien erstellt'
            : 'Gesamt-Diff erstellt',
        code_test: result.passed === true
            ? (fileCount
                ? fileCount + ' Dateien getestet · Tests bestanden'
                : 'Tests bestanden')
            : 'Change-Set getestet',
        code_apply: fileCount
            ? fileCount + ' Dateien angewendet'
            : 'Change-Set angewendet',
        agent_plan: 'Nächsten Schritt planen',
        agent_error: 'Agent-Fehler',
        web_search: 'Web durchsuchen',
        search_web: 'Web durchsuchen',
        fetch_url: 'Quelle öffnen',
        docker_restart: 'Container neu starten',
        verify_change: 'Änderung überprüfen',
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
            '⚠ Aktion benötigt Freigabe';

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
            ? (pending.target || 'Container') + ' neu starten'
            : pending.operation === 'code_apply' && approvalFileCount
                ? approvalFileCount + ' Dateien anwenden'
                : String(pending.operation || 'Aktion').replace(/_/g, ' ');

        approval.appendChild(operation);

        if (pending.operation === 'code_apply' && approvalFileCount) {
            const summary = document.createElement('div');
            summary.className = 'agent-change-summary';

            const counts = document.createElement('div');
            counts.className = 'agent-change-counts';
            counts.textContent = [
                '+ ' + Number(changeSummary.create || 0) + ' neu',
                '~ ' + Number(changeSummary.modify || 0) + ' geändert',
                '− ' + Number(changeSummary.delete || 0) + ' gelöscht'
            ].join('  ·  ');
            summary.appendChild(counts);

            const testStatus = document.createElement('div');
            testStatus.className = 'agent-change-tests';
            testStatus.textContent = pending.tests?.passed
                ? '✓ Tests bestanden'
                : '⚠ Tests nicht bestätigt';
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
                detailsTitle.textContent = 'Betroffene Dateien';
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
                : 'Ausführen';

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
    const title = document.createElement('strong'); title.textContent = artifact.name || 'Erzeugte Datei';
    const details = document.createElement('div'); details.className = 'batch-chat-details';
    details.textContent = [
        artifact.size != null ? formatBytes(artifact.size) : '',
        artifact.extension ? artifact.extension.toUpperCase() : '',
        message.batch_job?.processing_mode ? message.batch_job.processing_mode.toUpperCase() : '',
        message.batch_job?.pii_audit ? 'PII-Audit verfügbar' : ''
    ].filter(Boolean).join(' · ');
    card.appendChild(title); card.appendChild(details);
    const controls = document.createElement('div'); controls.className = 'batch-chat-controls';
    const download = document.createElement('a'); download.className = 'message-action-btn'; download.textContent = 'Download'; download.href = '/api/mlx/batch/' + encodeURIComponent(artifact.last_job_id) + '/download'; controls.appendChild(download);
    ['Ergebnis analysieren', 'Ergebnis zusammenfassen', 'PII Audit'].forEach(label => {
        const button = document.createElement('button'); button.className = 'message-action-btn'; button.textContent = label;
        button.addEventListener('click', () => {
            const input = document.getElementById('input');
            input.value = label === 'Ergebnis analysieren' ? 'Analysiere das Ergebnis.' : label === 'Ergebnis zusammenfassen' ? 'Fasse die erzeugte Datei zusammen.' : 'Mach einen PII Audit.';
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
    title.textContent = job.status === 'completed' ? (analysisJob ? '✓ Analyse abgeschlossen' : '✓ Verarbeitung abgeschlossen') :
        job.status === 'failed' ? (analysisJob ? 'Analyse fehlgeschlagen' : 'Verarbeitung fehlgeschlagen') :
        (analysisJob ? 'Datei wird analysiert' : 'Datei wird verarbeitet');
    const details = document.createElement('div');
    details.className = 'batch-chat-details';
    const eta = Number(job.eta_seconds || 0);
    details.textContent = [
        'Datei: ' + (message.batch_filename || 'Anhang'),
        analysisJob ? 'Operation: ' + ({ inspect: 'Inspektion', analyze: 'Analyse', summarize: 'Zusammenfassung' }[job.operation] || 'Analyse') :
            'Modus: ' + String(job.processing_mode || job.instruction_plan?.mode || 'wird bestimmt').toUpperCase(),
        'Fortschritt: ' + done + ' / ' + (total || '…') + ' (' + percent + ' %)',
        'MLX-Aufrufe: ' + Number(job.mlx_calls || 0),
        'LLM übersprungen: ' + Number(job.skipped_llm_chunks || 0),
        job.pii_audit ? 'PII-Audit: ' + (Object.values(job.pii_audit).every(value => value === 0) ? 'keine offensichtlichen Treffer' : 'restliche Treffer gefunden') : '',
        eta ? 'ETA: ' + Math.ceil(eta / 60) + ' Minuten' : ''
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
        job.status || 'unbekannt';

    if (
        job.status === 'queued' &&
        job.requires_start_choice
    ) {
        action('Kontrolliert starten', 'start');
        action('Alles automatisch', 'automatic-start');
        action('Abbrechen', 'cancel');
    } else if (
        job.status === 'paused' &&
        job.waiting_for_user
    ) {
        action('Weiter', 'resume');
        action('Rest automatisch', 'automatic');
        action('Abbrechen', 'cancel');
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
            action('Fortsetzen', 'resume');
        }

        if (
            job.status === 'running' ||
            job.status === 'queued' ||
            job.status === 'paused'
        ) {
            action('Abbrechen', 'cancel');
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
    const title = document.createElement('strong'); title.textContent = 'Lokales Bild';
    const image = document.createElement('img');
    image.className = 'image-artifact-preview';
    image.src = '/api/mlx/images/' + encodeURIComponent(artifact.image_id);
    image.alt = artifact.prompt || 'Generiertes Bild';
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
        input.value = 'Erstelle ein Bild von ' + (artifact.prompt || 'diesem Motiv');
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
        button.textContent = artifact.name || artifact.output_name || 'Erzeugte Datei';
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
                <div class="empty-logo"><img src="/assets/mlx-nobby.svg" alt="MLX Nobby"></div>
                <h1>Bereit für deine nächste geniale Idee?</h1>
                <p>
                    <span>Frag, diktier, lade hoch – Nobby ist am Start. 😎</span>
                    <span class="empty-local">Alles läuft lokal auf deinem Mac.</span>
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
                    'MLX Nobby denkt'
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
                sourcesHeader.textContent = 'Quellen';

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
                            'Lokale Wissensbasis'
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

            if (metrics) {
                content.appendChild(metrics);
            }

            enhanceCodeBlocks(content);

            const actions =
                document.createElement('div');

            actions.className =
                'message-actions';

            const copy =
                document.createElement('button');

            copy.className =
                'message-action-btn';

            copy.textContent =
                'Kopieren';

            copy.addEventListener(
                'click',
                async () => {
                    await navigator.clipboard.writeText(
                        message.content
                    );

                    copy.textContent =
                        'Kopiert';

                    setTimeout(
                        () => {
                            copy.textContent =
                                'Kopieren';
                        },
                        1200
                    );
                }
            );

            actions.appendChild(copy);

            const isLast =
                index ===
                session.messages.length - 1;

            if (isLast) {
                const regenerate =
                    document.createElement('button');

                regenerate.className =
                    'message-action-btn';

                regenerate.textContent =
                    'Neu generieren';

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
                            file.name || 'Bild';

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
                        file.name || 'Datei';

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
                                  file.record_count.toLocaleString('de-DE') +
                                  ' Datensätze'
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
                'message-action-btn';

            edit.textContent =
                'Bearbeiten';

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
})();
