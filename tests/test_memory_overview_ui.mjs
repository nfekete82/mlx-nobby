import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/memory-overview.js', import.meta.url), 'utf8',
);
const labels = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/memory-overview.json', import.meta.url), 'utf8',
));

function fixture() {
    const registry = new Map();
    const requests = [];
    class Element {
        constructor(tag = 'div') {
            this.tagName = tag;
            this.children = [];
            this.listeners = new Map();
            this.className = '';
            this.text = '';
            this.value = '';
            this.style = {};
            this.disabled = false;
        }
        set id(value) { this._id = value; registry.set(value, this); }
        get id() { return this._id; }
        set textContent(value) { this.text = String(value); this.children = []; }
        get textContent() { return this.text + this.children.map(el => el.textContent).join(''); }
        get options() { return this.children; }
        get classList() { return {contains: key => this.className.split(' ').includes(key)}; }
        setAttribute() {}
        append(...elements) { this.children.push(...elements); }
        appendChild(node) { this.append(node); return node; }
        replaceChildren(...elements) { this.text = ''; this.children = [...elements]; }
        insertBefore(element, before) {
            const index = this.children.indexOf(before);
            if (index < 0) this.children.push(element);
            else this.children.splice(index, 0, element);
        }
        querySelector(selector) {
            if (selector === '.settings-card') {
                return this.children.find(el => el.className === 'settings-card') || null;
            }
            return null;
        }
        addEventListener(type, callback) { this.listeners.set(type, callback); }
    }
    const pane = new Element();
    pane.id = 'memoryManagerPane';
    const original = new Element();
    original.className = 'settings-card';
    original.id = 'originalAdvancedSettings';
    pane.append(original);
    const tab = new Element('button');
    tab.id = 'memoryManagerTab';
    const response = data => ({ok:true,json:async()=>data});
    const fetch = async (url, options = {}) => {
        requests.push({url, options});
        if (url.endsWith('/status')) return response({
            paused:false,
            counts:{personal:1,legacy:1,archive:2},
            layers:{personal:true,archive:true},
        });
        if (url.includes('/items?')) {
            const params = new URL('https://localhost' + url).searchParams;
            if (params.get('source') === 'personal') return response({
                items:[{id:'p1',subject:'ich',field:'vorliebe',value:'synthetic memory',
                    source_chat_id:'chat-1',source_ordinal:2,status:'active',updated_at:1}],
                total:1,
            });
            if (params.get('source') === 'legacy') return response({
                items:[{id:'l1',text:'synthetic old memory',category:'preference'}],total:1,
            });
            return response({items:[
                {chat_id:'chat-1',ordinal:0,role:'user',content:'archived synthetic turn'},
                {chat_id:'chat-1',ordinal:1,role:'assistant',content:'synthetic reply'},
            ],total:2});
        }
        if (url.endsWith('/pause')) return response({
            paused:JSON.parse(options.body).paused,
        });
        return response({});
    };
    const context = {
        window:{},
        document:{
            getElementById:id=>registry.get(id),
            createElement:tag=>new Element(tag),
            head:new Element('head'),
            documentElement:new Element(),
            querySelector:()=>null,
            addEventListener:()=>{},
        },
        fetch,
        MutationObserver:class {observe(){} disconnect(){}},
        location:{pathname:'/chat'},
        setTimeout,
        clearTimeout,
        URL,
        console,
    };
    vm.runInNewContext(source, context);
    return {registry,requests,context};
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('labels are translated and dashboard exposes non-destructive pause', async () => {
    assert.deepEqual(Object.keys(labels.de).sort(), Object.keys(labels.en).sort());
    const {registry,requests} = fixture();
    assert.ok(registry.has('memoryOverview'));
    assert.ok(registry.has('memoryOverviewAdvanced'));
    assert.equal(registry.get('memoryOverviewAdvanced').children.some(
        el => el.id === 'originalAdvancedSettings'), true);
    registry.get('memoryManagerTab').listeners.get('click')();
    await tick();
    await tick();
    assert.match(registry.get('memoryOverviewItems').textContent, /synthetic memory/);
    assert.match(registry.get('memoryOverviewItems').textContent, /synthetic reply/);
    const toggle = registry.get('memoryOverviewToggle');
    await toggle.listeners.get('click')();
    assert.ok(requests.some(x => x.url.endsWith('/pause') &&
        x.options.method === 'POST' && JSON.parse(x.options.body).paused === true));
    assert.equal(toggle.textContent, 'Resume memory');
});

test('UI never invokes destructive legacy config when pausing', async () => {
    const {registry,requests} = fixture();
    await registry.get('memoryOverviewToggle').listeners.get('click')();
    assert.equal(requests.filter(x => /\/archive\/config|\/personal\/config/.test(x.url)).length,0);
});

test('semantic dashboard groups facts and hides archive behind disclosure', async () => {
    const {registry,requests} = fixture();
    registry.get('memoryManagerTab').listeners.get('click')();
    await tick();
    await tick();
    assert.ok(registry.has('memorySmartToggle'));
    assert.ok(registry.has('memorySmartRebuild'));
    const rendered = registry.get('memoryOverviewItems').textContent;
    assert.match(rendered, /About me/);
    assert.match(rendered, /Preference/);
    assert.doesNotMatch(rendered, /vorliebe\.[0-9a-f]+/);
    assert.match(rendered, /Chat archive/);
    assert.match(rendered, /archived synthetic turn/);
    const enable = registry.get('memorySmartToggle');
    await enable.listeners.get('click')();
    assert.ok(requests.some(r => r.url.endsWith('/smart/config')
        && r.options.method === 'POST'
        && JSON.parse(r.options.body).enabled === true));
    assert.equal(enable.textContent, 'Disable Qwen learning');
});
