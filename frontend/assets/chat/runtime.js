(function () {

    function rut(key, fallback = '', variables = {}) {
        let value = window.MLXI18n?.t(
            `runtime_ui.${key}`,
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

    const SETTINGS_KEY = 'mlx-web-chat-settings-v1';
    const DEFAULT_TEMPERATURE = 0.7;
    const DEFAULT_MAX_TOKENS = 3000;
    const MAX_TOKENS_LIMIT = 32000;
    const UI_SETTINGS_KEY = 'mlx-web-chat-ui-settings-v1';
    let globalSettings = {
        metrics_mode: 'compact',
        auto_scroll: true,
        show_runtime_thinking: true,
        auto_compact: true,
        default_preset: 'general',
        default_temperature: DEFAULT_TEMPERATURE,
        default_max_tokens: DEFAULT_MAX_TOKENS,
        thinking_preferred: false
    };

    const SYSTEM_PROMPT_PRESETS = {
        general: {
            label: 'General',
            prompt: 'You are a helpful and precise assistant.',
            temperature: 0.7,
            max_tokens: 3000
        },
        coding: {
            label: 'Coding',
            prompt: 'You are an experienced software developer. Respond with technical precision, prefer robust and maintainable solutions, and explain important decisions concisely.',
            temperature: 0.2,
            max_tokens: 5000
        },
        analysis: {
            label: 'Analysis',
            prompt: 'Analyze problems in a structured and critical way. Clearly separate facts, assumptions, and conclusions.',
            temperature: 0.3,
            max_tokens: 5000
        },
        roleplay: {
            label: 'Roleplay',
            prompt: 'Stay consistent in role, tone, and context. Avoid unnecessary meta commentary.',
            temperature: 0.9,
            max_tokens: 4000
        },
        'concise-de': {
            label: 'Deutsch knapp',
            prompt: 'Antworte auf Deutsch, präzise, knapp und ohne unnötige Wiederholungen.',
            temperature: 0.4,
            max_tokens: 2000
        }
    };

    let isGenerating;
    let legacySystemPrompt = '';
    let switchingModel = false;
    let switchingThinking = false;
    let modelAliases = [];
    let runtimeInfoInterval = null;
    let runtimeInfoRefreshing = false;
    const BOTTOM_TOLERANCE = 88;
    let autoScrollEnabled = true;
    let programmaticScroll = false;
    let programmaticScrollTarget = null;
    let programmaticScrollVersion = 0;
    let forceNextRenderToBottom = true;
    let hasNewContentBelow = false;
    let lastScrollTop = 0;
    let scrollFrame = null;
    let buttonFrame = null;
    let scrollBottomButton = null;

    const input = document.getElementById('input');
    const messagesElement = document.getElementById('messages');
    const sendButton = document.getElementById('sendButton');
    const systemPrompt = document.getElementById('systemPrompt');
    const systemPromptPreset = document.getElementById(
        'systemPromptPreset'
    );
    const temperature = document.getElementById('temperature');
    const maxTokens = document.getElementById('maxTokens');
    const showMetrics = document.getElementById('showMetrics');
    const autoScroll = document.getElementById('autoScroll');
    const showRuntimeThinking = document.getElementById('showRuntimeThinking');
    const autoCompact = document.getElementById('autoCompact');
    const defaultPreset = document.getElementById('defaultPreset');
    const defaultTemperature = document.getElementById('defaultTemperature');
    const defaultMaxTokens = document.getElementById('defaultMaxTokens');
    const thinkingPreferred = document.getElementById('thinkingPreferred');
    const modelTitle = document.getElementById('modelTitle');
    const modelPopover = document.getElementById('modelPopover');
    const modelList = document.getElementById('modelList');
    const modelSwitchStatus = document.getElementById(
        'modelSwitchStatus'
    );
    const runtimeInfoButton = document.getElementById(
        'runtimeInfoButton'
    );
    const runtimePopover = document.getElementById(
        'runtimePopover'
    );
    const runtimeInfoContent = document.getElementById(
        'runtimeInfoContent'
    );

    function configure(options) {
        isGenerating = options.isGenerating;
    }

function updateContext() {
    const session = MLXChatSessions.currentSession();
    const {
        maxContextChars,
        compactAtChars
    } = MLXChatCompact.getContextLimits();

    const chars = (
        session?.messages || []
    ).reduce(
        (sum, message) =>
            sum + (message.content || '').length,
        0
    );

    const tokens =
        Math.max(0, Math.round(chars / 4));

    const percent =
        Math.min(
            100,
            Math.round(
                chars / maxContextChars * 100
            )
        );

    document.getElementById(
        'contextText'
    ).textContent =
        tokens.toLocaleString('de-DE') +
        ' Tokens · ' +
        percent +
        ' %';

    const fill =
        document.getElementById(
            'contextFill'
        );

    fill.style.width =
        percent + '%';

    if (chars >= maxContextChars) {
        fill.style.background =
            'var(--red)';

    } else if (
        chars >= compactAtChars
    ) {
        fill.style.background =
            '#e0a84f';

    } else {
        fill.style.background =
            'var(--blue)';
    }
}


function distanceFromBottom() {
    return Math.max(
        0,
        messagesElement.scrollHeight -
        messagesElement.scrollTop -
        messagesElement.clientHeight
    );
}


function isNearBottom() {
    return distanceFromBottom() <= BOTTOM_TOLERANCE;
}


function updateScrollBottomButton() {
    if (!scrollBottomButton) return;

    const visible =
        hasNewContentBelow &&
        !isNearBottom();

    scrollBottomButton.classList.toggle(
        'visible',
        visible
    );
    scrollBottomButton.setAttribute(
        'aria-hidden',
        visible ? 'false' : 'true'
    );
}


function scheduleButtonUpdate() {
    if (buttonFrame !== null) return;

    buttonFrame = requestAnimationFrame(() => {
        buttonFrame = null;
        updateScrollBottomButton();
    });
}


function setProgrammaticScrollTop(top) {
    const version = ++programmaticScrollVersion;
    const previousBehavior =
        messagesElement.style.scrollBehavior;

    programmaticScroll = true;
    messagesElement.style.scrollBehavior = 'auto';
    messagesElement.scrollTop = top;
    messagesElement.style.scrollBehavior = previousBehavior;
    lastScrollTop = messagesElement.scrollTop;
    programmaticScrollTarget = lastScrollTop;

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            if (version === programmaticScrollVersion) {
                programmaticScroll = false;
                programmaticScrollTarget = null;
            }
        });
    });
}


function scheduleScrollBottom(force = false) {
    if (scrollFrame !== null) {
        cancelAnimationFrame(scrollFrame);
    }

    scrollFrame = requestAnimationFrame(() => {
        scrollFrame = null;

        if (
            !force &&
            (
                !globalSettings.auto_scroll ||
                !autoScrollEnabled
            )
        ) {
            hasNewContentBelow = true;
            scheduleButtonUpdate();
            return;
        }

        setProgrammaticScrollTop(
            messagesElement.scrollHeight
        );
        hasNewContentBelow = false;
        scheduleButtonUpdate();
    });
}


function scrollBottom(duringStreaming = false) {
    if (duringStreaming) {
        contentUpdated();
        return;
    }

    scheduleScrollBottom(false);
}


function beginUserMessage() {
    autoScrollEnabled = true;
    hasNewContentBelow = false;
    forceNextRenderToBottom = true;
    scheduleScrollBottom(true);
}


function resetScrollForChat() {
    autoScrollEnabled = true;
    hasNewContentBelow = false;
    forceNextRenderToBottom = true;
    scheduleButtonUpdate();
}


function beforeMessagesRender() {
    return {
        scrollTop: messagesElement.scrollTop,
        scrollHeight: messagesElement.scrollHeight,
        followLatest:
            globalSettings.auto_scroll &&
            autoScrollEnabled,
        forceBottom: forceNextRenderToBottom
    };
}


function afterMessagesRender(snapshot, options = {}) {
    if (!snapshot) return;

    const forceBottom = snapshot.forceBottom;
    forceNextRenderToBottom = false;

    if (forceBottom || snapshot.followLatest) {
        scheduleScrollBottom(forceBottom);
        return;
    }

    const maxScrollTop = Math.max(
        0,
        messagesElement.scrollHeight -
        messagesElement.clientHeight
    );
    setProgrammaticScrollTop(
        Math.min(snapshot.scrollTop, maxScrollTop)
    );

    if (
        options.contentUpdated ||
        messagesElement.scrollHeight >
            snapshot.scrollHeight + 1
    ) {
        hasNewContentBelow = true;
    }

    scheduleButtonUpdate();
}


function contentUpdated() {
    if (
        globalSettings.auto_scroll &&
        autoScrollEnabled
    ) {
        scheduleScrollBottom(false);
        return;
    }

    if (!isNearBottom()) {
        hasNewContentBelow = true;
    }
    scheduleButtonUpdate();
}


function handleMessagesScroll() {
    const currentScrollTop =
        messagesElement.scrollTop;

    if (
        programmaticScroll &&
        Math.abs(
            currentScrollTop -
            (programmaticScrollTarget ?? currentScrollTop)
        ) <= 1
    ) {
        lastScrollTop = currentScrollTop;
        scheduleButtonUpdate();
        return;
    }

    if (programmaticScroll) {
        // A real wheel/trackpad/touch/keyboard/scrollbar movement can arrive
        // before the programmatic guard is released. A position that differs
        // from the intended target is therefore treated as user input.
        programmaticScroll = false;
        programmaticScrollTarget = null;
        programmaticScrollVersion++;
    }

    const movedUp =
        currentScrollTop < lastScrollTop - 1;
    const nearBottom = isNearBottom();

    if (movedUp || !nearBottom) {
        autoScrollEnabled = false;
        if (scrollFrame !== null) {
            cancelAnimationFrame(scrollFrame);
            scrollFrame = null;
        }
    } else if (nearBottom) {
        autoScrollEnabled = true;
        hasNewContentBelow = false;
    }

    lastScrollTop = currentScrollTop;
    scheduleButtonUpdate();
}


function initScrollBehavior() {
    if (!messagesElement) return;

    messagesElement.addEventListener(
        'scroll',
        handleMessagesScroll,
        { passive: true }
    );

    scrollBottomButton =
        document.createElement('button');
    scrollBottomButton.id = 'scrollBottomButton';
    scrollBottomButton.className =
        'scroll-bottom-button';
    scrollBottomButton.type = 'button';
    scrollBottomButton.title = rut('new_messages', 'New messages');
    scrollBottomButton.setAttribute(
        'aria-label',
        rut('jump_new', 'Jump to new messages')
    );
    scrollBottomButton.setAttribute(
        'aria-hidden',
        'true'
    );
    scrollBottomButton.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 5v14"></path>
            <path d="m6 13 6 6 6-6"></path>
        </svg>
    `;

    messagesElement.parentElement.appendChild(
        scrollBottomButton
    );

    scrollBottomButton.addEventListener(
        'click',
        () => {
            autoScrollEnabled = true;
            hasNewContentBelow = false;
            scheduleScrollBottom(true);
        }
    );

    window.addEventListener(
        'resize',
        scheduleButtonUpdate
    );

    lastScrollTop = messagesElement.scrollTop;
    updateScrollBottomButton();
}


function autoResize() {
    input.style.height = 'auto';

    input.style.height =
        Math.min(
            input.scrollHeight,
            230
        ) + 'px';
}


function updateSendButton() {
    if (isSwitching()) {
        sendButton.textContent = '…';
        sendButton.disabled = true;
        sendButton.classList.remove('stop');

    } else if (isGenerating()) {
        sendButton.textContent = '■';
        sendButton.disabled = false;
        sendButton.classList.add('stop');
    } else {
        sendButton.textContent = '↑';
        sendButton.disabled = false;
        sendButton.classList.remove('stop');
    }
}


function isSwitching() {
    return switchingModel || switchingThinking;
}


function setExternalRuntimeBusy(busy) {
    switchingModel = Boolean(busy);
    updateSendButton();

    if (modelAliases.length) {
        renderModelList();
    }
}


async function refreshModelState() {
    await loadModelAliases();
    return loadStatus();
}


function modelAliasFor(status) {
    const active =
        modelAliases.find(
            item => item.repo === status.model
        ) ||
        modelAliases.find(item => item.active);

    return active?.alias || status.model || rut('no_model', 'No model');
}



function activeModelMetadata() {
    return (
        modelAliases.find(item => item.active) ||
        null
    );
}


function supportsVision() {
    const active = activeModelMetadata();

    return Boolean(
        active &&
        (
            active.vision === true ||
            active.backend === 'vlm'
        )
    );
}


async function ensureModelMetadata() {
    if (!modelAliases.length) {
        await loadModelAliases();
    }

    return activeModelMetadata();
}


async function ensureVisionSupport() {
    const active = await ensureModelMetadata();

    return Boolean(
        active &&
        (
            active.vision === true ||
            active.backend === 'vlm'
        )
    );
}


function setModelStatus(message) {
    document.getElementById('statusText').textContent = message;
    modelSwitchStatus.textContent = message;
}


function renderStatus(data) {
    modelTitle.textContent = modelAliasFor(data);

    document.getElementById(
        'statusText'
    ).textContent =
        data.online
            ? 'Online'
            : 'Offline';

    document.getElementById(
        'thinkingText'
    ).textContent =
        'Thinking ' +
        (data.thinking ? 'ON' : 'OFF');

    document.getElementById(
        'onlineDot'
    ).style.background =
        data.online
            ? 'var(--green)'
            : 'var(--red)';
}



function updateHeaderClock() {
    const clock = document.getElementById('headerClock');

    if (!clock) {
        return;
    }

    const now = new Date();

    const pad = (value) => String(value).padStart(2, '0');

    const date =
        pad(now.getDate()) + '.' +
        pad(now.getMonth() + 1) + '.' +
        now.getFullYear();

    const time =
        pad(now.getHours()) + ':' +
        pad(now.getMinutes()) + ':' +
        pad(now.getSeconds());

    clock.textContent = date + ' · ' + time;
}

let headerClockTimer = null;

function startHeaderClock() {
    updateHeaderClock();

    if (headerClockTimer !== null) {
        clearInterval(headerClockTimer);
    }

    headerClockTimer = setInterval(updateHeaderClock, 1000);
}

if (document.readyState === 'loading') {
    document.addEventListener(
        'DOMContentLoaded',
        startHeaderClock,
        { once: true }
    );
} else {
    startHeaderClock();
}


async function fetchStatus() {
    const response = await fetch('/api/mlx/status');

    if (!response.ok) {
        throw new Error('Status HTTP ' + response.status);
    }

    return response.json();
}


async function fetchSystem() {
    const response = await fetch('/api/mlx/system');

    if (!response.ok) {
        throw new Error('System HTTP ' + response.status);
    }

    return response.json();
}


async function loadStatus() {
    if (isSwitching()) return;

    try {
        const data = await fetchStatus();

        renderStatus(data);

        return data;

    } catch {
        document.getElementById(
            'statusText'
        ).textContent =
            rut('status_unavailable', 'Unavailable');

        document.getElementById(
            'onlineDot'
        ).style.background =
            'var(--red)';
    }
}


function errorMessage(data, fallback) {
    if (typeof data?.detail === 'string') {
        return data.detail;
    }

    return fallback;
}


function closeModelPopover() {
    modelPopover.hidden = true;
    modelTitle.setAttribute('aria-expanded', 'false');
}


function closeRuntimePopover() {
    runtimePopover.hidden = true;
    runtimeInfoButton.setAttribute('aria-expanded', 'false');

    if (runtimeInfoInterval) {
        clearInterval(runtimeInfoInterval);
        runtimeInfoInterval = null;
    }
}


function formatRuntimeNumber(value, digits = 1) {
    return Number(value).toLocaleString('de-DE', {
        maximumFractionDigits: digits
    });
}


function formatUptime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainingSeconds = total % 60;
    const parts = [];

    if (hours) parts.push(hours + 'h');
    if (minutes || hours) parts.push(minutes + 'm');
    parts.push(remainingSeconds + 's');

    return parts.join(' ');
}


function appendRuntimeRow(section, label, value) {
    const row = document.createElement('div');
    const strong = document.createElement('strong');

    row.className = 'runtime-info-row';
    strong.textContent = label + ' ';
    row.appendChild(strong);
    row.append(value);
    section.appendChild(row);
}


function appendRuntimeHeading(section, text) {
    const heading = document.createElement('div');

    heading.className = 'runtime-info-heading';
    heading.textContent = text;
    section.appendChild(heading);
}


function renderRuntimeInfo(status, systemData) {
    runtimeInfoContent.innerHTML = '';

    const runtime = document.createElement('div');

    runtime.className = 'runtime-info-section';
    appendRuntimeHeading(runtime, 'Runtime');

    const alias = document.createElement('div');

    alias.className = 'runtime-info-model';
    alias.textContent = modelAliasFor(status);
    runtime.appendChild(alias);

    const repo = document.createElement('div');

    repo.className = 'runtime-info-repo';
    repo.textContent = status.model || rut('no_model', 'No model');
    runtime.appendChild(repo);

    appendRuntimeRow(
        runtime,
        'Status',
        status.online ? '● Online' : '● Offline'
    );
    appendRuntimeRow(
        runtime,
        'Thinking',
        status.thinking ? 'ON' : 'OFF'
    );

    const thinkingButton = document.createElement('button');

    thinkingButton.type = 'button';
    thinkingButton.className = 'message-action-btn';
    thinkingButton.textContent = status.thinking
        ? 'Deaktivieren'
        : 'Aktivieren';
    thinkingButton.disabled = isSwitching();
    thinkingButton.addEventListener('click', () => {
        toggleThinking(!status.thinking);
    });
    runtime.appendChild(thinkingButton);

    const mlx = systemData?.mlx;

    if (mlx) {
        appendRuntimeRow(
            runtime,
            'RAM',
            formatRuntimeNumber(mlx.memory_mb / 1024) + ' GB'
        );
        appendRuntimeRow(runtime, 'PID', String(mlx.pid));
        appendRuntimeRow(runtime, 'Port', String(mlx.port));
        appendRuntimeRow(
            runtime,
            'Uptime',
            formatUptime(mlx.uptime_seconds)
        );
    } else {
        appendRuntimeRow(
            runtime,
            'System',
            rut('system_unavailable', 'System data unavailable')
        );
    }

    runtimeInfoContent.appendChild(runtime);

    const metricsSection = document.createElement('div');

    metricsSection.className = 'runtime-info-section';
    appendRuntimeHeading(metricsSection, rut('last_response', 'Last response'));

    const session = MLXChatSessions.currentSession();
    const message = [...(session?.messages || [])]
        .reverse()
        .find(item => item.role === 'assistant');
    const metrics = message?.metrics;

    if (!metrics || !Number.isFinite(metrics.total_ms)) {
        appendRuntimeRow(
            metricsSection,
            'Metriken',
            rut('no_metrics', 'No response metrics available yet')
        );

    } else {
        if (Number.isFinite(metrics.estimated_tokens)) {
            appendRuntimeRow(
                metricsSection,
                'Tokens',
                formatRuntimeNumber(metrics.estimated_tokens, 0)
            );
        }

        if (Number.isFinite(metrics.tokens_per_second)) {
            appendRuntimeRow(
                metricsSection,
                'Tokens/s',
                formatRuntimeNumber(metrics.tokens_per_second)
            );
        }

        if (Number.isFinite(metrics.first_content_ms)) {
            appendRuntimeRow(
                metricsSection,
                'First token',
                formatRuntimeNumber(
                    metrics.first_content_ms / 1000
                ) + ' s'
            );
        }

        appendRuntimeRow(
            metricsSection,
            'Gesamt',
            formatRuntimeNumber(metrics.total_ms / 1000) + ' s'
        );

        if (Number.isFinite(metrics.thinking_ms)) {
            appendRuntimeRow(
                metricsSection,
                'Thinking',
                formatRuntimeNumber(
                    metrics.thinking_ms / 1000
                ) + ' s'
            );
        }
    }

    runtimeInfoContent.appendChild(metricsSection);
}


async function refreshRuntimeInfo() {
    if (runtimePopover.hidden || runtimeInfoRefreshing) return;

    runtimeInfoRefreshing = true;

    try {
        if (!modelAliases.length) {
            await loadModelAliases();
        }

        const status = await fetchStatus();
        let systemData = null;

        try {
            systemData = await fetchSystem();
        } catch {}

        renderRuntimeInfo(status, systemData);

    } catch (error) {
        runtimeInfoContent.textContent = rut(
            'info_unavailable',
            'Runtime information unavailable: {message}',
            { message: error.message }
        );

    } finally {
        runtimeInfoRefreshing = false;
    }
}


function openRuntimePopover() {
    closeModelPopover();
    runtimePopover.hidden = false;
    runtimeInfoButton.setAttribute('aria-expanded', 'true');
    runtimeInfoContent.textContent = rut('runtime_loading', 'Loading runtime…');

    refreshRuntimeInfo();

    runtimeInfoInterval = setInterval(
        refreshRuntimeInfo,
        3000
    );
}


function renderModelList() {
    modelList.innerHTML = '';

    for (const model of modelAliases) {
        const option = document.createElement('button');

        option.type = 'button';
        option.className = 'model-option';
        option.disabled = isSwitching() || model.active;

        const alias = document.createElement('div');

        alias.className = 'model-option-alias';
        alias.textContent = model.alias;

        if (model.active) {
            const active = document.createElement('span');

            active.className = 'model-option-active';
            active.textContent = rut('active_badge', '● active');
            alias.appendChild(active);
        }

        const repo = document.createElement('div');

        repo.className = 'model-option-repo';
        repo.textContent = model.repo;

        option.appendChild(alias);
        option.appendChild(repo);

        option.addEventListener('click', () => {
            switchModel(model.alias);
        });

        modelList.appendChild(option);
    }
}


async function loadModelAliases() {
    const response = await fetch('/api/mlx/aliases');
    let data;

    try {
        data = await response.json();
    } catch {
        data = null;
    }

    if (!response.ok || !Array.isArray(data?.models)) {
        throw new Error(
            errorMessage(
                data,
                rut('aliases_failed', 'Could not load model aliases')
            )
        );
    }

    modelAliases = data.models;
    renderModelList();

    return modelAliases;
}


async function openModelPopover() {
    if (isSwitching()) return;

    closeRuntimePopover();
    modelPopover.hidden = false;
    modelTitle.setAttribute('aria-expanded', 'true');
    modelSwitchStatus.textContent = rut('models_loading', 'Loading models…');
    modelList.innerHTML = '';

    try {
        await loadModelAliases();
        const status = await fetchStatus();

        modelSwitchStatus.textContent =
            rut('active_prefix', 'Active:') + ' ' + modelAliasFor(status);
        modelTitle.textContent = modelAliasFor(status);

    } catch (error) {
        modelSwitchStatus.textContent =
            rut(
                'error_with_message',
                'Error: {message}',
                { message: error.message }
            );
    }
}


function wait(milliseconds) {
    return new Promise(resolve => {
        setTimeout(resolve, milliseconds);
    });
}


async function waitForModel(alias) {
    const timeoutAt = Date.now() + 120000;

    while (Date.now() < timeoutAt) {
        try {
            const status = await fetchStatus();
            const activeAlias = modelAliasFor(status);

            if (status.online && activeAlias === alias) {
                return status;
            }

            setModelStatus(
                status.online
                    ? 'Warte auf ' + alias + '…'
                    : rut('mlx_restarting', 'MLX is restarting…')
            );

        } catch {
            setModelStatus(rut('mlx_restarting', 'MLX is restarting…'));
        }

        await wait(1000);
    }

    throw new Error(
        rut(
            'mlx_alias_not_ready',
            'MLX did not become ready with {alias} in time',
            { alias }
        )
    );
}


async function waitForThinking(enabled) {
    const timeoutAt = Date.now() + 120000;

    while (Date.now() < timeoutAt) {
        try {
            const status = await fetchStatus();

            if (status.online && status.thinking === enabled) {
                return status;
            }
        } catch {}

        setModelStatus(rut('mlx_restarting', 'MLX is restarting…'));
        await wait(1000);
    }

    throw new Error(rut('thinking_timeout', 'Thinking switch did not become ready in time'));
}


async function toggleThinking(enabled) {
    if (isSwitching()) return;

    if (isGenerating()) {
        runtimeInfoContent.textContent =
            rut('thinking_after_response', 'Thinking can only be switched after the current response');
        return;
    }

    switchingThinking = true;
    updateSendButton();
    runtimeInfoContent.textContent = enabled
        ? rut('thinking_on', 'Enabling Thinking…')
        : rut('thinking_off', 'Disabling Thinking…');
    setModelStatus(
        enabled
            ? rut('thinking_on', 'Enabling Thinking…')
            : rut('thinking_off', 'Disabling Thinking…')
    );

    try {
        const response = await fetch(
            '/api/mlx/thinking/' + (enabled ? 'on' : 'off'),
            { method: 'POST' }
        );
        let data;

        try { data = await response.json(); } catch { data = null; }

        if (!response.ok) {
            throw new Error(
                errorMessage(data, rut('thinking_failed', 'Thinking switch failed'))
            );
        }

        setModelStatus(rut('mlx_restarting', 'MLX is restarting…'));
        const status = await waitForThinking(enabled);

        renderStatus(status);
        setModelStatus(
            'Thinking ' + (enabled ? 'ON' : 'OFF') + rut('ready_suffix', ' · ready')
        );

    } catch (error) {
        runtimeInfoContent.textContent =
            rut(
                'error_with_message',
                'Error: {message}',
                { message: error.message }
            );
        setModelStatus(rut(
                'error_with_message',
                'Error: {message}',
                { message: error.message }
            ));

    } finally {
        switchingThinking = false;
        updateSendButton();

        if (!runtimePopover.hidden) {
            refreshRuntimeInfo();
        }
    }
}


async function switchModel(alias) {
    if (isSwitching()) return;

    if (isGenerating()) {
        setModelStatus(
            rut('switch_after_response', 'Model switch available after the current response')
        );
        return;
    }

    try {
        if (!modelAliases.length) {
            await loadModelAliases();
        }

        if (!modelAliases.some(model => model.alias === alias)) {
            throw new Error(rut(
            'unknown_alias_with_name',
            'Unknown model alias: {alias}',
            { alias }
        ));
        }

        switchingModel = true;
        closeModelPopover();
        closeRuntimePopover();
        updateSendButton();
        setModelStatus('Wechsle zu ' + alias + '…');

        const response = await fetch(
            '/api/mlx/model/' + encodeURIComponent(alias),
            { method: 'POST' }
        );

        let data;

        try {
            data = await response.json();
        } catch {
            data = null;
        }

        if (!response.ok) {
            throw new Error(
                errorMessage(
                    data,
                    rut('switch_failed', 'Model switch failed')
                )
            );
        }

        setModelStatus(rut('mlx_restarting', 'MLX is restarting…'));

        const status = await waitForModel(alias);

        await loadModelAliases();
        renderStatus(status);
        setModelStatus(rut(
            'ready',
            '{alias} ready',
            { alias }
        ));

    } catch (error) {
        setModelStatus(rut(
                'error_with_message',
                'Error: {message}',
                { message: error.message }
            ));

    } finally {
        switchingModel = false;
        updateSendButton();
    }
}


function initModelSwitcher() {
    modelTitle.addEventListener('click', () => {
        if (modelPopover.hidden) {
            openModelPopover();
        } else {
            closeModelPopover();
        }
    });

    modelTitle.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            modelTitle.click();
        }
    });

    document.addEventListener('click', event => {
        if (
            !modelPopover.hidden &&
            !modelPopover.contains(event.target) &&
            event.target !== modelTitle
        ) {
            closeModelPopover();
        }
    });

    loadModelAliases()
        .then(loadStatus)
        .catch(() => {});
}


function initRuntimeInfoPopover() {
    runtimeInfoButton.addEventListener('click', () => {
        if (runtimePopover.hidden) {
            openRuntimePopover();
        } else {
            closeRuntimePopover();
        }
    });

    document.addEventListener('click', event => {
        if (
            !runtimePopover.hidden &&
            !runtimePopover.contains(event.target) &&
            event.target !== runtimeInfoButton
        ) {
            closeRuntimePopover();
        }
    });
}


function createSessionSettings() {
    const preset = SYSTEM_PROMPT_PRESETS[
        globalSettings.default_preset
    ] || SYSTEM_PROMPT_PRESETS.general;

    return {
        system_prompt:
            preset.prompt,
        preset_id: globalSettings.default_preset,
        temperature: globalSettings.default_temperature,
        max_tokens: globalSettings.default_max_tokens
    };
}


function normalizeTemperature(value) {
    const temperature = Number(value);

    return Number.isFinite(temperature) &&
        temperature >= 0 &&
        temperature <= 2
        ? temperature
        : DEFAULT_TEMPERATURE;
}


function normalizeMaxTokens(value) {
    const maxTokens = Number(value);

    return Number.isInteger(maxTokens) &&
        maxTokens >= 1 &&
        maxTokens <= MAX_TOKENS_LIMIT
        ? maxTokens
        : DEFAULT_MAX_TOKENS;
}


function normalizeGlobalSettings(settings = {}) {
    const preset = SYSTEM_PROMPT_PRESETS[settings.default_preset]
        ? settings.default_preset
        : 'general';

    return {
        metrics_mode:
            ['off', 'compact', 'full'].includes(settings.metrics_mode)
                ? settings.metrics_mode
                : (
                    settings.show_metrics === false
                        ? 'off'
                        : 'compact'
                ),
        auto_scroll: settings.auto_scroll !== false,
        show_runtime_thinking:
            settings.show_runtime_thinking !== false,
        auto_compact: settings.auto_compact !== false,
        default_preset: preset,
        default_temperature:
            normalizeTemperature(settings.default_temperature),
        default_max_tokens:
            normalizeMaxTokens(settings.default_max_tokens),
        thinking_preferred:
            settings.thinking_preferred === true
    };
}


function applyGlobalSettings() {
    showMetrics.value = globalSettings.metrics_mode;
    autoScroll.checked = globalSettings.auto_scroll;
    showRuntimeThinking.checked = globalSettings.show_runtime_thinking;
    autoCompact.checked = globalSettings.auto_compact;
    defaultPreset.value = globalSettings.default_preset;
    defaultTemperature.value = globalSettings.default_temperature;
    defaultMaxTokens.value = globalSettings.default_max_tokens;
    thinkingPreferred.checked = globalSettings.thinking_preferred;
    runtimeInfoButton.hidden = !globalSettings.show_runtime_thinking;
    document.getElementById('thinkingText').hidden =
        !globalSettings.show_runtime_thinking;

    if (!globalSettings.show_runtime_thinking) {
        closeRuntimePopover();
    }
}


function handleGlobalSettingsInput(event) {
    const target = event.target;

    if (target === showMetrics) {
        globalSettings.metrics_mode =
            ['off', 'compact', 'full'].includes(target.value)
                ? target.value
                : 'compact';
    } else if (target === autoScroll) {
        globalSettings.auto_scroll = target.checked;
        autoScrollEnabled =
            target.checked && isNearBottom();
        if (autoScrollEnabled) {
            hasNewContentBelow = false;
        }
        scheduleButtonUpdate();
    } else if (target === showRuntimeThinking) {
        globalSettings.show_runtime_thinking = target.checked;
    } else if (target === autoCompact) {
        globalSettings.auto_compact = target.checked;
    } else if (target === defaultPreset) {
        globalSettings.default_preset =
            SYSTEM_PROMPT_PRESETS[target.value]
                ? target.value
                : 'general';
    } else if (target === defaultTemperature) {
        globalSettings.default_temperature =
            normalizeTemperature(target.value);
    } else if (target === defaultMaxTokens) {
        globalSettings.default_max_tokens =
            normalizeMaxTokens(target.value);
    } else if (target === thinkingPreferred) {
        globalSettings.thinking_preferred = target.checked;
    } else {
        return;
    }

    globalSettings = normalizeGlobalSettings(globalSettings);
    localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(globalSettings));
    applyGlobalSettings();
    MLXChatRendering.renderMessages();
}


function showGenerationMetrics() {
    return globalSettings.metrics_mode !== 'off';
}


function generationMetricsMode() {
    return globalSettings.metrics_mode || 'compact';
}


function showRuntimeThinkingInfo() {
    return globalSettings.show_runtime_thinking;
}


function isAutoCompactEnabled() {
    return globalSettings.auto_compact;
}


function sessionSettings(session) {
    let changed = false;

    if (
        session?.settings &&
        typeof session.settings.system_prompt === 'string' &&
        typeof session.settings.preset_id === 'string'
    ) {
        const normalizedTemperature =
            normalizeTemperature(
                session.settings.temperature
            );

        const normalizedMaxTokens =
            normalizeMaxTokens(
                session.settings.max_tokens
            );

        if (
            session.settings.temperature !==
            normalizedTemperature
        ) {
            session.settings.temperature =
                normalizedTemperature;
            changed = true;
        }

        if (
            session.settings.max_tokens !==
            normalizedMaxTokens
        ) {
            session.settings.max_tokens =
                normalizedMaxTokens;
            changed = true;
        }

        if (changed) {
            session.updated = Date.now();
            MLXChatSessions.saveSessions();
        }

        return session.settings;
    }

    const preset = Object.entries(
        SYSTEM_PROMPT_PRESETS
    ).find(([, value]) =>
        value.prompt === legacySystemPrompt
    );

    session.settings = {
        system_prompt: legacySystemPrompt,
        preset_id: preset ? preset[0] : 'custom',
        temperature: DEFAULT_TEMPERATURE,
        max_tokens: DEFAULT_MAX_TOKENS
    };

    session.updated = Date.now();

    MLXChatSessions.saveSessions();

    return session.settings;
}


function loadSessionSettings() {
    const session = MLXChatSessions.currentSession();

    if (!session) return;

    const settings = sessionSettings(session);

    systemPrompt.value = settings.system_prompt;
    systemPromptPreset.value =
        SYSTEM_PROMPT_PRESETS[settings.preset_id]
            ? settings.preset_id
            : 'custom';
    temperature.value = settings.temperature;
    maxTokens.value = settings.max_tokens;
}


function handlePresetChange() {
    const session = MLXChatSessions.currentSession();
    const preset = SYSTEM_PROMPT_PRESETS[
        systemPromptPreset.value
    ];

    if (!session || !preset) return;

    const settings = sessionSettings(session);

    settings.system_prompt = preset.prompt;
    settings.preset_id = systemPromptPreset.value;
    settings.temperature = preset.temperature;
    settings.max_tokens = preset.max_tokens;

    session.updated = Date.now();
    systemPrompt.value = preset.prompt;
    temperature.value = preset.temperature;
    maxTokens.value = preset.max_tokens;

    MLXChatSessions.saveSessions();
}


function handleSystemPromptInput(event) {
    const session = MLXChatSessions.currentSession();

    if (!session) return;

    const settings = sessionSettings(session);

    if (event.target === temperature) {
        settings.temperature = normalizeTemperature(
            temperature.value
        );
        temperature.value = settings.temperature;

    } else if (event.target === maxTokens) {
        settings.max_tokens = normalizeMaxTokens(
            maxTokens.value
        );
        maxTokens.value = settings.max_tokens;

    } else if (event.target === systemPrompt) {
        settings.system_prompt = systemPrompt.value;
        settings.preset_id = 'custom';
        systemPromptPreset.value = 'custom';

    } else {
        return;
    }

    session.updated = Date.now();

    MLXChatSessions.saveSessions();
}


function getSessionSystemPrompt() {
    const session = MLXChatSessions.currentSession();

    if (!session) return '';

    return sessionSettings(session).system_prompt;
}


function getSessionGenerationSettings() {
    const session = MLXChatSessions.currentSession();

    if (!session) {
        return {
            temperature: DEFAULT_TEMPERATURE,
            max_tokens: DEFAULT_MAX_TOKENS
        };
    }

    const settings = sessionSettings(session);

    return {
        temperature: settings.temperature,
        max_tokens: settings.max_tokens
    };
}


function loadSettings() {
    try {
        globalSettings = normalizeGlobalSettings(
            JSON.parse(localStorage.getItem(UI_SETTINGS_KEY)) || {}
        );
    } catch {
        globalSettings = normalizeGlobalSettings();
    }

    applyGlobalSettings();

    try {
        const settings =
            JSON.parse(
                localStorage.getItem(
                    SETTINGS_KEY
                )
            );

        if (
            settings &&
            settings.systemPrompt !== undefined
        ) {
            legacySystemPrompt =
                settings.systemPrompt;
        }

    } catch {}

    loadSessionSettings();
}


function saveSettings() {
    localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({
            temperature:
                DEFAULT_TEMPERATURE,

            maxTokens:
                DEFAULT_MAX_TOKENS,

            systemPrompt: legacySystemPrompt
        })
    );
}


    window.MLXChatRuntime = {
        configure: configure,
        updateContext: updateContext,
        scrollBottom: scrollBottom,
        beginUserMessage: beginUserMessage,
        resetScrollForChat: resetScrollForChat,
        beforeMessagesRender: beforeMessagesRender,
        afterMessagesRender: afterMessagesRender,
        contentUpdated: contentUpdated,
        isNearBottom: isNearBottom,
        autoResize: autoResize,
        updateSendButton: updateSendButton,
        isSwitching: isSwitching,
        setExternalRuntimeBusy: setExternalRuntimeBusy,
        refreshModelState: refreshModelState,
        initModelSwitcher: initModelSwitcher,
        initRuntimeInfoPopover: initRuntimeInfoPopover,
        switchModel: switchModel,
        loadStatus: loadStatus,
        loadSettings: loadSettings,
        saveSettings: saveSettings,
        createSessionSettings: createSessionSettings,
        loadSessionSettings: loadSessionSettings,
        handlePresetChange: handlePresetChange,
        handleSystemPromptInput: handleSystemPromptInput,
        getSessionSystemPrompt: getSessionSystemPrompt,
        getSessionGenerationSettings:
            getSessionGenerationSettings,
        handleGlobalSettingsInput: handleGlobalSettingsInput,
        showGenerationMetrics: showGenerationMetrics,
        generationMetricsMode: generationMetricsMode,
        showRuntimeThinkingInfo: showRuntimeThinkingInfo,
        isAutoCompactEnabled: isAutoCompactEnabled,
        supportsVision: supportsVision,
        ensureModelMetadata: ensureModelMetadata,
        ensureVisionSupport: ensureVisionSupport,
        activeModelMetadata: activeModelMetadata
    };

    initScrollBehavior();
})();
