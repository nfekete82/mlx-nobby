(function () {
    'use strict';

    if (window.__mlxNobbySettingsLayout) return;
    window.__mlxNobbySettingsLayout = true;

    const SECTIONS = ['chat', 'models', 'knowledge', 'personal', 'tools', 'system'];
    const SYSTEM_TABS = ['runtime', 'storage', 'server', 'logs'];
    const FALLBACK = {
        title: 'Settings',
        chat: 'Chat',
        chat_description: 'Behavior, generation, context and backups.',
        models: 'Models',
        models_description: 'Models, roles, downloads and Model Scout.',
        knowledge: 'Knowledge',
        knowledge_description: 'Local documents and semantic search.',
        personal: 'Personal',
        personal_description: 'Profile, response style and appearance.',
        tools: 'Tools',
        tools_description: 'Automatic capabilities and workspace tests.',
        system: 'System',
        system_description: 'Runtime, storage, services and logs.',
        runtime: 'Runtime',
        storage: 'Storage',
        server: 'Server',
        logs: 'Logs'
    };

    let copy = { ...FALLBACK };
    let activeSection = 'chat';
    let activeSystemTab = 'runtime';
    let settings = null;
    let shellTitle = null;
    let contentTitle = null;
    let contentDescription = null;
    let organizerNav = null;
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
        if (/^\/settings\/knowledge\/?$/.test(path)) return 'knowledge';
        if (/^\/settings\/(profile|appearance)\/?$/.test(path)) return 'personal';
        if (/^\/settings\/functions\/?$/.test(path)) return 'tools';
        if (/^\/settings\/advanced\/(runtime|storage|server|logs)\/?$/.test(path)) return 'system';
        if (/^\/settings\/advanced\/generation\/?$/.test(path)) return 'chat';
        return 'chat';
    }

    function systemTabFromPath(pathname) {
        const match = String(pathname || '').match(/^\/settings\/advanced\/(runtime|storage|server|logs)\/?$/);
        return match ? match[1] : null;
    }

    function sectionTarget(section) {
        return {
            chat: 'general',
            models: 'models',
            knowledge: 'knowledge',
            personal: 'profile',
            tools: 'functions'
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
        contentDescription = document.createElement('p');
        contentCopy.append(contentTitle, contentDescription);

        systemNav = document.createElement('nav');
        systemNav.className = 'settings-organizer-system-tabs';
        systemNav.setAttribute('aria-label', 'System');
        SYSTEM_TABS.forEach(tab => systemNav.appendChild(systemButton(tab)));
        systemNav.hidden = true;

        contentHeader.append(contentCopy, systemNav);
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
        if (section === 'system') {
            controller.selectSystem(activeSystemTab);
        } else {
            controller.select(sectionTarget(section));
        }
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
        }

        activeSection = sectionFromPath(path);
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
