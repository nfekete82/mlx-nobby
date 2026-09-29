(() => {
    'use strict';

    const FALLBACK = {
        workspace_required: 'Workspace mode requires an active coding workspace.',
        workspace_check_failed: 'The active workspace could not be checked.',
        attachments_unsupported: 'Workspace mode currently works with the active coding workspace only. Remove attached files before starting the task.',
        failed: 'Workspace task failed: {message}'
    };

    let running = false;
    let workspace = null;
    let dictionary = {};
    let workspaceObserver = null;
    let workspaceSyncScheduled = false;

    function t(key, variables = {}) {
        let value = dictionary[key] || FALLBACK[key] || key;
        for (const [name, replacement] of Object.entries(variables)) {
            value = value.replaceAll('{' + name + '}', String(replacement ?? ''));
        }
        return value;
    }

    async function loadDictionary() {
        const language = String(
            window.MLXI18n?.getLanguage?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase().startsWith('de') ? 'de' : 'en';
        try {
            const response = await fetch(
                '/i18n/agent-task-mode.' + language + '.json',
                { cache: 'no-store' }
            );
            if (!response.ok) return;
            const data = await response.json();
            if (data && typeof data === 'object') dictionary = data;
        } catch (_error) {}
    }

    function executionGoal(userGoal) {
        return [
            'AGENT WORKSPACE MODE v1',
            '',
            'User goal:',
            String(userGoal || '').trim(),
            '',
            'Execution contract:',
            '1. Work only inside the bound coding workspace.',
            '2. Inspect the workspace first and decide whether the user is asking for a read-only answer or an actual mutation. Prefer workspace_search/workspace_read and git_status/git_diff.',
            '3. For read-only questions, analysis, explanations, searches, reviews, or diagnostics, answer from workspace evidence and do not prepare or apply a patch.',
            '4. Only when the user requests or clearly requires a workspace mutation, prepare changes with code_prepare. Let the existing coding runtime perform code_diff and code_test on the isolated patch before it requests approval for code_apply. Never bypass that approval flow.',
            '5. If patch tests fail, inspect the failure and attempt at most three repair cycles. Each new mutation must use the normal prepare/diff/test/approval path.',
            '6. After approval, rely on the existing code_apply and verification path; do not perform an unrelated second mutation.',
            '7. Do not use unrestricted shell commands when a workspace/code tool can do the job.',
            '8. For mutation tasks, finish with a concise summary containing changed files, isolated test result, apply/verification status, and patch/diff information. Mention that an applied patch can be reverted with code_revert when a patch id is available.',
            '9. If workspace evidence is insufficient or the requested change is unsafe, stop and explain instead of guessing.'
        ].join('\n');
    }

    async function activeWorkspace() {
        const response = await fetch('/api/mlx/code/workspaces', {
            cache: 'no-store'
        });
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        return data?.active_workspace || null;
    }

    function isWorkspaceMode() {
        return Boolean(workspace?.workspace_id);
    }

    function updateWorkspaceMarker() {
        const header = document.getElementById('activeWorkspaceHeader');
        if (!header) return;
        const active = isWorkspaceMode();
        header.dataset.agentMode = active ? 'task' : 'chat';
        header.setAttribute('data-workspace-task-active', active ? 'true' : 'false');
    }

    async function syncWorkspaceState() {
        try {
            workspace = await activeWorkspace();
        } catch (_error) {
            workspace = null;
        }
        updateWorkspaceMarker();
        return workspace;
    }

    function scheduleWorkspaceSync() {
        if (workspaceSyncScheduled) return;
        workspaceSyncScheduled = true;
        queueMicrotask(async () => {
            workspaceSyncScheduled = false;
            await syncWorkspaceState();
        });
    }

    async function consume({ prompt } = {}) {
        let currentWorkspace = null;
        try {
            currentWorkspace = await activeWorkspace();
        } catch (error) {
            return {
                error: t('workspace_check_failed') + ' ' +
                    (error?.message || '')
            };
        }

        workspace = currentWorkspace;
        updateWorkspaceMarker();

        if (!workspace?.workspace_id) {
            return null;
        }

        return {
            userGoal: String(prompt || '').trim(),
            executionGoal: executionGoal(prompt),
            workspaceId: workspace.workspace_id,
            workspaceName:
                workspace.name || workspace.root_path || workspace.workspace_id
        };
    }

    function conversationContext(session, currentMessage) {
        return (session?.messages || [])
            .filter(message =>
                message !== currentMessage &&
                ['user', 'assistant'].includes(message?.role)
            )
            .slice(-8)
            .map(message => ({
                role: message.role,
                content: String(
                    message.display_content || message.content || ''
                ).slice(0, 2000)
            }))
            .filter(message => message.content.trim());
    }

    function normalizeTaskGoals() {
        const session = window.MLXChatSessions?.currentSession?.();
        for (const message of session?.messages || []) {
            const userGoal = message?.task_mode?.user_goal;
            if (userGoal && message.agent_run) {
                message.agent_run.goal = userGoal;
            }
        }
    }

    function render() {
        normalizeTaskGoals();
        window.MLXChatSessions?.saveSessions?.();
        window.MLXChatRendering?.renderAll?.({ contentUpdated: true });
    }

    function setBusy(value) {
        running = Boolean(value);
        const input = document.getElementById('input');
        const send = document.getElementById('sendButton');
        if (input) input.disabled = running;
        if (send) send.disabled = running;
    }

    function installApprovalAdapter() {
        const generation = window.MLXChatGeneration;
        if (
            !generation?.approveAgentAction ||
            generation.__agentTaskModeApprovalAdapter
        ) return;

        generation.__agentTaskModeApprovalAdapter = true;
        const original = generation.approveAgentAction.bind(generation);
        generation.approveAgentAction = async (message, approved) => {
            const userGoal = message?.task_mode?.user_goal || null;
            const result = await original(message, approved);
            if (userGoal && message?.agent_run) {
                message.agent_run.goal = userGoal;
                render();
            }
            return result;
        };
    }

    async function runTask(task, session, userMessage, assistantMessage) {
        const controller = new AbortController();
        const runId = globalThis.crypto?.randomUUID
            ? globalThis.crypto.randomUUID()
            : 'task-' + Date.now().toString(16) +
                Math.random().toString(16).slice(2);
        let timer = null;

        assistantMessage.agent_run = {
            status: 'running',
            goal: task.userGoal,
            steps: [],
            pending_action: null
        };
        render();

        try {
            await window.MLXChatSessions?.persistSession?.(session);

            const poll = async () => {
                try {
                    const response = await fetch(
                        '/api/mlx/agent/runs/' + encodeURIComponent(runId),
                        { signal: controller.signal }
                    );
                    if (!response.ok) return;
                    const progress = await response.json();
                    if (!session.messages.includes(assistantMessage)) return;
                    const steps = Array.isArray(progress.steps)
                        ? [...progress.steps]
                        : [];
                    if (progress.current_step) steps.push(progress.current_step);
                    assistantMessage.agent_run = {
                        status: progress.status || 'running',
                        goal: task.userGoal,
                        steps,
                        pending_action: progress.pending_action || null
                    };
                    render();
                } catch (_error) {}
            };

            timer = setInterval(poll, 800);
            poll();

            const response = await fetch('/api/mlx/agent/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    goal: task.executionGoal,
                    mode: 'coding',
                    run_id: runId,
                    trace_id: userMessage.trace_id,
                    chat_id: session.id,
                    workspace_id: task.workspaceId,
                    workspace_bound: true,
                    conversation_context: conversationContext(
                        session,
                        userMessage
                    )
                }),
                signal: controller.signal
            });

            if (!response.ok) throw new Error(await response.text());
            const data = await response.json();
            if (!session.messages.includes(assistantMessage)) return;

            assistantMessage.agent_run = {
                status: data.status || 'completed',
                goal: task.userGoal,
                steps: Array.isArray(data.steps) ? data.steps : [],
                pending_action: data.pending_action || null
            };
            assistantMessage.content = data.answer || '';
            assistantMessage.model_metrics = data.model_metrics || null;
        } catch (error) {
            assistantMessage.agent_run = {
                ...(assistantMessage.agent_run || {}),
                status: 'failed',
                goal: task.userGoal,
                pending_action: null
            };
            assistantMessage.content = t('failed', {
                message: error?.message || String(error)
            });
        } finally {
            if (timer) clearInterval(timer);
            setBusy(false);
            render();
            document.getElementById('input')?.focus?.();
        }
    }

    async function startFromComposer() {
        if (!isWorkspaceMode() || running) return false;
        const input = document.getElementById('input');
        const prompt = String(input?.value || '').trim();
        if (!prompt) return true;

        const attachments = window.MLXChatAttachments?.getAttachments?.() || [];
        if (attachments.length) {
            window.alert?.(t('attachments_unsupported'));
            return true;
        }

        const session = window.MLXChatSessions?.currentSession?.();
        if (!session) return true;

        const task = await consume({ prompt });
        if (!task) return false;
        if (task.error) {
            session.messages.push({ role: 'assistant', content: task.error });
            render();
            return true;
        }

        const userMessage = {
            role: 'user',
            trace_id: globalThis.crypto?.randomUUID
                ? globalThis.crypto.randomUUID()
                : 'task-' + Date.now().toString(16),
            content: prompt,
            display_content: prompt,
            task_mode: true
        };
        const assistantMessage = {
            role: 'assistant',
            content: '',
            task_mode: {
                version: 1,
                user_goal: prompt,
                workspace_id: task.workspaceId,
                workspace_name: task.workspaceName
            }
        };

        session.messages.push(userMessage, assistantMessage);
        session.updated = Date.now();
        window.MLXChatSessions?.updateTitle?.(session);
        if (input) {
            input.value = '';
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
        setBusy(true);
        render();
        runTask(task, session, userMessage, assistantMessage);
        return true;
    }

    function interceptComposer() {
        const send = document.getElementById('sendButton');
        const input = document.getElementById('input');
        send?.addEventListener('click', event => {
            if (!isWorkspaceMode() || running) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            startFromComposer();
        }, true);
        input?.addEventListener('keydown', event => {
            if (
                !isWorkspaceMode() || running || event.isComposing ||
                event.key !== 'Enter' || event.shiftKey
            ) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            startFromComposer();
        }, true);
    }

    function observeWorkspaceHeader() {
        const header = document.getElementById('activeWorkspaceHeader');
        if (!header || workspaceObserver || typeof MutationObserver === 'undefined') {
            return;
        }
        workspaceObserver = new MutationObserver(scheduleWorkspaceSync);
        workspaceObserver.observe(header, {
            attributes: true,
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    function mount() {
        installApprovalAdapter();
        interceptComposer();
        observeWorkspaceHeader();
        syncWorkspaceState();
    }

    async function refreshLanguage() {
        dictionary = {};
        await loadDictionary();
    }

    window.MLXAgentTaskMode = {
        consume,
        executionGoal,
        isArmed: isWorkspaceMode,
        isRunning: () => running,
        getMode: () => isWorkspaceMode() ? 'task' : 'chat',
        setArmed: () => isWorkspaceMode(),
        setMode: () => isWorkspaceMode() ? 'task' : 'chat',
        startFromComposer,
        syncWorkspaceState,
        mount,
        __test: {
            activeWorkspace,
            conversationContext,
            isWorkspaceMode,
            normalizeTaskGoals,
            t
        }
    };

    loadDictionary().finally(mount);
    document.addEventListener('mlx-i18n-ready', refreshLanguage);
    document.addEventListener('mlx-language-changed', refreshLanguage);
    window.addEventListener('focus', scheduleWorkspaceSync);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) scheduleWorkspaceSync();
    });
})();
