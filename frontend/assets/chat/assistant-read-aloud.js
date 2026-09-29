(function () {
    'use strict';

    const CHUNK_MAX_CHARS = 600;
    const REQUEST_TIMEOUT_MS = 60000;
    const STYLE_ID = 'mlxAssistantReadAloudStyles';
    const FALLBACK = {
        read_aloud: 'Read aloud',
        generating: '{voice} · generating {current}/{total}',
        stop: 'Stop speech generation',
        playing: '{voice} · playing {current}/{total}',
        pause: 'Pause playback',
        paused: '{voice} · paused',
        resume: 'Resume playback',
        failed: 'Speech failed · try again',
        timeout: 'Speech generation timed out · try again',
        empty: 'No readable text'
    };

    let dictionary = {};
    let activeState = null;

    function language() {
        const configured = String(
            window.MLXI18n?.getLanguage?.() ||
            document.documentElement?.lang ||
            'en'
        ).toLowerCase();
        return configured.startsWith('de') ? 'de' : 'en';
    }

    function t(key, variables = {}) {
        let value = dictionary[key] || FALLBACK[key] || key;
        for (const [name, replacement] of Object.entries(variables)) {
            value = value.replaceAll(
                '{' + name + '}',
                String(replacement ?? '')
            );
        }
        return value;
    }

    async function loadDictionary() {
        try {
            const response = await fetch(
                '/i18n/assistant-read-aloud.' + language() + '.json',
                { cache: 'no-store' }
            );
            if (!response.ok) return;
            const payload = await response.json();
            if (payload && typeof payload === 'object') {
                dictionary = payload;
            }
        } catch (_) {}
    }

    function installStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            @keyframes mlx-assistant-speech-spin {
                to { transform: rotate(360deg); }
            }
            .mlx-message-speech-button.is-generating {
                opacity: 1 !important;
                cursor: pointer !important;
            }
            .mlx-message-speech-button.is-generating svg {
                animation: mlx-assistant-speech-spin .8s linear infinite;
                transform-origin: 50% 50%;
                transform-box: fill-box;
            }
            @media (prefers-reduced-motion: reduce) {
                .mlx-message-speech-button.is-generating svg {
                    animation: none;
                    opacity: .6;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function normalizeVisibleText(value) {
        return String(value || '')
            .replace(/https?:\/\/\S+/gi, '')
            .replace(/\r/g, '')
            .replace(/[\t ]+/g, ' ')
            .replace(/\n[\t ]+/g, '\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function extractAssistantText(article) {
        const content = article?.querySelector?.('.message-content');
        if (!content) return '';

        let source = null;
        for (const child of content.children || []) {
            if (child.tagName === 'DIV' && !child.className) {
                source = child;
                break;
            }
        }
        source ||= content;

        const clone = source.cloneNode(true);
        clone.querySelectorAll?.(
            'pre, script, style, svg, button, [aria-hidden="true"]'
        ).forEach(node => node.remove());

        return normalizeVisibleText(
            clone.innerText || clone.textContent || ''
        );
    }

    function splitSpeechText(value, maxChars = CHUNK_MAX_CHARS) {
        const source = normalizeVisibleText(value);
        if (!source) return [];
        if (source.length <= maxChars) return [source];

        const chunks = [];
        let remaining = source;
        const minimumNaturalCut = Math.floor(maxChars * 0.45);

        while (remaining.length > maxChars) {
            const windowText = remaining.slice(0, maxChars + 1);
            let cut = -1;

            for (const pattern of [
                /[.!?]["'”’)]?\s+/g,
                /\n\s*\n/g,
                /\n/g,
                /[,;:]\s+/g,
                /\s+/g
            ]) {
                let match;
                let last = -1;
                pattern.lastIndex = 0;
                while ((match = pattern.exec(windowText)) !== null) {
                    last = match.index + match[0].length;
                }
                if (last >= minimumNaturalCut) {
                    cut = last;
                    break;
                }
            }

            if (cut < 1) cut = maxChars;
            const chunk = remaining.slice(0, cut).trim();
            if (chunk) chunks.push(chunk);
            remaining = remaining.slice(cut).trim();
        }

        if (remaining) chunks.push(remaining);
        return chunks;
    }

    function voiceSettings() {
        const settings = window.MLXVoice?.getSettings?.() || {};
        const voices = window.MLXVoice?.getVoices?.() || [];
        const voice = String(settings.voice || 'Serena');
        const profile = voices.find(item => item?.id === voice) || null;
        return {
            voice,
            label: String(profile?.label || voice),
            kind: profile?.kind || 'preset',
            speed: Number(settings.speed ?? 1)
        };
    }

    function statusNode(article) {
        return article?.querySelector?.('.mlx-message-speech-status') || null;
    }

    function setStatus(state, text, isError = false) {
        const status = statusNode(state.article);
        if (!status) return;
        status.hidden = !text;
        status.classList.toggle('is-error', Boolean(isError));
        status.textContent = String(text || '');
    }

    function resetButton(state) {
        if (!state?.button) return;
        state.button.classList.remove('is-generating');
        state.button.removeAttribute('aria-busy');
        state.button.disabled = false;
        state.button.title = t('read_aloud');
        state.button.setAttribute('aria-label', state.button.title);
    }

    function releaseAudio(state) {
        if (!state) return;
        if (state.audio) {
            try { state.audio.pause(); } catch (_) {}
            state.audio = null;
        }
        if (state.audioUrl) {
            URL.revokeObjectURL(state.audioUrl);
            state.audioUrl = null;
        }
    }

    function stopState(state, { clearStatus = true } = {}) {
        if (!state) return;
        state.cancelled = true;
        if (state.timeoutId) {
            clearTimeout(state.timeoutId);
            state.timeoutId = null;
        }
        if (state.controller) {
            state.controller.abort();
            state.controller = null;
        }
        if (state.finishPlayback) {
            const finish = state.finishPlayback;
            state.finishPlayback = null;
            finish(false);
        }
        releaseAudio(state);
        resetButton(state);
        if (clearStatus) setStatus(state, '');
        if (activeState === state) activeState = null;
    }

    async function responseDetail(response) {
        try {
            const payload = await response.json();
            return payload?.detail || payload?.error || `HTTP ${response.status}`;
        } catch (_) {
            return `HTTP ${response.status}`;
        }
    }

    async function requestSpeech(state, text) {
        state.controller = new AbortController();
        state.timedOut = false;
        state.timeoutId = setTimeout(() => {
            state.timedOut = true;
            state.controller?.abort();
        }, REQUEST_TIMEOUT_MS);

        const voice = voiceSettings();
        try {
            const response = await fetch('/api/mlx/audio/speech', {
                method: 'POST',
                signal: state.controller.signal,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input: text,
                    voice: voice.voice,
                    language: 'de',
                    speed: voice.speed,
                    response_format: 'mp3',
                    instruct: voice.kind === 'clone' ? '' : undefined
                })
            });
            if (!response.ok) {
                throw new Error(await responseDetail(response));
            }
            return await response.blob();
        } finally {
            if (state.timeoutId) clearTimeout(state.timeoutId);
            state.timeoutId = null;
            state.controller = null;
        }
    }

    async function playBlob(state, blob, current, total) {
        if (!blob?.size) throw new Error('Empty audio response');

        releaseAudio(state);
        state.audioUrl = URL.createObjectURL(blob);
        state.audio = new Audio(state.audioUrl);
        state.paused = false;

        const voice = voiceSettings();
        setStatus(state, t('playing', {
            voice: voice.label,
            current,
            total
        }));
        state.button.title = t('pause');
        state.button.setAttribute('aria-label', state.button.title);

        const completed = await new Promise((resolve, reject) => {
            let settled = false;
            const finish = value => {
                if (settled) return;
                settled = true;
                state.finishPlayback = null;
                resolve(value);
            };
            state.finishPlayback = finish;
            state.audio.addEventListener('ended', () => finish(true), {
                once: true
            });
            state.audio.addEventListener('error', () => {
                if (settled) return;
                settled = true;
                state.finishPlayback = null;
                reject(new Error('Audio playback failed'));
            }, { once: true });
            state.audio.play().catch(reject);
        });

        releaseAudio(state);
        return completed;
    }

    async function togglePause(state) {
        if (!state?.audio) return;
        const voice = voiceSettings();
        if (state.audio.paused) {
            await state.audio.play();
            state.paused = false;
            state.button.title = t('pause');
            setStatus(state, t('playing', {
                voice: voice.label,
                current: state.current,
                total: state.total
            }));
        } else {
            state.audio.pause();
            state.paused = true;
            state.button.title = t('resume');
            setStatus(state, t('paused', { voice: voice.label }));
        }
        state.button.setAttribute('aria-label', state.button.title);
    }

    async function start(button) {
        const article = button.closest('.message.assistant');
        if (!article) return;

        if (activeState?.button === button) {
            if (activeState.controller) {
                stopState(activeState);
                return;
            }
            if (activeState.audio) {
                await togglePause(activeState);
                return;
            }
        }

        if (activeState) stopState(activeState);

        const text = extractAssistantText(article);
        const chunks = splitSpeechText(text);
        const state = {
            article,
            button,
            chunks,
            current: 0,
            total: chunks.length,
            controller: null,
            timeoutId: null,
            timedOut: false,
            cancelled: false,
            audio: null,
            audioUrl: null,
            finishPlayback: null,
            paused: false
        };
        activeState = state;

        if (!chunks.length) {
            setStatus(state, t('empty'), true);
            resetButton(state);
            activeState = null;
            return;
        }

        button.disabled = false;
        button.classList.add('is-generating');
        button.setAttribute('aria-busy', 'true');
        button.title = t('stop');
        button.setAttribute('aria-label', button.title);

        try {
            for (let index = 0; index < chunks.length; index += 1) {
                if (state.cancelled || activeState !== state) return;
                state.current = index + 1;
                state.total = chunks.length;

                const voice = voiceSettings();
                button.classList.add('is-generating');
                button.setAttribute('aria-busy', 'true');
                button.title = t('stop');
                button.setAttribute('aria-label', button.title);
                setStatus(state, t('generating', {
                    voice: voice.label,
                    current: state.current,
                    total: state.total
                }));

                const blob = await requestSpeech(state, chunks[index]);
                if (state.cancelled || activeState !== state) return;

                button.classList.remove('is-generating');
                button.removeAttribute('aria-busy');
                const completed = await playBlob(
                    state,
                    blob,
                    state.current,
                    state.total
                );
                if (!completed || state.cancelled || activeState !== state) {
                    return;
                }
            }

            setStatus(state, '');
            resetButton(state);
            activeState = null;
        } catch (error) {
            const timedOut = state.timedOut;
            const cancelled = state.cancelled || error?.name === 'AbortError';
            if (cancelled && !timedOut) {
                stopState(state);
                return;
            }

            console.error('[assistant-read-aloud]', error);
            releaseAudio(state);
            resetButton(state);
            setStatus(
                state,
                timedOut ? t('timeout') : t('failed'),
                true
            );
            if (activeState === state) activeState = null;
        }
    }

    function handleClick(event) {
        const button = event.target?.closest?.('.mlx-message-speech-button');
        if (!button) return;
        const article = button.closest('.message.assistant');
        if (!article) return;

        event.preventDefault();
        event.stopImmediatePropagation();
        start(button);
    }

    function install() {
        installStyles();
        document.addEventListener('click', handleClick, true);
        const messages = document.getElementById('messagesInner');
        if (messages && typeof MutationObserver !== 'undefined') {
            const observer = new MutationObserver(() => {
                if (activeState?.button && !activeState.button.isConnected) {
                    stopState(activeState);
                }
            });
            observer.observe(messages, { childList: true, subtree: true });
        }
    }

    window.MLXAssistantReadAloud = {
        stop: () => stopState(activeState),
        __test: {
            extractAssistantText,
            normalizeVisibleText,
            splitSpeechText,
            CHUNK_MAX_CHARS,
            REQUEST_TIMEOUT_MS
        }
    };

    loadDictionary().finally(install);
    document.addEventListener('mlx-language-changed', async () => {
        dictionary = {};
        await loadDictionary();
    });
})();
