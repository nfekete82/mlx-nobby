import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const attachmentsSource = fs.readFileSync('frontend/assets/chat/attachments.js', 'utf8');
const scope = {window: {}};
vm.runInNewContext(attachmentsSource, scope, {filename: 'attachments.js'});
const preset = text => {
    const value = scope.window.MLXChatAttachments.suggestPersonReferencePreset(text);
    return value && {...value};
};

const preferred = (prompt, models) =>
    scope.window.MLXChatAttachments.suggestPreferredPersonReferenceModel(
        preset(prompt), models
    );
const model = (id, enabled = true, available = true) => ({id, enabled, available});

test('same identity and a new pose uses Qwen 2.1 Edit, not Juggernaut', () => {
    const poses = [
        'Behalte dieselbe Person und das Gesicht möglichst ähnlich. Neue Ganzkörper-Pose.',
        'Create the same person in a different pose and preserve facial identity.',
        'Create a photorealistic full-body photograph of the exact same adult woman from the reference image.',
        'Erstelle ein neues Ganzkörperfoto derselben Person. Sie steht aufrecht und schaut zur Kamera.'
    ];
    for (const prompt of poses) {
        assert.deepEqual(preset(prompt), {kind: 'same_identity', pose_change: true});
        assert.equal(preferred(prompt, [
            model('juggernaut-xl'),
            model('mflux-osaurus-qwen-image-2.1-edit')
        ]), 'mflux-osaurus-qwen-image-2.1-edit');
    }
});

test('Qwen pose priority respects opt-in model availability and safer fallback', () => {
    const prompt = 'Create a full-body photo of the same woman standing outside';
    const a = model('mflux-osaurus-qwen-image-2.1-edit', false, true);
    const b = model('mflux-qwen-image-2.1-edit', true, true);
    assert.equal(preferred(prompt, [model('juggernaut-xl'), a, b]), b.id);
    assert.equal(preferred(prompt, [model('juggernaut-xl'), a, model(b.id, false)]), null);
    assert.equal(preferred(prompt, [model('juggernaut-xl'), model(a.id, true, false)]), null);
});

test('same-person variations keep Juggernaut defaults and random seed', () => {
    const prompt = 'Behalte dieselbe Person und ihr Gesicht. Erstelle ein ähnliches Porträt.';
    assert.deepEqual(preset(prompt),
        {kind: 'same_identity', strength: 0.75, steps: 40, guidance: 5});
    assert.equal(preferred(prompt, [model('juggernaut-xl')]), 'juggernaut-xl');
});

test('resemblance-only prompts keep distinct conservative defaults', () => {
    assert.deepEqual(
        preset('Erstelle ein neues Bild, das dieser Person ähnelt.'),
        {kind: 'resemblance', strength: 0.55, steps: 36, guidance: 5.5},
    );
    assert.deepEqual(
        preset('Create a portrait of a woman who looks like this person.'),
        {kind: 'resemblance', strength: 0.55, steps: 36, guidance: 5.5},
    );
});

test('unrelated edits do not automatically switch models or sampling', () => {
    assert.equal(preset('Change the background from blue to green.'), null);
    assert.equal(preset('Erstelle ein Bild eines Autos.'), null);
    assert.match(attachmentsSource, /imageMode !== 'edit'/);
    assert.match(attachmentsSource, /model\.id === id && model\.enabled && model\.available/);
    assert.match(attachmentsSource, /if \(!preset \|\| manualEditModel\) return false/);
    assert.match(attachmentsSource, /manualEditFields\.has\(key\)/);
    assert.match(attachmentsSource, /modelOptionsLoaded && editOptions\.model === 'juggernaut-xl'/);
    assert.match(attachmentsSource, /'input', offerPersonReferencePreset/);
});
