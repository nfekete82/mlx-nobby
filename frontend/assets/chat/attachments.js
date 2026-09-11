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

                name.textContent = file.name + suffix;
            }

            const remove = document.createElement('button');

            remove.className = 'attachment-remove';
            remove.textContent = '×';

            remove.addEventListener('click', () => {
                attachments.splice(index, 1);
                renderAttachments();
            });

            chip.appendChild(name);
            chip.appendChild(remove);

            bar.appendChild(chip);
        });
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


    async function addFiles(files) {
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
                     * Wichtig:
                     * Für die bestehende große-Dateien-Pipeline erzeugen
                     * wir aus dem extrahierten PDF-Inhalt eine lokale
                     * Textdatei. Die Original-PDF bleibt nur die
                     * Darstellung für den Benutzer.
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
                         * Absichtlich "text":
                         * Dadurch funktionieren die vorhandenen
                         * File-/Batch-/Agent-Routen weiter.
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
                    data_url: dataUrl
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
        renderAttachments();
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
        buildAttachmentContext:
            buildAttachmentContext,
        getAttachments:
            getAttachments,
        uploadTextAttachments: uploadTextAttachments,
        clearAttachments:
            clearAttachments
    };
})();
