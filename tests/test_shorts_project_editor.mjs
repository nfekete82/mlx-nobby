import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.textContent = ''; this.className = ''; this.disabled = false; this.dataset = {}; this.style = {};
        const classes = new Set(); this.classList = { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c), toggle: (c,on) => on ? classes.add(c) : classes.delete(c) }; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    replaceChildren(...children) { this.children = children; }
    setAttribute() {}
    addEventListener(name,fn) { (this.listeners[name] ||= []).push(fn); }
    async fire(name,event = {}) { for (const fn of this.listeners[name] || []) await fn(event); }
    querySelectorAll(selector) {
        const tags = selector.split(',');
        return this.children.flatMap(c => [...(tags.includes(c.tagName) ? [c] : []), ...c.querySelectorAll(selector)]);
    }
}
function harness(options = {}) {
    const calls = [], drafts = new Map();
    const head = new Element('head'), body = new Element('body');
    const project = { schema_version:2, title:'Neuer Short', duration:20, language:'de', quality:'fast', briefing:'', voice_enabled:false, voice:null, voice_speed:1,
        music_enabled:false, music_style:null, music_track:null, music_volume:.18,music_mode:'scene',subtitles_enabled:true, captions:{position:'bottom',size:54,style:'bold'},
        consistency_mode:true,character_consistency:true,style_consistency:true,style_strength:.8,visual_bible:null,
        scenes:Array.from({length:4},(_,i) => ({id:'scene-'+i,title:'',duration:5,description:'',video_prompt:'',camera:'',narration:'',caption:'',voice_enabled:true,
            transition:{type:'cut',duration:0},music:null,sfx:{enabled:false,track:null,volume:.5,offset:0}})) };
    const caps={qualities:{fast:{durations:[5,6,8,10,20]},standard:{durations:[5,6,8,10]},quality:{durations:[5]}},music:[],sfx:[],transitions:['cut','fade','fadeblack','fadewhite','flash']};
    const fetch = async (path,init={}) => {
        calls.push({path,init});await options.beforeRequest?.(path,init);const data=init.body ? JSON.parse(init.body) : {};
        const status = options.status?.(path, init) || 200;
        if (status !== 200) return { ok: false, status, json: async () => ({ detail: '{"detail":"Short nicht gefunden"}' }) };
        let result;
        if (path.endsWith('/capabilities')) result=caps;
        else if(path.endsWith('/preflight')) result=options.preflight || {available:true,warnings:[],models:[]};
        else if(path.endsWith('/drafts') && init.method === 'POST') {
            const id = String(drafts.size+1); const d={id,kind:'shorts_draft',version:1,project:structuredClone(data.project || project)};drafts.set(id,d);result={draft:d};
        } else if (path.endsWith('/drafts')) result={drafts:[...drafts.values()]};
        else if (path.endsWith('/render')) result={job:{id:'job',status:'queued',project:drafts.get(path.split('/').at(-2)).project}};
        else if (path.endsWith('/plan')) {
            const d=drafts.get(path.split('/').at(-2));d.version++;d.project.scenes.forEach(s=>{s.video_prompt='Luxury office';s.caption='COFFEE';});result={draft:d};
        } else {
            const id=path.split('/').at(-1), d=drafts.get(id);
            if (!d) return { ok:false, status:404, json:async()=>({detail:'Short nicht gefunden'}) };
            if(init.method==='DELETE') drafts.delete(id);
            if(init.method==='PUT') {d.project=structuredClone(data.project);d.version++;}
            result={draft:d};
        }
        return {ok:true,status:200,json:async()=>structuredClone(result)};
    };
    const preferenceStore = new Map(Object.entries(options.preferences || {}));
    const window={__MLXShortsStudioTranslations:JSON.parse(fs.readFileSync('frontend/i18n/shorts-studio.json','utf8')),setTimeout:options.timers?.setTimeout,clearTimeout:options.timers?.clearTimeout,localStorage:{getItem:key=>preferenceStore.get(key),setItem:(key,value)=>preferenceStore.set(key,value)},fetch, location:{origin:'http://localhost'}, MLXConfirm:async()=>true, MLXI18n:{getLanguage:()=> 'de'},MLXShortsStudio:{setActiveJob(){},openJob(){}},MLXShortsHistory:{open(){}}};
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/shorts-project-editor.js','utf8'), {window,document:{head,body,readyState:'loading',querySelector:()=>null,addEventListener(){},createElement:t=>new Element(t)},fetch,console});
    const buttons=()=>body.querySelectorAll('button');
    const click=async text=> {const b=buttons().find(b=>b.textContent===text);assert.ok(b,text);assert.equal(b.disabled,false,text+' enabled');await b.fire('click');};
    const expert = async (enabled=true) => {
        const label = body.querySelectorAll('label').find(el => el.children[0]?.textContent === 'Expertenmodus');
        const input = label.children[1]; input.checked = enabled; await input.fire('input');
    };
    return {window,body,head,calls,drafts,buttons,click,expert,fetch,preferenceStore,timers:options.timers, document:{head,body,readyState:'loading',querySelector:()=>null,addEventListener(){},createElement:t=>new Element(t)}};
}

test('Studio opens without a job, creates one server draft, edits scenes and plans without rendering',async()=>{
    const h=harness();await h.window.MLXShortsProjectEditor.newDraft();
    assert.equal(h.calls.filter(c=>c.init.method==='POST' && c.path.endsWith('/drafts')).length,1);
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,true);
    await h.expert();
    await h.click('+ Szene');
    await h.click('Duplizieren');
    await h.click('↑');
    await h.click('↓');
    await h.click('Löschen');
    await h.click('Draft speichern');
    assert.equal(h.drafts.get('1').project.scenes.length,5);
    await h.click('Löschen');
    await h.click('Mit KI planen');
    assert.equal(h.calls.some(c=>c.path.endsWith('/render')),false);
    assert.equal(h.drafts.get('1').project.scenes.length,4);
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,false);
    await h.click('Short rendern');
    assert.equal(h.calls.filter(c=>c.path.endsWith('/render')).length,1);
});

test('publication duration is rejected immediately and captions do not need narration',async()=>{
    const h=harness();await h.window.MLXShortsProjectEditor.newDraft();await h.click('Mit KI planen');
    const p=structuredClone(h.drafts.get('1').project);p.quality='quality';
    assert.equal(h.window.MLXShortsProjectEditor.__test.errors(p).length,0);
    p.scenes[0].duration=6;p.duration=21;
    assert.ok(h.window.MLXShortsProjectEditor.__test.errors(p).some(e=>e.includes('Dauer passt nicht')));
});

test('chat short branch plans once and returns before action execution or normal chat', async()=>{
    const source=fs.readFileSync('frontend/assets/chat/generation.js','utf8');
    const start=source.indexOf("            if (resolvedTarget === 'shorts_generate') {");
    const end=source.indexOf("            if (resolvedTarget === 'chat' &&",start);
    assert.ok(start>=0 && end>start);
    const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
    const branch=new AsyncFunction('resolvedTarget','fetch','session','userMessage','prompt','MLXChatSessions','MLXChatRendering','window','execute','gt',source.slice(start,end)+'\nexecute();');
    const message={},session={id:'chat',messages:[message]},calls=[];let executions=0,opened=0;
    await branch('shorts_generate',async path=>{calls.push(path);return {ok:true,json:async()=>({draft:{id:'draft'}})};},session,message,'Create a short',
        {currentSession:()=>session,saveSessions(){}},{renderAll(){}},{MLXShortsStudio:{openDraft:async()=>{opened++;}}},()=>executions++,(_key,fallback)=>fallback);
    assert.deepEqual(calls,['/api/mlx/shorts/plan']);assert.equal(executions,0);assert.equal(opened,1);assert.equal(session.messages.length,2);
});

function textContent(el) { return el.textContent + el.children.map(textContent).join(' '); }

for (const existing of ['empty', 'drafts', 'jobs', 'both', 'stale']) {
    test(`normal Studio open has welcome and no resource fetch (${existing})`, async () => {
        const h = harness();
        if (existing === 'drafts' || existing === 'both' || existing === 'stale') await h.window.MLXShortsProjectEditor.newDraft();
        const jobs = [];
        h.window.MLXShortsStudio.clearActiveJob = () => jobs.splice(0);
        if (existing === 'jobs' || existing === 'both' || existing === 'stale') jobs.push({ id: 'old-job' });
        h.calls.length = 0;
        await h.window.MLXShortsProjectEditor.open();
        assert.equal(h.calls.length, 0);
        assert.equal(jobs.length, 0);
        assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft, null);
        assert.ok(textContent(h.body).includes('Dein nächster Short'));
        assert.ok(!textContent(h.body).includes('detail'));
        await h.click('Neuer Short');
        assert.equal(h.calls.some(c => c.path.includes('shorts-jobs') || c.path.endsWith('/render')), false);
    });
}

test('missing selected draft recovers to welcome and New Short remains usable', async () => {
    const h = harness();
    await h.window.MLXShortsProjectEditor.open({ id: 'stale-draft', kind: 'shorts_draft' });
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft, null);
    assert.ok(textContent(h.body).includes('nicht mehr vorhanden'));
    assert.ok(!textContent(h.body).includes('detail'));
    await h.click('Neuer Short');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().view, 'editor');
});

test('draft list and draft selection never use source job endpoint', async () => {
    const h = harness(); await h.window.MLXShortsProjectEditor.newDraft();
    h.drafts.get('1').source_job_id = 'stale-job';
    await h.click('Meine Entwürfe'); h.calls.length = 0;
    await h.click('Laden');
    assert.ok(h.calls.some(c => c.path === '/api/mlx/shorts/drafts/1'));
    assert.equal(h.calls.some(c => c.path.includes('shorts-jobs') || c.path.endsWith('stale-job')), false);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().sourceJob, null);
});

test('job payload cannot open a draft and no draft ID is inferred from it', async () => {
    const h = harness();
    await h.window.MLXShortsProjectEditor.open({ id: 'job', kind: 'shorts', project: {} });
    assert.equal(h.calls.length, 0);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft, null);
    assert.ok(!textContent(h.body).includes('detail'));
});

test('explicit deletion resets welcome; a failed save preserves the editor', async () => {
    const h = harness(); await h.window.MLXShortsProjectEditor.newDraft();
    await h.expert();
    await h.click('Entwurf löschen');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft, null);
    assert.ok(textContent(h.body).includes('Dein nächster Short'));
    await h.click('Neuer Short'); h.drafts.clear();
    await h.click('Draft speichern');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.id, '1');
    assert.ok(textContent(h.body).includes('nicht mehr vorhanden'));
    assert.ok(!textContent(h.body).includes('detail'));
    await h.click('Neuer Short');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.id, '1');
});

test('server error is human readable and does not disable New Short permanently', async () => {
    let fail = true;
    const h = harness({status: path => fail && path.endsWith('/capabilities') ? 500 : 200});
    await h.window.MLXShortsProjectEditor.newDraft();
    assert.ok(textContent(h.body).includes('derzeit nicht verfügbar'));
    assert.ok(!textContent(h.body).includes('detail'));
    fail = false; await h.click('Neuer Short');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().view, 'editor');
});

function installController(h) {
    h.window.__MLXShortsStudioTranslations = JSON.parse(fs.readFileSync('frontend/i18n/shorts-studio.json', 'utf8'));
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/shorts-studio.js','utf8'), {
        window:h.window, document:h.document, URL, console, setTimeout:h.timers?.setTimeout || setTimeout, clearTimeout:h.timers?.clearTimeout || clearTimeout
    });
    return h.window.MLXShortsStudio;
}

test('controller opens start despite a selected legacy job and rejects draft job payloads', async () => {
    const h = harness(); const studio = installController(h);
    studio.setActiveJob({id:'job',kind:'shorts',status:'completed',project:{title:'Short',scenes:[{id:'scene'}]}});
    await studio.open();
    assert.equal(studio.getActiveJob(), null);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft, null);
    assert.equal(h.calls.length, 0);
    assert.equal(studio.extractJob({id:'draft',kind:'shorts_draft',project:{scenes:[]}}), null);
});

test('explicit missing job selection recovers without fetching draft endpoints', async () => {
    const h = harness({status: path => path.includes('/shorts-jobs/') ? 404 : 200});
    const studio = installController(h);
    assert.equal(await studio.loadJob('stale-job'), false);
    assert.equal(studio.getActiveJob(), null);
    assert.deepEqual(h.calls.map(c=>c.path), ['/api/mlx/shorts-jobs/stale-job']);
    assert.ok(!textContent(h.body).includes('detail'));
    assert.ok(textContent(h.body).includes('nicht mehr vorhanden'));
    await h.click('Neuer Short');
});

test('history selection loads only explicit job endpoint; deletion clears active job', async () => {
    const h = harness();
    const originalFetch=h.window.fetch;
    h.window.fetch=async (path,init) => {
        if(path.includes('/shorts-jobs/')) {
            h.calls.push({path,init});
            return {ok:true,status:200,json:async()=> init?.method==='DELETE' ? {deleted_job_ids:['selected-job']} :
                {job:{id:'selected-job',kind:'shorts',status:'completed',project:{title:'Selected',scenes:[{id:'s'}]}}}};
        }
        if(path.includes('/shorts-jobs?')) return {ok:true,json:async()=>({projects:[]})};
        return originalFetch(path,init);
    };
    const studio=installController(h);
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/shorts-history.js','utf8'), {
        window:h.window,document:h.document,console,setTimeout,clearTimeout
    });
    await h.window.MLXShortsHistory.__test.openProject({id:'selected-job'});
    assert.equal(studio.getActiveJob().id,'selected-job');
    assert.deepEqual(h.calls.map(c=>c.path), ['/api/mlx/shorts-jobs/selected-job']);
    await h.window.MLXShortsHistory.__test.deleteProject({id:'selected-job',status:'completed'});
    assert.equal(studio.getActiveJob(),null);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().view,'welcome');
    assert.equal(h.calls.some(c=>c.path.includes('/drafts/')),false);
});


test('missing video preview shows placeholder while Studio remains usable', async () => {
    const h = harness(); const studio = installController(h);
    studio.setActiveJob({id:'job',kind:'shorts',status:'completed',project:{title:'Short',scenes:[{id:'scene'}]},
        scene_results:[{scene_id:'scene',status:'completed',path:'/gone.mp4'}]});
    const videos = h.body.querySelectorAll('video');
    assert.ok(videos.length >= 2);
    for (const video of videos) await video.fire('error');
    assert.ok(textContent(h.body).includes('Vorschau nicht verfügbar'));
    assert.ok(!textContent(h.body).includes('detail'));
    await studio.open(); await h.click('Neuer Short');
});

test('job server errors show readable feedback and leave start usable', async () => {
    const h = harness({status:path => path.includes('/shorts-jobs/') ? 500 : 200});
    const studio = installController(h);
    await assert.rejects(studio.loadJob('job'), /derzeit nicht verfügbar/);
    assert.ok(textContent(h.body).includes('derzeit nicht verfügbar'));
    assert.ok(!textContent(h.body).includes('detail'));
    await h.click('Neuer Short');
});

function labelFields(h) { return h.body.querySelectorAll('label').map(el=>el.children[0]?.textContent); }
function inputFor(h,label) { const el=h.body.querySelectorAll('label').find(el=>el.children[0]?.textContent===label); assert.ok(el,label); return el.children[1]; }

test('fresh draft defaults to simple fields, experts toggle and preference alone is persisted', async()=>{
    const h=harness(); await h.window.MLXShortsProjectEditor.newDraft();
    const forbidden=['Video Prompt','Kamera / Bewegung','Caption Position','Caption Größe','Caption Stil','Voice Geschwindigkeit','Voice-Profil','Soundeffekt Track','Stilstärke (0–1)','Visual Bible · Charakter'];
    assert.equal(inputFor(h,'Expertenmodus').checked,false);
    forbidden.forEach(label=>assert.ok(!labelFields(h).includes(label),label));
    assert.ok(labelFields(h).includes('Stil') && labelFields(h).includes('Was passiert?'));
    const musicSelection = h.window.MLXShortsProjectEditor.__test.getState().draft.project.music_selection;
    await h.expert();
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.project.music_selection, musicSelection);
    forbidden.forEach(label=>assert.ok(labelFields(h).includes(label),label));
    assert.equal(h.preferenceStore.get('mlx-shorts-expert-mode'),'true');
    assert.equal(h.preferenceStore.size,1);
    const prompt=inputFor(h,'Video Prompt');prompt.value='Updated office scene';await prompt.fire('input');
    const camera=inputFor(h,'Kamera / Bewegung');camera.value='tracking shot';await camera.fire('input');
    await h.click('Draft speichern');
    assert.equal(h.drafts.get('1').project.scenes[0].video_prompt,'Updated office scene');
    assert.equal(h.drafts.get('1').project.scenes[0].camera,'tracking shot');
    await h.expert(false);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.project.music_selection, musicSelection);
    forbidden.forEach(label=>assert.ok(!labelFields(h).includes(label),label));
    assert.equal(h.preferenceStore.get('mlx-shorts-expert-mode'),'false');
    const resumed=harness({preferences:{'mlx-shorts-expert-mode':'true'}}); await resumed.window.MLXShortsProjectEditor.newDraft();
    assert.ok(labelFields(resumed).includes('Video Prompt'));
});

test('complete AI plan enables simple render despite missing optional audio with a warning',async()=>{
    const h=harness();await h.window.MLXShortsProjectEditor.newDraft();await h.click('Mit KI planen');
    const state=h.window.MLXShortsProjectEditor.__test.getState();
    state.draft.project.music_selection='auto';state.draft.project.music_enabled=true;
    state.draft.project.music_track='missing.wav';
    state.draft.project.scenes[0].sfx={enabled:true,track:null,volume:.5,offset:0};
    h.window.MLXShortsProjectEditor.refreshLanguage();
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,false);
    assert.ok(textContent(h.body).includes('Bereit zum Rendern'));
    assert.ok(textContent(h.body).includes('Keine passende lokale Musik'));
    assert.ok(!labelFields(h).includes('Soundeffekt Track'));
    state.draft.project.duration=21;h.window.MLXShortsProjectEditor.refreshLanguage();
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,true);
    assert.ok(textContent(h.body).includes('Die Gesamtdauer passt nicht'));
    state.draft.project.duration=20;state.draft.project.scenes[0].video_prompt='';
    h.window.MLXShortsProjectEditor.refreshLanguage();
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,true);
});

test('provider preflight warns about anchor fallback and blocks unavailable keyframes without exposing technical controls',async()=>{
    const h=harness({preflight:{available:true,warnings:['character_anchor_fallback'],models:[]}});
    await h.window.MLXShortsProjectEditor.newDraft();await h.click('Mit KI planen');
    assert.ok(textContent(h.body).includes('Character-Anker nicht verfügbar'));
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,false);
    assert.ok(!labelFields(h).includes('Video Prompt'));
    const blocked=harness({preflight:{available:false,warnings:[],models:[]}});
    await blocked.window.MLXShortsProjectEditor.newDraft();await blocked.click('Mit KI planen');
    assert.equal(blocked.buttons().find(b=>b.textContent==='Short rendern').disabled,true);
    assert.ok(textContent(blocked.body).includes('Kein kompatibler Keyframe-Generator'));
});

test('autosave coalesces edits and shows saved state while retaining simple mode',async()=>{
    const callbacks=new Map();let counter=0;
    const h=harness({timers:{setTimeout:fn=>{callbacks.set(++counter,fn);return counter;},clearTimeout:id=>callbacks.delete(id)}});
    await h.window.MLXShortsProjectEditor.newDraft();
    const title=inputFor(h,'Titel');title.value='Office Benefits #1';await title.fire('input');
    title.value='Office Benefits #2';await title.fire('input');
    const music=inputFor(h,'Musik');music.value='off';await music.fire('input');
    assert.equal(callbacks.size,1);assert.ok(textContent(h.body).includes('Ungespeichert'));
    const [id,callback]=[...callbacks.entries()][0];callbacks.delete(id);await callback();
    assert.equal(h.drafts.get('1').project.title,'Office Benefits #2');
    assert.equal(h.drafts.get('1').project.music_mode,'off');
    assert.ok(textContent(h.body).includes('Gespeichert'));
    assert.ok(!labelFields(h).includes('Video Prompt'));
});

function installHistory(h) {
    h.window.__MLXShortsStudioTranslations=JSON.parse(fs.readFileSync('frontend/i18n/shorts-studio.json','utf8'));
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/shorts-history.js','utf8'),{
        window:h.window,document:h.document,console,setTimeout,clearTimeout
    });
    return h.window.MLXShortsHistory;
}

test('history error stays human readable and safe technical diagnosis is in collapsed Details',()=>{
    const h=harness();const history=installHistory(h);
    const card=history.__test.renderProject({id:'job',title:'Office',status:'failed',phase:'failed',scene_count:4,current_scene:1,
        error:'RAW PROMPT /private/secret',error_stage:'keyframe',error_scene_number:2,error_code:'IMAGE_PROVIDER_INCOMPATIBLE',
        error_provider:'mflux',error_model:'qwen-edit',error_detail_safe:'Missing --image-paths'});
    assert.ok(textContent(card).includes('Szene 2 von 4'));
    assert.ok(textContent(card).includes('Keyframe-Generator ist mit der installierten MFLUX-Version'));
    assert.ok(!textContent(card).includes('RAW PROMPT'));
    const details=card.querySelectorAll('details')[0];assert.ok(details);assert.ok(!details.open);
    assert.ok(textContent(details).includes('--image-paths'));
    assert.ok(card.querySelectorAll('button').some(b=>b.textContent==='Erneut versuchen'));
});

test('history progress shows scene, phase, percent and elapsed time; retry uses a new revision response',async()=>{
    const h=harness();const history=installHistory(h);
    const card=history.__test.renderProject({id:'job',title:'Office',status:'running',phase:'video',scene_count:4,current_scene:1,
        progress:.35,started_at:Date.now()/1000-65});
    assert.ok(textContent(card).includes('Szene 2 von 4') && textContent(card).includes('Video wird gerendert'));
    assert.ok(textContent(card).includes('35%') && textContent(card).includes('Vergangene Zeit'));
    assert.equal(card.querySelectorAll('progress')[0].value,.35);
    let selected=null;h.window.MLXShortsStudio.setActiveJob=job=>selected=job;
    h.window.fetch=async(path,init)=>{h.calls.push({path,init});return {ok:true,json:async()=>({job:{id:'revision',parent_job_id:'job'}})};};
    await history.__test.retryProject({id:'job'});
    assert.equal(selected.id,'revision');assert.equal(selected.parent_job_id,'job');
    assert.equal(h.calls.at(-1).path,'/api/mlx/shorts-jobs/job/retry');
});


test('job viewer percent progress is normalized for the shared history status renderer',()=>{
    const h=harness();const history=installHistory(h);
    const panel=new Element('div');
    history.renderJobStatus(panel,{status:'running',phase:'keyframe',current_scene:1,scene_count:4,progress:25,progress_percent:25});
    assert.equal(panel.querySelectorAll('progress')[0].value,.25);
    assert.ok(textContent(panel).includes('25%') && !textContent(panel).includes('2500%'));
});


test('completed history duplication accepts the actual nested job response and opens a server draft',async()=>{
    const h=harness();const history=installHistory(h);let opened=null;
    const project={title:'Office',duration:20,scenes:[]};
    h.window.MLXShortsStudio.openDraft=async draft=>opened=draft;
    h.window.fetch=async(path,init={})=>{
        h.calls.push({path,init});
        return {ok:true,json:async()=>path.endsWith('/drafts') ? {draft:{id:'copy',project}} :
            {data:{job:{id:'completed',status:'completed',project,chat_id:'studio'}}}};
    };
    await history.__test.duplicateProject({id:'completed'});
    const body=JSON.parse(h.calls[1].init.body);
    assert.deepEqual(body.project,project);assert.equal(body.source_job_id,'completed');
    assert.equal(opened.id,'copy');
});

function fakeTimers() {
    let sequence = 0;
    const callbacks = new Map();
    return {callbacks, setTimeout(fn) {callbacks.set(++sequence, fn); return sequence;}, clearTimeout(id) {callbacks.delete(id);}};
}
function deferred() { let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve}; }
async function changeTitle(h, title) { const input = inputFor(h,'Titel'); input.value=title; await input.fire('input'); }

test('pending autosave is flushed before History and its obsolete callback cannot save another draft', async()=>{
    const timers=fakeTimers(), h=harness({timers}); let historyOpened=0;
    h.window.MLXShortsHistory.open=()=>historyOpened++;
    await h.window.MLXShortsProjectEditor.newDraft();
    await changeTitle(h,'Keep this title');
    const obsolete=[...timers.callbacks.values()][0];
    await h.click('Meine Shorts / Verlauf');
    assert.equal(h.drafts.get('1').project.title,'Keep this title');
    assert.equal(historyOpened,1);assert.equal(timers.callbacks.size,0);
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft,null);
    await h.window.MLXShortsProjectEditor.newDraft();
    await obsolete();
    assert.equal(h.calls.filter(c=>c.init.method==='PUT').length,1);
    assert.equal(h.drafts.get('2').project.title,'Neuer Short');
});

test('render and closing flush the newest editor state before continuing',async()=>{
    const h=harness({timers:fakeTimers()});await h.window.MLXShortsProjectEditor.newDraft();await h.click('Mit KI planen');
    await changeTitle(h,'Latest render title');
    let selected;h.window.MLXShortsStudio.setActiveJob=job=>selected=job;
    await h.click('Short rendern');
    assert.equal(selected.project.title,'Latest render title');
    const requests=h.calls.filter(c=>c.init.method==='PUT' || c.path.endsWith('/render'));
    assert.equal(requests.at(-2).init.method,'PUT');assert.ok(requests.at(-1).path.endsWith('/render'));
    await h.window.MLXShortsProjectEditor.open({id:'1',kind:'shorts_draft'});
    await changeTitle(h,'Latest close title');await h.click('Schließen');
    assert.equal(h.drafts.get('1').project.title,'Latest close title');
});

test('in-flight autosave and external navigation serialize without duplicate or late saves', async()=>{
    const started=deferred(), release=deferred(), timers=fakeTimers();
    const h=harness({timers,beforeRequest:async(_path,init)=>{if(init.method==='PUT'){started.resolve();await release.promise;}}});
    await h.window.MLXShortsProjectEditor.newDraft();await changeTitle(h,'Saved before switch');
    const callback=[...timers.callbacks.values()][0];timers.callbacks.clear();
    const saving=callback();await started.promise;
    const navigating=h.window.MLXShortsProjectEditor.newDraft();
    assert.equal(h.drafts.size,1);release.resolve();await saving;await navigating;
    assert.equal(h.drafts.size,2);assert.equal(h.drafts.get('1').project.title,'Saved before switch');
    assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.id,'2');
    await callback();
    assert.equal(h.calls.filter(c=>c.init.method==='PUT').length,1);
    assert.equal(h.drafts.get('2').project.title,'Neuer Short');
});

for (const status of [409,500]) test(`failed navigation save preserves edits and visibly blocks navigation (${status})`,async()=>{
    const h=harness({timers:fakeTimers(),status:(_path,init)=>init.method==='PUT'?status:200});let opened=0;
    h.window.MLXShortsHistory.open=()=>opened++;
    await h.window.MLXShortsProjectEditor.newDraft();await changeTitle(h,'Do not lose this');
    await h.click('Meine Shorts / Verlauf');
    assert.equal(opened,0);assert.equal(h.window.MLXShortsProjectEditor.__test.getState().draft.project.title,'Do not lose this');
    assert.ok(textContent(h.body).includes(status===500?'derzeit nicht verfügbar':'Eingaben prüfen'));
    assert.ok(!textContent(h.body).includes('"detail"'));
});

test('explicit job navigation flushes the active draft before requesting the selected job',async()=>{
    const started=deferred(), release=deferred();
    const h=harness({timers:fakeTimers(),beforeRequest:async(_path,init)=>{if(init.method==='PUT'){started.resolve();await release.promise;}}});
    await h.window.MLXShortsProjectEditor.newDraft();await changeTitle(h,'Persist before job selection');
    const original=h.window.fetch;h.window.fetch=async(path,init)=>path.includes('/shorts-jobs/')
        ? (h.calls.push({path,init}),{ok:true,json:async()=>({job:{id:'chosen',status:'completed',project:{scenes:[]}}})}) : original(path,init);
    const studio=installController(h), navigating=studio.loadJob('chosen');await started.promise;
    assert.equal(h.calls.some(c=>c.path.endsWith('/chosen')),false);
    release.resolve();assert.equal(await navigating,true);
    assert.equal(h.drafts.get('1').project.title,'Persist before job selection');assert.equal(studio.getActiveJob().id,'chosen');
});

test('older job selection and older polling response cannot overwrite the explicitly selected job',async()=>{
    const h=harness({timers:fakeTimers()}), responses=new Map();
    h.window.fetch=(path)=>{const pending=deferred();responses.set(path,pending);return pending.promise;};
    const studio=installController(h), older=studio.loadJob('B');
    await new Promise(r=>setImmediate(r));const newer=studio.loadJob('A');await new Promise(r=>setImmediate(r));
    const response=id=>({ok:true,json:async()=>({job:{id,status:'completed',project:{scenes:[]}}})});
    responses.get('/api/mlx/shorts-jobs/A').resolve(response('A'));assert.equal(await newer,true);
    responses.get('/api/mlx/shorts-jobs/B').resolve(response('B'));assert.equal(await older,false);
    assert.equal(studio.getActiveJob().id,'A');
    studio.setActiveJob({id:'B',status:'running',project:{scenes:[]}});
    const poll=[...h.timers.callbacks.values()][0];h.timers.callbacks.clear();const polling=poll();
    studio.setActiveJob({id:'A',status:'completed',project:{scenes:[]}});
    responses.get('/api/mlx/shorts-jobs/B').resolve(response('B'));await polling;
    assert.equal(studio.getActiveJob().id,'A');
});

test('cancel sends the clicked project ID and unknown HTTP errors never reveal raw details',async()=>{
    const h=harness(), history=installHistory(h);h.window.fetch=async(path,init)=>{
        h.calls.push({path,init});return {ok:true,json:async()=>({projects:[]})};
    };
    const card=history.__test.renderProject({id:'correct-job',status:'running'});
    await card.querySelectorAll('button').find(b=>b.textContent==='Abbrechen').fire('click',{stopPropagation(){}});
    assert.equal(h.calls[0].path,'/api/system/job-queue/shorts/correct-job/cancel');
    h.window.fetch=async()=>({ok:false,status:400,json:async()=>({detail:'Traceback /private/secret'})});
    await assert.rejects(history.__test.retryProject({id:'correct-job'}), /Aktion/);
});

test('a source revision defers resource preflight to the backend after reuse comparison',async()=>{
    const h=harness({preflight:{available:false,warnings:[],models:[]}});
    await h.window.MLXShortsProjectEditor.newDraft();
    h.drafts.get('1').source_job_id='completed-source';
    h.drafts.get('1').project.scenes.forEach(scene=>scene.video_prompt='Existing scene');
    await h.window.MLXShortsProjectEditor.open({id:'1',kind:'shorts_draft'});
    assert.equal(h.buttons().find(b=>b.textContent==='Short rendern').disabled,false);
    await h.click('Short rendern');assert.equal(h.calls.filter(c=>c.path.endsWith('/render')).length,1);
});

test('late History retry and duplicate responses do not replace a newer selection',async()=>{
    const h=harness(), history=installHistory(h), release=deferred();let token=1, opened=0;
    h.window.MLXShortsStudio.selectionToken=()=>token;
    h.window.MLXShortsStudio.setActiveJob=()=>opened++;
    h.window.fetch=async()=>{await release.promise;return {ok:true,json:async()=>({job:{id:'revision'}})};};
    const retry=history.__test.retryProject({id:'old'});token++;release.resolve();await retry;assert.equal(opened,0);
    const duplicateRelease=deferred();h.window.fetch=async()=>{await duplicateRelease.promise;return {ok:true,json:async()=>({job:{id:'old',status:'completed',project:{scenes:[]}}})};};
    const duplicate=history.__test.duplicateProject({id:'old'});token++;duplicateRelease.resolve();await duplicate;
    assert.equal(opened,0);
});

test('editor labels use complete shared German/English translations and can switch language',async()=>{
    const strings=JSON.parse(fs.readFileSync('frontend/i18n/shorts-studio.json','utf8'));
    assert.deepEqual(Object.keys(strings.de).sort(),Object.keys(strings.en).sort());
    const h=harness();await h.window.MLXShortsProjectEditor.newDraft();
    assert.ok(textContent(h.body).includes('Gesamtdauer'));
    h.window.MLXI18n.getLanguage=()=> 'en';h.window.MLXShortsProjectEditor.refreshLanguage();
    assert.ok(textContent(h.body).includes('Total duration'));
    assert.ok(!textContent(h.body).includes('editor_'));
});

test('successful History cancellation reloads server status without retrying or duplicating', async () => {
    const h = harness(), history = installHistory(h);
    let cancelled = false;
    h.window.fetch = async (path, init = {}) => {
        h.calls.push({path, init});
        if (path.endsWith('/cancel')) {
            assert.equal(init.method, 'POST');
            cancelled = true;
            return {ok: true, json: async () => ({ok: true, kind: 'shorts', job: {id: 'active', status: 'cancelled'}})};
        }
        assert.equal(path, '/api/mlx/shorts-jobs?limit=100');
        return {ok: true, json: async () => ({projects: [{id: 'active', title: 'Cancelled fixture', status: cancelled ? 'cancelled' : 'running'}]})};
    };
    const card = history.__test.renderProject({id: 'active', status: 'running'});
    await card.querySelectorAll('button').find(b => b.textContent === 'Abbrechen').fire('click', {stopPropagation() {}});
    assert.equal(cancelled, true);
    assert.deepEqual(h.calls.map(c => c.path), [
        '/api/system/job-queue/shorts/active/cancel', '/api/mlx/shorts-jobs?limit=100'
    ]);
    assert.equal(h.calls.filter(c => c.init.method === 'POST').length, 1);
    assert.equal(history.getProjects()[0].status, 'cancelled');
    const updated = history.__test.renderProject(history.getProjects()[0]);
    assert.ok(!updated.querySelectorAll('button').some(b => b.textContent === 'Abbrechen'));
});
