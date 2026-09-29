(function () {
    'use strict';

    if (window.__mlxNobbyAutomationsUI) return;
    window.__mlxNobbyAutomationsUI = true;

    const TERMINAL = new Set(['completed', 'failed', 'needs_approval', 'cancelled']);
    const FALLBACK = {
        new_automation: 'New automation',
        model_scout_template: 'Weekly Model Scout',
        empty: 'No automations yet.',
        name: 'Name',
        type: 'Type',
        type_agent: 'Agent task',
        type_model_scout: 'Model Scout',
        prompt: 'Task / prompt',
        mode: 'Agent mode',
        mode_diagnostic: 'Diagnostic',
        mode_research: 'Research',
        mode_coding: 'Coding',
        workspace: 'Workspace ID (optional)',
        schedule: 'Schedule',
        schedule_manual: 'Manual only',
        schedule_hourly: 'Hourly',
        schedule_daily: 'Daily',
        schedule_weekly: 'Weekly',
        time: 'Time',
        minute: 'Minute',
        weekday: 'Weekday',
        enabled: 'Enabled',
        save: 'Save',
        cancel: 'Cancel',
        edit: 'Edit',
        delete: 'Delete',
        run_now: 'Run now',
        pause: 'Pause',
        enable: 'Enable',
        active: 'Active',
        paused: 'Paused',
        next_run: 'Next run',
        last_run: 'Last run',
        never: 'Never',
        history: 'Run history',
        history_empty: 'No runs yet.',
        running: 'Running',
        status_queued: 'Queued',
        status_running: 'Running',
        status_completed: 'Completed',
        status_failed: 'Failed',
        status_needs_approval: 'Needs approval',
        status_cancelled: 'Cancelled',
        confirm_delete: 'Delete automation “{name}”?',
        save_failed: 'Could not save automation: {error}',
        action_failed: 'Action failed: {error}',
        template_name: 'Weekly Model Scout',
        template_hint: 'Searches for new MLX candidates only. Nothing is downloaded, benchmarked or activated automatically.',
        agent_hint: 'Scheduled agent tasks use the normal permission and approval system. Actions requiring approval are never auto-approved.',
        scout_hint: 'Model Scout discovery is read-only and does not download or activate models.',
        result_candidates: '{count} candidates found',
        timezone: 'Timezone',
        weekday_0: 'Monday',
        weekday_1: 'Tuesday',
        weekday_2: 'Wednesday',
        weekday_3: 'Thursday',
        weekday_4: 'Friday',
        weekday_5: 'Saturday',
        weekday_6: 'Sunday'
    };

    let copy = { ...FALLBACK };
    let pane = null;
    let form = null;
    let list = null;
    let historyList = null;
    let editingId = null;
    let automations = [];
    let runs = [];
    let pollTimer = null;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function timezoneName() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        } catch (_) {
            return 'UTC';
        }
    }

    function t(key, vars = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => {
            value = String(value).replaceAll('{' + name + '}', String(replacement ?? ''));
        });
        return value;
    }

    async function loadCopy() {
        copy = { ...FALLBACK };
        try {
            const response = await fetch('/i18n/automations.' + locale() + '.json', { cache: 'no-store' });
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_) {}
    }

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.error || ('HTTP ' + response.status));
        return data;
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function labelledField(key, input) {
        const wrap = element('label', 'automation-field');
        const label = element('span', 'automation-field-label');
        label.dataset.automationLabel = key;
        label.textContent = t(key);
        wrap.append(label, input);
        return wrap;
    }

    function createSelect(name, values) {
        const select = document.createElement('select');
        select.name = name;
        values.forEach(([value, key]) => {
            const option = document.createElement('option');
            option.value = value;
            option.dataset.automationOption = key;
            option.textContent = t(key);
            select.appendChild(option);
        });
        return select;
    }

    function createPane() {
        if (pane?.isConnected) return pane;
        const settings = document.getElementById('settings');
        if (!settings) return null;
        pane = settings.querySelector('[data-settings-pane="automations"]');
        if (pane) return pane;

        pane = element('section', 'settings-pane automations-settings-pane');
        pane.dataset.settingsPane = 'automations';
        pane.hidden = true;

        const toolbar = element('div', 'automations-toolbar');
        const addButton = element('button', 'automation-button primary');
        addButton.type = 'button';
        addButton.dataset.automationAction = 'new';
        addButton.addEventListener('click', () => openEditor());
        const templateButton = element('button', 'automation-button');
        templateButton.type = 'button';
        templateButton.dataset.automationAction = 'template';
        templateButton.addEventListener('click', openScoutTemplate);
        toolbar.append(addButton, templateButton);

        form = element('form', 'automation-editor');
        form.hidden = true;
        form.addEventListener('submit', saveEditor);

        const name = document.createElement('input');
        name.name = 'name';
        name.maxLength = 120;
        name.required = true;
        const kind = createSelect('kind', [
            ['agent', 'type_agent'],
            ['model_scout', 'type_model_scout']
        ]);
        kind.addEventListener('change', syncConditionalFields);
        const prompt = document.createElement('textarea');
        prompt.name = 'prompt';
        prompt.rows = 5;
        prompt.maxLength = 12000;
        const mode = createSelect('mode', [
            ['diagnostic', 'mode_diagnostic'],
            ['research', 'mode_research'],
            ['coding', 'mode_coding']
        ]);
        const workspace = document.createElement('input');
        workspace.name = 'workspace_id';
        workspace.maxLength = 160;
        const schedule = createSelect('schedule_type', [
            ['manual', 'schedule_manual'],
            ['hourly', 'schedule_hourly'],
            ['daily', 'schedule_daily'],
            ['weekly', 'schedule_weekly']
        ]);
        schedule.addEventListener('change', syncConditionalFields);
        const time = document.createElement('input');
        time.name = 'schedule_time';
        time.type = 'time';
        time.value = '09:00';
        const minute = document.createElement('input');
        minute.name = 'schedule_minute';
        minute.type = 'number';
        minute.min = '0';
        minute.max = '59';
        minute.value = '0';
        const weekday = createSelect('schedule_weekday', Array.from({ length: 7 }, (_, index) => [String(index), 'weekday_' + index]));
        const zone = document.createElement('input');
        zone.name = 'timezone';
        zone.readOnly = true;
        zone.value = timezoneName();
        const enabled = document.createElement('input');
        enabled.name = 'enabled';
        enabled.type = 'checkbox';
        enabled.checked = true;

        const grid = element('div', 'automation-editor-grid');
        const nameField = labelledField('name', name);
        nameField.classList.add('automation-field-wide');
        const kindField = labelledField('type', kind);
        kindField.dataset.automationKindField = 'true';
        const promptField = labelledField('prompt', prompt);
        promptField.classList.add('automation-field-wide');
        promptField.dataset.automationAgentOnly = 'true';
        const modeField = labelledField('mode', mode);
        modeField.dataset.automationAgentOnly = 'true';
        const workspaceField = labelledField('workspace', workspace);
        workspaceField.dataset.automationAgentOnly = 'true';
        const scheduleField = labelledField('schedule', schedule);
        const timeField = labelledField('time', time);
        timeField.dataset.automationTimeField = 'true';
        const minuteField = labelledField('minute', minute);
        minuteField.dataset.automationMinuteField = 'true';
        const weekdayField = labelledField('weekday', weekday);
        weekdayField.dataset.automationWeekdayField = 'true';
        const zoneField = labelledField('timezone', zone);
        zoneField.dataset.automationScheduledOnly = 'true';
        const enabledWrap = element('label', 'automation-check');
        const enabledLabel = element('span');
        enabledLabel.dataset.automationLabel = 'enabled';
        enabledLabel.textContent = t('enabled');
        enabledWrap.append(enabled, enabledLabel);
        grid.append(
            nameField, kindField, promptField, modeField, workspaceField,
            scheduleField, timeField, minuteField, weekdayField, zoneField,
            enabledWrap
        );

        const hint = element('p', 'automation-editor-hint');
        hint.dataset.automationHint = 'true';
        const actions = element('div', 'automation-editor-actions');
        const cancel = element('button', 'automation-button');
        cancel.type = 'button';
        cancel.dataset.automationAction = 'cancel';
        cancel.addEventListener('click', closeEditor);
        const save = element('button', 'automation-button primary');
        save.type = 'submit';
        save.dataset.automationAction = 'save';
        actions.append(cancel, save);
        form.append(grid, hint, actions);

        list = element('div', 'automations-list');
        const historyBox = element('section', 'automations-history');
        const historyHeader = element('h5');
        historyHeader.dataset.automationHistoryTitle = 'true';
        historyList = element('div', 'automations-history-list');
        historyBox.append(historyHeader, historyList);

        pane.append(toolbar, form, list, historyBox);
        settings.appendChild(pane);
        updateStaticLabels();
        syncConditionalFields();
        return pane;
    }

    function updateStaticLabels() {
        if (!pane) return;
        pane.querySelector('[data-automation-action="new"]')?.replaceChildren(document.createTextNode(t('new_automation')));
        pane.querySelector('[data-automation-action="template"]')?.replaceChildren(document.createTextNode(t('model_scout_template')));
        pane.querySelector('[data-automation-action="cancel"]')?.replaceChildren(document.createTextNode(t('cancel')));
        pane.querySelector('[data-automation-action="save"]')?.replaceChildren(document.createTextNode(t('save')));
        pane.querySelector('[data-automation-history-title]')?.replaceChildren(document.createTextNode(t('history')));
        pane.querySelectorAll('[data-automation-label]').forEach(node => {
            node.textContent = t(node.dataset.automationLabel);
        });
        pane.querySelectorAll('[data-automation-option]').forEach(node => {
            node.textContent = t(node.dataset.automationOption);
        });
        render();
    }

    function syncConditionalFields() {
        if (!form) return;
        const kind = form.elements.kind?.value || 'agent';
        const schedule = form.elements.schedule_type?.value || 'manual';
        form.querySelectorAll('[data-automation-agent-only]').forEach(node => {
            node.hidden = kind !== 'agent';
        });
        form.querySelectorAll('[data-automation-scheduled-only]').forEach(node => {
            node.hidden = schedule === 'manual';
        });
        const timeField = form.querySelector('[data-automation-time-field]');
        const minuteField = form.querySelector('[data-automation-minute-field]');
        const weekdayField = form.querySelector('[data-automation-weekday-field]');
        if (timeField) timeField.hidden = !['daily', 'weekly'].includes(schedule);
        if (minuteField) minuteField.hidden = schedule !== 'hourly';
        if (weekdayField) weekdayField.hidden = schedule !== 'weekly';
        const hint = form.querySelector('[data-automation-hint]');
        if (hint) hint.textContent = kind === 'model_scout' ? t('scout_hint') : t('agent_hint');
    }

    function openEditor(item = null) {
        createPane();
        editingId = item?.id || null;
        form.hidden = false;
        form.elements.name.value = item?.name || '';
        form.elements.kind.value = item?.kind || 'agent';
        form.elements.prompt.value = item?.prompt || '';
        form.elements.mode.value = item?.mode || 'diagnostic';
        form.elements.workspace_id.value = item?.workspace_id || '';
        form.elements.schedule_type.value = item?.schedule_type || 'manual';
        form.elements.schedule_time.value = item?.schedule_time || '09:00';
        form.elements.schedule_weekday.value = String(item?.schedule_weekday ?? 0);
        form.elements.schedule_minute.value = String(item?.schedule_minute ?? 0);
        form.elements.timezone.value = item?.timezone || timezoneName();
        form.elements.enabled.checked = item ? Boolean(item.enabled) : true;
        syncConditionalFields();
        form.elements.name.focus();
    }

    function openScoutTemplate() {
        openEditor({
            name: t('template_name'),
            kind: 'model_scout',
            mode: 'diagnostic',
            schedule_type: 'weekly',
            schedule_time: '10:00',
            schedule_weekday: 6,
            timezone: timezoneName(),
            enabled: true
        });
    }

    function closeEditor() {
        editingId = null;
        if (form) form.hidden = true;
    }

    function editorPayload() {
        const scheduleType = form.elements.schedule_type.value;
        return {
            name: form.elements.name.value.trim(),
            kind: form.elements.kind.value,
            prompt: form.elements.kind.value === 'agent' ? form.elements.prompt.value.trim() : '',
            mode: form.elements.mode.value,
            workspace_id: form.elements.workspace_id.value.trim() || null,
            enabled: form.elements.enabled.checked,
            schedule: {
                type: scheduleType,
                time: ['daily', 'weekly'].includes(scheduleType) ? form.elements.schedule_time.value : null,
                weekday: scheduleType === 'weekly' ? Number(form.elements.schedule_weekday.value) : null,
                minute: scheduleType === 'hourly' ? Number(form.elements.schedule_minute.value) : null,
                timezone: form.elements.timezone.value || timezoneName()
            }
        };
    }

    async function saveEditor(event) {
        event.preventDefault();
        const payload = editorPayload();
        const url = editingId
            ? '/api/mlx/automations/' + encodeURIComponent(editingId)
            : '/api/mlx/automations';
        try {
            await requestJson(url, {
                method: editingId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            closeEditor();
            await refresh();
        } catch (error) {
            window.alert?.(t('save_failed', { error: error?.message || error }));
        }
    }

    function formatDate(value) {
        if (!value) return t('never');
        const date = new Date(Number(value) * 1000);
        if (Number.isNaN(date.getTime())) return t('never');
        return new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', {
            dateStyle: 'short', timeStyle: 'short'
        }).format(date);
    }

    function statusLabel(status) {
        return t('status_' + String(status || '')) || status || '—';
    }

    function scheduleLabel(item) {
        if (item.schedule_type === 'hourly') return t('schedule_hourly') + ' · :' + String(item.schedule_minute ?? 0).padStart(2, '0');
        if (item.schedule_type === 'daily') return t('schedule_daily') + ' · ' + (item.schedule_time || '09:00');
        if (item.schedule_type === 'weekly') return t('schedule_weekly') + ' · ' + t('weekday_' + item.schedule_weekday) + ' · ' + (item.schedule_time || '09:00');
        return t('schedule_manual');
    }

    function button(label, handler, className = '') {
        const node = element('button', 'automation-button ' + className, label);
        node.type = 'button';
        node.addEventListener('click', handler);
        return node;
    }

    async function toggleAutomation(item) {
        try {
            await requestJson('/api/mlx/automations/' + encodeURIComponent(item.id), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !item.enabled })
            });
            await refresh();
        } catch (error) {
            window.alert?.(t('action_failed', { error: error?.message || error }));
        }
    }

    async function deleteAutomation(item) {
        const message = t('confirm_delete', { name: item.name });
        const approved = window.MLXConfirm
            ? await window.MLXConfirm({ title: t('delete'), message, confirmLabel: t('delete'), cancelLabel: t('cancel') })
            : window.confirm(message);
        if (!approved) return;
        try {
            await requestJson('/api/mlx/automations/' + encodeURIComponent(item.id), { method: 'DELETE' });
            await refresh();
        } catch (error) {
            window.alert?.(t('action_failed', { error: error?.message || error }));
        }
    }

    async function runNow(item) {
        try {
            const run = await requestJson('/api/mlx/automations/' + encodeURIComponent(item.id) + '/run', { method: 'POST' });
            await refresh();
            pollRun(run.id);
        } catch (error) {
            window.alert?.(t('action_failed', { error: error?.message || error }));
        }
    }

    function pollRun(runId) {
        clearTimeout(pollTimer);
        const check = async () => {
            try {
                const run = await requestJson('/api/mlx/automations/runs/' + encodeURIComponent(runId), { cache: 'no-store' });
                await refresh();
                if (!TERMINAL.has(run.status)) {
                    pollTimer = setTimeout(check, 1200);
                }
            } catch (_) {}
        };
        pollTimer = setTimeout(check, 700);
    }

    function renderAutomations() {
        if (!list) return;
        list.innerHTML = '';
        if (!automations.length) {
            list.appendChild(element('div', 'automation-empty', t('empty')));
            return;
        }
        automations.forEach(item => {
            const card = element('article', 'automation-card');
            const top = element('div', 'automation-card-top');
            const titleWrap = element('div');
            const title = element('strong', 'automation-card-title', item.name);
            const meta = element('div', 'automation-card-meta',
                (item.kind === 'model_scout' ? t('type_model_scout') : t('type_agent')) + ' · ' + scheduleLabel(item));
            titleWrap.append(title, meta);
            const badge = element('span', 'automation-status ' + (item.enabled ? 'active' : 'paused'), item.enabled ? t('active') : t('paused'));
            top.append(titleWrap, badge);

            const facts = element('div', 'automation-card-facts');
            facts.append(
                element('span', '', t('next_run') + ': ' + formatDate(item.next_run_at)),
                element('span', '', t('last_run') + ': ' + formatDate(item.last_run_at)),
                element('span', '', item.last_status ? statusLabel(item.last_status) : '')
            );

            const actions = element('div', 'automation-card-actions');
            actions.append(
                button(t('run_now'), () => runNow(item), 'primary'),
                button(t('edit'), () => openEditor(item)),
                button(item.enabled ? t('pause') : t('enable'), () => toggleAutomation(item)),
                button(t('delete'), () => deleteAutomation(item), 'danger')
            );
            card.append(top, facts, actions);
            list.appendChild(card);
        });
    }

    function resultSummary(run) {
        if (run.error) return run.error;
        const result = run.result;
        if (!result) return '';
        if (result.kind === 'model_scout') return t('result_candidates', { count: result.count || 0 });
        return String(result.answer || result.status || '').trim().slice(0, 420);
    }

    function renderHistory() {
        if (!historyList) return;
        historyList.innerHTML = '';
        if (!runs.length) {
            historyList.appendChild(element('div', 'automation-empty', t('history_empty')));
            return;
        }
        const byId = new Map(automations.map(item => [item.id, item]));
        runs.slice(0, 30).forEach(run => {
            const row = element('article', 'automation-run');
            const top = element('div', 'automation-run-top');
            const task = byId.get(run.automation_id);
            top.append(
                element('strong', '', task?.name || run.automation_id),
                element('span', 'automation-run-status status-' + run.status, statusLabel(run.status))
            );
            const when = element('div', 'automation-run-meta', formatDate(run.started_at || run.created_at));
            const summary = resultSummary(run);
            row.append(top, when);
            if (summary) row.appendChild(element('p', 'automation-run-result', summary));
            historyList.appendChild(row);
        });
    }

    function render() {
        renderAutomations();
        renderHistory();
    }

    async function refresh() {
        createPane();
        try {
            const [automationData, runData] = await Promise.all([
                requestJson('/api/mlx/automations', { cache: 'no-store' }),
                requestJson('/api/mlx/automations/runs?limit=50', { cache: 'no-store' })
            ]);
            automations = Array.isArray(automationData.automations) ? automationData.automations : [];
            runs = Array.isArray(runData.runs) ? runData.runs : [];
            render();
        } catch (error) {
            console.error('[automations] refresh failed:', error);
        }
    }

    function show({ updateHistory = true } = {}) {
        createPane();
        const settings = document.getElementById('settings');
        settings?.querySelectorAll('[data-settings-pane]').forEach(item => {
            item.hidden = item !== pane;
        });
        if (pane) pane.hidden = false;
        if (updateHistory && location.pathname !== '/settings/automations') {
            history.replaceState(null, '', '/settings/automations');
        }
        refresh();
    }

    async function initialize() {
        if (!createPane()) return false;
        await loadCopy();
        updateStaticLabels();
        return true;
    }

    window.MLXAutomationsUI = {
        show,
        refresh,
        openEditor,
        openScoutTemplate,
        timezoneName,
        __test: { scheduleLabel, statusLabel, resultSummary }
    };

    document.addEventListener('mlx-language-changed', () => {
        loadCopy().then(updateStaticLabels);
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
