
function findSectionByHeading(title) {
    const headings =
        Array.from(
            document.querySelectorAll('h2')
        );

    const heading =
        headings.find(
            item =>
                item.textContent.trim() === title
        );

    if (!heading) {
        return null;
    }

    let element = heading;

    while (
        element &&
        element.parentElement
    ) {
        element =
            element.parentElement;

        if (
            element.classList &&
            element.classList.contains('mt-6')
        ) {
            return element;
        }
    }

    return heading.parentElement;
}


function setupAppViews() {

    /*
     * Bestehende Bereiche identifizieren.
     * Kein HTML muss dafür zerstört werden.
     */

    const addModel =
        findSectionByHeading(
            'Neues Modell'
        );

    const models =
        findSectionByHeading(
            'Modelle'
        );

    const cache =
        findSectionByHeading(
            'Lokaler Cache'
        );

    const downloads =
        findSectionByHeading(
            'Downloads & Jobs'
        );

    const batch =
        document.getElementById(
            'batch-transform'
        );


    if (addModel) {
        addModel.dataset.appView =
            'models';
    }

    if (models) {
        models.dataset.appView =
            'models';
    }

    if (cache) {
        cache.dataset.appView =
            'models';
    }

    if (downloads) {
        downloads.dataset.appView =
            'downloads';
    }

    if (batch) {
        batch.dataset.appView =
            'batch';
    }


    /*
     * Alles vor "Neues Modell" gehört zum Dashboard.
     */

    if (addModel) {

        let element =
            addModel.previousElementSibling;

        while (element) {

            if (
                element.tagName !== 'SCRIPT' &&
                element.id !== 'extraViews'
            ) {
                element.dataset.appView =
                    'dashboard';
            }

            element =
                element.previousElementSibling;
        }
    }


    showAppView();
}


function currentAppView() {

    const hash =
        location.hash
            .replace('#', '')
            .trim();

    const allowed = new Set([
        'dashboard',
        'models',
        'downloads',
        'batch',
        'system',
        'logs'
    ]);

    if (
        !hash ||
        !allowed.has(hash)
    ) {
        return 'dashboard';
    }

    return hash;
}


function showAppView() {

    const view =
        currentAppView();


    document
        .querySelectorAll(
            '[data-app-view]'
        )
        .forEach(
            element => {

                const visible =
                    element.dataset.appView ===
                    view;

                element.classList.toggle(
                    'hidden',
                    !visible
                );
            }
        );


    document
        .querySelectorAll(
            '.nav-item'
        )
        .forEach(
            item => {

                const active =
                    item.dataset.view ===
                    view;

                if (active) {
                    item.className =
                        'nav-item px-3 py-2 rounded-lg text-sm font-medium bg-blue-700 text-white';

                } else {
                    item.className =
                        'nav-item px-3 py-2 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-900';
                }
            }
        );


    /*
     * Bereichsspezifische Daten erst laden,
     * wenn der jeweilige View aktiv ist.
     */
    if (
        view === 'system' &&
        typeof MLXSystem !== 'undefined' &&
        typeof MLXSystem.loadSystemView === 'function'
    ) {
        MLXSystem.loadSystemView();
    }

    if (
        view === 'logs' &&
        typeof MLXLogs !== 'undefined' &&
        typeof MLXLogs.loadLogsView === 'function'
    ) {
        MLXLogs.loadLogsView();
    }
}


window.addEventListener(
    'hashchange',
    showAppView
);



let busy = false;
let currentThinking = false;

function setButtonsDisabled(disabled) {
    document.querySelectorAll('.server-btn').forEach(button => {
        button.disabled = disabled;
    });

    document.getElementById('thinkingToggle').disabled = disabled;
}

function renderThinking(enabled) {
    currentThinking = enabled;

    const text = document.getElementById('thinking');
    const toggle = document.getElementById('thinkingToggle');
    const knob = document.getElementById('thinkingKnob');

    text.textContent = enabled ? 'ON' : 'OFF';

    if (enabled) {
        text.className = 'text-xl font-semibold text-emerald-400';
        toggle.className =
            'relative inline-flex h-7 w-12 items-center rounded-full bg-emerald-600 transition disabled:opacity-40';
        knob.className =
            'inline-block h-5 w-5 transform rounded-full bg-white transition translate-x-6';
    } else {
        text.className = 'text-xl font-semibold text-slate-300';
        toggle.className =
            'relative inline-flex h-7 w-12 items-center rounded-full bg-slate-700 transition disabled:opacity-40';
        knob.className =
            'inline-block h-5 w-5 transform rounded-full bg-white transition translate-x-1';
    }
}

async function loadStatus() {
    try {
        const response = await fetch('/api/mlx/status');

        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }

        const data = await response.json();

        document.getElementById('model').textContent = data.model ?? '–';
        document.getElementById('pid').textContent = data.pid ?? '–';
        document.getElementById('port').textContent = data.port ?? '–';

        document.getElementById('memory').textContent =
            data.memory_mb
                ? (data.memory_mb / 1024).toFixed(2) + ' GB'
                : '–';

        renderThinking(!!data.thinking);

        const badge = document.getElementById('statusBadge');
        const globalBadge = document.getElementById('globalStatusBadge');
        const state = document.getElementById('serverState');

        if (data.online) {
            badge.textContent = '● ONLINE';

            if (globalBadge) {
                globalBadge.textContent =
                    '● ONLINE';

                globalBadge.className =
                    'hidden lg:block px-3 py-2 rounded-full bg-emerald-950 border border-emerald-900 text-emerald-400 text-xs font-semibold';
            }
            badge.className =
                'px-4 py-2 rounded-full bg-emerald-950 text-emerald-400 text-sm font-semibold';

            state.textContent = 'MLX läuft';
            state.className = 'text-2xl font-bold text-emerald-400';

        } else {
            badge.textContent = '● OFFLINE';
            badge.className =
                'px-4 py-2 rounded-full bg-red-950 text-red-400 text-sm font-semibold';

            state.textContent = 'MLX gestoppt';
            state.className = 'text-2xl font-bold text-red-400';
        }

        document.getElementById('lastUpdate').textContent =
            'Aktualisiert: ' + new Date().toLocaleTimeString('de-DE');

    } catch (error) {
        document.getElementById('statusBadge').textContent = '● AGENT FEHLER';
        document.getElementById('serverState').textContent = 'Nicht erreichbar';
    }
}



async function addModel(alias, repo, quantization) {
    const button =
        document.getElementById('addModelButton');

    const status =
        document.getElementById('addModelStatus');

    if (busy) return;

    alias = alias.trim();
    repo = repo.trim();

    if (!alias) {
        status.textContent = 'Bitte einen Alias eingeben.';
        status.className =
            'text-sm text-amber-400 mt-4 min-h-[22px]';
        return;
    }

    if (!repo) {
        status.textContent =
            'Bitte ein Hugging-Face-Repository eingeben.';

        status.className =
            'text-sm text-amber-400 mt-4 min-h-[22px]';
        return;
    }

    busy = true;
    button.disabled = true;
    setButtonsDisabled(true);

    status.textContent =
        'Modell wird angelegt und Download gestartet…';

    status.className =
        'text-sm text-blue-400 mt-4 min-h-[22px]';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/models/add',
            MLXCommon.jsonRequest(
                'POST',
                {
                    alias: alias,
                    repo: repo,
                    quantization: quantization || null
                }
            )
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ ' + alias +
            ' hinzugefügt · Downloadjob ' +
            data.job.id;

        status.className =
            'text-sm text-emerald-400 mt-4 min-h-[22px]';

        document.getElementById('addModelAlias').value = '';
        document.getElementById('addModelRepo').value = '';

        await MLXModels.loadModels();
        await MLXJobs.loadJobs();

        await MLXCache.loadCache();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

        status.className =
            'text-sm text-red-400 mt-4 min-h-[22px]';

    } finally {
        busy = false;
        button.disabled = false;
        setButtonsDisabled(false);
    }
}



async function removeModelAlias(alias, repo) {
    if (busy) return;

    const confirmed = confirm(
        'Alias "' + alias + '" entfernen?\n\n' +
        repo +
        '\n\nDer lokale Modell-Cache bleibt erhalten.'
    );

    if (!confirmed) return;

    busy = true;
    setButtonsDisabled(true);

    document.querySelectorAll('.model-btn, .remove-model-btn').forEach(button => {
        button.disabled = true;
    });

    const status =
        document.getElementById('actionStatus');

    status.textContent =
        'Alias ' + alias + ' wird entfernt…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/models/' + encodeURIComponent(alias),
            {
                method: 'DELETE'
            }
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ Alias ' + alias + ' entfernt';

        await MLXModels.loadModels();
        await MLXCache.loadCache();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);

        document.querySelectorAll('.model-btn, .remove-model-btn').forEach(button => {
            button.disabled = false;
        });
    }
}



async function switchModel(alias) {
    if (busy) return;

    busy = true;
    setButtonsDisabled(true);

    document.querySelectorAll('.model-btn').forEach(button => {
        button.disabled = true;
    });

    const status =
        document.getElementById('actionStatus');

    status.textContent =
        'Modell ' + alias + ' wird gestartet…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/model/' + encodeURIComponent(alias),
            {
                method: 'POST'
            }
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ Modell ' + alias + ' aktiv';

        await loadStatus();
MLXSystem.loadSystemView();
        await MLXModels.loadModels();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);

        document.querySelectorAll('.model-btn').forEach(button => {
            button.disabled = false;
        });
    }
}



async function redownloadModel(target, repo, size) {
    if (busy) return;

    const confirmed = confirm(
        'Modell wirklich neu herunterladen?\n\n' +
        repo +
        '\nAktuelle Cache-Größe: ' + size +
        '\n\nDer vorhandene Cache wird verworfen und neu geladen.'
    );

    if (!confirmed) return;

    busy = true;
    setButtonsDisabled(true);

    document.querySelectorAll(
        '.redownload-btn, .delete-cache-btn, .retry-btn, .model-btn, .remove-model-btn'
    ).forEach(button => {
        button.disabled = true;
    });

    const status =
        document.getElementById('actionStatus');

    status.textContent =
        'Redownload für ' + target + ' wird gestartet…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/jobs/redownload/' + encodeURIComponent(target),
            {
                method: 'POST'
            }
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ Redownload gestartet · Job ' + data.id;

        await MLXJobs.loadJobs();
        await MLXCache.loadCache();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);

        document.querySelectorAll(
            '.redownload-btn, .delete-cache-btn, .retry-btn, .model-btn, .remove-model-btn'
        ).forEach(button => {
            button.disabled = false;
        });
    }
}



async function deleteModelCache(target, repo, size) {
    if (busy) return;

    const confirmed = confirm(
        'Lokalen Cache wirklich löschen?\n\n' +
        repo +
        '\nGröße: ' + size +
        '\n\nDer Alias bleibt erhalten.'
    );

    if (!confirmed) return;

    busy = true;
    setButtonsDisabled(true);

    document.querySelectorAll(
        '.delete-cache-btn, .retry-btn, .model-btn, .remove-model-btn'
    ).forEach(button => {
        button.disabled = true;
    });

    const status =
        document.getElementById('actionStatus');

    status.textContent =
        'Cache von ' + target + ' wird gelöscht…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/cache/' + encodeURIComponent(target),
            {
                method: 'DELETE'
            }
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ Cache gelöscht · Alias bleibt erhalten';

        await MLXCache.loadCache();
        await MLXModels.loadModels();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);

        document.querySelectorAll(
            '.delete-cache-btn, .retry-btn, .model-btn, .remove-model-btn'
        ).forEach(button => {
            button.disabled = false;
        });
    }
}



async function retryDownload(target) {
    if (busy) return;

    busy = true;
    setButtonsDisabled(true);

    document.querySelectorAll('.retry-btn').forEach(button => {
        button.disabled = true;
    });

    const status =
        document.getElementById('actionStatus');

    status.textContent =
        'Download ' + target + ' wird fortgesetzt…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/jobs/retry/' + encodeURIComponent(target),
            {
                method: 'POST'
            }
        );

        if (!response.ok) {
            throw MLXCommon.fastApiDetailError(data);
        }

        status.textContent =
            '✓ Downloadjob gestartet · ' + data.id;

        await MLXJobs.loadJobs();
        await MLXCache.loadCache();

    } catch (error) {
        status.textContent =
            'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);

        document.querySelectorAll('.retry-btn').forEach(button => {
            button.disabled = false;
        });
    }
}



async function serverCommand(command) {
    if (busy) return;

    busy = true;
    setButtonsDisabled(true);

    const status = document.getElementById('actionStatus');
    status.textContent = command + ' läuft…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/server/' + command,
            { method: 'POST' }
        );

        if (!response.ok) {
            throw new Error(JSON.stringify(data.detail));
        }

        status.textContent = '✓ ' + command + ' erfolgreich';

        await loadStatus();
        await MLXModels.loadModels();

    } catch (error) {
        status.textContent = 'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);
    }
}

async function toggleThinking() {
    if (busy) return;

    busy = true;
    setButtonsDisabled(true);

    const target = currentThinking ? 'off' : 'on';
    const status = document.getElementById('actionStatus');

    status.textContent =
        'Thinking wird ' + (target === 'on' ? 'aktiviert' : 'deaktiviert') + '…';

    try {
        const {
            response,
            data
        } = await MLXCommon.fetchJson(
            '/api/mlx/thinking/' + target,
            { method: 'POST' }
        );

        if (!response.ok) {
            throw new Error(JSON.stringify(data.detail));
        }

        status.textContent =
            '✓ Thinking ' + (target === 'on' ? 'aktiviert' : 'deaktiviert');

        await loadStatus();
        await MLXModels.loadModels();

    } catch (error) {
        status.textContent = 'Fehler: ' + error.message;

    } finally {
        busy = false;
        setButtonsDisabled(false);
    }
}

document.getElementById('addModelForm').addEventListener(
    'submit',
    event => {
        event.preventDefault();

        addModel(
            document.getElementById('addModelAlias').value,
            document.getElementById('addModelRepo').value,
            document.getElementById('addModelQuant').value
        );
    }
);



document.querySelectorAll('.server-btn').forEach(button => {
    button.addEventListener('click', () => {
        serverCommand(button.dataset.command);
    });
});

document.getElementById('thinkingToggle').addEventListener(
    'click',
    toggleThinking
);

setupAppViews();

loadStatus();
MLXModels.loadModels();
MLXCache.loadCache();
MLXJobs.loadJobs();

if (
    typeof MLXBatchTransform !== 'undefined' &&
    typeof MLXBatchTransform.init === 'function'
) {
    MLXBatchTransform.init();
}

setInterval(() => {
    if (!busy) {
        loadStatus();
        MLXJobs.loadJobs();


        MLXCache.loadCache();
    }
}, 3000);
