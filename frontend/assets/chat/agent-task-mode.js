(() => {
    'use strict';

    let armed = false;
    let button = null;

    function t(key, fallback) {
        return window.MLXI18n?.t(key, fallback) ?? fallback;
    }

    function setArmed(value) {
        armed = Boolean(value);
        if (!button) return;
        button.classList.toggle('is-active', armed);
        button.setAttribute('aria-pressed', armed ? 'true' : 'false');
        button.title = armed
            ? t('agent_task_mode.disable_title', 'Task Mode ausschalten')
            : t('agent_task_mode.enable_title', 'Task Mode für die nächste Nachricht');
        const label = button.querySelector('[data-agent-task-label]');
        if (label) {
            label.textContent = armed
                ? t('agent_task_mode.active', 'Task Mode aktiv')
                : t('agent_task_mode.label', 'Task');
        }
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
        if (!response.ok) {
            throw new Error(await response.text());
        }
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
                error: t(
                    'agent_task_mode.workspace_check_failed',
                    'Der aktive Workspace konnte nicht geprüft werden.'
                ) + ' ' + (error?.message || '')
            };
        }

        if (!workspace?.workspace_id) {
            return {
                error: t(
                    'agent_task_mode.workspace_required',
                    'Task Mode benötigt einen aktiven Coding-Workspace. Öffne zuerst einen Workspace und starte die Aufgabe erneut.'
                )
            };
        }

        return {
            userGoal: String(prompt || '').trim(),
            executionGoal: executionGoal(prompt),
            workspaceId: workspace.workspace_id,
            workspaceName: workspace.name || workspace.root_path || workspace.workspace_id
        };
    }

    function mount() {
        if (document.getElementById('agentTaskModeButton')) {
            button = document.getElementById('agentTaskModeButton');
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
        button.innerHTML = '<span class="agent-task-mode-icon" aria-hidden="true">⌘</span><span data-agent-task-label></span>';
        button.addEventListener('click', () => setArmed(!armed));
        actions.insertBefore(button, dictation);
        setArmed(false);
    }

    document.addEventListener('mlx:i18n-ready', () => setArmed(armed));
    document.addEventListener('mlx:i18n-changed', () => setArmed(armed));

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
        mount();
    }

    window.MLXAgentTaskMode = {
        consume,
        executionGoal,
        isArmed: () => armed,
        setArmed,
        mount,
        __test: { activeWorkspace }
    };
})();
