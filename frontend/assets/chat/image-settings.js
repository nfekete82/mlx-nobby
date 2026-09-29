function imageT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(
        key,
        fallback
    ) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${name}}`,
            String(replacement ?? '')
        );
    }

    return value;
}

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
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : imageT('image_settings.invalid_config', 'Invalid image configuration'));
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
        const summary = node('summary', model.name + (data.effective_model === model.id ? imageT('image_settings.active_suffix', ' · active') : ''));
        card.append(summary);
        card.append(node('p', [model.provider, model.model_family, model.quantization].join(' · ')));
        card.append(node('p', model.availability_note, 'settings-hint'));
        const legacy = model.id === 'FLUX.1-schnell';
        const form = node('div', null, 'image-model-fields');
        const enabled = field(form, imageT('image_settings.model_enabled', 'Model enabled'), model.enabled, 'checkbox');
        const repo = field(form, imageT('image_settings.repository', 'Repository'), model.repository);
        const local = field(form, imageT('image_settings.local_path', 'Local model path (optional)'), model.local_path);
        const steps = field(form, imageT('image_settings.default_steps', 'Default steps'), model.default_steps, 'number');
        steps.min = 1; steps.max = model.provider === 'diffusionkit' ? 8 : 50;
        const guidance = field(form, imageT('image_settings.default_guidance', 'Default guidance'), model.default_guidance, 'number');
        guidance.min = 0; guidance.max = 10; guidance.step = 0.1;
        card.append(form);
        const loraList = node('div', null, 'image-lora-list');
        const loraRows = [];
        function addLora(lora = {}) {
            const row = node('fieldset', null, 'image-lora-row');
            row.append(node('legend', 'LoRA ' + (loraRows.length + 1)));
            const use = field(row, imageT('image_settings.enabled', 'Enabled'), lora.enabled ?? true, 'checkbox');
            const source = field(row, imageT(
                'image_settings.lora_path',
                'Path or org/repo[:file.safetensors]'
            ), lora.path || lora.repository);
            const scale = field(row, imageT('image_settings.weight', 'Weight'), lora.scale ?? 1, 'number');
            scale.min = -2; scale.max = 2; scale.step = 0.05;
            const trigger = field(row, imageT('image_settings.trigger_word', 'Trigger word (hint)'), lora.trigger_word);
            const remove = node('button', imageT('image_settings.remove', 'Remove'), 'message-action-btn'); remove.type = 'button';
            const entry = { row, use, source, scale, trigger };
            remove.onclick = () => { row.remove(); loraRows.splice(loraRows.indexOf(entry), 1); };
            row.append(remove); loraList.append(row); loraRows.push(entry);
        }
        if (model.capabilities.includes('lora')) {
            for (const lora of model.loras) addLora(lora);
            const add = node('button', imageT('image_settings.add_lora', 'Add LoRA'), 'message-action-btn'); add.type = 'button';
            add.onclick = () => { if (loraRows.length < 8) addLora(); };
            card.append(loraList, add);
        } else card.append(node('p', imageT('image_settings.no_lora', 'This provider does not support LoRAs.'), 'settings-hint'));
        const controls = node('div', null, 'batch-chat-controls');
        if (!legacy) {
            const save = node('button', imageT('image_settings.save_config', 'Save configuration'), 'message-action-btn'); save.type = 'button';
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
        const activate = node('button', data.default_model === model.id ? imageT('image_settings.default_model', 'Default model') : imageT('image_settings.use_as_default', 'Set as default'), 'message-action-btn');
        activate.type = 'button'; activate.disabled = !model.enabled || !model.available;
        activate.onclick = () => action(activate, async () => {
            await api('/models/' + encodeURIComponent(model.id) + '/activate', 'POST', {});
            await api('/role', 'PUT', { model: 'auto' });
        });
        controls.append(activate); card.append(controls); return card;
    }
    async function load() {
        status.textContent = imageT('image_settings.loading', 'Loading image models …');
        try {
            const data = await api('/models');
            role.replaceChildren();
            const auto = node('option', imageT(
                'image_settings.auto',
                'Automatic ({model})',
                { model: data.default_model }
            )); auto.value = 'auto'; role.append(auto);
            for (const model of data.models) {
                const option = node('option', model.name + (!model.enabled ? ' · deaktiviert' : !model.available ? ' · Gewichte fehlen' : ''));
                option.value = model.id; option.disabled = !model.enabled || !model.available; role.append(option);
            }
            if (data.role !== 'auto' && !data.models.some(model => model.id === data.role)) {
                const invalid = node('option', data.role + imageT('image_settings.unregistered_suffix', ' · not registered')); invalid.value = data.role; invalid.disabled = true; role.append(invalid);
            }
            role.value = data.role;
            list.replaceChildren(...data.models.map(model => renderModel(model, data)));
            status.textContent = imageT(
                'image_settings.active',
                'Active: {model}',
                { model: data.effective_model }
            ) +
            (
                data.running_model
                    ? imageT(
                        'image_settings.running_job',
                        ' · job running: {model}',
                        { model: data.running_model }
                    )
                    : imageT(
                        'image_settings.no_model_loaded',
                        ' · no image model currently loaded'
                    )
            );
        } catch (error) { status.textContent = imageT(
            'image_settings.error_prefix',
            'Image models: {message}',
            { message: error.message }
        ); }
    }
    role.onchange = () => action(role, () => api('/role', 'PUT', { model: role.value }));
    window.MLXImageSettings = { load };
})();

/*
 * Image artifact regeneration lives next to the image settings because it
 * reuses the exact image-runtime parameters from an existing artifact. The
 * transient seed is intentionally omitted so the image service chooses a new
 * seed for every click.
 */
(() => {
    const generation = window.MLXChatGeneration;

    if (
        !generation?.createImageUpscaleMenu ||
        generation.__imageRegenerateInstalled
    ) {
        return;
    }

    generation.__imageRegenerateInstalled = true;

    const originalCreateImageUpscaleMenu =
        generation.createImageUpscaleMenu.bind(generation);

    const IMAGE_QUALITIES = new Set([
        'fast',
        'standard',
        'quality'
    ]);

    function finiteNumber(value, minimum, maximum) {
        const number = Number(value);
        return Number.isFinite(number) &&
            number >= minimum &&
            number <= maximum
            ? number
            : null;
    }

    function regenerationOptions(artifact) {
        const prompt = String(artifact?.prompt || '').trim();

        if (!prompt) {
            return null;
        }

        const imageOptions = {
            prompt,
            model: String(artifact?.model || 'auto'),
            auto_size: false
        };

        const width = finiteNumber(artifact?.width, 256, 1216);
        const height = finiteNumber(artifact?.height, 256, 1216);
        const steps = finiteNumber(artifact?.steps, 1, 50);
        const guidance = finiteNumber(artifact?.guidance, 0, 10);

        if (width != null) imageOptions.width = Math.round(width);
        if (height != null) imageOptions.height = Math.round(height);
        if (steps != null) imageOptions.steps = Math.round(steps);
        if (guidance != null) imageOptions.guidance = guidance;

        const negativePrompt = String(
            artifact?.negative_prompt || ''
        ).trim();

        if (negativePrompt) {
            imageOptions.negative_prompt = negativePrompt;
        }

        return {
            prompt,
            imageOptions,
            quality: IMAGE_QUALITIES.has(artifact?.quality)
                ? artifact.quality
                : null
        };
    }

    function activeImageJob(status) {
        return [
            'queued',
            'loading',
            'running',
            'saving'
        ].includes(String(status || ''));
    }

    function persistentChatRevision(session) {
        const revision = Number(session?.revision);
        return Number.isSafeInteger(revision) && revision >= 0
            ? revision
            : 0;
    }

    function pendingImageMessage(
        artifact,
        variantIndex = null,
        variantCount = null,
        variantGroupId = null
    ) {
        const base = imageT(
            'generation.image_generating',
            'Generating the image locally with the selected image model …'
        );
        const isVariantSet = Number(variantCount) > 1;

        return {
            role: 'assistant',
            content: isVariantSet
                ? base + ' · ' + variantIndex + '/' + variantCount
                : base,
            image_generation_pending: true,
            image_regenerated_from_artifact_id:
                artifact?.artifact_id || null,
            image_variant_index:
                isVariantSet ? Number(variantIndex) : null,
            image_variant_count:
                isVariantSet ? Number(variantCount) : null,
            image_variant_group_id:
                isVariantSet ? variantGroupId : null
        };
    }

    function newTraceId(prefix = 'image-regenerate') {
        return globalThis.crypto?.randomUUID
            ? globalThis.crypto.randomUUID()
            : prefix + '-' + Date.now().toString(16) + '-' +
                Math.random().toString(16).slice(2);
    }

    async function submitPreparedImage(
        prepared,
        session,
        pendingMessage
    ) {
        try {
            const response = await fetch(
                '/api/mlx/chat/actions',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        prompt: prepared.prompt,
                        action: 'image_generate',
                        image_options: prepared.imageOptions,
                        quality: prepared.quality,
                        resolved_target: 'image',
                        conversation_context: [],
                        trace_id: newTraceId(),
                        chat_id: session.id,
                        chat_revision:
                            persistentChatRevision(session)
                    })
                }
            );

            if (!response.ok) {
                throw new Error(await response.text());
            }

            const toolResult = await response.json();

            if (
                window.MLXChatSessions?.currentSession?.() !== session ||
                !session.messages.includes(pendingMessage)
            ) {
                const staleJob = toolResult?.data?.job;

                if (
                    staleJob?.id &&
                    activeImageJob(staleJob.status)
                ) {
                    fetch(
                        '/api/mlx/image-jobs/' +
                            encodeURIComponent(staleJob.id) +
                            '/cancel',
                        { method: 'POST' }
                    ).catch(() => {});
                }

                return false;
            }

            if (toolResult?.tool !== 'image_generate') {
                throw new Error(
                    imageT(
                        'generation.image_regenerate_unexpected_action',
                        'The image regeneration request was not accepted.'
                    )
                );
            }

            if (toolResult.data?.job?.id) {
                generation.updateImageJobMessage(
                    session,
                    pendingMessage,
                    toolResult
                );
                return true;
            }

            pendingMessage.tool_result = toolResult;
            pendingMessage.image_generation_pending = false;

            if (
                toolResult.status === 'completed' &&
                toolResult.artifacts?.[0]?.artifact_id
            ) {
                session.workspace = {
                    ...(session.workspace || {}),
                    active_artifact_id:
                        toolResult.artifacts[0].artifact_id
                };
                pendingMessage.content = '';
                return true;
            }

            throw new Error(
                toolResult?.error ||
                imageT(
                    'generation.action_failed',
                    'The action could not be completed.'
                )
            );

        } catch (error) {
            pendingMessage.image_generation_pending = false;
            pendingMessage.tool_result = {
                type: 'tool_result',
                tool: 'image_generate',
                status: 'failed',
                data: {},
                artifacts: [],
                error: error?.message || String(error)
            };
            pendingMessage.content = imageT(
                'generation.tool_error',
                '**Tool error:** {message}',
                { message: pendingMessage.tool_result.error }
            );
            return false;
        }
    }

    function persistAndRender(session) {
        session.updated = Date.now();
        window.MLXChatSessions.saveSessions();
        window.MLXChatRendering?.renderAll?.({
            contentUpdated: true
        });
    }

    async function regenerateImageArtifact(artifact) {
        const prepared = regenerationOptions(artifact);
        const session = window.MLXChatSessions?.currentSession?.();

        if (!prepared || !session) {
            return false;
        }

        const pendingMessage = pendingImageMessage(artifact);
        session.messages.push(pendingMessage);
        persistAndRender(session);

        const started = await submitPreparedImage(
            prepared,
            session,
            pendingMessage
        );

        persistAndRender(session);

        if (started) {
            generation.resumeImageJobsForSession?.(session);
        }

        return started;
    }

    async function generateImageVariants(artifact, count = 3) {
        const prepared = regenerationOptions(artifact);
        const session = window.MLXChatSessions?.currentSession?.();
        const variantCount = Math.max(
            2,
            Math.min(6, Math.round(Number(count) || 3))
        );

        if (!prepared || !session) {
            return false;
        }

        const groupId = newTraceId('image-variant-group');
        const pendingMessages = Array.from(
            { length: variantCount },
            (_unused, index) => pendingImageMessage(
                artifact,
                index + 1,
                variantCount,
                groupId
            )
        );

        session.messages.push(...pendingMessages);
        persistAndRender(session);

        let startedCount = 0;

        for (const pendingMessage of pendingMessages) {
            if (
                await submitPreparedImage(
                    prepared,
                    session,
                    pendingMessage
                )
            ) {
                startedCount += 1;
            }
        }

        persistAndRender(session);

        if (startedCount > 0) {
            generation.resumeImageJobsForSession?.(session);
        }

        return startedCount === variantCount;
    }

    generation.createImageUpscaleMenu = source => {
        const enhanceMenu = originalCreateImageUpscaleMenu(source);

        // Text-to-image artifacts have a prompt but no source image. Edits and
        // upscales intentionally keep their existing enhancement-only UI.
        if (
            !source?.prompt ||
            source?.source_path ||
            source?.scale
        ) {
            return enhanceMenu;
        }

        const fragment = document.createDocumentFragment();
        const regenerate = document.createElement('button');
        const variants = document.createElement('button');

        regenerate.type = 'button';
        regenerate.className = 'message-action-btn';
        regenerate.textContent = imageT(
            'ui.regenerate',
            'Regenerate'
        );
        regenerate.title = regenerate.textContent;

        variants.type = 'button';
        variants.className = 'message-action-btn';
        variants.textContent = '3× ' + imageT(
            'ui.regenerate',
            'Regenerate'
        );
        variants.title = variants.textContent;

        regenerate.addEventListener('click', async () => {
            regenerate.disabled = true;
            variants.disabled = true;
            const originalLabel = regenerate.textContent;
            regenerate.textContent = imageT(
                'common.loading',
                'Loading…'
            );

            const started = await regenerateImageArtifact(source);

            if (!started && regenerate.isConnected) {
                regenerate.disabled = false;
                variants.disabled = false;
                regenerate.textContent = originalLabel;
            }
        });

        variants.addEventListener('click', async () => {
            regenerate.disabled = true;
            variants.disabled = true;
            const originalLabel = variants.textContent;
            variants.textContent = imageT(
                'common.loading',
                'Loading…'
            );

            const started = await generateImageVariants(source, 3);

            if (!started && variants.isConnected) {
                regenerate.disabled = false;
                variants.disabled = false;
                variants.textContent = originalLabel;
            }
        });

        fragment.append(regenerate, variants, enhanceMenu);
        return fragment;
    };

    window.MLXImageRegenerate = {
        regenerateImageArtifact,
        generateImageVariants,
        regenerationOptions
    };
})();