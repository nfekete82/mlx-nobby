/* Shared history controls for the existing model console and job views. */
(() => {
    const pending = new Set();
    const scopes = [
        ['completed', 'Erledigte löschen', 'abgeschlossenen'],
        ['failed', 'Fehlgeschlagene löschen', 'fehlgeschlagenen'],
        ['all', 'Historie leeren', 'abgeschlossenen, fehlgeschlagenen, abgebrochenen und unterbrochenen'],
    ];

    function updateButtons(kind) {
        document.querySelectorAll('[data-history-kind="' + kind + '"]').forEach(button => {
            button.disabled = pending.has(kind);
        });
    }

    function mount(target, { kind, onComplete, buttonClass = 'model-console-button danger' }) {
        if (!target || !['downloads', 'batch'].includes(kind)) return;
        target.replaceChildren();
        const actions = document.createElement('div');
        actions.className = 'history-cleanup-actions';
        const feedback = document.createElement('span');
        feedback.className = 'settings-hint';
        feedback.setAttribute('role', 'status');
        for (const [scope, label, description] of scopes) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = buttonClass;
            button.dataset.historyKind = kind;
            button.textContent = label;
            button.addEventListener('click', async () => {
                if (pending.has(kind)) return;
                const noun = kind === 'downloads' ? 'Download-Einträge' : 'Job-Einträge';
                if (!window.confirm('Die ' + description + ' ' + noun + ' aus der Historie entfernen?\n\n' +
                    'Laufende, wartende und pausierte Vorgänge bleiben erhalten. Modelle sowie Ein- und Ausgabedateien werden nicht gelöscht.')) return;
                pending.add(kind);
                updateButtons(kind);
                feedback.textContent = 'Historie wird bereinigt …';
                try {
                    const response = await fetch(kind === 'downloads' ? '/api/mlx/jobs/cleanup' : '/api/mlx/batch/cleanup', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scope }),
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + response.status);
                    feedback.textContent = data.removed + ' Einträge entfernt · ' + data.remaining + ' erhalten';
                    await onComplete?.(data);
                } catch (error) {
                    feedback.textContent = 'Bereinigung fehlgeschlagen: ' + error.message;
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

    window.MLXHistoryCleanup = { mount };
})();
