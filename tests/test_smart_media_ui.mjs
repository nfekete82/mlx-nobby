import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8'
);
const start = source.indexOf('// Explicit, persisted opt-out for the optional Qwen media planner.');
const end = source.indexOf('async function sendMessage(options = {})', start);
assert.ok(start > 0 && end > start, 'Smart Media functions are accessible for testing');

const values = new Map();
const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, val) => values.set(key, val),
};
const calls = [];
let result = {
    mode: 'smart',
    target: 'image',
    prompt: 'Photorealistic adult blonde woman riding a bicycle at golden hour.',
    model: 'juggernaut-xl',
    negative_prompt: 'extra limbs',
};
let shouldFail = false;
const context = vm.createContext({
    window: {localStorage: storage},
    console: {warn() {}},
    fetch: async (url, options) => {
        calls.push({url, body: JSON.parse(options.body)});
        if (shouldFail) throw new Error('offline');
        return {ok: true, json: async () => result};
    },
});
vm.runInContext(source.slice(start, end), context);
const run = (name, ...args) =>
    vm.runInContext(name, context)(...args);
assert.equal(run('smartMediaPreference'), true, 'default is Smart');
run('setSmartMediaPreference', false);
assert.equal(run('smartMediaPreference'), false, 'user can opt out');
run('setSmartMediaPreference', true);

const originalText = 'Erstelle ein Bild von einer blonden Frau auf dem Fahrrad';
const image = {
    prompt: originalText, resolved_target: 'image',
    active_artifact_id: null,
    quality: 'quality',
    image_options: {model: 'auto', width: 1024, height: 1024},
};
const plannedImage = await run('applySmartMediaPlan', image, 'image', 'none');
assert.equal(plannedImage.prompt, originalText, 'route text remains original');
assert.equal(plannedImage.image_options.model, 'juggernaut-xl');
assert.equal(plannedImage.image_options.negative_prompt, 'extra limbs');
assert.equal(plannedImage.image_options.prompt, result.prompt);
assert.equal(plannedImage.image_options.width, 1024);
assert.equal(calls.at(-1).url, '/api/mlx/chat/media/plan');

const manual = {
    prompt: originalText, image_options: {
        model: 'mlxserve-qwen-image-2.1', negative_prompt: 'user preference',
    },
};
await run('applySmartMediaPlan', manual, 'image', 'none');
assert.equal(manual.image_options.model, 'mlxserve-qwen-image-2.1');
assert.equal(manual.image_options.negative_prompt, 'user preference');

result = {mode: 'smart', target: 'image_edit', model: 'mflux-osaurus-qwen-image-2.1-edit',
    prompt: 'Keep person and facial identity, change background only.',
    negative_prompt: ''};
const edit = {
    prompt: 'Ändere das Bild: anderer Hintergrund',
    active_artifact_id: 'image-abc', resolved_target: 'image_edit',
    image_options: {model: 'auto', strength: 0.5},
};
await run('applySmartMediaPlan', edit, 'image_edit', 'image');
assert.equal(edit.prompt, 'Ändere das Bild: anderer Hintergrund');
assert.equal(edit.active_artifact_id, 'image-abc');
assert.equal(edit.image_options.model, 'mflux-osaurus-qwen-image-2.1-edit');
assert.equal(edit.image_options.strength, 0.5);
assert.equal(edit.image_options.prompt, result.prompt);

result = {mode: 'smart', target: 'video', model: 'auto',
    prompt: 'The person pedals slowly; camera remains static.', negative_prompt: ''};
const video = {
    prompt: 'Mach aus dem Bild ein Video, die Person fährt Fahrrad',
    video_options: {duration: 5, profile: 'standard', aspect_ratio: '9:16'},
    active_artifact_id: 'image-abc',
};
await run('applySmartMediaPlan', video, 'video', 'image');
assert.equal(video.prompt, 'Mach aus dem Bild ein Video, die Person fährt Fahrrad');
assert.equal(video.active_artifact_id, 'image-abc');
assert.equal(video.video_options.duration, 5);
assert.equal(video.video_options.profile, 'standard');
assert.equal(video.video_options.prompt, result.prompt);

shouldFail = true;
const direct = {prompt: 'Keep this direct', image_options: {model: 'auto'}};
await run('applySmartMediaPlan', direct, 'image', 'none');
assert.equal(direct.image_options.prompt, undefined, 'offline fallback is direct');
assert.equal(direct.prompt, 'Keep this direct');
console.log('Smart Media planner UI contracts: image/edit/video, model precedence, opt-out and fallback passed.');
