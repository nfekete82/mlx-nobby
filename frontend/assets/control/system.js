(function () {
function formatSystemUptime(seconds) {
    if (seconds === null || seconds === undefined) {
        return '–';
    }

    const days = Math.floor(seconds / 86400);
    seconds %= 86400;

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);

    if (days > 0) return days + 'd ' + hours + 'h';
    if (hours > 0) return hours + 'h ' + minutes + 'm';

    return minutes + 'm';
}


async function loadSystemView() {
    const updated = document.getElementById('sysUpdated');

    try {
        const response = await fetch('/api/mlx/system');

        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }

        const data = await response.json();

        const system = data.system || {};
        const mlx = data.mlx || {};

        document.getElementById('sysRamTotal').textContent =
            system.total_gb != null
                ? system.total_gb + ' GB'
                : '–';

        document.getElementById('sysRamFree').textContent =
            system.free_percent != null
                ? system.free_percent + ' %'
                : '–';

        document.getElementById('sysSwap').textContent =
            (system.swap_used_gb ?? 0) +
            ' / ' +
            (system.swap_total_gb ?? 0) +
            ' GB';

        document.getElementById('sysMlxRam').textContent =
            mlx.memory_mb
                ? (mlx.memory_mb / 1024).toFixed(2) + ' GB'
                : '–';

        document.getElementById('sysPid').textContent =
            mlx.pid ?? '–';

        document.getElementById('sysPort').textContent =
            mlx.port ?? '–';

        document.getElementById('sysUptime').textContent =
            formatSystemUptime(mlx.uptime_seconds);

        document.getElementById('sysThinking').textContent =
            mlx.thinking ? 'ON' : 'OFF';

        document.getElementById('sysModel').textContent =
            mlx.model ?? '–';

        const args = mlx.server_args || [];

        document.getElementById('sysArgs').textContent =
            args.length
                ? args.join(' \\\n')
                : 'No running server arguments found.';

        updated.textContent =
            'Updated: ' +
            new Date().toLocaleTimeString('en-US');

    } catch (error) {
        if (updated) {
            updated.textContent =
                'Error: ' + error.message;
        }
    }
}



    window.MLXSystem = {
        loadSystemView: loadSystemView
    };
})();
