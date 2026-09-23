'use strict';

function generationText(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(key, fallback) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            '{' + name + '}',
            String(replacement)
        );
    }

    return value;
}

function gt(key, fallback = '', variables = {}) {
    return generationText(
        'generation.' + key,
        fallback,
        variables
    );
}

const IMAGE_EDIT_VERB_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:bearbeit(?:e|en)?|änder(?:e|n)?|aender(?:e|n)?|veränder(?:e|n)?|veraender(?:e|n)?|färb(?:e|en)?|faerb(?:e|en)?|entfern(?:e|en)?|lösch(?:e|en)?|loesch(?:e|en)?|ersetz(?:e|en)?|füg(?:e|en)?|fueg(?:e|en)?|retuschier(?:e|en)?|korrigier(?:e|en)?|verbesser(?:e|n)?|change|edit|modify|recolor|remove|replace|add|retouch|blur)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_EDIT_MAKE_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:mach|mache|make)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_EDIT_MODIFIER_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:rot|blau|grün|gruen|gelb|schwarz|weiß|weiss|blond|heller|dunkler|dunkel|hell|wärmer|waermer|kälter|kaelter|realistischer|jünger|juenger|älter|aelter|unscharf|scharf|weg|hintergrund|farbe|farben|person|objekt|gesicht|haare|bart|kleidung|stil|schwarzweiß|schwarz-weiss|schwarz-weiß|größer|groesser|kleiner|entfernt|red|blue|green|yellow|black|white|blonde?|lighter|darker|dark|bright|warmer|cooler|more realistic|younger|older|blurry|blurred|sharp|background|color|colour|object|face|hair|beard|clothing|style|remove|removed)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_EDIT_FOLLOWUP_PATTERN =
    /^\s*(?:(?:und\s+)?(?:jetzt|nun|noch|then|now)(?=$|[^\p{L}\p{N}_]).*)?(?:bitte\s+)?(?:(?:mehr|etwas|ein\s+bisschen|more|a\s+bit)\s+)?(?:ganzkörper|ganzkoerper|full[ -]?body|dunkler|heller|wärmer|waermer|kälter|kaelter|realistischer|jünger|juenger|älter|aelter|unscharf|schärfer|schaerfer|weiter\s+(?:raus|weg)|näher|naeher|länger|laenger|kürzer|kuerzer|darker|lighter|warmer|cooler|more realistic|younger|older|blurrier|sharper|zoom(?:ed)?\s+out|zoom(?:ed)?\s+in|longer|shorter)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_QUESTION_PATTERN =
    /^\s*(?:was|wie|welche|welcher|welches|wer|wo|wann|warum|ist|sind|hat|haben|what|how|which|who|where|when|why|is|are|does|do|has|have)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_CREATION_VERB_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:erstelle|erstellen|generiere|generieren|erzeuge|erzeugen|zeichne|zeichnen|mach|mache|create|generate|draw|make)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_NOUN_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:bild|foto|illustration|image|photo|picture)(?=$|[^\p{L}\p{N}_])/iu;

const IMAGE_NOUN_OF_PATTERN =
    /(?:^|[^\p{L}\p{N}_])(?:bild|foto|illustration|image|photo|picture)\s+(?:von|of)(?=$|[^\p{L}\p{N}_])/iu;

const VIDEO_ANIMATE_PATTERN = /\b(?:animier(?:e|en)?\s+(?:dieses|das|mein)?\s*(?:bild|foto)|mach(?:e)?\s+(?:daraus|hieraus)\s+(?:ein\s+)?video|erzeug(?:e|en)?\s+(?:daraus|hieraus)\s+(?:eine\s+)?animation|animate\s+(?:this|that)?\s*(?:image|picture)|turn\s+(?:this|that)\s+(?:image|picture)\s+into\s+(?:a\s+)?video)\b/iu;
const VIDEO_GENERATE_PATTERN = /\b(?:erstelle|generiere|erzeuge|mach(?:e)?|create|generate|make)\b.{0,40}\b(?:video|clip)\b/iu;

function isVideoRequest(prompt) {
    const value = String(prompt || '');
    return VIDEO_ANIMATE_PATTERN.test(value) || VIDEO_GENERATE_PATTERN.test(value);
}

const VIDEO_DURATIONS = new Set([5, 6, 8, 10]);

function videoOptionsForRequest(options, mediaKind, duration = 5) {
    const existing = options?.video || null;
    if (mediaKind !== 'video') return existing;
    const selected = Number(duration);
    return {
        ...(existing || {}),
        duration: VIDEO_DURATIONS.has(selected) ? selected : 5
    };
}

function isImageEditRequest(prompt, hasImage) {
    if (!hasImage) {
        return false;
    }

    const value = String(prompt || '').trim();

    if (!value) {
        return false;
    }

    if (IMAGE_QUESTION_PATTERN.test(value)) {
        return false;
    }

    if (IMAGE_EDIT_VERB_PATTERN.test(value)) {
        return true;
    }

    if (IMAGE_EDIT_FOLLOWUP_PATTERN.test(value)) {
        return true;
    }

    return (
        IMAGE_EDIT_MAKE_PATTERN.test(value) &&
        IMAGE_EDIT_MODIFIER_PATTERN.test(value)
    ) || (
        /(?:^|[^\p{L}\p{N}_])(?:hintergrund|background)(?=$|[^\p{L}\p{N}_])/iu.test(value) &&
        /(?:^|[^\p{L}\p{N}_])(?:unscharf|dunkler|heller|blurry|blurred|darker|lighter)(?=$|[^\p{L}\p{N}_])/iu.test(value)
    ) || (
        /(?:^|[^\p{L}\p{N}_])(?:andere|andre)\s+farb(?:e|en)(?=$|[^\p{L}\p{N}_])/iu.test(value)
    );
}

function isImageComparisonRequest(prompt, hasParentImage) {
    if (!hasParentImage) {
        return false;
    }

    const value = String(prompt || '').trim();

    if (!value) {
        return false;
    }

    const explicitComparison =
        /(?:^|[^\p{L}\p{N}_])(?:vergleich|vergleiche|unterschied|unterschiede|vorher|nachher|before|after|compare|comparison|difference|differences)(?=$|[^\p{L}\p{N}_])/iu;

    const changedStateQuestion =
        /(?:^|[^\p{L}\p{N}_])(?:verändert|veraendert|geändert|geaendert|anders|changed|modified|different)(?=$|[^\p{L}\p{N}_])/iu;

    return (
        explicitComparison.test(value) ||
        (
            IMAGE_QUESTION_PATTERN.test(value) &&
            changedStateQuestion.test(value)
        )
    );
}


function isImageGenerationRequest(prompt) {
    const value = String(prompt || '').trim();

    return IMAGE_NOUN_OF_PATTERN.test(value) || (
        IMAGE_CREATION_VERB_PATTERN.test(value) &&
        IMAGE_NOUN_PATTERN.test(value)
    );
}

(function () {
    let getGenerating;
    let setGenerating;
    let getAbortController;
    let setAbortController;

    const IMAGE_UPSCALE_PRESETS = Object.freeze([
        Object.freeze({
            preset: 'photo-2x',
            labelKey: 'image_upscale_photo_2x',
            fallback: '2× Photo'
        }),
        Object.freeze({
            preset: 'photo-4x',
            labelKey: 'image_upscale_photo_4x',
            fallback: '4× Photo'
        }),
        Object.freeze({
            preset: 'anime-4x',
            labelKey: 'image_upscale_illustration_4x',
            fallback: '4× Illustration'
        })
    ]);

    const input = document.getElementById('input');

    function configure(options) {
        getGenerating = options.getGenerating;
        setGenerating = options.setGenerating;
        getAbortController = options.getAbortController;
        setAbortController = options.setAbortController;
    }


function persistentChatRevision(session) {
    const revision = Number(session?.revision);

    return (
        Number.isSafeInteger(revision) &&
        revision >= 0
    )
        ? revision
        : 0;
}


function imageAttachments(message) {
    const attachments =
        Array.isArray(message?.attachments)
            ? message.attachments
            : [];

    const visionImages =
        Array.isArray(message?.vision_images)
            ? message.vision_images
            : [];

    return [
        ...attachments,
        ...visionImages
    ].filter(
        attachment =>
            attachment.kind === 'image' &&
            attachment.data_url
    );
}


async function imageArtifactDataUrl(artifact) {
    if (!artifact?.image_id) {
        throw new Error(
            'Image artifact does not contain an image_id'
        );
    }

    const response = await fetch(
        '/api/mlx/images/' +
        encodeURIComponent(artifact.image_id)
    );

    if (!response.ok) {
        throw new Error(
            'Image could not be loaded for analysis: ' +
            response.status
        );
    }

    const blob = await response.blob();

    return await new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () =>
            resolve(reader.result);

        reader.onerror = () =>
            reject(
                new Error(
                    'Image could not be read'
                )
            );

        reader.readAsDataURL(blob);
    });
}


function sessionImageArtifacts(session) {
    return (session?.messages || [])
        .slice()
        .reverse()
        .flatMap(message => {
            const result = message?.tool_result;
            if (
                result?.status !== 'completed' ||
                !isImageJobTool(result?.tool)
            ) {
                return [];
            }
            const artifacts = result.artifacts;
            return Array.isArray(artifacts) ? artifacts : [];
        })
        .filter(artifact => {
            const artifactId =
                String(artifact?.artifact_id || '');

            if (
                !/^image-\d{10}-[0-9a-f]{12}$/.test(
                    artifactId
                )
            ) {
                return false;
            }

            const imageId =
                String(artifact?.image_id || '');

            if (
                imageId &&
                !/^\d{10}-[0-9a-f]{12}$/.test(imageId)
            ) {
                return false;
            }

            const mimeType =
                String(artifact?.mime_type || '');

            if (
                mimeType &&
                !mimeType.startsWith('image/')
            ) {
                return false;
            }

            return true;
        });
}


function imageUpscalePresets() {
    return IMAGE_UPSCALE_PRESETS.map(item => ({ ...item }));
}

function createImageUpscaleMenu(source) {
    const menu = document.createElement('details');
    menu.className = 'image-upscale-menu';

    const summary = document.createElement('summary');
    summary.className = 'message-action-btn';
    summary.textContent = gt('image_enhance', 'Enhance image');
    menu.appendChild(summary);

    const choices = document.createElement('div');
    choices.className = 'image-upscale-menu-options';

    for (const option of IMAGE_UPSCALE_PRESETS) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'image-upscale-option';
        button.textContent = gt(
            option.labelKey,
            option.fallback
        );
        button.addEventListener('click', async () => {
            menu.open = false;
            await startImageUpscale(source, option.preset);
        });
        choices.appendChild(button);
    }

    menu.appendChild(choices);
    return menu;
}


async function startImageUpscale(source, preset = 'photo-2x') {
    if (MLXChatRuntime.isSwitching() || getGenerating()) {
        return false;
    }

    const option = IMAGE_UPSCALE_PRESETS.find(
        item => item.preset === preset
    );
    if (!option) {
        return false;
    }

    const session = MLXChatSessions.currentSession();
    if (!session) {
        return false;
    }

    let selectedSource = source || activeSessionImageArtifact(session);
    if (!selectedSource) {
        selectedSource = MLXChatAttachments.getAttachments()
            .find(item => item.kind === 'image') || null;
    }

    let fileContext = null;
    let activeArtifactId = null;
    let sourceAttachment = null;

    try {
        if (selectedSource?.artifact_id) {
            const knownArtifact = sessionImageArtifacts(session).find(
                artifact =>
                    artifact.artifact_id === selectedSource.artifact_id
            );
            if (knownArtifact) {
                activeArtifactId = knownArtifact.artifact_id;
            }
        } else if (selectedSource?.kind === 'image') {
            let storedPath =
                selectedSource.stored_path ||
                selectedSource.path ||
                null;
            let storedName = selectedSource.file_id || null;

            if (!storedPath && selectedSource.file) {
                const uploaded = await MLXChatAttachments
                    .uploadImageAttachments([selectedSource]);
                const item = uploaded[0];
                if (!item?.upload?.path) {
                    throw new Error(
                        gt(
                            'image_upload_failed',
                            'Image could not be uploaded.'
                        )
                    );
                }
                storedPath = item.upload.path;
                storedName = item.upload.stored_name || storedName;
                selectedSource.stored_path = storedPath;
                selectedSource.file_id = storedName;
            }

            if (storedPath) {
                fileContext = {
                    ...selectedSource,
                    kind: 'image',
                    mime_type:
                        selectedSource.mime_type ||
                        selectedSource.type ||
                        'image/jpeg',
                    stored_path: storedPath,
                    file_id: storedName
                };
                sourceAttachment = {
                    name: selectedSource.name,
                    size: selectedSource.size,
                    type:
                        selectedSource.type ||
                        selectedSource.mime_type,
                    extension: selectedSource.extension,
                    kind: 'image',
                    data_url: selectedSource.data_url
                };
            }
        }

        if (!fileContext?.stored_path && !activeArtifactId) {
            throw new Error(
                gt(
                    'image_upscale_source_required',
                    'Please select an image to enhance.'
                )
            );
        }

        const prompt = gt(
            'image_upscale_request',
            'Enhance image · {preset}',
            { preset: gt(option.labelKey, option.fallback) }
        );
        const userMessage = {
            role: 'user',
            trace_id: newTraceId(),
            content: prompt,
            display_content: prompt,
            attachments: sourceAttachment ? [sourceAttachment] : []
        };
        session.messages.push(userMessage);

        if (sourceAttachment) {
            MLXChatAttachments.removeAttachment?.(selectedSource);
        }

        const pendingMessage = {
            role: 'assistant',
            content: gt(
                'image_upscaling',
                'Enhancing the image locally with Real-ESRGAN …'
            ),
            image_generation_pending: true,
            image_parent_artifact_id: activeArtifactId || null
        };
        session.messages.push(pendingMessage);
        MLXChatSessions.updateTitle(session);
        session.updated = Date.now();
        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll({ contentUpdated: true });

        const response = await fetch('/api/mlx/chat/actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'image_upscale',
                prompt,
                file_context: fileContext,
                active_artifact_id: activeArtifactId,
                image_options: { preset: option.preset },
                conversation_context: buildAgentConversationContext(
                    session,
                    userMessage
                ),
                trace_id: userMessage.trace_id,
                chat_id: session.id,
                chat_revision: persistentChatRevision(session)
            })
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }

        const toolResult = await response.json();

        // Ignore a late upscale response after the chat was cleared
        // or the user switched to another session.
        if (
            MLXChatSessions.currentSession() !== session ||
            !session.messages.includes(pendingMessage)
        ) {
            const staleJob = toolResult?.data?.job;

            if (
                staleJob?.id &&
                IMAGE_JOB_ID_PATTERN.test(String(staleJob.id)) &&
                ACTIVE_IMAGE_JOB_STATUSES.has(staleJob.status)
            ) {
                fetch(
                    '/api/mlx/image-jobs/' +
                        encodeURIComponent(staleJob.id) +
                        '/cancel',
                    { method: 'POST' }
                ).catch(() => {});
            }

            return false;
        }

        if (toolResult.tool !== 'image_upscale') {
            throw new Error(
                gt(
                    'image_upscale_unexpected_action',
                    'The image enhancement action was not accepted.'
                )
            );
        }

        if (toolResult.data?.job?.id) {
            const terminal = updateImageJobMessage(
                session,
                pendingMessage,
                toolResult
            );
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({ contentUpdated: true });
            if (!terminal) {
                watchImageJob(session, pendingMessage);
            }
            return true;
        }

        pendingMessage.tool_result = toolResult;
        pendingMessage.image_generation_pending = false;
        if (
            toolResult.status === 'completed' &&
            toolResult.artifacts?.[0]?.artifact_id
        ) {
            session.workspace = {
                ...(session.workspace || {}),
                active_artifact_id:
                    toolResult.artifacts[0].artifact_id
            };
            pendingMessage.content = toolSummary(toolResult);
        } else {
            pendingMessage.content = toolFailureSummary(toolResult);
        }
        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll({ contentUpdated: true });
        return toolResult.status === 'completed';
    } catch (error) {
        const pendingMessage = session.messages.at(-1);
        if (pendingMessage?.image_generation_pending) {
            pendingMessage.image_generation_pending = false;
            pendingMessage.tool_result = {
                tool: 'image_upscale',
                status: 'failed',
                data: {},
                artifacts: [],
                error: error.message
            };
            pendingMessage.content = toolFailureSummary(
                pendingMessage.tool_result
            );
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({ contentUpdated: true });
        }
        return false;
    }
}


function activeSessionImageArtifact(session) {

    const activeArtifactId =
        session?.workspace?.active_artifact_id;

    if (!activeArtifactId) return null;

    const artifact =
        sessionImageArtifacts(session).find(
            item =>
                item.artifact_id === activeArtifactId
        );

    if (artifact) {
        return artifact;
    }

    // The workspace artifact ID is already a valid reference to a
    // server-managed generated image. Preserve image follow-ups even
    // when the originating tool_result is missing from session.messages.
    if (
        /^image-\d{10}-[0-9a-f]{12}$/i.test(
            activeArtifactId
        )
    ) {
        const imageId =
            activeArtifactId.replace(/^image-/, '');

        return {
            artifact_id: activeArtifactId,
            image_id: imageId,
            name: 'generated-image.png',
            mime_type: 'image/png'
        };
    }

    return null;
}


function imageConversationState(session) {
    const artifacts = sessionImageArtifacts(session);

    const active =
        activeSessionImageArtifact(session) ||
        artifacts[0] ||
        null;

    const parent =
        active?.parent_artifact_id
            ? artifacts.find(
                artifact =>
                    artifact.artifact_id === active.parent_artifact_id
            ) || null
            : null;

    return {
        artifacts,
        active,
        parent,
        has_active_image: Boolean(active),
        has_parent_image: Boolean(parent)
    };
}


function latestSessionImageUpload(session) {
    for (const message of [...(session?.messages || [])].reverse()) {
        const candidates = [
            ...(Array.isArray(message?.attachments) ? message.attachments : []),
            ...(Array.isArray(message?.vision_images) ? message.vision_images : [])
        ];
        for (const image of candidates.reverse()) {
            if (
                image?.kind === 'image' &&
                typeof image.stored_path === 'string' &&
                image.stored_path
            ) {
                return image;
            }
        }
    }
    return null;
}


function preferredVideoImageSource(session, currentImages = []) {
    const newestCurrent = [...currentImages]
        .reverse()
        .find(image => image?.kind === 'image');
    if (newestCurrent) return { origin: 'current_upload', source: newestCurrent };
    const active = activeSessionImageArtifact(session);
    if (active) return { origin: 'active_artifact', source: active };
    return null;
}


function buildApiMessages(messages) {
    return messages.map(message => {
        if (message.role !== 'user') {
            return {
                role: message.role,
                content: message.content
            };
        }

        const images =
            imageAttachments(message);

        if (!images.length) {
            return {
                role: message.role,
                content: message.content
            };
        }

        const content = [];

        if (
            typeof message.content === 'string' &&
            message.content.trim()
        ) {
            content.push({
                type: 'text',
                text: message.content
            });
        }

        for (const image of images) {
            content.push({
                type: 'image_url',
                image_url: {
                    url: image.data_url
                }
            });
        }

        return {
            role: message.role,
            content: content
        };
    });
}


function newTraceId() {
    return globalThis.crypto?.randomUUID
        ? globalThis.crypto.randomUUID()
        : 'trace-' + Date.now().toString(16) +
            Math.random().toString(16).slice(2);
}


function textCharacters(value) {
    if (typeof value === 'string') {
        return value.length;
    }

    if (Array.isArray(value)) {
        return value.reduce(
            (total, item) => total + textCharacters(item),
            0
        );
    }

    if (value && typeof value === 'object') {
        return Object.entries(value).reduce(
            (total, [key, item]) =>
                ['image_url', 'url', 'data_url'].includes(key)
                    ? total
                    : total + textCharacters(item),
            0
        );
    }

    return 0;
}


function buildContextSources(messages) {
    const sources = {
        system: { characters: 0, items: 0 },
        profile: { characters: 0, items: 0 },
        history: { characters: 0, items: 0 },
        knowledge_rag: { characters: 0, items: 0 },
        document_web: { characters: 0, items: 0 },
        attachments: { characters: 0, items: 0 },
        tool_agent: { characters: 0, items: 0 }
    };

    for (const message of messages || []) {
        const characters = textCharacters(message?.content);
        const declared = message?._context_sources || {};
        let declaredCharacters = 0;

        for (const [source, value] of Object.entries(declared)) {
            if (!sources[source]) continue;
            const sourceCharacters = Math.max(
                0,
                Number(value?.characters || 0)
            );
            const sourceItems = Math.max(
                0,
                Number(value?.items || 0)
            );
            sources[source].characters += sourceCharacters;
            sources[source].items += sourceItems;
            declaredCharacters += sourceCharacters;
        }

        const defaultSource =
            message?.role === 'system' ? 'system' : 'history';
        sources[defaultSource].characters += Math.max(
            0,
            characters - declaredCharacters
        );
        sources[defaultSource].items += 1;
    }

    return sources;
}


async function* readSseEvents(reader) {
    const decoder = new TextDecoder();
    let buffer = '';

    function takeEvents(final = false) {
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        if (final && buffer.trim()) {
            events.push(buffer);
            buffer = '';
        }

        return events;
    }

    while (true) {
        const { value, done } = await reader.read();

        if (done) {
            buffer += decoder.decode();

            for (const event of takeEvents(true)) {
                yield event;
            }

            return;
        }

        buffer += decoder.decode(value, { stream: true });

        for (const event of takeEvents()) {
            yield event;
        }
    }
}


function defaultVisionPrompt(imageCount) {
    if (imageCount > 1) {
        return gt(
            'vision_describe_images_prompt',
            'Describe all attached images in order. Answer in English.'
        );
    }

    return gt(
        'vision_describe_image_prompt',
        'Describe this image in detail. Answer in English.'
    );
}


async function regenerateLastAnswer() {
    if (
        getGenerating() ||
        MLXChatRuntime.isSwitching()
    ) return;

    const session =
        MLXChatSessions.currentSession();

    if (!session) return;

    if (
        !session.messages.length ||
        session.messages[
            session.messages.length - 1
        ].role !== 'assistant'
    ) {
        return;
    }

    session.messages.pop();

    MLXChatSessions.saveSessions();
    MLXChatRuntime.beginUserMessage();
    MLXChatRendering.renderAll({
        contentUpdated: true
    });

    await generateAssistant(
        session
    );
}


function stripTrailingSvgStreamArtifact(text) {
    const value = String(text ?? '');

    if (!value.trim()) {
        return value;
    }

    const lines = value.split(/\r?\n/);

    let start = lines.length;
    let artifactLines = 0;
    let svgOccurrences = 0;

    while (start > 0) {
        const line = lines[start - 1].trim();

        // Leerzeilen direkt innerhalb/vor dem Artefakt-Tail mitnehmen.
        if (!line) {
            if (artifactLines > 0) {
                start -= 1;
                continue;
            }

            break;
        }

        const compact = line.replace(/\s+/g, '');

        if (!/^(?:svg)+$/i.test(compact)) {
            break;
        }

        artifactLines += 1;
        svgOccurrences += (
            compact.match(/svg/gi) || []
        ).length;

        start -= 1;
    }

    // Zu wenig Evidenz:
    // Eine einzelne SVG-Zeile oder "SVG SVG" bleibt legitimer Inhalt.
    if (
        artifactLines === 0 ||
        (artifactLines < 2 && svgOccurrences < 3)
    ) {
        return value;
    }

    const prefix = lines
        .slice(0, start)
        .join('\n')
        .trimEnd();

    // Wenn praktisch die komplette Antwort nur aus SVG besteht,
    // nichts verändern.
    if (!prefix.trim()) {
        return value;
    }

    // Nicht innerhalb eines offenen Markdown-Codeblocks eingreifen.
    const backtickFences =
        (prefix.match(/```/g) || []).length;

    const tildeFences =
        (prefix.match(/~~~/g) || []).length;

    if (
        backtickFences % 2 !== 0 ||
        tildeFences % 2 !== 0
    ) {
        return value;
    }

    return prefix;
}


async function generateAssistant(session) {
if (
        getGenerating() ||
        MLXChatRuntime.isSwitching()
    ) {
return;
    }

    const runtimeRevision =
        MLXChatSessions.runtimeRevision(session);

    const generationIsCurrent = () =>
        MLXChatSessions.runtimeRevisionIsCurrent(
            session,
            runtimeRevision
        );

    if (!generationIsCurrent()) {
        return;
    }

    const generationSettings =
        MLXChatRuntime
            .getSessionGenerationSettings();

    const generationStartedAt =
        performance.now();

    let firstContentAt = null;
    let completed = false;

    const assistantMessage = {
        role: 'assistant',
        content: '',
        reasoning: '',
        sources: [],
        thinking_seconds: null,
        response_pending: true,
        metrics: {
            started_at: Date.now()
        }
    };

    session.messages.push(
        assistantMessage
    );

    session.updated =
        Date.now();

    MLXChatSessions.saveSessions();

    setGenerating(true);
    setAbortController(
        new AbortController()
    );
MLXChatRuntime.updateSendButton();
MLXChatRendering.renderAll({
    contentUpdated: true
});
try {
        const turnMessage = session.messages
            .slice(0, -1)
            .reverse()
            .find(message => message?.role === 'user');
        const traceId = turnMessage?.trace_id || newTraceId();
        if (turnMessage && !turnMessage.trace_id) {
            turnMessage.trace_id = traceId;
        }
        const apiMessages =
            buildApiMessages(
                session.messages.slice(0, -1)
            );

        const response = await fetch(
            '/api/chat/stream',
            {
                method: 'POST',

                headers: {
                    'Content-Type':
                        'application/json'
                },

                signal:
                    getAbortController().signal,

                body: JSON.stringify({
                    messages: apiMessages,

                    temperature:
                        generationSettings.temperature,

                    max_tokens:
                        generationSettings.max_tokens,

                    system_prompt:
                        MLXChatRuntime
                            .getSessionSystemPrompt(),

                    trace_id: traceId,

                    context_sources:
                        buildContextSources(
                            session.messages.slice(0, -1)
                        )
                })
            }
        );

        if (!generationIsCurrent()) {
            try {
                await response.body?.cancel?.();
            } catch (_error) {}

            return;
        }

        if (!response.ok) {
            const error =
                await response.text();

            throw new Error(error);
        }

        const reader =
            response.body.getReader();

        for await (const event of readSseEvents(reader)) {
                if (!generationIsCurrent()) {
                    try {
                        await reader.cancel();
                    } catch (_error) {}

                    return;
                }

                if (
                    event.startsWith(
                        'event: done'
                    )
                ) {
                    continue;
                }

                if (
                    event.startsWith(
                        'event: sources'
                    )
                ) {
                    const dataLine =
                        event
                            .split('\n')
                            .find(
                                line =>
                                    line.startsWith(
                                        'data:'
                                    )
                            );

                    if (dataLine) {
                        const sourceData =
                            JSON.parse(
                                dataLine.slice(5)
                            );

                        assistantMessage.sources =
                            Array.isArray(
                                sourceData.sources
                            )
                                ? sourceData.sources
                                : [];

                        MLXChatSessions.saveSessions();
                    }

                    continue;
                }

                if (
                    event.startsWith(
                        'event: metrics'
                    )
                ) {
                    const dataLine = event
                        .split('\n')
                        .find(line => line.startsWith('data:'));

                    if (dataLine) {
                        assistantMessage.model_metrics = JSON.parse(
                            dataLine.slice(5)
                        );
                        MLXChatSessions.saveSessions();
                    }

                    continue;
                }

                if (
                    event.startsWith(
                        'event: error'
                    )
                ) {
                    const dataLine =
                        event
                            .split('\n')
                            .find(
                                line =>
                                    line.startsWith(
                                        'data:'
                                    )
                            );

                    if (dataLine) {
                        const data =
                            JSON.parse(
                                dataLine.slice(5)
                            );

                        throw new Error(
                            data.error
                        );
                    }

                    continue;
                }

                const dataLine =
                    event
                        .split('\n')
                        .find(
                            line =>
                                line.startsWith(
                                    'data:'
                                )
                        );

                if (!dataLine) continue;

                const data =
                    JSON.parse(
                        dataLine.slice(5)
                    );

                if (data.text) {

                    if (
                        data.type === 'reasoning'
                    ) {
                        if (
                            !assistantMessage._thinkingStarted
                        ) {
                            assistantMessage._thinkingStarted =
                                performance.now();
                        }

                        assistantMessage.reasoning +=
                            data.text;

                    } else {
                        if (firstContentAt === null) {
                            firstContentAt =
                                performance.now();
                        }

                        if (
                            assistantMessage._thinkingStarted &&
                            assistantMessage.thinking_seconds === null
                        ) {
                            assistantMessage.thinking_seconds =
                                (
                                    performance.now() -
                                    assistantMessage._thinkingStarted
                                ) / 1000;
                        }

                        assistantMessage.content +=
                            data.text;
                    }

                    MLXChatRendering.renderMessages({
                        contentUpdated: true
                    });
                }
        }

        completed = true;

        if (
            assistantMessage._thinkingStarted &&
            assistantMessage.thinking_seconds === null
        ) {
            assistantMessage.thinking_seconds =
                (
                    performance.now() -
                    assistantMessage._thinkingStarted
                ) / 1000;
        }

        const cleanedAssistantContent =
            stripTrailingSvgStreamArtifact(
                assistantMessage.content
            );

        if (
            cleanedAssistantContent !==
            assistantMessage.content
        ) {
            console.warn(
                '[MLX Chat] Removed trailing SVG stream artifact'
            );

            assistantMessage.content =
                cleanedAssistantContent;
        }

        delete assistantMessage._thinkingStarted;

        MLXChatSessions.saveSessions();

    } catch (error) {

        if (
            error.name !== 'AbortError'
        ) {
            assistantMessage.content +=
                '\n\n' + gt(
                'error_markdown',
                '**Error:** {message}',
                { message: error.message }
            );
        }

        MLXChatSessions.saveSessions();

    } finally {
        assistantMessage.response_pending = false;

        if (
            assistantMessage._thinkingStarted &&
            assistantMessage.thinking_seconds === null
        ) {
            assistantMessage.thinking_seconds =
                (
                    performance.now() -
                    assistantMessage._thinkingStarted
                ) / 1000;
        }

        delete assistantMessage._thinkingStarted;

        const totalMs = Math.max(
            0,
            Math.round(
                performance.now() -
                generationStartedAt
            )
        );

        const firstContentMs =
            firstContentAt === null
                ? null
                : Math.max(
                    0,
                    Math.round(
                        firstContentAt -
                        generationStartedAt
                    )
                );

        const outputChars =
            assistantMessage.content.length;

        const estimatedTokens =
            Math.max(
                0,
                Math.round(outputChars / 4)
            );

        const contentDurationMs =
            firstContentMs === null
                ? null
                : totalMs - firstContentMs;

        const tokensPerSecond =
            completed &&
            contentDurationMs > 0 &&
            estimatedTokens > 0
                ? Number(
                    (
                        estimatedTokens /
                        (contentDurationMs / 1000)
                    ).toFixed(1)
                )
                : null;

        assistantMessage.metrics = {
            started_at:
                assistantMessage.metrics.started_at,
            first_content_ms: firstContentMs,
            total_ms: totalMs,
            thinking_ms:
                assistantMessage.thinking_seconds === null
                    ? null
                    : Math.max(
                        0,
                        Math.round(
                            assistantMessage.thinking_seconds *
                            1000
                        )
                    ),
            output_chars: outputChars,
            estimated_tokens: estimatedTokens,
            tokens_per_second: tokensPerSecond
        };

        MLXChatSessions.saveSessions();

        setGenerating(false);
        setAbortController(null);

        MLXChatRuntime.updateSendButton();
        MLXChatRendering.renderAll({
            contentUpdated: true
        });
    }
}





function buildAgentConversationContext(
    session,
    currentMessage
) {
    return (session?.messages || [])
        .filter(message =>
            message !== currentMessage &&
            ['user', 'assistant'].includes(message?.role)
        )
        .slice(-8)
        .map(message => {
            let content = String(
                message.display_content ||
                message.content ||
                ''
            ).slice(0, 2000);

            if (message.agent_run?.goal) {
                content +=
                    '\nAgent-Auftrag: ' +
                    String(message.agent_run.goal).slice(0, 1000);
            }

            return {
                role: message.role,
                content: content
            };
        })
        .filter(message => message.content.trim());
}


let agentRunActive = false;

function renderAgentSafely() {
    try {
        MLXChatRendering.renderAll({ contentUpdated: true });
    } catch (error) {
        console.error('[MLX Agent rendering]', error);
    }
}

async function runAgent(
    session,
    goal,
    assistantMessage,
    mode = 'diagnostic',
    conversationContext = [],
    traceId = newTraceId(),
    resources = {}
) {
    agentRunActive = true;
    setGenerating(true);
    MLXChatRuntime.updateSendButton();

    const agentAbortController = new AbortController();
    setAbortController(agentAbortController);

    const runId = globalThis.crypto?.randomUUID
        ? globalThis.crypto.randomUUID()
        : 'run-' + Date.now().toString(16) +
            Math.random().toString(16).slice(2);
    let progressTimer = null;

    assistantMessage.agent_run = {
        status: 'running',
        goal: goal,
        steps: [],
        pending_action: null
    };

    MLXChatSessions.saveSessions();
    renderAgentSafely();

    try {
        const pollProgress = async () => {
            try {
                const response = await fetch(
                    '/api/mlx/agent/runs/' + encodeURIComponent(runId),
                    {
                        signal: agentAbortController.signal
                    }
                );
                if (!response.ok) return;
                const progress = await response.json();
                if (!session.messages.includes(assistantMessage)) return;
                const liveSteps = Array.isArray(progress.steps)
                    ? [...progress.steps]
                    : [];
                if (progress.current_step) {
                    liveSteps.push(progress.current_step);
                }
                assistantMessage.agent_run = {
                    status: progress.status || 'running',
                    goal: progress.goal || goal,
                    steps: liveSteps,
                    pending_action: progress.pending_action || null
                };
                MLXChatSessions.saveSessions();
                renderAgentSafely();
            } catch (_error) {
                // The synchronous endpoint remains the authoritative response.
            }
        };

        progressTimer = setInterval(pollProgress, 800);
        pollProgress();

        await MLXChatSessions.persistSession(session);
        if (!session.messages.includes(assistantMessage)) return;

        const response = await fetch(
            '/api/mlx/agent/run',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    goal: goal,
                    mode: mode,
                    run_id: runId,
                    trace_id: traceId,
                    chat_id: session.id,
                    chat_revision: persistentChatRevision(session),
                    attachments: resources.attachments || [],
                    active_artifact_id: resources.activeArtifactId || null,
                    workspace_id: resources.workspaceId || null,
                    workspace_bound: true,
                    conversation_context:
                        conversationContext
                }),
                signal: agentAbortController.signal
            }
        );

        if (!response.ok) {
            throw new Error(
                await response.text()
            );
        }

        const data = await response.json();
        if (!session.messages.includes(assistantMessage)) return;

        assistantMessage.agent_run = {
            status: data.status || 'completed',
            goal: data.goal || goal,
            steps: Array.isArray(data.steps)
                ? data.steps
                : [],
            pending_action:
                data.pending_action || null
        };

        assistantMessage.content =
            data.answer || '';
        assistantMessage.model_metrics =
            data.model_metrics || null;

    } catch (error) {
        if (error?.name === 'AbortError') {
            assistantMessage.agent_run = {
                ...(assistantMessage.agent_run || {}),
                status: 'cancelled',
                goal: goal,
                pending_action: null
            };
        } else {
            console.error(
                '[MLX Agent]',
                error
            );

            assistantMessage.agent_run = {
                status: 'failed',
                goal: goal,
                steps: [],
                pending_action: null
            };

            assistantMessage.content = gt(
                'agent_error',
                'Agent error: {message}',
                {
                    message:
                        error?.message ||
                        String(error)
                }
            );
        }

    } finally {
        if (progressTimer) {
            clearInterval(progressTimer);
        }
        agentRunActive = false;
        setGenerating(false);
        setAbortController(null);
        MLXChatRuntime.updateSendButton();

        MLXChatSessions.saveSessions();
        renderAgentSafely();
    }
}



async function approveAgentAction(
    message,
    approved
) {
    const session =
        MLXChatSessions.currentSession();

    const pending =
        message?.agent_run?.pending_action;

    if (
        !session ||
        !pending?.approval_id ||
        getGenerating()
    ) {
        return;
    }

    const approvalId =
        pending.approval_id;

    message.agent_run.status =
        'running';

    message.agent_run.pending_action =
        null;

    agentRunActive = true;
    setGenerating(true);
    MLXChatRuntime.updateSendButton();

    MLXChatSessions.saveSessions();
    renderAgentSafely();

    try {
        const response = await fetch(
            '/api/mlx/agent/approve/' +
            encodeURIComponent(approvalId),
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    approved: Boolean(approved)
                })
            }
        );

        if (!response.ok) {
            throw new Error(
                await response.text()
            );
        }

        const data =
            await response.json();

        message.agent_run = {
            status: data.status || 'completed',
            goal: data.goal || message.agent_run.goal || '',
            steps: Array.isArray(data.steps)
                ? data.steps
                : [],
            pending_action:
                data.pending_action || null
        };

        message.content =
            data.answer || '';

    } catch (error) {
        console.error(
            '[MLX Agent Approval]',
            error
        );

        message.agent_run.status =
            'failed';

        message.content = gt(
            'agent_approval_failed',
            'Agent approval failed: {message}',
            { message: error?.message || String(error) }
        );

    } finally {
        agentRunActive = false;
        setGenerating(false);
        MLXChatRuntime.updateSendButton();

        MLXChatSessions.saveSessions();
        renderAgentSafely();
    }
}


async function sendMessage(options = {}) {
    if (agentRunActive) return;
if (MLXChatRuntime.isSwitching()) {
return;
    }

    if (getGenerating()) {
getAbortController()?.abort();
        return;
    }

    const prompt =
        input.value.trim();

    const currentAttachments =
        MLXChatAttachments.getAttachments();

    if (
        !prompt &&
        !currentAttachments.length
    ) {
return;
    }

    const session =
        MLXChatSessions.currentSession();

    if (!session) {

        return;
    }
const imageFiles =
        currentAttachments.filter(
            file => file.kind === 'image'
        );

    const textFiles =
        currentAttachments.filter(
            file => file.kind === 'text'
        );

    const imageState =
        imageConversationState(session);

    const imageArtifactCandidates =
        imageState.artifacts;

    const activeWorkspaceImageArtifact =
        activeSessionImageArtifact(session);

    const activeImageArtifact =
        imageState.active;

    const explicitImageEditRequest =
        isImageEditRequest(
            prompt,
            imageFiles.length > 0 ||
                Boolean(activeImageArtifact)
        );
    const explicitVideoAnimateRequest = VIDEO_ANIMATE_PATTERN.test(prompt);
    const preferredVideoSource = explicitVideoAnimateRequest
        ? preferredVideoImageSource(session, imageFiles)
        : null;

    const imageComparisonRequest =
        isImageComparisonRequest(
            prompt,
            imageState.has_parent_image
        );

    const refersToExistingImage =
        imageComparisonRequest ||
        /\b(?:das|dieses|diesem|dieser|bild|foto|abbildung|es|davon|darauf)\b|\bist\s+das\b|\bsieht\s+(?:das|es)\b/i
            .test(prompt);
    const transformPattern = /anonymis|entfern|bereinig|ersetz|änder|aender|transformier|schwärz|schwaerz/i;
    const fileOperationPattern = /anonymis|entfern|bereinig|ersetz|änder|aender|transformier|schwärz|schwaerz|fass|zusammenfass|prüf|pruef|struktur|datensätz|datensaetz|felder|zeitraum|auffällig|auffaellig|problem|muster|analys/i;

    const fileExcerptPattern =
        /\b(?:erste[nrms]?|letzte[nrms]?|first|last)\s+\d+\s+(?:zeile|zeilen|lines?)\b|\b(?:zeile|zeilen|lines?)\s+\d+(?:\s*(?:-|–|—|bis|to|through)\s*\d+)?\b/i;
    const auditPattern = /pii\s*audit|personenbezogene daten|noch.*daten.*drin|nochmal.*prüf|nochmal.*pruef/i;
    const artifactCandidates = session.messages.slice().reverse().flatMap(message =>
        message.file_artifact ? [message.file_artifact] : []
    ).filter(file => file.kind === 'text' && file.stored_path);
    const activeArtifactId = session.workspace?.active_artifact_id;
    const activeArtifact = artifactCandidates.find(file => file.artifact_id === activeArtifactId);
    const uploadCandidates = session.messages.slice().reverse().flatMap(message =>
        Array.isArray(message.attachments) ? message.attachments : []
    ).filter(file => file.kind === 'text' && file.stored_path);
    const priorFileAttachments = activeArtifact ? [activeArtifact] : (artifactCandidates.length ? artifactCandidates : uploadCandidates);
    const refersToExistingFile =
        /\b(?:sie|datei|diese|diesen|ergebnis|letzte|bearbeitete|neue|es|das|darin|davon|daraus|inhalt|inhaltlich|zeile|zeilen|feld|felder|datensatz|datensätze|record|records|json|csv|sql)\b/i
            .test(prompt);
    const ambiguousArtifactReference = !textFiles.length && !activeArtifact && refersToExistingFile && artifactCandidates.length > 1;
    /*
     * Newly attached text/data files always use the dedicated file
     * pipeline. Follow-up operations on existing files still require
     * an explicit file-operation intent.
     */
    const routesFileOperation =
        !auditPattern.test(prompt) &&
        (
            textFiles.length > 0 ||
            (
                (
                    fileOperationPattern.test(prompt) ||
                    fileExcerptPattern.test(prompt)
                ) &&
                refersToExistingFile &&
                priorFileAttachments.length > 0
            )
        );



    let documentPageContext = '';
    let documentRagContext = '';

    const currentDocumentFiles =
        currentAttachments.filter(
            file => file.kind === 'document'
        );

    /*
     * Documents remain active in the conversation after the first send.
     *
     * Priority:
     * 1. currently attached document
     * 2. most recently used document from the chat history
     */
    const priorDocumentFiles =
        session.messages
            .slice()
            .reverse()
            .flatMap(message =>
                Array.isArray(message.attachments)
                    ? message.attachments
                    : []
            )
            .filter(file =>
                file.kind === 'document' &&
                file.document_id
            );

    const documentFiles =
        currentDocumentFiles.length
            ? currentDocumentFiles
            : (
                priorDocumentFiles.length
                    ? [priorDocumentFiles[0]]
                    : []
            );

    const usingPriorDocument =
        !currentDocumentFiles.length &&
        documentFiles.length > 0;

    if (usingPriorDocument) {
        console.log(
            '[MLX PDF] Reusing conversation document:',
            documentFiles[0].name,
            documentFiles[0].document_id
        );
    }

    if (documentFiles.length) {
        const pageMatch =
            prompt.match(
                /\bseite\s+(\d+)\b/i
            );

        if (pageMatch) {
            const requestedPage =
                Number(pageMatch[1]);

            const document =
                documentFiles[0];

            const page =
                Array.isArray(document.page_texts)
                    ? document.page_texts.find(
                        item =>
                            Number(item.page) ===
                            requestedPage
                    )
                    : null;

            if (page && page.text) {
                documentPageContext =
                    '\n\n--- DOKUMENT: ' +
                    document.name +
                    ' · SEITE ' +
                    requestedPage +
                    ' ---\n' +
                    page.text +
                    '\n--- ENDE SEITE ' +
                    requestedPage +
                    ' ---';

                console.log(
                    '[MLX PDF] Exact page lookup:',
                    document.name,
                    requestedPage
                );

            } else if (document.document_id) {
                try {
                    const pageResponse = await fetch(
                        '/api/mlx/documents/' +
                        encodeURIComponent(document.document_id) +
                        '/page/' +
                        requestedPage,
                        {
                            cache: 'no-store'
                        }
                    );

                    if (!pageResponse.ok) {
                        throw new Error(
                            await pageResponse.text()
                        );
                    }

                    const pageData =
                        await pageResponse.json();

                    if (pageData.text) {
                        documentPageContext =
                            '\n\n--- DOKUMENT: ' +
                            (pageData.name || document.name) +
                            ' · SEITE ' +
                            requestedPage +
                            ' ---\n' +
                            pageData.text +
                            '\n--- ENDE SEITE ' +
                            requestedPage +
                            ' ---';

                        console.log(
                            '[MLX PDF] Persistent page lookup:',
                            pageData.name || document.name,
                            requestedPage,
                            pageData.chunks
                        );
                    } else {
                        documentPageContext =
                            '\n\n' + gt(
                            'page_no_text',
                            'Note: Page {page} contains no readable text.',
                            { page: requestedPage }
                        );
                    }

                } catch (error) {
                    console.error(
                        '[MLX PDF] Persistent page lookup failed',
                        error
                    );

                    documentPageContext = '\n\n' + gt(
                        'page_read_failed',
                        'Note: Page {page} could not be read from document "{name}".',
                        { page: requestedPage, name: document.name }
                    );
                }

            } else {
                documentPageContext = '\n\n' + gt(
                    'page_read_failed',
                    'Note: Page {page} could not be read from document "{name}".',
                    { page: requestedPage, name: document.name }
                );
            }
        } else {
            const document = documentFiles[0];

            if (
                document.document_id &&
                prompt.trim()
            ) {
                try {
                    const ragResponse = await fetch(
                        '/api/mlx/documents/search',
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({
                                document_id: document.document_id,
                                query: prompt,
                                limit: 6
                            })
                        }
                    );

                    if (!ragResponse.ok) {
                        throw new Error(
                            await ragResponse.text()
                        );
                    }

                    const ragData = await ragResponse.json();
                    const results = Array.isArray(ragData.results)
                        ? ragData.results
                        : [];

                    if (results.length) {
                        documentRagContext =
                            '\n\n--- RELEVANTE FUNDSTELLEN AUS DOKUMENT: ' +
                            document.name +
                            ' ---\n' +
                            results.map((result, index) =>
                                '[Fundstelle ' +
                                (index + 1) +
                                ' · Seite ' +
                                result.page +
                                ']\n' +
                                result.content
                            ).join('\n\n') +
                            '\n--- ENDE DOKUMENT-FUNDSTELLEN ---';

                        console.log(
                            '[MLX PDF RAG]',
                            document.name,
                            results.map(result => ({
                                page: result.page,
                                score: result.score
                            }))
                        );
                    }
                } catch (error) {
                    console.error(
                        '[MLX PDF RAG] Search failed',
                        error
                    );
                }
            }
        }
    }

    const attachmentTextContext =
        MLXChatAttachments.buildAttachmentContext();

    const attachmentContext =
        attachmentTextContext +
        documentPageContext +
        documentRagContext;

    const effectivePrompt =
        prompt ||
        (
            imageFiles.length
                ? defaultVisionPrompt(imageFiles.length)
                : ''
        );

    const messageContent =
        attachmentContext
            ? (
                effectivePrompt +
                '\n\n' +
                attachmentContext
            )
            : effectivePrompt;

    let visionImages = [];

    if (
        !imageFiles.length &&
        activeImageArtifact &&
        refersToExistingImage &&
        !explicitImageEditRequest &&
        !explicitVideoAnimateRequest
    ) {
        try {
            const visionArtifacts =
                imageComparisonRequest && imageState.parent
                    ? [
                        imageState.parent,
                        activeImageArtifact
                    ]
                    : [activeImageArtifact];

            for (const artifact of visionArtifacts) {
                const dataUrl =
                    await imageArtifactDataUrl(
                        artifact
                    );

                visionImages.push({
                    kind: 'image',
                    name:
                        artifact.name ||
                        'generated-image.png',
                    type:
                        artifact.mime_type ||
                        'image/png',
                    image_id:
                        artifact.image_id,
                    artifact_id:
                        artifact.artifact_id,
                    data_url: dataUrl
                });
            }

            console.log(
                imageComparisonRequest
                    ? '[MLX Vision] Image comparison artifacts:'
                    : '[MLX Vision] Active image artifact:',
                visionArtifacts.map(
                    artifact => artifact.artifact_id
                )
            );
        } catch (error) {
            console.error(
                '[MLX Vision] Image could not be loaded',
                error
            );

            alert(
                gt(
                'generated_image_load_failed',
                'The most recently generated image could not be loaded for analysis.'
            )
            );

            return;
        }
    }

    const userMessage = {
        role: 'user',
        trace_id: newTraceId(),
        content: messageContent,
        display_content: effectivePrompt,
        vision_images: visionImages,
        attachments:
            currentAttachments.map(
                file => ({
                    name: file.name,
                    size: file.size,
                    type: file.type,
                    extension: file.extension,
                    kind: file.kind || 'text',
                    document_type: file.document_type,
                    document_id: file.document_id,
                    pages: file.pages,
                    characters: file.characters,
                    context_omitted: !!file.context_omitted,
                    data_url:
                        file.kind === 'image'
                            ? file.data_url
                            : undefined
                })
            ),
        _context_sources: {
            attachments: {
                characters: attachmentTextContext.length,
                items: currentAttachments.length + visionImages.length
            },
            document_web: {
                characters:
                    documentPageContext.length +
                    documentRagContext.length,
                items: documentFiles.length
            }
        }
    };
    session.messages.push(userMessage);

    MLXChatAttachments.clearAttachments();

    MLXChatSessions.updateTitle(session);

    await MLXChatCompact.autoCompactIfNeeded(
        session
    );

    session.updated =
        Date.now();

    MLXChatSessions.saveSessions();

    input.value = '';
    MLXChatRuntime.autoResize();

    MLXChatRuntime.beginUserMessage();
    MLXChatRendering.renderAll({
        contentUpdated: true
    });

    if (ambiguousArtifactReference) {
        session.messages.push({
            role: 'assistant',
            content: 'Welches Ergebnis meinst du?',
            artifact_choice: { prompt: prompt, candidates: artifactCandidates.slice(0, 5) }
        });
        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll({
            contentUpdated: true
        });
        return;
    }

    const explicitImageCreationRequest =
        isImageGenerationRequest(prompt);

    const routesCurrentImageToVision =
        (
            imageFiles.length > 1 ||
            visionImages.length > 1
        ) &&
        !explicitImageCreationRequest &&
        !explicitImageEditRequest &&
        !explicitVideoAnimateRequest;

    if (
        !routesFileOperation &&
        !textFiles.length &&
        !routesCurrentImageToVision
    ) {
        const imageRequest =
            explicitImageCreationRequest ||
            explicitImageEditRequest;
        let pendingImageMessage = null;
        if (imageRequest) {
            pendingImageMessage = { role: 'assistant', content: gt('image_generating', 'Generating the image locally with the selected image model …'), image_generation_pending: true };
            session.messages.push(pendingImageMessage);
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({
                contentUpdated: true
            });
        }
        try {
            let currentImageContext = null;

            const selectedCurrentImage =
                preferredVideoSource?.origin === 'current_upload'
                    ? preferredVideoSource.source
                    : imageFiles.length === 1
                        ? imageFiles[0]
                        : null;

            if (selectedCurrentImage) {
                const image = selectedCurrentImage;

                let storedPath =
                    image.stored_path ||
                    image.path ||
                    null;

                let storedName =
                    image.file_id ||
                    null;

                if (!storedPath && image.file) {
                    const uploaded =
                        await MLXChatAttachments
                            .uploadImageAttachments([
                                image
                            ]);

                    const item = uploaded[0];

                    if (!item?.upload?.path) {
                        throw new Error(
                            gt(
                                'generation.image_upload_failed',
                                'Image could not be uploaded.'
                            )
                        );
                    }

                    storedPath =
                        item.upload.path;

                    storedName =
                        item.upload.stored_name ||
                        storedName;

                    image.stored_path =
                        storedPath;

                    image.file_id =
                        storedName;
                }

                const storedAttachment = [...(userMessage.attachments || [])]
                    .reverse()
                    .find(item => item.kind === 'image' && item.name === image.name);
                if (storedAttachment && storedPath) {
                    storedAttachment.stored_path = storedPath;
                    storedAttachment.file_id = storedName;
                }

                currentImageContext = {
                    ...image,
                    kind: 'image',
                    mime_type:
                        image.mime_type ||
                        image.type ||
                        'image/jpeg',
                    stored_path:
                        storedPath,
                    file_id:
                        storedName
                };
            }

            const historicalVideoUpload =
                preferredVideoSource?.origin === 'chat_upload'
                    ? preferredVideoSource.source
                    : null;
            const fileContext = currentImageContext || historicalVideoUpload ||
                (explicitVideoAnimateRequest
                    ? null
                    : documentFiles[0] || priorFileAttachments[0] || null);

            // Always expose the active image artifact to the semantic
            // router. This lets the router resolve natural image follow-ups
            // from conversation context even when the deterministic edit
            // patterns do not recognize the wording.
            const activeArtifactIdForEdit =
                !currentImageContext && !historicalVideoUpload &&
                (refersToExistingImage || explicitImageEditRequest || explicitVideoAnimateRequest)
                    ? (
                        (preferredVideoSource?.origin === 'active_artifact'
                            ? preferredVideoSource.source?.artifact_id
                            : activeImageArtifact?.artifact_id) ||
                        session?.workspace?.active_artifact_id ||
                        null
                    )
                    : null;

            if (
                pendingImageMessage &&
                explicitImageEditRequest &&
                activeArtifactIdForEdit
            ) {
                pendingImageMessage.image_parent_artifact_id =
                    activeArtifactIdForEdit;
            }

            if (
                explicitImageEditRequest &&
                !fileContext?.stored_path &&
                !activeArtifactIdForEdit
            ) {
                throw new Error(
                    gt(
                        'generation.image_edit_source_required',
                        'Please attach the image you want to edit.'
                    )
                );
            }

            /*
             * Ask for media quality only when this turn is actually
             * creating/editing image or video content. Normal chat
             * never sees this modal.
             */
            const explicitVideoCreationRequest =
                /\b(?:erstelle|erzeuge|generiere|mach|create|generate|make)\b[\s\S]{0,100}\b(?:video|clip|animation)\b/i.test(prompt) ||
                /\b(?:video|clip|animation)\b[\s\S]{0,100}\b(?:erstellen|erzeugen|generieren|create|generate)\b/i.test(prompt);

            const mediaQualityKind =
                (
                    explicitVideoAnimateRequest ||
                    explicitVideoCreationRequest ||
                    Boolean(options?.video)
                )
                    ? 'video'
                    : (
                        explicitImageCreationRequest ||
                        explicitImageEditRequest ||
                        Boolean(options?.image)
                    )
                        ? 'image'
                        : null;

            let selectedMediaQuality =
                MLXChatRuntime.getSessionMediaQuality?.() ||
                'standard';
            let selectedVideoDuration = VIDEO_DURATIONS.has(
                Number(options?.video?.duration)
            )
                ? Number(options.video.duration)
                : 5;

            if (mediaQualityKind) {
                const modal =
                    document.getElementById('mediaQualityModal');
                const title =
                    document.getElementById('mediaQualityModalTitle');
                const message =
                    document.getElementById('mediaQualityModalMessage');
                const cancel =
                    document.getElementById('mediaQualityModalCancel');
                const confirm =
                    document.getElementById('mediaQualityModalConfirm');
                const durationField =
                    document.getElementById('videoDurationField');
                const durationSelect =
                    document.getElementById('videoDuration');
                const qualityButtons =
                    typeof document.querySelectorAll === 'function'
                        ? [
                            ...document.querySelectorAll(
                                '[data-media-quality]'
                            )
                        ]
                        : [];

                if (
                    modal &&
                    title &&
                    message &&
                    cancel &&
                    confirm &&
                    qualityButtons.length
                ) {
                    // Default is Standard; subsequent jobs reuse this session's choice.
                    let choice = selectedMediaQuality;

                    const renderChoice = () => {
                        for (const button of qualityButtons) {
                            const active =
                                button.dataset.mediaQuality === choice;

                            button.classList.toggle(
                                'is-selected',
                                active
                            );

                            button.setAttribute(
                                'aria-pressed',
                                active ? 'true' : 'false'
                            );
                        }
                    };

                    title.textContent =
                        mediaQualityKind === 'video'
                            ? 'Videoqualität wählen'
                            : 'Bildqualität wählen';

                    message.textContent =
                        mediaQualityKind === 'video'
                            ? 'Welche Qualität möchtest du für das Video verwenden?'
                            : 'Welche Qualität möchtest du für das Bild verwenden?';

                    if (durationField && durationSelect) {
                        durationField.hidden = mediaQualityKind !== 'video';
                        durationSelect.value = String(selectedVideoDuration);
                    }

                    renderChoice();

                    const result = await new Promise(resolve => {
                        let settled = false;

                        const finish = value => {
                            if (settled) return;
                            settled = true;

                            modal.hidden = true;
                            modal.setAttribute(
                                'aria-hidden',
                                'true'
                            );

                            for (const button of qualityButtons) {
                                button.removeEventListener(
                                    'click',
                                    onQuality
                                );
                            }

                            cancel.removeEventListener(
                                'click',
                                onCancel
                            );

                            confirm.removeEventListener(
                                'click',
                                onConfirm
                            );

                            modal
                                .querySelector(
                                    '[data-media-quality-dismiss]'
                                )
                                ?.removeEventListener(
                                    'click',
                                    onCancel
                                );

                            document.removeEventListener(
                                'keydown',
                                onKeydown
                            );

                            resolve(value);
                        };

                        const onQuality = event => {
                            choice =
                                event.currentTarget
                                    .dataset.mediaQuality ||
                                'standard';

                            renderChoice();
                        };

                        const onCancel = () => {
                            finish(null);
                        };

                        const onConfirm = () => {
                            if (mediaQualityKind === 'video' && durationSelect) {
                                const duration = Number(durationSelect.value);
                                selectedVideoDuration = VIDEO_DURATIONS.has(duration)
                                    ? duration
                                    : 5;
                            }
                            finish(choice);
                        };

                        const onKeydown = event => {
                            if (event.key === 'Escape') {
                                event.preventDefault();
                                onCancel();
                            }

                            if (
                                event.key === 'Enter' &&
                                !event.shiftKey
                            ) {
                                event.preventDefault();
                                onConfirm();
                            }
                        };

                        for (const button of qualityButtons) {
                            button.addEventListener(
                                'click',
                                onQuality
                            );
                        }

                        cancel.addEventListener(
                            'click',
                            onCancel
                        );

                        confirm.addEventListener(
                            'click',
                            onConfirm
                        );

                        modal
                            .querySelector(
                                '[data-media-quality-dismiss]'
                            )
                            ?.addEventListener(
                                'click',
                                onCancel
                            );

                        document.addEventListener(
                            'keydown',
                            onKeydown
                        );

                        modal.hidden = false;
                        modal.setAttribute(
                            'aria-hidden',
                            'false'
                        );

                        requestAnimationFrame(() => {
                            const standard =
                                modal.querySelector(
                                    '[data-media-quality="standard"]'
                                );

                            standard?.focus();
                        });
                    });

                    /*
                     * Cancel means exactly that: do not create a media
                     * job and do not send the action request.
                     */
                    if (!result) {
                        return;
                    }

                    selectedMediaQuality = result;

                    /*
                     * Keep the old session setting in sync for existing
                     * backend/UI code without showing the composer control.
                     */
                    const legacySelect =
                        document.getElementById('mediaQuality');

                    if (legacySelect) {
                        legacySelect.value =
                            selectedMediaQuality;

                        MLXChatRuntime
                            .handleMediaQualityChange?.();
                    }
                }
            }

            const conversationContext =
                buildAgentConversationContext(
                    session,
                    userMessage
                );
            const actionPayload = {
                prompt: prompt,
                file_context: fileContext,
                active_artifact_id: activeArtifactIdForEdit,
                image_options: options?.image || null,
                video_options: videoOptionsForRequest(
                    options,
                    mediaQualityKind,
                    selectedVideoDuration
                ),
                quality: selectedMediaQuality,
                conversation_context: conversationContext,
                trace_id: userMessage.trace_id,
                chat_id: session.id,
                chat_revision: persistentChatRevision(session)

            };

            const actionResponse = await fetch('/api/mlx/chat/actions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(actionPayload)
            });
            if (!actionResponse.ok) throw new Error(await actionResponse.text());
            const toolResult = await actionResponse.json();

            // The request may have finished after "Chat leeren".
            // Never let an old turn repopulate the fresh conversation.
            if (
                MLXChatSessions.currentSession() !== session ||
                !session.messages.includes(userMessage)
            ) {
                const staleJob = toolResult?.data?.job;

                if (
                    staleJob?.id &&
                    IMAGE_JOB_ID_PATTERN.test(String(staleJob.id)) &&
                    (ACTIVE_IMAGE_JOB_STATUSES.has(staleJob.status) || ACTIVE_VIDEO_JOB_STATUSES.has(staleJob.status))
                ) {
                    fetch(
                        (['video_generate', 'video_animate'].includes(toolResult.tool)
                            ? '/api/mlx/video-jobs/'
                            : '/api/mlx/image-jobs/') +
                            encodeURIComponent(staleJob.id) +
                            '/cancel',
                        { method: 'POST' }
                    ).catch(() => {});
                }

                return;
            }

            if (
                ['video_generate', 'video_animate'].includes(toolResult.tool) &&
                toolResult.data?.job?.id
            ) {
                const pendingVideoMessage = {
                    role: 'assistant', content: '',
                    video_job: toolResult.data.job,
                    tool_result: toolResult
                };
                session.messages.push(pendingVideoMessage);
                MLXChatSessions.saveSessions();
                MLXChatRendering.renderAll({ contentUpdated: true });
                if (ACTIVE_VIDEO_JOB_STATUSES.has(toolResult.status)) {
                    watchVideoJob(session, pendingVideoMessage);
                }
                return;
            }

            // The semantic router may recognize an image operation even when
            // the frontend fast-path did not. Create the pending image
            // message after routing in that case so queued/running jobs are
            // handled exactly like deterministic image requests.
            if (
                !pendingImageMessage &&
                isImageJobTool(toolResult.tool)
            ) {
                pendingImageMessage = {
                    role: 'assistant',
                    content: gt(
                        'image_generating',
                        'Generating the image locally with the selected image model …'
                    ),
                    image_generation_pending: true
                };

                if (
                    toolResult.tool === 'image_edit' &&
                    activeArtifactIdForEdit
                ) {
                    pendingImageMessage.image_parent_artifact_id =
                        activeArtifactIdForEdit;
                }

                session.messages.push(pendingImageMessage);
                MLXChatSessions.saveSessions();
                MLXChatRendering.renderAll({
                    contentUpdated: true
                });
            }

            if (
                isImageJobTool(toolResult.tool) &&
                pendingImageMessage &&
                toolResult.data?.job?.id
            ) {
                updateImageJobMessage(
                    session,
                    pendingImageMessage,
                    toolResult
                );

                MLXChatSessions.saveSessions();
                MLXChatRendering.renderAll({
                    contentUpdated: true
                });

                if (
                    [
                        'queued',
                        'loading',
                        'running',
                        'saving'
                    ].includes(toolResult.status)
                ) {
                    watchImageJob(
                        session,
                        pendingImageMessage
                    );
                }

                return;
            }

            // ------------------------------------------------
            // Auto-Agent
            // ------------------------------------------------
            // The regular chat router can automatically escalate a complex
            // task to the existing agent loop.

            if (
                [
                    'research_agent',
                    'diagnostic_agent',
                    'coding_agent',
                    'orchestrator'
                ].includes(toolResult.tool) &&
                toolResult.status === 'completed'
            ) {
                const assistantMessage = {
                    role: 'assistant',
                    content:
                        toolResult.tool === 'research_agent'
                            ? gt('research_running', 'Research in progress …')
                            : toolResult.tool === 'coding_agent'
                                ? gt('coding_running', 'Analyzing code …')
                                : toolResult.tool === 'orchestrator'
                                    ? gt('orchestration_running', 'Orchestration in progress …')
                                    : gt('system_running', 'Analyzing system …'),
                    agent_run: {
                        status: 'running',
                        goal: prompt,
                        steps: [],
                        pending_action: null
                    }
                };

                userMessage.agent_mode = true;

                session.messages.push(
                    assistantMessage
                );

                MLXChatSessions.saveSessions();
                MLXChatRendering.renderAll({
                    contentUpdated: true
                });

                await runAgent(
                    session,
                    prompt,
                    assistantMessage,
                    toolResult.data?.mode ||
                    toolResult.result?.mode ||
                    toolResult.mode ||
                    'diagnostic',
                    conversationContext,
                    userMessage.trace_id,
                    {
                        attachments: [
                            ...(currentImageContext
                                ? [{ kind: 'image', stored_path: currentImageContext.stored_path }]
                                : []),
                            ...documentFiles.map(file => ({
                                kind: 'document',
                                document_id: file.document_id
                            }))
                        ],
                        activeArtifactId: activeArtifactIdForEdit,
                        workspaceId: toolResult.data?.workspace_id || null
                    }
                );

                return;
            }

            if (
                toolResult.tool === 'web_search' &&
                toolResult.status === 'completed'
            ) {
                const results =
                    toolResult.data?.results || [];

                if (!results.length) {
                    session.messages.push({
                        role: 'assistant',
                        content: gt(
                            'web_search_no_results',
                            'The web search returned no matching results.'
                        ),
                        tool_result: toolResult
                    });

                    MLXChatSessions.saveSessions();
                    MLXChatRendering.renderAll({
                        contentUpdated: true
                    });
                    return;
                }

                const searchContext =
                    results
                        .map((item, index) => {
                            const published =
                                item.published_date
                                    ? '\nDatum: ' +
                                      item.published_date
                                    : '';

                            const fetchedText =
                                item.fetch?.ok &&
                                item.fetch?.text
                                    ? item.fetch.text
                                    : '';

                            const sourceText =
                                fetchedText
                                    ? (
                                        '\nSeiteninhalt:\n' +
                                        fetchedText.slice(0, 12000)
                                    )
                                    : (
                                        '\nSnippet: ' +
                                        (item.snippet || '')
                                    );

                            return (
                                '[' + (index + 1) + '] ' +
                                item.title +
                                '\nURL: ' +
                                item.url +
                                published +
                                sourceText
                            );
                        })
                        .join('\n\n');

                userMessage.web_search = {
                    provider:
                        toolResult.data?.provider ||
                        'SearXNG',
                    query:
                        toolResult.data?.query ||
                        prompt,
                    results: results
                };

                userMessage.content =
                    messageContent +
                    '\n\n' +
                    '--- LIVE-WEBSUCHE ---\n' +
                    gt(
                        'web_search_current_date',
                        'Current date:'
                    ) +
                    ' ' +
                    (toolResult.data?.current_date ||
                        new Date().toLocaleDateString('sv-SE')) +
                    '. ' +
                    gt(
                        'web_search_relative_date_instruction',
                        'Interpret relative date expressions such as "today" exclusively using this date.'
                    ) +
                    ' ' +
                    'The following information comes from a current web search. ' +
                    'For some results, the actual webpage content was loaded as well. ' +
                    'Prefer the loaded webpage content over the search snippet. ' +
                    'Ignore navigation, cookie notices, menus, footers, and other irrelevant page content. ' +
                    'Do not claim that something is current unless it is supported by these sources. ' +
                    'At the end, list the sources actually used as clickable URLs. ' +
                    'If the sources are insufficient or contradictory, state that explicitly.\n\n' +
                    searchContext;
                userMessage._context_sources.document_web.characters +=
                    userMessage.content.length - messageContent.length;
                userMessage._context_sources.document_web.items +=
                    results.length;

                console.log(
                    '[MLX Web] SearXNG:',
                    results.length,
                    'results for',
                    toolResult.data?.query
                );

                MLXChatSessions.saveSessions();

                await generateAssistant(
                    session
                );

                return;
            }

            if (
                toolResult.tool === 'knowledge_search' &&
                toolResult.status === 'completed'
            ) {
                if (pendingImageMessage) {
                    const pendingIndex =
                        session.messages.indexOf(pendingImageMessage);

                    if (pendingIndex >= 0) {
                        session.messages.splice(pendingIndex, 1);
                    }
                }

                await generateAssistant(
                    session
                );

                return;
            }

            if (toolResult.tool !== 'normal_chat') {
                if (pendingImageMessage) {
                    const pendingIndex = session.messages.indexOf(pendingImageMessage);
                    if (pendingIndex >= 0) session.messages.splice(pendingIndex, 1);
                }
                session.messages.push({
                    role: 'assistant',
                    content:
                        toolResult.status === 'completed'
                            ? toolSummary(toolResult)
                            : toolFailureSummary(toolResult),
                    tool_result: toolResult
                });
                MLXChatSessions.saveSessions();
                MLXChatRendering.renderAll({
                    contentUpdated: true
                });
                return;
            }
        } catch (error) {
            if (pendingImageMessage) {
                const pendingIndex = session.messages.indexOf(pendingImageMessage);
                if (pendingIndex >= 0) session.messages.splice(pendingIndex, 1);
            }
            session.messages.push({ role: 'assistant', content: gt('tool_error', '**Tool error:** {message}', { message: error.message }) });
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({
                contentUpdated: true
            });
            return;
        }
    }

    if (routesFileOperation) {
        try {
            const uploaded = textFiles.length
                ? await MLXChatAttachments.uploadTextAttachments(textFiles)
                : priorFileAttachments.slice(0, 1).map(attachment => ({ attachment, upload: { path: attachment.stored_path } }));
            for (const item of uploaded) {
                const storedAttachment = userMessage.attachments.find(file => file.name === item.attachment.name);
                if (storedAttachment) {
                    storedAttachment.stored_path = item.upload.path;
                    storedAttachment.file_id = item.upload.stored_name;
                }
                const response = await fetch('/api/mlx/chat/files/route', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        input_path: item.upload.path,
                        instruction: prompt,
                        file_type: ['json', 'csv', 'sql'].includes(item.attachment.extension)
                            ? item.attachment.extension : 'text',
                        chunk_tokens: 12000,
                        attachment_id: item.upload.stored_name || item.attachment.file_id || null,
                        trace_id: userMessage.trace_id,
                        chat_id: session.id
                    })
                });
                if (!response.ok) throw new Error(await response.text());
                const routed = await response.json();

                if (routed.job && routed.requires_start_choice) {
                    routed.job.requires_start_choice = true;
                }

                session.messages.push({
                    role: 'assistant',
                    content: routed.intent === 'transform' ? gt('file_processing', 'Processing file …') : gt('file_analyzing', 'Analyzing file …'),
                    batch_job: routed.job,
                    batch_filename: item.attachment.name,
                    chain_next: routed.intent === 'transform' && /\b(?:und danach|anschließend|anschliessend).*(?:fass|zusammenfass)|(?:fass|zusammenfass).*\b(?:danach|anschließend|anschliessend)/i.test(prompt)
                        ? 'summarize' : null
                });
            }
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({
                contentUpdated: true
            });

            for (const message of session.messages) {
                const job = message.batch_job;

                if (
                    job?.id &&
                    (
                        job.status === 'queued' ||
                        job.status === 'running' ||
                        job.status === 'paused'
                    )
                ) {
                    watchBatchJob(session, job.id);
                }
            }

            return;
        } catch (error) {
            session.messages.push({ role: 'assistant', content: gt('batch_error', '**Batch error:** {message}', { message: error.message }) });
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({
                contentUpdated: true
            });
            return;
        }
    }

    await generateAssistant(
        session
    );
}

function toolSummary(result) {
    const data = result.data || {};
    if (result.tool === 'model_list') {
        const items = data.models || [];
        return items.length
            ? gt(
                'installed_models',
                'Installed models: {models}',
                {
                    models: items
                        .map(item =>
                            item.alias +
                            (item.active ? ' (active)' : '')
                        )
                        .join(', ')
                }
            )
            : gt('no_models', 'No models found.');
    }
    if (result.tool === 'system_status') {
        const status = data.status || {};
        return 'MLX ist ' + (status.online ? 'online' : 'offline') + '. Model: ' + (status.model || 'keins') + '. RAM: ' + (status.memory_mb ?? '–') + ' MB.';
    }
    if (result.tool === 'batch_status') {
        const jobs = data.jobs || [];
        const active = jobs.filter(job => ['queued', 'running', 'paused'].includes(job.status));
        return active.length
            ? gt(
                'file_jobs_active',
                '{count} file job(s) active.',
                { count: active.length }
            )
            : gt(
                'no_file_jobs',
                'There are currently no active file jobs.'
            );
    }
    if (result.tool === 'logs_query') {
        return gt(
            'logs_checked',
            'The latest relevant logs were checked.'
        );
    }
    if (result.tool === 'pii_audit') {
        const total = Object.values(data).reduce((sum, value) => sum + Number(value || 0), 0);
        return total
            ? gt(
                'pii_hits',
                'PII audit: {count} obvious match(es). This is not a complete guarantee.',
                { count: total }
            )
            : gt(
                'pii_no_hits',
                'PII audit: no obvious matches. This is not a complete guarantee.'
            );
    }
    if (result.tool === 'model_switch') {
        return gt(
            'model_switch_started',
            'Model switch has been started.'
        );
    }
    if (result.tool === 'thinking_on' || result.tool === 'thinking_off') return gt(
        result.tool === 'thinking_on' ? 'thinking_enabled' : 'thinking_disabled',
        result.tool === 'thinking_on' ? 'Thinking enabled.' : 'Thinking disabled.'
    );
    if (result.tool === 'model_restart') {
        return gt(
            'server_restarting',
            'MLX server is restarting.'
        );
    }
    if (result.tool === 'image_generate') {
        return gt(
            'image_generated',
            'Image generated locally with {model}.',
            {
                model:
                    result.artifacts?.[0]?.model ||
                    gt(
                        'selected_image_model',
                        'the selected image model'
                    )
            }
        );
    }
    if (result.tool === 'image_upscale') {
        return gt(
            'image_upscaled',
            'Image enhanced locally with Real-ESRGAN.'
        );
    }
    if (result.tool === 'web_search') {
        return gt(
            'web_search_completed',
            'Live web search via SearXNG completed.'
        );
    }
    if (result.tool === 'knowledge_search') {
        const results = data.results || [];
        if (!results.length) return gt(
            'knowledge_no_source',
            'No matching source found in the knowledge base ({mode}).',
            { mode: data.mode || 'fts_fallback' }
        );
        return '**' + gt('knowledge_base', 'Knowledge base') + ' · ' + (data.mode === 'hybrid' ? 'Hybrid' : 'FTS fallback') + '**\n\n' + results.map(item =>
            '- `' + item.path + ':' + item.start_line + '-' + item.end_line + '`' + (item.symbol ? ' — ' + item.symbol : '') + '\n  ' + item.snippet.replace(/\n/g, ' ').slice(0, 260)
        ).join('\n');
    }
    return gt('action_completed', 'Action completed.');
}

function toolFailureSummary(result) {
    if (
        ['image_edit', 'image_upscale', 'video_generate', 'video_animate'].includes(result?.tool) &&
        result.error
    ) {
        return gt(
            'tool_error',
            '**Tool error:** {message}',
            { message: result.error }
        );
    }

    return gt(
        'action_failed',
        'The action could not be completed.'
    );
}

const ACTIVE_IMAGE_JOB_STATUSES = new Set([
    'queued',
    'loading',
    'running',
    'saving'
]);
const IMAGE_JOB_ID_PATTERN = /^[a-f0-9]{24}$/;

// Transient image-service failures are expected during a local service
// restart. Keep retrying with bounded backoff long enough for the service
// to return, but never poll forever.
const IMAGE_JOB_RETRY_DELAYS_MS = [
    1000,
    2000,
    4000,
    8000,
    10000,
    10000,
    10000,
    10000
];

const IMAGE_JOB_TOOLS = new Set([
    'image_generate',
    'image_edit',
    'image_upscale'
]);
const imageJobWatchers = new Map();
const ACTIVE_VIDEO_JOB_STATUSES = new Set([
    'queued', 'loading', 'encoding', 'generating', 'upscaling', 'decoding', 'muxing'
]);
const videoJobWatchers = new Map();

function isImageJobTool(tool) {
    return IMAGE_JOB_TOOLS.has(tool);
}

function imageJobHasStep(job) {
    const currentStep = Number(job?.current_step);
    const totalSteps = Number(job?.total_steps);

    return job?.current_step != null &&
        job?.total_steps != null &&
        Number.isInteger(currentStep) &&
        Number.isInteger(totalSteps) &&
        currentStep > 0 &&
        totalSteps > 0 &&
        currentStep <= totalSteps;
}

function isWatchingImageJob(message) {
    const jobId = message?.image_job?.id;
    return Boolean(jobId && imageJobWatchers.has(jobId));
}

function updateImageJobMessage(
    session,
    message,
    toolResult,
    nowSeconds = Date.now() / 1000
) {
    const job = toolResult?.data?.job;

    if (!job?.id) {
        return true;
    }

    const previousJob = message.image_job;
    const nextJob = { ...job };

    if (imageJobHasStep(nextJob)) {
        const sameStep =
            imageJobHasStep(previousJob) &&
            Number(previousJob.current_step) ===
                Number(nextJob.current_step) &&
            Number(previousJob.total_steps) ===
                Number(nextJob.total_steps);
        const previousProgressUpdate = Number(
            previousJob?.progress_updated_at
        );
        const reportedProgressUpdate = Number(
            nextJob.progress_updated_at
        );

        nextJob.progress_updated_at =
            sameStep &&
                Number.isFinite(previousProgressUpdate) &&
                previousProgressUpdate > 0
                ? previousProgressUpdate
                : Number.isFinite(reportedProgressUpdate) &&
                    reportedProgressUpdate > 0
                    ? reportedProgressUpdate
                    : nowSeconds;
    }

    message.image_job = nextJob;

    if (
        toolResult.status === 'completed' &&
        message.image_parent_artifact_id &&
        toolResult.artifacts?.[0] &&
        !toolResult.artifacts[0].parent_artifact_id
    ) {
        toolResult.artifacts[0].parent_artifact_id =
            message.image_parent_artifact_id;

        if (toolResult.data?.image) {
            toolResult.data.image.parent_artifact_id =
                message.image_parent_artifact_id;
        }
    }

    message.tool_result = toolResult;
    message.image_generation_pending = false;

    if (toolResult.status === 'completed') {
        const artifact = toolResult.artifacts?.[0];
        if (artifact?.artifact_id) {
            session.workspace = {
                ...(session.workspace || {}),
                active_artifact_id: artifact.artifact_id
            };
        }
        message.content = [
            'image_generate',
            'image_edit'
        ].includes(toolResult.tool)
            ? ''
            : toolSummary(toolResult);
    } else if (toolResult.status === 'cancelled') {
        message.content = gt(
            'image_job_cancelled',
            'Image job cancelled.'
        );
    } else if (toolResult.status === 'failed') {
        message.content = toolResult.error
            ? gt(
                'tool_error',
                '**Tool error:** {message}',
                { message: toolResult.error }
            )
            : toolFailureSummary(toolResult);
    } else {
        message.content = '';
    }

    return !ACTIVE_IMAGE_JOB_STATUSES.has(toolResult.status);
}

function imageJobWatcherIsCurrent(watcher) {
    return !watcher.stopped &&
        imageJobWatchers.get(watcher.jobId) === watcher &&
        MLXChatSessions.currentSession() === watcher.session &&
        watcher.session.messages.includes(watcher.message);
}

function stopImageJobWatcher(watcher) {
    if (!watcher || watcher.stopped) {
        return;
    }

    watcher.stopped = true;
    if (watcher.timerId != null && typeof clearTimeout === 'function') {
        clearTimeout(watcher.timerId);
        watcher.timerId = null;
    }
    if (imageJobWatchers.get(watcher.jobId) === watcher) {
        imageJobWatchers.delete(watcher.jobId);
    }
    window.MLXChatRendering?.syncImageJobUiTimer?.();
}

function scheduleImageJobPoll(
    watcher,
    poll,
    delayMs = 1000
) {
    watcher.timerId = setTimeout(() => {
        watcher.timerId = null;
        poll();
    }, delayMs);
}

function unavailableImageJobResult(message) {
    const error = gt(
        'image_job_unavailable',
        'The running image job is no longer available. ' +
            'The image service may have restarted.'
    );

    return {
        type: 'tool_result',
        tool: message.tool_result.tool,
        status: 'failed',
        data: {
            job: {
                ...message.image_job,
                status: 'failed',
                result: null,
                error,
                recovery_status: 'not_found',
                finished_at: Date.now() / 1000
            }
        },
        artifacts: [],
        error
    };
}

function unreachableImageJobResult(message) {
    const error = gt(
        'image_job_service_unavailable',
        'The image service could not be reached after several retries. ' +
            'The image job was interrupted.'
    );

    return {
        type: 'tool_result',
        tool: message.tool_result.tool,
        status: 'failed',
        data: {
            job: {
                ...message.image_job,
                status: 'failed',
                result: null,
                error,
                recovery_status: 'service_unavailable',
                finished_at: Date.now() / 1000
            }
        },
        artifacts: [],
        error
    };
}


function watchImageJob(session, message) {
    let failures = 0;
    const initialJobId = message.image_job?.id;

    if (
        !IMAGE_JOB_ID_PATTERN.test(String(initialJobId || '')) ||
        imageJobWatchers.has(initialJobId) ||
        MLXChatSessions.currentSession() !== session
    ) {
        return false;
    }

    const watcher = {
        jobId: initialJobId,
        message,
        session,
        stopped: false,
        timerId: null
    };
    imageJobWatchers.set(initialJobId, watcher);

    window.MLXChatRendering?.syncImageJobUiTimer?.();

    const poll = async () => {
        if (!imageJobWatcherIsCurrent(watcher)) {
            stopImageJobWatcher(watcher);
            return;
        }

        try {
            const response = await fetch(
                '/api/mlx/image-jobs/' +
                encodeURIComponent(watcher.jobId)
            );
            if (!imageJobWatcherIsCurrent(watcher)) {
                stopImageJobWatcher(watcher);
                return;
            }
            if (!response.ok) {
                if (response.status === 404) {
                    const toolResult = unavailableImageJobResult(message);
                    updateImageJobMessage(session, message, toolResult);
                    MLXChatSessions.saveSessions();
                    MLXChatRendering.renderMessages({
                        contentUpdated: true
                    });
                    stopImageJobWatcher(watcher);
                    return;
                }
                throw new Error(await response.text());
            }
            const toolResult = await response.json();
            if (!imageJobWatcherIsCurrent(watcher)) {
                stopImageJobWatcher(watcher);
                return;
            }
            const terminal = updateImageJobMessage(
                session,
                message,
                toolResult
            );
            failures = 0;
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderMessages({
                contentUpdated: true
            });
            if (!terminal) {
                scheduleImageJobPoll(watcher, poll);
            } else {
                stopImageJobWatcher(watcher);
            }
        } catch (error) {
            if (!imageJobWatcherIsCurrent(watcher)) {
                stopImageJobWatcher(watcher);
                return;
            }
            failures += 1;
            console.warn('Could not load image job status', error);

            const retryDelay =
                IMAGE_JOB_RETRY_DELAYS_MS[failures - 1];

            if (retryDelay != null) {
                scheduleImageJobPoll(
                    watcher,
                    poll,
                    retryDelay
                );
            } else {
                const toolResult =
                    unreachableImageJobResult(message);

                updateImageJobMessage(
                    session,
                    message,
                    toolResult
                );

                MLXChatSessions.saveSessions();
                MLXChatRendering.renderMessages({
                    contentUpdated: true
                });

                stopImageJobWatcher(watcher);
            }
        }
    };

    poll();
    return true;
}

async function resetSessionRuntime(session) {
    if (!session) {
        return;
    }

    // Abort an active text/chat request.
    try {
        getAbortController?.()?.abort();
    } catch (_error) {}

    setAbortController?.(null);
    setGenerating?.(false);

    // Find every active image job belonging to this session before
    // deleteMessages() removes the messages containing the job IDs.
    const jobIds = new Set();
    const videoJobIds = new Set();

    for (const message of session.messages || []) {
        const job = message?.image_job;

        if (
            ACTIVE_IMAGE_JOB_STATUSES.has(job?.status) &&
            IMAGE_JOB_ID_PATTERN.test(String(job?.id || ''))
        ) {
            jobIds.add(job.id);
        }
        const videoJob = message?.video_job;
        if (ACTIVE_VIDEO_JOB_STATUSES.has(videoJob?.status) && IMAGE_JOB_ID_PATTERN.test(String(videoJob?.id || ''))) {
            videoJobIds.add(videoJob.id);
        }
    }

    // Stop browser-side polling immediately.
    for (const watcher of [...imageJobWatchers.values()]) {
        if (watcher.session === session) {
            stopImageJobWatcher(watcher);
        }
    }
    for (const watcher of [...videoJobWatchers.values()]) {
        if (watcher.session === session) stopVideoJobWatcher(watcher);
    }

    // Ask the image service to cancel the actual backend jobs.
    await Promise.allSettled(
        [...jobIds].map(jobId =>
            fetch(
                '/api/mlx/image-jobs/' +
                    encodeURIComponent(jobId) +
                    '/cancel',
                { method: 'POST' }
            )
        )
    );
    await Promise.allSettled(
        [...videoJobIds].map(jobId => fetch(
            '/api/mlx/video-jobs/' + encodeURIComponent(jobId) + '/cancel',
            { method: 'POST' }
        ))
    );

    window.MLXChatRendering?.syncImageJobUiTimer?.();
    MLXChatRuntime?.updateSendButton?.();
}


function resumeImageJobsForSession(session) {
    for (const watcher of imageJobWatchers.values()) {
        if (watcher.session !== session) {
            stopImageJobWatcher(watcher);
        }
    }

    if (!session || MLXChatSessions.currentSession() !== session) {
        return 0;
    }

    let started = 0;
    for (const message of session.messages) {
        const job = message?.image_job;
        if (
            !IMAGE_JOB_TOOLS.has(message?.tool_result?.tool) ||
            !ACTIVE_IMAGE_JOB_STATUSES.has(job?.status) ||
            !IMAGE_JOB_ID_PATTERN.test(String(job?.id || ''))
        ) {
            continue;
        }

        if (watchImageJob(session, message)) {
            started += 1;
        }
    }

    return started;
}

function updateVideoJobMessage(session, message, toolResult, nowSeconds = Date.now() / 1000) {
    const job = toolResult?.data?.job;
    if (!job?.id) return true;
    const previous = message.video_job;
    const next = { ...job };
    if (
        Number(previous?.progress) !== Number(next.progress) ||
        Number(previous?.current_step) !== Number(next.current_step) ||
        previous?.phase !== next.phase
    ) {
        next.progress_updated_at = nowSeconds;
    } else if (previous?.progress_updated_at) {
        next.progress_updated_at = previous.progress_updated_at;
    }
    message.video_job = next;
    message.tool_result = toolResult;
    if (toolResult.status === 'completed') {
        message.content = '';
    } else if (toolResult.status === 'cancelled') {
        message.content = gt('video_job_cancelled', 'Video job cancelled.');
    } else if (toolResult.status === 'failed') {
        message.content = toolResult.error
            ? gt('tool_error', '**Tool error:** {message}', { message: toolResult.error })
            : toolFailureSummary(toolResult);
    } else {
        message.content = '';
    }
    return !ACTIVE_VIDEO_JOB_STATUSES.has(toolResult.status);
}

function stopVideoJobWatcher(watcher) {
    if (!watcher || watcher.stopped) return;
    watcher.stopped = true;
    if (watcher.timerId != null) clearTimeout(watcher.timerId);
    if (videoJobWatchers.get(watcher.jobId) === watcher) {
        videoJobWatchers.delete(watcher.jobId);
    }
}

function watchVideoJob(session, message) {
    const jobId = String(message?.video_job?.id || '');
    if (!IMAGE_JOB_ID_PATTERN.test(jobId) || videoJobWatchers.has(jobId)) return false;
    const watcher = { jobId, session, message, stopped: false, timerId: null };
    videoJobWatchers.set(jobId, watcher);
    const poll = async () => {
        if (watcher.stopped || MLXChatSessions.currentSession() !== session || !session.messages.includes(message)) {
            stopVideoJobWatcher(watcher);
            return;
        }
        try {
            const response = await fetch('/api/mlx/video-jobs/' + encodeURIComponent(jobId));
            if (!response.ok) throw new Error(await response.text());
            const result = await response.json();
            const terminal = updateVideoJobMessage(session, message, result);
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderMessages({ contentUpdated: true });
            if (terminal) stopVideoJobWatcher(watcher);
            else watcher.timerId = setTimeout(poll, 1000);
        } catch (error) {
            console.warn('Could not load video job status', error);
            watcher.timerId = setTimeout(poll, 4000);
        }
    };
    poll();
    return true;
}

function resumeVideoJobsForSession(session) {
    for (const watcher of [...videoJobWatchers.values()]) {
        if (watcher.session !== session) stopVideoJobWatcher(watcher);
    }
    if (!session || MLXChatSessions.currentSession() !== session) return 0;
    let started = 0;
    for (const message of session.messages) {
        if (ACTIVE_VIDEO_JOB_STATUSES.has(message?.video_job?.status) && watchVideoJob(session, message)) started += 1;
    }
    return started;
}

function watchBatchJob(session, jobId) {
    const poll = async () => {
        try {
            const response = await fetch('/api/mlx/batch');
            if (!response.ok) throw new Error(await response.text());
            const data = await response.json();
            const job = (data.jobs || []).find(item => item.id === jobId);
            const message = session.messages.find(item => item.batch_job?.id === jobId);
            if (!job || !message) return;
            const requiresStartChoice =
                Boolean(
                    message.batch_job?.requires_start_choice
                );

            message.batch_job = job;

            if (requiresStartChoice) {
                message.batch_job.requires_start_choice = true;
            }
            if (job.status === 'completed' && job.kind === 'file_analysis' && job.result) {
                message.content = job.result;
                session.messages.forEach(chatMessage => (chatMessage.attachments || []).forEach(attachment => {
                    if (attachment.file_id && attachment.file_id === job.attachment_id) {
                        attachment.record_count = job.metadata?.record_count;
                        attachment.analysis_metadata = job.metadata;
                    }
                }));
            }
            if (job.status === 'completed' && job.output_path) {
                message.file_artifact = {
                    artifact_id: crypto.randomUUID(),
                    source_attachment_id: job.attachment_id || null,
                    source_job_id: job.id,
                    chat_id: job.chat_id || session.id,
                    run_id: job.run_id || null,
                    kind: 'text',
                    stored_path: job.output_path,
                    file_id: job.id + '-output',
                    name: job.output_path.split('/').pop(),
                    output_name: job.output_name || job.output_path.split('/').pop(),
                    original_name: message.batch_filename || null,
                    mime_type: job.output_mime_type || 'text/plain',
                    size: job.output_size ?? null,
                    extension: (job.output_path.split('.').pop() || 'txt').toLowerCase(),
                    last_job_id: job.id,
                    last_operation: 'file_transform',
                    operation: 'file_transform',
                    processing_mode: job.processing_mode || null,
                    audit_result: job.pii_audit || null,
                    parent_artifact_id: null,
                    created_at: Date.now()
                };
                if (message.chain_next === 'summarize' && !message.chain_started) {
                    message.chain_started = true;
                    const chainResponse = await fetch('/api/mlx/chat/files/route', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            input_path: job.output_path,
                            instruction: 'Summarize the generated file.',
                            file_type: message.file_artifact.extension === 'md' ? 'text' : message.file_artifact.extension,
                            attachment_id: message.file_artifact.file_id,
                            chat_id: session.id,
                            trace_id: job.trace_id
                        })
                    });
                    if (chainResponse.ok) {
                        const routed = await chainResponse.json();
                        session.messages.push({ role: 'assistant', content: gt('generated_file_summarizing', 'Summarizing generated file …'), batch_job: routed.job, batch_filename: message.file_artifact.name });
                        watchBatchJob(session, routed.job.id);
                    }
                }
            }
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderMessages({
                contentUpdated: true
            });
            if (job.status === 'queued' || job.status === 'running' || job.status === 'paused') {
                setTimeout(poll, 2000);
            }
        } catch (error) {
            console.warn('Could not load batch status', error);
        }
    };
    poll();
}


    window.MLXChatGeneration = {
        isAgentRunning: () => agentRunActive,
        configure: configure,
        regenerateLastAnswer: regenerateLastAnswer,
        generateAssistant: generateAssistant,
        sendMessage: sendMessage,
        startImageUpscale: startImageUpscale,
        createImageUpscaleMenu: createImageUpscaleMenu,
        approveAgentAction: approveAgentAction,
        updateImageJobMessage: updateImageJobMessage,
        updateVideoJobMessage: updateVideoJobMessage,
        isWatchingImageJob: isWatchingImageJob,
resetSessionRuntime: resetSessionRuntime,
        resumeImageJobsForSession: resumeImageJobsForSession,
        resumeVideoJobsForSession: resumeVideoJobsForSession,
        __test: {
            buildApiMessages: buildApiMessages,
            buildContextSources: buildContextSources,
            readSseEvents: readSseEvents,
            stripTrailingSvgStreamArtifact: stripTrailingSvgStreamArtifact,
            defaultVisionPrompt: defaultVisionPrompt,
            imageAttachments: imageAttachments,
            imageConversationState: imageConversationState,
            latestSessionImageUpload: latestSessionImageUpload,
            preferredVideoImageSource: preferredVideoImageSource,
            isImageComparisonRequest: isImageComparisonRequest,
            sessionImageArtifacts: sessionImageArtifacts,
            activeSessionImageArtifact: activeSessionImageArtifact,
            isImageEditRequest: isImageEditRequest,
            isImageGenerationRequest: isImageGenerationRequest,
            imageUpscalePresets: imageUpscalePresets,
            isImageJobTool: isImageJobTool,
            updateImageJobMessage: updateImageJobMessage,
            isWatchingImageJob: isWatchingImageJob,
            resumeImageJobsForSession: resumeImageJobsForSession,
            resumeVideoJobsForSession: resumeVideoJobsForSession,
            updateVideoJobMessage: updateVideoJobMessage,
            watchVideoJob: watchVideoJob,
            isVideoRequest: isVideoRequest,
            videoOptionsForRequest: videoOptionsForRequest,
            watchImageJob: watchImageJob,
            toolFailureSummary: toolFailureSummary,
            toolSummary: toolSummary
        }
    };
})();
