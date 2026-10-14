/* Local before/after comparator for successful Nobby image edits.
 * Reads only the existing authenticated image endpoint, never file paths.
 */
(() => {
    if (window.MLXImageCompare) return;
    const ID = /^\d{10}-[0-9a-f]{12}$/;
    let dialog = null;
    let before = null;
    let after = null;
    let range = null;
    let earlierFocus = null;

    function label(key, english) {
        return window.MLXI18n?.t('rendering.' + key, english) ?? english;
    }

    function imageUrl(id) {
        return ID.test(String(id || '')) ? '/api/mlx/images/' + encodeURIComponent(id) : null;
    }

    function updateRatio(value) {
        if (!before || !range) return;
        const amount = Math.min(100, Math.max(0, Number(value) || 0));
        range.value = String(amount);
        before.style.clipPath = 'inset(0 ' + (100 - amount) + '% 0 0)';
    }

    function ensureDialog() {
        if (dialog) return;
        dialog = document.createElement('dialog');
        dialog.className = 'image-compare-dialog';
        dialog.setAttribute('aria-labelledby', 'imageCompareTitle');

        const header = document.createElement('header');
        const heading = document.createElement('strong');
        heading.id = 'imageCompareTitle';
        heading.textContent = label('image_compare_title', 'Before / after');

        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'message-action-btn';
        close.textContent = '×';
        close.setAttribute('aria-label', label('image_preview_close', 'Close image preview'));
        close.addEventListener('click', () => dialog.close());
        header.append(heading, close);

        const stage = document.createElement('div');
        stage.className = 'image-compare-stage';

        after = document.createElement('img');
        after.className = 'image-compare-after';
        after.alt = label('image_compare_after', 'Edited image');
        before = document.createElement('img');
        before.className = 'image-compare-before';
        before.alt = label('image_compare_before', 'Original image');
        stage.append(after, before);

        const controls = document.createElement('label');
        controls.className = 'image-compare-controls';
        const labelText = document.createElement('span');
        labelText.textContent = label('image_compare_label', 'Move to reveal the original image');
        range = document.createElement('input');
        range.type = 'range';
        range.min = '0';
        range.max = '100';
        range.value = '50';
        range.setAttribute('aria-label', label('image_compare_slider', 'Original image visibility'));
        range.addEventListener('input', () => updateRatio(range.value));
        controls.append(labelText, range);

        dialog.append(header, stage, controls);
        dialog.addEventListener('click', event => {
            if (event.target === dialog) dialog.close();
        });
        dialog.addEventListener('close', () => {
            document.body.classList.remove('image-preview-open');
            before.removeAttribute('src');
            after.removeAttribute('src');
            if (earlierFocus?.isConnected) earlierFocus.focus();
        });
        document.body.appendChild(dialog);
    }

    function open({ beforeId, afterId, width, height } = {}, trigger = null) {
        const left = imageUrl(beforeId);
        const right = imageUrl(afterId);
        if (!left || !right || beforeId === afterId) return false;
        ensureDialog();
        earlierFocus = trigger || document.activeElement;
        const stage = dialog.querySelector('.image-compare-stage');
        const w = Number(width), h = Number(height);
        const ratio = Number.isFinite(w) && Number.isFinite(h) &&
            w >= 256 && h >= 256 && w <= 4096 && h <= 4096 ? w / h : 1;
        stage.style.aspectRatio = String(ratio);
        // Keep the entire image visible for portrait and landscape references.
        stage.style.width = 'min(100%, ' + (67 * ratio).toFixed(2) + 'dvh)';
        before.src = left;
        after.src = right;
        updateRatio(50);
        if (!dialog.open) {
            dialog.showModal();
            document.body.classList.add('image-preview-open');
        }
        range.focus();
        return true;
    }

    document.addEventListener('mlx-language-changed', () => {
        if (!dialog) return;
        dialog.querySelector('#imageCompareTitle').textContent = label('image_compare_title', 'Before / after');
        dialog.querySelector('.image-compare-controls span').textContent = label('image_compare_label', 'Move to reveal the original image');
        range.setAttribute('aria-label', label('image_compare_slider', 'Original image visibility'));
        before.alt = label('image_compare_before', 'Original image');
        after.alt = label('image_compare_after', 'Edited image');
    });
    window.MLXImageCompare = { open, imageUrl };
})();
