function attachmentT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${name}}`,
            String(replacement ?? '')
        );
    }

    return value;
}

(function () {
    let attachments = [];
    let editOptions = {};
    let imageMode = 'auto';
    let pendingMaskUpload = Promise.resolve();
    let manualEditModel = false;
    let manualEditFields = new Set();
    let personPresetPending = false;

    function personReferencePreset(prompt) {
        const text = String(prompt || '');
        // Specific identity promises outrank "möglichst ähnlich" qualifiers.
        const exact = /\b(?:dieselbe[nr]?|derselben|demselben|denselben|gleiche[nmrs]?|gleichen)\s+(?:person|frau|mann|gesicht)\b|\b(?:exact(?:ly)?\s+)?(?:same|identical)\s+(?:(?:adult|young|older|middle-aged|elderly)\s+){0,2}(?:person|woman|man|face)\b|\b(?:behalte|bewahre|erhalte|keep|preserve|retain)\b.{0,80}\b(?:person|gesicht|aussehen|identität|face|identity|appearance)\b/iu;
        const similarity = /(?:^|[^\p{L}])(?:ähnelt|aehnelt|ähnlich|aehnlich|resembling|resembles|resemble|similar\s+to|looks\s+like)(?!\p{L})/iu;
        if (exact.test(text)) {
            return {kind: 'same_identity', strength: 0.75, steps: 40, guidance: 5.0};
        }
        if (similarity.test(text) && /\b(?:person|frau|mann|gesicht|woman|man|face)\b/iu.test(text)) {
            return {kind: 'resemblance', strength: 0.55, steps: 36, guidance: 5.5};
        }
        return null;
    }

    function applyPersonReferencePreset(models) {
        if (imageMode !== 'edit' ||
            attachments.filter(file => file.kind === 'image').length !== 1) return false;

        const preset = personReferencePreset(document.getElementById('input')?.value);
        // Respect explicit user choices and keep Qwen as the fallback if
        // Juggernaut is disabled, missing or not ready.
        const available = models.some(model =>
            model.id === 'juggernaut-xl' && model.enabled && model.available
        );
        if (!preset || !available || (manualEditModel && editOptions.model !== 'juggernaut-xl') ||
            (editOptions.model && editOptions.model !== 'juggernaut-xl')) return false;

        let changed = false;
        if (!manualEditModel && editOptions.model !== 'juggernaut-xl') {
            editOptions.model = 'juggernaut-xl';
            changed = true;
        }
        for (const key of ['strength', 'steps', 'guidance']) {
            if (!manualEditFields.has(key) && editOptions[key] !== preset[key]) {
                editOptions[key] = preset[key];
                changed = true;
            }
        }
        // Seed intentionally remains random; masks are not compatible with SDXL.
        return changed;
    }

    function offerPersonReferencePreset() {
        if (personPresetPending || imageMode !== 'edit' ||
            attachments.filter(file => file.kind === 'image').length !== 1) return;
        if (!personReferencePreset(document.getElementById('input')?.value)) return;
        personPresetPending = true;
        availableEditModels().then(models => {
            personPresetPending = false;
            if (applyPersonReferencePreset(models)) renderAttachments();
        }).catch(() => { personPresetPending = false; });
    }

    function uid() {
        return crypto.randomUUID();
    }

    const ALLOWED_EXTENSIONS = new Set([
        'txt',
        'md',
        'json',
        'php',
        'js',
        'ts',
        'html',
        'css',
        'py',
        'sh',
        'sql',
        'xml',
        'yml',
        'yaml',
        'ini',
        'conf',
        'log',
        'csv',
        'jpg',
        'jpeg',
        'png',
        'webp',
        'gif',
        'pdf'
    ]);

    const IMAGE_EXTENSIONS = new Set([
        'jpg',
        'jpeg',
        'png',
        'webp',
        'gif'
    ]);

    const MAX_FILE_SIZE = 250 * 1024 * 1024;
    const MAX_IMAGE_SIZE = 20 * 1024 * 1024;
    // Text files beyond this size are uploaded for batch processing and are
    // deliberately never copied into the ordinary chat prompt.
    const MAX_CONTEXT_FILE_CHARS = 100000;

    function fileExtension(name) {
        const parts = name.toLowerCase().split('.');

        if (parts.length < 2) {
            return '';
        }

        return parts.pop();
    }

    function isImageExtension(extension) {
        return IMAGE_EXTENSIONS.has(
            String(extension || '').toLowerCase()
        );
    }

    function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error);

            reader.readAsDataURL(file);
        });
    }

    function formatBytes(bytes) {
        if (bytes < 1024) {
            return bytes + ' B';
        }

        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(1) + ' KB';
        }

        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    // A shared promise prevents one model-list request per image attachment
    // while keeping model selection immediately available without opening a menu.
    let editModelsPromise = null;

    function availableEditModels() {
        if (!editModelsPromise) {
            editModelsPromise = fetch('/api/image/models', {cache: 'no-store'})
                .then(response => {
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    return response.json();
                })
                .then(data => (data.models || []).filter(model =>
                    model.capabilities?.includes('image_edit')
                ))
                .catch(error => {
                    editModelsPromise = null;
                    throw error;
                });
        }
        return editModelsPromise;
    }

    function renderEditControls(bar) {
        if (!attachments.some(file => file.kind === 'image')) return;

        // Display the intent first; edit-only controls stay out of the way.
        const modeLabel = document.createElement('label');
        modeLabel.className = 'image-attachment-mode';
        const modeText = document.createElement('span');
        modeText.className = 'image-attachment-mode-label';
        modeText.textContent = attachmentT('attachments.image_mode', 'Use image for');
        const modeSelect = document.createElement('select');
        modeSelect.className = 'image-edit-control image-attachment-mode-select';
        for (const [value, key, fallback] of [
            ['auto', 'attachments.image_mode_auto', 'Automatic'],
            ['describe', 'attachments.image_mode_describe', 'Beschreiben / analysieren'],
            ['edit', 'attachments.image_mode_edit', 'Edit']
        ]) {
            const choice = document.createElement('option');
            choice.value = value;
            choice.textContent = attachmentT(key, fallback);
            modeSelect.append(choice);
        }
        modeSelect.value = imageMode;
        modeSelect.addEventListener('change', () => {
            imageMode = modeSelect.value;
            renderAttachments();
            offerPersonReferencePreset();
        });
        modeLabel.append(modeText, modeSelect);
        bar.append(modeLabel);
        if (imageMode !== 'edit') return;

        const panel = document.createElement('section');
        panel.className = 'image-edit-options';
        panel.setAttribute('aria-label',
            attachmentT('attachments.edit_model', 'Editing model'));

        const primary = document.createElement('div');
        primary.className = 'image-edit-primary';

        const modelLabel = document.createElement('label');
        modelLabel.className = 'image-edit-model-field';
        modelLabel.textContent = attachmentT('attachments.edit_model', 'Editing model');

        const select = document.createElement('select');
        select.className = 'image-edit-control';
        const automatic = document.createElement('option');
        automatic.value = 'auto';
        automatic.textContent = attachmentT('attachments.edit_auto', 'Automatic');
        select.append(automatic);
        select.value = 'auto';
        // During async model discovery the current model's option is not yet
        // attached. Do not erase its strength/steps while rebuilding the UI.
        let modelOptionsLoaded = false;
        const selectedSdxl = () => select.value === 'juggernaut-xl' ||
            (!modelOptionsLoaded && editOptions.model === 'juggernaut-xl');
        const strengthLabel = document.createElement('label');
        strengthLabel.className = 'image-edit-strength-field';
        strengthLabel.textContent = attachmentT('attachments.img2img_strength', 'Veränderungsstärke');
        const strengthValue = document.createElement('output');
        strengthValue.className = 'image-edit-strength-value';
        const strength = document.createElement('input');
        strength.type = 'range';
        strength.min = '0.15';
        strength.max = '0.85';
        strength.step = '0.05';
        strength.className = 'image-edit-strength-control';
        strength.value = String(editOptions.model === 'juggernaut-xl'
            ? (editOptions.strength ?? 0.45) : 0.45);
        const updateStrength = () => {
            const useSdxl = selectedSdxl();
            strengthLabel.hidden = !useSdxl;
            if (!useSdxl) {
                delete editOptions.strength;
            } else {
                strength.value = String(editOptions.strength ?? 0.45);
                editOptions.strength = Number(strength.value);
                strengthValue.value = Number(strength.value).toFixed(2);
                strengthValue.textContent = strengthValue.value;
            }
        };
        strength.addEventListener('input', () => {
            if (select.value !== 'juggernaut-xl') return;
            editOptions.strength = Number(strength.value);
            manualEditFields.add('strength');
            strengthValue.value = Number(strength.value).toFixed(2);
            strengthValue.textContent = strengthValue.value;
        });
        select.addEventListener('change', () => {
            manualEditModel = true;
            if (select.value === 'auto') delete editOptions.model;
            else editOptions.model = select.value;
            if (select.value === 'juggernaut-xl') {
                // SDXL is whole-image img2img, not Qwen masked editing.
                delete editOptions.mask_path;
                delete editOptions.auto_mask;
            }
            updateStrength();
        });
        modelLabel.append(select);
        primary.append(modelLabel);
        strengthLabel.append(strength, strengthValue);
        primary.append(strengthLabel);

        availableEditModels().then(models => {
            if (!panel.isConnected) return;
            modelOptionsLoaded = true;
            for (const model of models) {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.name +
                    (model.available ? '' : ' · ' + (model.availability_note || attachmentT('attachments.edit_unavailable', 'unavailable')));
                option.disabled = !model.enabled || !model.available;
                select.append(option);
            }
            if (editOptions.model && !models.some(model => model.id === editOptions.model)) {
                const unknown = document.createElement('option');
                unknown.value = editOptions.model;
                unknown.textContent = editOptions.model;
                unknown.disabled = true;
                select.append(unknown);
            }
            if (applyPersonReferencePreset(models)) {
                renderAttachments();
                return;
            }
            select.value = editOptions.model || 'auto';
            updateStrength();
            updateSamplingVisibility();
        }).catch(() => {
            modelOptionsLoaded = true;
            // Keep automatic routing available even if model discovery is offline.
            if (editOptions.model) {
                const previous = document.createElement('option');
                previous.value = editOptions.model;
                previous.textContent = editOptions.model;
                select.append(previous);
                select.value = editOptions.model;
            }
            updateStrength();
            updateSamplingVisibility();
        });

        updateStrength();

        const advanced = document.createElement('details');
        advanced.className = 'image-edit-advanced';
        const summary = document.createElement('summary');
        summary.textContent = attachmentT('attachments.edit_more', 'More options');
        advanced.append(summary);

        const fields = document.createElement('div');
        fields.className = 'image-edit-advanced-fields';

        const negativeLabel = document.createElement('label');
        negativeLabel.textContent = attachmentT('attachments.edit_negative_prompt', 'Negative prompt');
        const negative = document.createElement('input');
        negative.type = 'text';
        negative.maxLength = 2000;
        negative.className = 'image-edit-control';
        negative.value = editOptions.negative_prompt || '';
        negative.placeholder = attachmentT('attachments.edit_negative_placeholder',
            'Optional: What should not appear in the image?');
        negative.addEventListener('change', () => {
            if (negative.value.trim()) editOptions.negative_prompt = negative.value.trim();
            else delete editOptions.negative_prompt;
        });
        negativeLabel.append(negative);
        fields.append(negativeLabel);

        const sdxlSampling = document.createElement('div');
        sdxlSampling.className = 'image-edit-sdxl-sampling';
        const sdxlNumeric = [
            ['steps', 'attachments.img2img_steps', 'Steps', 1, 50, 1],
            ['guidance', 'attachments.img2img_cfg', 'CFG / Guidance', 0, 10, 0.1],
            ['seed', 'attachments.img2img_seed', 'Seed (optional)', 0, 4294967295, 1]
        ];
        for (const [key, translationKey, fallback, min, max, step] of sdxlNumeric) {
            const label = document.createElement('label');
            label.textContent = attachmentT(translationKey, fallback);
            const field = document.createElement('input');
            field.type = 'number';
            field.className = 'image-edit-control';
            field.min = String(min);
            field.max = String(max);
            field.step = String(step);
            field.placeholder = attachmentT('attachments.img2img_default', 'Standard');
            field.value = editOptions[key] == null ? '' : String(editOptions[key]);
            field.addEventListener('change', () => {
                manualEditFields.add(key);
                const raw = field.value.trim();
                if (!raw) {
                    delete editOptions[key];
                } else if (field.checkValidity() && Number.isFinite(Number(raw))) {
                    editOptions[key] = Number(raw);
                } else {
                    field.reportValidity();
                }
            });
            label.append(field);
            sdxlSampling.append(label);
        }
        const updateSamplingVisibility = () => {
            sdxlSampling.hidden = select.value !== 'juggernaut-xl' &&
                !(!modelOptionsLoaded && editOptions.model === 'juggernaut-xl');
            if (sdxlSampling.hidden) {
                // Other edit models must not even receive the SDXL numeric
                // inputs in the DOM; otherwise those controls can interfere
                // with keyboard navigation or precision-edit workflows.
                sdxlSampling.remove?.();
                for (const key of ['steps', 'guidance', 'seed']) delete editOptions[key];
            } else if (!Array.from(fields.children || []).includes(sdxlSampling)) {
                fields.append(sdxlSampling);
            }
        };
        select.addEventListener('change', updateSamplingVisibility);
        updateSamplingVisibility();

        const maskLabel = document.createElement('label');
        maskLabel.textContent = attachmentT('attachments.edit_mask_short', 'Mask (optional)');
        const mask = document.createElement('input');
        mask.type = 'file';
        mask.accept = 'image/png,image/jpeg,image/webp';
        mask.className = 'image-edit-control';
        const maskStatus = document.createElement('small');
        maskStatus.className = 'image-edit-mask-status';
        maskStatus.textContent = editOptions.mask_path
            ? attachmentT('attachments.edit_mask_ready', 'Mask uploaded')
            : '';
        mask.addEventListener('change', () => {
            pendingMaskUpload = (async () => {
                if (!mask.files?.[0]) {
                    delete editOptions.mask_path;
                    maskStatus.textContent = '';
                    return;
                }
                mask.disabled = true;
                try {
                    const file = mask.files[0];
                    const uploaded = await uploadImageAttachments([
                        {file, name: file.name, kind: 'image'}
                    ]);
                    if (!uploaded[0]?.upload?.path) {
                        throw new Error(attachmentT('generation.image_upload_failed',
                            'Image could not be uploaded.'));
                    }
                    editOptions.mask_path = uploaded[0].upload.path;
                    delete editOptions.auto_mask;
                    maskStatus.textContent = attachmentT(
                        'attachments.edit_mask_ready', 'Mask uploaded');
                } catch (error) {
                    delete editOptions.mask_path;
                    maskStatus.textContent = '';
                    alert(error.message);
                } finally {
                    mask.disabled = false;
                }
            })();
        });
        maskLabel.append(mask, maskStatus);
        fields.append(maskLabel);
        const updateMaskVisibility = () => {
            maskLabel.hidden = selectedSdxl();
        };
        select.addEventListener('change', updateMaskVisibility);
        updateMaskVisibility();
        advanced.append(fields);
        primary.append(advanced);
        panel.append(primary);
        bar.append(panel);
    }

    function renderAttachments() {
        const bar = document.getElementById('attachmentBar');

        if (!attachments.some(file => file.kind === 'image')) {
            imageMode = 'auto';
            editOptions = {};
            manualEditModel = false;
            manualEditFields = new Set();
        }
        bar.innerHTML = '';

        if (!attachments.length) {
            bar.classList.remove('visible');
            return;
        }

        bar.classList.add('visible');

        attachments.forEach((file, index) => {
            const chip = document.createElement('div');
            chip.className = 'attachment-chip';
            chip.dataset.attachmentId = file.id;
            if (file.kind === 'image') {
                chip.draggable = true;
                chip.addEventListener('dragstart', event => {
                    event.dataTransfer.setData('application/x-mlx-reference', file.id);
                    event.dataTransfer.effectAllowed = 'move';
                });
                chip.addEventListener('dragover', event => event.preventDefault());
                chip.addEventListener('drop', event => {
                    const id = event.dataTransfer.getData('application/x-mlx-reference');
                    if (!id) return;
                    event.preventDefault();
                    event.stopPropagation();
                    moveAttachment(id, file.id);
                });
                chip.addEventListener('keydown', event => {
                    if (!event.altKey || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
                    event.preventDefault();
                    const images = attachments.filter(item => item.kind === 'image');
                    const target = images[images.indexOf(file) + (event.key === 'ArrowLeft' ? -1 : 1)];
                    if (target) moveAttachment(file.id, target.id);
                    bar.querySelector('[data-attachment-id="' + file.id + '"]')?.focus();
                });
                chip.tabIndex = 0;
                chip.title = attachmentT('attachments.reorder', 'Drag to reorder; Alt + arrow keys also work.');
            }

            if (file.kind === 'image' && file.data_url) {
                const preview = document.createElement('img');

                preview.src = file.data_url;
                preview.alt = file.name;
                preview.className = 'attachment-image-preview';
                chip.appendChild(preview);
            }

            const name = document.createElement('span');

            name.className = 'attachment-name';

            if (file.processing) {
                name.innerHTML =
                    '<span class="attachment-processing-dot"></span>' +
                    file.name +
                    attachmentT('attachments.pdf_processing', ' · PDF is being processed and indexed …');
                chip.classList.add('processing');
            } else {
                let suffix =
                    ' · ' +
                    formatBytes(file.size) +
                    (
                        file.document_type === 'pdf' && file.pages
                            ? ' · ' + file.pages + ' Seiten'
                            : ''
                    );

                if (
                    file.document_type === 'pdf' &&
                    file.rag_status
                ) {
                    if (file.rag_status === 'ready') {
                        suffix += attachmentT('attachments.rag_ready', ' · ✓ RAG ready');
                    } else if (file.rag_status === 'error') {
                        suffix += attachmentT('attachments.rag_error', ' · ⚠ RAG error');
                    } else if (
                        file.rag_status === 'indexing' &&
                        file.rag_chunks_total > 0
                    ) {
                        suffix +=
                            ' · RAG ' +
                            file.rag_chunks_done +
                            '/' +
                            file.rag_chunks_total +
                            ' · ' +
                            Number(file.rag_progress || 0).toFixed(1) +
                            ' %';
                    } else if (
                        file.rag_status === 'queued' ||
                        file.rag_status === 'indexing'
                    ) {
                        suffix += attachmentT('attachments.rag_preparing', ' · Preparing RAG …');
                    }
                }

                const number = file.kind === 'image' ? attachments.filter(item => item.kind === 'image').indexOf(file) + 1 : null;
                name.textContent = (number ? number + '. ' : '') + file.name + suffix;
            }

            const remove = document.createElement('button');

            remove.className = 'attachment-remove';
            remove.textContent = '×';

            remove.addEventListener('click', () => {
                attachments.splice(index, 1);
                renderAttachments();
            });

            chip.appendChild(name);

            if (file.kind === 'image') {
                chip.className += ' image-attachment-chip';

                const enhanceMenu = window.MLXChatGeneration
                    ?.createImageUpscaleMenu?.(file);
                if (enhanceMenu) {
                    chip.appendChild(enhanceMenu);
                }
            }

            chip.appendChild(remove);

            bar.appendChild(chip);
        });
        renderEditControls(bar);
    }

    async function pollDocumentRag(attachmentId) {
        while (true) {
            const attachment = attachments.find(
                item => item.id === attachmentId
            );

            if (
                !attachment ||
                !attachment.document_id ||
                attachment.document_type !== 'pdf'
            ) {
                return;
            }

            try {
                const response = await fetch(
                    '/api/mlx/documents/status/' +
                    encodeURIComponent(attachment.document_id),
                    {
                        cache: 'no-store'
                    }
                );

                if (!response.ok) {
                    throw new Error(
                        'RAG-Status HTTP ' + response.status
                    );
                }

                const status = await response.json();

                const current = attachments.find(
                    item => item.id === attachmentId
                );

                if (!current) {
                    return;
                }

                current.rag_status =
                    status.status || 'unknown';

                current.rag_chunks_done =
                    Number(status.chunks_done || 0);

                current.rag_chunks_total =
                    Number(status.chunks_total || 0);

                current.rag_progress =
                    Number(status.progress || 0);

                current.rag_cached =
                    Boolean(status.cached);

                current.rag_error =
                    status.error || null;

                renderAttachments();

                if (
                    current.rag_status === 'ready' ||
                    current.rag_status === 'error'
                ) {
                    return;
                }

            } catch (error) {
                console.warn(
                    '[MLX PDF RAG] Could not read status:',
                    error
                );
            }

            await new Promise(
                resolve => setTimeout(resolve, 750)
            );
        }
    }


    function moveAttachment(id, targetId) {
        const from = attachments.findIndex(item => item.id === id);
        const to = attachments.findIndex(item => item.id === targetId);
        if (from < 0 || to < 0 || from === to) return;
        const [item] = attachments.splice(from, 1);
        attachments.splice(to, 0, item);
        renderAttachments();
    }

    let addingFiles = Promise.resolve();
    function addFiles(files) {
        const list = Array.from(files);
        addingFiles = addingFiles.catch(() => {}).then(() => addFilesSequential(list));
        return addingFiles;
    }

    async function addFilesSequential(files) {
        const list = Array.from(files);

        for (const file of list) {
            const ext = fileExtension(file.name);

            if (!ALLOWED_EXTENSIONS.has(ext)) {
                alert(
                    attachmentT(
                    'attachments.unsupported_type',
                    'Unsupported file type: {name}',
                    { name: file.name }
                )
                );

                continue;
            }

            const isImage = isImageExtension(ext);

            const sizeLimit =
                isImage
                    ? MAX_IMAGE_SIZE
                    : MAX_FILE_SIZE;

            if (file.size > sizeLimit) {
                alert(
                    attachmentT(
                    'attachments.too_large',
                    '{name} is larger than {size} MB.',
                    {
                        name: file.name,
                        size: isImage
                            ? (MAX_IMAGE_SIZE / 1024 / 1024)
                            : (MAX_FILE_SIZE / 1024 / 1024)
                    }
                )
                );

                continue;
            }

            if (ext === 'pdf') {
                const processingId = uid();

                attachments.push({
                    id: processingId,
                    name: file.name,
                    size: file.size,
                    type: file.type || 'application/pdf',
                    extension: 'pdf',
                    kind: 'document',
                    source_kind: 'document',
                    document_type: 'pdf',
                    processing: true
                });

                renderAttachments();

                if (window.MLXChatRuntime) {
                    MLXChatRuntime.setExternalRuntimeBusy(true);
                }

                try {
                    const data = new FormData();
                    data.append('file', file, file.name);

                    const response = await fetch(
                        '/api/mlx/documents/parse',
                        {
                            method: 'POST',
                            body: data
                        }
                    );

                    if (!response.ok) {
                        let detail = '';

                        try {
                            const errorData = await response.json();
                            detail = errorData.detail || '';
                        } catch (_) {
                            detail = await response.text();
                        }

                        throw new Error(
                            detail ||
                            attachmentT('attachments.pdf_processing_failed', 'Could not process the PDF.')
                        );
                    }

                    const parsed = await response.json();

                    const extractedText =
                        String(parsed.text || '');

                    if (!extractedText.trim()) {
                        throw new Error(
                            attachmentT('attachments.pdf_no_text', 'No readable text was found in this PDF.')
                        );
                    }

                    /*
                     * Important:
                     * Create a local text file from the extracted PDF content
                     * for the existing large-file pipeline. Keep the original
                     * PDF only as the user-facing representation.
                     */
                    const extractedFile = new File(
                        [extractedText],
                        file.name + '.txt',
                        {
                            type: 'text/plain'
                        }
                    );

                    const processingIndex =
                        attachments.findIndex(
                            item => item.id === processingId
                        );

                    const completedAttachment = {
                        id: processingId,
                        name: file.name,
                        size: file.size,
                        type:
                            file.type ||
                            'application/pdf',
                        extension: 'pdf',

                        /*
                         * Deliberately use "text" so the existing file,
                         * batch, and agent routes continue to work.
                         */
                        kind: 'document',

                        source_kind: 'document',
                        document_type: 'pdf',
                        document_id: parsed.document_id || null,
                        pages: parsed.pages || 0,
                        page_texts:
                            Array.isArray(parsed.page_texts)
                                ? parsed.page_texts
                                : [],
                        characters:
                            parsed.characters ||
                            extractedText.length,

                        content:
                            extractedText.length <=
                            MAX_CONTEXT_FILE_CHARS
                                ? extractedText
                                : '',

                        file: extractedFile,

                        context_omitted:
                            extractedText.length >
                            MAX_CONTEXT_FILE_CHARS,
                        processing: false,

                        rag_status:
                            parsed.rag?.status ||
                            (
                                parsed.rag?.indexed
                                    ? 'ready'
                                    : 'queued'
                            ),

                        rag_chunks_done:
                            Number(
                                parsed.rag?.chunks_done || 0
                            ),

                        rag_chunks_total:
                            Number(
                                parsed.rag?.chunks_total ||
                                parsed.rag?.chunks ||
                                0
                            ),

                        rag_progress:
                            Number(
                                parsed.rag?.progress || 0
                            ),

                        rag_cached:
                            Boolean(parsed.rag?.cached),

                        rag_error:
                            parsed.rag?.error || null
                    };

                    if (processingIndex >= 0) {
                        attachments[processingIndex] =
                            completedAttachment;
                    } else {
                        attachments.push(completedAttachment);
                    }

                    renderAttachments();

                    if (
                        completedAttachment.document_id &&
                        completedAttachment.rag_status !== 'ready' &&
                        completedAttachment.rag_status !== 'error'
                    ) {
                        pollDocumentRag(
                            completedAttachment.id
                        );
                    }

                } catch (error) {
                    const processingIndex =
                        attachments.findIndex(
                            item => item.id === processingId
                        );

                    if (processingIndex >= 0) {
                        attachments.splice(processingIndex, 1);
                    }

                    renderAttachments();

                    console.error(
                        '[MLX PDF]',
                        error
                    );

                    alert(attachmentT(
                        'attachments.pdf_read_failed',
                        'Could not read PDF: {name}\n\n{message}',
                        {
                            name: file.name,
                            message: error.message || attachmentT('attachments.unknown_error', 'Unknown error')
                        }
                    ));
                } finally {
                    if (window.MLXChatRuntime) {
                        MLXChatRuntime.setExternalRuntimeBusy(false);
                    }
                }

                continue;
            }

            if (isImage) {
                if (attachments.filter(item => item.kind === 'image').length >= 10) {
                    alert(attachmentT('attachments.reference_limit', 'Up to ten reference images are supported.'));
                    continue;
                }
                let dataUrl;

                try {
                    dataUrl = await fileToDataUrl(file);
                } catch {
                    alert(
                        attachmentT(
                    'ui.image_read_failed_prefix',
                    'Image could not be read:'
                ) + ' ' +
                        file.name
                    );

                    continue;
                }

                attachments.push({
                    id: uid(),
                    name: file.name,
                    size: file.size,
                    type: file.type || 'image/jpeg',
                    extension: ext,
                    kind: 'image',
                    data_url: dataUrl,
                    file: file
                });

                continue;
            }

            let content = '';
            if (file.size <= MAX_CONTEXT_FILE_CHARS) {
                try {
                    content = await file.text();
                } catch {
                    alert(attachmentT(
                    'attachments.file_read_failed',
                    'File could not be read: {name}',
                    { name: file.name }
                ));
                    continue;
                }
            }

            attachments.push({
                id: uid(),
                name: file.name,
                size: file.size,
                type: file.type,
                extension: ext,
                kind: 'text',
                content: content,
                file: file,
                context_omitted: file.size > MAX_CONTEXT_FILE_CHARS
            });
        }

        renderAttachments();
    }

    function buildAttachmentContext() {
        if (!attachments.length) {
            return '';
        }

        const parts = [];

        const textFiles =
            attachments.filter(
                file => file.kind !== 'image'
            );

        if (!textFiles.length) {
            return '';
        }

        parts.push(
            attachmentT('attachments.user_files', 'Additional user files:')
        );

        for (const file of textFiles) {
            parts.push(
                '\n--- FILE: ' +
                file.name +
                ' ---\n'
            );

            parts.push(
                '```' +
                file.extension +
                '\n' +
                file.content +
                '\n```'
            );
        }

        return parts.join('\n');
    }

    function getAttachments() {
        return attachments;
    }

    function clearAttachments() {
        attachments = [];
        editOptions = {};
        imageMode = 'auto';
        manualEditModel = false;
        manualEditFields = new Set();
        renderAttachments();
    }

    function removeAttachment(attachment) {
        const index = attachments.indexOf(attachment);
        if (index < 0) {
            return false;
        }
        attachments.splice(index, 1);
        renderAttachments();
        return true;
    }

    async function uploadTextAttachments(files) {
        const uploaded = [];
        for (const item of files.filter(file => file.kind === 'text' && file.file)) {
            const data = new FormData();
            data.append('file', item.file, item.name);
            const response = await fetch('/api/mlx/batch/upload', { method: 'POST', body: data });
            if (!response.ok) throw new Error(await response.text());
            uploaded.push({ attachment: item, upload: await response.json() });
        }
        return uploaded;
    }

    async function uploadImageAttachments(files) {
        const uploaded = [];

        for (const item of files.filter(
            file => file.kind === 'image' && file.file
        )) {
            const data = new FormData();

            data.append(
                'file',
                item.file,
                item.name
            );

            const response = await fetch(
                '/api/mlx/batch/upload',
                {
                    method: 'POST',
                    body: data
                }
            );

            if (!response.ok) {
                throw new Error(
                    await response.text()
                );
            }

            uploaded.push({
                attachment: item,
                upload: await response.json()
            });
        }

        return uploaded;
    }

    function init() {

        document.addEventListener(
            'paste',
            async event => {

                const clipboardData = event.clipboardData;

                if (
                    !clipboardData ||
                    !clipboardData.items
                ) {
                    return;
                }

                const imageFiles = [];

                for (const item of clipboardData.items) {

                    if (
                        item.kind !== 'file' ||
                        !item.type ||
                        !item.type.startsWith('image/')
                    ) {
                        continue;
                    }

                    const blob = item.getAsFile();

                    if (!blob) {
                        continue;
                    }

                    let extension = 'png';

                    if (item.type === 'image/jpeg') {
                        extension = 'jpg';
                    } else if (item.type === 'image/webp') {
                        extension = 'webp';
                    } else if (item.type === 'image/gif') {
                        extension = 'gif';
                    }

                    const filename = (
                        'clipboard-' +
                        new Date()
                            .toISOString()
                            .replace(/[:.]/g, '-') +
                        '.' +
                        extension
                    );

                    const file = new File(
                        [blob],
                        filename,
                        {
                            type: item.type,
                            lastModified: Date.now()
                        }
                    );

                    imageFiles.push(file);

                }

                if (!imageFiles.length) {
                    return;
                }

                event.preventDefault();

                await addFiles(imageFiles);

            }
        );

        document.getElementById(
            'attachButton'
        ).addEventListener(
            'click',
            () => {
                document.getElementById(
                    'fileInput'
                ).click();
            }
        );

        document.getElementById(
            'fileInput'
        ).addEventListener(
            'change',
            async event => {
                await addFiles(
                    event.target.files
                );

                event.target.value = '';
            }
        );

        const composer =
            document.getElementById(
                'composer'
            );

        // Defaults may become eligible after the user types the pose prompt.
        document.getElementById('input')?.addEventListener(
            'input', offerPersonReferencePreset
        );

        composer.addEventListener(
            'dragover',
            event => {
                event.preventDefault();

                composer.classList.add(
                    'dragging'
                );
            }
        );

        composer.addEventListener(
            'dragleave',
            event => {
                if (
                    !composer.contains(
                        event.relatedTarget
                    )
                ) {
                    composer.classList.remove(
                        'dragging'
                    );
                }
            }
        );

        composer.addEventListener(
            'drop',
            async event => {
                event.preventDefault();

                composer.classList.remove(
                    'dragging'
                );

                await addFiles(
                    event.dataTransfer.files
                );
            }
        );
    }

    window.formatBytes = formatBytes;

    window.MLXChatAttachments = {
        init: init,
        addFiles: addFiles,
        getEditOptions: () => imageMode === 'edit' ? {...editOptions} : {},
        getImageMode: () => imageMode,
        suggestPersonReferencePreset: personReferencePreset,
        whenReady: () => Promise.all([addingFiles, pendingMaskUpload]),
        moveAttachment: moveAttachment,
        buildAttachmentContext:
            buildAttachmentContext,
        getAttachments:
            getAttachments,
        uploadTextAttachments: uploadTextAttachments,
        uploadImageAttachments: uploadImageAttachments,
        removeAttachment: removeAttachment,
        clearAttachments:
            clearAttachments
    };
})();
