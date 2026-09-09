/* Image settings own their registry; never populate from the LLM aliases. */
(() => {
    const status = document.getElementById('imageModelsStatus');
    const list = document.getElementById('imageModelList');
    const role = document.getElementById('imageRole');
    if (!status || !list || !role) return;

    function node(tag, text, className) {
        const element = document.createElement(tag);
        if (text) element.textContent = text;
        if (className) element.className = className;
        return element;
    }
    async function api(path, method = 'GET', body) {
        const response = await fetch('/api/image' + path, {
            method, headers: { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Ungültige Image-Konfiguration');
        return data;
    }
    function field(parent, label, value, type = 'text') {
        const wrapper = node('label', label, 'image-model-field');
        const input = node('input'); input.type = type;
        if (type === 'checkbox') input.checked = Boolean(value);
        else input.value = value ?? '';
        wrapper.append(input); parent.append(wrapper); return input;
    }
    async function action(button, operation) {
        button.disabled = true;
        try { await operation(); await load(); }
        catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    }
    function renderModel(model, data) {
        const card = node('details', null, 'image-model-card');
        const summary = node('summary', model.name + (data.effective_model === model.id ? ' · aktiv' : ''));
        card.append(summary);
        card.append(node('p', [model.provider, model.model_family, model.quantization].join(' · ')));
        card.append(node('p', model.availability_note, 'settings-hint'));
        const legacy = model.id === 'FLUX.1-schnell';
        const form = node('div', null, 'image-model-fields');
        const enabled = field(form, 'Modell aktiviert', model.enabled, 'checkbox');
        const repo = field(form, 'Repository', model.repository);
        const local = field(form, 'Lokaler Modellpfad (optional)', model.local_path);
        const steps = field(form, 'Standard-Steps', model.default_steps, 'number');
        steps.min = 1; steps.max = model.provider === 'diffusionkit' ? 8 : 50;
        const guidance = field(form, 'Standard-Guidance', model.default_guidance, 'number');
        guidance.min = 0; guidance.max = 10; guidance.step = 0.1;
        card.append(form);
        const loraList = node('div', null, 'image-lora-list');
        const loraRows = [];
        function addLora(lora = {}) {
            const row = node('fieldset', null, 'image-lora-row');
            row.append(node('legend', 'LoRA ' + (loraRows.length + 1)));
            const use = field(row, 'Aktiv', lora.enabled ?? true, 'checkbox');
            const source = field(row, 'Pfad oder org/repo[:datei.safetensors]', lora.path || lora.repository);
            const scale = field(row, 'Gewichtung', lora.scale ?? 1, 'number');
            scale.min = -2; scale.max = 2; scale.step = 0.05;
            const trigger = field(row, 'Triggerwort (Hinweis)', lora.trigger_word);
            const remove = node('button', 'Entfernen', 'message-action-btn'); remove.type = 'button';
            const entry = { row, use, source, scale, trigger };
            remove.onclick = () => { row.remove(); loraRows.splice(loraRows.indexOf(entry), 1); };
            row.append(remove); loraList.append(row); loraRows.push(entry);
        }
        if (model.capabilities.includes('lora')) {
            for (const lora of model.loras) addLora(lora);
            const add = node('button', 'LoRA hinzufügen', 'message-action-btn'); add.type = 'button';
            add.onclick = () => { if (loraRows.length < 8) addLora(); };
            card.append(loraList, add);
        } else card.append(node('p', 'Dieser Provider unterstützt keine LoRAs.', 'settings-hint'));
        const controls = node('div', null, 'batch-chat-controls');
        if (!legacy) {
            const save = node('button', 'Konfiguration speichern', 'message-action-btn'); save.type = 'button';
            save.onclick = () => action(save, () => api('/models/' + encodeURIComponent(model.id), 'PUT', {
                enabled: enabled.checked, repository: repo.value.trim() || null,
                local_path: local.value.trim() || null, default_steps: Number(steps.value),
                default_guidance: Number(guidance.value),
                loras: loraRows.map(row => {
                    const value = row.source.value.trim();
                    return { [value.startsWith('/') || value.startsWith('~/') ? 'path' : 'repository']: value,
                        enabled: row.use.checked, scale: Number(row.scale.value), trigger_word: row.trigger.value };
                })
            }));
            controls.append(save);
        } else form.querySelectorAll('input').forEach(input => { input.disabled = true; });
        const activate = node('button', data.default_model === model.id ? 'Standardmodell' : 'Als Standard verwenden', 'message-action-btn');
        activate.type = 'button'; activate.disabled = !model.enabled || !model.available;
        activate.onclick = () => action(activate, async () => {
            await api('/models/' + encodeURIComponent(model.id) + '/activate', 'POST', {});
            await api('/role', 'PUT', { model: 'auto' });
        });
        controls.append(activate); card.append(controls); return card;
    }
    async function load() {
        status.textContent = 'Bildmodelle werden geladen …';
        try {
            const data = await api('/models');
            role.replaceChildren();
            const auto = node('option', 'Automatisch (' + data.default_model + ')'); auto.value = 'auto'; role.append(auto);
            for (const model of data.models) {
                const option = node('option', model.name + (!model.enabled ? ' · deaktiviert' : !model.available ? ' · Gewichte fehlen' : ''));
                option.value = model.id; option.disabled = !model.enabled || !model.available; role.append(option);
            }
            if (data.role !== 'auto' && !data.models.some(model => model.id === data.role)) {
                const invalid = node('option', data.role + ' · nicht registriert'); invalid.value = data.role; invalid.disabled = true; role.append(invalid);
            }
            role.value = data.role;
            list.replaceChildren(...data.models.map(model => renderModel(model, data)));
            status.textContent = 'Aktiv: ' + data.effective_model + (data.running_model ? ' · Auftrag läuft: ' + data.running_model : ' · aktuell kein Bildmodell geladen');
        } catch (error) { status.textContent = 'Bildmodelle: ' + error.message; }
    }
    role.onchange = () => action(role, () => api('/role', 'PUT', { model: role.value }));
    window.MLXImageSettings = { load };
})();
