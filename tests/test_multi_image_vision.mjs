import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url),
    'utf8',
);

const translations = {
    'generation.vision_describe_image_prompt':
        'Describe this image in detail. Answer in English.',
    'generation.vision_describe_images_prompt':
        'Describe all attached images in order. Answer in English.',
};
const window = {
    MLXI18n: {
        t(key, fallback) {
            return translations[key] ?? fallback;
        },
    },
};
window.window = window;

vm.runInNewContext(source, {
    console,
    document: {
        getElementById() {
            return {};
        },
    },
    window,
}, {
    filename: 'frontend/assets/chat/generation.js',
});

const vision = window.MLXChatGeneration.__test;

function image(index) {
    return {
        kind: 'image',
        name: `image-${index}.png`,
        data_url: `data:image/png;base64,image-${index}`,
    };
}

function imageUrls(message) {
    return Array.from(message.content)
        .filter(part => part.type === 'image_url')
        .map(part => part.image_url.url);
}

function build(attachments, content = 'Describe the images.') {
    return vision.buildApiMessages([{
        role: 'user',
        content,
        attachments,
    }])[0];
}

const oneImage = build([image(1)]);
assert.deepEqual(
    Array.from(oneImage.content, part => part.type),
    ['text', 'image_url'],
);
assert.deepEqual(imageUrls(oneImage), [image(1).data_url]);

const twoImages = build([image(1), image(2)]);
assert.deepEqual(
    imageUrls(twoImages),
    [image(1).data_url, image(2).data_url],
);

const manyImages = build([
    image(1),
    image(2),
    image(3),
    image(4),
    image(5),
]);
assert.deepEqual(
    imageUrls(manyImages),
    [1, 2, 3, 4, 5].map(index => image(index).data_url),
);

const fileContext =
    'Compare the images.\n\nAdditional user files:\n' +
    '--- FILE: notes.txt ---\nnotes';
const mixed = build([
    image(1),
    { kind: 'text', name: 'notes.txt', content: 'notes' },
    image(2),
    { kind: 'document', name: 'manual.pdf' },
    image(3),
], fileContext);
assert.equal(mixed.content[0].type, 'text');
assert.equal(mixed.content[0].text, fileContext);
assert.deepEqual(
    imageUrls(mixed),
    [image(1).data_url, image(2).data_url, image(3).data_url],
);

const history = vision.buildApiMessages([
    { role: 'system', content: 'System prompt' },
    { role: 'user', content: 'First turn', attachments: [image(1)] },
    { role: 'assistant', content: 'First answer' },
    {
        role: 'user',
        content: 'Compare first and second image',
        attachments: [image(2), image(3)],
    },
]);
assert.deepEqual(
    Array.from(history, message => message.role),
    ['system', 'user', 'assistant', 'user'],
);
assert.deepEqual(imageUrls(history[1]), [image(1).data_url]);
assert.deepEqual(
    imageUrls(history[3]),
    [image(2).data_url, image(3).data_url],
);
assert.equal(history[2].content, 'First answer');

const generatedImage = build([], 'Describe the generated image.');
assert.deepEqual(imageUrls(generatedImage), []);
const generatedHistory = vision.buildApiMessages([{
    role: 'user',
    content: 'Describe the generated image.',
    attachments: [],
    vision_images: [image(6)],
}])[0];
assert.deepEqual(imageUrls(generatedHistory), [image(6).data_url]);

assert.equal(
    vision.defaultVisionPrompt(1),
    'Describe this image in detail. Answer in English.',
);
assert.equal(
    vision.defaultVisionPrompt(2),
    'Describe all attached images in order. Answer in English.',
);

console.log(
    'Multi-image vision: one, two, many, mixed attachments, ordering, and history passed.',
);
