(() => {
    'use strict';

    const MODAL_ID = 'talkingPhotoModal';
    const IMAGE_INPUT_ID = 'talkingPhotoImage';
    const BUTTON_ID = 'talkingPhotoClipboardButton';
    const HINT_ID = 'talkingPhotoClipboardHint';
    const STYLE_ID = 'talkingPhotoClipboardStyles';
    const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

    function language() {
        return (
            document.documentElement.lang ||
            window.I18n?.currentLanguage ||
            navigator.language ||
            'de'
        ).toLowerCase();
    }

    function localText(de, en) {
        return language().startsWith('de') ? de : en;
    }

    function installStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            .mlx-talking-photo-clipboard {
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: wrap;
                margin: -4px 0 12px;
            }
            .mlx-talking-photo-clipboard button {
                border: 1px solid rgba(148,163,184,.24);
                border-radius: 10px;
                padding: 8px 12px;
                background: #17263a;
                color: inherit;
                cursor: pointer;
                font: inherit;
            }
            .mlx-talking-photo-clipboard button:hover {
                background: #1f3350;
            }
            .mlx-talking-photo-clipboard-hint {
                font-size: .78rem;
                opacity: .7;
                line-height: 1.35;
            }
        `;
        document.head.append(style);
    }

    function setHint(message, isError = false) {
        const hint = document.getElementById(HINT_ID);
        if (!hint) return;
        hint.textContent = message;
        hint.style.opacity = isError ? '1' : '.7';
    }

    async function convertToPng(blob) {
        if (!blob.type.startsWith('image/')) {
            throw new Error(localText(
                'Die Zwischenablage enthält kein Bild.',
                'The clipboard does not contain an image.',
            ));
        }

        if (blob.type === 'image/png' || blob.type === 'image/jpeg') {
            const extension = blob.type === 'image/png' ? 'png' : 'jpg';
            return new File([blob], `clipboard-image.${extension}`, {type: blob.type});
        }

        if (typeof createImageBitmap !== 'function') {
            throw new Error(localText(
                'Dieses Bildformat kann im Browser nicht in PNG umgewandelt werden.',
                'This image format cannot be converted to PNG in this browser.',
            ));
        }

        const bitmap = await createImageBitmap(blob);
        try {
            const canvas = document.createElement('canvas');
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
            const context = canvas.getContext('2d');
            if (!context) throw new Error('Canvas unavailable');
            context.drawImage(bitmap, 0, 0);
            const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
            if (!png) throw new Error('PNG conversion failed');
            return new File([png], 'clipboard-image.png', {type: 'image/png'});
        } finally {
            bitmap.close?.();
        }
    }

    async function normalizeImage(blob) {
        const file = await convertToPng(blob);
        if (!file.size) {
            throw new Error(localText('Das Bild ist leer.', 'The image is empty.'));
        }
        if (file.size > MAX_IMAGE_BYTES) {
            throw new Error(localText(
                'Das Bild aus der Zwischenablage ist größer als 10 MB.',
                'The clipboard image is larger than 10 MB.',
            ));
        }
        return file;
    }

    function applyImage(file) {
        const input = document.getElementById(IMAGE_INPUT_ID);
        if (!input) {
            throw new Error(localText(
                'Das Talking-Photo-Bildfeld wurde nicht gefunden.',
                'The Talking Photo image field was not found.',
            ));
        }

        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', {bubbles: true}));
        setHint(localText(
            'Bild aus der Zwischenablage übernommen. Du kannst es mit ⌘V jederzeit ersetzen.',
            'Clipboard image added. You can replace it at any time with Ctrl/Cmd+V.',
        ));
    }

    async function readClipboardImage() {
        if (!navigator.clipboard?.read) {
            throw new Error(localText(
                'Direktes Lesen der Zwischenablage wird hier nicht unterstützt. Klicke ins Talking-Photo-Fenster und drücke ⌘V.',
                'Direct clipboard access is not supported here. Click the Talking Photo window and press Ctrl/Cmd+V.',
            ));
        }

        const items = await navigator.clipboard.read();
        for (const item of items) {
            const imageType = item.types.find(type => type.startsWith('image/'));
            if (!imageType) continue;
            return normalizeImage(await item.getType(imageType));
        }
        throw new Error(localText(
            'In der Zwischenablage wurde kein Bild gefunden.',
            'No image was found in the clipboard.',
        ));
    }

    async function pasteFromButton() {
        const button = document.getElementById(BUTTON_ID);
        if (button) button.disabled = true;
        try {
            setHint(localText(
                'Zwischenablage wird gelesen …',
                'Reading clipboard …',
            ));
            applyImage(await readClipboardImage());
        } catch (error) {
            setHint(error?.message || String(error), true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function handlePaste(event) {
        const modal = document.getElementById(MODAL_ID);
        if (!modal || modal.hidden) return;

        const items = Array.from(event.clipboardData?.items || []);
        const imageItem = items.find(item => item.kind === 'file' && item.type.startsWith('image/'));
        if (!imageItem) return;

        const blob = imageItem.getAsFile();
        if (!blob) return;

        event.preventDefault();
        try {
            applyImage(await normalizeImage(blob));
        } catch (error) {
            setHint(error?.message || String(error), true);
        }
    }

    function decorateModal(modal) {
        if (!modal || modal.querySelector(`#${BUTTON_ID}`)) return;
        const imageInput = modal.querySelector(`#${IMAGE_INPUT_ID}`);
        const imageLabel = imageInput?.closest('label');
        if (!imageInput || !imageLabel) return;

        installStyles();

        const controls = document.createElement('div');
        controls.className = 'mlx-talking-photo-clipboard';

        const button = document.createElement('button');
        button.id = BUTTON_ID;
        button.type = 'button';
        button.textContent = localText(
            '📋 Aus Zwischenablage einfügen',
            '📋 Paste from clipboard',
        );
        button.addEventListener('click', pasteFromButton);

        const hint = document.createElement('div');
        hint.id = HINT_ID;
        hint.className = 'mlx-talking-photo-clipboard-hint';
        hint.textContent = localText(
            'Oder einfach im Talking-Photo-Fenster ⌘V drücken.',
            'Or simply press Ctrl/Cmd+V while the Talking Photo window is open.',
        );

        controls.append(button, hint);
        imageLabel.insertAdjacentElement('afterend', controls);
    }

    function scan() {
        decorateModal(document.getElementById(MODAL_ID));
    }

    document.addEventListener('paste', handlePaste);

    const observer = new MutationObserver(scan);
    observer.observe(document.documentElement, {childList: true, subtree: true});
    scan();
})();
