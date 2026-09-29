(() => {
    'use strict';

    const CSS_ID = 'mlx-agent-diff-view-css';
    const CSS_VERSION = '20260929-agent-diff-v1';
    let observer = null;
    let enhancing = false;

    const COPY = {
        de: {
            compare: 'Änderungen vergleichen',
            old: 'Alt',
            next: 'Neu',
            onePrepared: '1 Änderung vorbereitet',
            file: 'Datei'
        },
        en: {
            compare: 'Compare changes',
            old: 'Old',
            next: 'New',
            onePrepared: '1 change prepared',
            file: 'File'
        }
    };

    function language() {
        return String(
            globalThis.MLXI18n?.getLanguage?.() ||
            globalThis.document?.documentElement?.lang ||
            'en'
        ).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function copy(key) {
        return COPY[language()]?.[key] || COPY.en[key] || key;
    }

    function installCss() {
        if (
            typeof document === 'undefined' ||
            document.getElementById(CSS_ID) ||
            !document.head
        ) return;

        const link = document.createElement('link');
        link.id = CSS_ID;
        link.rel = 'stylesheet';
        link.href = '/assets/chat/agent-diff-view.css?v=' + CSS_VERSION;
        document.head.appendChild(link);
    }

    function parseHunkHeader(line) {
        const match = String(line || '').match(
            /^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$/
        );
        if (!match) return null;
        return {
            oldStart: Number(match[1]),
            oldCount: Number(match[2] || 1),
            newStart: Number(match[3]),
            newCount: Number(match[4] || 1),
            suffix: match[5] || ''
        };
    }

    function parseUnifiedDiff(diffText) {
        const lines = String(diffText || '').split('\n');
        const rows = [];
        let oldLine = null;
        let newLine = null;
        let removed = [];
        let added = [];

        function flushChangeBlock() {
            const count = Math.max(removed.length, added.length);
            for (let index = 0; index < count; index += 1) {
                rows.push({
                    type: 'change',
                    left: removed[index] || null,
                    right: added[index] || null
                });
            }
            removed = [];
            added = [];
        }

        for (const line of lines) {
            if (line.startsWith('--- ') || line.startsWith('+++ ')) {
                continue;
            }
            if (line === '\\ No newline at end of file' || line === '') {
                continue;
            }

            const hunk = parseHunkHeader(line);
            if (hunk) {
                flushChangeBlock();
                oldLine = hunk.oldStart;
                newLine = hunk.newStart;
                rows.push({ type: 'hunk', text: line });
                continue;
            }

            if (line.startsWith('-')) {
                removed.push({
                    number: oldLine,
                    text: line.slice(1),
                    kind: 'removed'
                });
                if (oldLine != null) oldLine += 1;
                continue;
            }

            if (line.startsWith('+')) {
                added.push({
                    number: newLine,
                    text: line.slice(1),
                    kind: 'added'
                });
                if (newLine != null) newLine += 1;
                continue;
            }

            flushChangeBlock();

            if (line.startsWith(' ')) {
                rows.push({
                    type: 'context',
                    left: {
                        number: oldLine,
                        text: line.slice(1),
                        kind: 'context'
                    },
                    right: {
                        number: newLine,
                        text: line.slice(1),
                        kind: 'context'
                    }
                });
                if (oldLine != null) oldLine += 1;
                if (newLine != null) newLine += 1;
            }
        }

        flushChangeBlock();
        return rows;
    }

    function changeCount(files) {
        return (Array.isArray(files) ? files : []).reduce(
            (total, file) => total +
                Number(file?.added || 0) +
                Number(file?.removed || 0),
            0
        );
    }

    function cell(line, side) {
        const element = document.createElement('div');
        element.className = 'agent-split-diff-cell ' + side +
            (line?.kind ? ' is-' + line.kind : ' is-empty');

        const number = document.createElement('span');
        number.className = 'agent-split-diff-line-number';
        number.textContent = line?.number == null ? '' : String(line.number);

        const code = document.createElement('code');
        code.className = 'agent-split-diff-code';
        code.textContent = line?.text ?? '';

        element.append(number, code);
        return element;
    }

    function renderFileDiff(file) {
        const section = document.createElement('section');
        section.className = 'agent-split-diff-file';

        const header = document.createElement('div');
        header.className = 'agent-split-diff-file-header';

        const path = document.createElement('strong');
        path.textContent = String(file?.path || copy('file'));

        const stats = document.createElement('span');
        stats.className = 'agent-split-diff-stats';
        stats.textContent = '+' + Number(file?.added || 0) +
            ' / −' + Number(file?.removed || 0);

        header.append(path, stats);
        section.appendChild(header);

        const labels = document.createElement('div');
        labels.className = 'agent-split-diff-labels';
        const oldLabel = document.createElement('span');
        oldLabel.textContent = copy('old');
        const newLabel = document.createElement('span');
        newLabel.textContent = copy('next');
        labels.append(oldLabel, newLabel);
        section.appendChild(labels);

        const grid = document.createElement('div');
        grid.className = 'agent-split-diff-grid';

        for (const row of parseUnifiedDiff(file?.diff || '')) {
            if (row.type === 'hunk') {
                const hunk = document.createElement('div');
                hunk.className = 'agent-split-diff-hunk';
                hunk.textContent = row.text;
                grid.appendChild(hunk);
                continue;
            }

            const pair = document.createElement('div');
            pair.className = 'agent-split-diff-row ' +
                (row.type === 'change' ? 'is-change' : 'is-context');
            pair.append(
                cell(row.left, 'left'),
                cell(row.right, 'right')
            );
            grid.appendChild(pair);
        }

        section.appendChild(grid);
        return section;
    }

    function buildDiffViewer(files) {
        const list = Array.isArray(files)
            ? files.filter(file => typeof file?.diff === 'string')
            : [];
        if (!list.length) return null;

        const details = document.createElement('details');
        details.className = 'agent-git-diff';
        details.dataset.agentGitDiff = '1';
        details.open = changeCount(list) <= 120;

        const summary = document.createElement('summary');
        const totalAdded = list.reduce(
            (total, file) => total + Number(file?.added || 0),
            0
        );
        const totalRemoved = list.reduce(
            (total, file) => total + Number(file?.removed || 0),
            0
        );
        summary.textContent = copy('compare') +
            ' · +' + totalAdded + ' / −' + totalRemoved;
        details.appendChild(summary);

        const body = document.createElement('div');
        body.className = 'agent-git-diff-body';
        for (const file of list) {
            body.appendChild(renderFileDiff(file));
        }
        details.appendChild(body);
        return details;
    }

    function normalizeText(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function fixStepUx(row, step) {
        const title = row.querySelector?.('.agent-step-title');
        if (!title) return;

        if (
            step?.action === 'code_patch' &&
            Number(step?.result?.summary?.files || step?.result?.files?.length || 0) === 1
        ) {
            const text = normalizeText(title.textContent);
            if (/^1\s+(Änderungen|changes)\s+(vorbereitet|prepared)$/i.test(text)) {
                title.textContent = copy('onePrepared');
            }
        }

        const evidenceTitle = row.querySelector?.('.agent-test-evidence-title');
        if (
            evidenceTitle &&
            normalizeText(evidenceTitle.textContent) ===
                normalizeText(title.textContent)
        ) {
            evidenceTitle.hidden = true;
        }
    }

    function enhanceCard(card, message) {
        const steps = Array.isArray(message?.agent_run?.steps)
            ? message.agent_run.steps
            : [];
        const rows = Array.from(card.querySelectorAll('.agent-step'));

        rows.forEach((row, index) => {
            const step = steps[index];
            if (!step) return;
            fixStepUx(row, step);
        });

        let diffIndex = -1;
        for (let index = steps.length - 1; index >= 0; index -= 1) {
            if (
                steps[index]?.action === 'code_diff' &&
                Array.isArray(steps[index]?.result?.files)
            ) {
                diffIndex = index;
                break;
            }
        }
        if (diffIndex < 0) {
            for (let index = steps.length - 1; index >= 0; index -= 1) {
                if (
                    steps[index]?.action === 'code_patch' &&
                    Array.isArray(steps[index]?.result?.files)
                ) {
                    diffIndex = index;
                    break;
                }
            }
        }

        if (diffIndex < 0 || !rows[diffIndex]) return;
        if (rows[diffIndex].querySelector('[data-agent-git-diff="1"]')) return;

        const viewer = buildDiffViewer(steps[diffIndex].result.files);
        if (!viewer) return;

        const body = rows[diffIndex].querySelector('.agent-step-body') || rows[diffIndex];
        body.appendChild(viewer);
    }

    function enhance() {
        if (enhancing || typeof document === 'undefined') return 0;
        const session = globalThis.MLXChatSessions?.currentSession?.();
        const container = document.getElementById('messagesInner');
        if (!session || !container) return 0;

        const agentMessages = (session.messages || []).filter(
            message => message?.agent_run
        );
        const cards = Array.from(container.querySelectorAll('.agent-card'));
        if (!agentMessages.length || !cards.length) return 0;

        enhancing = true;
        let changed = 0;
        try {
            const count = Math.min(agentMessages.length, cards.length);
            for (let index = 0; index < count; index += 1) {
                const message = agentMessages[index];
                if (!message?.task_mode) continue;
                enhanceCard(cards[index], message);
                changed += 1;
            }
        } finally {
            enhancing = false;
        }
        return changed;
    }

    function install() {
        if (typeof document === 'undefined') return false;
        installCss();
        const container = document.getElementById('messagesInner');
        if (!container) return false;

        if (!observer && typeof MutationObserver !== 'undefined') {
            observer = new MutationObserver(() => {
                if (enhancing) return;
                queueMicrotask(enhance);
            });
            observer.observe(container, {
                childList: true,
                subtree: true
            });
        }

        enhance();
        return true;
    }

    globalThis.MLXAgentDiffView = {
        enhance,
        install,
        __test: {
            changeCount,
            normalizeText,
            parseHunkHeader,
            parseUnifiedDiff
        }
    };

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', install, { once: true });
        } else {
            install();
        }
        document.addEventListener('mlx-language-changed', () => {
            queueMicrotask(enhance);
        });
    }
})();
