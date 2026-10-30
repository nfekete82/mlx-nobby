'use strict';

// Natural-language chat bridge: existing local Qwen3-TTS voices + LTX audio-to-video.
// No fallback to another voice when a named local voice is missing.
(function () {
    const VIDEO_REQUEST = /\b(?:erstelle|generiere|erzeuge|mach(?:e)?|create|generate|make)\b.{0,65}\b(?:video|clip)\b/iu;
    const NAMED_VOICE = /\b(?:mit\s+der\s+stimme\s+von|in\s+der\s+stimme\s+von|with\s+(?:the\s+)?voice\s+of)\s+([\p{L}\p{N}_ -]{1,80}?)(?=\s+(?:sagt|spricht|says|speaks)\b|[,;:]|$)/iu;
    const SPOKEN_WORDS = /\b(?:sagt|spricht|says|speaks)\b\s*:?\s*([\s\S]+)$/iu;
    const DANCE = /\b(?:tanzt|tanzen|tanzend|dance|dances|dancing)\b/iu;
    const VALID_ID = /^[a-f0-9]{24}$/;

    function parseRequest(prompt) {
        const value = String(prompt || '').trim();
        // Only explicit *creation* commands. Never intercept questions or examples.
        if (!VIDEO_REQUEST.test(value) || /^\s*(?:wie|kann|würde|what|how|can|could)\b/iu.test(value)) {
            return null;
        }
        const named = NAMED_VOICE.exec(value);
        const spoken = SPOKEN_WORDS.exec(value);
        if (!named || !spoken || named.index >= spoken.index) return null;
        const voiceName = named[1].trim();
        const speech = spoken[1].trim()
            .replace(/^[„“"'«]\s*/u, '')
            .replace(/\s*[“”"'»]\s*[.!?]?\s*$/u, '')
            .trim();
        if (!voiceName || !speech || speech.length > 5000) return null;
        return {
            voiceName,
            speech,
            language: /\b(?:english|englisch)\b/iu.test(value) ? 'en' : 'de',
            scene_motion: DANCE.test(value.slice(0, spoken.index)) ? 'dance' : 'none',
        };
    }

    function resolveVoice(profiles, name) {
        const norm = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase();
        const voices = Array.isArray(profiles) ? profiles : [];
        const match = voices.find(item =>
            [item?.id, item?.label, item?.name].some(value => norm(value) === norm(name))
        );
        return match ? String(match.id || match.name || match.label).trim() : null;
    }

    function toToolResult(job) {
        if (!VALID_ID.test(String(job?.id || ''))) throw new Error('Ungültige Talking-Photo-Job-ID');
        const status = String(job.status || 'queued');
        const videoJob = {...job, source: 'talking_photo', voice_video: true, operation: 'i2v'};
        const artifacts = status === 'completed' ? [{
            video_id: job.id,
            artifact_id: 'talking-photo-' + job.id,
            url: '/api/talking-photo/videos/' + job.id,
            mime_type: 'video/mp4',
            operation: 'i2v',
            provider: 'LTX 2.5 + Qwen3-TTS',
            model: 'LTX 2.5',
            audio: true,
            voice: job.voice || null,
            scene_motion: job.scene_motion || 'none',
        }] : [];
        return {type: 'tool_result', tool: 'video_animate', status,
            data: {job: videoJob}, artifacts, error: job.error || null};
    }

    function asDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('Bild konnte nicht gelesen werden.'));
            reader.readAsDataURL(file);
        });
    }

    async function imageDataUrl(imageSource, artifactToDataUrl) {
        const source = imageSource?.source;
        if (!source) throw new Error('Bitte ein Foto anhängen oder ein vorhandenes Bild auswählen.');
        if (typeof source.data_url === 'string' && /^data:image\/(?:png|jpeg);base64,/i.test(source.data_url)) {
            return source.data_url;
        }
        if (source.file && typeof source.file.size === 'number') {
            if (source.file.size > 10 * 1024 * 1024)
                throw new Error('Das Foto darf maximal 10 MB groß sein.');
            if (!['image/png', 'image/jpeg'].includes(source.file.type))
                throw new Error('Für Video mit Sprache bitte ein PNG- oder JPEG-Foto verwenden.');
            return asDataUrl(source.file);
        }
        if (source.image_id && typeof artifactToDataUrl === 'function') {
            return artifactToDataUrl(source);
        }
        throw new Error('Das ausgewählte Bild ist nicht als PNG/JPEG verfügbar. Bitte erneut hochladen.');
    }

    async function create({prompt, imageSource, artifactToDataUrl, fetcher = fetch}) {
        const parsed = parseRequest(prompt);
        if (!parsed) throw new Error('Kein eindeutiger Video-mit-Stimme-Befehl.');
        if (!imageSource?.source) throw new Error('Bitte ein Foto der sprechenden Person anhängen.');
        const voiceResponse = await fetcher('/api/mlx/audio/voices/manage');
        if (!voiceResponse.ok) throw new Error('Die lokalen Stimmprofile konnten nicht geladen werden.');
        const voices = await voiceResponse.json();
        const voice = resolveVoice(voices.voices, parsed.voiceName);
        if (!voice) throw new Error('Die Stimme „' + parsed.voiceName +
            '“ ist nicht als lokales Stimmprofil vorhanden. Bitte die genaue Profilbezeichnung verwenden.');
        const dataUrl = await imageDataUrl(imageSource, artifactToDataUrl);
        const response = await fetcher('/api/talking-photo/jobs', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                image_data_url: dataUrl, text: parsed.speech, voice,
                language: parsed.language, scene_motion: parsed.scene_motion,
                motion: 'natural', engine: 'ltx-distilled', speed: 1.0,
                preserve_speech_audio: true,
            }),
        });
        if (!response.ok) {
            let detail = 'Video mit Sprache konnte nicht gestartet werden.';
            try {
                const body = await response.json();
                if (typeof body.detail === 'string') detail = body.detail;
            } catch (_) { /* Never expose raw proxy error pages */ }
            throw new Error(detail);
        }
        return toToolResult(await response.json());
    }

    window.MLXVoiceVideo = Object.freeze({
        parseRequest, resolveVoice, toToolResult, create,
    });
})();
