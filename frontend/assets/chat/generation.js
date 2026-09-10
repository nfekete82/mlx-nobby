'use strict';

function gt(key, fallback = '', variables = {}) {
    let value = window.MLXI18n?.t(
        'generation.' + key,
        fallback
    ) ?? fallback;

    for (const [name, replacement] of Object.entries(variables)) {
        value = value.replaceAll(
            '{' + name + '}',
            String(replacement)
        );
    }

    return value;
}

(function () {
    let getGenerating;
    let setGenerating;
    let getAbortController;
    let setAbortController;

    const input = document.getElementById('input');

    function configure(options) {
        getGenerating = options.getGenerating;
        setGenerating = options.setGenerating;
        getAbortController = options.getAbortController;
        setAbortController = options.setAbortController;
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


async function generateAssistant(session) {
if (
        getGenerating() ||
        MLXChatRuntime.isSwitching()
    ) {
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
        const apiMessages =
            buildApiMessages(
                session.messages.slice(0, -1)
            );

        console.log(
            '[MLX DEBUG] Chat messages:',
            apiMessages
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
                            .getSessionSystemPrompt()
                })
            }
        );

        if (!response.ok) {
            const error =
                await response.text();

            throw new Error(error);
        }

        const reader =
            response.body.getReader();

        const decoder =
            new TextDecoder();

        let buffer = '';

        while (true) {
            const {
                value,
                done
            } = await reader.read();

            if (done) break;

            buffer +=
                decoder.decode(
                    value,
                    { stream: true }
                );

            const events =
                buffer.split('\n\n');

            buffer =
                events.pop() || '';

            for (const event of events) {

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


async function runAgent(
    session,
    goal,
    assistantMessage,
    mode = 'diagnostic',
    conversationContext = []
) {
    setGenerating(true);
    setAbortController(null);
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
    MLXChatRendering.renderAll({
        contentUpdated: true
    });

    try {
        const pollProgress = async () => {
            try {
                const response = await fetch(
                    '/api/mlx/agent/runs/' + encodeURIComponent(runId)
                );
                if (!response.ok) return;
                const progress = await response.json();
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
                MLXChatRendering.renderAll({
                    contentUpdated: true
                });
            } catch (_error) {
                // Der synchrone Endpunkt bleibt die maßgebliche Antwort.
            }
        };

        progressTimer = setInterval(pollProgress, 800);
        pollProgress();

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
                    conversation_context:
                        conversationContext
                })
            }
        );

        if (!response.ok) {
            throw new Error(
                await response.text()
            );
        }

        const data = await response.json();

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

    } catch (error) {
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

    } finally {
        if (progressTimer) {
            clearInterval(progressTimer);
        }
        setGenerating(false);
        setAbortController(null);

        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll({
            contentUpdated: true
        });
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

    setGenerating(true);

    MLXChatSessions.saveSessions();
    MLXChatRendering.renderAll({
        contentUpdated: true
    });

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
        setGenerating(false);

        MLXChatSessions.saveSessions();
        MLXChatRendering.renderAll({
            contentUpdated: true
        });
    }
}


async function sendMessage(options = {}) {
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

    const imageArtifactCandidates =
        session.messages
            .slice()
            .reverse()
            .flatMap(message => {
                const artifacts =
                    message?.tool_result?.artifacts;

                return Array.isArray(artifacts)
                    ? artifacts
                    : [];
            })
            .filter(
                artifact =>
                    artifact?.image_id &&
                    String(
                        artifact.mime_type || ''
                    ).startsWith('image/')
            );

    const activeImageArtifactId =
        session.workspace?.active_artifact_id;

    const activeImageArtifact =
        imageArtifactCandidates.find(
            artifact =>
                artifact.artifact_id ===
                activeImageArtifactId
        ) ||
        imageArtifactCandidates[0] ||
        null;

    const refersToExistingImage =
        /\b(?:das|dieses|diesem|dieser|bild|foto|abbildung|es|davon|darauf)\b|\bist\s+das\b|\bsieht\s+(?:das|es)\b/i
            .test(prompt);
    const transformPattern = /anonymis|entfern|bereinig|ersetz|änder|aender|transformier|schwärz|schwaerz/i;
    const fileOperationPattern = /anonymis|entfern|bereinig|ersetz|änder|aender|transformier|schwärz|schwaerz|fass|zusammenfass|prüf|pruef|struktur|datensätz|datensaetz|felder|zeitraum|auffällig|auffaellig|problem|muster|analys/i;
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
    const refersToExistingFile = /\b(sie|datei|diese|diesen|ergebnis|letzte|bearbeitete|neue)\b/i.test(prompt);
    const ambiguousArtifactReference = !textFiles.length && !activeArtifact && refersToExistingFile && artifactCandidates.length > 1;
    const routesFileOperation = !auditPattern.test(prompt) && fileOperationPattern.test(prompt) &&
        (textFiles.length > 0 || /\b(sie|datei|diese|diesen)\b/i.test(prompt) && priorFileAttachments.length > 0);

    if (
        imageFiles.length &&
        !await MLXChatRuntime.ensureVisionSupport()
    ) {
        alert(
            gt(
            'vision_not_supported',
            'The active model does not support image analysis. Please select a VLM/vision model first.'
        )
        );

        return;
    }

    let documentPageContext = '';
    let documentRagContext = '';

    const currentDocumentFiles =
        currentAttachments.filter(
            file => file.kind === 'document'
        );

    /*
     * Dokumente bleiben nach dem ersten Senden im Gespräch aktiv.
     *
     * Priorität:
     * 1. aktuell angehängtes Dokument
     * 2. zuletzt verwendetes Dokument aus dem Chatverlauf
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

    const attachmentContext =
        MLXChatAttachments.buildAttachmentContext() +
        documentPageContext +
        documentRagContext;

    const effectivePrompt =
        prompt ||
        (
            imageFiles.length
                ? 'Describe this image in detail.'
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
        refersToExistingImage
    ) {
        if (!await MLXChatRuntime.ensureVisionSupport()) {
            alert(
                gt(
                'vision_not_supported',
                'The active model does not support image analysis. Please select a VLM/vision model first.'
            )
            );
            return;
        }

        try {
            const dataUrl =
                await imageArtifactDataUrl(
                    activeImageArtifact
                );

            visionImages.push({
                kind: 'image',
                name:
                    activeImageArtifact.name ||
                    'generated-image.png',
                type:
                    activeImageArtifact.mime_type ||
                    'image/png',
                image_id:
                    activeImageArtifact.image_id,
                artifact_id:
                    activeImageArtifact.artifact_id,
                data_url: dataUrl
            });

            console.log(
                '[MLX Vision] Active image artifact:',
                activeImageArtifact.artifact_id
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
            )
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
        /\b(?:erstelle|generiere|erzeuge|zeichne|mach)\b.*\b(?:bild|foto|illustration)\b|\b(?:bild|foto|illustration)\s+von\b/i.test(prompt);

    const explicitImageEditRequest =
        /\b(?:bearbeite|ändere|aendere|verändere|veraendere|ersetze|entferne|füge|fuege|retuschiere|ändere.*stil|aendere.*stil)\b/i.test(prompt);

    const routesCurrentImageToVision =
        imageFiles.length > 0 &&
        !explicitImageCreationRequest &&
        !explicitImageEditRequest;

    if (
        !routesFileOperation &&
        !textFiles.length &&
        !routesCurrentImageToVision
    ) {
        const imageRequest = explicitImageCreationRequest;
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
            const fileContext = priorFileAttachments[0] || null;
            const conversationContext =
                buildAgentConversationContext(
                    session,
                    userMessage
                );
            const actionResponse = await fetch('/api/mlx/chat/actions', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt,
                    file_context: fileContext,
                    image_options: options?.image || null,
                    conversation_context: conversationContext
                })
            });
            if (!actionResponse.ok) throw new Error(await actionResponse.text());
            const toolResult = await actionResponse.json();

            if (
                toolResult.tool === 'image_generate' &&
                Array.isArray(toolResult.artifacts) &&
                toolResult.artifacts[0]?.artifact_id
            ) {
                session.workspace = {
                    ...(session.workspace || {}),
                    active_artifact_id:
                        toolResult.artifacts[0].artifact_id
                };
            }

            // ------------------------------------------------
            // Auto-Agent
            // ------------------------------------------------
            // Der normale Chat-Router kann eine komplexe Aufgabe
            // automatisch an den bestehenden Agent-Loop eskalieren.

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
                    conversationContext
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
                    'The following information comes from a current web search. ' +
                    'For some results, the actual webpage content was loaded as well. ' +
                    'Prefer the loaded webpage content over the search snippet. ' +
                    'Ignore navigation, cookie notices, menus, footers, and other irrelevant page content. ' +
                    'Do not claim that something is current unless it is supported by these sources. ' +
                    'At the end, list the sources actually used as clickable URLs. ' +
                    'If the sources are insufficient or contradictory, state that explicitly.\n\n' +
                    searchContext;

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
                    content: toolResult.status === 'completed' ? toolSummary(toolResult) : gt('action_failed', 'The action could not be completed.'),
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
                        chunk_tokens: 2000,
                        attachment_id: item.upload.stored_name || item.attachment.file_id || null
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
                watchBatchJob(session, routed.job.id);
            }
            MLXChatSessions.saveSessions();
            MLXChatRendering.renderAll({
                contentUpdated: true
            });
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
                            attachment_id: message.file_artifact.file_id
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
        configure: configure,
        regenerateLastAnswer: regenerateLastAnswer,
        generateAssistant: generateAssistant,
        sendMessage: sendMessage,
        approveAgentAction: approveAgentAction
    };
})();
