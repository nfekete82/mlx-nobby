/* Native, safe interactive follow-up questions for the local chat. */
(function () {
    'use strict';

    const STORAGE_KEY = 'mlx-nobby-interactive-questions-mode-v1';
    const draftAnswers = new Map();
    const MAX_JSON_LENGTH = 12000;
    const FENCE = String.fromCharCode(96).repeat(3);

    function localeDe() {
        return String(window.MLXI18n?.getLocale?.() || document.documentElement?.lang || 'de')
            .toLowerCase().startsWith('de');
    }

    function localText(de, en) {
        return localeDe() ? de : en;
    }

    function getMode() {
        try {
            const value = window.localStorage?.getItem(STORAGE_KEY);
            return ['auto', 'always', 'off'].includes(value) ? value : 'auto';
        } catch {
            return 'auto';
        }
    }

    function setMode(value) {
        if (!['auto', 'always', 'off'].includes(value)) return false;
        try {
            window.localStorage?.setItem(STORAGE_KEY, value);
        } catch {
            return false;
        }
        return true;
    }

    function init() {
        const select = document.getElementById('interactiveQuestionsMode');
        if (!select) return;
        select.value = getMode();
        select.addEventListener('change', () => {
            setMode(select.value);
        });
    }

    function instructionForTurn(messages) {
        const mode = getMode();
        if (mode === 'off') return '';
        const last = Array.isArray(messages)
            ? [...messages].reverse().find(message => message?.role === 'user')
            : null;
        const userText = typeof last?.content === 'string' ? last.content : '';
        if (/^(?:Meine Antworten auf deine Rückfragen:|My answers to your follow-up questions:)/i.test(userText)) {
            return '\nThe user just completed your follow-up questionnaire. Use the answers to address their original request now. Do not ask the same questions again.\n';
        }
        if (/^(?:Bitte beantworte meine ursprüngliche Frage ohne weitere Rückfragen\.|Please answer my original question without further follow-up questions\.)/i.test(userText)) {
            return '\nThe user skipped the questionnaire. Answer their original request directly without further questions.\n';
        }
        const policy = mode === 'always'
            ? 'For substantial open-ended requests with missing individual preferences, prefer asking concise follow-up questions before a final recommendation.'
            : 'Ask follow-up questions only when at least two independent missing details would materially improve the result; otherwise answer directly or ask one normal text question.';
        return '\nINTERACTIVE FOLLOW-UP QUESTIONS (optional feature):\n'
            + policy + '\n'
            + 'Never ask repetitive, speculative, purely engagement-driven, or unsolicited sensitive questions. '
            + 'Do not delay explicit implementation, coding, quick facts, image generation or other already actionable tasks. '
            + 'If the user has already supplied the necessary details, give the answer instead. '
            + 'Ask at most three questions and do not ask for information already in the conversation.\n'
            + 'Write every question, answer choice and explanation in the same language as the user.\n'
            + 'IMPORTANT FORMAT RULE: If your answer would mainly ask the user two or more numbered or bulleted questions, ALWAYS use the interactive nobby-questions JSON format below INSTEAD of a plain text numbered list. Make all missing-preference questions clickable, with 3-6 realistic choices and a free-text question when options would be misleading. This is a UI contract, not optional formatting. Do NOT output the same questions both in prose and in the JSON block.\n'
            + 'When and only when a short questionnaire is useful, return a brief introduction followed by EXACTLY ONE fenced JSON block:\n'
            + FENCE + 'nobby-questions\n'
            + '{"title":"Short heading","description":"Optional one-sentence explanation",'
            + '"questions":[{"id":"q1","label":"Question text?","type":"single",'
            + '"options":["Choice A","Choice B","Other"]},'
            + '{"id":"q2","label":"More details?","type":"text","required":false}],'
            + '"footer":"Optional one-sentence note"}\n'
            + FENCE + '\n'
            + 'Types: single (radio options), multiple (checkbox options), text (free text). '
            + 'Use valid JSON only, no comments or trailing commas. '
            + 'Each option must be meaningful; do not assume the answers or draw a diagnosis from them. '
            + 'If a form is not necessary, never output a nobby-questions block.\n';
    }

    function clean(value, limit) {
        return typeof value === 'string' ? value.trim().slice(0, limit) : '';
    }

    function normalize(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)
            || !Array.isArray(raw.questions)
            || raw.questions.length < 1 || raw.questions.length > 4) return null;
        const questions = [];
        for (let i = 0; i < raw.questions.length; i++) {
            const item = raw.questions[i];
            if (!item || typeof item !== 'object') return null;
            const type = item.type || 'single';
            const label = clean(item.label, 240);
            if (!label || !['single', 'multiple', 'text'].includes(type)) return null;
            let options = [];
            if (type !== 'text') {
                if (!Array.isArray(item.options) || item.options.length < 2
                    || item.options.length > 10) return null;
                options = item.options.map(value => clean(value, 120));
                if (options.some(value => !value)
                    || new Set(options).size !== options.length) return null;
            }
            questions.push({
                id: clean(item.id, 40) || 'q' + (i + 1),
                label,
                type,
                options,
                required: item.required !== false
            });
        }
        return {
            title: clean(raw.title, 140),
            description: clean(raw.description, 400),
            footer: clean(raw.footer, 400),
            questions
        };
    }

    function extract(text, pending = false) {
        const content = String(text || '');
        const open = /^```nobby-questions[ \t]*\r?$/gm.exec(content);
        if (!open) return null;
        const start = open.index + open[0].length;
        const closing = /^```[ \t]*\r?$/gm;
        closing.lastIndex = start;
        const end = closing.exec(content);
        if (!end) {
            return pending ? {text: content.slice(0, open.index).trim(), loading: true} : null;
        }
        const block = content.slice(start, end.index).trim();
        if (!block || block.length > MAX_JSON_LENGTH) return null;
        let spec;
        try {
            spec = normalize(JSON.parse(block));
        } catch {
            return null;
        }
        if (!spec) return null;
        return {
            spec,
            text: (content.slice(0, open.index)
                + content.slice(end.index + end[0].length)).trim(),
            loading: false
        };
    }


    // Conservative compatibility fallback for local models that ask several
    // numbered questions in prose despite receiving the structured format rule.
    // It only applies to completed question-first answers, never to regular lists.
    function extractProseQuestions(value) {
        const content = typeof value === 'string' ? value : '';
        if (getMode() === 'off' || !content.trim() || content.length > 4500
            || content.includes(FENCE)) return null;

        const lines = content.split(/\r?\n/);
        const entries = [];
        let first = -1;
        let last = -1;
        let expected = 1;
        for (let i = 0; i < lines.length; i++) {
            const match = lines[i].match(/^\s*(\d+)[.)]\s+(.{10,})\s*$/);
            if (!match) {
                if (first >= 0 && last === i - 1 && lines[i].trim()) break;
                continue;
            }
            const number = Number(match[1]);
            if (first < 0 && number !== 1) continue;
            if (first >= 0 && number !== expected) return null;
            if (expected > 4) return null;
            const raw = match[2].trim();
            if (!raw.includes('?')) return null;
            entries.push(raw);
            if (first < 0) first = i;
            last = i;
            expected += 1;
        }
        if (entries.length < 2 || entries.length > 4) return null;
        const before = lines.slice(0, first).join('\n').trim();
        const after = lines.slice(last + 1).join('\n').trim();
        if (before.length > 1200 || after.length > 600) return null;
        const context = before + '\n' + after;
        if (!/(?:fragen|punkte|bräucht|brauch|benötig|beantwort|sag mir|gib mir|questions|tell me|let me know|need (?:to know|a few|some details))/i.test(context)) {
            return null;
        }

        const questions = entries.map((entry, index) => {
            let label = entry.replace(/\*\*|__/g, '');
            let sample = '';
            const example = /\((?:z\.\s*B\.?|e\.g\.?|zum Beispiel|beispielsweise)\s*:?\s*([^)]+)\)\s*\??$/i.exec(label);
            const parenthesis = /\(([^)]+)\)\s*\??$/.exec(label);
            if (example) {
                sample = example[1];
                label = label.slice(0, example.index).trim();
            } else if (parenthesis && parenthesis[1].includes(',')) {
                sample = parenthesis[1];
                label = label.slice(0, parenthesis.index).trim();
            }
            const options = sample
                ? sample.split(/\s*[,;]\s*/).map(part => part.replace(/[?.!]+$/g, '').trim())
                    .filter(Boolean)
                : [];
            const usable = options.length >= 2 && options.length <= 10
                && options.every(option => option.length <= 120)
                && new Set(options).size === options.length;
            const multiple = /(?:welche\s+(?:interessen|bereiche|themen)|was\s+(?:genau\s+)?(?:frustriert|stört)|which (?:interests|areas))/i.test(label);
            return {
                id: 'q' + (index + 1),
                label: clean(label, 240),
                type: usable ? (multiple ? 'multiple' : 'single') : 'text',
                options: usable ? options : [],
                required: true
            };
        });
        const spec = normalize({
            title: localeDe() ? 'Ein paar Fragen vorab' : 'A few questions first',
            questions
        });
        if (!spec) return null;
        return {spec, text: [before, after].filter(Boolean).join('\n\n'), loading: false};
    }

    function formatAnswers(spec, answers) {
        const lines = [localText(
            'Meine Antworten auf deine Rückfragen:',
            'My answers to your follow-up questions:'
        )];
        spec.questions.forEach((question, index) => {
            const value = answers[index];
            const answer = Array.isArray(value) ? value.join(', ') : String(value || '');
            lines.push((index + 1) + '. ' + question.label + '\n' + (
                answer || localText('(übersprungen)', '(skipped)')
            ));
        });
        lines.push(localText(
            'Bitte berücksichtige diese Angaben und beantworte nun meine ursprüngliche Frage.',
            'Please use these answers to address my original request now.'
        ));
        return lines.join('\n\n').slice(0, 7000);
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function enhance(container, message, session, index, markdownHtml) {
        const parsed = extract(message?.content, message?.response_pending === true)
            || (!message?.response_pending && message?.role === 'assistant'
                && session?.messages?.[session.messages.length - 1] === message
                ? extractProseQuestions(message?.content) : null);
        if (!parsed) return false;

        container.innerHTML = markdownHtml(parsed.text);
        if (parsed.loading) {
            container.appendChild(el('p', 'nobby-question-loading', localText(
                'Fragen werden vorbereitet …', 'Preparing questions …'
            )));
            return true;
        }

        const spec = parsed.spec;
        const form = el('form', 'nobby-question-form');
        form.setAttribute('aria-label', localText('Interaktive Rückfragen', 'Interactive questions'));
        if (spec.title) form.appendChild(el('h3', 'nobby-question-title', spec.title));
        if (spec.description) {
            form.appendChild(el('p', 'nobby-question-description', spec.description));
        }

        const key = String(session.id) + ':' + index;
        const completed = message.interactive_answers;
        const selected = completed?.answers || draftAnswers.get(key) || {};
        const fields = [];

        spec.questions.forEach((question, qIndex) => {
            const field = el('fieldset', 'nobby-question-field');
            const legend = el('legend', '', (qIndex + 1) + '. ' + question.label);
            field.appendChild(legend);
            if (question.type === 'text') {
                const input = el('textarea', 'nobby-question-textarea');
                input.rows = 3;
                input.maxLength = 1000;
                input.value = typeof selected[qIndex] === 'string' ? selected[qIndex] : '';
                input.placeholder = localText('Deine Antwort …', 'Your answer …');
                input.disabled = Boolean(completed);
                input.addEventListener('input', () => remember(qIndex, input.value));
                field.appendChild(input);
                fields.push({question, input});
            } else {
                const group = el('div', 'nobby-question-options');
                const inputs = [];
                question.options.forEach((option, optionIndex) => {
                    const label = el('label', 'nobby-question-option');
                    const control = el('input');
                    control.type = question.type === 'multiple' ? 'checkbox' : 'radio';
                    control.name = 'nobby-question-' + index + '-' + qIndex;
                    control.value = option;
                    control.checked = question.type === 'multiple'
                        ? Array.isArray(selected[qIndex]) && selected[qIndex].includes(option)
                        : selected[qIndex] === option;
                    control.disabled = Boolean(completed);
                    control.addEventListener('change', () => {
                        remember(qIndex, question.type === 'multiple'
                            ? inputs.filter(node => node.checked).map(node => node.value)
                            : option);
                    });
                    inputs.push(control);
                    label.append(control, el('span', '', option));
                    group.appendChild(label);
                });
                field.appendChild(group);
                fields.push({question, inputs});
            }
            form.appendChild(field);
        });

        if (spec.footer) form.appendChild(el('p', 'nobby-question-footer', spec.footer));
        const status = el('p', 'nobby-question-status');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');

        function remember(questionIndex, value) {
            const stored = {...(draftAnswers.get(key) || selected)};
            stored[questionIndex] = value;
            draftAnswers.set(key, stored);
        }

        function validTurn() {
            return window.MLXChatSessions?.currentSession?.() === session
                && session.messages[index] === message
                && session.messages[session.messages.length - 1] === message
                && !message.response_pending
                && !message.interactive_answers
                && !window.MLXChatGeneration?.isBusy?.()
                && !window.MLXChatRuntime?.isSwitching?.();
        }

        function send(answers, skipped = false) {
            if (!validTurn()) {
                status.textContent = localText(
                    'Bitte zuerst die aktuelle Antwort abschließen.',
                    'Please finish the current response first.'
                );
                return;
            }
            const composer = document.getElementById('input');
            if (!composer || composer.value.trim()
                || (window.MLXChatAttachments?.getAttachments?.() || []).length) {
                status.textContent = localText(
                    'Bitte zuerst den Chat-Entwurf oder Anhänge absenden bzw. entfernen.',
                    'Please send or remove your chat draft and attachments first.'
                );
                return;
            }
            const text = skipped
                ? localText(
                    'Bitte beantworte meine ursprüngliche Frage ohne weitere Rückfragen.',
                    'Please answer my original question without further follow-up questions.'
                )
                : formatAnswers(spec, answers);
            message.interactive_answers = {answers, skipped, submitted_at: Date.now()};
            draftAnswers.delete(key);
            window.MLXChatSessions.saveSessions();
            composer.value = text;
            window.MLXChatRuntime?.autoResize?.();
            window.MLXChatRendering?.renderMessages?.({contentUpdated: true});
            Promise.resolve(window.MLXChatGeneration.sendMessage()).catch(error => {
                console.error('Interactive question submission failed:', error);
            });
        }

        if (completed) {
            form.classList.add('nobby-question-completed');
            form.appendChild(el('p', 'nobby-question-done', completed.skipped
                ? localText('Rückfragen übersprungen', 'Questions skipped')
                : localText('Antworten gesendet', 'Answers submitted')));
        } else {
            const actions = el('div', 'nobby-question-actions');
            const submit = el('button', 'nobby-question-submit', localText(
                'Antworten auswerten →', 'Submit answers →'
            ));
            submit.type = 'submit';
            const skip = el('button', 'nobby-question-skip', localText(
                'Überspringen', 'Skip'
            ));
            skip.type = 'button';
            skip.addEventListener('click', () => send({}, true));
            actions.append(submit, skip);
            form.append(actions, status);
            form.addEventListener('submit', event => {
                event.preventDefault();
                const answers = {};
                let invalid = null;
                fields.forEach(({question, input, inputs}, i) => {
                    const value = input ? input.value.trim() : question.type === 'multiple'
                        ? inputs.filter(node => node.checked).map(node => node.value)
                        : (inputs.find(node => node.checked)?.value || '');
                    answers[i] = value;
                    if (question.required && !invalid
                        && (!value || (Array.isArray(value) && !value.length))) {
                        invalid = input || inputs[0];
                    }
                });
                if (invalid) {
                    status.textContent = localText(
                        'Bitte beantworte die Pflichtfragen.', 'Please answer the required questions.'
                    );
                    invalid.focus();
                    return;
                }
                send(answers);
            });
        }
        container.appendChild(form);
        return true;
    }

    window.MLXInteractiveQuestions = {
        init, getMode, setMode, instructionForTurn, normalize, extract,
        extractProseQuestions,
        formatAnswers, enhance
    };
})();
