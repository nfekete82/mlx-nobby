/* Shared, lazy image dialog for chat and variant galleries. */
(() => {
    if (window.MLXImagePreview) return;
    const selector = '.message-attachment-preview, .image-artifact-preview, .image-variant-preview';
    let dialog, preview, heading, closeButton, previousFocus;
    const text = (key, fallback) => window.MLXI18n?.t('rendering.' + key, fallback) ?? fallback;

    function refreshLabels() {
        if (!dialog) return;
        heading.textContent = text('image_preview_title', 'Image preview');
        closeButton.setAttribute('aria-label', text('image_preview_close', 'Close image preview'));
    }

    function open(image) {
        if (!image?.src) return;
        if (!dialog) {
            dialog = document.createElement('dialog');
            dialog.className = 'image-preview-dialog';
            dialog.setAttribute('aria-labelledby', 'imagePreviewTitle');
            const header = document.createElement('header');
            heading = document.createElement('strong');
            heading.id = 'imagePreviewTitle';
            closeButton = document.createElement('button');
            closeButton.type = 'button';
            closeButton.className = 'message-action-btn';
            closeButton.textContent = '×';
            closeButton.addEventListener('click', () => dialog.close());
            header.append(heading, closeButton);
            preview = document.createElement('img');
            dialog.append(header, preview);
            dialog.addEventListener('click', event => {
                if (event.target === dialog) dialog.close();
            });
            dialog.addEventListener('close', () => {
                document.body.classList.remove('image-preview-open');
                preview.removeAttribute('src');
                if (previousFocus?.isConnected) previousFocus.focus();
            });
            document.body.appendChild(dialog);
        }
        preview.src = image.currentSrc || image.src;
        preview.alt = image.alt || '';
        refreshLabels();
        if (!dialog.open) {
            previousFocus = image.closest('.image-variant-preview-link') || image;
            dialog.showModal();
            document.body.classList.add('image-preview-open');
            closeButton.focus();
        }
    }

    document.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const image = event.target.closest?.(selector) ||
            event.target.closest?.('.image-variant-preview-link')?.querySelector(selector);
        if (!image) return;
        event.preventDefault();
        open(image);
    });
    document.addEventListener('keydown', event => {
        if (!['Enter', ' '].includes(event.key)) return;
        const image = event.target.matches?.(selector) ? event.target :
            event.target.matches?.('.image-variant-preview-link') ? event.target.querySelector('.image-variant-preview') : null;
        if (!image) return;
        event.preventDefault();
        open(image);
    });
    document.addEventListener('mlx-language-changed', refreshLabels);
    window.MLXImagePreview = { open };
})();
