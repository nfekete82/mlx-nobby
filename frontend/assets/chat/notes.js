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


    function resetEditor() {
        editingNoteId = null;

        nameInput.value = '';
        contentInput.value = '';

        if (folderSelect) {
            folderSelect.value = '';
        }

        saveButton.textContent =
            notesT('notes.save_note', 'Save note');

        const cancel =
            document.getElementById(
                'noteEditCancel'
            );

        if (cancel) {
            cancel.style.display = 'none';
        }
    }


    function editNote(note) {
        editingNoteId = note.id;

        nameInput.value = note.name || '';
        contentInput.value = note.content || '';

        if (folderSelect) {
            folderSelect.value =
                note.folder_id || '';
        }

        saveButton.textContent =
            notesT('notes.save_changes', 'Save changes');

        const cancel =
            document.getElementById(
                'noteEditCancel'
            );

        if (cancel) {
            cancel.style.display = 'block';
        }

        nameInput.focus();

        panel.scrollTo({
            top: panel.scrollHeight,
            behavior: 'smooth'
        });
    }


    async function saveNote() {
        const name =
            nameInput.value.trim();

        const content =
            contentInput.value.trim();

        if (!name) {
            alert(notesT('notes.enter_name', 'Enter a name.'));
            nameInput.focus();
            return;
        }

        if (!content) {
            alert(notesT('notes.enter_content', 'Enter note text.'));
            contentInput.focus();
            return;
        }

        const payload = {
            name,
            content,
            folder_id:
                folderSelect &&
                folderSelect.value
                    ? folderSelect.value
                    : null
        };

        if (editingNoteId) {
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
            await api(
                '/api/mlx/notes',
                jsonOptions(
                    'POST',
                    payload
                )
            );
        }

        resetEditor();
        await loadNotes();
    }


    async function deleteNote(note) {
        if (
            !confirm(
                notesT(
                'notes.confirm_delete_note',
                'Really delete note "{name}"?',
                { name: note.name }
            )
            )
        ) {
            return;
        }

        await api(
            '/api/mlx/notes/' +
            encodeURIComponent(note.id),
            {
                method: 'DELETE'
            }
        );

        if (editingNoteId === note.id) {
            resetEditor();
        }

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
        if (
            !confirm(
                notesT(
                'notes.confirm_delete_folder',
                'Delete folder "{name}"?\n\nThe notes will not be deleted.',
                { name: folder.name }
            )
            )
        ) {
            return;
        }

        await api(
            '/api/mlx/note-folders/' +
            encodeURIComponent(folder.id),
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
        resetEditor();

        if (folderSelect) {
            folderSelect.value =
                folderId || '';
        }

        nameInput.focus();

        panel.scrollTo({
            top: panel.scrollHeight,
            behavior: 'smooth'
        });
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
            'note-card';

        card.draggable = true;

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


        const top =
            document.createElement('div');

        top.className =
            'note-card-top';


        const title =
            document.createElement('div');

        title.className =
            'note-card-title';

        title.innerHTML =
            '<span class="note-drag-handle">⋮⋮</span>' +
            '<strong>' +
            escapeHtml(note.name) +
            '</strong>';


        const menu =
            document.createElement('button');

        menu.type = 'button';
        menu.className =
            'note-item-menu';

        menu.textContent = '⋯';

        const menuItems = [
            {
                label: notesT('notes.insert_chat', 'Insert into chat'),
                action: () =>
                    insertIntoChat(note)
            },
            {
                label: notesT('notes.edit', 'Edit'),
                action: () =>
                    editNote(note)
            },
            {
                separator: true
            },
            {
                label: notesT('notes.delete', 'Delete'),
                danger: true,
                action: () =>
                    deleteNote(note)
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


        top.appendChild(title);
        top.appendChild(menu);


        const preview =
            document.createElement('div');

        preview.className =
            'note-card-preview';

        preview.textContent =
            note.content.length > 180
                ? note.content.slice(
                    0,
                    180
                ) + '…'
                : note.content;


        const insertButton =
            document.createElement('button');

        insertButton.type = 'button';

        insertButton.className =
            'note-action-primary';

        insertButton.textContent =
            notesT('notes.insert', 'Insert');

        insertButton.addEventListener(
            'click',
            () => insertIntoChat(note)
        );


        card.appendChild(top);
        card.appendChild(preview);
        card.appendChild(insertButton);

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
            folder.collapsed
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
            folder.collapsed
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


        if (!folder.collapsed) {

            const body =
                document.createElement('div');

            body.className =
                'note-folder-body';


            for (
                const child
                of childFolders(folder.id)
            ) {
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

        root.innerHTML =
            '<span>⌂</span>' +
            '<strong>' +
            notesT('notes.no_folder', 'No folder') +
            '</strong>' +
            '<small>' +
            notesT(
                'notes.drop_remove_folder',
                'Drop here to remove from folder'
            ) +
            '</small>';

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

        const toolbar =
            document.createElement('div');

        toolbar.className =
            'notes-tree-toolbar';

        const rootNewNote =
            document.createElement('button');

        rootNewNote.type = 'button';
        rootNewNote.textContent =
            notesT('notes.add_note', '+ Note');

        rootNewNote.addEventListener(
            'click',
            () => newNoteInFolder(null)
        );

        const rootNewFolder =
            document.createElement('button');

        rootNewFolder.type = 'button';
        rootNewFolder.textContent =
            notesT('notes.add_folder', '+ Folder');

        rootNewFolder.addEventListener(
            'click',
            () => createFolder(null)
        );

        toolbar.appendChild(
            rootNewNote
        );

        toolbar.appendChild(
            rootNewFolder
        );

        list.appendChild(toolbar);


        for (
            const folder
            of childFolders(null)
        ) {
            list.appendChild(
                renderFolder(
                    folder,
                    0
                )
            );
        }


        const rootDrop =
            createRootDropZone();

        list.appendChild(rootDrop);


        const rootNotes =
            folderNotes(null);

        for (const note of rootNotes) {
            list.appendChild(
                createNoteCard(note)
            );
        }


        if (
            !folders.length &&
            !notes.length
        ) {
            const empty =
                document.createElement('div');

            empty.className =
                'note-empty-state';

            empty.textContent =
                notesT('notes.no_notes', 'No notes yet.');

            list.appendChild(empty);
        }
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
        const existingTopButton =
            document.getElementById(
                'noteFolderAdd'
            );

        if (existingTopButton) {
            existingTopButton.remove();
        }


        folderSelect =
            document.getElementById(
                'noteFolder'
            );

        if (!folderSelect) {
            folderSelect =
                document.createElement(
                    'select'
                );

            folderSelect.id =
                'noteFolder';

            folderSelect.className =
                'note-folder-select';

            nameInput.parentNode.insertBefore(
                folderSelect,
                nameInput
            );
        }


        let cancel =
            document.getElementById(
                'noteEditCancel'
            );

        if (!cancel) {
            cancel =
                document.createElement(
                    'button'
                );

            cancel.id =
                'noteEditCancel';

            cancel.type =
                'button';

            cancel.className =
                'note-edit-cancel';

            cancel.textContent =
                notesT('notes.cancel_edit', 'Cancel editing');

            cancel.style.display =
                'none';

            cancel.addEventListener(
                'click',
                resetEditor
            );

            saveButton.parentNode.insertBefore(
                cancel,
                saveButton.nextSibling
            );
        }
    }


    async function openPanel() {
        panel.style.display = 'block';

        document
            .getElementById('notesButton')
            .classList.add('active');

        try {
            await loadNotes();
        } catch (error) {
            console.error(error);

            alert(
                notesT('notes.load_failed', 'Notes could not be loaded.')
            );
        }
    }


    function closePanel() {
        closeContextMenu();

        panel.style.display =
            'none';

        document
            .getElementById('notesButton')
            .classList.remove('active');
    }


    function togglePanel() {
        if (
            panel.style.display ===
            'block'
        ) {
            closePanel();
        } else {
            openPanel();
        }
    }


    function init() {
        installFolderUi();

        document
            .getElementById('notesButton')
            .addEventListener(
                'click',
                togglePanel
            );

        document
            .getElementById('notesClose')
            .addEventListener(
                'click',
                closePanel
            );

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
                    event.key === 'Escape'
                ) {
                    closeContextMenu();
                }
            }
        );
    }


    window.MLXChatNotes = {
        init,
        loadNotes
    };

})();
