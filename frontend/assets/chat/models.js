(function () {
    const root = document.getElementById('modelConsole');
    const content = document.getElementById('modelConsoleContent');
    const liveRegion = document.getElementById('modelConsoleStatus');
    const assignments = document.getElementById('modelConsoleAssignments');
    const dialog = document.getElementById('modelConsoleDialog');
    const dialogTitle = document.getElementById('modelConsoleDialogTitle');
    const dialogEyebrow = document.getElementById('modelConsoleDialogEyebrow');
    const dialogBody = document.getElementById('modelConsoleDialogBody');
    const dialogActions = document.getElementById('modelConsoleDialogActions');
    const toastRegion = document.getElementById('modelConsoleToasts');

    const state = {
        activeTab: 'models',
        runtimeAction: null,
        deletingModel: false,
        selectedModel: null,
        modal: null,
        error: null,
        visible: false,
        loading: false,
        loaded: false,
        refreshTimer: null,
        aliases: { current: null, models: [] },
        status: null,
        system: null,
        cache: { count: 0, complete: 0, incomplete: 0, models: [] },
        jobs: [],
    };

    let fetchImpl = (...args) => window.fetch(...args);
    let waitImpl = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = text;
        return element;
    }

    function actionButton(label, action, options = {}) {
        const button = node('button', 'model-console-button' + (options.primary ? ' primary' : '') + (options.danger ? ' danger' : ''), label);
        button.type = 'button';
        button.dataset.action = action;
        if (options.alias) button.dataset.alias = options.alias;
        if (options.target) button.dataset.target = options.target;
        if (options.disabled) button.disabled = true;
        if (options.title) button.title = options.title;
        return button;
    }

    function cleanTechnicalError(value) {
        if (!value) return 'Unbekannter Fehler';
        if (typeof value === 'string') return value.replace(/^Error:\s*/i, '').trim();
        if (typeof value.detail === 'string') return value.detail;
        if (value.detail && typeof value.detail === 'object') {
            return value.detail.stderr || value.detail.stdout || JSON.stringify(value.detail);
        }
        return value.message || 'Unbekannter Fehler';
    }

    async function requestJson(url, options) {
        const response = await fetchImpl(url, options);
        let data = null;
        try { data = await response.json(); } catch {}
        if (!response.ok) {
            const error = new Error(cleanTechnicalError(data) || ('HTTP ' + response.status));
            error.status = response.status;
            error.data = data;
            throw error;
        }
        return data || {};
    }

    function sourceName(repo) {
        const parts = String(repo || '').split('/').filter(Boolean);
        let value = parts[parts.length - 1] || '';
        if (/^\d+(?:\.\d+)?[-_ ]?bit$/i.test(value) && parts.length > 1) {
            value = parts[parts.length - 2];
        }
        return value;
    }

    function displayName(modelOrRepo) {
        const repo = typeof modelOrRepo === 'string'
            ? modelOrRepo
            : modelOrRepo?.repo;
        let value = sourceName(repo);
        value = value
            .replace(/(?:[-_ ](?:mlx|opt(?:i)?q))+$/ig, '')
            .replace(/[-_ ](?:mixed[-_ ]?)?\d+(?:\.\d+)?[-_ ]?bit\b/ig, '')
            .replace(/(?:[-_ ](?:mlx|opt(?:i)?q))+$/ig, '')
            .replace(/[-_]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        if (!value) return typeof modelOrRepo === 'object' ? modelOrRepo.alias : 'Unbenanntes Modell';
        return value.split(' ').map(token => {
            if (/^(qwen|mlx|vlm|llm)$/i.test(token)) return token.toUpperCase() === 'QWEN' ? 'Qwen' : token.toUpperCase();
            if (/^gemma$/i.test(token)) return 'Gemma';
            return token;
        }).join(' ');
    }

    function formatBytes(bytes) {
        if (bytes === null || bytes === undefined || bytes === '') return null;
        const value = Number(bytes);
        if (!Number.isFinite(value) || value < 0) return null;
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = value;
        let index = 0;
        while (size >= 1024 && index < units.length - 1) {
            size /= 1024;
            index += 1;
        }
        const digits = index >= 3 ? 2 : index === 0 ? 0 : 1;
        return size.toLocaleString('de-DE', { maximumFractionDigits: digits }) + ' ' + units[index];
    }

    function formatUptime(seconds) {
        if (seconds === null || seconds === undefined || seconds === '') return null;
        if (!Number.isFinite(Number(seconds))) return null;
        let remaining = Math.max(0, Math.floor(Number(seconds)));
        const days = Math.floor(remaining / 86400);
        remaining %= 86400;
        const hours = Math.floor(remaining / 3600);
        remaining %= 3600;
        const minutes = Math.floor(remaining / 60);
        if (days) return days + 'd ' + hours + 'h';
        if (hours) return hours + 'h ' + minutes + 'm';
        return minutes + 'm';
    }

    function validateModelInput(alias, repo) {
        const errors = {};
        const normalizedAlias = String(alias || '').trim();
        const normalizedRepo = String(repo || '').trim();
        if (!normalizedAlias) errors.alias = 'Alias ist erforderlich.';
        else if (!/^[A-Za-z0-9._-]+$/.test(normalizedAlias)) errors.alias = 'Nur Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich.';
        if (!normalizedRepo) errors.repo = 'Repository oder lokaler Pfad ist erforderlich.';
        else if (/[\x00-\x1f\x7f\\"`$|&]/.test(normalizedRepo)) errors.repo = 'Modellreferenz enthält unsichere Zeichen.';
        else if (!normalizedRepo.startsWith('/') && !normalizedRepo.startsWith('~/') &&
            !/^[A-Za-z0-9_][A-Za-z0-9_.-]*\/[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(normalizedRepo)) {
            errors.repo = 'Erwartet wird owner/modell oder ein absoluter lokaler Pfad.';
        }
        return { valid: Object.keys(errors).length === 0, errors, alias: normalizedAlias, repo: normalizedRepo };
    }

    function aliasExists(alias, models = state.aliases.models) {
        const normalized = String(alias || '').trim().toLowerCase();
        return Boolean(normalized && models.some(model => String(model.alias || '').toLowerCase() === normalized));
    }

    function cacheForModel(model) {
        return (state.cache.models || []).find(item => item.repo === model.repo) || null;
    }

    function duplicateInfoForLocalModel(model) {
        for (const item of state.cache.models || []) {
            const matches = Array.isArray(item.local_matches) ? item.local_matches : [];
            const match = matches.find(entry =>
                entry.path === model.repo ||
                (entry.alias && entry.alias === model.alias)
            );
            if (!match) continue;

            return {
                cache: item,
                exact: Boolean(item.duplicate && match.match === 'exact'),
                possible: Boolean(item.possible_duplicate && match.match === 'name')
            };
        }
        return null;
    }

    function jobForModel(model) {
        return state.jobs.find(job => job.target === model.alias || job.target === model.repo) || null;
    }

    function activeModel() {
        const currentRepo = state.status?.model || state.aliases.current;
        return state.aliases.models.find(model => model.repo === currentRepo)
            || state.aliases.models.find(model => model.active)
            || null;
    }

    function isJobRunning(job) {
        return Boolean(job && ['queued', 'running', 'detached'].includes(job.status));
    }

    function modelAvailability(model) {
        if (model.local) return { state: 'ready', label: 'Bereit' };
        const cache = cacheForModel(model);
        const job = jobForModel(model);
        if (isJobRunning(job)) return { state: 'download', label: 'Wird heruntergeladen', job };
        if (cache?.complete) return { state: 'ready', label: 'Bereit', cache };
        if (job?.status === 'failed' || job?.status === 'interrupted') return { state: 'error', label: 'Download fehlgeschlagen', job, cache };
        if (cache && !cache.complete) return { state: 'error', label: 'Download unvollständig', cache };
        return { state: 'missing', label: 'Nicht lokal verfügbar' };
    }

    function statusView() {
        if (state.runtimeAction) {
            if (state.runtimeAction.error) return { kind: 'error', label: 'Fehler' };
            return state.runtimeAction.type === 'stop'
                ? { kind: 'stopping', label: 'Stoppt' }
                : { kind: 'starting', label: 'Startet' };
        }
        if (state.error && !state.status) return { kind: 'error', label: 'Fehler' };
        return state.status?.online
            ? { kind: 'online', label: 'Online' }
            : { kind: 'offline', label: 'Offline' };
    }

    function statusChip(view = statusView()) {
        const chip = node('span', 'model-console-status ' + view.kind);
        const dot = node('span', 'model-console-status-dot');
        dot.setAttribute('aria-hidden', 'true');
        chip.append(dot, document.createTextNode(view.label));
        return chip;
    }

    function badge(text, kind = '') {
        return node('span', 'model-console-badge' + (kind ? ' ' + kind : ''), text);
    }

    function appendModelBadges(container, model, includeThinking) {
        if (!model) return;
        container.appendChild(badge(model.backend === 'vlm' ? 'VLM' : 'LLM'));
        if (model.quantization) container.appendChild(badge(model.quantization));
        if (model.vision) container.appendChild(badge('Vision'));
        container.appendChild(badge(model.local ? 'Lokal' : 'Hugging Face'));
        if (includeThinking && state.status) container.appendChild(badge('Thinking ' + (state.status.thinking ? 'AN' : 'AUS')));
    }

    function metric(label, value) {
        const item = node('div', 'model-console-metric');
        item.append(node('span', '', label), node('strong', '', value));
        return item;
    }

    function actionStep(label, mode) {
        const row = node('div', 'model-console-step ' + mode);
        row.append(node('span', 'model-console-step-icon', mode === 'done' ? '✓' : mode === 'active' ? '●' : '○'), node('span', '', label));
        return row;
    }

    function deriveActionSteps(action) {
        if (!action) return [];
        if (action.type === 'thinking') {
            return [{ label: 'Runtime-Bestätigung abwarten', mode: action.phase === 'ready' ? 'done' : 'active' }];
        }
        const stopped = Boolean(action.observedOffline);
        const checking = action.phase === 'checking' || action.phase === 'ready';
        if (action.type === 'stop') {
            return [
                { label: 'Runtime stoppen', mode: action.phase === 'ready' ? 'done' : 'active' },
                { label: 'Offline-Status bestätigen', mode: action.phase === 'ready' ? 'done' : action.phase === 'stopped' ? 'active' : 'pending' },
            ];
        }
        return [
            { label: action.type === 'switch' ? 'Bisheriges Modell beenden' : 'Runtime stoppen', mode: stopped ? 'done' : action.phase === 'requesting' ? 'active' : 'pending' },
            { label: 'Modell initialisieren', mode: checking || action.phase === 'ready' ? 'done' : action.phase === 'initializing' ? 'active' : 'pending' },
            { label: 'Bereitschaft prüfen', mode: action.phase === 'ready' ? 'done' : checking ? 'active' : 'pending' },
        ];
    }

    function renderActionProgress(container) {
        if (!state.runtimeAction) return;
        const panel = node('div', 'model-console-action-progress');
        const title = state.runtimeAction.type === 'switch'
            ? displayName(state.runtimeAction.model) + ' wird geladen …'
            : state.runtimeAction.type === 'restart'
                ? 'Modell wird neu gestartet …'
                : state.runtimeAction.type === 'start'
                    ? 'Runtime wird gestartet …'
                    : state.runtimeAction.type === 'thinking'
                        ? 'Thinking wird geändert …'
                        : 'Runtime wird gestoppt …';
        panel.appendChild(node('strong', '', title));
        deriveActionSteps(state.runtimeAction).forEach(step => panel.appendChild(actionStep(step.label, step.mode)));
        if (state.runtimeAction.error) {
            const error = node('div', 'model-console-inline-error', state.runtimeAction.error);
            const retry = actionButton('Erneut versuchen', 'retry-runtime');
            error.appendChild(retry);
            panel.appendChild(error);
        }
        container.appendChild(panel);
    }

    function renderHero() {
        const hero = node('section', 'model-console-hero');
        const heading = node('div', 'model-console-hero-heading');
        const label = node('div', 'model-console-eyebrow', 'Aktives Modell');
        heading.append(label, statusChip());
        hero.appendChild(heading);

        const model = activeModel();
        const title = node('h5', '', model ? displayName(model) : 'Kein Modell konfiguriert');
        hero.appendChild(title);
        if (model?.alias) hero.appendChild(node('div', 'model-console-alias', model.alias));
        const badges = node('div', 'model-console-badges');
        appendModelBadges(badges, model, true);
        if (badges.childNodes.length) hero.appendChild(badges);

        const metrics = node('div', 'model-console-metrics');
        const mlx = state.system?.mlx || {};
        const memoryMb = Number(mlx.memory_mb ?? state.status?.memory_mb);
        if (Number.isFinite(memoryMb) && memoryMb > 0) metrics.appendChild(metric('RAM', formatBytes(memoryMb * 1024 * 1024)));
        const pid = mlx.pid ?? state.status?.pid;
        if (pid !== null && pid !== undefined) metrics.appendChild(metric('PID', String(pid)));
        const port = mlx.port ?? state.status?.port;
        if (port !== null && port !== undefined) metrics.appendChild(metric('Port', String(port)));
        const uptime = formatUptime(mlx.uptime_seconds);
        if (uptime) metrics.appendChild(metric('Uptime', uptime));
        if (metrics.childNodes.length) hero.appendChild(metrics);

        renderActionProgress(hero);
        if (!state.runtimeAction) {
            const actions = node('div', 'model-console-actions');
            if (state.status?.online) {
                actions.append(actionButton('↻ Neustarten', 'restart-runtime'), actionButton('■ Stoppen', 'stop-runtime', { danger: true }));
            } else if (model || state.status?.model) {
                actions.append(actionButton('▶ Starten', 'start-runtime', { primary: true }));
            }
            if (actions.childNodes.length) hero.appendChild(actions);
        }
        return hero;
    }

    function renderModelRow(model) {
        const availability = modelAvailability(model);
        const active = activeModel()?.alias === model.alias && Boolean(state.status?.online);
        const row = node('article', 'model-console-row' + (active ? ' active' : ''));
        const main = node('div', 'model-console-row-main');
        const titleLine = node('div', 'model-console-row-title');
        titleLine.appendChild(node('strong', '', displayName(model)));
        if (active) titleLine.appendChild(badge('● Aktiv', 'active'));
        main.appendChild(titleLine);
        const meta = node('div', 'model-console-row-meta');
        meta.appendChild(node('span', 'model-console-alias', model.alias));
        appendModelBadges(meta, model, false);
        main.appendChild(meta);
        if (availability.state !== 'ready') {
            const availabilityLine = node('div', 'model-console-availability ' + availability.state, availability.label);
            if (availability.state === 'download') availabilityLine.appendChild(node('span', 'model-console-indeterminate'));
            main.appendChild(availabilityLine);
        }
        row.appendChild(main);

        const actions = node('div', 'model-console-row-actions');
        const globallyBusy = Boolean(state.runtimeAction) || state.deletingModel;
        if (!active) {
            const ready = availability.state === 'ready';
            actions.appendChild(actionButton('▶ Laden', 'load-model', {
                alias: model.alias,
                primary: true,
                disabled: globallyBusy || !ready,
                title: ready ? '' : availability.label,
            }));
        }
        const menu = node('details', 'model-console-menu');
        const summary = node('summary', 'model-console-icon-button', '•••');
        summary.setAttribute('aria-label', 'Aktionen für ' + model.alias);
        menu.appendChild(summary);
        const menuPanel = node('div', 'model-console-menu-panel');
        menuPanel.appendChild(actionButton('Details', 'model-details', { alias: model.alias }));
        if (!active) menuPanel.appendChild(actionButton('Modell laden', 'load-model', { alias: model.alias, disabled: globallyBusy || availability.state !== 'ready' }));
        if (availability.state === 'error') menuPanel.appendChild(actionButton('Download fortsetzen', 'retry-download', { target: model.alias }));
        menuPanel.appendChild(actionButton('Aus Konfiguration entfernen', 'remove-model', { alias: model.alias, danger: true, disabled: active || globallyBusy }));
        if (model.local && model.available !== false) {
            const protectedModel = model.active || activeModel()?.repo === model.repo;
            actions.appendChild(actionButton('Löschen', 'delete-local-model', {
                alias: model.alias, danger: true,
                disabled: protectedModel || globallyBusy || isJobRunning(jobForModel(model)),
                title: protectedModel ? 'Aktives Modell ist geschützt – auch bei gestoppter Runtime.' : 'Lokale Modelldateien und Alias löschen',
            }));
        }
        menu.appendChild(menuPanel);
        actions.appendChild(menu);
        row.appendChild(actions);
        return row;
    }

    function renderModels() {
        const fragment = document.createDocumentFragment();
        fragment.appendChild(renderHero());
        const section = node('section', 'model-console-section');
        const head = node('div', 'model-console-section-heading');
        head.append(node('h5', '', 'Installierte Modelle'), node('span', '', String(state.aliases.models.length)));
        section.appendChild(head);
        if (!state.aliases.models.length) {
            const empty = node('div', 'model-console-empty');
            empty.append(node('strong', '', 'Noch keine Modelle'), node('p', '', 'Füge ein lokales MLX-Modell oder ein Hugging-Face-Repository hinzu.'), actionButton('+ Modell hinzufügen', 'add-model', { primary: true }));
            section.appendChild(empty);
        } else {
            const list = node('div', 'model-console-list');
            state.aliases.models.forEach(model => list.appendChild(renderModelRow(model)));
            section.appendChild(list);
        }
        fragment.appendChild(section);
        fragment.appendChild(renderDownloads());
        return fragment;
    }

    function definitionRow(label, value, options = {}) {
        if (value === null || value === undefined || value === '') return null;
        const row = node('div', 'model-console-definition');
        row.appendChild(node('dt', '', label));
        const dd = node('dd', options.mono ? 'mono' : '');
        const valueNode = node('span', 'model-console-break', String(value));
        valueNode.title = String(value);
        dd.appendChild(valueNode);
        if (options.copy) {
            const copy = actionButton('Kopieren', 'copy-value');
            copy.dataset.value = String(value);
            dd.appendChild(copy);
        }
        row.appendChild(dd);
        return row;
    }

    function renderRuntime() {
        const fragment = document.createDocumentFragment();
        const section = node('section', 'model-console-runtime');
        const head = node('div', 'model-console-section-heading');
        head.append(node('h5', '', 'Runtime'), statusChip());
        section.appendChild(head);
        const model = activeModel();
        const mlx = state.system?.mlx || {};
        const details = node('dl', 'model-console-definitions');
        [
            definitionRow('Status', statusView().label),
            definitionRow('Modell', model?.alias || state.status?.model),
            definitionRow('Backend', model?.backend === 'vlm' ? 'VLM' : model ? 'LLM' : null),
            definitionRow('PID', mlx.pid ?? state.status?.pid),
            definitionRow('Port', mlx.port ?? state.status?.port),
            Number(mlx.memory_mb ?? state.status?.memory_mb) > 0 ? definitionRow('RAM', formatBytes(Number(mlx.memory_mb ?? state.status?.memory_mb) * 1024 * 1024)) : null,
            definitionRow('Thinking', state.status ? (state.status.thinking ? 'An' : 'Aus') : null),
            definitionRow('Vision', model ? (model.vision ? 'Ja' : 'Nein') : null),
            definitionRow('Uptime', formatUptime(mlx.uptime_seconds)),
        ].filter(Boolean).forEach(item => details.appendChild(item));
        section.appendChild(details);

        const availableModels = state.aliases.models.filter(item =>
            modelAvailability(item).state === 'ready'
        );
        const switcher = node('div', 'model-console-control-row');
        const switcherInfo = node('div');
        switcherInfo.append(
            node('strong', '', 'Aktives Modell'),
            node('p', '', 'Wechselt das Modell über den vorhandenen Runtime-Manager.')
        );
        const switcherControls = node('div', 'model-console-switcher');
        const modelSelect = node('select');
        modelSelect.setAttribute('aria-label', 'Runtime-Modell auswählen');
        availableModels.forEach(item => {
            const option = node('option', '', item.alias);
            option.value = item.alias;
            if (item.alias === model?.alias) option.selected = true;
            modelSelect.appendChild(option);
        });
        const switchButton = actionButton('Modell wechseln', 'switch-selected-model', {
            disabled: !availableModels.length || Boolean(state.runtimeAction),
        });
        modelSelect.addEventListener('change', () => {
            switchButton.disabled = !modelSelect.value
                || modelSelect.value === activeModel()?.alias
                || Boolean(state.runtimeAction);
        });
        switchButton.disabled = switchButton.disabled
            || modelSelect.value === model?.alias;
        switcherControls.append(modelSelect, switchButton);
        switcher.append(switcherInfo, switcherControls);
        section.appendChild(switcher);

        const thinking = node('div', 'model-console-control-row');
        const thinkingInfo = node('div');
        thinkingInfo.append(node('strong', '', 'Thinking'), node('p', '', 'Aktiviert erweitertes Reasoning, sofern vom Modell unterstützt.'));
        const thinkingButton = actionButton(state.status?.thinking ? 'An' : 'Aus', 'toggle-thinking', { primary: Boolean(state.status?.thinking), disabled: !state.status?.online || Boolean(state.runtimeAction) });
        thinkingButton.setAttribute('aria-pressed', state.status?.thinking ? 'true' : 'false');
        thinking.append(thinkingInfo, thinkingButton);
        section.appendChild(thinking);

        renderActionProgress(section);
        if (!state.runtimeAction) {
            const actions = node('div', 'model-console-actions');
            if (state.status?.online) actions.append(actionButton('↻ Neustarten', 'restart-runtime'), actionButton('■ Stoppen', 'stop-runtime', { danger: true }));
            else if (model || state.status?.model) actions.append(actionButton('▶ Starten', 'start-runtime', { primary: true }));
            actions.appendChild(actionButton('Logs anzeigen', 'show-logs'));
            section.appendChild(actions);
        }
        fragment.appendChild(section);

        const technical = node('details', 'model-console-technical');
        technical.appendChild(node('summary', '', 'Runtime-Details'));
        const technicalList = node('dl', 'model-console-definitions');
        const repo = model?.repo || state.status?.model;
        [
            definitionRow('Server-Endpunkt', (mlx.port ?? state.status?.port) ? 'http://127.0.0.1:' + (mlx.port ?? state.status?.port) : null, { mono: true, copy: true }),
            definitionRow(model?.local ? 'Lokaler Modellpfad' : 'Repository', repo, { mono: true, copy: true }),
            definitionRow('Startparameter', Array.isArray(mlx.server_args) && mlx.server_args.length ? mlx.server_args.join(' ') : null, { mono: true, copy: true }),
        ].filter(Boolean).forEach(item => technicalList.appendChild(item));
        technical.appendChild(technicalList);
        fragment.appendChild(technical);
        return fragment;
    }

    function renderStorageRow(item) {
        const row = node('article', 'model-console-storage-row');
        const info = node('div', 'model-console-row-main');
        info.append(node('strong', '', displayName(item)), node('span', 'model-console-storage-repo', item.repo));
        if (!item.complete) {
            info.appendChild(node('span', 'model-console-availability error', 'Unvollständig · ' + item.incomplete_files + ' Dateien'));
        } else if (item.duplicate) {
            const extra = item.duplicate_size || formatBytes(item.duplicate_size_bytes);
            info.appendChild(node('span', 'model-console-availability error', 'Doppelt vorhanden' + (extra ? ' · zusätzlich ca. ' + extra : '')));
        } else if (item.possible_duplicate) {
            info.appendChild(node('span', 'model-console-availability error', 'Mögliche Dublette · lokalen Modellpfad prüfen'));
        }
        const right = node('div', 'model-console-storage-actions');
        right.appendChild(node('strong', '', item.size || formatBytes(item.size_bytes) || '–'));
        if (!item.active) right.appendChild(actionButton('HF-Dateien löschen', 'delete-cache', { target: item.alias || item.repo, danger: true }));
        else right.appendChild(badge('Aktives Modell', 'active'));
        row.append(info, right);
        return row;
    }

    function renderStorage() {
        const fragment = document.createDocumentFragment();
        const summary = node('section', 'model-console-storage-summary');
        const systemMemory = state.system?.system || {};
        summary.append(
            metric('Unified Memory', systemMemory.total_gb != null ? systemMemory.total_gb + ' GB' : '–'),
            metric('RAM frei', systemMemory.free_percent != null ? systemMemory.free_percent + ' %' : '–'),
            metric('HF-Speicher', state.cache.total_size || formatBytes(state.cache.total_size_bytes) || '–'),
            metric('HF-Modelle', String(state.cache.count ?? state.cache.models.length))
        );
        if (state.cache.path) {
            const path = node('div', 'model-console-cache-path');
            path.append(node('span', '', 'Hugging-Face-Speicher'), node('code', '', state.cache.path), actionButton('Kopieren', 'copy-value'));
            path.lastChild.dataset.value = state.cache.path;
            summary.appendChild(path);
        }
        fragment.appendChild(summary);
        const localModels = state.aliases.models.filter(model => model.local);
        if (localModels.length) {
            const localSection = node('section', 'model-console-section');
            const localHead = node('div', 'model-console-section-heading');
            localHead.append(node('h5', '', 'Lokale Modellpfade'), node('span', '', String(localModels.length)));
            localSection.appendChild(localHead);
            const localList = node('div', 'model-console-list');
            localModels.forEach(model => {
                const row = node('article', 'model-console-storage-row');
                const info = node('div', 'model-console-row-main');
                info.append(node('strong', '', displayName(model)), node('span', 'model-console-storage-repo', model.repo));
                const duplicateInfo = duplicateInfoForLocalModel(model);
                if (duplicateInfo?.exact) {
                    const extra = duplicateInfo.cache.duplicate_size || formatBytes(duplicateInfo.cache.duplicate_size_bytes);
                    info.appendChild(node('span', 'model-console-availability error', 'Doppelt vorhanden' + (extra ? ' · zusätzlich ca. ' + extra : '')));
                } else if (duplicateInfo?.possible) {
                    info.appendChild(node('span', 'model-console-availability error', 'Mögliche Dublette mit Hugging Face · bitte prüfen'));
                }
                const right = node('div', 'model-console-storage-actions');
                right.appendChild(badge(model.active ? 'Aktives Modell' : 'Lokal unter ~/Models', model.active ? 'active' : ''));
                row.append(info, right);
                localList.appendChild(row);
            });
            localSection.appendChild(localList);
            fragment.appendChild(localSection);
        }
        const section = node('section', 'model-console-section');

        const visibleCacheModels = (state.cache.models || []).filter(item =>
            Number(item.size_bytes || 0) >= 1024 * 1024 ||
            !item.complete
        );

        const head = node('div', 'model-console-section-heading');
        head.append(
            node('h5', '', 'Lokal verfügbare Hugging-Face-Modelle'),
            node('span', '', String(visibleCacheModels.length))
        );
        section.appendChild(head);

        if (!visibleCacheModels.length) {
            section.appendChild(
                node(
                    'div',
                    'model-console-empty',
                    'Keine lokal verfügbaren Hugging-Face-Modelle gefunden.'
                )
            );
        } else {
            const list = node('div', 'model-console-list');
            visibleCacheModels.forEach(item =>
                list.appendChild(renderStorageRow(item))
            );
            section.appendChild(list);
        }

        fragment.appendChild(section);
        return fragment;
    }

    function renderDownloads() {
        const fragment = document.createDocumentFragment();

        const section = node('section', 'model-console-section');

        const head = node('div', 'model-console-section-heading');
        head.append(
            node('h5', '', 'Downloads & Jobs'),
            node('span', '', String(state.jobs.length))
        );
        const cleanup = node('div', 'history-cleanup');
        window.MLXHistoryCleanup?.mount(cleanup, {
            kind: 'downloads',
            onComplete: async data => {
                toast(data.removed + ' Download-Einträge entfernt');
                await load({ force: true });
            },
        });
        head.appendChild(cleanup);
        section.appendChild(head);

        if (!state.jobs.length) {
            section.appendChild(
                node(
                    'div',
                    'model-console-empty',
                    'Aktuell sind keine Download-Jobs vorhanden.'
                )
            );

            fragment.appendChild(section);
            return fragment;
        }

        const list = node('div', 'model-console-list');

        const jobs = [...state.jobs].sort((a, b) => {
            const aRunning = isJobRunning(a) ? 1 : 0;
            const bRunning = isJobRunning(b) ? 1 : 0;

            if (aRunning !== bRunning) return bRunning - aRunning;

            const aTime = new Date(
                a.updated_at || a.created_at || 0
            ).getTime();

            const bTime = new Date(
                b.updated_at || b.created_at || 0
            ).getTime();

            return bTime - aTime;
        });

        jobs.forEach(job => {
            const row = node('article', 'model-console-storage-row');

            const info = node('div', 'model-console-row-main');

            const target =
                job.alias ||
                job.target ||
                job.repo ||
                job.model ||
                ('Job ' + (job.id || ''));

            info.appendChild(
                node('strong', '', displayName(job.repo || target))
            );

            if (job.repo && job.repo !== target) {
                info.appendChild(
                    node(
                        'span',
                        'model-console-storage-repo',
                        job.repo
                    )
                );
            }

            const status =
                job.status === 'running' ? 'Wird heruntergeladen' :
                job.status === 'queued' ? 'Wartet' :
                job.status === 'detached' ? 'Läuft' :
                job.status === 'completed' ? 'Abgeschlossen' :
                job.status === 'failed' ? 'Fehlgeschlagen' :
                job.status === 'interrupted' ? 'Unterbrochen' :
                (job.status || 'Unbekannt');

            const statusClass =
                isJobRunning(job) ? 'download' :
                job.status === 'completed' ? 'ready' :
                ['failed', 'interrupted'].includes(job.status) ? 'error' :
                '';

            info.appendChild(
                node(
                    'span',
                    'model-console-availability ' + statusClass,
                    status
                )
            );

            const right = node(
                'div',
                'model-console-storage-actions'
            );

            if (job.progress !== undefined && job.progress !== null) {
                let progress = Number(job.progress);

                if (Number.isFinite(progress)) {
                    if (progress <= 1) progress *= 100;

                    right.appendChild(
                        node(
                            'strong',
                            '',
                            Math.round(progress) + ' %'
                        )
                    );
                }
            }

            if (job.id) {
                right.appendChild(
                    badge('#' + job.id)
                );
            }

            row.append(info, right);
            list.appendChild(row);
        });

        section.appendChild(list);
        fragment.appendChild(section);

        return fragment;
    }

    function renderSkeleton() {
        content.innerHTML = '';
        const skeleton = node('div', 'model-console-skeleton');
        skeleton.append(node('div'), node('div'), node('div'));
        content.appendChild(skeleton);
        content.setAttribute('aria-busy', 'true');
    }

    function renderErrorBanner() {
        if (!state.error) return null;
        const banner = node('div', 'model-console-error-banner');
        const text = node('div');
        text.append(node('strong', '', 'Daten konnten nicht vollständig geladen werden.'), node('span', '', state.error));
        banner.append(text, actionButton('Erneut laden', 'refresh'));
        return banner;
    }

    function render() {
        if (!root || !content) return;
        const title = document.getElementById('modelConsoleTitle');
        const description = root.querySelector('.model-console-header p');
        const addButton = document.getElementById('modelConsoleAdd');
        const headings = {
            models: ['Modelle', 'Installierte Modelle, Downloads und Modellrollen zentral verwalten.'],
            runtime: ['Runtime', 'Aktives Modell, Backend und Laufzeitstatus verwalten.'],
            storage: ['Speicher', 'Lokal verfügbare Modelle und ihr Speicherverbrauch im Überblick.'],
            downloads: ['Downloads', 'Download-Jobs der Model Console.'],
        };
        const heading = headings[state.activeTab] || headings.models;
        if (title) title.textContent = heading[0];
        if (description) description.textContent = heading[1];
        if (addButton) addButton.hidden = state.activeTab !== 'models';
        content.innerHTML = '';
        const errorBanner = renderErrorBanner();
        if (errorBanner) content.appendChild(errorBanner);
        if (!state.loaded && state.loading) {
            renderSkeleton();
            return;
        }
        if (state.activeTab === 'runtime') content.appendChild(renderRuntime());
        else if (state.activeTab === 'storage') content.appendChild(renderStorage());
        else if (state.activeTab === 'downloads') content.appendChild(renderDownloads());
        else content.appendChild(renderModels());
        content.setAttribute('aria-busy', state.loading ? 'true' : 'false');
        if (assignments) assignments.hidden = state.activeTab !== 'models';
    }

    async function load(options = {}) {
        if (state.loading && !options.force) return;
        state.loading = true;
        if (!state.loaded) renderSkeleton();
        const endpoints = [
            ['aliases', '/api/mlx/aliases'],
            ['status', '/api/mlx/status'],
            ['system', '/api/mlx/system'],
            ['cache', '/api/mlx/cache'],
            ['jobs', '/api/mlx/jobs'],
        ];
        const results = await Promise.allSettled(endpoints.map(item => requestJson(item[1])));
        const errors = [];
        results.forEach((result, index) => {
            const key = endpoints[index][0];
            if (result.status === 'fulfilled') {
                if (key === 'jobs') state.jobs = Array.isArray(result.value.jobs) ? result.value.jobs : [];
                else state[key] = result.value;
            } else {
                errors.push(cleanTechnicalError(result.reason));
            }
        });
        state.error = errors.length ? errors[0] : null;
        state.loading = false;
        state.loaded = true;
        render();
        scheduleRefresh();
    }

    function scheduleRefresh(delay) {
        clearTimeout(state.refreshTimer);
        state.refreshTimer = null;
        if (!state.visible) return;
        const hasRunningJobs = state.jobs.some(isJobRunning);
        state.refreshTimer = setTimeout(() => load({ force: true }), delay ?? (hasRunningJobs ? 4000 : 15000));
    }

    function setTab(tab) {
        if (!['models', 'runtime', 'storage', 'downloads'].includes(tab)) return;
        state.activeTab = tab;
        root.querySelectorAll('[data-model-console-tab]').forEach(button => {
            const active = button.dataset.modelConsoleTab === tab;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        render();
    }

    function toast(message, type = 'success', details = '') {
        if (!toastRegion) return;
        const item = node('div', 'model-console-toast ' + type);
        item.appendChild(node('strong', '', (type === 'success' ? '✓ ' : '') + message));
        if (details) {
            const detail = node('details');
            detail.append(node('summary', '', 'Details'), node('div', '', details));
            item.appendChild(detail);
        }
        toastRegion.appendChild(item);
        setTimeout(() => item.remove(), 5200);
    }

    function openDialog({ eyebrow = '', title, body, actions = [] }) {
        state.modal = title;
        dialogEyebrow.textContent = eyebrow;
        dialogTitle.textContent = title;
        dialogBody.innerHTML = '';
        dialogActions.innerHTML = '';
        if (typeof body === 'string') dialogBody.textContent = body;
        else if (body) dialogBody.appendChild(body);
        actions.forEach(item => dialogActions.appendChild(item));
        if (!dialog.open) dialog.showModal();
        requestAnimationFrame(() => dialog.querySelector('input, button, select')?.focus());
    }

    function closeDialog() {
        state.modal = null;
        if (dialog?.open) dialog.close();
    }

    function openAddDialog() {
        const form = node('div', 'model-console-form');
        form.innerHTML = '<label>Alias<input id="modelAddAlias" autocomplete="off" placeholder="z. B. qwen38"></label><div id="modelAddAliasError" class="model-console-field-error"></div><label>Hugging-Face Repository oder lokaler Modellpfad<div style="display:flex;gap:8px;align-items:center"><input id="modelAddRepo" style="flex:1" autocomplete="off" placeholder="mlx-community/Modell oder ~/Models/…"><button id="modelSelectFolder" class="model-console-button" type="button">Auswählen…</button></div></label><div id="modelAddRepoError" class="model-console-field-error"></div><label>Quantisierung<select id="modelAddQuantization"><option value="">Automatisch erkennen</option><option value="2-bit">2-bit</option><option value="4-bit">4-bit</option><option value="6-bit">6-bit</option><option value="8-bit">8-bit</option></select></label><p class="settings-hint">Remote-Modelle werden nach dem Hinzufügen als Background Job heruntergeladen.</p>';

        const selectFolder = form.querySelector('#modelSelectFolder');

        selectFolder?.addEventListener('click', async () => {
            const repoInput = document.getElementById('modelAddRepo');
            const repoError = document.getElementById('modelAddRepoError');

            selectFolder.disabled = true;
            selectFolder.textContent = 'Öffne …';
            repoError.textContent = '';

            try {
                const result = await requestJson('/api/mlx/models/select-folder');

                if (!result.cancelled && result.path) {
                    repoInput.value = result.path;

                    if (!result.looks_like_model) {
                        repoError.textContent = 'Hinweis: Im ausgewählten Ordner wurden keine typischen MLX-Modell-Dateien erkannt.';
                    }

                    repoInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            } catch (error) {
                repoError.textContent = cleanTechnicalError(error);
            } finally {
                selectFolder.disabled = false;
                selectFolder.textContent = 'Auswählen…';
            }
        });
        const cancel = actionButton('Abbrechen', 'close-dialog');
        const submit = actionButton('Modell hinzufügen', 'submit-model', { primary: true });
        openDialog({ eyebrow: 'Modelle', title: 'Modell hinzufügen', body: form, actions: [cancel, submit] });
    }

    function showModelDetails(model) {
        const cache = cacheForModel(model);
        const details = node('dl', 'model-console-definitions');
        [
            definitionRow('Alias', model.alias, { mono: true, copy: true }),
            definitionRow('Anzeigename', displayName(model)),
            definitionRow(model.local ? 'Lokaler Modellpfad' : 'Repository', model.repo, { mono: true, copy: true }),
            definitionRow(!model.local && cache?.path ? 'Cache-Pfad' : null, cache?.path, { mono: true, copy: true }),
            definitionRow('Backend', model.backend === 'vlm' ? 'VLM' : 'LLM'),
            definitionRow('Quantisierung', model.quantization),
            definitionRow('Vision', model.vision ? 'Ja' : 'Nein'),
            definitionRow('Quelle', model.local ? 'Lokales Dateisystem' : 'Hugging Face'),
            definitionRow('Cache-Größe', cache?.size || formatBytes(cache?.size_bytes)),
            model.active ? definitionRow('Thinking', state.status ? (state.status.thinking ? 'An' : 'Aus') : null) : null,
        ].filter(Boolean).forEach(item => details.appendChild(item));
        openDialog({ eyebrow: 'Technische Details', title: displayName(model), body: details, actions: [actionButton('Schließen', 'close-dialog')] });
    }

    function confirmAction(title, message, confirmLabel, confirmAction, data = {}) {
        const body = node('div', 'model-console-confirm');
        body.appendChild(node('p', '', message));
        const cancel = actionButton('Abbrechen', 'close-dialog');
        const confirm = actionButton(confirmLabel, confirmAction, { danger: true });
        Object.entries(data).forEach(([key, value]) => { confirm.dataset[key] = value; });
        openDialog({ eyebrow: 'Bestätigung', title, body, actions: [cancel, confirm] });
    }

    async function submitModel() {
        const aliasInput = document.getElementById('modelAddAlias');
        const repoInput = document.getElementById('modelAddRepo');
        const quantization = document.getElementById('modelAddQuantization')?.value || null;
        const validation = validateModelInput(aliasInput?.value, repoInput?.value);
        const duplicate = aliasExists(validation.alias);
        if (duplicate) validation.errors.alias = 'Dieser Alias ist bereits vorhanden.';
        if (validation.repo.startsWith('/') && quantization) {
            validation.errors.repo = 'Für lokale Modellpfade wird die vorhandene Quantisierung automatisch verwendet.';
        }
        const aliasError = document.getElementById('modelAddAliasError');
        const repoError = document.getElementById('modelAddRepoError');
        aliasError.textContent = validation.errors.alias || '';
        repoError.textContent = validation.errors.repo || '';
        if (!validation.valid || duplicate || validation.errors.repo) return;
        const button = dialogActions.querySelector('[data-action="submit-model"]');
        button.disabled = true;
        button.textContent = 'Wird hinzugefügt …';
        try {
            await requestJson('/api/mlx/models/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alias: validation.alias, repo: validation.repo, quantization }),
            });
            closeDialog();
            toast(validation.alias + ' wurde hinzugefügt');
            await load({ force: true });
            window.loadModelRoles?.();
        } catch (error) {
            repoError.textContent = cleanTechnicalError(error);
            button.disabled = false;
            button.textContent = 'Modell hinzufügen';
        }
    }

    async function monitorMutation({ type, expectedRepo, commandPromise, onUpdate = () => {}, fetchStatus = () => requestJson('/api/mlx/status'), timeoutMs = 125000 }) {
        const action = { type, phase: 'requesting', observedOffline: false };
        let commandDone = false;
        let commandError = null;
        commandPromise.then(() => { commandDone = true; }, error => { commandDone = true; commandError = error; });
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
            let status = null;
            try { status = await fetchStatus(); } catch {}
            if (status && !status.online) {
                action.observedOffline = true;
                action.phase = type === 'stop' ? 'stopped' : 'initializing';
            } else if (status?.online && type !== 'stop') {
                const expectedReady = !expectedRepo || status.model === expectedRepo;
                if (commandDone && !commandError && expectedReady) {
                    action.phase = 'ready';
                    onUpdate({ ...action }, status);
                    return status;
                }
                if (action.observedOffline || commandDone) action.phase = 'checking';
            }
            onUpdate({ ...action }, status);
            if (commandDone && commandError) throw commandError;
            if (type === 'stop' && commandDone && status && !status.online) {
                action.phase = 'ready';
                onUpdate({ ...action }, status);
                return status;
            }
            await waitImpl(800);
        }
        throw new Error('Die Runtime hat den erwarteten Zustand nicht rechtzeitig bestätigt.');
    }

    function canBeginRuntimeAction() {
        return !state.runtimeAction && !state.deletingModel && !window.MLXChatRuntime?.isSwitching?.();
    }

    async function performRuntimeAction(type, model = null) {
        if (!canBeginRuntimeAction()) return false;
        const previous = activeModel();
        const expectedRepo = type === 'switch' ? model?.repo : previous?.repo || state.status?.model;
        state.runtimeAction = { type, model, phase: 'requesting', observedOffline: false, error: null };
        if (liveRegion) liveRegion.textContent = type === 'switch' ? displayName(model) + ' wird geladen.' : 'Runtime-Aktion läuft.';
        window.MLXChatRuntime?.setExternalRuntimeBusy?.(true);
        render();
        const url = type === 'switch'
            ? '/api/mlx/model/' + encodeURIComponent(model.alias)
            : '/api/mlx/server/' + type;
        try {
            const commandPromise = requestJson(url, { method: 'POST' });
            const status = await monitorMutation({
                type,
                expectedRepo,
                commandPromise,
                onUpdate(action, observedStatus) {
                    state.runtimeAction = { ...state.runtimeAction, ...action };
                    if (observedStatus) state.status = observedStatus;
                    render();
                },
            });
            state.status = status;
            const success = type === 'switch' ? displayName(model) + ' wurde geladen' : type === 'restart' ? 'Runtime neu gestartet' : type === 'start' ? 'Runtime gestartet' : 'Runtime gestoppt';
            toast(success);
            if (liveRegion) liveRegion.textContent = success + '.';
            await load({ force: true });
            window.MLXChatRuntime?.refreshModelState?.().catch(() => {});
            state.runtimeAction = null;
            render();
            return true;
        } catch (error) {
            const message = cleanTechnicalError(error);
            state.runtimeAction = { ...state.runtimeAction, error: message };
            state.error = null;
            if (liveRegion) liveRegion.textContent = 'Runtime-Aktion fehlgeschlagen: ' + message;
            toast('Runtime-Aktion fehlgeschlagen', 'error', message);
            render();
            return false;
        } finally {
            window.MLXChatRuntime?.setExternalRuntimeBusy?.(false);
        }
    }

    async function toggleThinking() {
        if (!state.status?.online || !canBeginRuntimeAction()) return;
        const enabled = !state.status.thinking;
        state.runtimeAction = { type: 'thinking', phase: 'requesting', observedOffline: false, error: null };
        window.MLXChatRuntime?.setExternalRuntimeBusy?.(true);
        render();
        try {
            await requestJson('/api/mlx/thinking/' + (enabled ? 'on' : 'off'), { method: 'POST' });
            const deadline = Date.now() + 125000;
            let confirmed = null;
            while (Date.now() < deadline) {
                try {
                    const status = await requestJson('/api/mlx/status');
                    state.status = status;
                    if (status.online && status.thinking === enabled) { confirmed = status; break; }
                } catch {}
                await waitImpl(800);
            }
            if (!confirmed) throw new Error('Thinking wurde nicht rechtzeitig von der Runtime bestätigt.');
            toast('Thinking ' + (enabled ? 'aktiviert' : 'deaktiviert'));
            state.runtimeAction = null;
            await load({ force: true });
            window.MLXChatRuntime?.refreshModelState?.().catch(() => {});
        } catch (error) {
            const message = cleanTechnicalError(error);
            state.runtimeAction = null;
            toast('Thinking konnte nicht geändert werden', 'error', message);
            state.error = message;
            render();
        } finally {
            window.MLXChatRuntime?.setExternalRuntimeBusy?.(false);
        }
    }

    async function removeModel(alias) {
        try {
            await requestJson('/api/mlx/models/' + encodeURIComponent(alias), { method: 'DELETE' });
            closeDialog();
            toast(alias + ' wurde aus der Konfiguration entfernt');
            await load({ force: true });
            window.loadModelRoles?.();
        } catch (error) {
            closeDialog();
            toast('Modell konnte nicht entfernt werden', 'error', cleanTechnicalError(error));
        }
    }

    async function deleteLocalModel(alias) {
        if (!canBeginRuntimeAction()) return;
        state.deletingModel = true;
        const confirm = dialogActions.querySelector('[data-action="confirm-delete-local-model"]');
        if (confirm) confirm.disabled = true;
        window.MLXChatRuntime?.setExternalRuntimeBusy?.(true);
        render();
        try {
            await requestJson('/api/mlx/models/' + encodeURIComponent(alias) + '/local', { method: 'DELETE' });
            closeDialog();
            toast(alias + ': lokale Dateien und Alias gelöscht');
        } catch (error) {
            closeDialog();
            toast('Modell konnte nicht gelöscht werden', 'error', cleanTechnicalError(error));
        } finally {
            state.deletingModel = false;
            window.MLXChatRuntime?.setExternalRuntimeBusy?.(false);
            await load({ force: true });
            await window.loadModelRoles?.();
            window.MLXChatRuntime?.refreshModelState?.().catch(() => {});
        }
    }

    async function deleteCache(target) {
        try {
            await requestJson('/api/mlx/cache/' + encodeURIComponent(target), { method: 'DELETE' });
            closeDialog();
            toast('Cache-Eintrag wurde gelöscht');
            await load({ force: true });
        } catch (error) {
            closeDialog();
            toast('Cache konnte nicht gelöscht werden', 'error', cleanTechnicalError(error));
        }
    }

    async function retryDownload(target) {
        try {
            await requestJson('/api/mlx/jobs/retry/' + encodeURIComponent(target), { method: 'POST' });
            toast('Download wird fortgesetzt');
            await load({ force: true });
        } catch (error) {
            toast('Download konnte nicht gestartet werden', 'error', cleanTechnicalError(error));
        }
    }

    async function showLogs() {
        const loading = node('div', 'model-console-log', 'Logs werden geladen …');
        openDialog({ eyebrow: 'Runtime', title: 'Letzte Logs', body: loading, actions: [actionButton('Aktualisieren', 'refresh-logs'), actionButton('Schließen', 'close-dialog')] });
        try {
            const data = await requestJson('/api/mlx/logs/all?limit=120');
            const sources = Array.isArray(data.sources) ? data.sources : [];
            dialogBody.innerHTML = '';
            if (!sources.length) dialogBody.appendChild(node('div', 'model-console-empty', 'Keine Logs vorhanden.'));
            sources.forEach(source => {
                const details = node('details', 'model-console-log-source');
                if (source.id === 'mlx-errors') details.open = true;
                details.appendChild(node('summary', '', source.name || source.id));
                details.appendChild(node('pre', 'model-console-log', (source.lines || []).join('\n') || 'Keine Einträge'));
                dialogBody.appendChild(details);
            });
        } catch (error) {
            dialogBody.textContent = 'Logs konnten nicht geladen werden: ' + cleanTechnicalError(error);
        }
    }

    async function copyValue(value) {
        try {
            await navigator.clipboard.writeText(value);
            toast('In die Zwischenablage kopiert');
        } catch {
            toast('Kopieren nicht möglich', 'error');
        }
    }

    async function handleAction(button) {
        const action = button.dataset.action;
        const model = state.aliases.models.find(item => item.alias === button.dataset.alias);
        if (action === 'refresh') return load({ force: true });
        if (action === 'add-model') return openAddDialog();
        if (action === 'model-details' && model) return showModelDetails(model);
        if (action === 'load-model' && model) return performRuntimeAction('switch', model);
        if (action === 'switch-selected-model') {
            const selectedAlias = root.querySelector('.model-console-switcher select')?.value;
            const selectedModel = state.aliases.models.find(item => item.alias === selectedAlias);
            if (selectedModel) return performRuntimeAction('switch', selectedModel);
        }
        if (action === 'restart-runtime') return performRuntimeAction('restart');
        if (action === 'stop-runtime') return performRuntimeAction('stop');
        if (action === 'start-runtime') return performRuntimeAction('start');
        if (action === 'retry-runtime') {
            const failed = state.runtimeAction;
            state.runtimeAction = null;
            return performRuntimeAction(failed.type, failed.model);
        }
        if (action === 'toggle-thinking') return toggleThinking();
        if (action === 'show-logs' || action === 'refresh-logs') return showLogs();
        if (action === 'retry-download') return retryDownload(button.dataset.target);
        if (action === 'remove-model' && model) return confirmAction(displayName(model) + ' entfernen?', 'Der Alias „' + model.alias + '“ wird aus der Konfiguration entfernt. Heruntergeladene Modelldateien bleiben erhalten.', 'Aus Konfiguration entfernen', 'confirm-remove-model', { alias: model.alias });
        if (action === 'confirm-remove-model') return removeModel(button.dataset.alias);
        if (action === 'delete-local-model' && model?.local) return confirmAction(
            displayName(model) + ' löschen?',
            'Lokale Dateien von „' + model.alias + '“ dauerhaft löschen?\n' + model.repo +
            '\nDer Alias wird ebenfalls entfernt. Aktive Modelle, Rollen-Zuordnungen und laufende Downloads verhindern die Löschung.',
            'Modell dauerhaft löschen', 'confirm-delete-local-model', { alias: model.alias }
        );
        if (action === 'confirm-delete-local-model') return deleteLocalModel(button.dataset.alias);
        if (action === 'delete-cache') return confirmAction('Hugging-Face-Dateien löschen?', 'Die lokal gespeicherten Hugging-Face-Dateien für „' + button.dataset.target + '“ werden dauerhaft gelöscht. Falls keine zweite lokale Kopie existiert, muss das Modell später erneut heruntergeladen werden. Der Konfigurations-Alias bleibt erhalten.', 'HF-Dateien löschen', 'confirm-delete-cache', { target: button.dataset.target });
        if (action === 'confirm-delete-cache') return deleteCache(button.dataset.target);
        if (action === 'submit-model') return submitModel();
        if (action === 'copy-value') return copyValue(button.dataset.value || '');
        if (action === 'close-dialog') return closeDialog();
    }

    function open() {
        state.visible = true;
        if (!state.loaded) load();
        else {
            render();
            scheduleRefresh(0);
        }
    }

    function close() {
        state.visible = false;
        clearTimeout(state.refreshTimer);
        state.refreshTimer = null;
        closeDialog();
    }

    if (root) {
        root.addEventListener('click', event => {
            const tab = event.target.closest('[data-model-console-tab]');
            if (tab) return setTab(tab.dataset.modelConsoleTab);
            const button = event.target.closest('[data-action]');
            if (button && !button.disabled) handleAction(button);
        });
        document.getElementById('modelConsoleAdd')?.addEventListener('click', openAddDialog);
        dialog?.addEventListener('click', event => {
            const button = event.target.closest('[data-action]');
            if (button && !button.disabled) {
                event.preventDefault();
                handleAction(button);
            }
        });
        dialog?.addEventListener('close', () => { state.modal = null; });
    }

    window.MLXModelConsole = {
        open,
        close,
        load,
        setTab,
        __test: {
            state,
            displayName,
            formatBytes,
            formatUptime,
            validateModelInput,
            aliasExists,
            deriveActionSteps,
            monitorMutation,
            modelAvailability,
            activeModel,
            statusView,
            canBeginRuntimeAction,
            setDependencies(dependencies = {}) {
                if (dependencies.fetch) fetchImpl = dependencies.fetch;
                if (dependencies.wait) waitImpl = dependencies.wait;
            },
        },
    };
})();
