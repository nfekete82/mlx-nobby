(function () {
    'use strict';

    const STREAM_ENDPOINT = '/api/mlx/audio/speech/stream';
    const BUFFERED_ENDPOINT = '/api/mlx/audio/speech';
    const MAX_CHARS = 1500;
    const MAX_CACHE_ENTRIES = 12;
    const MAX_CACHE_BASE64_CHARS = 8_000_000;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;

    let activeSession = null;
    const streamCache = new Map();

    const pauseIcon = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 5v14M15 5v14"></path>
        </svg>`;
    const playIcon = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m8 5 11 7-11 7Z"></path>
        </svg>`;

    function vt(key, fallback) {
        return window.MLXI18n?.t(`voice.${key}`, fallback) || fallback;
    }

    function currentSettings() {
        return window.MLXVoice?.getSettings?.() || {
            voice: 'Serena',
            speed: 1.0,
        };
    }

    function streamSupported() {
        return Boolean(
            AudioContextClass &&
            window.ReadableStream &&
            window.TextDecoder &&
            window.fetch
        );
    }

    function messageText(button) {
        if (button.classList.contains('mlx-voice-preview')) {
            return String(document.getElementById('input')?.value || '').trim();
        }

        const article = button.closest('.message');
        const content = article?.querySelector('.message-content');
        if (!content) return '';

        if (article.classList.contains('assistant')) {
            for (const child of content.children) {
                if (child.tagName === 'DIV' && !child.className) {
                    return String(child.innerText || child.textContent || '').trim();
                }
            }
        }

        return String(content.innerText || content.textContent || '').trim();
    }

    function splitText(text, maxChars = MAX_CHARS) {
        const normalized = String(text || '').trim();
        if (!normalized || normalized.length <= maxChars) return [normalized].filter(Boolean);

        const sentences = normalized.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [normalized];
        const chunks = [];
        let current = '';

        for (const rawSentence of sentences) {
            const sentence = rawSentence.trim();
            if (!sentence) continue;

            if (sentence.length > maxChars) {
                if (current) {
                    chunks.push(current);
                    current = '';
                }
                for (let start = 0; start < sentence.length; start += maxChars) {
                    chunks.push(sentence.slice(start, start + maxChars).trim());
                }
                continue;
            }

            const candidate = current ? `${current} ${sentence}` : sentence;
            if (candidate.length > maxChars) {
                chunks.push(current);
                current = sentence;
            } else {
                current = candidate;
            }
        }

        if (current) chunks.push(current);
        return chunks.filter(Boolean);
    }

    function replayKey(text, settings) {
        return JSON.stringify({
            text: String(text || '').trim(),
            voice: String(settings?.voice || 'Serena'),
            speed: Number(settings?.speed ?? 1),
        });
    }

    function rememberStream(key, chunks) {
        if (!key || !Array.isArray(chunks) || !chunks.length) return;
        const size = chunks.reduce(
            (total, chunk) => total + String(chunk?.pcm || '').length,
            0
        );
        if (size <= 0 || size > MAX_CACHE_BASE64_CHARS) return;
        if (streamCache.has(key)) streamCache.delete(key);
        streamCache.set(
            key,
            chunks.map(chunk => ({
                pcm: String(chunk.pcm || ''),
                sample_rate: Number(chunk.sample_rate) || 24000,
            }))
        );
        while (streamCache.size > MAX_CACHE_ENTRIES) {
            streamCache.delete(streamCache.keys().next().value);
        }
    }

    function statusNode(button) {
        return button.closest('.message')?.querySelector('.mlx-message-speech-status') || null;
    }

    function setStatus(session, text) {
        const node = session.status;
        if (!node) return;
        node.textContent = text;
        node.hidden = !text;
    }

    function snapshotButton(button) {
        return {
            html: button.innerHTML,
            text: button.textContent,
            title: button.title,
            aria: button.getAttribute('aria-label'),
            preview: button.classList.contains('mlx-voice-preview'),
        };
    }

    function renderButton(session, state) {
        const button = session.button;
        const original = session.original;

        if (state === 'loading') {
            if (original.preview) button.textContent = vt('stream_preparing', 'Preparing…');
            button.title = vt('stream_cancel', 'Cancel speech');
            button.setAttribute('aria-label', button.title);
            return;
        }

        if (state === 'playing') {
            if (original.preview) {
                button.textContent = vt('pause', 'Pause');
            } else {
                button.innerHTML = pauseIcon;
            }
            button.title = vt('pause', 'Pause playback');
            button.setAttribute('aria-label', button.title);
            return;
        }

        if (state === 'paused') {
            if (original.preview) {
                button.textContent = vt('resume', 'Resume');
            } else {
                button.innerHTML = playIcon;
            }
            button.title = vt('resume', 'Resume playback');
            button.setAttribute('aria-label', button.title);
        }
    }

    function restoreButton(session) {
        const { button, original } = session;
        button.innerHTML = original.html;
        if (original.preview) button.textContent = original.text;
        button.title = original.title;
        if (original.aria == null) {
            button.removeAttribute('aria-label');
        } else {
            button.setAttribute('aria-label', original.aria);
        }
        button.disabled = false;
    }

    function clearCompletionTimer(session) {
        if (session.finishTimer != null) {
            clearTimeout(session.finishTimer);
            session.finishTimer = null;
        }
    }

    function stopSession(session, options = {}) {
        if (!session || session.stopped) return;
        session.stopped = true;
        clearCompletionTimer(session);
        try { session.controller?.abort(); } catch (_) {}
        try { session.bufferedAudio?.pause(); } catch (_) {}
        if (session.bufferedUrl) {
            URL.revokeObjectURL(session.bufferedUrl);
            session.bufferedUrl = null;
        }
        for (const source of session.sources) {
            try { source.stop(); } catch (_) {}
        }
        session.sources.clear();
        if (session.context && session.context.state !== 'closed') {
            session.context.close().catch(() => {});
        }
        restoreButton(session);
        if (!options.keepStatus) setStatus(session, '');
        if (activeSession === session) activeSession = null;
    }

    function armCompletion(session) {
        clearCompletionTimer(session);
        if (!session.streamDone || session.stopped) return;

        const check = () => {
            if (session.stopped) return;
            if (session.paused) {
                session.finishTimer = setTimeout(check, 150);
                return;
            }
            const remaining = session.scheduledUntil - session.context.currentTime;
            if (remaining > 0.05) {
                session.finishTimer = setTimeout(
                    check,
                    Math.min(500, Math.max(70, remaining * 500))
                );
                return;
            }
            stopSession(session);
        };

        session.finishTimer = setTimeout(check, 80);
    }

    function float32FromBase64(value) {
        const binary = atob(value);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }
        return new Float32Array(bytes.buffer);
    }

    function scheduleAudioChunk(session, event) {
        const samples = float32FromBase64(event.pcm);
        if (!samples.length) return;

        const sampleRate = Math.max(8000, Number(event.sample_rate) || 24000);
        const buffer = session.context.createBuffer(1, samples.length, sampleRate);
        buffer.copyToChannel(samples, 0);

        const source = session.context.createBufferSource();
        source.buffer = buffer;
        source.connect(session.context.destination);
        source.addEventListener('ended', () => session.sources.delete(source), { once: true });

        const startAt = Math.max(
            session.scheduledUntil,
            session.context.currentTime + 0.025
        );
        source.start(startAt);
        session.sources.add(source);
        session.scheduledUntil = startAt + buffer.duration;

        if (!session.firstAudio) {
            session.firstAudio = true;
            renderButton(session, 'playing');
            setStatus(
                session,
                session.replaying
                    ? `${session.voice} · ${vt('stream_playing', 'Playing…')}`
                    : `${session.voice} · ${vt('stream_playing', 'Playing while generating…')}`
            );
        }
    }

    async function consumeNdjson(session, response) {
        if (!response.body?.getReader) {
            throw new Error('Streaming response body is unavailable');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let pending = '';

        while (!session.stopped) {
            const { value, done } = await reader.read();
            if (done) break;
            pending += decoder.decode(value, { stream: true });

            let newline;
            while ((newline = pending.indexOf('\n')) >= 0) {
                const raw = pending.slice(0, newline).trim();
                pending = pending.slice(newline + 1);
                if (!raw) continue;
                const event = JSON.parse(raw);
                if (event.type === 'audio') {
                    session.recordedChunks.push({
                        pcm: String(event.pcm || ''),
                        sample_rate: Number(event.sample_rate) || 24000,
                    });
                    scheduleAudioChunk(session, event);
                } else if (event.type === 'error') {
                    throw new Error(event.detail || 'TTS streaming failed');
                }
            }
        }
    }

    async function fetchStreamPart(session, text) {
        const response = await fetch(STREAM_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: session.controller.signal,
            body: JSON.stringify({
                input: text,
                voice: session.voice,
                language: 'de',
                speed: 1.0,
                instruct: session.instruct,
            }),
        });

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const payload = await response.json();
                detail = payload.detail || detail;
            } catch (_) {}
            throw new Error(detail);
        }

        await consumeNdjson(session, response);
    }

    async function playBufferedFallback(session, text) {
        const response = await fetch(BUFFERED_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: session.controller.signal,
            body: JSON.stringify({
                input: text,
                language: 'de',
                response_format: 'mp3',
                voice: session.voice,
                speed: 1.0,
                instruct: session.instruct,
            }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        session.bufferedAudio = audio;
        session.bufferedUrl = url;
        renderButton(session, 'playing');
        setStatus(session, `${session.voice} · ${vt('stream_playing', 'Playing…')}`);
        audio.addEventListener('ended', () => stopSession(session), { once: true });
        audio.addEventListener('error', () => stopSession(session), { once: true });
        await audio.play();
    }

    async function startStreaming(button, text, settings, options = {}) {
        if (activeSession) stopSession(activeSession);

        const context = new AudioContextClass({ latencyHint: 'interactive' });
        const key = replayKey(text, settings);
        const cached = options.forceRegenerate ? null : streamCache.get(key);
        const session = {
            button,
            original: snapshotButton(button),
            status: statusNode(button),
            context,
            controller: new AbortController(),
            sources: new Set(),
            scheduledUntil: 0,
            finishTimer: null,
            firstAudio: false,
            streamDone: false,
            paused: false,
            stopped: false,
            replaying: Boolean(cached?.length),
            voice: String(settings.voice || 'Serena'),
            instruct: '',
            bufferedAudio: null,
            bufferedUrl: null,
            recordedChunks: [],
            replayKey: key,
        };
        activeSession = session;
        renderButton(session, 'loading');
        setStatus(session, `${session.voice} · ${vt('stream_preparing', 'Preparing speech…')}`);

        try {
            await context.resume();

            if (cached?.length) {
                for (const chunk of cached) {
                    if (session.stopped) return;
                    scheduleAudioChunk(session, chunk);
                }
                session.streamDone = true;
                armCompletion(session);
                return;
            }

            const parts = splitText(text);
            for (const part of parts) {
                if (session.stopped) return;
                await fetchStreamPart(session, part);
            }
            session.streamDone = true;
            if (!session.firstAudio) {
                throw new Error('TTS stream returned no audio');
            }
            rememberStream(session.replayKey, session.recordedChunks);
            armCompletion(session);
        } catch (error) {
            if (session.stopped || error?.name === 'AbortError') return;
            console.warn('[voice-stream] Streaming failed, using MP3 fallback:', error);

            for (const source of session.sources) {
                try { source.stop(); } catch (_) {}
            }
            session.sources.clear();
            session.scheduledUntil = 0;
            session.firstAudio = false;
            session.recordedChunks = [];
            try {
                await playBufferedFallback(session, text);
            } catch (fallbackError) {
                console.error('[voice-stream] Buffered fallback failed:', fallbackError);
                setStatus(session, `${session.voice} · ${vt('stream_failed', 'Speech failed')}`);
                stopSession(session, { keepStatus: true });
            }
        }
    }

    async function toggleSession(session) {
        if (session.bufferedAudio) {
            if (session.bufferedAudio.paused) {
                await session.bufferedAudio.play();
                session.paused = false;
                renderButton(session, 'playing');
            } else {
                session.bufferedAudio.pause();
                session.paused = true;
                renderButton(session, 'paused');
            }
            return;
        }

        if (!session.firstAudio) {
            stopSession(session);
            return;
        }

        if (session.paused) {
            await session.context.resume();
            session.paused = false;
            renderButton(session, 'playing');
            armCompletion(session);
        } else {
            await session.context.suspend();
            session.paused = true;
            renderButton(session, 'paused');
            clearCompletionTimer(session);
        }
    }

    document.addEventListener('click', event => {
        const button = event.target?.closest?.(
            '.mlx-message-speech-button, .mlx-user-speech-button, .mlx-voice-preview'
        );
        if (!button) return;

        const settings = currentSettings();
        if (
            !streamSupported() ||
            Math.abs(Number(settings.speed ?? 1) - 1.0) > 1e-6
        ) {
            return;
        }

        const text = messageText(button);
        if (!text) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        if (activeSession?.button === button) {
            toggleSession(activeSession).catch(error => {
                console.error('[voice-stream] Pause/resume failed:', error);
                stopSession(activeSession);
            });
            return;
        }

        const forceRegenerate = event.shiftKey === true;
        if (forceRegenerate) streamCache.delete(replayKey(text, settings));
        startStreaming(button, text, settings, { forceRegenerate }).catch(error => {
            console.error('[voice-stream] Playback failed:', error);
        });
    }, true);

    window.addEventListener('mlx:voice-settings-changed', () => {
        if (activeSession) stopSession(activeSession);
        streamCache.clear();
    });

    window.MLXVoiceStreaming = {
        isSupported: streamSupported,
        stop: () => activeSession && stopSession(activeSession),
        isActive: () => Boolean(activeSession),
        splitText,
        clearCache: () => streamCache.clear(),
        cacheSize: () => streamCache.size,
    };
})();