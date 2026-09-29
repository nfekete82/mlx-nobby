(() => {
    'use strict';

    const SCRIPT_VERSION = '20260929-task-mode-v2';
    const CSS_ID = 'mlx-agent-task-mode-css';
    const FALLBACK = {
        chat_label: 'Chat',
        task_label: 'Task',
        chat_title: 'Use normal chat mode',
        task_title: 'Use Agent Task Mode for this workspace',
        task_unavailable_title: 'Select a coding workspace to use Task Mode',
        workspace_required: 'Task Mode requires an active coding workspace. Open a workspace first and start the task again.',
        workspace_check_failed: 'The active workspace could not be checked.',
        attachments_unsupported: 'Task Mode v1 currently works with the active coding workspace only. Remove attached files before starting the task.',
        running: 'Agent Task Mode is working …',
        failed: 'Agent Task Mode failed: {message}'
    };

    let mode = 'chat';
    let running = false;
    let workspace = null;
    let switcher = null;
    let chatButton = null;
    let taskButton = null;
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

    function installCss() {
        if (
            typeof document === 'undefined' ||
            document.getElementById?.(CSS_ID) ||
            !document.head?.appendChild
        ) return;
        const link = document.createElement('link');
        link.id = CSS_ID;
        link.rel = 'stylesheet';
        link.href = '/assets/chat/agent-task-mode.css?v=' + SCRIPT_VERSION;
        document.head.appendChild(link);
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

    function updateSwitch() {
        if (!switcher || !chatButton || !taskButton) return;

        const hasWorkspace = Boolean(workspace?.workspace_id);
        if (!hasWorkspace && mode === 'task') mode = 'chat';

        const taskActive = mode === 'task' && hasWorkspace;
        chatButton.classList.toggle('is-active', !taskActive);
        taskButton.classList.toggle('is-active', taskActive);
        chatButton.setAttribute('aria-pressed', taskActive ? 'false' : 'true');
        taskButton.setAttribute('aria-pressed', taskActive ? 'true' : 'false');

        chatButton.disabled = running;
        taskButton.disabled = running || !hasWorkspace;
        chatButton.textContent = t('chat_label');
        taskButton.textContent = t('task_label');
        chatButton.title = t('chat_title');
        taskButton.title = hasWorkspace
            ? t('task_title')
            : t('task_unavailable_title');

        switcher.classList.toggle('is-running', running);
        switcher.classList.toggle('has-workspace', hasWorkspace);
        switcher.dataset.mode = taskActive ? 'task' : 'chat';
        switcher.title = !hasWorkspace
            ? t('task_unavailable_title')
            : '';
    }

    function setMode(nextMode) {
        const requested = nextMode === 'task' ? 'task' : 'chat';
        if (requested === 'task' && !workspace?.workspace_id) {
            mode = 'chat';
        } else if (!running) {
            mode = requested;
        }
        updateSwitch();
        return mode;
    }

    function executionGoal(userGoal) {
        return [
            'AGENT TASK MODE v1',
            '',
            'User goal:',
            String(userGoal || '').trim(),
            '',
            'Execution contract:',
            '1. Work only inside the bound coding workspace.',
            '2. Inspect the project before proposing changes. Prefer workspace_search/workspace_read and git_status/git_diff.',
            '3. Form a concise implementation plan from evidence before any mutation.',
            '4. Prepare changes with code_prepare. Let the existing coding runtime perform code_diff and code_test on the isolated patch before it requests approval for code_apply. Never bypass that approval flow.',
            '5. If patch tests fail, inspect the failure and attempt at most three repair cycles. Each new mutation must use the normal prepare/diff/test/approval path.',
            '6. After approval, rely on the existing code_apply and verification path; do not perform an unrelated second mutation.',
            '7. Do not use unrestricted shell commands when a workspace/code tool can do the job.',
            '8. Finish with a concise summary containing changed files, isolated test result, apply/verification status, and patch/diff information. Mention that an applied patch can be reverted with code_revert when a patch id is available.',
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

    async function syncWorkspaceState() {
        try {
            workspace = await activeWorkspace();
        } catch (_error) {
            workspace = null;
        }
        if (!workspace?.workspace_id && mode === 'task') mode = 'chat';
        updateSwitch();
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
        if (mode !== 'task') return null;

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
        updateSwitch();

        if (!workspace?.workspace_id) {
            setMode('chat');
            return { error: t('workspace_required') };
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
        updateSwitch();
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
        if (mode !== 'task' || running) return false;
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
            if (mode !== 'task' || running) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            startFromComposer();
        }, true);
        input?.addEventListener('keydown', event => {
            if (
                mode !== 'task' || running || event.isComposing ||
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

    function mountSwitch() {
        if (switcher) return true;
        const workspaceHeader = document.getElementById('activeWorkspaceHeader');
        if (!workspaceHeader?.parentNode) return false;

        switcher = document.createElement('div');
        switcher.id = 'agentTaskModeSwitch';
        switcher.className = 'agent-task-mode-switch';
        switcher.setAttribute('role', 'group');

        chatButton = document.createElement('button');
        chatButton.id = 'agentChatModeButton';
        chatButton.className = 'agent-task-mode-option';
        chatButton.type = 'button';
        chatButton.addEventListener('click', () => setMode('chat'));

        taskButton = document.createElement('button');
        taskButton.id = 'agentTaskModeButton';
        taskButton.className = 'agent-task-mode-option';
        taskButton.type = 'button';
        taskButton.addEventListener('click', async () => {
            await syncWorkspaceState();
            setMode('task');
        });

        switcher.append(chatButton, taskButton);
        workspaceHeader.insertAdjacentElement('afterend', switcher);
        updateSwitch();
        return true;
    }

    function mount() {
        installCss();
        installApprovalAdapter();
        if (!mountSwitch()) return;
        interceptComposer();
        observeWorkspaceHeader();
        syncWorkspaceState();
    }

    async function refreshLanguage() {
        dictionary = {};
        await loadDictionary();
        updateSwitch();
    }

    window.MLXAgentTaskMode = {
        consume,
        executionGoal,
        getMode: () => mode,
        isArmed: () => mode === 'task',
        isRunning: () => running,
        setArmed: value => setMode(value ? 'task' : 'chat'),
        setMode,
        startFromComposer,
        syncWorkspaceState,
        mount,
        __test: {
            activeWorkspace,
            conversationContext,
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
