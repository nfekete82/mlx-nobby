/* Shared history controls for the existing model console and job views. */
(() => {
    const pending = new Set();
    const mounts = new Map();
    const ht = (key, fallback) => window.MLXI18n?.t(
        `history.${key}`,
        fallback
    ) ?? fallback;
    const scopes = [
        ['completed', 'delete_completed', 'completed_description'],
        ['failed', 'delete_failed', 'failed_description'],
        ['all', 'clear', 'all_description'],
    ];

    function updateButtons(kind) {
        document.querySelectorAll('[data-history-kind="' + kind + '"]').forEach(button => {
            button.disabled = pending.has(kind);
        });
    }

    function mount(target, { kind, onComplete, buttonClass = 'model-console-button danger' }) {
        if (!target || !['downloads', 'batch'].includes(kind)) return;
        mounts.set(target, { kind, onComplete, buttonClass });
        target.replaceChildren();
        const actions = document.createElement('div');
        actions.className = 'history-cleanup-actions';
        const feedback = document.createElement('span');
        feedback.className = 'settings-hint';
        feedback.setAttribute('role', 'status');
        for (const [scope, labelKey, descriptionKey] of scopes) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = buttonClass;
            button.dataset.historyKind = kind;
            button.textContent = ht(labelKey, {
                delete_completed: 'Delete completed',
                delete_failed: 'Delete failed',
                clear: 'Clear history',
            }[labelKey]);
            button.addEventListener('click', async () => {
                if (pending.has(kind)) return;
                const description = ht(descriptionKey, descriptionKey);
                const noun = kind === 'downloads'
                    ? ht('download_entries', 'download entries')
                    : ht('job_entries', 'job entries');
                if (!window.confirm(ht(
                    'confirm',
                    'Remove the {description} {noun} from history?\n\nRunning, queued, and paused operations are preserved. Models and input/output files are not deleted.'
                ).replace('{description}', description).replace('{noun}', noun))) return;
                pending.add(kind);
                updateButtons(kind);
                feedback.textContent = ht('cleaning', 'Cleaning history …');
                try {
                    const response = await fetch(kind === 'downloads' ? '/api/mlx/jobs/cleanup' : '/api/mlx/batch/cleanup', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scope }),
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + response.status);
                    feedback.textContent = ht(
                        'removed',
                        '{removed} entries removed · {remaining} preserved'
                    ).replace('{removed}', data.removed).replace('{remaining}', data.remaining);
                    await onComplete?.(data);
                } catch (error) {
                    feedback.textContent = ht('failed', 'Cleanup failed:') + ' ' + error.message;
                } finally {
                    pending.delete(kind);
                    updateButtons(kind);
                }
            });
            actions.appendChild(button);
        }
        target.append(actions, feedback);
        updateButtons(kind);
    }

    document.addEventListener?.('mlx-language-changed', () => {
        for (const [target, options] of mounts) {
            mount(target, options);
        }
    });

    window.MLXHistoryCleanup = { mount };
})();
