/* Unified on-device memory dashboard. No remote services and no unsafe HTML. */
(() => {
    'use strict';
    if (window.MLXMemoryOverview) return;
    const $ = id => document.getElementById(id);
    const defaults = {
        knowledgeTitle: "Knowledge & life story",
        knowledgeHelp: "Browse every stored item by topic. A page is a selection; use More to continue. Statements reflect what you reported, not independently verified truth.",
        knowledgeAbout: "About me",
        knowledgeLife: "My life story",
        knowledgePeople: "People & relationships",
        knowledgeEvents: "Experiences & events",
        knowledgePreferences: "Preferences & habits",
        knowledgeWork: "Work & projects",
        knowledgeMedia: "Images & videos",
        knowledgeDecisions: "Decisions & tasks",
        knowledgeChanges: "Timeline & changes",
        knowledgeRelations: "Connections",
        knowledgeOverview: "What does Nobby know about me?",
        knowledgeProject: "Filter by project",
        knowledgeSince: "From date",
        knowledgeUntil: "To date",
        knowledgeLoad: "Apply filters",
        knowledgeExport: "Export knowledge",
        knowledgeImport: "Import knowledge",
        knowledgeBackupHelp: "Knowledge exports contain private information and source references. Back up original chats and media separately using Chat backup. Imports respect current deletion rules.",
        knowledgePin: "Mark important",
        knowledgeUnpin: "Remove priority",
        knowledgeHistory: "Show correction history",
        knowledgeMerge: "Merge selected memories",
        knowledgeMergeValue: "Combined statement (original versions remain in history)",
        knowledgeSelected: "Select for merging",
        knowledgeShown: "Shown / stored",
        knowledgeSources: "Open original chat",
        knowledgeDiagnostics: "Processing & diagnostics",
        knowledgeImportConfirm: "Import this private knowledge backup? Existing deletion rules take precedence.",
        knowledgeSuccess: "Saved locally.",
        knowledgeNoHistory: "No older versions.",
        knowledgeConflicts: "Review open contradictions in the personal memory controls below.",
        knowledgeStatement: "Reported statement",
        knowledgePlan: "Plan",
        knowledgeInterpretation: "Interpretation",
        knowledgeAssumption: "Assumption",
        knowledgeFact: "Confirmed memory",
        knowledgeScopes: "What may Nobby retain?",
        knowledgeSimilar: "Review similar memories",
        knowledgeReported: "reported experience",
        changeadded: "Added",
        changeupdated: "Corrected",
        changedeleted: "Deleted",
        changemerged: "Merged",
        changepinned: "Marked important",
        changeunpinned: "Priority removed",
        changeobserved: "Source analyzed",
        changeimported: "Imported",
        title: 'Your memory',
        description: 'Everything Nobby has retained, in one place. All data stays on this device.',
        pause: 'Pause memory',
        resume: 'Resume memory',
        paused: 'Paused: no automatic recall or learning. Saved data is preserved.',
        active: 'Active: existing enabled memory layers can be used by Nobby.',
        note: 'Pausing does not delete anything. Old messages can be reindexed using advanced tools after resuming.',
        search: 'Search saved information…',
        all: 'All',
        personal: 'Personal facts',
        legacy: 'Saved memories',
        archive: 'Chat excerpts',
        showMore: 'Show more',
        details: 'Advanced settings and maintenance',
        edit: 'Edit',
        remove: 'Delete',
        exclude: 'Exclude chat from index',
        excludedNotice: 'The entire chat will be excluded from the search index. Original chat messages remain saved.',
        confirmDelete: 'Delete this saved memory and its revisions?',
        confirmLegacyDelete: 'Delete this saved memory?',
        noItems: 'Nothing saved in this category.',
        source: 'Source',
        manual: 'Manually saved',
        unknown: 'Unknown',
        preserved: 'Your original chats are stored separately. Deleting an extracted fact does not delete its original chat.',
        error: 'Could not load memory:',
        count: 'entries',
        layersOff: 'The two optional memory layers are currently disabled. Enable them under Advanced settings to learn from older chats.',
        original: 'Original chat preserved',
        cancel: 'Cancel',
        save: 'Save',
        smartTitle: 'Qwen · On-device',
        smartOn: 'Enable local Qwen learning',
        smartOff: 'Disable Qwen learning',
        smartRebuild: 'Analyze earlier chats',
        smartEnabled: 'Qwen analyzes new user messages in the background. Only verified facts are saved locally.',
        smartDisabled: 'Optional: let your local Qwen recognize facts from normal conversations. No cloud service.',
        smartRequiresPersonal: 'First enable Personal memory under Advanced settings.',
        smartQueue: 'In queue',
        smartProcessed: 'Analyzed',
        smartFailed: 'Failed',
        smartStarted: 'Older chat analysis scheduled. Progress appears here.',
        smartFullProgress: 'Full history',
        activityTitle: 'Media and work history',
        activityLoad: 'Load activity',
        activityMore: 'More activity',
        activityNone: 'No indexed activity yet. Enable and rebuild the local chat archive.',
        activityAll: 'All activities',
        activityImage: 'Images',
        activityVideo: 'Videos',
        activityAgent: 'Agent work',
        activityTool: 'Other tools',
        smartHelp: 'Learning and history remain local. Check, correct or delete every fact below.',
        groupAbout: 'About me',
        groupPartner: 'Relationship & partner',
        groupFamily: 'Family',
        groupWork: 'Work & projects',
        groupOther: 'Other information',
        archiveDetails: 'Chat archive — raw messages',
        archivedNote: 'These are searchable chat messages, not verified facts.',
        malformed: 'Uncategorized fact',
        sourceMessage: 'Chat source',
        birthday: 'Birthday',
        preference: 'Preference',
        name: 'Name',
        profession: 'Profession',
        residence: 'Residence',
        age: 'Age',
        health: 'Health',
        role: 'Role',
        goal: 'Goal',
        project: 'Project',
        relationship: 'Relationship',
        hobby: 'Hobby',
        technology: 'Technology',
        statusLabel: 'Status',
        desc: 'Description',
        date: 'Date',
        education: 'Education',
        decision: 'Decision',
    };
    let translations = {en: defaults, de: {}};
    const t = key => translations[window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en'][key]
        || defaults[key] || key;
    const sources = ['personal', 'legacy', 'archive'];
    const fieldLabels = {
        geburtstag:'birthday', vorliebe:'preference', 'präferenz':'preference',
        name:'name', beruf:'profession', wohnort:'residence', alter:'age',
        gesundheit:'health', rolle:'role', ziel:'goal', projekt:'project',
        beziehung:'relationship', hobby:'hobby', technologie:'technology',
        status:'statusLabel', beschreibung:'desc', termin:'date',
        ausbildung:'education', entscheidung:'decision',
    };
    const categoryNames = ['groupAbout','groupPartner','groupFamily','groupWork','groupOther'];
    function categoryFor(item) {
        const subject = String(item.subject || '');
        if (subject === 'ich') return 'groupAbout';
        if (subject === 'partner') return 'groupPartner';
        if (subject.startsWith('familie')) return 'groupFamily';
        if (subject.startsWith('projekte') || subject === 'arbeit') return 'groupWork';
        return 'groupOther';
    }
    function readableField(field) {
        const raw = String(field || '').split('.')[0];
        return t(fieldLabels[raw] || (raw === 'notiz' ? 'desc' : 'malformed'));
    }
    const state = {paused:false, layers:{}, counts:{}, query:'', filter:'all',
        pages:{personal:[],legacy:[],archive:[]}, total:{}, busy:false, epoch:0,
        smart:{enabled:false,pending:0,processed:0,failed:0},
        activity:{items:[],total:0,kind:''}};
    const api = async (path, options = {}) => {
        const response = await fetch(path, options);
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(result.detail || result.error || 'HTTP ' + response.status);
        return result;
    };
    const post = (path, payload) => api(path, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
    });
    function element(tag, label = '', css = '') {
        const node = document.createElement(tag);
        if (label) node.textContent = String(label);
        if (css) node.className = css;
        return node;
    }
    function action(label, handler, css = 'settings-button') {
        const button = element('button', label, css);
        button.type = 'button';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try { await handler(); }
            catch (error) { notice(t('error') + ' ' + error.message); }
            finally { button.disabled = false; }
        });
        return button;
    }
    const notice = value => {
        if ($('memoryOverviewNotice')) $('memoryOverviewNotice').textContent = String(value);
    };
    function syncLabels() {
        if (!$('memoryOverview')) return;
        $('memoryOverviewTitle').textContent = t('title');
        $('memoryOverviewDescription').textContent = t('description');
        $('memoryOverviewNote').textContent = t('note');
        $('memoryOverviewSearch').placeholder = t('search');
        $('memoryOverviewWarning').textContent = t('preserved');
        $('memoryOverviewAdvancedLabel').textContent = t('details');
        $('memorySmartTitle').textContent = t('smartTitle');
        $('memorySmartHelp').textContent = t('smartHelp');
        $('memorySmartRebuild').textContent = t('smartRebuild');
        $('memoryActivityTitle').textContent = t('activityTitle');
        $('memoryActivityLoad').textContent = t('activityLoad');
        $('memoryActivityMore').textContent = t('activityMore');
        const activityKeys = ['activityAll', 'activityImage', 'activityVideo',
            'activityAgent', 'activityTool'];
        Array.from($('memoryActivityFilter').options).forEach((item, index) => {
            item.textContent = t(activityKeys[index]);
        });
        document.querySelectorAll?.('[data-i18n-memory]').forEach(node => {
            node.textContent = t(node.dataset.i18nMemory);
        });
        if ($('memoryKnowledgeSearch')) {
            $('memoryKnowledgeSearch').placeholder=t('search');
            $('memoryKnowledgeProject').placeholder=t('knowledgeProject');
            renderKnowledge();
        }
        renderSmart();
        const filter = $('memoryOverviewFilter');
        for (const option of filter.options) option.textContent = t(option.value);
        renderStatus();
        renderItems();
    }
    function renderStatus() {
        if (!$('memoryOverview')) return;
        $('memoryOverviewToggle').textContent = state.paused ? t('resume') : t('pause');
        $('memoryOverviewMode').textContent = t(state.paused ? 'paused' : 'active');
        const sum = $('memoryOverviewCounts');
        sum.replaceChildren();
        for (const source of sources) {
            sum.append(element('span', t(source) + ': ' + (state.counts[source] || 0),
                'memory-overview-count'));
        }
        $('memoryOverviewLayers').textContent = (
            !state.layers.personal && !state.layers.archive ? t('layersOff') : ''
        );
    }
    function itemBody(item, source) {
        if (source === 'personal') return item.value;
        if (source === 'legacy') return item.text;
        return item.content;
    }
    function itemTitle(item, source) {
        if (source === 'personal') return readableField(item.field);
        if (source === 'legacy') return item.category || t('legacy');
        return 'Chat ' + item.chat_id + ' · #' + item.ordinal + ' (' + item.role + ')';
    }
    function provenance(item, source) {
        if (source === 'personal' || source === 'legacy') {
            return item.source_chat_id
                ? (t('source') + ': ' + item.source_chat_id
                  + (item.source_ordinal === null || item.source_ordinal === undefined
                    ? '' : ' · #' + item.source_ordinal))
                : t('manual');
        }
        return t('source') + ': ' + item.chat_id;
    }
    async function modify(item, source, mode) {
        const id = encodeURIComponent(item.id);
        if (mode === 'edit') {
            const value = window.prompt(t('edit'), itemBody(item, source));
            if (value === null || !value.trim()) return;
            if (source === 'personal') {
                await api('/api/mlx/memory/personal/facts/' + id, {
                    method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({value:value.trim()}),
                });
            } else {
                await api('/api/mlx/memory/' + id, {
                    method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({text:value.trim()}),
                });
            }
        } else if (source === 'archive') {
            if (!window.confirm(t('excludedNotice'))) return;
            await post('/api/mlx/memory/archive/exclude/' + encodeURIComponent(item.chat_id), {});
        } else {
            if (!window.confirm(t(source === 'personal' ? 'confirmDelete' : 'confirmLegacyDelete'))) return;
            const path = source === 'personal'
                ? '/api/mlx/memory/personal/facts/' + id : '/api/mlx/memory/' + id;
            await api(path, {method:'DELETE'});
        }
        await refresh();
    }

    const knowledge = {kind:'all',category:'',items:[],total:0,next:null,selected:new Set(),epoch:0};
    const knowledgeCategories = [
        ['','knowledgeOverview','all'], ['about','knowledgeAbout','fact'],
        ['life','knowledgeLife','episode'], ['people','knowledgePeople','fact'],
        ['events','knowledgeEvents','episode'], ['preferences','knowledgePreferences','fact'],
        ['work','knowledgeWork','fact'], ['media','knowledgeMedia','media'],
        ['decisions','knowledgeDecisions','fact'], ['changes','knowledgeChanges','change'],
        ['relations','knowledgeRelations','relation'],
    ];
    const knowledgeBase = '/api/mlx/memory/knowledge/';
    function sourceLink(source) {
        if (source.role === 'manual') return element('small', t('manual'));
        const link = element('a', t('knowledgeSources') + ' · #' + source.ordinal);
        link.href = '/chat?memory_chat=' + encodeURIComponent(source.chat_id)
            + '&memory_message=' + encodeURIComponent(source.ordinal);
        return link;
    }
    async function knowledgeHistory(item, target) {
        const data = await api(knowledgeBase + 'history/' + encodeURIComponent(item.id));
        target.replaceChildren();
        const rows = data.items || [];
        if (!rows.length) target.append(element('p', t('knowledgeNoHistory')));
        for (const row of rows) target.append(element('p',
            new Date(row.created_at * 1000).toLocaleString() + ' · ' + row.value +
            (row.status === 'active' ? ' ✓' : '')));
    }
    function renderKnowledge() {
        const list = $('memoryKnowledgeList');
        if (!list) return;
        list.replaceChildren();
        $('memoryKnowledgeSummary').textContent = t('knowledgeShown') + ': '
            + knowledge.items.length + ' / ' + knowledge.total;
        if (!knowledge.items.length) list.append(element('p', t('noItems')));
        for (const item of knowledge.items) {
            const card = element('article', '', 'memory-overview-item');
            const isFact = Boolean(item.field);
            const title = isFact ? readableField(item.field)
                : (item.title || (item.subject && item.object ? item.subject + ' → ' + (item.predicate === 'reported_experience' ? t('knowledgeReported') : readableField(item.predicate)) + ' → ' + item.object : t('knowledgeChanges')));
            card.append(element('strong', title), element('p', item.value || item.description || (item.action ? t('change'+item.action) : '')));
            if (item.kind || item.status) {
                const keys = {statement:'knowledgeStatement',fact:'knowledgeFact',plan:'knowledgePlan',
                    interpretation:'knowledgeInterpretation',assumption:'knowledgeAssumption'};
                const label = keys[item.kind || item.status];
                if (label) card.append(element('small', t(label)));
            }
            if (item.period) card.append(element('small', item.period));
            if (Array.isArray(item.people) && item.people.length) card.append(element('small', item.people.join(', ')));
            for (const source of item.sources || []) card.append(sourceLink(source));
            const actions = element('div', '', 'memory-overview-actions');
            if (isFact) {
                const select = element('input'); select.type = 'checkbox';
                select.checked = knowledge.selected.has(item.id);
                select.setAttribute('aria-label', t('knowledgeSelected'));
                select.addEventListener('change', () => {
                    if (select.checked) knowledge.selected.add(item.id);
                    else knowledge.selected.delete(item.id);
                    $('memoryKnowledgeMerge').disabled = knowledge.selected.size < 2;
                });
                const selectLabel = element('label', t('knowledgeSelected')); selectLabel.append(select);
                card.append(selectLabel);
                actions.append(action(t('edit'), async () => {
                    const value = window.prompt(t('edit'), item.value);
                    if (value === null || !value.trim()) return;
                    await api('/api/mlx/memory/personal/facts/' + encodeURIComponent(item.id), {
                        method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:value.trim()})});
                    await loadKnowledge();
                }));
                actions.append(action(t(item.pinned ? 'knowledgeUnpin' : 'knowledgePin'), async () => {
                    await post(knowledgeBase + 'pin/' + encodeURIComponent(item.id), {pinned:!item.pinned});
                    await loadKnowledge();
                }));
                const history = element('details');
                const heading = element('summary', t('knowledgeHistory')); history.append(heading);
                const historyList = element('div'); history.append(historyList);
                history.addEventListener('toggle', () => {
                    if (history.open) knowledgeHistory(item, historyList).catch(error => notice(t('error') + ' ' + error.message));
                });
                card.append(history);
            }
            if (isFact || knowledge.kind === 'episode' || item.object_type === 'episode') actions.append(action(t('remove'), async () => {
                if (!window.confirm(t('confirmDelete'))) return;
                const path = isFact ? '/api/mlx/memory/personal/facts/' : knowledgeBase + 'episode/';
                await api(path + encodeURIComponent(item.id), {method:'DELETE'});
                await loadKnowledge();
            }));
            card.append(actions); list.append(card);
        }
        $('memoryKnowledgeMore').hidden = knowledge.next === null;
        $('memoryKnowledgeMerge').disabled = knowledge.selected.size < 2;
    }
    async function loadKnowledge(append = false) {
        if (!$('memoryKnowledge')) return;
        const epoch = ++knowledge.epoch;
        if (knowledge.kind === 'media') { await loadActivities(false); return; }
        const params = new URLSearchParams({kind:knowledge.kind,
            query:$('memoryKnowledgeSearch').value.trim(),
            category:knowledge.kind === 'fact' ? knowledge.category : '',
            project:$('memoryKnowledgeProject').value.trim(),
            offset:String(append ? knowledge.next || 0 : 0),limit:'30'});
        for (const [id, key] of [['memoryKnowledgeSince','since'],['memoryKnowledgeUntil','until']]) {
            if ($(id).value) {
                const date = new Date($(id).value + 'T00:00:00');
                if (key === 'until') date.setDate(date.getDate() + 1);
                params.set(key, String(date.getTime()/1000));
            }
        }
        const data = await api(knowledgeBase + 'items?' + params);
        if (epoch !== knowledge.epoch) return;
        knowledge.items = append ? [...knowledge.items, ...(data.items || [])] : (data.items || []);
        if (!append) knowledge.selected.clear();
        knowledge.total = Number(data.total) || 0;
        knowledge.next = data.next_offset ?? null;
        renderKnowledge();
        const diagnostics = await api(knowledgeBase + 'status');
        if (epoch !== knowledge.epoch) return;
        const node = $('memoryKnowledgeDiagnostics'); node.replaceChildren();
        for (const [key, value] of Object.entries(diagnostics.counts || {})) {
            const label = {chats:'archive',messages:'sourceMessage',episodes:'knowledgeEvents',facts:'personal',relations:'knowledgeRelations'}[key];
            node.append(element('span', t(label || 'count') + ': ' + value + ' · '));
        }
        for (const [key, value] of Object.entries(diagnostics.jobs || {})) {
            const label = {pending:'smartQueue',done:'smartProcessed',error:'smartFailed',excluded:'exclude'}[key];
            node.append(element('span', t(label || 'count') + ': ' + value + ' · '));
        }
        for (const error of diagnostics.errors || []) node.append(element('p', t('error') + ' ' + error.error_code + ' (' + error.count + ')'));
        for(const failed of diagnostics.failed_sources || []) node.append(element('p',
            t('source')+' '+failed.source_id.slice(0,12)+' · '+t('sourceMessage')+' '+failed.chunk+' · '+failed.error_code));
    }
    async function exportKnowledge() {
        const data = await api(knowledgeBase + 'export');
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}));
        const link = element('a'); link.href = url; link.download = 'mlx-nobby-private-knowledge.json';
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function loadKnowledgeScopes() {
        const data = await api(knowledgeBase + 'scopes');
        const controls = $('memoryKnowledgeScopes'); controls.replaceChildren();
        for (const [key,label] of knowledgeCategories.filter(row =>
            ['about','life','people','events','preferences','work','media','decisions'].includes(row[0]))) {
            const item = element('label'); const span = element('span',t(label));
            const check = element('input'); check.type='checkbox';check.value=key;
            check.checked=(data.scopes || []).includes(key);
            check.addEventListener('change',async () => {
                const values = Array.from(controls.querySelectorAll('input:checked')).map(node=>node.value);
                try { await post(knowledgeBase+'scopes',{scopes:values});notice(t('knowledgeSuccess')); }
                catch(error) { check.checked=!check.checked;notice(t('error')+' '+error.message); }
            });
            item.append(check,span);controls.append(item);
        }
    }
    async function showKnowledgeSimilar() {
        const data = await api(knowledgeBase+'similar');
        const output=$('memoryKnowledgeSimilar');output.replaceChildren();
        if (!(data.items || []).length) output.append(element('p',t('noItems')));
        for(const pair of data.items || []) {
            const card=element('article','','memory-overview-item');
            for(const value of pair.values) card.append(element('p',value));
            card.append(action(t('knowledgeMerge'),async()=>{
                const value=window.prompt(t('knowledgeMergeValue'),pair.values.join(' '));
                if(!value?.trim()) return;
                await post(knowledgeBase+'merge',{ids:pair.ids,value:value.trim()});
                await loadKnowledge();await showKnowledgeSimilar();
            }));output.append(card);
        }
    }

    function mountKnowledge(panel) {
        const section = element('section', '', 'memory-overview-group'); section.id = 'memoryKnowledge';
        const heading = element('h3', t('knowledgeTitle')); heading.dataset.i18nMemory = 'knowledgeTitle';
        const help = element('p', t('knowledgeHelp')); help.dataset.i18nMemory = 'knowledgeHelp';
        const nav = element('div', '', 'memory-overview-search');
        const category = element('select'); category.id = 'memoryKnowledgeCategory';
        for (const [key,label,kind] of knowledgeCategories) {
            const option = element('option', t(label)); option.value = key; option.dataset.kind = kind; option.dataset.i18nMemory = label; category.append(option);
        }
        const search = element('input'); search.id = 'memoryKnowledgeSearch'; search.type = 'search'; search.placeholder = t('search');
        search.setAttribute('aria-label', t('search'));
        const project = element('input'); project.id = 'memoryKnowledgeProject'; project.placeholder = t('knowledgeProject'); project.setAttribute('aria-label', t('knowledgeProject'));
        const dates = element('div', '', 'memory-overview-search');
        for (const [id,key] of [['memoryKnowledgeSince','knowledgeSince'],['memoryKnowledgeUntil','knowledgeUntil']]) {
            const label = element('label'); const labelText=element('span',t(key));labelText.dataset.i18nMemory=key;label.append(labelText); const input = element('input'); input.id = id; input.type = 'date'; label.append(input); dates.append(label);
        }
        const load = action(t('knowledgeLoad'), () => loadKnowledge()); load.dataset.i18nMemory = 'knowledgeLoad';
        nav.append(category, search, project, load);
        const summary = element('p'); summary.id = 'memoryKnowledgeSummary'; summary.setAttribute('role','status');
        const list = element('div', '', 'memory-overview-group'); list.id = 'memoryKnowledgeList';
        const more = action(t('showMore'), () => loadKnowledge(true)); more.id = 'memoryKnowledgeMore'; more.hidden = true;
        const merge = action(t('knowledgeMerge'), async () => {
            const value = window.prompt(t('knowledgeMergeValue'));
            if (!value?.trim()) return;
            await post(knowledgeBase + 'merge', {ids:Array.from(knowledge.selected), value:value.trim()});
            await loadKnowledge();
        }); merge.id = 'memoryKnowledgeMerge'; merge.disabled = true; merge.dataset.i18nMemory = 'knowledgeMerge';
        const tools = element('div', '', 'memory-overview-search');
        const download = action(t('knowledgeExport'), exportKnowledge); download.dataset.i18nMemory = 'knowledgeExport';
        const upload = element('input'); upload.type = 'file'; upload.accept = '.json,application/json'; upload.id = 'memoryKnowledgeImport';
        upload.setAttribute('aria-label', t('knowledgeImport'));
        upload.addEventListener('change', async () => {
            const file = upload.files?.[0]; if (!file) return;
            try {
                if (file.size > 32 * 1024 * 1024) throw Error('32 MiB');
                if (!window.confirm(t('knowledgeImportConfirm'))) return;
                await post(knowledgeBase + 'import', JSON.parse(await file.text()));
                notice(t('knowledgeSuccess')); await loadKnowledge();
            } catch (error) { notice(t('error') + ' ' + error.message); }
            finally { upload.value = ''; }
        });
        const uploadLabel = element('label');const uploadText=element('span',t('knowledgeImport'));uploadText.dataset.i18nMemory='knowledgeImport'; uploadLabel.append(uploadText,upload);
        tools.append(download, uploadLabel);
        const backupHelp = element('small', t('knowledgeBackupHelp')); backupHelp.dataset.i18nMemory = 'knowledgeBackupHelp';
        const scopePanel=element('details');
        const scopeTitle=element('summary',t('knowledgeScopes'));scopeTitle.dataset.i18nMemory='knowledgeScopes';
        const scopeList=element('div','','memory-overview-search');scopeList.id='memoryKnowledgeScopes';
        scopePanel.append(scopeTitle,scopeList);
        scopePanel.addEventListener('toggle',()=>{if(scopePanel.open) loadKnowledgeScopes().catch(error=>notice(t('error')+' '+error.message));});
        const similarPanel=element('details');
        const similarTitle=element('summary',t('knowledgeSimilar'));similarTitle.dataset.i18nMemory='knowledgeSimilar';
        const similarList=element('div');similarList.id='memoryKnowledgeSimilar';similarPanel.append(similarTitle,similarList);
        similarPanel.addEventListener('toggle',()=>{if(similarPanel.open) showKnowledgeSimilar().catch(error=>notice(t('error')+' '+error.message));});
        const diagnostics = element('details');
        const diagnosticsTitle=element('summary',t('knowledgeDiagnostics'));diagnosticsTitle.dataset.i18nMemory='knowledgeDiagnostics';
        diagnostics.append(diagnosticsTitle);
        const diagnosticList = element('div'); diagnosticList.id = 'memoryKnowledgeDiagnostics'; diagnostics.append(diagnosticList);
        section.append(heading,help,nav,dates,summary,list,more,merge,similarPanel,scopePanel,tools,backupHelp,diagnostics);
        panel.append(section);
        category.addEventListener('change', () => {
            const selected = knowledgeCategories.find(row => row[0] === category.value);
            knowledge.category = selected[0]; knowledge.kind = selected[2];
            if (knowledge.kind === 'media') {
                $('memoryOverviewActivities').open = true;
                $('memoryOverviewActivities').scrollIntoView?.({behavior:'smooth'});
            }
            loadKnowledge().catch(error => notice(t('error') + ' ' + error.message));
        });
        search.addEventListener('keydown', event => { if (event.key === 'Enter') loadKnowledge().catch(error => notice(t('error') + ' ' + error.message)); });
    }
    function renderSmart() {
        if (!$('memorySmartToggle')) return;
        const flag = Boolean(state.smart.enabled);
        $('memorySmartToggle').textContent = t(flag ? 'smartOff' : 'smartOn');
        $('memorySmartRebuild').disabled = !flag || state.paused;
        $('memorySmartToggle').disabled = !state.layers.personal;
        $('memorySmartMessage').textContent = (
            !state.layers.personal ? t('smartRequiresPersonal')
            : t(flag ? 'smartEnabled' : 'smartDisabled')
        );
        $('memorySmartProgress').textContent = flag
            ? t('smartQueue') + ': ' + (state.smart.pending || 0)
                + ' · ' + t('smartProcessed') + ': ' + (state.smart.processed || 0)
                + ' · ' + t('smartFailed') + ': ' + (state.smart.failed || 0)
            : '';
        const full = state.smart.full_scan || {};
        if (flag && full.total) {
            $('memorySmartProgress').textContent += ' · ' + t('smartFullProgress') +
                ': ' + (full.examined || 0) + '/' + full.total +
                (full.active ? ' …' : '');
        }
    }
    async function smartToggle() {
        const next = !state.smart.enabled;
        await post('/api/mlx/memory/smart/config', {enabled:next});
        state.smart.enabled = next;
        renderSmart();
    }
    let smartPoll = null;
    function ensureSmartPolling() {
        if (smartPoll) return;
        smartPoll = setInterval(async () => {
            if (!document.getElementById('memoryOverview')) {
                clearInterval(smartPoll);
                smartPoll = null;
                return;
            }
            try {
                const data = await api('/api/mlx/memory/smart/status');
                state.smart = {...state.smart, ...data};
                renderSmart();
                if (!data.full_scan?.active && !(data.pending > 0)) {
                    clearInterval(smartPoll);
                    smartPoll = null;
                }
            } catch (_) {
                clearInterval(smartPoll);
                smartPoll = null;
            }
        }, 3000);
    }
    async function smartBackfill() {
        const result = await post('/api/mlx/memory/smart/backfill', {full:true});
        state.smart = {...state.smart, ...result};
        renderSmart();
        ensureSmartPolling();
        notice(t('smartStarted'));
    }
    async function loadActivities(append = false) {
        const kind = $('memoryActivityFilter').value;
        const offset = append && kind === state.activity.kind
            ? state.activity.items.length : 0;
        const data = await api('/api/mlx/memory/archive/activities?kind=' +
            encodeURIComponent(kind) + '&limit=25&offset=' + offset);
        state.activity = {
            kind, total: Number(data.total) || 0,
            items: offset ? [...state.activity.items, ...(data.activities || [])]
                : (data.activities || []),
        };
        const output = $('memoryActivityList');
        output.replaceChildren();
        if (!state.activity.items.length) {
            output.append(element('p', t('activityNone'), 'memory-overview-empty'));
        }
        for (const item of state.activity.items) {
            const card = element('div', '', 'memory-overview-item');
            const label = element('strong',
                item.kind + ' · ' + item.operation + ' · ' + item.status);
            const summary = [
                item.model ? t('activityModel') + ': ' + item.model : '',
                item.project ? t('activityProject') + ': ' + item.project : '',
                item.prompt || '',
            ].filter(Boolean).join(' | ');
            const detail = element('p', summary);
            const source = element('small',
                'Chat ' + item.chat_id + ' · #' + item.ordinal +
                (item.artifact_ref ? ' · ' + item.artifact_ref : ''),
                'memory-overview-meta');
            card.append(label, detail, source);
            output.append(card);
        }
        $('memoryActivityMore').hidden = state.activity.items.length >= state.activity.total;
    }

    function renderItems() {
        if (!$('memoryOverview')) return;
        const container = $('memoryOverviewItems');
        container.replaceChildren();
        const visible = state.filter === 'all' ? sources : [state.filter];
        for (const source of visible) {
            const group = element('div', '', 'memory-overview-group');
            const heading = element('h4', t(source) + ' (' +
                (state.total[source] ?? state.counts[source] ?? 0) + ')');
            const archiveFolder = source === 'archive' ? element('details') : null;
            if (archiveFolder) {
                const label = element('summary', t('archiveDetails') + ' (' +
                    (state.total[source] ?? state.counts[source] ?? 0) + ')');
                archiveFolder.append(label, element('p', t('archivedNote')));
                group.append(archiveFolder);
            } else group.append(heading);
            const output = archiveFolder || group;
            const values = state.pages[source] || [];
            if (!values.length && source !== 'personal') {
                output.append(element('p', t('noItems'), 'memory-overview-empty'));
            }
            // Group meaningful personal facts by subject instead of showing
            // opaque subject.hash identifiers from the storage schema.
            const buckets = new Map();
            if (source === 'personal') {
                for (const item of values) {
                    const name = categoryFor(item);
                    if (!buckets.has(name)) buckets.set(name, []);
                    buckets.get(name).push(item);
                }
            }
            const addCard = (item, parent = output) => {
                const card = element('div', '', 'memory-overview-item');
                const label = element('strong', itemTitle(item, source));
                const raw = String(itemBody(item, source) || '');
                const detail = element('details');
                const excerpt = element('summary', raw.length > 280
                    ? raw.slice(0, 280) + '…' : raw);
                detail.append(excerpt);
                if (raw.length > 280) detail.append(element('p', raw));
                const meta = element('small', provenance(item, source), 'memory-overview-meta');
                const actions = element('div', '', 'memory-overview-actions');
                if (source !== 'archive') {
                    actions.append(action(t('edit'), () => modify(item, source, 'edit')));
                }
                actions.append(action(t(source === 'archive' ? 'exclude' : 'remove'),
                    () => modify(item, source, 'delete'),
                    'settings-button memory-overview-danger'));
                card.append(label, detail, meta, actions);
                parent.append(card);
            };
            if (source === 'personal') {
                for (const name of categoryNames) {
                    const facts = buckets.get(name) || [];
                    const bucket = element('details', '', 'memory-subject-category');
                    bucket.open = facts.length > 0;
                    bucket.append(element('summary', t(name) + ' (' + facts.length + ')'));
                    if (!facts.length) {
                        bucket.append(element('p', t('noItems'), 'memory-overview-empty'));
                    } else {
                        for (const item of facts) addCard(item, bucket);
                    }
                    output.append(bucket);
                }
            } else {
                for (const item of values) addCard(item);
            }
            if (values.length < (state.total[source] || 0)) {
                output.append(action(t('showMore'), () => loadPage(source, true)));
            }
            container.append(group);
        }
    }
    async function loadPage(source, append = false) {
        const epoch = state.epoch;
        const current = append ? state.pages[source].length : 0;
        const url = '/api/mlx/memory/dashboard/items?source=' + encodeURIComponent(source)
            + '&query=' + encodeURIComponent(state.query)
            + '&offset=' + current + '&limit=20';
        const data = await api(url);
        if (state.epoch !== epoch) return;
        state.pages[source] = append
            ? [...state.pages[source], ...(data.items || [])] : (data.items || []);
        state.total[source] = data.total || 0;
        renderItems();
    }
    async function refresh() {
        if (!$('memoryOverview')) return;
        const epoch = ++state.epoch;
        notice('');
        const selected = state.filter === 'all' ? sources : [state.filter];
        try {
            const info = await api('/api/mlx/memory/dashboard/status');
            if (epoch !== state.epoch) return;
            state.paused = Boolean(info.paused);
            state.counts = info.counts || {};
            state.layers = info.layers || {};
            try {
                const smarter = await api('/api/mlx/memory/smart/status');
                if (epoch !== state.epoch) return;
                state.smart = {...state.smart, ...smarter};
                if (smarter.full_scan?.active || smarter.pending > 0)
                    ensureSmartPolling();
            } catch (_) {
                // Older native Agent installations still retain the legacy dashboard.
            }
            state.pages = {personal:[],legacy:[],archive:[]};
            state.total = {};
            renderStatus();
            renderSmart();
            await Promise.all([...selected.map(source => loadPage(source)), loadKnowledge()]);
        } catch (error) {
            if (epoch === state.epoch) notice(t('error') + ' ' + error.message);
        }
    }
    async function togglePause() {
        const button = $('memoryOverviewToggle');
        const next = !state.paused;
        button.disabled = true;
        try {
            const result = await post('/api/mlx/memory/dashboard/pause', {paused:next});
            state.paused = result.paused;
            renderStatus();
            renderSmart();
            notice(t(state.paused ? 'paused' : 'active'));
        } catch (error) {
            notice(t('error') + ' ' + error.message);
        } finally { button.disabled = false; }
    }
    function foldExpertPanels(pane, advanced) {
        const candidates = [
            ...Array.from(pane.children).filter(el =>
                el.classList.contains('settings-card') && el.id !== 'memoryOverview'),
        ];
        for (const section of candidates) advanced.append(section);
    }
    function mount() {
        const pane = $('memoryManagerPane');
        if (!pane || $('memoryOverview')) return;
        const style = element('style');
        style.textContent = `
            #memoryOverview{display:grid;gap:13px}
            #memoryOverview .memory-overview-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
            #memoryOverview .memory-overview-top h3{font-size:1.2rem;margin:0}
            #memoryOverview .memory-overview-counts{display:flex;gap:6px;flex-wrap:wrap}
            #memoryOverview .memory-overview-count{padding:5px 10px;border:1px solid rgba(127,127,127,.25);border-radius:20px;font-size:.8rem}
            #memoryOverview .memory-overview-search{display:flex;gap:8px;flex-wrap:wrap}
            #memoryOverviewSearch{flex:1;min-width:160px}
            #memoryOverview .memory-overview-group{display:grid;gap:9px;padding-top:8px}
            #memoryOverview .memory-overview-group h4{font-size:.95rem;margin:8px 0 2px}
            #memoryOverview .memory-subject-category{border:1px solid rgba(127,127,127,.22);border-radius:10px;padding:12px;display:grid;gap:8px;margin:6px 0}
            #memoryOverview .memory-subject-category>summary{cursor:pointer;font-weight:600}
            #memoryOverview .memory-subject-category>.memory-overview-item{margin-top:8px}
            #memoryOverview .memory-overview-item{border:1px solid rgba(127,127,127,.2);border-radius:10px;padding:12px;display:grid;gap:6px}
            #memoryOverview .memory-overview-item details{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}
            #memoryOverview .memory-overview-item summary{cursor:pointer}
            #memoryOverview .memory-overview-meta{color:var(--muted,#94a3b8)}
            #memoryOverview .memory-overview-actions{display:flex;justify-content:flex-end;gap:6px}
            #memoryOverview .memory-overview-danger{opacity:.75}
            #memoryOverview .memory-overview-empty{font-size:.82rem;color:var(--muted,#94a3b8)}
            #memoryOverviewSmart{display:grid;gap:9px;padding:12px;border:1px solid rgba(127,127,127,.2);border-radius:10px}
            #memoryOverviewSmart .smart-actions{display:flex;gap:8px;flex-wrap:wrap}
            #memoryOverviewSmart small{color:var(--muted,#94a3b8)}
            #memoryOverviewAdvanced{margin-top:14px}
            #memoryOverviewAdvanced>summary{cursor:pointer;padding:12px;border:1px solid rgba(127,127,127,.25);border-radius:9px}
            #memoryOverviewAdvanced>.settings-card{margin-top:10px}
        `;
        document.head.append(style);
        const panel = element('section', '', 'settings-card');
        panel.id = 'memoryOverview';
        const top = element('div', '', 'memory-overview-top');
        const headings = element('div');
        const title = element('h3'); title.id = 'memoryOverviewTitle';
        const description = element('p'); description.id = 'memoryOverviewDescription';
        headings.append(title, description);
        const toggle = action('', togglePause);
        toggle.id = 'memoryOverviewToggle';
        top.append(headings, toggle);
        const mode = element('p'); mode.id = 'memoryOverviewMode';
        const counts = element('div', '', 'memory-overview-counts'); counts.id = 'memoryOverviewCounts';
        const warning = element('small'); warning.id = 'memoryOverviewWarning';
        const layers = element('small'); layers.id = 'memoryOverviewLayers';
        const note = element('small'); note.id = 'memoryOverviewNote';
        const smartPanel = element('section', '', '');
        smartPanel.id = 'memoryOverviewSmart';
        const smartTitle = element('strong', t('smartTitle'));
        smartTitle.id = 'memorySmartTitle';
        const smartHelp = element('small'); smartHelp.id = 'memorySmartHelp';
        const smartMessage = element('p'); smartMessage.id = 'memorySmartMessage';
        const smartActions = element('div', '', 'smart-actions');
        const smartButton = action('', smartToggle);
        smartButton.id = 'memorySmartToggle';
        const smartRebuild = action('', smartBackfill);
        smartRebuild.id = 'memorySmartRebuild';
        smartActions.append(smartButton, smartRebuild);
        const smartProgress = element('small'); smartProgress.id = 'memorySmartProgress';
        smartPanel.append(smartTitle, smartHelp, smartMessage, smartActions, smartProgress);
        const activityPanel = element('details', '', 'memory-subject-category');
        activityPanel.id = 'memoryOverviewActivities';
        const activityTitle = element('summary', t('activityTitle'));
        activityTitle.id = 'memoryActivityTitle';
        const activityFilter = element('select'); activityFilter.id = 'memoryActivityFilter';
        for (const [kind, label] of [
            ['', 'activityAll'], ['image', 'activityImage'],
            ['video', 'activityVideo'], ['agent', 'activityAgent'],
            ['tool', 'activityTool'],
        ]) {
            const option = element('option');
            option.value = kind;
            option.textContent = t(label);
            activityFilter.append(option);
        }
        const activityLoad = action('', () => loadActivities(false));
        activityLoad.id = 'memoryActivityLoad';
        const activityMore = action('', () => loadActivities(true));
        activityMore.id = 'memoryActivityMore';
        activityMore.hidden = true;
        const activityList = element('div'); activityList.id = 'memoryActivityList';
        activityPanel.append(
            activityTitle, activityFilter, activityLoad,
            activityList, activityMore,
        );
        activityFilter.addEventListener('change', () => {
            if (activityPanel.open) void loadActivities(false);
        });
        const search = element('div', '', 'memory-overview-search');
        const input = element('input'); input.id = 'memoryOverviewSearch'; input.type = 'search';
        const filter = document.createElement('select'); filter.id = 'memoryOverviewFilter';
        for (const source of ['all', ...sources]) {
            const option = document.createElement('option');
            option.value = source; filter.append(option);
        }
        search.append(input, filter);
        const items = element('div'); items.id = 'memoryOverviewItems';
        const status = element('p'); status.id = 'memoryOverviewNotice';
        status.setAttribute('role', 'status');
        mountKnowledge(panel);
        panel.insertBefore(top, panel.children[0]);
        panel.insertBefore(mode, panel.children[1]);
        panel.insertBefore(counts, panel.children[2]);
        panel.insertBefore(layers, panel.children[3]);
        panel.append(smartPanel, activityPanel, search, items, warning, note, status);
        const advanced = element('details'); advanced.id = 'memoryOverviewAdvanced';
        const advancedLabel = element('summary'); advancedLabel.id = 'memoryOverviewAdvancedLabel';
        advanced.append(advancedLabel);
        const insertion = pane.querySelector('.settings-card');
        pane.insertBefore(panel, insertion || null);
        pane.append(advanced);
        foldExpertPanels(pane, advanced);
        const observer = new MutationObserver(() => foldExpertPanels(pane, advanced));
        observer.observe(pane, {childList:true});
        input.addEventListener('input', () => {
            clearTimeout(state.searchTimer);
            state.searchTimer = setTimeout(() => {
                state.query = input.value.trim();
                refresh();
            }, 250);
        });
        filter.addEventListener('change', () => {
            state.filter = filter.value;
            refresh();
        });
        $('memoryManagerTab')?.addEventListener('click', () => { refresh(); });
        document.querySelector('[data-organizer-section="memory"]')
            ?.addEventListener('click', () => refresh());
        syncLabels();
        if (location.pathname === '/settings/memory') refresh();
    }
    fetch('/i18n/memory-overview.json')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data?.de) translations = {en:{...defaults,...(data.en || {})},de:data.de};
            syncLabels();
        })
        .catch(() => {});
    const observer = new MutationObserver(() => {
        if ($('memoryOverview')) observer.disconnect();
        else mount();
    });
    observer.observe(document.documentElement, {childList:true,subtree:true});
    document.addEventListener('mlx-language-changed', syncLabels);
    window.MLXMemoryOverview = {refresh};
    mount();
})();
