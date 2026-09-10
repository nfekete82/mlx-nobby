(function () {
let logsPaused = false;
let logSources = [];
let activeLogSource = null;


function filteredLogText(lines) {

    const search =
        document.getElementById(
            'logSearch'
        );

    const query =
        search
            ? search.value.trim().toLowerCase()
            : '';

    if (!query) {
        return (lines || []).join('\n');
    }

    return (lines || [])
        .filter(
            line =>
                String(line)
                    .toLowerCase()
                    .includes(query)
        )
        .join('\n');
}


function renderLogTabs() {

    const tabs =
        document.getElementById(
            'logsTabs'
        );

    if (!tabs) return;

    tabs.innerHTML = '';

    for (const source of logSources) {

        const button =
            document.createElement(
                'button'
            );

        const active =
            source.id ===
            activeLogSource;

        button.className =
            active
                ? 'px-4 py-2 rounded-xl bg-blue-700 text-white text-sm font-semibold'
                : 'px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white text-sm font-semibold';

        button.textContent =
            source.name;

        button.addEventListener(
            'click',
            () => {
                activeLogSource =
                    source.id;

                renderLogTabs();
                renderActiveLog();
            }
        );

        tabs.appendChild(
            button
        );
    }
}


function renderActiveLog() {

    const source =
        logSources.find(
            item =>
                item.id ===
                activeLogSource
        );

    if (!source) return;

    document.getElementById(
        'activeLogTitle'
    ).textContent =
        source.name;

    document.getElementById(
        'activeLogFile'
    ).textContent =
        source.file || '–';

    const output =
        document.getElementById(
            'logsOutput'
        );

    output.textContent =
        filteredLogText(
            source.lines
        );

    const autoScroll =
        document.getElementById(
            'logsAutoScroll'
        );

    if (
        autoScroll &&
        autoScroll.checked
    ) {
        output.scrollTop =
            output.scrollHeight;
    }
}


async function loadLogsView() {

    if (logsPaused) return;

    const output =
        document.getElementById(
            'logsOutput'
        );

    if (!output) return;

    try {

        const response =
            await fetch(
                '/api/mlx/logs/all?limit=400'
            );

        if (!response.ok) {
            throw new Error(
                'HTTP ' +
                response.status
            );
        }

        const data =
            await response.json();

        logSources =
            data.sources || [];

        if (
            !activeLogSource &&
            logSources.length
        ) {
            activeLogSource =
                logSources[0].id;
        }

        if (
            activeLogSource &&
            !logSources.some(
                item =>
                    item.id ===
                    activeLogSource
            )
        ) {
            activeLogSource =
                logSources.length
                    ? logSources[0].id
                    : null;
        }

        renderLogTabs();

        if (activeLogSource) {
            renderActiveLog();

        } else {
            output.textContent =
                'No logs available.';
        }

        const updated =
            document.getElementById(
                'logsUpdated'
            );

        if (updated) {
            updated.textContent =
                new Date()
                    .toLocaleTimeString(
                        'en-US'
                    );
        }

    } catch (error) {

        output.textContent =
            'Could not load logs:\n' +
            error.message;
    }
}


    window.MLXLogs = {
        loadLogsView: loadLogsView
    };
})();
