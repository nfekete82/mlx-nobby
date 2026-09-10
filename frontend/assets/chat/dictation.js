function dictationT(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [varName, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            `{${varName}}`,
            String(replacement ?? '')
        );
    }

    return value;
}

(() => {
    const button = document.getElementById("dictationButton");
    const input = document.getElementById("input");

    if (!button || !input) {
        return;
    }

    let recorder = null;
    let stream = null;
    let chunks = [];
    let state = "idle";

    function setState(nextState) {
        state = nextState;

        button.classList.toggle("recording", state === "recording");
        button.classList.toggle("transcribing", state === "transcribing");

        button.disabled = state === "transcribing";
        button.setAttribute(
            "aria-pressed",
            state === "recording" ? "true" : "false"
        );

        if (state === "recording") {
            button.title = dictationT('dictation.stop', 'Stop recording');
            button.setAttribute("aria-label", dictationT('dictation.stop', 'Stop recording'));
        } else if (state === "transcribing") {
            button.title = dictationT('dictation.transcribing', 'Transcribing…');
            button.setAttribute("aria-label", dictationT('dictation.transcribing_label', 'Transcribing'));
        } else {
            button.title = dictationT('dictation.start', 'Start dictation');
            button.setAttribute("aria-label", dictationT('dictation.start', 'Start dictation'));
        }
    }

    function chooseMimeType() {
        const candidates = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/mp4",
        ];

        for (const type of candidates) {
            if (
                typeof MediaRecorder !== "undefined" &&
                MediaRecorder.isTypeSupported(type)
            ) {
                return type;
            }
        }

        return "";
    }

    function extensionForMime(type) {
        if (type.includes("mp4")) {
            return "m4a";
        }

        if (type.includes("ogg")) {
            return "ogg";
        }

        return "webm";
    }

    function insertTranscript(text) {
        text = String(text || "").trim();

        if (!text) {
            return;
        }

        const start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? start;

        let before = input.value.slice(0, start);
        const after = input.value.slice(end);

        if (before && !/\s$/.test(before)) {
            before += " ";
        }

        const value = before + text + after;
        const caret = (before + text).length;

        input.value = value;
        input.focus();
        input.setSelectionRange(caret, caret);

        // Bestehende Auto-Resize-/Token-/Context-Logik informieren.
        input.dispatchEvent(
            new Event("input", {
                bubbles: true,
            })
        );
    }

    async function transcribe(blob) {
        setState("transcribing");

        try {
            const mime = blob.type || "audio/webm";
            const extension = extensionForMime(mime);

            const form = new FormData();

            form.append(
                "file",
                blob,
                `dictation-${Date.now()}.${extension}`
            );

            const response = await fetch(
                "/api/mlx/audio/transcriptions",
                {
                    method: "POST",
                    body: form,
                }
            );

            let data = null;

            try {
                data = await response.json();
            } catch (_) {
                throw new Error(
                    dictationT(
                    'dictation.invalid_response',
                    'Invalid response from speech service ({status})',
                    { status: response.status }
                )
                );
            }

            if (!response.ok) {
                throw new Error(
                    data?.detail || dictationT(
                        'dictation.transcription_failed',
                        'Transcription failed ({status})',
                        { status: response.status }
                    )
                );
            }

            insertTranscript(data.text);

        } catch (error) {
            console.error("[dictation]", error);
            alert(dictationT(
                'dictation.failed',
                'Dictation failed: {message}',
                { message: error.message }
            ));

        } finally {
            setState("idle");
        }
    }

    async function startRecording() {
        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia ||
            typeof MediaRecorder === "undefined"
        ) {
            alert(dictationT('dictation.unsupported', 'This browser does not support audio recording.'));
            return;
        }

        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

            chunks = [];

            const mimeType = chooseMimeType();

            recorder = mimeType
                ? new MediaRecorder(stream, { mimeType })
                : new MediaRecorder(stream);

            recorder.addEventListener("dataavailable", event => {
                if (event.data && event.data.size > 0) {
                    chunks.push(event.data);
                }
            });

            recorder.addEventListener("stop", async () => {
                const actualMime =
                    recorder?.mimeType ||
                    mimeType ||
                    "audio/webm";

                const blob = new Blob(chunks, {
                    type: actualMime,
                });

                chunks = [];

                if (stream) {
                    stream.getTracks().forEach(track => track.stop());
                    stream = null;
                }

                recorder = null;

                if (blob.size > 0) {
                    await transcribe(blob);
                } else {
                    setState("idle");
                }
            });

            recorder.start();
            setState("recording");

        } catch (error) {
            console.error("[dictation]", error);

            if (stream) {
                stream.getTracks().forEach(track => track.stop());
                stream = null;
            }

            recorder = null;
            setState("idle");

            if (
                error.name === "NotAllowedError" ||
                error.name === "PermissionDeniedError"
            ) {
                alert(window.MLXI18n?.t(
                    "dictation.permission_denied",
                    "Microphone access was denied. Allow MLX Nobby to use the microphone."
                ));
                return;
            }

            alert((window.MLXI18n?.t(
                "dictation.start_failed",
                "Could not start the microphone:"
            ) || "Could not start the microphone:") + ` ${error.message}`);
        }
    }

    function stopRecording() {
        if (recorder && recorder.state !== "inactive") {
            recorder.stop();
        }
    }

    button.addEventListener("click", () => {
        if (state === "recording") {
            stopRecording();
            return;
        }

        if (state === "idle") {
            startRecording();
        }
    });

    window.addEventListener("beforeunload", () => {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    });

    setState("idle");
})();
