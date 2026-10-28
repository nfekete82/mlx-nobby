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

    function wording(de, en) {
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
            : 'Only ask follow-up questions if at least two independent missing details would materially improve the result; otherwise answer directly or ask a single normal text question.';
        return '\nINTERACTIVE FOLLOW-UP QUESTIONS (optional feature):\n'
            + policy + '\n'
            + 'Never ask repetitive, speculative, purely engagement-driven, or unsolicited sensitive questions. '
            + 'Do not delay explicit implementation, coding, quick facts, image generation or other already actionable tasks. '
            + 'If the user has already supplied the necessary details, give the answer instead. '
            + 'Ask at most three questions and do not ask for information already in the conversation.\n'
            + 'Write every question, answer choice and explanation in the same language as the user.\n'
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
                    || item.options.length > 8) return null;
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

    function formatAnswers(spec, answers) {
        const lines = [wording(
            'Meine Antworten auf deine Rückfragen:',
            'My answers to your follow-up questions:'
        )];
        spec.questions.forEach((question, index) => {
            const value = answers[index];
            const answer = Array.isArray(value) ? value.join(', ') : String(value || '');
            lines.push((index + 1) + '. ' + question.label + '\n' + (
                answer || wording('(übersprungen)', '(skipped)')
            ));
        });
        lines.push(wording(
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
        const parsed = extract(message?.content, message?.response_pending === true);
        if (!parsed) return false;

        container.innerHTML = markdownHtml(parsed.text);
        if (parsed.loading) {
            container.appendChild(el('p', 'nobby-question-loading', wording(
                'Fragen werden vorbereitet …', 'Preparing questions …'
            )));
            return true;
        }

        const spec = parsed.spec;
        const form = el('form', 'nobby-question-form');
        form.setAttribute('aria-label', wording('Interaktive Rückfragen', 'Interactive questions'));
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
                input.placeholder = wording('Deine Antwort …', 'Your answer …');
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
                status.textContent = wording(
                    'Bitte zuerst die aktuelle Antwort abschließen.',
                    'Please finish the current response first.'
                );
                return;
            }
            const composer = document.getElementById('input');
            if (!composer || composer.value.trim()
                || (window.MLXChatAttachments?.getAttachments?.() || []).length) {
                status.textContent = wording(
                    'Bitte zuerst den Chat-Entwurf oder Anhänge absenden bzw. entfernen.',
                    'Please send or remove your chat draft and attachments first.'
                );
                return;
            }
            const text = skipped
                ? wording(
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
                ? wording('Rückfragen übersprungen', 'Questions skipped')
                : wording('Antworten gesendet', 'Answers submitted')));
        } else {
            const actions = el('div', 'nobby-question-actions');
            const submit = el('button', 'nobby-question-submit', wording(
                'Antworten auswerten →', 'Submit answers →'
            ));
            submit.type = 'submit';
            const skip = el('button', 'nobby-question-skip', wording(
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
                    status.textContent = wording(
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
        formatAnswers, enhance
    };
})();
