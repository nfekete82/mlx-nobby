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
    let pendingMaskUpload = Promise.resolve();

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

    function renderEditControls(bar) {
        if (!attachments.some(file => file.kind === 'image')) return;
        const details = document.createElement('details');
        details.className = 'image-edit-options';
        const summary = document.createElement('summary');
        summary.textContent = attachmentT('attachments.edit_options', 'Image editing · advanced options');
        details.append(summary);
        function input(key, label, type, attributes = {}) {
            const wrapper = document.createElement('label');
            wrapper.textContent = attachmentT('attachments.edit_' + key, label);
            const control = document.createElement('input');
            control.type = type;
            Object.assign(control, attributes);
            if (type === 'checkbox') control.checked = key === 'use_kv_cache' ? editOptions[key] !== false : editOptions[key] === true;
            else control.value = editOptions[key] ?? '';
            control.addEventListener('change', () => {
                if (type === 'checkbox') editOptions[key] = control.checked;
                else if (control.value === '') delete editOptions[key];
                else editOptions[key] = type === 'number' ? Number(control.value) : control.value;
            });
            wrapper.append(control);
            details.append(wrapper);
        }
        const modelLabel = document.createElement('label');
        modelLabel.textContent = attachmentT('attachments.edit_model', 'Editing model');
        const select = document.createElement('select');
        const auto = document.createElement('option');
        auto.value = 'auto'; auto.textContent = attachmentT('attachments.edit_auto', 'Automatic · locally available models');
        select.append(auto);
        select.addEventListener('change', () => { editOptions.model = select.value; });
        modelLabel.append(select); details.append(modelLabel);
        let loaded = false;
        details.addEventListener('toggle', async () => {
            if (!details.open || loaded) return;
            loaded = true;
            try {
                const response = await fetch('/api/image/models');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const data = await response.json();
                for (const model of data.models || []) {
                    if (!model.capabilities?.includes('image_edit')) continue;
                    const option = document.createElement('option');
                    option.value = model.id; option.textContent = model.name + (model.available ? '' : ' · ' + model.availability_note);
                    option.disabled = !model.enabled || !model.available;
                    select.append(option);
                }
                if (editOptions.model && ![...select.options].some(option => option.value === editOptions.model)) {
                    const option = document.createElement('option');
                    option.value = editOptions.model; option.textContent = editOptions.model; select.append(option);
                }
                select.value = editOptions.model || 'auto';
            } catch (_) { loaded = false; }
        });
        input('seed', 'Seed (empty = random)', 'number', {min: 0, max: 4294967295});
        input('steps', 'Steps', 'number', {min: 1, max: 50});
        input('guidance', 'Guidance (negative prompts need > 1)', 'number', {min: 1, max: 10, step: 0.1});
        input('strength', 'Edit strength (0–1)', 'number', {min: 0.01, max: 1, step: 0.05});
        input('negative_prompt', 'Negative prompt', 'text', {maxLength: 2000});
        input('auto_mask', 'Auto-mask: object to repaint', 'text', {maxLength: 200});
        input('use_kv_cache', 'KV cache (on by default)', 'checkbox');
        input('use_step_cache', 'Step cache (requires KV cache; useful from 10 steps)', 'checkbox');
        input('enhance_prompt', 'Improve prompt with built-in vision model', 'checkbox');
        input('verify', 'Verify result with built-in vision model', 'checkbox');
        const maskLabel = document.createElement('label');
        maskLabel.textContent = attachmentT('attachments.edit_mask', 'Mask (white = repaint, black = preserve)');
        const mask = document.createElement('input'); mask.type = 'file'; mask.accept = 'image/png,image/jpeg,image/webp';
        mask.addEventListener('change', () => {
            pendingMaskUpload = (async () => {
            if (!mask.files[0]) { delete editOptions.mask_path; return; }
            mask.disabled = true;
            try {
                const uploaded = await uploadImageAttachments([{file: mask.files[0], name: mask.files[0].name, kind: 'image'}]);
                if (!uploaded[0]?.upload?.path) throw new Error(attachmentT('generation.image_upload_failed', 'Image could not be uploaded.'));
                editOptions.mask_path = uploaded[0].upload.path;
                delete editOptions.auto_mask;
                summary.textContent = attachmentT('attachments.edit_mask_ready', 'Image editing · mask uploaded');
            } catch (error) { delete editOptions.mask_path; alert(error.message); }
            finally { mask.disabled = false; }
            })();
        });
        maskLabel.append(mask); details.append(maskLabel);
        const hint = document.createElement('p');
        hint.textContent = attachmentT('attachments.edit_hint', 'Advanced options require a compatible MFLUX model. Reference order follows the numbered thumbnails. Original images are preserved. Identity preservation is best effort.');
        details.append(hint);
        bar.append(details);
    }

    function renderAttachments() {
        const bar = document.getElementById('attachmentBar');

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
        getEditOptions: () => ({...editOptions}),
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
