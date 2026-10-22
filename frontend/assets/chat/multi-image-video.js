(function () {
    'use strict';
    const host = document.getElementById('multiImageVideo');
    if (!host) return;
    const localText = (de, en) => String(window.MLXI18n?.getLanguage?.() || document.documentElement.lang).startsWith('de') ? de : en;
    let images = [], dragged = null, epoch = 0, busy = false, modeTouched = false;
    const urls = new Set();
    const node = (tag, text, cls) => {
        const el = document.createElement(tag);
        if (text) el.textContent = text;
        if (cls) el.className = cls;
        return el;
    };
    const enabled = node('input'); enabled.type = 'checkbox'; enabled.id = 'multiVideoEnabled';
    const heading = node('label', '', 'multi-video-heading');
    heading.append(enabled, node('strong', 'Multi-Image-to-Video'), node('small', '2–5'));
    const body = node('div', '', 'multi-video-body'); body.hidden = true;
    const mode = node('select'); mode.id = 'multiVideoMode';
    const keyframes = node('option'); keyframes.value = 'keyframes'; keyframes.disabled = true;
    const scenes = node('option'); scenes.value = 'scenes';
    mode.append(keyframes, scenes); mode.value = 'scenes';
    const hint = node('p', '', 'multi-video-hint');
    const list = node('div', '', 'multi-video-images'); list.id = 'multiVideoImages';
    const drop = node('label', '', 'multi-video-drop');
    const fileInput = node('input'); fileInput.type = 'file'; fileInput.multiple = true;
    fileInput.accept = 'image/png,image/jpeg,image/webp'; fileInput.id = 'multiVideoFiles';
    const dropText = node('span'); drop.append(dropText, fileInput);
    const libraryButton = node('button'); libraryButton.type = 'button';
    const library = node('div', '', 'multi-video-library'); library.hidden = true;
    const promptLabel = node('label');
    const prompt = node('textarea'); prompt.id = 'multiVideoPrompt'; prompt.maxLength = 4000; prompt.rows = 2;
    promptLabel.append(node('span', 'Videoprompt'), prompt);
    const error = node('p', '', 'multi-video-error'); error.setAttribute('role', 'alert');
    body.append(mode, hint, list, drop, libraryButton, library, promptLabel, error);
    host.append(heading, body);
    enabled.addEventListener('change', () => { body.hidden = !enabled.checked; });
    function revoke(item) {
        if (urls.delete(item.preview)) URL.revokeObjectURL(item.preview);
    }
    function status() {
        hint.textContent = mode.value === 'keyframes'
            ? localText('Ein Clip · Bilder als zeitliche Anker von Start bis Ende. Spätere Anker führen die Bewegung; pixelgenaue Bildtreue ist nicht garantiert.',
                 'One clip · images anchor time from start to end. Later anchors guide motion; exact image reproduction is not guaranteed.')
            : localText('Ein Segment je Bild · Dauer je Szene wie oben gewählt · Audio wird verbunden. Fertige Szenen bleiben bei Fehlern für Fortsetzen erhalten.',
                 'One segment per image · duration per scene as selected above · audio is joined. Completed scenes are retained for retry after a failure.');
    }
    function move(from, to) {
        if (from === to || to < 0 || to >= images.length) return;
        images.splice(to, 0, images.splice(from, 1)[0]); render();
    }
    function render() {
        list.replaceChildren();
        images.forEach((item, index) => {
            const card = node('div', '', 'multi-video-image'); card.draggable = true; card.tabIndex = 0;
            card.dataset.index = String(index);
            const img = node('img'); img.src = item.preview; img.alt = item.name || `${index + 1}`;
            const number = node('span', `${index + 1} · ${mode.value === 'keyframes' ? Math.round(index * 100 / Math.max(1, images.length - 1)) + '%' : localText('Szene', 'Scene')}`, 'multi-video-number');
            const controls = node('div', '', 'multi-video-image-actions');
            const button = (label, action) => {
                const el = node('button', label); el.type = 'button'; el.addEventListener('click', action); controls.append(el); return el;
            };
            button('←', () => move(index, index - 1)).setAttribute('aria-label', localText('Nach links', 'Move left'));
            button('→', () => move(index, index + 1)).setAttribute('aria-label', localText('Nach rechts', 'Move right'));
            const replace = node('input'); replace.type = 'file'; replace.accept = fileInput.accept; replace.hidden = true;
            replace.addEventListener('change', () => void addFiles(replace.files, index));
            button(localText('Ersetzen', 'Replace'), () => replace.click());
            button('×', () => { revoke(item); images.splice(index, 1); render(); }).setAttribute('aria-label', localText('Bild entfernen', 'Remove image'));
            card.addEventListener('dragstart', event => { dragged = index; event.dataTransfer.setData('text/plain', String(index)); });
            card.addEventListener('dragend', () => { dragged = null; });
            card.addEventListener('dragover', event => event.preventDefault());
            card.addEventListener('drop', event => {
                event.preventDefault(); event.stopPropagation();
                if (dragged !== null) move(dragged, index);
                dragged = null;
            });
            card.addEventListener('keydown', event => {
                if (event.altKey && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
                    event.preventDefault(); move(index, index + (event.key === 'ArrowLeft' ? -1 : 1));
                }
            });
            card.append(img, number, controls, replace); list.append(card);
        });
        status();
    }
    async function addFiles(files, replaceIndex = null) {
        if (busy) return;
        const replaced = replaceIndex === null ? null : images[replaceIndex];
        const incoming = Array.from(files || []);
        if (incoming.some(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type))) {
            error.textContent = localText('Bitte PNG, JPEG oder WebP auswählen.', 'Choose PNG, JPEG or WebP images.'); return;
        }
        if (replaceIndex === null && images.length + incoming.length > 5) {
            error.textContent = localText('Maximal 5 Bilder.', 'Maximum 5 images.'); return;
        }
        const current = epoch;
        busy = true; error.textContent = localText('Bilder werden hochgeladen …', 'Uploading images …');
        try {
            for (const file of incoming) {
                const item = {file, kind: 'image', name: file.name};
                const uploaded = await window.MLXChatAttachments.uploadImageAttachments([item]);
                if (current !== epoch) return;
                if (!uploaded[0]?.upload?.path) throw new Error(localText('Upload fehlgeschlagen', 'Upload failed'));
                const preview = URL.createObjectURL(file); urls.add(preview);
                const value = {name: file.name, stored_path: uploaded[0].upload.path, preview};
                if (replaceIndex !== null) {
                    const currentIndex = images.indexOf(replaced);
                    if (currentIndex < 0) { revoke(value); continue; }
                    revoke(replaced); images[currentIndex] = value;
                }
                else images.push(value);
            }
            error.textContent = ''; render();
        } catch (failure) { if (current === epoch) error.textContent = failure.message; }
        finally { busy = false; fileInput.value = ''; }
    }
    fileInput.addEventListener('change', () => void addFiles(fileInput.files));
    drop.addEventListener('dragover', event => event.preventDefault());
    drop.addEventListener('drop', event => { event.preventDefault(); event.stopPropagation(); void addFiles(event.dataTransfer.files); });
    mode.addEventListener('change', () => { modeTouched = true; render(); });
    libraryButton.addEventListener('click', async () => {
        library.hidden = !library.hidden;
        if (library.hidden) return;
        const current = epoch;
        try {
            const response = await fetch('/api/library/assets?kind=image&limit=100');
            if (!response.ok) throw new Error(localText('Bibliothek nicht erreichbar', 'Library unavailable'));
            const data = await response.json();
            if (current !== epoch) return;
            library.replaceChildren();
            for (const asset of (data.assets || []).filter(item => item.kind === 'image')) {
                const button = node('button'); button.type = 'button';
                const img = node('img'); img.src = asset.url; img.alt = asset.id; img.loading = 'lazy';
                button.append(img); button.setAttribute('aria-label', asset.id);
                button.addEventListener('click', () => {
                    if (images.length >= 5) { error.textContent = localText('Maximal 5 Bilder.', 'Maximum 5 images.'); return; }
                    images.push({artifact_id: 'image-' + asset.id, preview: asset.url, name: asset.id}); render();
                }); library.append(button);
            }
            if (!library.children.length) library.textContent = localText('Keine Bilder vorhanden.', 'No images available.');
        } catch (failure) { error.textContent = failure.message; }
    });
    window.MLXMultiImageVideo = {
        configure(kind, sources, originalPrompt) {
            ++epoch;
            for (const item of images) revoke(item);
            images = []; host.hidden = kind !== 'video';
            if (host.hidden) return;
            for (const source of (sources || []).slice(0, 5)) {
                if (!source.stored_path) continue;
                const preview = source.dataUrl || source.data_url || source.preview || (source.file ? URL.createObjectURL(source.file) : null);
                if (preview?.startsWith('blob:')) urls.add(preview);
                if (preview) images.push({stored_path: source.stored_path, name: source.name, preview});
            }
            enabled.checked = images.length >= 2; body.hidden = !enabled.checked;
            keyframes.textContent = localText('A · Keyframe-Animation', 'A · Keyframe animation');
            scenes.textContent = localText('B · Szenen verbinden', 'B · Join scenes');
            dropText.textContent = localText('Bilder auswählen oder hier ablegen', 'Choose images or drop them here');
            libraryButton.textContent = localText('Aus Medienbibliothek hinzufügen', 'Add from media library');
            promptLabel.firstChild.textContent = localText('Videoprompt', 'Video prompt');
            mode.setAttribute('aria-label', localText('Generierungsmodus', 'Generation mode'));
            prompt.value = originalPrompt || ''; error.textContent = ''; library.hidden = true;
            keyframes.disabled = true; mode.value = 'scenes'; modeTouched = false; render();
            const current = epoch;
            fetch('/api/mlx/video/models').then(response => response.ok ? response.json() : {}).then(data => {
                if (current !== epoch) return;
                keyframes.disabled = !data.multi_image?.native_keyframes;
                if (!keyframes.disabled && !modeTouched) mode.value = 'keyframes';
                render();
            }).catch(() => {});
        },
        selection(quality) {
            if (host.hidden || !enabled.checked) return null;
            if (busy) throw new Error(localText('Bitte Upload abwarten.', 'Wait for the upload to finish.'));
            if (images.length < 2 || images.length > 5) throw new Error(localText('Bitte 2–5 Bilder auswählen.', 'Select 2–5 images.'));
            if (quality === 'preview') throw new Error(localText('Für Multi-Image bitte Fast, Standard oder Qualität wählen.', 'Choose Fast, Standard or Quality for multi-image video.'));
            if (mode.value === 'keyframes' && keyframes.disabled) throw new Error(localText('Native Keyframes nicht verfügbar.', 'Native keyframes unavailable.'));
            if (prompt.value.trim().length < 3) throw new Error(localText('Bitte Videoprompt eingeben.', 'Enter a video prompt.'));
            error.textContent = '';
            return {multi_image_mode: mode.value, multi_images: images.map(item => item.artifact_id
                ? {artifact_id: item.artifact_id} : {stored_path: item.stored_path}), prompt: prompt.value.trim()};
        },
        showError(message) { error.textContent = message; }
    };
})();
