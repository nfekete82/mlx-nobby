function notesT(key, fallback = '', variables = {}) {
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

(function () {

    let notes = [];
    let folders = [];

    let folderSelect = null;
    let editingNoteId = null;
    let selectedNoteId = null;
    let searchTerm = '';
    let dragPayload = null;
    let contextMenu = null;

    const panel =
        document.getElementById('notesPanel');

    const list =
        document.getElementById('notesList');

    const nameInput =
        document.getElementById('noteName');

    const contentInput =
        document.getElementById('noteContent');

    const saveButton =
        document.getElementById('noteSave');


    function escapeHtml(value) {
        return String(value || '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }


    async function api(url, options = {}) {
        const response = await fetch(url, options);

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text);
        }

        return response.json();
    }


    function jsonOptions(method, body) {
        return {
            method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        };
    }


    function getFolder(id) {
        return folders.find(
            folder => folder.id === id
        );
    }


    function getNote(id) {
        return notes.find(
            note => note.id === id
        );
    }

    // MLX-NOBBY-NOTES-BROWSER-V2

    function folderBreadcrumb(folderId) {

        if (!folderId) {
            return notesT(
                'notes.no_folder',
                'Ohne Ordner'
            );
        }

        const parts = [];
        const seen = new Set();

        let folder =
            getFolder(folderId);

        while (
            folder &&
            !seen.has(folder.id)
        ) {
            seen.add(folder.id);
            parts.push(folder.name);

            folder =
                folder.parent_id
                    ? getFolder(folder.parent_id)
                    : null;
        }

        return parts.length
            ? parts.reverse().join(' / ')
            : notesT(
                'notes.no_folder',
                'Ohne Ordner'
            );
    }



    // MLX-NOBBY-NOTES-POLISH-V1

    function normalizeNoteSearch(value) {
        return String(value || '')
            .normalize('NFKD')
            .toLocaleLowerCase('de');
    }


    function noteMatchesSearch(note) {

        if (!searchTerm) {
            return true;
        }

        const haystack =
            normalizeNoteSearch(
                [
                    note.name || '',
                    note.content || ''
                ].join('\n')
            );

        return haystack.includes(
            searchTerm
        );
    }


    function folderMatchesSearch(
        folder,
        seen = new Set()
    ) {

        if (!searchTerm) {
            return true;
        }

        if (
            !folder ||
            seen.has(folder.id)
        ) {
            return false;
        }

        seen.add(folder.id);


        if (
            normalizeNoteSearch(
                folder.name
            ).includes(searchTerm)
        ) {
            return true;
        }


        if (
            folderNotes(folder.id)
                .some(noteMatchesSearch)
        ) {
            return true;
        }


        return childFolders(folder.id)
            .some(child =>
                folderMatchesSearch(
                    child,
                    new Set(seen)
                )
            );
    }


    function rememberSelectedNoteId(id) {

        try {
            if (id) {
                localStorage.setItem(
                    'mlxNotesSelectedId',
                    String(id)
                );
            } else {
                localStorage.removeItem(
                    'mlxNotesSelectedId'
                );
            }
        } catch (error) {
            console.debug(
                'Could not persist selected note.',
                error
            );
        }
    }


    function restoreSelectedNoteId() {

        if (selectedNoteId) {
            return;
        }

        try {
            const saved =
                localStorage.getItem(
                    'mlxNotesSelectedId'
                );

            if (
                saved &&
                getNote(saved)
            ) {
                selectedNoteId =
                    saved;
            }
        } catch (error) {
            console.debug(
                'Could not restore selected note.',
                error
            );
        }
    }


    function initNotesSearch() {

        const input =
            document.getElementById(
                'notesSearch'
            );

        const clearButton =
            document.getElementById(
                'notesSearchClear'
            );

        if (
            !input ||
            !clearButton
        ) {
            return;
        }


        const updateClearButton =
            () => {

                clearButton.hidden =
                    !input.value;
            };


        input.addEventListener(
            'input',
            () => {

                searchTerm =
                    normalizeNoteSearch(
                        input.value.trim()
                    );

                updateClearButton();

                renderNotes();
            }
        );


        clearButton.addEventListener(
            'click',
            () => {

                input.value = '';
                searchTerm = '';

                updateClearButton();

                renderNotes();

                input.focus();
            }
        );


        input.addEventListener(
            'keydown',
            event => {

                if (
                    event.key ===
                    'Escape' &&
                    input.value
                ) {
                    event.preventDefault();
                    event.stopPropagation();

                    input.value = '';
                    searchTerm = '';

                    updateClearButton();

                    renderNotes();
                }
            }
        );
    }


    function initSidebarResize() {

        const browser =
            panel.querySelector(
                '.notes-browser'
            );

        const sidebar =
            panel.querySelector(
                '.notes-sidebar'
            );

        const resizer =
            document.getElementById(
                'notesSidebarResizer'
            );

        if (
            !browser ||
            !sidebar ||
            !resizer
        ) {
            return;
        }


        const MIN_WIDTH = 240;
        const MAX_WIDTH = 480;
        const DEFAULT_WIDTH = 300;


        const clamp =
            value =>
                Math.min(
                    MAX_WIDTH,
                    Math.max(
                        MIN_WIDTH,
                        value
                    )
                );


        const applyWidth =
            width => {

                browser.style.setProperty(
                    '--notes-sidebar-width',
                    clamp(width) + 'px'
                );
            };


        try {

            const saved =
                Number(
                    localStorage.getItem(
                        'mlxNotesSidebarWidth'
                    )
                );

            if (Number.isFinite(saved)) {
                applyWidth(saved);
            }

        } catch (error) {
            console.debug(
                'Could not restore sidebar width.',
                error
            );
        }


        let active = false;
        let startX = 0;
        let startWidth = 0;


        const stopResize =
            () => {

                if (!active) {
                    return;
                }

                active = false;

                document.body.classList.remove(
                    'notes-resizing'
                );

                const width =
                    sidebar.getBoundingClientRect()
                        .width;

                try {
                    localStorage.setItem(
                        'mlxNotesSidebarWidth',
                        String(
                            Math.round(width)
                        )
                    );
                } catch (error) {
                    console.debug(
                        'Could not persist sidebar width.',
                        error
                    );
                }
            };


        resizer.addEventListener(
            'pointerdown',
            event => {

                if (
                    window.matchMedia(
                        '(max-width: 760px)'
                    ).matches
                ) {
                    return;
                }

                active = true;

                startX =
                    event.clientX;

                startWidth =
                    sidebar
                        .getBoundingClientRect()
                        .width;

                document.body.classList.add(
                    'notes-resizing'
                );

                event.preventDefault();
            }
        );


        window.addEventListener(
            'pointermove',
            event => {

                if (!active) {
                    return;
                }

                const width =
                    startWidth +
                    (
                        event.clientX -
                        startX
                    );

                applyWidth(width);
            }
        );


        window.addEventListener(
            'pointerup',
            stopResize
        );


        window.addEventListener(
            'pointercancel',
            stopResize
        );


        resizer.addEventListener(
            'dblclick',
            () => {

                applyWidth(
                    DEFAULT_WIDTH
                );

                try {
                    localStorage.removeItem(
                        'mlxNotesSidebarWidth'
                    );
                } catch (error) {
                    console.debug(
                        'Could not reset sidebar width.',
                        error
                    );
                }
            }
        );
    }



    // MLX-NOBBY-NOTES-CONFIRM-MODAL-V1

    function notesConfirm({
        title = 'Löschen?',
        message = '',
        confirmLabel = 'Löschen',
        cancelLabel = 'Abbrechen'
    } = {}) {

        return new Promise(resolve => {

            const existing =
                document.querySelector(
                    '.notes-confirm-overlay'
                );

            if (existing) {
                existing.remove();
            }


            const previousFocus =
                document.activeElement;


            const overlay =
                document.createElement('div');

            overlay.className =
                'notes-confirm-overlay';


            const dialog =
                document.createElement('div');

            dialog.className =
                'notes-confirm-dialog';

            dialog.setAttribute(
                'role',
                'alertdialog'
            );

            dialog.setAttribute(
                'aria-modal',
                'true'
            );


            const icon =
                document.createElement('div');

            icon.className =
                'notes-confirm-icon';

            icon.innerHTML = `
                <svg
                    width="22"
                    height="22"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                >
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6l-1 14H6L5 6"></path>
                    <path d="M10 11v6"></path>
                    <path d="M14 11v6"></path>
                    <path d="M9 6V4h6v2"></path>
                </svg>
            `;


            const copy =
                document.createElement('div');

            copy.className =
                'notes-confirm-copy';


            const heading =
                document.createElement('h3');

            heading.className =
                'notes-confirm-title';

            heading.textContent =
                title;


            const text =
                document.createElement('p');

            text.className =
                'notes-confirm-message';

            text.textContent =
                message;


            copy.appendChild(
                heading
            );

            copy.appendChild(
                text
            );


            const head =
                document.createElement('div');

            head.className =
                'notes-confirm-head';

            head.appendChild(
                icon
            );

            head.appendChild(
                copy
            );


            const actions =
                document.createElement('div');

            actions.className =
                'notes-confirm-actions';


            const cancelButton =
                document.createElement('button');

            cancelButton.type =
                'button';

            cancelButton.className =
                'notes-confirm-cancel';

            cancelButton.textContent =
                cancelLabel;


            const confirmButton =
                document.createElement('button');

            confirmButton.type =
                'button';

            confirmButton.className =
                'notes-confirm-delete';

            confirmButton.textContent =
                confirmLabel;


            actions.appendChild(
                cancelButton
            );

            actions.appendChild(
                confirmButton
            );


            dialog.appendChild(
                head
            );

            dialog.appendChild(
                actions
            );

            overlay.appendChild(
                dialog
            );

            document.body.appendChild(
                overlay
            );


            let finished = false;


            const cleanup =
                result => {

                    if (finished) {
                        return;
                    }

                    finished = true;

                    document.removeEventListener(
                        'keydown',
                        onKeyDown,
                        true
                    );

                    overlay.classList.add(
                        'is-closing'
                    );

                    window.setTimeout(
                        () => {
                            overlay.remove();

                            if (
                                previousFocus &&
                                typeof previousFocus.focus ===
                                'function'
                            ) {
                                previousFocus.focus();
                            }

                            resolve(result);
                        },
                        120
                    );
                };


            const onKeyDown =
                event => {

                    if (
                        event.key ===
                        'Escape'
                    ) {
                        event.preventDefault();
                        event.stopPropagation();

                        cleanup(false);
                    }

                    if (
                        event.key ===
                        'Enter' &&
                        document.activeElement ===
                        confirmButton
                    ) {
                        event.preventDefault();

                        cleanup(true);
                    }
                };


            cancelButton.addEventListener(
                'click',
                () => cleanup(false)
            );


            confirmButton.addEventListener(
                'click',
                () => cleanup(true)
            );


            overlay.addEventListener(
                'click',
                event => {

                    if (
                        event.target ===
                        overlay
                    ) {
                        cleanup(false);
                    }
                }
            );


            dialog.addEventListener(
                'click',
                event =>
                    event.stopPropagation()
            );


            document.addEventListener(
                'keydown',
                onKeyDown,
                true
            );


            requestAnimationFrame(
                () => {

                    overlay.classList.add(
                        'is-visible'
                    );

                    cancelButton.focus();
                }
            );
        });
    }


    function showPreviewMode() {

        const preview =
            document.getElementById(
                'notePreview'
            );

        const editor =
            document.getElementById(
                'noteEditor'
            );

        if (preview) {
            preview.hidden = false;
        }

        if (editor) {
            editor.hidden = true;
        }
    }


    function showEditorMode() {

        const preview =
            document.getElementById(
                'notePreview'
            );

        const editor =
            document.getElementById(
                'noteEditor'
            );

        if (preview) {
            preview.hidden = true;
        }

        if (editor) {
            editor.hidden = false;
        }
    }


    function selectNote(note) {

        if (!note) {
            return;
        }

        selectedNoteId =
            note.id;

        rememberSelectedNoteId(
            note.id
        );

        showPreviewMode();
        renderNotes();
    }


    function renderPreview() {

        const preview =
            document.getElementById(
                'notePreview'
            );

        if (!preview) {
            return;
        }

        const note =
            getNote(selectedNoteId);

        preview.innerHTML = '';

        if (!note) {

            const empty =
                document.createElement('div');

            empty.className =
                'note-preview-empty';

            const icon =
                document.createElement('div');

            icon.className =
                'note-preview-empty-icon';

            icon.textContent = '📝';

            const title =
                document.createElement('strong');

            title.textContent =
                'Notiz auswählen';

            const text =
                document.createElement('span');

            text.textContent =
                'Wähle links eine Notiz aus oder erstelle eine neue.';

            empty.appendChild(icon);
            empty.appendChild(title);
            empty.appendChild(text);

            preview.appendChild(empty);

            return;
        }


        const wrapper =
            document.createElement('div');

        wrapper.className =
            'note-preview-document';


        const header =
            document.createElement('div');

        header.className =
            'note-preview-header';


        const headerCopy =
            document.createElement('div');

        headerCopy.className =
            'note-preview-header-copy';


        const breadcrumb =
            document.createElement('div');

        breadcrumb.className =
            'note-preview-path';

        breadcrumb.textContent =
            folderBreadcrumb(
                note.folder_id
            );


        const title =
            document.createElement('h2');

        title.className =
            'note-preview-title';

        title.textContent =
            note.name || 'Notiz';


        headerCopy.appendChild(
            breadcrumb
        );

        headerCopy.appendChild(
            title
        );


        const menu =
            document.createElement('button');

        menu.type = 'button';
        menu.className =
            'note-preview-menu';

        menu.textContent = '⋯';

        menu.title = 'Weitere Aktionen';

        menu.addEventListener(
            'click',
            event =>
                showContextMenu(
                    event,
                    [
                        {
                            label:
                                notesT(
                                    'notes.insert_chat',
                                    'In Chat einfügen'
                                ),
                            action:
                                () =>
                                    insertIntoChat(
                                        note
                                    )
                        },
                        {
                            label:
                                notesT(
                                    'notes.edit',
                                    'Bearbeiten'
                                ),
                            action:
                                () =>
                                    editNote(
                                        note
                                    )
                        },
                        {
                            separator: true
                        },
                        {
                            label:
                                notesT(
                                    'notes.delete',
                                    'Löschen'
                                ),
                            danger: true,
                            action:
                                () =>
                                    deleteNote(
                                        note
                                    )
                        }
                    ]
                )
        );


        header.appendChild(
            headerCopy
        );

        header.appendChild(
            menu
        );


        const content =
            document.createElement('div');

        content.className =
            'note-preview-content';

        content.textContent =
            note.content || '';


        const actions =
            document.createElement('div');

        actions.className =
            'note-preview-actions';


        const insertButton =
            document.createElement('button');

        insertButton.type =
            'button';

        insertButton.className =
            'notes-primary-button';

        insertButton.textContent =
            notesT(
                'notes.insert',
                'Einfügen'
            );

        insertButton.addEventListener(
            'click',
            () =>
                insertIntoChat(
                    note
                )
        );


        const editButton =
            document.createElement('button');

        editButton.type =
            'button';

        editButton.className =
            'notes-secondary-button';

        editButton.textContent =
            notesT(
                'notes.edit',
                'Bearbeiten'
            );

        editButton.addEventListener(
            'click',
            () =>
                editNote(
                    note
                )
        );


        const deleteButton =
            document.createElement('button');

        deleteButton.type =
            'button';

        deleteButton.className =
            'notes-danger-button';

        deleteButton.textContent =
            notesT(
                'notes.delete',
                'Löschen'
            );

        deleteButton.addEventListener(
            'click',
            () =>
                deleteNote(
                    note
                )
        );


        actions.appendChild(
            insertButton
        );

        actions.appendChild(
            editButton
        );

        actions.appendChild(
            deleteButton
        );


        wrapper.appendChild(
            header
        );

        wrapper.appendChild(
            content
        );

        wrapper.appendChild(
            actions
        );

        preview.appendChild(
            wrapper
        );
    }



    function childFolders(parentId) {
        return folders
            .filter(folder =>
                (folder.parent_id || null) ===
                (parentId || null)
            )
            .sort((a, b) =>
                String(a.name).localeCompare(
                    String(b.name),
                    'de'
                )
            );
    }


    function folderNotes(folderId) {
        return notes
            .filter(note =>
                (note.folder_id || null) ===
                (folderId || null)
            )
            .sort((a, b) =>
                String(a.name).localeCompare(
                    String(b.name),
                    'de'
                )
            );
    }


    async function loadNotes() {
        const data =
            await api('/api/mlx/notes');

        notes =
            Array.isArray(data.notes)
                ? data.notes
                : [];

        folders =
            Array.isArray(data.folders)
                ? data.folders
                : [];

        renderFolderSelect();
        renderNotes();
    }


    function insertIntoChat(note) {
        const input =
            document.getElementById('input');

        const current =
            input.value.trim();

        input.value =
            current
                ? current + '\n\n' + note.content
                : note.content;

        input.focus();

        if (
            window.MLXChatRuntime &&
            MLXChatRuntime.autoResize
        ) {
            MLXChatRuntime.autoResize();
        }

        closePanel();
    }


    function resetEditor(
        showPreview = true
    ) {
        editingNoteId = null;

        nameInput.value = '';
        contentInput.value = '';

        if (folderSelect) {
            folderSelect.value = '';
        }

        saveButton.textContent =
            notesT(
                'notes.save_note',
                'Notiz speichern'
            );

        if (showPreview) {
            showPreviewMode();
            renderPreview();
        }
    }


    function editNote(note) {

        if (!note) {
            return;
        }

        selectedNoteId =
            note.id;

        editingNoteId =
            note.id;

        nameInput.value =
            note.name || '';

        contentInput.value =
            note.content || '';

        if (folderSelect) {
            folderSelect.value =
                note.folder_id || '';
        }

        saveButton.textContent =
            notesT(
                'notes.save_changes',
                'Änderungen speichern'
            );

        showEditorMode();

        nameInput.focus();
        nameInput.select();
    }


    async function saveNote() {

        const name =
            nameInput.value.trim();

        const content =
            contentInput.value.trim();

        if (!name) {
            alert(
                notesT(
                    'notes.enter_name',
                    'Bitte einen Namen eingeben.'
                )
            );

            nameInput.focus();
            return;
        }

        if (!content) {
            alert(
                notesT(
                    'notes.enter_content',
                    'Bitte einen Notiztext eingeben.'
                )
            );

            contentInput.focus();
            return;
        }


        const folderId =
            folderSelect &&
            folderSelect.value
                ? folderSelect.value
                : null;


        const payload = {
            name,
            content,
            folder_id:
                folderId
        };


        const previousEditingId =
            editingNoteId;

        let result = null;


        if (editingNoteId) {

            result =
                await api(
                    '/api/mlx/notes/' +
                    encodeURIComponent(
                        editingNoteId
                    ),
                    jsonOptions(
                        'PUT',
                        payload
                    )
                );

        } else {

            result =
                await api(
                    '/api/mlx/notes',
                    jsonOptions(
                        'POST',
                        payload
                    )
                );
        }


        const returnedId =
            result?.note?.id ||
            result?.id ||
            previousEditingId ||
            null;


        resetEditor(false);

        if (returnedId) {
            selectedNoteId =
                returnedId;

            rememberSelectedNoteId(
                returnedId
            );
        }


        showPreviewMode();

        await loadNotes();


        if (!returnedId) {

            const candidates =
                notes.filter(note =>
                    note.name === name &&
                    note.content === content &&
                    (note.folder_id || null) ===
                    (folderId || null)
                );

            if (candidates.length) {
                selectedNoteId =
                    candidates[
                        candidates.length - 1
                    ].id;

                renderNotes();
            }
        }
    }


async function deleteNote(note) {

        const confirmed =
            await notesConfirm({
                title:
                    'Notiz löschen?',
                message:
                    `„${note.name || 'Notiz'}“ wird dauerhaft gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.`,
                confirmLabel:
                    'Notiz löschen',
                cancelLabel:
                    'Abbrechen'
            });


        if (!confirmed) {
            return;
        }


        await api(
            '/api/mlx/notes/' +
            encodeURIComponent(
                note.id
            ),
            {
                method: 'DELETE'
            }
        );


        if (
            selectedNoteId ===
            note.id
        ) {
            selectedNoteId =
                null;

            if (
                typeof rememberSelectedNoteId ===
                'function'
            ) {
                rememberSelectedNoteId(
                    null
                );
            }
        }


        if (
            editingNoteId ===
            note.id
        ) {
            resetEditor(false);
        }


        showPreviewMode();

        await loadNotes();
    }


    async function moveNote(
        noteId,
        folderId
    ) {
        const note = getNote(noteId);

        if (!note) {
            return;
        }

        if (
            (note.folder_id || null) ===
            (folderId || null)
        ) {
            return;
        }

        await api(
            '/api/mlx/notes/' +
            encodeURIComponent(noteId) +
            '/folder',
            jsonOptions(
                'PATCH',
                {
                    folder_id:
                        folderId || null
                }
            )
        );

        await loadNotes();
    }


    async function createFolder(
        parentId = null
    ) {
        const name = prompt(
            parentId
                ? notesT('notes.new_subfolder_name', 'Name of the subfolder:')
                : notesT('notes.new_folder_name', 'Name of the new folder:')
        );

        if (name === null) {
            return;
        }

        const value = name.trim();

        if (!value) {
            return;
        }

        await api(
            '/api/mlx/note-folders',
            jsonOptions(
                'POST',
                {
                    name: value,
                    parent_id:
                        parentId || null
                }
            )
        );

        await loadNotes();
    }


    async function renameFolder(folder) {
        const name = prompt(
            notesT('notes.rename_folder', 'New folder name:'),
            folder.name
        );

        if (name === null) {
            return;
        }

        const value = name.trim();

        if (!value) {
            return;
        }

        await api(
            '/api/mlx/note-folders/' +
            encodeURIComponent(folder.id),
            jsonOptions(
                'PATCH',
                {
                    name: value
                }
            )
        );

        await loadNotes();
    }


async function deleteFolder(folder) {

        const confirmed =
            await notesConfirm({
                title:
                    'Ordner löschen?',
                message:
                    `Der Ordner „${folder.name || 'Ordner'}“ wird gelöscht. Die enthaltenen Notizen bleiben erhalten und werden nicht gelöscht.`,
                confirmLabel:
                    'Ordner löschen',
                cancelLabel:
                    'Abbrechen'
            });


        if (!confirmed) {
            return;
        }


        await api(
            '/api/mlx/note-folders/' +
            encodeURIComponent(
                folder.id
            ),
            {
                method: 'DELETE'
            }
        );


        await loadNotes();
    }


    async function moveFolder(
        folderId,
        parentId
    ) {
        const folder = getFolder(folderId);

        if (!folder) {
            return;
        }

        if (folder.id === parentId) {
            return;
        }

        if (
            (folder.parent_id || null) ===
            (parentId || null)
        ) {
            return;
        }

        try {
            await api(
                '/api/mlx/note-folders/' +
                encodeURIComponent(
                    folder.id
                ),
                jsonOptions(
                    'PATCH',
                    {
                        parent_id:
                            parentId || null
                    }
                )
            );

            await loadNotes();

        } catch (error) {
            console.error(error);

            alert(
                notesT(
                'notes.folder_move_failed',
                'Folder could not be moved.\n\nA folder cannot be moved into itself or one of its subfolders.'
            )
            );
        }
    }


    async function toggleFolder(folder) {
        const collapsed =
            !Boolean(folder.collapsed);

        folder.collapsed =
            collapsed;

        renderNotes();

        try {
            await api(
                '/api/mlx/note-folders/' +
                encodeURIComponent(
                    folder.id
                ),
                jsonOptions(
                    'PATCH',
                    {
                        collapsed
                    }
                )
            );
        } catch (error) {
            console.error(error);
        }
    }


    function newNoteInFolder(folderId) {

        resetEditor(false);

        if (folderSelect) {
            folderSelect.value =
                folderId || '';
        }

        showEditorMode();

        nameInput.focus();
    }


    function closeContextMenu() {
        if (!contextMenu) {
            return;
        }

        contextMenu.remove();
        contextMenu = null;
    }


    function showContextMenu(
        event,
        items
    ) {
        event.preventDefault();
        event.stopPropagation();

        closeContextMenu();

        contextMenu =
            document.createElement('div');

        contextMenu.className =
            'notes-context-menu';

        for (const item of items) {

            if (item.separator) {
                const separator =
                    document.createElement('div');

                separator.className =
                    'notes-context-separator';

                contextMenu.appendChild(
                    separator
                );

                continue;
            }

            const button =
                document.createElement('button');

            button.type = 'button';
            button.textContent =
                item.label;

            if (item.danger) {
                button.classList.add(
                    'danger'
                );
            }

            button.addEventListener(
                'click',
                async clickEvent => {
                    clickEvent.stopPropagation();
                    closeContextMenu();

                    try {
                        await item.action();
                    } catch (error) {
                        console.error(error);
                        alert(
                            notesT('notes.action_failed', 'Action failed.')
                        );
                    }
                }
            );

            contextMenu.appendChild(
                button
            );
        }

        document.body.appendChild(
            contextMenu
        );

        const margin = 8;

        let left = event.clientX;
        let top = event.clientY;

        const rect =
            contextMenu.getBoundingClientRect();

        if (
            left + rect.width >
            window.innerWidth - margin
        ) {
            left =
                window.innerWidth -
                rect.width -
                margin;
        }

        if (
            top + rect.height >
            window.innerHeight - margin
        ) {
            top =
                window.innerHeight -
                rect.height -
                margin;
        }

        contextMenu.style.left =
            Math.max(margin, left) + 'px';

        contextMenu.style.top =
            Math.max(margin, top) + 'px';
    }


    function clearDragClasses() {
        document
            .querySelectorAll(
                '.note-drop-target'
            )
            .forEach(element =>
                element.classList.remove(
                    'note-drop-target'
                )
            );

        document
            .querySelectorAll(
                '.note-dragging'
            )
            .forEach(element =>
                element.classList.remove(
                    'note-dragging'
                )
            );
    }


    function startDrag(
        event,
        type,
        id
    ) {
        dragPayload = {
            type,
            id
        };

        event.currentTarget.classList.add(
            'note-dragging'
        );

        event.dataTransfer.effectAllowed =
            'move';

        event.dataTransfer.setData(
            'text/plain',
            JSON.stringify(dragPayload)
        );
    }


    function endDrag() {
        dragPayload = null;
        clearDragClasses();
    }


    function allowDrop(
        event,
        element
    ) {
        if (!dragPayload) {
            return;
        }

        event.preventDefault();

        event.dataTransfer.dropEffect =
            'move';

        clearDragClasses();

        element.classList.add(
            'note-drop-target'
        );
    }


    async function dropOnFolder(
        event,
        folderId
    ) {
        event.preventDefault();
        event.stopPropagation();

        const payload =
            dragPayload;

        dragPayload = null;
        clearDragClasses();

        if (!payload) {
            return;
        }

        if (payload.type === 'note') {
            await moveNote(
                payload.id,
                folderId
            );

            return;
        }

        if (payload.type === 'folder') {
            await moveFolder(
                payload.id,
                folderId
            );
        }
    }


    function createNoteCard(note) {

        const card =
            document.createElement('div');

        card.className =
            'note-card note-tree-item';

        if (
            selectedNoteId ===
            note.id
        ) {
            card.classList.add(
                'is-selected'
            );
        }

        card.draggable = true;

        card.title =
            note.name || '';


        card.addEventListener(
            'dragstart',
            event =>
                startDrag(
                    event,
                    'note',
                    note.id
                )
        );

        card.addEventListener(
            'dragend',
            endDrag
        );


        card.addEventListener(
            'click',
            event => {

                if (
                    event.target.closest(
                        'button'
                    )
                ) {
                    return;
                }

                selectNote(note);
            }
        );


        card.addEventListener(
            'dblclick',
            event => {

                if (
                    event.target.closest(
                        'button'
                    )
                ) {
                    return;
                }

                event.preventDefault();

                editNote(note);
            }
        );


        const top =
            document.createElement('div');

        top.className =
            'note-card-top';


        const title =
            document.createElement('div');

        title.className =
            'note-card-title';


        const handle =
            document.createElement('span');

        handle.className =
            'note-drag-handle';

        handle.textContent =
            '⋮⋮';


        const titleText =
            document.createElement('strong');

        titleText.textContent =
            note.name || 'Notiz';


        title.appendChild(
            handle
        );

        title.appendChild(
            titleText
        );


        const menu =
            document.createElement('button');

        menu.type = 'button';

        menu.className =
            'note-item-menu';

        menu.textContent = '⋯';


        const menuItems = [
            {
                label:
                    notesT(
                        'notes.insert_chat',
                        'In Chat einfügen'
                    ),
                action:
                    () =>
                        insertIntoChat(
                            note
                        )
            },
            {
                label:
                    notesT(
                        'notes.edit',
                        'Bearbeiten'
                    ),
                action:
                    () =>
                        editNote(
                            note
                        )
            },
            {
                separator: true
            },
            {
                label:
                    notesT(
                        'notes.delete',
                        'Löschen'
                    ),
                danger: true,
                action:
                    () =>
                        deleteNote(
                            note
                        )
            }
        ];


        menu.addEventListener(
            'click',
            event =>
                showContextMenu(
                    event,
                    menuItems
                )
        );


        card.addEventListener(
            'contextmenu',
            event =>
                showContextMenu(
                    event,
                    menuItems
                )
        );


        top.appendChild(
            title
        );

        top.appendChild(
            menu
        );

        card.appendChild(
            top
        );

        return card;
    }


    function renderFolder(
        folder,
        depth = 0
    ) {
        const wrapper =
            document.createElement('div');

        wrapper.className =
            'note-folder';

        wrapper.style.setProperty(
            '--note-folder-depth',
            depth
        );


        const header =
            document.createElement('div');

        header.className =
            'note-folder-header';

        header.draggable = true;

        header.addEventListener(
            'dragstart',
            event =>
                startDrag(
                    event,
                    'folder',
                    folder.id
                )
        );

        header.addEventListener(
            'dragend',
            endDrag
        );

        header.addEventListener(
            'dragover',
            event =>
                allowDrop(
                    event,
                    header
                )
        );

        header.addEventListener(
            'drop',
            event =>
                dropOnFolder(
                    event,
                    folder.id
                )
        );


        const toggle =
            document.createElement('button');

        toggle.type = 'button';

        toggle.className =
            'note-folder-toggle';

        toggle.textContent =
            folder.collapsed &&
            !searchTerm
                ? '▸'
                : '▾';

        toggle.addEventListener(
            'click',
            event => {
                event.stopPropagation();
                toggleFolder(folder);
            }
        );


        const icon =
            document.createElement('span');

        icon.className =
            'note-folder-icon';

        icon.textContent =
            folder.collapsed &&
            !searchTerm
                ? '📁'
                : '📂';


        const name =
            document.createElement('div');

        name.className =
            'note-folder-name';

        name.innerHTML =
            '<strong>' +
            escapeHtml(folder.name) +
            '</strong>';

        name.addEventListener(
            'dblclick',
            event => {
                event.stopPropagation();
                toggleFolder(folder);
            }
        );


        const menu =
            document.createElement('button');

        menu.type = 'button';

        menu.className =
            'note-folder-menu';

        menu.textContent = '⋯';

        const menuItems = [
            {
                label: notesT('notes.new_note', 'New note'),
                action: () =>
                    newNoteInFolder(
                        folder.id
                    )
            },
            {
                label: 'Unterordner anlegen',
                action: () =>
                    createFolder(
                        folder.id
                    )
            },
            {
                separator: true
            },
            {
                label: 'Umbenennen',
                action: () =>
                    renameFolder(folder)
            },
            {
                label: notesT('notes.delete', 'Delete'),
                danger: true,
                action: () =>
                    deleteFolder(folder)
            }
        ];

        menu.addEventListener(
            'click',
            event =>
                showContextMenu(
                    event,
                    menuItems
                )
        );

        header.addEventListener(
            'contextmenu',
            event =>
                showContextMenu(
                    event,
                    menuItems
                )
        );


        header.appendChild(toggle);
        header.appendChild(icon);
        header.appendChild(name);
        header.appendChild(menu);

        wrapper.appendChild(header);


        if (
            !folder.collapsed ||
            searchTerm
        ) {

            const body =
                document.createElement('div');

            body.className =
                'note-folder-body';


            for (
                const child
                of childFolders(folder.id)
            ) {

                if (
                    searchTerm &&
                    !folderMatchesSearch(
                        child
                    )
                ) {
                    continue;
                }

                body.appendChild(
                    renderFolder(
                        child,
                        depth + 1
                    )
                );
            }


            for (
                const note
                of folderNotes(folder.id)
            ) {

                if (
                    searchTerm &&
                    !noteMatchesSearch(
                        note
                    )
                ) {
                    continue;
                }

                body.appendChild(
                    createNoteCard(note)
                );
            }


            if (
                !childFolders(folder.id).length &&
                !folderNotes(folder.id).length
            ) {
                const empty =
                    document.createElement('div');

                empty.className =
                    'note-folder-empty';

                empty.textContent =
                    notesT('notes.empty_folder', 'Drop here or create a new note');

                body.appendChild(empty);
            }


            wrapper.appendChild(body);
        }

        return wrapper;
    }


    function createRootDropZone() {

        const root =
            document.createElement('div');

        root.className =
            'note-root-drop';

        const icon =
            document.createElement('span');

        icon.textContent = '⌂';


        const name =
            document.createElement('strong');

        name.textContent =
            notesT(
                'notes.no_folder',
                'Ohne Ordner'
            );


        const hint =
            document.createElement('small');

        hint.textContent =
            notesT(
                'notes.drop_remove_folder',
                'Hierher ziehen'
            );


        root.appendChild(icon);
        root.appendChild(name);
        root.appendChild(hint);


        root.addEventListener(
            'dragover',
            event =>
                allowDrop(
                    event,
                    root
                )
        );


        root.addEventListener(
            'drop',
            event =>
                dropOnFolder(
                    event,
                    null
                )
        );


        return root;
    }


    function renderNotes() {

        list.innerHTML = '';


        restoreSelectedNoteId();


        if (
            selectedNoteId &&
            !getNote(selectedNoteId)
        ) {
            selectedNoteId =
                null;

            rememberSelectedNoteId(
                null
            );
        }


        if (
            !selectedNoteId &&
            notes.length
        ) {
            const first =
                [...notes]
                    .sort(
                        (a, b) =>
                            String(a.name)
                                .localeCompare(
                                    String(b.name),
                                    'de'
                                )
                    )[0];

            selectedNoteId =
                first?.id || null;

            rememberSelectedNoteId(
                selectedNoteId
            );
        }


        const toolbar =
            document.createElement('div');

        toolbar.className =
            'notes-tree-toolbar';


        const rootNewNote =
            document.createElement('button');

        rootNewNote.type =
            'button';

        rootNewNote.textContent =
            notesT(
                'notes.add_note',
                '+ Notiz'
            );

        rootNewNote.addEventListener(
            'click',
            () =>
                newNoteInFolder(
                    null
                )
        );


        const rootNewFolder =
            document.createElement('button');

        rootNewFolder.type =
            'button';

        rootNewFolder.textContent =
            notesT(
                'notes.add_folder',
                '+ Ordner'
            );

        rootNewFolder.addEventListener(
            'click',
            () =>
                createFolder(
                    null
                )
        );


        toolbar.appendChild(
            rootNewNote
        );

        toolbar.appendChild(
            rootNewFolder
        );

        list.appendChild(
            toolbar
        );


        const tree =
            document.createElement('div');

        tree.className =
            'notes-tree-content';


        const visibleFolders =
            childFolders(null)
                .filter(folder =>
                    !searchTerm ||
                    folderMatchesSearch(
                        folder
                    )
                );


        for (
            const folder
            of visibleFolders
        ) {
            tree.appendChild(
                renderFolder(
                    folder,
                    0
                )
            );
        }


        const rootSection =
            document.createElement('div');

        rootSection.className =
            'note-root-section';


        rootSection.appendChild(
            createRootDropZone()
        );


        const rootNotes =
            document.createElement('div');

        rootNotes.className =
            'note-root-notes';


        const visibleRootNotes =
            folderNotes(null)
                .filter(note =>
                    !searchTerm ||
                    noteMatchesSearch(
                        note
                    )
                );


        for (
            const note
            of visibleRootNotes
        ) {
            rootNotes.appendChild(
                createNoteCard(
                    note
                )
            );
        }


        rootSection.appendChild(
            rootNotes
        );

        tree.appendChild(
            rootSection
        );


        if (
            !folders.length &&
            !notes.length
        ) {
            const empty =
                document.createElement('div');

            empty.className =
                'note-empty-state';

            empty.textContent =
                notesT(
                    'notes.no_notes',
                    'Noch keine Notizen vorhanden.'
                );

            tree.appendChild(
                empty
            );

        } else if (
            searchTerm &&
            !visibleFolders.length &&
            !visibleRootNotes.length
        ) {

            const empty =
                document.createElement('div');

            empty.className =
                'note-empty-state notes-search-empty';

            empty.textContent =
                'Keine passenden Notizen gefunden.';

            tree.appendChild(
                empty
            );
        }


        list.appendChild(
            tree
        );

        renderPreview();
    }


    function renderFolderSelect() {
        if (!folderSelect) {
            return;
        }

        const current =
            folderSelect.value;

        folderSelect.innerHTML = '';

        const rootOption =
            document.createElement('option');

        rootOption.value = '';
        rootOption.textContent =
            notesT('notes.no_folder', 'No folder');

        folderSelect.appendChild(
            rootOption
        );


        function add(
            parentId,
            depth
        ) {
            for (
                const folder
                of childFolders(parentId)
            ) {
                const option =
                    document.createElement(
                        'option'
                    );

                option.value =
                    folder.id;

                option.textContent =
                    '   '.repeat(depth) +
                    (depth ? '↳ ' : '') +
                    folder.name;

                folderSelect.appendChild(
                    option
                );

                add(
                    folder.id,
                    depth + 1
                );
            }
        }

        add(null, 0);

        if (
            [...folderSelect.options]
                .some(
                    option =>
                        option.value ===
                        current
                )
        ) {
            folderSelect.value =
                current;
        }
    }


    function installFolderUi() {

        folderSelect =
            document.getElementById(
                'noteFolder'
            );

        if (!folderSelect) {
            throw new Error(
                '#noteFolder fehlt.'
            );
        }


        const cancel =
            document.getElementById(
                'noteEditCancel'
            );

        if (cancel) {

            cancel.addEventListener(
                'click',
                () =>
                    resetEditor(true)
            );
        }
    }


    async function openPanel() {

        const backdrop =
            document.getElementById(
                'notesBackdrop'
            );

        if (backdrop) {
            backdrop.hidden = false;
        }

        panel.style.display =
            'flex';

        panel.setAttribute(
            'aria-hidden',
            'false'
        );


        document
            .getElementById(
                'notesButton'
            )
            .classList.add(
                'active'
            );


        showPreviewMode();


        try {

            await loadNotes();

        } catch (error) {

            console.error(error);

            alert(
                notesT(
                    'notes.load_failed',
                    'Notizen konnten nicht geladen werden.'
                )
            );
        }
    }


    function closePanel() {

        closeContextMenu();

        const backdrop =
            document.getElementById(
                'notesBackdrop'
            );

        if (backdrop) {
            backdrop.hidden = true;
        }

        panel.style.display =
            'none';

        panel.setAttribute(
            'aria-hidden',
            'true'
        );


        document
            .getElementById(
                'notesButton'
            )
            .classList.remove(
                'active'
            );
    }


    function togglePanel() {

        const visible =
            panel.style.display !==
            'none';

        if (visible) {
            closePanel();
        } else {
            openPanel();
        }
    }


    function init() {

        installFolderUi();

        initNotesSearch();
        initSidebarResize();


        document
            .getElementById(
                'notesButton'
            )
            .addEventListener(
                'click',
                togglePanel
            );


        document
            .getElementById(
                'notesClose'
            )
            .addEventListener(
                'click',
                closePanel
            );


        const backdrop =
            document.getElementById(
                'notesBackdrop'
            );

        if (backdrop) {

            backdrop.addEventListener(
                'click',
                closePanel
            );
        }


        saveButton.addEventListener(
            'click',
            saveNote
        );


        document.addEventListener(
            'click',
            event => {

                if (
                    contextMenu &&
                    !contextMenu.contains(
                        event.target
                    )
                ) {
                    closeContextMenu();
                }
            }
        );


        document.addEventListener(
            'keydown',
            event => {

                if (
                    (
                        event.metaKey ||
                        event.ctrlKey
                    ) &&
                    event.key.toLowerCase() ===
                    'f' &&
                    panel.style.display !==
                    'none'
                ) {
                    const search =
                        document.getElementById(
                            'notesSearch'
                        );

                    if (search) {
                        event.preventDefault();
                        search.focus();
                        search.select();
                    }

                    return;
                }


                if (
                    event.key !==
                    'Escape'
                ) {
                    return;
                }


                if (contextMenu) {
                    closeContextMenu();
                    return;
                }


                if (
                    panel.style.display !==
                    'none'
                ) {
                    closePanel();
                }
            }
        );
    }


    window.MLXChatNotes = {
        init,
        loadNotes
    };

})();
