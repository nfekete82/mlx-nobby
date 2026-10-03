(function () {
    'use strict';

    if (window.__mlxNobbySettingsLayout) return;
    window.__mlxNobbySettingsLayout = true;

    const SECTIONS = ['chat', 'models', 'knowledge', 'personal', 'tools', 'automations', 'system'];
    const MODEL_TABS = ['models', 'runtime', 'storage', 'downloads'];
    const SYSTEM_TABS = ['server', 'logs'];
    const FALLBACK = {
        title: 'Settings',
        chat: 'Chat',
        chat_description: 'Behavior, generation, context and backups.',
        models: 'Models',
        models_description: 'Models, roles, downloads and Model Scout.',
        runtime: 'Runtime',
        storage: 'Storage',
        downloads: 'Downloads',
        knowledge: 'Knowledge',
        knowledge_description: 'Local documents and semantic search.',
        personal: 'Personal',
        personal_description: 'Profile, response style and appearance.',
        tools: 'Tools',
        tools_description: 'Automatic capabilities and workspace tests.',
        automations: 'Automations',
        automations_description: 'Scheduled local agent tasks and recurring checks.',
        system: 'System',
        system_description: 'Local services and logs.',
        server: 'Server',
        logs: 'Logs'
    };

    let copy = { ...FALLBACK };
    let activeSection = 'chat';
    let activeModelTab = 'models';
    let activeSystemTab = 'server';
    let settings = null;
    let shellTitle = null;
    let contentTitle = null;
    let contentDescription = null;
    let organizerNav = null;
    let modelNav = null;
    let systemNav = null;
    let controller = null;
    let retryTimer = null;
    let syncTimer = null;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    async function loadCopy() {
        copy = { ...FALLBACK };
        try {
            const response = await fetch('/i18n/settings-layout.' + locale() + '.json', { cache: 'no-store' });
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_) {}
    }

    function sectionFromPath(pathname) {
        const path = String(pathname || '');
        if (/^\/settings\/models\/?$/.test(path)) return 'models';
        if (/^\/settings\/advanced\/(runtime|storage)\/?$/.test(path)) return 'models';
        if (/^\/settings\/knowledge\/?$/.test(path)) return 'knowledge';
        if (/^\/settings\/(profile|appearance)\/?$/.test(path)) return 'personal';
        if (/^\/settings\/functions\/?$/.test(path)) return 'tools';
        if (/^\/settings\/automations\/?$/.test(path)) return 'automations';
        if (/^\/settings\/advanced\/(server|logs)\/?$/.test(path)) return 'system';
        if (/^\/settings\/advanced\/generation\/?$/.test(path)) return 'chat';
        return 'chat';
    }

    function systemTabFromPath(pathname) {
        const match = String(pathname || '').match(/^\/settings\/advanced\/(server|logs)\/?$/);
        return match ? match[1] : null;
    }

    function sectionTarget(section) {
        return {
            chat: 'general',
            models: 'models',
            knowledge: 'knowledge',
            personal: 'profile',
            tools: 'functions',
            automations: 'automations'
        }[section] || 'general';
    }

    function movePaneContent(sourceName, targetName, beforeSelector = null) {
        if (!settings) return;
        const source = settings.querySelector('[data-settings-pane="' + sourceName + '"]');
        const target = settings.querySelector('[data-settings-pane="' + targetName + '"]');
        if (!source || !target || source.dataset.settingsConsolidated === 'true') return;

        const movable = Array.from(source.children).filter(child =>
            !child.classList.contains('settings-page-intro')
        );
        let before = beforeSelector ? target.querySelector(beforeSelector)?.closest('.settings-card') : null;
        movable.forEach(node => target.insertBefore(node, before || null));
        source.dataset.settingsConsolidated = 'true';
    }

    function consolidateContent() {
        movePaneContent('generation', 'general', '#exportChatJson');
        movePaneContent('appearance', 'profile');
    }

    function navButton(section) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.organizerSection = section;
        button.addEventListener('click', () => activateSection(section));
        return button;
    }

    function modelButton(tab) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.organizerModelTab = tab;
        button.addEventListener('click', () => activateModelTab(tab));
        return button;
    }

    function systemButton(tab) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.organizerSystemTab = tab;
        button.addEventListener('click', () => activateSystemTab(tab));
        return button;
    }

    function buildLayout() {
        if (!settings || settings.dataset.settingsOrganized === 'true') return;
        settings.dataset.settingsOrganized = 'true';
        settings.classList.add('settings-organized');

        const header = settings.querySelector('.settings-shell-header');
        shellTitle = header?.querySelector('h3') || null;
        if (shellTitle) shellTitle.removeAttribute('data-i18n');

        const body = document.createElement('div');
        body.className = 'settings-organizer-body';

        organizerNav = document.createElement('nav');
        organizerNav.className = 'settings-organizer-nav';
        organizerNav.setAttribute('aria-label', 'Settings');
        SECTIONS.forEach(section => organizerNav.appendChild(navButton(section)));

        const main = document.createElement('div');
        main.className = 'settings-organizer-main';

        const contentHeader = document.createElement('header');
        contentHeader.className = 'settings-organizer-content-header';
        const contentCopy = document.createElement('div');
        contentCopy.className = 'settings-organizer-content-copy';
        contentTitle = document.createElement('h4');
        contentTitle.id = 'settingsOrganizerTitle';
        const modelConsole = settings.querySelector('#modelConsole');
        if (modelConsole) {
            modelConsole.removeAttribute('aria-label');
            modelConsole.removeAttribute('data-i18n-aria-label');
            modelConsole.setAttribute('aria-labelledby', contentTitle.id);
        }
        contentDescription = document.createElement('p');
        contentCopy.append(contentTitle, contentDescription);

        modelNav = document.createElement('nav');
        modelNav.className = 'settings-organizer-system-tabs settings-organizer-model-tabs';
        modelNav.setAttribute('aria-label', 'Models');
        MODEL_TABS.forEach(tab => modelNav.appendChild(modelButton(tab)));
        modelNav.hidden = true;

        systemNav = document.createElement('nav');
        systemNav.className = 'settings-organizer-system-tabs';
        systemNav.setAttribute('aria-label', 'System');
        SYSTEM_TABS.forEach(tab => systemNav.appendChild(systemButton(tab)));
        systemNav.hidden = true;

        contentHeader.append(contentCopy, modelNav, systemNav);
        main.appendChild(contentHeader);

        const panes = Array.from(settings.children).filter(child => child.classList.contains('settings-pane'));
        panes.forEach(pane => main.appendChild(pane));
        body.append(organizerNav, main);
        settings.appendChild(body);
    }

    function updateLabels() {
        if (shellTitle) shellTitle.textContent = copy.title;
        organizerNav?.querySelectorAll('[data-organizer-section]').forEach(button => {
            button.textContent = copy[button.dataset.organizerSection] || button.dataset.organizerSection;
        });
        modelNav?.querySelectorAll('[data-organizer-model-tab]').forEach(button => {
            button.textContent = copy[button.dataset.organizerModelTab] || button.dataset.organizerModelTab;
        });
        systemNav?.querySelectorAll('[data-organizer-system-tab]').forEach(button => {
            button.textContent = copy[button.dataset.organizerSystemTab] || button.dataset.organizerSystemTab;
        });
    }

    function render() {
        if (!settings) return;
        settings.dataset.organizerSection = activeSection;
        updateLabels();
        if (contentTitle) contentTitle.textContent = copy[activeSection] || activeSection;
        if (contentDescription) contentDescription.textContent = copy[activeSection + '_description'] || '';

        organizerNav?.querySelectorAll('[data-organizer-section]').forEach(button => {
            const selected = button.dataset.organizerSection === activeSection;
            button.classList.toggle('active', selected);
            button.setAttribute('aria-current', selected ? 'page' : 'false');
        });

        if (modelNav) {
            const show = activeSection === 'models';
            if (modelNav.hidden === show) modelNav.hidden = !show;
            modelNav.querySelectorAll('[data-organizer-model-tab]').forEach(button => {
                const selected = button.dataset.organizerModelTab === activeModelTab;
                button.classList.toggle('active', selected);
                button.setAttribute('aria-selected', selected ? 'true' : 'false');
            });
        }

        if (systemNav) {
            const show = activeSection === 'system';
            if (systemNav.hidden === show) systemNav.hidden = !show;
            systemNav.querySelectorAll('[data-organizer-system-tab]').forEach(button => {
                const selected = button.dataset.organizerSystemTab === activeSystemTab;
                button.classList.toggle('active', selected);
                button.setAttribute('aria-selected', selected ? 'true' : 'false');
            });
        }
    }

    function activateSection(section) {
        if (!controller || !SECTIONS.includes(section)) return;
        activeSection = section;
        if (section === 'automations') {
            window.MLXAutomationsUI?.show({ updateHistory: true });
            render();
            return;
        }
        if (section === 'system') {
            controller.selectSystem(activeSystemTab);
        } else {
            controller.select(sectionTarget(section));
            if (section === 'models') {
                window.MLXModelConsole?.setTab(activeModelTab);
            }
        }
        render();
    }

    function activateModelTab(tab) {
        if (!controller || !MODEL_TABS.includes(tab)) return;
        activeSection = 'models';
        activeModelTab = tab;
        controller.select('models');
        window.MLXModelConsole?.setTab(tab);
        render();
    }

    function activateSystemTab(tab) {
        if (!controller || !SYSTEM_TABS.includes(tab)) return;
        activeSection = 'system';
        activeSystemTab = tab;
        controller.selectSystem(tab);
        render();
    }

    function syncFromPath(options = {}) {
        const path = String(location.pathname || '');
        const legacyGeneration = /^\/settings\/advanced\/generation\/?$/.test(path);
        const legacyAppearance = /^\/settings\/appearance\/?$/.test(path);
        const legacyModelSystem = path.match(/^\/settings\/advanced\/(runtime|storage)\/?$/);

        if (options.normalizeLegacy !== false && controller) {
            if (legacyGeneration) {
                activeSection = 'chat';
                controller.select('general');
                render();
                return;
            }
            if (legacyAppearance) {
                activeSection = 'personal';
                controller.select('profile');
                render();
                return;
            }
            if (legacyModelSystem) {
                activeSection = 'models';
                activeModelTab = legacyModelSystem[1];
                controller.select('models');
                window.MLXModelConsole?.setTab(activeModelTab);
                render();
                return;
            }
        }

        activeSection = sectionFromPath(path);
        if (activeSection === 'automations') {
            window.MLXAutomationsUI?.show({ updateHistory: false });
            render();
            return;
        }
        const systemTab = systemTabFromPath(path);
        if (systemTab) activeSystemTab = systemTab;
        render();
    }

    function scheduleSync() {
        clearTimeout(syncTimer);
        syncTimer = setTimeout(() => syncFromPath(), 0);
    }

    function wrapController() {
        const api = window.MLXChatSettings;
        if (!api || api.__organizedSettingsWrapped) return Boolean(api);

        const originalOpen = api.open.bind(api);
        const originalSelect = api.select.bind(api);
        const originalSelectSystem = api.selectSystem.bind(api);
        controller = {
            open: originalOpen,
            select: originalSelect,
            selectSystem: originalSelectSystem
        };

        api.open = function (...args) {
            const result = originalOpen(...args);
            scheduleSync();
            return result;
        };
        api.select = function (...args) {
            const result = originalSelect(...args);
            scheduleSync();
            return result;
        };
        api.selectSystem = function (...args) {
            const result = originalSelectSystem(...args);
            scheduleSync();
            return result;
        };
        api.__organizedSettingsWrapped = true;
        return true;
    }

    async function initialize() {
        settings = document.getElementById('settings');
        if (!settings || !window.MLXChatSettings) return false;
        clearTimeout(retryTimer);
        await loadCopy();
        consolidateContent();
        buildLayout();
        wrapController();
        syncFromPath();
        return true;
    }

    function start() {
        let attempts = 0;
        const tryInitialize = async () => {
            attempts += 1;
            if (await initialize()) return;
            if (attempts < 100) retryTimer = setTimeout(tryInitialize, 50);
        };
        tryInitialize();
    }

    window.MLXSettingsLayout = {
        sectionFromPath,
        systemTabFromPath,
        sectionTarget,
        sync: syncFromPath,
        activate: activateSection,
        activateModel: activateModelTab,
        activateSystem: activateSystemTab
    };

    document.addEventListener('mlx-language-changed', () => {
        loadCopy().then(() => render());
    });

    window.addEventListener?.('popstate', () => syncFromPath());

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
