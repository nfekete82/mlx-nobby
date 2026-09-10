
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
        'Speichern & neu generieren';

    const cancel =
        document.createElement('button');

    cancel.className =
        'message-action-btn edit-cancel';

    cancel.textContent =
        'Abbrechen';

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
                'Zusätzliche Dateien des Benutzers:'
            )
                ? message.content.substring(
                    message.content.indexOf(
                        'Zusätzliche Dateien des Benutzers:'
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
     * Alles nach der bearbeiteten Nachricht
     * wird verworfen.
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
    content.textContent = 'Lade Vorgänge…';
    return fetch('/api/mlx/batch').then(response => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
    }).then(data => {
        const jobs = (data.jobs || []).slice(0, 8);
        content.innerHTML = jobs.length ? jobs.map(job => {
            const active = ['queued', 'running', 'paused'].includes(job.status);
            const progress = job.total_chunks ? Math.round((job.processed_chunks || 0) / job.total_chunks * 100) + ' %' : (active ? 'Verarbeitung läuft' : 'Fertig');
            return '<div class="jobs-panel-item"><strong>' + (job.output_name || job.original_name || job.input_name || 'Datei') + '</strong><span>' + (job.operation || 'Dateioperation') + ' · ' + progress + '</span></div>';
        }).join('') : 'Keine aktiven Dateioperationen.';
    }).catch(() => { content.textContent = 'Vorgänge sind momentan nicht verfügbar.'; });
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
            ? 'Seitenleiste öffnen'
            : 'Seitenleiste schließen'
    );

    sidebarToggle.setAttribute(
        'title',
        collapsed
            ? 'Seitenleiste öffnen'
            : 'Seitenleiste schließen'
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


/* MLX Nobby Mini Sidebar Rail */

const railExpand =
    document.getElementById('railExpand');

const railChats =
    document.getElementById('railChats');

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

    status.textContent = 'Modellrollen werden geladen…';

    try {
        const [rolesResponse, aliasesResponse] =
            await Promise.all([
                fetch('/api/mlx/model-roles'),
                fetch('/api/mlx/aliases'),
            ]);

        if (!rolesResponse.ok) {
            throw new Error(
                'Modellrollen HTTP ' + rolesResponse.status
            );
        }

        if (!aliasesResponse.ok) {
            throw new Error(
                'Modelle HTTP ' + aliasesResponse.status
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
                'Automatisch' +
                (
                    resolution.alias
                        ? ' (' + resolution.alias + ')'
                        : ''
                );

            select.appendChild(automatic);

            for (const model of models) {
                const option =
                    document.createElement('option');

                option.value = model.alias;
                option.textContent =
                    model.alias +
                    (
                        model.active
                            ? ' · aktiv'
                            : ''
                    );

                select.appendChild(option);
            }

            select.value = current;

            if (select.value !== current) {
                select.value = 'auto';
            }
        }

        status.textContent =
            models.length +
            ' Modelle verfügbar · Rollen werden nur gespeichert';
    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;
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
                'Fehler: ' + error.message;
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
    WORKSPACE_NOT_FOUND: 'Der ausgewählte Ordner existiert nicht mehr.',
    WORKSPACE_ROOT_UNAVAILABLE: 'Der aktive Workspace ist nicht mehr verfügbar.',
    WORKSPACE_PERMISSION_DENIED: 'Keine Berechtigung für diesen Ordner.',
    FOLDER_PICKER_UNAVAILABLE: 'Der macOS-Ordnerdialog ist nicht verfügbar.',
    FOLDER_PICKER_FAILED: 'Der Ordnerdialog konnte nicht geöffnet werden.',
    WORKSPACE_CHANGED: 'Der aktive Workspace wurde zwischenzeitlich gewechselt.'
};

function workspaceErrorMessage(error) {
    const code = String(error?.message || error || '');
    return WORKSPACE_ERRORS[code] || code || 'Workspace-Aktion fehlgeschlagen.';
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
    const feedback = document.getElementById('workspaceFeedback');
    if (feedback) feedback.textContent = message;
}

function renderActiveWorkspace(workspace) {
    const badge = document.getElementById('activeWorkspaceBadge');
    if (!badge) return;

    if (!workspace) {
        badge.hidden = true;
        badge.textContent = '';
        badge.removeAttribute('title');
        return;
    }

    badge.hidden = false;
    badge.textContent = '📁 ' + workspace.name;
    badge.title = workspace.root_path;
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
        if (data.active_workspace && data.active_workspace.available === false) {
            showWorkspaceFeedback(WORKSPACE_ERRORS.WORKSPACE_ROOT_UNAVAILABLE);
        }
        if (!target) return;

        target.replaceChildren();
        if (!spaces.length) {
            target.textContent = 'Noch keine Code-Workspaces.';
            return;
        }

        spaces.forEach(space => {
            const item = document.createElement('div');
            item.className = 'jobs-panel-item';
            const name = document.createElement('strong');
            name.textContent = space.name + (space.active ? ' · aktiv' : '');
            const path = document.createElement('span');
            path.textContent = space.root_path;
            path.title = space.root_path;
            const actions = document.createElement('span');

            if (!space.active) {
                actions.appendChild(workspaceActionButton('Aktivieren', '/activate', space.workspace_id));
                actions.append(' ');
            }
            actions.appendChild(workspaceActionButton('Neu indexieren', '/refresh', space.workspace_id));
            actions.append(' ');
            actions.appendChild(workspaceActionButton('Entfernen', '', space.workspace_id));
            item.append(name, path, actions);
            target.appendChild(item);
        });
    } catch (error) {
        renderActiveWorkspace(null);
        if (target) target.textContent = 'Code-Workspaces sind momentan nicht verfügbar.';
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
                throw new Error('Die Backup-Datei ist größer als 20 MB');
            }

            const imported = MLXChatSessions.importBackup(
                await file.text()
            );

            alert(imported + ' Chat(s) importiert.');

        } catch (error) {
            alert('Import fehlgeschlagen: ' + error.message);
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
            return 'Dienst nicht erreichbar';
        }

        return service.detail || 'Bereit';
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
            service.name || 'Dienst'
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
                'Dienststatus konnte nicht geladen werden'
            ),
            createTextElement(
                'span',
                '',
                message || 'Unbekannter Fehler'
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
                    name: 'Lokale Dienste',
                    online: false,
                    detail: 'Agent nicht erreichbar',
                });
            }

            if (webResult.status === 'fulfilled') {
                services.push({
                    name: 'Web / Docker',
                    online: Boolean(webResult.value.payload.ok),
                    port: Number(window.location.port) || 8090,
                    latency_ms: webResult.value.latency_ms,
                    detail: 'NobbyMLX Web-App',
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
                    `Zuletzt geprüft ${new Date().toLocaleTimeString('de-DE')}`;
            }
        } catch (error) {
            renderServiceHealthError(error?.message);

            if (updated) {
                updated.textContent = 'Status nicht verfügbar';
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
