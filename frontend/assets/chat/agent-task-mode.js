(() => {
    'use strict';

    const SCRIPT_VERSION = '20260929-task-mode-v1';
    const CSS_ID = 'mlx-agent-task-mode-css';
    const FALLBACK = {
        label: 'Task',
        active: 'Task Mode active',
        enable_title: 'Use Task Mode for the next message',
        disable_title: 'Disable Task Mode',
        workspace_required: 'Task Mode requires an active coding workspace. Open a workspace first and start the task again.',
        workspace_check_failed: 'The active workspace could not be checked.',
        starting: 'Starting Agent Task Mode …'
    };

    let armed = false;
    let button = null;
    let dictionary = {};

    function t(key) {
        return dictionary[key] || FALLBACK[key] || key;
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

    function setArmed(value) {
        armed = Boolean(value);
        if (!button) return;
        button.classList.toggle('is-active', armed);
        button.setAttribute('aria-pressed', armed ? 'true' : 'false');
        button.title = armed ? t('disable_title') : t('enable_title');
        const label = button.querySelector('[data-agent-task-label]');
        if (label) label.textContent = armed ? t('active') : t('label');
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
            '4. Prepare changes with code_prepare. Never bypass the existing approval flow for code_apply.',
            '5. After an approved patch is applied, run the workspace test suite with code_test.',
            '6. If tests fail, inspect the failure and attempt at most three repair cycles. Each new mutation must use the normal prepare/apply approval path.',
            '7. Do not use unrestricted shell commands when a workspace/code tool can do the job.',
            '8. Finish with a concise summary containing changed files, test result, and patch/diff information. Mention that the applied patch can be reverted with code_revert when a patch id is available.',
            '9. If the workspace evidence is insufficient or the requested change is unsafe, stop and explain instead of guessing.'
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

    async function consume({ prompt } = {}) {
        if (!armed) return null;
        setArmed(false);

        let workspace = null;
        try {
            workspace = await activeWorkspace();
        } catch (error) {
            return {
                error: t('workspace_check_failed') + ' ' +
                    (error?.message || '')
            };
        }

        if (!workspace?.workspace_id) {
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

    function mount() {
        installCss();
        if (document.getElementById('agentTaskModeButton')) {
            button = document.getElementById('agentTaskModeButton');
            setArmed(armed);
            return;
        }

        const actions = document.querySelector('.composer-actions');
        const dictation = document.getElementById('dictationButton');
        if (!actions || !dictation) return;

        button = document.createElement('button');
        button.id = 'agentTaskModeButton';
        button.className = 'agent-task-mode-button';
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        button.innerHTML =
            '<span class="agent-task-mode-icon" aria-hidden="true">⌘</span>' +
            '<span data-agent-task-label></span>';
        button.addEventListener('click', () => setArmed(!armed));
        actions.insertBefore(button, dictation);
        setArmed(false);
    }

    async function refreshLanguage() {
        dictionary = {};
        await loadDictionary();
        setArmed(armed);
    }

    window.MLXAgentTaskMode = {
        consume,
        executionGoal,
        isArmed: () => armed,
        setArmed,
        mount,
        __test: { activeWorkspace, t }
    };

    loadDictionary().finally(mount);
    document.addEventListener('mlx-i18n-ready', refreshLanguage);
    document.addEventListener('mlx-language-changed', refreshLanguage);
})();
