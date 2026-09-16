function chatT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${name}}`,
            String(replacement ?? '')
        );
    }

    return value;
}


const chatState = {
    sessions: [],
    activeId: null
};

let generating = false;
let abortController = null;

const input = document.getElementById('input');
const messagesInner = document.getElementById('messagesInner');
const messagesElement = document.getElementById('messages');
const sendButton = document.getElementById('sendButton');

marked.setOptions({
    breaks: true,
    gfm: true
});


function startEditMessage(index, article) {
    if (
        generating ||
        MLXChatRuntime.isSwitching()
    ) return;

    const session =
        MLXChatSessions.currentSession();

    if (!session) return;

    const message =
        session.messages[index];

    if (!message) return;

    if (message.role !== 'user') {
        return;
    }

    const body =
        article.children[1];

    const oldContent =
        body.querySelector(
            '.message-content'
        );

    const oldActions =
        body.querySelector(
            '.message-actions'
        );

    if (!oldContent) return;

    oldContent.style.display =
        'none';

    if (oldActions) {
        oldActions.style.display =
            'none';
    }

    const wrap =
        document.createElement('div');

    wrap.className =
        'edit-message-wrap';

    const textarea =
        document.createElement(
            'textarea'
        );

    textarea.className =
        'edit-message-textarea';

    textarea.value =
        message.display_content ??
        message.content;

    const buttons =
        document.createElement('div');

    buttons.className =
        'edit-message-actions';

    const save =
        document.createElement('button');

    save.className =
        'message-action-btn edit-save';

    save.textContent =
        chatT('ui.save_regenerate', 'Save & regenerate');

    const cancel =
        document.createElement('button');

    cancel.className =
        'message-action-btn edit-cancel';

    cancel.textContent =
        chatT('common.cancel', 'Cancel');

    save.addEventListener(
        'click',
        async () => {
            const value =
                textarea.value.trim();

            if (!value) return;

            await saveEditedMessage(
                index,
                value
            );
        }
    );

    cancel.addEventListener(
        'click',
        () => {
            MLXChatRendering.renderMessages();
        }
    );

    buttons.appendChild(save);
    buttons.appendChild(cancel);

    wrap.appendChild(textarea);
    wrap.appendChild(buttons);

    body.appendChild(wrap);

    textarea.focus();

    textarea.setSelectionRange(
        textarea.value.length,
        textarea.value.length
    );
}


async function saveEditedMessage(index, value) {
    if (
        generating ||
        MLXChatRuntime.isSwitching()
    ) return;

    const session =
        MLXChatSessions.currentSession();

    if (!session) return;

    const message =
        session.messages[index];

    if (!message) return;

    if (message.role !== 'user') {
        return;
    }

    message.display_content =
        value;

    if (
        message.attachments &&
        message.attachments.length
    ) {
        const fileContext =
            message.content.includes(
                chatT('ui.user_files', 'Additional user files:')
            )
                ? message.content.substring(
                    message.content.indexOf(
                        chatT('ui.user_files', 'Additional user files:')
                    )
                )
                : '';

        message.content =
            fileContext
                ? value + '\n\n' + fileContext
                : value;

    } else {
        message.content =
            value;
    }

    /*
     * Discard everything after the edited message.
     */
    session.messages =
        session.messages.slice(
            0,
            index + 1
        );

    session.updated =
        Date.now();

    MLXChatSessions.saveSessions();

    MLXChatRuntime.beginUserMessage();
    MLXChatRendering.renderAll({
        contentUpdated: true
    });

    await MLXChatCompact.autoCompactIfNeeded(
        session
    );

    await MLXChatGeneration.generateAssistant(
        session
    );
}



document.getElementById(
    'newChat'
).addEventListener(
    'click',
    () => {
        if (!generating) {
            MLXChatSessions.createSession();
        }
    }
);


document.getElementById(
    'clearButton'
).addEventListener(
    'click',
    MLXChatSessions.deleteMessages
);


document.getElementById(
    'settingsButton'
).addEventListener(
    'click',
    () => {
        window.MLXChatSettings.open('general');
    }
);

document.getElementById('sidebarSettingsButton').addEventListener('click', () => {
    window.MLXChatSettings.open('general');
});

function loadJobsPanel() {
    const content = document.getElementById('jobsPanelContent');
    content.textContent = chatT('ui.jobs_loading', 'Loading jobs…');
    return fetch('/api/mlx/batch').then(response => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
    }).then(data => {
        const jobs = (data.jobs || []).slice(0, 8);
        content.innerHTML = jobs.length ? jobs.map(job => {
            const active = ['queued', 'running', 'paused'].includes(job.status);
            const progress = job.total_chunks ? Math.round((job.processed_chunks || 0) / job.total_chunks * 100) + ' %' : (active ? chatT('ui.processing_running', 'Processing') : chatT('ui.completed', 'Completed'));
            return '<div class="jobs-panel-item"><strong>' + (job.output_name || job.original_name || job.input_name || chatT('ui.file', 'File')) + '</strong><span>' + (job.operation || chatT('ui.file_operation', 'File operation')) + ' · ' + progress + '</span></div>';
        }).join('') : chatT('ui.no_active_file_jobs', 'No active file operations.');
    }).catch(() => { content.textContent = chatT('ui.jobs_unavailable', 'Jobs are currently unavailable.'); });
}

window.MLXHistoryCleanup?.mount(document.getElementById('jobsPanelCleanup'), {
    kind: 'batch', onComplete: loadJobsPanel,
});
document.getElementById('sidebarJobsButton').addEventListener('click', () => {
    document.getElementById('jobsPanel').hidden = false;
    loadJobsPanel();
});
document.getElementById('jobsPanelClose').addEventListener('click', () => { document.getElementById('jobsPanel').hidden = true; });

const sidebarToggle =
    document.getElementById('sidebarToggle');

const sidebarCollapseButton =
    document.getElementById('sidebarCollapseButton');

const appShell =
    document.querySelector('.app');

const sidebar =
    document.querySelector('.sidebar');

function setDesktopSidebarCollapsed(collapsed) {

    appShell.classList.toggle(
        'sidebar-collapsed',
        collapsed
    );

    localStorage.setItem(
        'mlx-nobby-sidebar-collapsed',
        collapsed ? '1' : '0'
    );

    sidebarToggle.setAttribute(
        'aria-label',
        collapsed
            ? chatT('ui.open_sidebar', 'Open sidebar')
            : chatT('ui.close_sidebar', 'Close sidebar')
    );

    sidebarToggle.setAttribute(
        'title',
        collapsed
            ? chatT('ui.open_sidebar', 'Open sidebar')
            : chatT('ui.close_sidebar', 'Close sidebar')
    );
}

function restoreSidebarState() {

    if (
        window.matchMedia(
            '(min-width: 901px)'
        ).matches
    ) {
        const collapsed =
            localStorage.getItem(
                'mlx-nobby-sidebar-collapsed'
            ) === '1';

        setDesktopSidebarCollapsed(
            collapsed
        );
    }
}

sidebarToggle.addEventListener(
    'click',
    () => {

        if (
            window.matchMedia(
                '(max-width: 900px)'
            ).matches
        ) {
            sidebar.classList.toggle(
                'mobile-open'
            );

            return;
        }

        setDesktopSidebarCollapsed(
            !appShell.classList.contains(
                'sidebar-collapsed'
            )
        );
    }
);

sidebarCollapseButton?.addEventListener(
    'click',
    () => {
        setDesktopSidebarCollapsed(true);
    }
);

restoreSidebarState();


/* MLX nobby Mini Sidebar Rail */

const railExpand =
    document.getElementById('railExpand');

const railChats =
    document.getElementById('railChats');


/* MLX-NOBBY-CONFIRM-MODAL-JS */

function showConfirmModal({
    title = 'Bestätigung',
    message = 'Möchtest du fortfahren?',
    confirmLabel = 'OK',
    cancelLabel = 'Cancel',
} = {}) {
    return new Promise(resolve => {
        const modal =
            document.getElementById('confirmModal');

        const titleElement =
            document.getElementById('confirmModalTitle');

        const messageElement =
            document.getElementById('confirmModalMessage');

        const confirmButton =
            document.getElementById('confirmModalConfirm');

        const cancelButton =
            document.getElementById('confirmModalCancel');

        if (
            !modal ||
            !titleElement ||
            !messageElement ||
            !confirmButton ||
            !cancelButton
        ) {
            resolve(false);
            return;
        }

        let settled = false;

        titleElement.textContent = title;
        messageElement.textContent = message;
        confirmButton.textContent = confirmLabel;
        cancelButton.textContent = cancelLabel;

        function cleanup() {
            confirmButton.removeEventListener(
                'click',
                onConfirm
            );

            cancelButton.removeEventListener(
                'click',
                onCancel
            );

            modal.removeEventListener(
                'click',
                onBackdrop
            );

            document.removeEventListener(
                'keydown',
                onKeydown
            );
        }

        function finish(result) {
            if (settled) {
                return;
            }

            settled = true;

            modal.hidden = true;
            modal.setAttribute(
                'aria-hidden',
                'true'
            );

            cleanup();
            resolve(result);
        }

        function onConfirm() {
            finish(true);
        }

        function onCancel() {
            finish(false);
        }

        function onBackdrop(event) {
            if (
                event.target.matches(
                    '[data-confirm-dismiss]'
                )
            ) {
                finish(false);
            }
        }

        function onKeydown(event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                finish(false);
                return;
            }

            if (event.key === 'Enter') {
                event.preventDefault();
                finish(true);
            }
        }

        confirmButton.addEventListener(
            'click',
            onConfirm
        );

        cancelButton.addEventListener(
            'click',
            onCancel
        );

        modal.addEventListener(
            'click',
            onBackdrop
        );

        document.addEventListener(
            'keydown',
            onKeydown
        );

        modal.hidden = false;
        modal.setAttribute(
            'aria-hidden',
            'false'
        );

        requestAnimationFrame(() => {
            confirmButton.focus();
        });
    });
}

window.MLXConfirm = showConfirmModal;

/* MLX-NOBBY-CONFIRM-MODAL-JS-END */

const railNewChat =
    document.getElementById('railNewChat');

const railJobs =
    document.getElementById('railJobs');

const railSettings =
    document.getElementById('railSettings');


function openDesktopSidebar() {

    setDesktopSidebarCollapsed(false);
}


railExpand?.addEventListener(
    'click',
    openDesktopSidebar
);

railChats?.addEventListener(
    'click',
    openDesktopSidebar
);

railNewChat?.addEventListener(
    'click',
    () => {
        document
            .getElementById('newChat')
            ?.click();
    }
);

railJobs?.addEventListener(
    'click',
    () => {
        document
            .getElementById('sidebarJobsButton')
            ?.click();
    }
);

railSettings?.addEventListener(
    'click',
    () => {
        document
            .getElementById('sidebarSettingsButton')
            ?.click();
    }
);

(function () {
    const settings = document.getElementById('settings');
    const mainTabs = new Set([
        'general',
        'models-system',
        'knowledge',
        'profile',
        'appearance',
    ]);
    const systemTabs = new Set([
        'models',
        'generation',
        'runtime',
        'storage',
        'server',
        'logs',
    ]);
    const systemPane = {
        models: 'models',
        generation: 'generation',
        runtime: 'models',
        storage: 'models',
        server: 'system',
        logs: 'logs',
    };
    const legacySystemTab = {
        models: 'models',
        generation: 'generation',
        runtime: 'runtime',
        storage: 'storage',
        speicher: 'storage',
        system: 'server',
        server: 'server',
        logs: 'logs',
    };
    let activeMainTab = 'general';
    let activeSystemTab = 'models';

    function pane(tab) {
        return settings.querySelector('[data-settings-pane="' + tab + '"]');
    }

    function setSelected(button, selected) {
        button.classList.toggle('active', selected);
        button.setAttribute('aria-selected', selected ? 'true' : 'false');
    }

    function updateLocation() {
        const path = activeMainTab === 'models-system'
            ? '/settings/models-system/' + activeSystemTab
            : '/settings/' + activeMainTab;
        history.replaceState(null, '', path);
    }

    function ensureAdminFrame(tab) {
        if (!['server', 'logs'].includes(tab)) return;
        const target = pane(systemPane[tab])
            ?.querySelector('[data-control-view="' + tab + '"]');
        if (!target || target.querySelector('iframe')) return;

        const frame = document.createElement('iframe');
        frame.className = 'settings-admin-frame';
        frame.title = tab === 'server'
            ? 'MLX Server- und Systemverwaltung'
            : 'MLX Logs';
        frame.src = '/control?embedded=1#' + tab;
        target.appendChild(frame);
    }

    function showPane(name) {
        settings.querySelectorAll('[data-settings-pane]').forEach(item => {
            item.hidden = item.dataset.settingsPane !== name;
        });
    }

    function selectSystem(tab, updateHistory = true) {
        if (!systemTabs.has(tab)) tab = 'models';
        activeMainTab = 'models-system';
        activeSystemTab = tab;

        showPane(systemPane[tab]);
        settings.querySelector('.settings-subtabs').hidden = false;
        settings.querySelectorAll('[data-settings-tab]').forEach(button => {
            setSelected(button, button.dataset.settingsTab === 'models-system');
        });
        settings.querySelectorAll('[data-settings-system-tab]').forEach(button => {
            setSelected(button, button.dataset.settingsSystemTab === tab);
        });

        if (['models', 'runtime', 'storage'].includes(tab)) {
            window.MLXModelConsole?.setTab(tab);
            window.MLXModelConsole?.open();
            if (tab === 'models') {
                loadModelRoles();
                window.MLXImageSettings?.load();
            }
        } else {
            window.MLXModelConsole?.close();
        }

        ensureAdminFrame(tab);
        if (updateHistory) updateLocation();
    }

    function selectMain(tab, updateHistory = true) {
        if (!mainTabs.has(tab)) tab = 'general';
        if (tab === 'models-system') {
            selectSystem(activeSystemTab, updateHistory);
            return;
        }

        activeMainTab = tab;
        showPane(tab);
        settings.querySelector('.settings-subtabs').hidden = true;
        settings.querySelectorAll('[data-settings-tab]').forEach(button => {
            setSelected(button, button.dataset.settingsTab === tab);
        });
        window.MLXModelConsole?.close();
        if (tab === 'knowledge') window.MLXKnowledge?.loadStatus?.();
        if (tab === 'profile') window.MLXProfile?.load?.();
        if (updateHistory) updateLocation();
    }

    function select(tab) {
        if (mainTabs.has(tab)) selectMain(tab);
        else if (legacySystemTab[tab]) selectSystem(legacySystemTab[tab]);
        else selectMain('general');
    }

    function open(tab = 'general') {
        settings.classList.add('open');
        select(tab);
    }

    function close() {
        settings.classList.remove('open');
        window.MLXModelConsole?.close();
        if (location.pathname.startsWith('/settings')) {
            history.replaceState(null, '', '/chat');
        }
    }

    settings.querySelectorAll('[data-settings-tab]').forEach(button => {
        button.addEventListener('click', () => selectMain(button.dataset.settingsTab));
    });
    settings.querySelectorAll('[data-settings-system-tab]').forEach(button => {
        button.addEventListener('click', () => selectSystem(button.dataset.settingsSystemTab));
    });
    document.getElementById('settingsClose').addEventListener('click', close);
    window.MLXChatSettings = { open, close, select, selectSystem };

    if (location.pathname.startsWith('/settings')) {
        const parts = location.pathname
            .replace(/^\/settings\/?/, '')
            .split('/')
            .filter(Boolean)
            .map(part => decodeURIComponent(part).toLowerCase());
        const first = parts[0] || 'general';

        settings.classList.add('open');
        if (first === 'models-system') {
            selectSystem(legacySystemTab[parts[1]] || 'models');
        } else if (legacySystemTab[first]) {
            selectSystem(legacySystemTab[parts[1]] || legacySystemTab[first]);
        } else {
            selectMain(first);
        }
    }
})();



async function loadModelRoles() {
    const status = document.getElementById('modelRolesStatus');
    const selects = Array.from(
        document.querySelectorAll('[data-model-role]')
    );

    if (!status || !selects.length) return;

    status.textContent = chatT('ui.loading_model_roles', 'Loading model roles…');

    try {
        const [rolesResponse, aliasesResponse] =
            await Promise.all([
                fetch('/api/mlx/model-roles'),
                fetch('/api/mlx/aliases'),
            ]);

        if (!rolesResponse.ok) {
            throw new Error(
                chatT(
                'ui.model_roles_http_error',
                'Model roles HTTP {status}',
                { status: rolesResponse.status }
            )
            );
        }

        if (!aliasesResponse.ok) {
            throw new Error(
                chatT(
                'ui.models_http_error',
                'Models HTTP {status}',
                { status: aliasesResponse.status }
            )
            );
        }

        const rolesData = await rolesResponse.json();
        const aliasesData = await aliasesResponse.json();

        const roles = rolesData.roles || {};
        const resolved = rolesData.resolved || {};
        const models = Array.isArray(aliasesData.models)
            ? aliasesData.models
            : [];

        for (const select of selects) {
            const role = select.dataset.modelRole;
            const current = roles[role] || 'auto';
            const resolution = resolved[role] || {};

            select.innerHTML = '';

            const automatic =
                document.createElement('option');

            automatic.value = 'auto';
            automatic.textContent =
                chatT('ui.automatic', 'Automatic') +
                (
                    resolution.alias
                        ? ' (' + resolution.alias + ')'
                        : ''
                );

            select.appendChild(automatic);

            for (const model of models) {
                if (role === 'embedding' && !model.embedding_compatible) continue;
                const option =
                    document.createElement('option');

                option.value = model.alias;
                option.textContent =
                    model.alias +
                    (
                        model.active
                            ? chatT('ui.active_suffix', ' · active')
                            : ''
                    );

                select.appendChild(option);
            }

            if (current !== 'auto' && !Array.from(select.options).some(option => option.value === current)) {
                const incompatible = document.createElement('option');
                incompatible.value = current;
                incompatible.textContent = current + ' (incompatible)';
                incompatible.disabled = true;
                select.appendChild(incompatible);
            }

            select.value = current;
        }

        status.textContent = chatT(
            'ui.models_available_roles_only',
            '{count} models available · roles are only saved',
            { count: models.length }
        );
    } catch (error) {
        status.textContent =
            chatT(
            'ui.error',
            'Error: {message}',
            { message: error.message }
        );
    }
}


async function saveModelRole(select) {
    const role = select.dataset.modelRole;
    const alias = select.value;
    const status =
        document.getElementById('modelRolesStatus');

    select.disabled = true;

    if (status) {
        status.textContent =
            'Speichere ' + role + '…';
    }

    try {
        const response = await fetch(
            '/api/mlx/model-roles/' +
            encodeURIComponent(role),
            {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    alias: alias,
                }),
            }
        );

        let data = null;

        try {
            data = await response.json();
        } catch {}

        if (!response.ok) {
            throw new Error(
                data?.detail ||
                ('HTTP ' + response.status)
            );
        }

        if (status) {
            status.textContent =
                role +
                ' → ' +
                alias +
                ' gespeichert';
        }

        await loadModelRoles();
    } catch (error) {
        if (status) {
            status.textContent =
                chatT(
            'ui.error',
            'Error: {message}',
            { message: error.message }
        );
        }

        await loadModelRoles();
    } finally {
        select.disabled = false;
    }
}


document
    .querySelectorAll('[data-model-role]')
    .forEach(select => {
        select.addEventListener(
            'change',
            () => saveModelRole(select)
        );
    });


const WORKSPACE_ERRORS = {
    WORKSPACE_NOT_FOUND: chatT('ui.workspace_missing', 'The selected folder no longer exists.'),
    WORKSPACE_ROOT_UNAVAILABLE: chatT('ui.workspace_root_unavailable', 'The active workspace is no longer available.'),
    WORKSPACE_PERMISSION_DENIED: chatT('ui.workspace_permission_denied', 'No permission for this folder.'),
    FOLDER_PICKER_UNAVAILABLE: chatT('ui.folder_picker_unavailable', 'The macOS folder picker is unavailable.'),
    FOLDER_PICKER_FAILED: chatT('ui.folder_picker_failed', 'The folder picker could not be opened.'),
    WORKSPACE_CHANGED: chatT('ui.workspace_changed', 'The active workspace changed during the operation.')
};

function workspaceErrorMessage(error) {
    const code = String(error?.message || error || '');
    return WORKSPACE_ERRORS[code] || code || chatT('ui.workspace_action_failed', 'Workspace action failed.');
}

async function workspaceRequest(path, options = {}) {
    const response = await fetch(path, options);
    let data = {};

    try {
        data = await response.json();
    } catch (error) {
        data = {};
    }

    if (!response.ok) {
        throw new Error(data.detail || ('HTTP ' + response.status));
    }

    return data;
}

function showWorkspaceFeedback(message = '') {
    [
        document.getElementById('workspaceFeedback'),
        document.getElementById('workspaceSettingsFeedback')
    ].filter(Boolean).forEach(feedback => {
        feedback.textContent = message;
    });
}

let activeWorkspaceSettings = null;

function renderWorkspaceTestCommands(workspace) {
    activeWorkspaceSettings = workspace || null;
    const input = document.getElementById('workspaceTestCommands');
    const save = document.getElementById('workspaceTestsSave');
    const detect = document.getElementById('workspaceTestsDetect');
    if (!input || !save) return;

    input.disabled = !workspace;
    save.disabled = !workspace;
    if (detect) {
        detect.disabled = !workspace;
    }
    clearWorkspaceTestDetection();
    input.value = workspace
        ? JSON.stringify(workspace.test_commands || [], null, 2)
        : '';
}

function clearWorkspaceTestDetection() {
    const panel = document.getElementById('workspaceTestDetection');
    const list = document.getElementById('workspaceTestDetectionList');
    const use = document.getElementById('workspaceTestsUseDetected');

    if (list) {
        list.replaceChildren();
    }

    if (panel) {
        panel.hidden = true;
    }

    if (use) {
        use.disabled = true;
    }
}

function renderWorkspaceTestDetection(result) {
    const panel = document.getElementById('workspaceTestDetection');
    const list = document.getElementById('workspaceTestDetectionList');
    const use = document.getElementById('workspaceTestsUseDetected');

    if (!panel || !list || !use) {
        return;
    }

    list.replaceChildren();

    const entries = [
        ...(Array.isArray(result?.detected) ? result.detected : []),
        ...(Array.isArray(result?.recommended) ? result.recommended : [])
    ];

    if (!entries.length) {
        const empty = document.createElement('p');
        empty.className = 'settings-hint';
        empty.textContent = chatT(
            'ui.workspace_tests_detect_none',
            'No test commands were detected.'
        );
        list.appendChild(empty);
        panel.hidden = false;
        use.disabled = true;
        return;
    }

    entries.forEach(entry => {
        if (
            !entry ||
            !Array.isArray(entry.command) ||
            !entry.command.length ||
            !entry.command.every(
                part => typeof part === 'string' && part.length > 0
            )
        ) {
            return;
        }

        const row = document.createElement('label');
        row.className = 'workspace-test-detection-item';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'workspace-test-detection-checkbox';
        checkbox.dataset.command = JSON.stringify(entry.command);
        checkbox.checked = entry.available !== false;

        const body = document.createElement('span');

        const command = document.createElement('code');
        command.textContent = entry.command.join(' ');

        const meta = document.createElement('small');

        const metadata = [
            entry.source,
            entry.confidence
        ].filter(Boolean);

        if (entry.available === false) {
            metadata.push(chatT(
                'ui.workspace_tests_detect_unavailable',
                'unavailable'
            ));
        }

        meta.textContent = metadata.join(' · ');

        body.append(command);

        if (metadata.length) {
            body.append(document.createElement('br'), meta);
        }

        row.append(checkbox, body);
        list.appendChild(row);
    });

    panel.hidden = false;

    use.disabled = !list.querySelector(
        '.workspace-test-detection-checkbox'
    );
}

function parseWorkspaceTestCommands(value) {
    let commands;
    try {
        commands = JSON.parse(String(value || '').trim() || '[]');
    } catch (error) {
        throw new Error(chatT(
            'ui.workspace_test_commands_invalid_json',
            'Test commands must be valid JSON.'
        ));
    }

    if (
        !Array.isArray(commands) ||
        !commands.every(command =>
            Array.isArray(command) &&
            command.length > 0 &&
            command.every(part => typeof part === 'string' && part.length > 0)
        )
    ) {
        throw new Error(chatT(
            'ui.workspace_test_commands_invalid_shape',
            'Use a JSON list containing one argument list per command.'
        ));
    }

    return commands;
}

function renderActiveWorkspace(workspace) {
    const badge = document.getElementById('activeWorkspaceBadge');
    const header = document.getElementById('activeWorkspaceHeader');
    const headerButton = document.getElementById('activeWorkspaceHeaderButton');
    const headerClose = document.getElementById('activeWorkspaceHeaderClose');

    if (badge) {
        if (!workspace) {
            badge.hidden = true;
            badge.textContent = '';
            badge.removeAttribute('title');
        } else {
            badge.hidden = false;
            badge.textContent = '📁 ' + workspace.name;
            badge.title = workspace.root_path;
        }
    }

    if (!header || !headerButton || !headerClose) {
        return;
    }

    if (!workspace) {
        header.dataset.active = 'false';
        headerButton.textContent = chatT('ui.workspace_open', '📁 Open workspace');
        headerButton.title = chatT('ui.workspace_select', 'Select workspace');
        headerClose.hidden = true;
        return;
    }

    const rootPath = String(workspace.root_path || '');
    const home = rootPath.startsWith('/Users/')
        ? rootPath.split('/').slice(0, 3).join('/')
        : '';

    const displayPath = home && rootPath.startsWith(home)
        ? '~' + rootPath.slice(home.length)
        : rootPath;

    header.dataset.active = 'true';
    headerButton.textContent =
        '📁 ' + workspace.name + ' · ' + displayPath;
    headerButton.title = rootPath;
    headerClose.hidden = false;
}

function workspaceActionButton(label, action, workspaceId) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'message-action-btn';
    button.textContent = label;
    button.addEventListener('click', async () => {
        button.disabled = true;
        showWorkspaceFeedback('');
        try {
            await workspaceRequest(
                '/api/mlx/code/workspaces/' + encodeURIComponent(workspaceId) + action,
                { method: action === '' ? 'DELETE' : 'POST' }
            );
            await loadWorkspaces();
        } catch (error) {
            showWorkspaceFeedback(workspaceErrorMessage(error));
        } finally {
            button.disabled = false;
        }
    });
    return button;
}

async function loadWorkspaces() {
    const target = document.getElementById('workspaceList');

    try {
        const data = await workspaceRequest('/api/mlx/code/workspaces');
        const spaces = data.workspaces || [];
        renderActiveWorkspace(data.active_workspace || null);
        renderWorkspaceTestCommands(data.active_workspace || null);
        if (data.active_workspace && data.active_workspace.available === false) {
            showWorkspaceFeedback(WORKSPACE_ERRORS.WORKSPACE_ROOT_UNAVAILABLE);
        }
        if (!target) return;

        target.replaceChildren();
        if (!spaces.length) {
            target.textContent = chatT('ui.no_workspaces', 'No code workspaces yet.');
            return;
        }

        spaces.forEach(space => {
            const item = document.createElement('div');
            item.className = 'jobs-panel-item';
            const name = document.createElement('strong');
            name.textContent = space.name + (space.active ? chatT('ui.active_suffix', ' · active') : '');
            const path = document.createElement('span');
            path.textContent = space.root_path;
            path.title = space.root_path;
            const actions = document.createElement('span');

            if (!space.active) {
                actions.appendChild(workspaceActionButton(chatT('ui.enable', 'Enable'), '/activate', space.workspace_id));
                actions.append(' ');
            }
            actions.appendChild(workspaceActionButton(chatT('ui.workspace_reindex', 'Reindex'), '/refresh', space.workspace_id));
            actions.append(' ');
            actions.appendChild(workspaceActionButton(chatT('ui.workspace_remove', 'Remove'), '', space.workspace_id));
            item.append(name, path, actions);
            target.appendChild(item);
        });
    } catch (error) {
        renderActiveWorkspace(null);
        if (target) target.textContent = chatT('ui.workspaces_unavailable', 'Code workspaces are currently unavailable.');
        showWorkspaceFeedback(workspaceErrorMessage(error));
    }
}

async function openWorkspacePicker() {
    const buttons = [
        document.getElementById('workspacePickerButton'),
        document.getElementById('workspacePickerSettings')
    ].filter(Boolean);
    buttons.forEach(button => { button.disabled = true; });
    showWorkspaceFeedback('');

    try {
        const result = await workspaceRequest(
            '/api/mlx/code/workspaces/pick',
            { method: 'POST' }
        );
        if (result.status === 'cancelled') return;
        await loadWorkspaces();
    } catch (error) {
        showWorkspaceFeedback(workspaceErrorMessage(error));
    } finally {
        buttons.forEach(button => { button.disabled = false; });
    }
}

const activeWorkspaceHeaderButton = document.getElementById(
    'activeWorkspaceHeaderButton'
);

if (activeWorkspaceHeaderButton) {
    activeWorkspaceHeaderButton.addEventListener(
        'click',
        openWorkspacePicker
    );
}

const activeWorkspaceHeaderClose = document.getElementById(
    'activeWorkspaceHeaderClose'
);

if (activeWorkspaceHeaderClose) {
    activeWorkspaceHeaderClose.addEventListener('click', async event => {
        event.stopPropagation();
        activeWorkspaceHeaderClose.disabled = true;

        try {
            await workspaceRequest(
                '/api/mlx/code/workspaces/active',
                {
                    method: 'DELETE',
                }
            );

            await loadWorkspaces();

        } catch (error) {
            showWorkspaceFeedback(
                workspaceErrorMessage(error)
            );

        } finally {
            activeWorkspaceHeaderClose.disabled = false;
        }
    });
}


const workspacePickerButton = document.getElementById('workspacePickerButton');
if (workspacePickerButton) {
    workspacePickerButton.addEventListener('click', openWorkspacePicker);
}

const workspacePickerSettings = document.getElementById('workspacePickerSettings');
if (workspacePickerSettings) {
    workspacePickerSettings.addEventListener('click', openWorkspacePicker);
}

const workspaceAdd = document.getElementById('workspaceAdd');
if (workspaceAdd) {
    workspaceAdd.addEventListener('click', async () => {
        const input = document.getElementById('workspacePath');
        if (!input) return;

        const path = input.value.trim();
        if (!path) return;

        showWorkspaceFeedback('');

        try {
            await workspaceRequest('/api/mlx/code/workspaces', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({path})
            });

            input.value = '';
            await loadWorkspaces();

        } catch (error) {
            showWorkspaceFeedback(workspaceErrorMessage(error));
        }
    });
}

const workspaceTestsDetect = document.getElementById('workspaceTestsDetect');

if (workspaceTestsDetect) {
    workspaceTestsDetect.addEventListener('click', async () => {
        if (!activeWorkspaceSettings) {
            return;
        }

        workspaceTestsDetect.disabled = true;
        showWorkspaceFeedback('');
        clearWorkspaceTestDetection();

        try {
            const result = await workspaceRequest(
                '/api/mlx/code/workspaces/' +
                encodeURIComponent(activeWorkspaceSettings.workspace_id) +
                '/detect-tests'
            );

            renderWorkspaceTestDetection(result);

            showWorkspaceFeedback(chatT(
                'ui.workspace_tests_detect_complete',
                'Test command detection completed. Review the suggestions before applying them.'
            ));
        } catch (error) {
            showWorkspaceFeedback(workspaceErrorMessage(error));
        } finally {
            workspaceTestsDetect.disabled = !activeWorkspaceSettings;
        }
    });
}

const workspaceTestsUseDetected = document.getElementById(
    'workspaceTestsUseDetected'
);

if (workspaceTestsUseDetected) {
    workspaceTestsUseDetected.addEventListener('click', () => {
        const input = document.getElementById('workspaceTestCommands');
        const list = document.getElementById(
            'workspaceTestDetectionList'
        );

        if (!input || !list) {
            return;
        }

        const commands = Array.from(
            list.querySelectorAll(
                '.workspace-test-detection-checkbox:checked'
            )
        ).map(checkbox => {
            try {
                return JSON.parse(
                    checkbox.dataset.command || 'null'
                );
            } catch (error) {
                return null;
            }
        }).filter(command =>
            Array.isArray(command) &&
            command.length > 0 &&
            command.every(
                part => typeof part === 'string' && part.length > 0
            )
        );

        input.value = JSON.stringify(commands, null, 2);
        input.focus();

        showWorkspaceFeedback(chatT(
            'ui.workspace_tests_detect_applied',
            'Selected commands were copied into the editor. Save them to update the workspace.'
        ));
    });
}

const workspaceTestsSave = document.getElementById('workspaceTestsSave');
if (workspaceTestsSave) {
    workspaceTestsSave.addEventListener('click', async () => {
        const input = document.getElementById('workspaceTestCommands');
        if (!input || !activeWorkspaceSettings) return;

        workspaceTestsSave.disabled = true;
        showWorkspaceFeedback('');
        try {
            const testCommands = parseWorkspaceTestCommands(input.value);
            await workspaceRequest('/api/mlx/code/workspaces', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({
                    path: activeWorkspaceSettings.root_path,
                    name: activeWorkspaceSettings.name,
                    test_commands: testCommands
                })
            });
            showWorkspaceFeedback(chatT(
                'ui.workspace_test_commands_saved',
                'Test commands saved.'
            ));
            await loadWorkspaces();
        } catch (error) {
            showWorkspaceFeedback(workspaceErrorMessage(error));
        } finally {
            workspaceTestsSave.disabled = !activeWorkspaceSettings;
        }
    });
}

function openWorkspaceTestConfiguration() {
    window.MLXChatSettings?.open?.('general');
    loadWorkspaces();
    requestAnimationFrame(() => {
        document.getElementById('workspaceTestSettings')?.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
        document.getElementById('workspaceTestCommands')?.focus();
    });
}

window.MLXChatWorkspace = {
    load: loadWorkspaces,
    openTestConfiguration: openWorkspaceTestConfiguration,
    __test: {
        parseWorkspaceTestCommands,
        renderWorkspaceTestDetection,
        clearWorkspaceTestDetection
    }
};


document.getElementById(
    'settings'
).addEventListener(
    'input',
    event => {
        MLXChatRuntime.saveSettings();
        MLXChatRuntime.handleGlobalSettingsInput(event);
        MLXChatRuntime.handleSystemPromptInput(event);
    }
);


document.getElementById(
    'settings'
).addEventListener(
    'change',
    MLXChatRuntime.handleGlobalSettingsInput
);


document.getElementById(
    'systemPromptPreset'
).addEventListener(
    'change',
    MLXChatRuntime.handlePresetChange
);


document.getElementById('exportChatJson').addEventListener(
    'click',
    MLXChatSessions.exportCurrentJson
);

document.getElementById('exportChatMarkdown').addEventListener(
    'click',
    MLXChatSessions.exportCurrentMarkdown
);

document.getElementById('exportAllChats').addEventListener(
    'click',
    MLXChatSessions.exportAllChats
);

document.getElementById('importChatsButton').addEventListener(
    'click',
    () => document.getElementById('importChatsFile').click()
);

document.getElementById('importChatsFile').addEventListener(
    'change',
    async event => {
        const file = event.target.files[0];

        if (!file) return;

        try {
            if (file.size > 20 * 1024 * 1024) {
                throw new Error(chatT('ui.backup_too_large', 'The backup file is larger than 20 MB'));
            }

            const imported = MLXChatSessions.importBackup(
                await file.text()
            );

            alert(chatT('ui.chats_imported', '{count} chat(s) imported.', { count: imported }));

        } catch (error) {
            alert(chatT('ui.import_failed', 'Import failed: {message}', { message: error.message }));
        } finally {
            event.target.value = '';
        }
    }
);


input.addEventListener(
    'input',
    MLXChatRuntime.autoResize
);


input.addEventListener(
    'keydown',
    event => {
        if (
            event.key === 'Enter' &&
            !event.shiftKey
        ) {
            event.preventDefault();
            MLXChatGeneration.sendMessage();
        }
    }
);


sendButton.addEventListener(
    'click',
    MLXChatGeneration.sendMessage
);


document.addEventListener(
    'click',
    () => {
        document
            .querySelectorAll(
                '.chat-menu.open'
            )
            .forEach(menu => {
                menu.classList.remove(
                    'open'
                );
            });
    }
);


MLXChatRuntime.configure({
    isGenerating: () => generating
});

MLXChatGeneration.configure({
    getGenerating: () => generating,
    setGenerating: value => {
        generating = value;
    },
    getAbortController: () => abortController,
    setAbortController: value => {
        abortController = value;
    }
});

MLXChatSessions.configure({
    state: chatState,
    renderAll: () => MLXChatRendering.renderAll(),
    renderSidebar: () => MLXChatRendering.renderSidebar(),
    isGenerating: () => generating,
    createSessionSettings:
        MLXChatRuntime.createSessionSettings,
    onSessionSelected: () => {
        MLXChatRuntime.loadSessionSettings();
        MLXChatRuntime.resetScrollForChat();
        MLXChatGeneration.resumeImageJobsForSession(
            MLXChatSessions.currentSession()
        );
    }
});

MLXChatRendering.configure({
    state: chatState,
    currentSession: MLXChatSessions.currentSession,
    isGenerating: () => generating,
    selectSession: MLXChatSessions.selectSession,
    renameSession: MLXChatSessions.renameSession,
    deleteSession: MLXChatSessions.deleteSession,
    updateContext: MLXChatRuntime.updateContext,
    startEditMessage: startEditMessage,
    regenerateLastAnswer: MLXChatGeneration.regenerateLastAnswer
});

MLXChatAttachments.init();
MLXChatNotes.init();
MLXChatRuntime.initModelSwitcher();
MLXChatRuntime.initRuntimeInfoPopover();

MLXChatSessions.loadSessions();
MLXChatRuntime.loadSettings();

MLXChatRendering.renderAll();
MLXChatGeneration.resumeImageJobsForSession(
    MLXChatSessions.currentSession()
);
MLXChatSessions.syncWithServer();
MLXChatRuntime.loadStatus();
loadWorkspaces();

setInterval(
    MLXChatRuntime.loadStatus,
    5000
);

input.focus();


// ============================================================
// Composer + menu
// ============================================================

(function initComposerPlusMenu() {
    const plusButton = document.getElementById('composerPlusButton');
    const plusMenu = document.getElementById('composerPlusMenu');

    if (!plusButton || !plusMenu) return;

    function closePlusMenu() {
        plusMenu.hidden = true;
        plusButton.setAttribute('aria-expanded', 'false');
    }

    function openPlusMenu() {
        plusMenu.hidden = false;
        plusButton.setAttribute('aria-expanded', 'true');
    }

    function togglePlusMenu() {
        if (plusMenu.hidden) {
            openPlusMenu();
        } else {
            closePlusMenu();
        }
    }

    plusButton.addEventListener('click', event => {
        event.stopPropagation();
        togglePlusMenu();
    });

    plusMenu.addEventListener('click', event => {
        const item = event.target.closest('[data-plus-action]');
        if (!item) return;

        const action = item.dataset.plusAction;
        closePlusMenu();

        if (action === 'notes') {
            document.getElementById('notesButton')?.click();
            return;
        }

        if (action === 'file') {
            document.getElementById('attachButton')?.click();
            return;
        }

        if (action === 'workspace') {
            document.getElementById('workspacePickerButton')?.click();
        }
    });

    document.addEventListener('click', event => {
        if (
            !plusMenu.hidden &&
            !plusMenu.contains(event.target) &&
            !plusButton.contains(event.target)
        ) {
            closePlusMenu();
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !plusMenu.hidden) {
            closePlusMenu();
            plusButton.focus();
        }
    });
})();

(() => {
    const SERVICE_HEALTH_REFRESH_MS = 10000;
    let serviceHealthBusy = false;

    function serviceHealthElements() {
        return {
            grid: document.getElementById('serviceHealthGrid'),
            updated: document.getElementById('serviceHealthUpdated'),
            refresh: document.getElementById('serviceHealthRefresh'),
        };
    }

    function createTextElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        element.textContent = text;
        return element;
    }

    function serviceDetail(service) {
        if (!service.online) {
            return chatT('ui.service_unavailable', 'Service unavailable');
        }

        return service.detail || chatT('ui.ready', 'Ready');
    }

    function serviceMeta(service) {
        const parts = [];

        parts.push(service.online ? 'Online' : 'Offline');

        if (service.port) {
            parts.push(`Port ${service.port}`);
        }

        if (Number.isFinite(Number(service.latency_ms))) {
            parts.push(`${Math.round(Number(service.latency_ms))} ms`);
        }

        return parts.join(' · ');
    }

    function serviceExtra(service) {
        const parts = [];

        if (service.pid) {
            parts.push(`PID ${service.pid}`);
        }

        if (Number.isFinite(Number(service.memory_mb)) && Number(service.memory_mb) > 0) {
            parts.push(`${Number(service.memory_mb).toFixed(0)} MB RAM`);
        }

        return parts.join(' · ');
    }

    function createServiceCard(service) {
        const card = document.createElement('div');
        card.className = 'settings-service-card';
        card.dataset.online = service.online ? 'true' : 'false';

        const top = document.createElement('div');
        top.className = 'settings-service-card-top';

        const title = createTextElement(
            'strong',
            'settings-service-name',
            service.name || chatT('ui.service', 'Service')
        );

        const status = document.createElement('span');
        status.className = 'settings-service-status';

        const dot = document.createElement('span');
        dot.className = 'settings-service-status-dot';
        dot.setAttribute('aria-hidden', 'true');

        const statusText = createTextElement(
            'span',
            'settings-service-status-text',
            service.online ? 'Online' : 'Offline'
        );

        status.append(dot, statusText);
        top.append(title, status);

        const detail = createTextElement(
            'span',
            'settings-service-detail',
            serviceDetail(service)
        );

        const meta = createTextElement(
            'span',
            'settings-service-meta',
            serviceMeta(service)
        );

        card.append(top, detail, meta);

        const extra = serviceExtra(service);

        if (extra) {
            card.append(
                createTextElement(
                    'span',
                    'settings-service-extra',
                    extra
                )
            );
        }

        return card;
    }

    function renderServiceHealth(services) {
        const { grid } = serviceHealthElements();
        if (!grid) return;

        grid.replaceChildren();

        services.forEach(service => {
            grid.appendChild(createServiceCard(service));
        });
    }

    function renderServiceHealthError(message) {
        const { grid } = serviceHealthElements();
        if (!grid) return;

        const error = document.createElement('div');
        error.className = 'settings-service-error';

        error.append(
            createTextElement(
                'strong',
                '',
                chatT('ui.service_status_failed', 'Could not load service status')
            ),
            createTextElement(
                'span',
                '',
                message || chatT('ui.unknown_error', 'Unknown error')
            )
        );

        grid.replaceChildren(error);
    }

    async function fetchJsonWithLatency(url) {
        const started = performance.now();

        try {
            const response = await fetch(url, {
                cache: 'no-store',
                headers: {
                    Accept: 'application/json',
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();

            return {
                payload,
                latency_ms: Math.round(performance.now() - started),
            };
        } catch (error) {
            error.latency_ms = Math.round(performance.now() - started);
            throw error;
        }
    }

    async function loadServiceHealth() {
        const { grid, updated, refresh } = serviceHealthElements();

        if (!grid || serviceHealthBusy) return;

        serviceHealthBusy = true;

        if (refresh) {
            refresh.disabled = true;
        }

        try {
            const [nativeResult, webResult] = await Promise.allSettled([
                fetchJsonWithLatency('/api/mlx/services/health'),
                fetchJsonWithLatency('/api/health'),
            ]);

            let services = [];

            if (
                nativeResult.status === 'fulfilled' &&
                Array.isArray(nativeResult.value.payload.services)
            ) {
                services = nativeResult.value.payload.services.slice();
            } else {
                services.push({
                    name: chatT('ui.local_services', 'Local services'),
                    online: false,
                    detail: chatT('ui.agent_unavailable', 'Agent unavailable'),
                });
            }

            if (webResult.status === 'fulfilled') {
                services.push({
                    name: 'Web / Docker',
                    online: Boolean(webResult.value.payload.ok),
                    port: Number(window.location.port) || 8090,
                    latency_ms: webResult.value.latency_ms,
                    detail: 'MLX nobby Web-App',
                });
            } else {
                services.push({
                    name: 'Web / Docker',
                    online: false,
                    port: Number(window.location.port) || 8090,
                    latency_ms: webResult.reason?.latency_ms,
                    detail: null,
                });
            }

            renderServiceHealth(services);

            if (updated) {
                updated.textContent =
                    chatT('ui.last_checked', 'Last checked: {time}', {
                        time: new Date().toLocaleTimeString(window.MLXI18n?.getLocale?.() || 'en-US')
                    });
            }
        } catch (error) {
            renderServiceHealthError(error?.message);

            if (updated) {
                updated.textContent = chatT('ui.status_unavailable', 'Status unavailable');
            }
        } finally {
            serviceHealthBusy = false;

            if (refresh) {
                refresh.disabled = false;
            }
        }
    }

    function initServiceHealth() {
        const { grid, refresh } = serviceHealthElements();

        if (!grid) return;

        refresh?.addEventListener('click', loadServiceHealth);
        document.addEventListener('mlx-language-changed', loadServiceHealth);

        document
            .querySelector('[data-settings-system-tab="server"]')
            ?.addEventListener('click', () => {
                window.setTimeout(loadServiceHealth, 50);
            });

        loadServiceHealth();

        window.setInterval(() => {
            const pane = document.querySelector(
                '[data-settings-pane="system"]'
            );

            if (pane && !pane.hidden) {
                loadServiceHealth();
            }
        }, SERVICE_HEALTH_REFRESH_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener(
            'DOMContentLoaded',
            initServiceHealth,
            { once: true }
        );
    } else {
        initServiceHealth();
    }
})();


// MLX-NOBBY-COMPOSER-SINGLELINE
(function initSingleLineComposer() {

    function syncComposerMeta() {

        const workspace =
            document.getElementById('activeWorkspaceBadge');

        const workspaceValue =
            document.getElementById('composerWorkspaceValue');


        if (workspace && workspaceValue) {

            let text =
                (workspace.textContent || '')
                    .replace(/^📁\s*/, '')
                    .trim();

            workspaceValue.textContent =
                text || chatT('ui.no_workspace', 'No workspace');

            workspaceValue.title =
                workspace.title || text || '';
        }


        const contextText =
            document.getElementById('contextText');

        const composerContextText =
            document.getElementById('composerContextText');


        if (contextText && composerContextText) {

            const text =
                (contextText.textContent || '').trim();

            composerContextText.textContent =
                text || '0 Tokens · 0 %';
        }


        const contextFill =
            document.getElementById('contextFill');

        const composerContextFill =
            document.getElementById('composerContextFill');


        if (contextFill && composerContextFill) {

            composerContextFill.style.width =
                contextFill.style.width || '0%';

            const computed =
                window.getComputedStyle(contextFill);

            composerContextFill.style.backgroundColor =
                computed.backgroundColor;
        }
    }


    function updateComposerMode() {

        const composer =
            document.querySelector('.composer');

        const input =
            document.getElementById('input');


        if (!composer || !input) {
            return;
        }


        /*
         * 52px is the regular single-line height.
         *
         * scrollHeight increases reliably once text wraps or
         * the user presses Enter.
         */
        const multiline =
            input.value.includes('\n')
            || input.scrollHeight > 58;


        composer.classList.toggle(
            'composer-multiline',
            multiline
        );
    }


    function observe(element) {

        if (!element) {
            return;
        }


        const observer =
            new MutationObserver(syncComposerMeta);


        observer.observe(
            element,
            {
                subtree: true,
                childList: true,
                characterData: true,
                attributes: true,
                attributeFilter: [
                    'style',
                    'title',
                    'hidden'
                ]
            }
        );
    }


    function init() {

        const input =
            document.getElementById('input');

        const plusButton =
            document.getElementById('composerPlusButton');


        if (input) {

            input.addEventListener(
                'input',
                () => {
                    requestAnimationFrame(
                        updateComposerMode
                    );
                }
            );


            /*
             * Also respond when the existing autosize logic
             * changes the height.
             */
            if ('ResizeObserver' in window) {

                const resizeObserver =
                    new ResizeObserver(
                        updateComposerMode
                    );

                resizeObserver.observe(input);
            }
        }


        if (plusButton) {

            plusButton.addEventListener(
                'click',
                () => {
                    requestAnimationFrame(
                        syncComposerMeta
                    );
                }
            );
        }


        observe(
            document.getElementById(
                'activeWorkspaceBadge'
            )
        );

        observe(
            document.getElementById(
                'contextText'
            )
        );

        observe(
            document.getElementById(
                'contextFill'
            )
        );


        updateComposerMode();
        syncComposerMeta();
    }


    if (document.readyState === 'loading') {

        document.addEventListener(
            'DOMContentLoaded',
            init,
            { once: true }
        );

    } else {

        init();
    }

})();


// MLX-NOBBY-CENTERED-START
(function initCenteredChatStart() {

    let lastEmptyState = null;


    function getSession() {

        try {

            if (
                window.MLXChatSessions &&
                typeof MLXChatSessions.currentSession === 'function'
            ) {
                return MLXChatSessions.currentSession();
            }

        } catch (error) {
            console.debug(
                'Centered start: session not ready',
                error
            );
        }

        return null;
    }


    function updateCenteredChatState() {

        const session = getSession();

        if (!session) {
            return;
        }


        const messages =
            Array.isArray(session.messages)
                ? session.messages
                : [];


        const empty =
            messages.length === 0;


        if (empty === lastEmptyState) {
            return;
        }


        lastEmptyState = empty;


        document.body.classList.toggle(
            'mlx-empty-chat',
            empty
        );


        document.body.classList.toggle(
            'mlx-chat-started',
            !empty
        );
    }


    /*
     * renderMessages changes messagesInner whenever a chat is
     * loaded, cleared, or extended.
     *
     * This also covers:
     *
     * - creating a new chat
     * - opening an existing chat
     * - sending the first message
     * - clearing a chat
     */

    function observeMessages() {

        const messagesInner =
            document.getElementById('messagesInner');


        if (!messagesInner) {
            return;
        }


        const observer =
            new MutationObserver(() => {

                requestAnimationFrame(
                    updateCenteredChatState
                );

            });


        observer.observe(
            messagesInner,
            {
                childList: true,
                subtree: true
            }
        );
    }


    function init() {

        observeMessages();

        updateCenteredChatState();


        /*
         * Additional events make the switch happen on the first
         * submit instead of after a visible delay.
         */

        const input =
            document.getElementById('input');


        if (input) {

            input.addEventListener(
                'keydown',
                event => {

                    if (
                        event.key === 'Enter' &&
                        !event.shiftKey
                    ) {

                        requestAnimationFrame(
                            updateCenteredChatState
                        );
                    }

                }
            );

        }


        const sendButton =
            document.getElementById('sendButton');


        if (sendButton) {

            sendButton.addEventListener(
                'click',
                () => {

                    requestAnimationFrame(
                        updateCenteredChatState
                    );

                }
            );

        }


        /*
         * Safety net for session changes.
         *
         * Avoid continuous polling; update only when the window
         * becomes active again.
         */

        window.addEventListener(
            'focus',
            updateCenteredChatState
        );

    }


    if (document.readyState === 'loading') {

        document.addEventListener(
            'DOMContentLoaded',
            init,
            { once: true }
        );

    } else {

        init();
    }

})();


// MLX-NOBBY-STARTSCREEN-POLISH
(function initStartscreenPolish() {

    function currentSession() {
        try {
            return window.MLXChatSessions?.currentSession?.() || null;
        } catch (_) {
            return null;
        }
    }


    function hasMessages() {
        const session = currentSession();

        return Boolean(
            session &&
            Array.isArray(session.messages) &&
            session.messages.length
        );
    }


    function applyState(forceStarted = false) {

        const started =
            forceStarted || hasMessages();

        document.body.classList.toggle(
            'mlx-chat-started',
            started
        );

        document.body.classList.toggle(
            'mlx-empty-chat',
            !started
        );

        /*
         * The UI may become visible only now. This prevents an
         * incorrect intermediate state during reload.
         */
        document.body.classList.remove(
            'mlx-ui-booting'
        );
    }


    function init() {

        applyState();


        const messagesInner =
            document.getElementById('messagesInner');


        if (messagesInner) {

            new MutationObserver(() => {

                requestAnimationFrame(() => {
                    applyState();
                });

            }).observe(
                messagesInner,
                {
                    childList: true,
                    subtree: true
                }
            );

        }


        /*
         * Move to the bottom immediately on submit so the animation
         * does not wait for renderMessages() to finish.
         */

        const formInput =
            document.getElementById('input');

        if (formInput) {

            formInput.addEventListener(
                'keydown',
                event => {

                    if (
                        event.key === 'Enter' &&
                        !event.shiftKey &&
                        !event.isComposing &&
                        formInput.value.trim()
                    ) {
                        applyState(true);
                    }

                }
            );

        }


        const send =
            document.getElementById('sendButton');

        if (send) {

            send.addEventListener(
                'click',
                () => {

                    if (
                        document
                            .getElementById('input')
                            ?.value
                            ?.trim()
                    ) {
                        applyState(true);
                    }

                }
            );

        }

    }


    if (document.readyState === 'loading') {

        document.addEventListener(
            'DOMContentLoaded',
            init,
            { once: true }
        );

    } else {

        init();
    }

})();

// Initialize interface translations.
document.addEventListener('DOMContentLoaded', () => {
    window.MLXI18n?.init();
});


// ==========================================================
// MLX Nobby lifecycle controls
// ==========================================================

const powerButton = document.getElementById('powerButton');
const powerMenu = document.getElementById('powerMenu');

function closePowerMenu() {
    if (!powerButton || !powerMenu) return;

    powerMenu.hidden = true;
    powerButton.setAttribute(
        'aria-expanded',
        'false'
    );
}

function openPowerMenu() {
    if (!powerButton || !powerMenu) return;

    powerMenu.hidden = false;
    powerButton.setAttribute(
        'aria-expanded',
        'true'
    );
}

function updateLifecycleProgress(data) {
    const bar =
        document.getElementById('lifecycleProgressBar');

    const progressText =
        document.getElementById('lifecycleProgressText');

    const phase =
        document.getElementById('lifecycleProgressPhase');

    const busyText =
        document.getElementById('confirmModalBusyText');

    const current = Number(data.current || 0);
    const total = Number(data.total || 0);

    let percent = 0;

    if (total > 0) {
        percent = Math.max(
            0,
            Math.min(
                100,
                Math.round((current / total) * 100)
            )
        );
    }

    if (bar) {
        bar.style.width = percent + '%';
    }

    const percentText =
        document.getElementById('lifecycleProgressPercent');

    const track =
        document.querySelector(
            '#lifecycleProgress .lifecycle-progress-track'
        );

    if (percentText) {
        percentText.textContent = percent + ' %';
    }

    if (track) {
        track.setAttribute(
            'aria-valuenow',
            String(percent)
        );
    }

    if (progressText) {
        progressText.textContent =
            total > 0
                ? current + ' / ' + total
                : '';
    }

    if (phase) {
        phase.textContent =
            data.message || '';
    }

    if (busyText && data.message) {
        busyText.textContent = data.message;
    }
}


function showLifecycleFailure(message) {
    const modal =
        document.getElementById('confirmModal');

    const messageElement =
        document.getElementById('confirmModalMessage');

    const actions =
        modal?.querySelector('.app-modal-actions');

    const busy =
        document.getElementById('confirmModalBusy');

    if (busy) {
        busy.hidden = true;
    }

    if (messageElement) {
        messageElement.hidden = false;
        messageElement.textContent =
            chatT('ui.system_action_failed', 'System action failed: {message}', { message });
    }

    if (actions) {
        actions.hidden = false;
    }

    setLifecycleActionsDisabled(false);
}


async function waitForLifecycleProgress(action) {
    const deadline = Date.now() + 240000;

    let sawLifecycleState = false;
    let consecutiveErrors = 0;

    while (Date.now() < deadline) {
        try {
            const response = await fetch(
                '/api/mlx/system/lifecycle?_=' +
                    Date.now(),
                {
                    cache: 'no-store',
                }
            );

            if (!response.ok) {
                throw new Error(
                    'HTTP ' + response.status
                );
            }

            const data = await response.json();

            consecutiveErrors = 0;

            if (
                data.action === action &&
                data.state !== 'idle'
            ) {
                sawLifecycleState = true;
                updateLifecycleProgress(data);
            }

            if (
                data.action === action &&
                data.state === 'completed'
            ) {
                updateLifecycleProgress(data);

                await new Promise(
                    resolve =>
                        setTimeout(resolve, 700)
                );

                window.location.reload();
                return;
            }

            if (
                data.action === action &&
                data.state === 'failed'
            ) {
                updateLifecycleProgress(data);

                showLifecycleFailure(
                    data.error ||
                    data.message ||
                    chatT('ui.unknown_error', 'Unknown error')
                );

                return;
            }

        } catch (error) {
            /*
             * restart-all intentionally restarts the
             * agent. During that window the lifecycle
             * endpoint is temporarily unavailable.
             *
             * This is expected and must not turn the
             * modal into an error state.
             */
            consecutiveErrors += 1;

            if (
                sawLifecycleState &&
                consecutiveErrors < 40
            ) {
                const phase =
                    document.getElementById(
                        'lifecycleProgressPhase'
                    );

                if (phase) {
                    phase.textContent =
                        chatT('ui.services_restarting_progress', 'Services are restarting …');
                }
            }
        }

        await new Promise(
            resolve => setTimeout(resolve, 750)
        );
    }

    /*
     * Recovery fallback:
     * lifecycle polling should normally reach
     * "completed". If the agent transition caused us
     * to miss it, reload once and let the recovered
     * application establish the final state.
     */
    window.location.reload();
}


function showLifecycleBusyModal(title, message) {
    const modal =
        document.getElementById('confirmModal');

    const titleElement =
        document.getElementById('confirmModalTitle');

    const messageElement =
        document.getElementById('confirmModalMessage');

    const actions =
        modal?.querySelector('.app-modal-actions');

    const busy =
        document.getElementById('confirmModalBusy');

    const busyText =
        document.getElementById('confirmModalBusyText');

    const progress =
        document.getElementById('lifecycleProgress');

    const progressBar =
        document.getElementById('lifecycleProgressBar');

    const progressText =
        document.getElementById('lifecycleProgressText');

    const progressPhase =
        document.getElementById('lifecycleProgressPhase');

    const progressPercent =
        document.getElementById('lifecycleProgressPercent');

    const progressTrack =
        progress?.querySelector(
            '.lifecycle-progress-track'
        );

    if (
        !modal ||
        !titleElement ||
        !messageElement ||
        !actions ||
        !busy ||
        !busyText ||
        !progress
    ) {
        return;
    }

    titleElement.textContent = title;
    messageElement.hidden = true;

    actions.hidden = true;

    busy.hidden = false;
    busyText.textContent = message;

    progress.hidden = false;

    if (progressBar) {
        progressBar.style.width = '0%';
    }

    if (progressText) {
        progressText.textContent = '';
    }

    if (progressPhase) {
        progressPhase.textContent = 'Vorbereitung …';
    }

    if (progressPercent) {
        progressPercent.textContent = '0 %';
    }

    if (progressTrack) {
        progressTrack.setAttribute(
            'aria-valuenow',
            '0'
        );
    }

    modal.hidden = false;
}


function setLifecycleActionsDisabled(disabled) {
    document
        .querySelectorAll(
            '#powerMenu [data-lifecycle-action]'
        )
        .forEach(button => {
            button.disabled = disabled;
            button.setAttribute(
                'aria-disabled',
                String(disabled)
            );
        });

    if (powerButton) {
        powerButton.disabled = disabled;
    }
}


async function runLifecycleAction(action) {
    const config = {
        'restart-all': {
            title: chatT('ui.services_restart_title', 'Restart services'),
            confirm:
                chatT('ui.services_restart_confirm', 'Really restart all MLX Nobby services?'),
            confirmLabel:
                chatT('ui.services_restart_confirm_label', 'Restart'),
            busy:
                chatT('ui.services_restarting', 'MLX Nobby is restarting …'),
        },

        'rebuild-all': {
            title: chatT('ui.rebuild_all_title', 'Rebuild everything'),
            confirm:
                chatT('ui.rebuild_all_confirm', 'Completely rebuild MLX Nobby and then restart all services?'),
            confirmLabel:
                chatT('ui.rebuild_all_confirm_label', 'Rebuild'),
            busy:
                chatT('ui.rebuilding', 'MLX Nobby is being rebuilt …'),
        },
    };

    const current = config[action];

    if (!current) {
        return;
    }

    const confirmed = await showConfirmModal({
        title: current.title,
        message: current.confirm,
        confirmLabel: current.confirmLabel,
        cancelLabel: chatT('common.cancel', 'Cancel'),
    });

    if (!confirmed) {
        return;
    }

    closePowerMenu();

    showLifecycleBusyModal(
        current.title,
        current.busy
    );

    setLifecycleActionsDisabled(true);

    try {
        const response = await fetch(
            '/api/mlx/system/' + action,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: '{}',
            }
        );

        if (!response.ok) {
            const text = await response.text();

            throw new Error(
                text || ('HTTP ' + response.status)
            );
        }

        waitForLifecycleProgress(action);

    } catch (error) {
        const modal =
            document.getElementById('confirmModal');

        const messageElement =
            document.getElementById('confirmModalMessage');

        const actions =
            modal?.querySelector('.app-modal-actions');

        const busy =
            document.getElementById('confirmModalBusy');

        if (busy) {
            busy.hidden = true;
        }

        if (messageElement) {
            messageElement.hidden = false;
            messageElement.textContent =
                chatT('ui.system_action_failed', 'System action failed: {message}', { message: String(error.message || error) });
        }

        if (actions) {
            actions.hidden = false;
        }

        setLifecycleActionsDisabled(false);
    }
}

if (powerButton && powerMenu) {
    powerButton.addEventListener(
        'click',
        event => {
            event.stopPropagation();

            if (powerMenu.hidden) {
                openPowerMenu();
            } else {
                closePowerMenu();
            }
        }
    );

    powerMenu.addEventListener(
        'click',
        event => {
            const button = event.target.closest(
                '[data-lifecycle-action]'
            );

            if (!button) return;

            runLifecycleAction(
                button.dataset.lifecycleAction
            );
        }
    );

    document.addEventListener(
        'click',
        event => {
            if (
                !powerMenu.hidden &&
                !powerMenu.contains(event.target) &&
                event.target !== powerButton
            ) {
                closePowerMenu();
            }
        }
    );

    document.addEventListener(
        'keydown',
        event => {
            if (
                event.key === 'Escape' &&
                !powerMenu.hidden
            ) {
                closePowerMenu();
                powerButton.focus();
            }
        }
    );
}
