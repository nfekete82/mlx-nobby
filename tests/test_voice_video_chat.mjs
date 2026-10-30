import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const script = fs.readFileSync(new URL('../frontend/assets/chat/voice-video.js', import.meta.url), 'utf8');
const window = {};
const context = {window, console, FileReader: class {}};
vm.runInNewContext(script, context, {filename: 'voice-video.js'});
const bridge = window.MLXVoiceVideo;
assert.ok(bridge);

const prompt = 'Erstelle ein Video indem die Frau tanzt und dabei mit der Stimme von Pervin sagt Komm mit mir tanzen';
const parsed = bridge.parseRequest(prompt);
assert.equal(parsed.voiceName, 'Pervin');
assert.equal(parsed.speech, 'Komm mit mir tanzen');
assert.equal(parsed.scene_motion, 'dance');
assert.equal(parsed.language, 'de');
assert.equal(parsed.engine, 'ltx-distilled');
const maximalQualityPrompt = 'Erstelle ein Video mit LTX-Max, in dem die Frau tanzt und ' +
    'mit der Stimme von Pervin auf Deutsch sagt: „Komm mit mir tanzen!“';
const max = bridge.parseRequest(maximalQualityPrompt);
assert.equal(max?.voiceName, 'Pervin');
assert.equal(max?.speech, 'Komm mit mir tanzen!');
assert.equal(max?.language, 'de');
assert.equal(max?.scene_motion, 'dance');
assert.equal(max?.engine, 'ltx-max');
assert.equal(bridge.parseRequest(
    'Erstelle ein Video in maximaler Qualität, die Frau tanzt und mit der Stimme von Pervin sagt: „Hallo!“'
)?.engine, 'ltx-max');
// Spoken dialogue is NEVER interpreted as a quality setting or language instruction.
assert.equal(bridge.parseRequest(
    'Erstelle ein Video mit der Stimme von Pervin sagt: „LTX-Max ist toll!“'
)?.engine, 'ltx-distilled');

// Exact wording from the reported regression, including the instruction
// AFTER the quoted sentence. Never translate the requested German dialogue.
const reportedPrompt =
    'Erstelle ein Video, in dem die Frau natürlich tanzt und dabei mit der Stimme von ' +
    'Pervin auf Deutsch sagt: „Komm mit mir tanzen!“. Die Sprache muss Deutsch bleiben.';
const reported = bridge.parseRequest(reportedPrompt);
assert.equal(reported?.voiceName, 'Pervin');
assert.equal(reported?.speech, 'Komm mit mir tanzen!');
assert.equal(reported?.language, 'de');
assert.equal(reported?.scene_motion, 'dance');
assert.equal(bridge.hasVoiceIntent(reportedPrompt), true);
assert.equal(bridge.parseRequest(
    'Erstelle ein Video mit der Stimme von Pervin auf Deutsch sagt: „Guten Morgen!“'
)?.speech, 'Guten Morgen!');
assert.equal(bridge.parseRequest(
    'Erstelle ein Video mit der Stimme von Pervin auf Englisch sagt: „Come dance with me!“'
)?.language, 'en');
assert.equal(bridge.parseRequest(
    'Erstelle ein Video mit der Stimme von Pervin sagt „Hallo“. Bitte auf Englisch NICHT übersetzen.'
)?.language, 'de');
assert.equal(bridge.parseRequest(
    'Erstelle ein Video mit der Stimme von Pervin sagt: „Nicht geschlossene Worte'
), null);
assert.equal(bridge.hasVoiceIntent(
    'Erstelle ein Video mit der Stimme von Pervin sagt: „Nicht geschlossen'
), true);
assert.equal(bridge.parseRequest('Kannst du ein Video mit Pervins Stimme machen?'), null);
assert.equal(bridge.parseRequest('Erstelle ein Video, die Frau tanzt'), null);
assert.equal(bridge.parseRequest('Erstelle ein Video: Die Frau sagt Hallo.'), null);
assert.equal(bridge.resolveVoice([{id:'pervin', label:'Pervin'}, {id:'anna'}], 'PERVIN'), 'pervin');
assert.equal(bridge.resolveVoice([{id:'anna'}], 'Pervin'), null);

const requests = [];
const fakeFetch = async (url, options) => {
    requests.push({url, options});
    if (url.endsWith('/manage')) return {
        ok: true, json: async () => ({voices:[{id:'pervin',label:'Pervin'}]})
    };
    if (url.endsWith('/jobs')) return {
        ok: true, json: async () => ({id:'a'.repeat(24),status:'queued',
            voice:'pervin',scene_motion:'dance',progress:0,phase:'queued'})
    };
    throw new Error('unexpected URL ' + url);
};
const result = await bridge.create({
    prompt, imageSource: {source: {data_url:'data:image/png;base64,cG5n'}},
    fetcher: fakeFetch
});
assert.equal(requests.length, 2);
assert.equal(requests[0].url, '/api/mlx/audio/voices/manage');
assert.equal(requests[1].url, '/api/talking-photo/jobs');
const payload = JSON.parse(requests[1].options.body);
assert.equal(payload.text, 'Komm mit mir tanzen');
assert.equal(payload.voice, 'pervin');
assert.equal(payload.scene_motion, 'dance');
assert.equal(payload.language, 'de');
assert.equal(payload.preserve_speech_audio, true);
assert.equal(payload.engine, 'ltx-distilled');
assert.equal(payload.image_data_url, 'data:image/png;base64,cG5n');
assert.equal(result.status, 'queued');
assert.equal(result.data.job.voice_video, true);
assert.equal(result.artifacts.length, 0);
const maxResult = await bridge.create({
    prompt: maximalQualityPrompt,
    imageSource: {source: {data_url: 'data:image/png;base64,cG5n'}},
    fetcher: fakeFetch
});
assert.equal(maxResult.status, 'queued');
const maxPayload = JSON.parse(requests.at(-1).options.body);
assert.equal(maxPayload.engine, 'ltx-max');
assert.equal(maxPayload.text, 'Komm mit mir tanzen!');
assert.equal(maxPayload.voice, 'pervin');
assert.equal(maxPayload.language, 'de');
assert.equal(maxPayload.preserve_speech_audio, true);

// The reported request must reach native TTS with the exact German quote.
const reportedResult = await bridge.create({
    prompt: reportedPrompt,
    imageSource: {source: {data_url: 'data:image/png;base64,cG5n'}},
    fetcher: fakeFetch
});
assert.equal(reportedResult.status, 'queued');
const reportedPayload = JSON.parse(requests.at(-1).options.body);
assert.equal(reportedPayload.text, 'Komm mit mir tanzen!');
assert.equal(reportedPayload.voice, 'pervin');
assert.equal(reportedPayload.language, 'de');
assert.equal(reportedPayload.scene_motion, 'dance');
assert.equal(reportedPayload.preserve_speech_audio, true);
const done = bridge.toToolResult({
    id:'a'.repeat(24),status:'completed', voice:'pervin',scene_motion:'dance',
    result:{video_url:'/api/talking-photo/videos/'+'a'.repeat(24)}
});
assert.equal(done.artifacts[0].audio, true);
assert.equal(done.artifacts[0].url, '/api/talking-photo/videos/'+'a'.repeat(24));
assert.equal(done.artifacts[0].scene_motion, 'dance');

await assert.rejects(bridge.create({
    prompt, imageSource:{source:{data_url:'data:image/png;base64,cG5n'}},
    fetcher:async () => ({ok:true,json:async()=>({voices:[{id:'other'}]})})
}), /nicht als lokales Stimmprofil/);
await assert.rejects(bridge.create({prompt, imageSource:null, fetcher: fakeFetch}), /Foto/);

console.log('Voice-video prompt parsing, voice selection, A2V creation and chat artifacts passed.');
