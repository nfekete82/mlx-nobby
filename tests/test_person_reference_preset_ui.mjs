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

test('same-person face and different-pose prompts get Juggernaut pose defaults', () => {
    assert.deepEqual(
        preset('Behalte dieselbe Person und das Gesicht möglichst ähnlich. Neue Ganzkörper-Pose.'),
        {kind: 'same_identity', strength: 0.75, steps: 40, guidance: 5},
    );
    assert.deepEqual(
        preset('Create the same person in a different pose and preserve facial identity.'),
        {kind: 'same_identity', strength: 0.75, steps: 40, guidance: 5},
    );
    assert.deepEqual(
        preset('Create a photorealistic full-body photograph of the exact same adult woman from the reference image.'),
        {kind: 'same_identity', strength: 0.75, steps: 40, guidance: 5},
    );
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
    assert.match(attachmentsSource, /model\.id === 'juggernaut-xl' && model\.enabled && model\.available/);
    assert.match(attachmentsSource, /manualEditModel && editOptions\.model !== 'juggernaut-xl'/);
    assert.match(attachmentsSource, /manualEditFields\.has\(key\)/);
    assert.match(attachmentsSource, /modelOptionsLoaded && editOptions\.model === 'juggernaut-xl'/);
    assert.match(attachmentsSource, /'input', offerPersonReferencePreset/);
});
