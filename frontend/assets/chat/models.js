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

    function mt(key, fallback = '', variables = {}) {
        let value = window.MLXI18n?.t(
            `models.${key}`,
            fallback
        ) ?? fallback;

        Object.entries(variables).forEach(([name, replacement]) => {
            value = value.replaceAll(
                `{${name}}`,
                String(replacement ?? '')
            );
        });

        return value;
    }

    function modelLocale() {
        return window.MLXI18n?.getLocale?.() || 'en-US';
    }

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
        if (!value) return mt('unknown_error', 'Unknown error');
        if (typeof value === 'string') return value.replace(/^Error:\s*/i, '').trim();
        if (typeof value.detail === 'string') return value.detail;
        if (value.detail && typeof value.detail === 'object') {
            return value.detail.stderr || value.detail.stdout || JSON.stringify(value.detail);
        }
        return value.message || mt('unknown_error', 'Unknown error');
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
        if (!value) return typeof modelOrRepo === 'object' ? modelOrRepo.alias : mt('unnamed', 'Unnamed model');
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
        return size.toLocaleString(modelLocale(), { maximumFractionDigits: digits }) + ' ' + units[index];
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
        if (!normalizedAlias) errors.alias = mt('validation.alias_required', 'Alias is required.');
        else if (!/^[A-Za-z0-9._-]+$/.test(normalizedAlias)) errors.alias = mt('validation.alias_chars', 'Only letters, numbers, dots, underscores and hyphens are allowed.');
        if (!normalizedRepo) errors.repo = mt('validation.repo_required', 'Repository or local path is required.');
        else if (/[\x00-\x1f\x7f\\"`$|&]/.test(normalizedRepo)) errors.repo = mt('validation.unsafe_reference', 'Model reference contains unsafe characters.');
        else if (!normalizedRepo.startsWith('/') && !normalizedRepo.startsWith('~/') &&
            !/^[A-Za-z0-9_][A-Za-z0-9_.-]*\/[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(normalizedRepo)) {
            errors.repo = mt('validation.repo_format', 'Expected owner/model or an absolute local path.');
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
        if (model.local) return { state: 'ready', label: mt('status.ready', 'Ready') };
        const cache = cacheForModel(model);
        const job = jobForModel(model);
        if (isJobRunning(job)) return { state: 'download', label: mt('status.downloading', 'Downloading'), job };
        if (cache?.complete) return { state: 'ready', label: mt('status.ready', 'Ready'), cache };
        if (job?.status === 'failed' || job?.status === 'interrupted') return { state: 'error', label: mt('status.download_failed', 'Download failed'), job, cache };
        if (cache && !cache.complete) return { state: 'error', label: mt('status.download_incomplete', 'Download incomplete'), cache };
        return { state: 'missing', label: mt('status.missing', 'Not available locally') };
    }

    function statusView() {
        if (state.runtimeAction) {
            if (state.runtimeAction.error) return { kind: 'error', label: mt('status.error', 'Error') };
            return state.runtimeAction.type === 'stop'
                ? { kind: 'stopping', label: mt('status.stopping', 'Stopping') }
                : { kind: 'starting', label: mt('status.starting', 'Starting') };
        }
        if (state.error && !state.status) return { kind: 'error', label: mt('status.error', 'Error') };
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
        container.appendChild(badge(
            model.local
                ? mt('status.local', 'Local')
                : 'Hugging Face'
        ));
        if (includeThinking && state.status) container.appendChild(badge('Thinking ' + (
            state.status.thinking
                ? mt('status.on', 'On')
                : mt('status.off', 'Off')
        )));
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
            return [{ label: mt('runtime.wait_confirmation', 'Wait for runtime confirmation'), mode: action.phase === 'ready' ? 'done' : 'active' }];
        }
        const stopped = Boolean(action.observedOffline);
        const checking = action.phase === 'checking' || action.phase === 'ready';
        if (action.type === 'stop') {
            return [
                { label: mt('runtime.stop_runtime', 'Stop runtime'), mode: action.phase === 'ready' ? 'done' : 'active' },
                { label: mt('runtime.confirm_offline', 'Confirm offline status'), mode: action.phase === 'ready' ? 'done' : action.phase === 'stopped' ? 'active' : 'pending' },
            ];
        }
        return [
            { label: action.type === 'switch' ? mt('runtime.stop_previous', 'Stop previous model') : mt('runtime.stop_runtime', 'Stop runtime'), mode: stopped ? 'done' : action.phase === 'requesting' ? 'active' : 'pending' },
            { label: mt('runtime.initialize', 'Initialize model'), mode: checking || action.phase === 'ready' ? 'done' : action.phase === 'initializing' ? 'active' : 'pending' },
            { label: mt('runtime.check_ready', 'Check readiness'), mode: action.phase === 'ready' ? 'done' : checking ? 'active' : 'pending' },
        ];
    }

    function renderActionProgress(container) {
        if (!state.runtimeAction) return;
        const panel = node('div', 'model-console-action-progress');
        const title = state.runtimeAction.type === 'switch'
            ? mt(
                'runtime.loading',
                'Loading {model} …',
                { model: displayName(state.runtimeAction.model) }
            )
            : state.runtimeAction.type === 'restart'
                ? mt('runtime.restarting', 'Restarting model …')
                : state.runtimeAction.type === 'start'
                    ? mt('runtime.starting', 'Starting runtime …')
                    : state.runtimeAction.type === 'thinking'
                        ? mt('runtime.thinking_change', 'Changing Thinking …')
                        : mt('runtime.stopping', 'Stopping runtime …');
        panel.appendChild(node('strong', '', title));
        deriveActionSteps(state.runtimeAction).forEach(step => panel.appendChild(actionStep(step.label, step.mode)));
        if (state.runtimeAction.error) {
            const error = node('div', 'model-console-inline-error', state.runtimeAction.error);
            const retry = actionButton(mt('actions.retry', 'Try again'), 'retry-runtime');
            error.appendChild(retry);
            panel.appendChild(error);
        }
        container.appendChild(panel);
    }

    function renderHero() {
        const hero = node('section', 'model-console-hero');
        const heading = node('div', 'model-console-hero-heading');
        const label = node('div', 'model-console-eyebrow', mt('runtime.active_model', 'Active model'));
        heading.append(label, statusChip());
        hero.appendChild(heading);

        const model = activeModel();
        const title = node('h5', '', model ? displayName(model) : mt('runtime.no_model', 'No model configured'));
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
                actions.append(actionButton(mt('actions.restart', '↻ Restart'), 'restart-runtime'), actionButton(mt('actions.stop', '■ Stop'), 'stop-runtime', { danger: true }));
            } else if (model || state.status?.model) {
                actions.append(actionButton(mt('actions.start', '▶ Start'), 'start-runtime', { primary: true }));
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
        if (active) titleLine.appendChild(badge(
            '● ' + mt('status.active', 'Active'),
            'active'
        ));
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
            actions.appendChild(actionButton(mt('actions.load', '▶ Load'), 'load-model', {
                alias: model.alias,
                primary: true,
                disabled: globallyBusy || !ready,
                title: ready ? '' : availability.label,
            }));
        }
        const menu = node('details', 'model-console-menu');
        const summary = node('summary', 'model-console-icon-button', '•••');
        summary.setAttribute('aria-label', mt(
            'models.actions_for',
            'Actions for {model}',
            { model: model.alias }
        ));
        menu.appendChild(summary);
        const menuPanel = node('div', 'model-console-menu-panel');
        menuPanel.appendChild(actionButton(mt('actions.details', 'Details'), 'model-details', { alias: model.alias }));
        if (!active) menuPanel.appendChild(actionButton(mt('actions.load_model', 'Load model'), 'load-model', { alias: model.alias, disabled: globallyBusy || availability.state !== 'ready' }));
        if (availability.state === 'error') menuPanel.appendChild(actionButton(mt('actions.continue_download', 'Resume download'), 'retry-download', { target: model.alias }));
        menuPanel.appendChild(actionButton(mt('actions.remove_config', 'Remove from configuration'), 'remove-model', { alias: model.alias, danger: true, disabled: active || globallyBusy }));
        if (model.local && model.available !== false) {
            const protectedModel = model.active || activeModel()?.repo === model.repo;
            actions.appendChild(actionButton(mt('actions.delete', 'Delete'), 'delete-local-model', {
                alias: model.alias, danger: true,
                disabled: protectedModel || globallyBusy || isJobRunning(jobForModel(model)),
                title: protectedModel ? mt('models.active_protected', 'The active model is protected even when the runtime is stopped.') : mt('models.delete_local', 'Delete local model files and alias'),
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
        const section = node(
            'details',
            'model-console-section model-console-collapsible'
        );
        section.open = true;

        const head = node(
            'summary',
            'model-console-section-heading model-console-collapsible-summary'
        );
        head.append(
            node(
                'h5',
                '',
                mt('models.installed', 'Installed models')
            ),
            node(
                'span',
                '',
                String(state.aliases.models.length)
            )
        );
        section.appendChild(head);
        if (!state.aliases.models.length) {
            const empty = node('div', 'model-console-empty');
            empty.append(node('strong', '', mt('models.none', 'No models yet')), node('p', '', mt('models.none_description', 'Add a local MLX model or a Hugging Face repository.')), actionButton(mt('models.add', '+ Add model'), 'add-model', { primary: true }));
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
            const copy = actionButton(mt('actions.copy', 'Copy'), 'copy-value');
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
            definitionRow(mt('models.model', 'Model'), model?.alias || state.status?.model),
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
            node('strong', '', mt('runtime.active_model', 'Active model')),
            node('p', '', mt('runtime.switch_description', 'Switches the model through the existing runtime manager.'))
        );
        const switcherControls = node('div', 'model-console-switcher');
        const modelSelect = node('select');
        modelSelect.setAttribute('aria-label', mt('runtime.select_model', 'Select runtime model'));
        availableModels.forEach(item => {
            const option = node('option', '', item.alias);
            option.value = item.alias;
            if (item.alias === model?.alias) option.selected = true;
            modelSelect.appendChild(option);
        });
        const switchButton = actionButton(mt('actions.switch_model', 'Switch model'), 'switch-selected-model', {
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
        thinkingInfo.append(node('strong', '', 'Thinking'), node('p', '', mt('runtime.thinking_description', 'Enables extended reasoning when supported by the model.')));
        const thinkingButton = actionButton(state.status?.thinking ? 'An' : 'Aus', 'toggle-thinking', { primary: Boolean(state.status?.thinking), disabled: !state.status?.online || Boolean(state.runtimeAction) });
        thinkingButton.setAttribute('aria-pressed', state.status?.thinking ? 'true' : 'false');
        thinking.append(thinkingInfo, thinkingButton);
        section.appendChild(thinking);

        renderActionProgress(section);
        if (!state.runtimeAction) {
            const actions = node('div', 'model-console-actions');
            if (state.status?.online) actions.append(actionButton(mt('actions.restart', '↻ Restart'), 'restart-runtime'), actionButton(mt('actions.stop', '■ Stop'), 'stop-runtime', { danger: true }));
            else if (model || state.status?.model) actions.append(actionButton(mt('actions.start', '▶ Start'), 'start-runtime', { primary: true }));
            actions.appendChild(actionButton(mt('actions.show_logs', 'Show logs'), 'show-logs'));
            section.appendChild(actions);
        }
        fragment.appendChild(section);

        const technical = node('details', 'model-console-technical');
        technical.appendChild(node('summary', '', mt('runtime.details', 'Runtime details')));
        const technicalList = node('dl', 'model-console-definitions');
        const repo = model?.repo || state.status?.model;
        [
            definitionRow(mt('runtime.endpoint', 'Server endpoint'), (mlx.port ?? state.status?.port) ? 'http://127.0.0.1:' + (mlx.port ?? state.status?.port) : null, { mono: true, copy: true }),
            definitionRow(model?.local ? mt('storage.local_path', 'Local model path') : 'Repository', repo, { mono: true, copy: true }),
            definitionRow(mt('runtime.start_parameters', 'Start parameters'), Array.isArray(mlx.server_args) && mlx.server_args.length ? mlx.server_args.join(' ') : null, { mono: true, copy: true }),
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
            info.appendChild(node('span', 'model-console-availability error', mt(
                'storage.incomplete',
                'Incomplete · {count} files',
                { count: item.incomplete_files }
            )));
        } else if (item.duplicate) {
            const extra = item.duplicate_size || formatBytes(item.duplicate_size_bytes);
            info.appendChild(node('span', 'model-console-availability error', mt(
                'storage.duplicate',
                'Duplicate'
            ) + (
                extra
                    ? mt(
                        'storage.duplicate_extra',
                        ' · approx. {size} extra',
                        { size: extra }
                    )
                    : ''
            )));
        } else if (item.possible_duplicate) {
            info.appendChild(node('span', 'model-console-availability error', mt('storage.possible_duplicate', 'Possible duplicate · check local model path')));
        }
        const right = node('div', 'model-console-storage-actions');
        right.appendChild(node('strong', '', item.size || formatBytes(item.size_bytes) || '–'));
        if (!item.active) right.appendChild(actionButton(mt('actions.delete_hf', 'Delete HF files'), 'delete-cache', { target: item.alias || item.repo, danger: true }));
        else right.appendChild(badge(mt('runtime.active_model', 'Active model'), 'active'));
        row.append(info, right);
        return row;
    }

    function renderStorage() {
        const fragment = document.createDocumentFragment();
        const summary = node('section', 'model-console-storage-summary');
        const systemMemory = state.system?.system || {};
        summary.append(
            metric('Unified Memory', systemMemory.total_gb != null ? systemMemory.total_gb + ' GB' : '–'),
            metric(mt('storage.free_ram', 'Free RAM'), systemMemory.free_percent != null ? systemMemory.free_percent + ' %' : '–'),
            metric(mt('hf_storage', 'HF storage'), state.cache.total_size || formatBytes(state.cache.total_size_bytes) || '–'),
            metric(mt('storage.hf_models', 'HF models'), String(state.cache.count ?? state.cache.models.length))
        );
        if (state.cache.path) {
            const path = node('div', 'model-console-cache-path');
            path.append(node('span', '', mt('storage.hf_storage', 'Hugging Face storage')), node('code', '', state.cache.path), actionButton(mt('actions.copy', 'Copy'), 'copy-value'));
            path.lastChild.dataset.value = state.cache.path;
            summary.appendChild(path);
        }
        fragment.appendChild(summary);
        const localModels = state.aliases.models.filter(model => model.local);
        if (localModels.length) {
            const localSection = node('section', 'model-console-section');
            const localHead = node('div', 'model-console-section-heading');
            localHead.append(node('h5', '', mt('storage.local_paths', 'Local model paths')), node('span', '', String(localModels.length)));
            localSection.appendChild(localHead);
            const localList = node('div', 'model-console-list');
            localModels.forEach(model => {
                const row = node('article', 'model-console-storage-row');
                const info = node('div', 'model-console-row-main');
                info.append(node('strong', '', displayName(model)), node('span', 'model-console-storage-repo', model.repo));
                const duplicateInfo = duplicateInfoForLocalModel(model);
                if (duplicateInfo?.exact) {
                    const extra = duplicateInfo.cache.duplicate_size || formatBytes(duplicateInfo.cache.duplicate_size_bytes);
                    info.appendChild(node('span', 'model-console-availability error', mt(
                'storage.duplicate',
                'Duplicate'
            ) + (
                extra
                    ? mt(
                        'storage.duplicate_extra',
                        ' · approx. {size} extra',
                        { size: extra }
                    )
                    : ''
            )));
                } else if (duplicateInfo?.possible) {
                    info.appendChild(node('span', 'model-console-availability error', mt('storage.possible_hf_duplicate', 'Possible duplicate with Hugging Face · please check')));
                }
                const right = node('div', 'model-console-storage-actions');
                right.appendChild(badge(model.active ? mt('runtime.active_model', 'Active model') : mt('storage.local_models_location', 'Local under ~/Models'), model.active ? 'active' : ''));
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
            node('h5', '', mt('storage.hf_available', 'Locally available Hugging Face models')),
            node('span', '', String(visibleCacheModels.length))
        );
        section.appendChild(head);

        if (!visibleCacheModels.length) {
            section.appendChild(
                node(
                    'div',
                    'model-console-empty',
                    mt('storage.none_hf', 'No locally available Hugging Face models found.')
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
            node('h5', '', mt('downloads.title', 'Downloads & Jobs')),
            node('span', '', String(state.jobs.length))
        );
        const cleanup = node('div', 'history-cleanup');
        window.MLXHistoryCleanup?.mount(cleanup, {
            kind: 'downloads',
            onComplete: async data => {
                toast(mt(
                    'downloads.removed',
                    '{count} download entries removed',
                    { count: data.removed }
                ));
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
                    mt('downloads.none', 'There are currently no download jobs.')
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
                job.status === 'running' ? mt('status.downloading', 'Downloading') :
                job.status === 'queued' ? mt('status.waiting', 'Queued') :
                job.status === 'detached' ? mt('remaining.running', 'Running') :
                job.status === 'completed' ? mt('status.completed', 'Completed') :
                job.status === 'failed' ? mt('status.failed', 'Failed') :
                job.status === 'interrupted' ? mt('status.interrupted', 'Interrupted') :
                (job.status || mt('status.unknown', 'Unknown'));

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
        text.append(node('strong', '', mt('messages.load_failed', 'Data could not be loaded completely.')), node('span', '', state.error));
        banner.append(text, actionButton(mt('actions.reload', 'Reload'), 'refresh'));
        return banner;
    }

    function render() {
        if (!root || !content) return;
        const title = document.getElementById('modelConsoleTitle');
        const description = root.querySelector('.model-console-header p');
        const addButton = document.getElementById('modelConsoleAdd');
        const headings = {
            models: [mt('models.title', 'Models'), mt('models.description', 'Manage installed models, downloads and model roles.')],
            runtime: ['Runtime', mt('runtime.switch_description', 'Switches the model through the existing runtime manager.')],
            storage: [mt('storage', 'Storage'), mt('storage_description', 'Overview of locally available models and their storage usage.')],
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
            detail.append(node('summary', '', mt('actions.details', 'Details')), node('div', '', details));
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
        form.innerHTML = `
            <label>
                ${mt('dialog.alias', 'Alias')}
                <input
                    id="modelAddAlias"
                    autocomplete="off"
                    placeholder="e.g. qwen38"
                >
            </label>

            <div
                id="modelAddAliasError"
                class="model-console-field-error"
            ></div>

            <label>
                ${mt(
                    'dialog.repository_or_path',
                    'Hugging Face repository or local model path'
                )}

                <div style="display:flex;gap:8px;align-items:center">
                    <input
                        id="modelAddRepo"
                        style="flex:1"
                        autocomplete="off"
                        placeholder="mlx-community/model or ~/Models/…"
                    >

                    <button
                        id="modelSelectFolder"
                        class="model-console-button"
                        type="button"
                    >${mt('actions.select', 'Select…')}</button>
                </div>
            </label>

            <div
                id="modelAddRepoError"
                class="model-console-field-error"
            ></div>

            <label>
                ${mt('dialog.quantization', 'Quantization')}

                <select id="modelAddQuantization">
                    <option value="">
                        ${mt('dialog.auto_detect', 'Detect automatically')}
                    </option>
                    <option value="2-bit">2-bit</option>
                    <option value="4-bit">4-bit</option>
                    <option value="6-bit">6-bit</option>
                    <option value="8-bit">8-bit</option>
                </select>
            </label>

            <p class="settings-hint">
                ${mt(
                    'dialog.remote_hint',
                    'Remote models are downloaded as background jobs after being added.'
                )}
            </p>
        `;

        const selectFolder = form.querySelector('#modelSelectFolder');

        selectFolder?.addEventListener('click', async () => {
            const repoInput = document.getElementById('modelAddRepo');
            const repoError = document.getElementById('modelAddRepoError');

            selectFolder.disabled = true;
            selectFolder.textContent = mt('dialog.opening', 'Opening …');
            repoError.textContent = '';

            try {
                const result = await requestJson('/api/mlx/models/select-folder');

                if (!result.cancelled && result.path) {
                    repoInput.value = result.path;

                    if (!result.looks_like_model) {
                        repoError.textContent = mt('validation.folder_warning', 'Note: No typical MLX model files were detected in the selected folder.');
                    }

                    repoInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            } catch (error) {
                repoError.textContent = cleanTechnicalError(error);
            } finally {
                selectFolder.disabled = false;
                selectFolder.textContent = mt('dialog.select', 'Select…');
            }
        });
        const cancel = actionButton(mt('actions.cancel', 'Cancel'), 'close-dialog');
        const submit = actionButton(mt('remaining.add_model', 'Add model'), 'submit-model', { primary: true });
        openDialog({ eyebrow: mt('models.title', 'Models'), title: mt('remaining.add_model', 'Add model'), body: form, actions: [cancel, submit] });
    }

    function showModelDetails(model) {
        const cache = cacheForModel(model);
        const details = node('dl', 'model-console-definitions');
        [
            definitionRow('Alias', model.alias, { mono: true, copy: true }),
            definitionRow(mt('dialog.display_name', 'Display name'), displayName(model)),
            definitionRow(model.local ? mt('storage.local_path', 'Local model path') : 'Repository', model.repo, { mono: true, copy: true }),
            definitionRow(!model.local && cache?.path ? 'Cache-Pfad' : null, cache?.path, { mono: true, copy: true }),
            definitionRow('Backend', model.backend === 'vlm' ? 'VLM' : 'LLM'),
            definitionRow(mt('dialog.quantization', 'Quantization'), model.quantization),
            definitionRow('Vision', model.vision ? 'Ja' : 'Nein'),
            definitionRow(mt('storage.source', 'Source'), model.local ? mt('storage.local_filesystem', 'Local file system') : 'Hugging Face'),
            definitionRow(mt('storage.cache_size', 'Cache size'), cache?.size || formatBytes(cache?.size_bytes)),
            model.active ? definitionRow('Thinking', state.status ? (state.status.thinking ? 'An' : 'Aus') : null) : null,
        ].filter(Boolean).forEach(item => details.appendChild(item));
        openDialog({ eyebrow: mt('dialog.technical_details', 'Technical details'), title: displayName(model), body: details, actions: [actionButton(mt('actions.close', 'Close'), 'close-dialog')] });
    }

    function confirmAction(title, message, confirmLabel, confirmAction, data = {}) {
        const body = node('div', 'model-console-confirm');
        body.appendChild(node('p', '', message));
        const cancel = actionButton(mt('actions.cancel', 'Cancel'), 'close-dialog');
        const confirm = actionButton(confirmLabel, confirmAction, { danger: true });
        Object.entries(data).forEach(([key, value]) => { confirm.dataset[key] = value; });
        openDialog({ eyebrow: mt('dialog.confirmation', 'Confirmation'), title, body, actions: [cancel, confirm] });
    }

    async function submitModel() {
        const aliasInput = document.getElementById('modelAddAlias');
        const repoInput = document.getElementById('modelAddRepo');
        const quantization = document.getElementById('modelAddQuantization')?.value || null;
        const validation = validateModelInput(aliasInput?.value, repoInput?.value);
        const duplicate = aliasExists(validation.alias);
        if (duplicate) validation.errors.alias = mt('validation.alias_exists', 'This alias already exists.');
        if (validation.repo.startsWith('/') && quantization) {
            validation.errors.repo = mt('validation.local_quantization', 'Existing quantization is used automatically for local model paths.');
        }
        const aliasError = document.getElementById('modelAddAliasError');
        const repoError = document.getElementById('modelAddRepoError');
        aliasError.textContent = validation.errors.alias || '';
        repoError.textContent = validation.errors.repo || '';
        if (!validation.valid || duplicate || validation.errors.repo) return;
        const button = dialogActions.querySelector('[data-action="submit-model"]');
        button.disabled = true;
        button.textContent = mt('dialog.adding', 'Adding …');
        try {
            await requestJson('/api/mlx/models/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alias: validation.alias, repo: validation.repo, quantization }),
            });
            closeDialog();
            toast(mt(
                'messages.added',
                '{model} added',
                { model: validation.alias }
            ));
            await load({ force: true });
            window.loadModelRoles?.();
        } catch (error) {
            repoError.textContent = cleanTechnicalError(error);
            button.disabled = false;
            button.textContent = mt('remaining.add_model', 'Add model');
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
        throw new Error(mt('runtime.confirmation_timeout', 'The runtime did not confirm the expected state in time.'));
    }

    function canBeginRuntimeAction() {
        return !state.runtimeAction && !state.deletingModel && !window.MLXChatRuntime?.isSwitching?.();
    }

    async function performRuntimeAction(type, model = null) {
        if (!canBeginRuntimeAction()) return false;
        const previous = activeModel();
        const expectedRepo = type === 'switch' ? model?.repo : previous?.repo || state.status?.model;
        state.runtimeAction = { type, model, phase: 'requesting', observedOffline: false, error: null };
        if (liveRegion) liveRegion.textContent = type === 'switch' ? mt(
            'runtime.loading_sentence',
            '{model} is loading.',
            { model: displayName(model) }
        ) : mt('runtime.action_running', 'Runtime action in progress.');
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
            const success = type === 'switch'
                ? mt('runtime.loaded', '{model} loaded', { model: displayName(model) })
                : type === 'restart'
                    ? mt('runtime.restarted', 'Runtime restarted')
                    : type === 'start'
                        ? mt('runtime.started', 'Runtime started')
                        : mt('runtime.stopped', 'Runtime stopped');
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
            if (liveRegion) liveRegion.textContent = mt('runtime.action_failed', 'Runtime action failed') + ': ' + message;
            toast(mt('runtime.action_failed', 'Runtime action failed'), 'error', message);
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
            if (!confirmed) throw new Error(mt('runtime.thinking_timeout', 'Thinking was not confirmed by the runtime in time.'));
            toast('Thinking ' + (enabled ? mt('status.on', 'enabled') : mt('status.off', 'disabled')));
            state.runtimeAction = null;
            await load({ force: true });
            window.MLXChatRuntime?.refreshModelState?.().catch(() => {});
        } catch (error) {
            const message = cleanTechnicalError(error);
            state.runtimeAction = null;
            toast(mt('runtime.thinking_failed', 'Thinking could not be changed'), 'error', message);
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
            toast(mt(
                'messages.removed',
                '{model} removed from configuration',
                { model: alias }
            ));
            await load({ force: true });
            window.loadModelRoles?.();
        } catch (error) {
            closeDialog();
            toast(mt('messages.remove_failed', 'Model could not be removed'), 'error', cleanTechnicalError(error));
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
            toast(mt(
                'messages.deleted',
                '{model}: local files and alias deleted',
                { model: alias }
            ));
        } catch (error) {
            closeDialog();
            toast(mt('messages.delete_failed', 'Model could not be deleted'), 'error', cleanTechnicalError(error));
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
            toast(mt('messages.cache_deleted', 'Cache entry deleted'));
            await load({ force: true });
        } catch (error) {
            closeDialog();
            toast(mt('messages.cache_delete_failed', 'Cache could not be deleted'), 'error', cleanTechnicalError(error));
        }
    }

    async function retryDownload(target) {
        try {
            await requestJson('/api/mlx/jobs/retry/' + encodeURIComponent(target), { method: 'POST' });
            toast(mt('messages.download_continues', 'Download resumed'));
            await load({ force: true });
        } catch (error) {
            toast(mt('status.download_failed', 'Download failed'), 'error', cleanTechnicalError(error));
        }
    }

    async function showLogs() {
        const loading = node('div', 'model-console-log', mt('dialog.loading_logs', 'Loading logs …'));
        openDialog({ eyebrow: 'Runtime', title: mt('dialog.last_logs', 'Latest logs'), body: loading, actions: [actionButton(mt('actions.refresh', 'Refresh'), 'refresh-logs'), actionButton(mt('actions.close', 'Close'), 'close-dialog')] });
        try {
            const data = await requestJson('/api/mlx/logs/all?limit=120');
            const sources = Array.isArray(data.sources) ? data.sources : [];
            dialogBody.innerHTML = '';
            if (!sources.length) dialogBody.appendChild(node('div', 'model-console-empty', mt('dialog.no_logs', 'No logs available.')));
            sources.forEach(source => {
                const details = node('details', 'model-console-log-source');
                if (source.id === 'mlx-errors') details.open = true;
                details.appendChild(node('summary', '', source.name || source.id));
                details.appendChild(node('pre', 'model-console-log', (source.lines || []).join('\n') || mt('dialog.no_entries', 'No entries')));
                dialogBody.appendChild(details);
            });
        } catch (error) {
            dialogBody.textContent = mt('dialog.logs_failed', 'Could not load logs') + ': ' + cleanTechnicalError(error);
        }
    }

    async function copyValue(value) {
        try {
            await navigator.clipboard.writeText(value);
            toast(mt('dialog.copied', 'Copied to clipboard'));
        } catch {
            toast(mt('dialog.copy_failed', 'Copy failed'), 'error');
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
        if (action === 'remove-model' && model) return confirmAction(displayName(model) + mt(
            'confirm.remove_suffix',
            ' remove?'
        ), mt(
            'confirm.remove_alias',
            'Alias “{alias}” will be removed from the configuration. Downloaded model files will remain.',
            { alias: model.alias }
        ), mt('actions.remove_config', 'Remove from configuration'), 'confirm-remove-model', { alias: model.alias });
        if (action === 'confirm-remove-model') return removeModel(button.dataset.alias);
        if (action === 'delete-local-model' && model?.local) return confirmAction(
            displayName(model) + mt(
            'confirm.delete_suffix',
            ' delete?'
        ),
            mt(
                'local_files_prefix',
                'Local files for “{alias}”',
                { alias: model.alias }
            ) + mt(
            'confirm.delete_suffix',
            ' delete?'
        ) + model.repo +
            mt(
            'confirm.remove_alias_note',
            '\nThe alias will also be removed. Active models, role assignments and running downloads prevent deletion.'
        ),
            mt('models.delete_permanently', 'Delete model permanently'), 'confirm-delete-local-model', { alias: model.alias }
        );
        if (action === 'confirm-delete-local-model') return deleteLocalModel(button.dataset.alias);
        if (action === 'delete-cache') return confirmAction(mt('dialog.delete_hf_title', 'Delete Hugging Face files?'), mt(
            'confirm.delete_cache_full',
            'The locally stored Hugging Face files for “{model}” will be permanently deleted. If no second local copy exists, the model will need to be downloaded again later. The configuration alias will remain.',
            { model: button.dataset.target }
        ), mt('actions.delete_hf', 'Delete HF files'), 'confirm-delete-cache', { target: button.dataset.target });
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

    document.addEventListener('mlx-language-changed', () => {
        if (state.loaded) {
            render();
        }
    });

})();
