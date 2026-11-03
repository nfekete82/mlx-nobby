'use strict';

/* Optional, read-only energy history panel in the existing System settings. */
(() => {
    const API = '/api/mlx/system/energy';
    const REFRESH_MS = 30000;
    let root = null;
    let timer = null;
    let mountObserver = null;
    let busy = false;

    function german() {
        return String(window.MLXI18n?.getLocale?.() ||
            document.documentElement.lang || 'de').toLowerCase().startsWith('de');
    }

    function tr(de, en) {
        return german() ? de : en;
    }

    function node(tag, className, content) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (content != null) element.textContent = String(content);
        return element;
    }

    function format(value, digits = 2) {
        const number = Number(value);
        return Number.isFinite(number)
            ? number.toLocaleString(german() ? 'de-DE' : 'en-US', {
                minimumFractionDigits: digits,
                maximumFractionDigits: digits
            })
            : '—';
    }

    function stat(title, value) {
        const item = node('div', 'mlx-energy-stat');
        item.append(node('span', '', title), node('strong', '', value));
        return item;
    }

    function show(report) {
        if (!root) return;
        const status = root.querySelector('[data-energy-status]');
        const metrics = root.querySelector('[data-energy-stats]');
        const days = root.querySelector('[data-energy-days]');
        const hours = root.querySelector('[data-energy-hours]');
        const description = root.querySelector('[data-energy-details]');
        const hasData = Number(report?.seven_days_kwh) > 0;
        const live = report?.active === true;
        status.textContent = live
            ? tr('● Messung aktiv', '● Collecting')
            : tr('○ Logger offline oder noch keine Werte', '○ Logger offline or no values yet');
        metrics.replaceChildren(
            stat(tr('Aktuell', 'Now'),
                live && report.current_w != null ? format(report.current_w, 1) + ' W' : '—'),
            stat(tr('Heute', 'Today'), format(report.today_kwh, 3) + ' kWh'),
            stat(tr('Heute (geschätzt)', 'Today (estimated)'),
                format(report.today_eur, 2) + ' €'),
            stat(tr('Erfasste Zeit heute', 'Measured today'),
                format(report.today_measured_hours, 2) + ' h')
        );
        days.replaceChildren();
        const values = Array.isArray(report.days) ? report.days : [];
        const maximum = Math.max(0.00001, ...values.map(item => Number(item.kwh) || 0));
        for (const item of values) {
            const column = node('div', 'mlx-energy-column');
            const chart = node('div', 'mlx-energy-bar-shell');
            const bar = node('div', 'mlx-energy-bar');
            bar.style.height = (Math.max(0, Number(item.kwh) || 0) / maximum * 100) + '%';
            const readable = item.date?.slice(5) || '—';
            const caption = node('small', '', readable);
            const amount = format(item.kwh, 3) + ' kWh';
            column.title = String(item.date || '') + ': ' + amount +
                ' / ' + format(item.measured_hours, 2) + ' h';
            column.setAttribute('aria-label', column.title);
            chart.append(bar);
            column.append(chart, caption);
            days.append(column);
        }
        const recent = (Array.isArray(report.hours) ? report.hours : []).slice(-12);
        hours.replaceChildren();
        if (recent.length) {
            const maxWh = Math.max(0.01, ...recent.map(item => Number(item.wh) || 0));
            for (const item of recent) {
                const row = node('div', 'mlx-energy-hour');
                const shortHour = String(item.hour || '').slice(11, 16);
                const label = node('span', '', shortHour);
                const track = node('div', 'mlx-energy-hour-track');
                const progress = node('div', 'mlx-energy-hour-progress');
                progress.style.width = (100 * (Number(item.wh) || 0) / maxWh) + '%';
                track.append(progress);
                row.append(label, track, node('small', '', format(item.wh, 1) + ' Wh'));
                hours.append(row);
            }
        } else {
            hours.append(node('p', 'mlx-energy-muted',
                tr('Noch keine erfassten Stunden.', 'No measured hours yet.')));
        }
        description.textContent = hasData
            ? tr('Letzte 7 Tage: ', 'Last 7 days: ') +
                format(report.seven_days_kwh, 3) + ' kWh · ' +
                tr('Strompreis ', 'Electricity price ') +
                format(report.price_eur_kwh, 2) + ' €/kWh'
            : tr('Keine Messwerte vorhanden. macmon und den optionalen Host-Logger installieren.',
                'No measurements. Install macmon and the optional host logger.');
    }

    async function refresh() {
        if (!root || busy || document.hidden) return;
        const settings = root.closest('.settings');
        if (settings && !settings.classList.contains('open')) return;
        if (root.closest('[hidden]')) return;
        busy = true;
        try {
            const response = await fetch(API, {cache: 'no-store'});
            if (!response.ok) throw new Error('HTTP ' + response.status);
            show(await response.json());
        } catch (_error) {
            const status = root.querySelector('[data-energy-status]');
            if (status) status.textContent = tr('Energie-API nicht erreichbar',
                'Energy API unavailable');
        } finally {
            busy = false;
        }
    }

    function addCss() {
        if (document.getElementById('mlx-energy-styles')) return;
        const style = node('style');
        style.id = 'mlx-energy-styles';
        style.textContent = [
            '.mlx-energy{margin:18px 0;padding:20px;border:1px solid #334155;',
            'border-radius:14px;background:#101b2c;color:#e2e8f0}',
            '.mlx-energy h3{margin:0;font-size:18px;font-weight:700}',
            '.mlx-energy-header{display:flex;align-items:center;justify-content:space-between;gap:10px}',
            '.mlx-energy button{padding:6px 12px;border:1px solid #475569;',
            'border-radius:8px;color:#e2e8f0;background:transparent;cursor:pointer}',
            '.mlx-energy-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));',
            'gap:10px;margin:16px 0}',
            '.mlx-energy-stat{padding:12px;background:#1e293b;border-radius:10px;display:grid;gap:5px}',
            '.mlx-energy-stat span{font-size:12px;color:#94a3b8}',
            '.mlx-energy-stat strong{font-size:18px;font-variant-numeric:tabular-nums}',
            '.mlx-energy-bars{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));',
            'gap:7px;height:120px;margin:12px 0 6px}',
            '.mlx-energy-column{min-width:0;display:flex;flex-direction:column;align-items:center;gap:5px}',
            '.mlx-energy-bar-shell{flex:1;width:100%;background:#1e293b;border-radius:6px;',
            'display:flex;align-items:end;overflow:hidden}',
            '.mlx-energy-bar{width:100%;min-height:0;background:#38bdf8;border-radius:6px 6px 0 0}',
            '.mlx-energy-column small{font-size:11px;color:#94a3b8}',
            '.mlx-energy-hour{display:grid;grid-template-columns:45px 1fr 65px;align-items:center;',
            'gap:9px;margin:7px 0;font-size:12px;font-variant-numeric:tabular-nums}',
            '.mlx-energy-hour-track{background:#1e293b;height:8px;border-radius:10px;overflow:hidden}',
            '.mlx-energy-hour-progress{height:100%;background:#38bdf8;border-radius:10px}',
            '.mlx-energy-hour small{text-align:right;color:#94a3b8}',
            '.mlx-energy-muted,.mlx-energy-details{color:#94a3b8;font-size:12px;line-height:1.5}',
            '.mlx-energy-note{border-top:1px solid #334155;padding-top:10px;margin-top:16px}'
        ].join('');
        document.head.append(style);
    }

    function mount() {
        if (root) return true;
        const anchor = document.getElementById('systemHealthV1');
        if (!anchor) return false;
        addCss();
        root = node('section', 'mlx-energy');
        root.id = 'mlxEnergyMonitor';
        const header = node('div', 'mlx-energy-header');
        header.append(node('h3', '', tr('Energie · Apple Silicon', 'Energy · Apple Silicon')));
        const button = node('button', '', tr('Aktualisieren', 'Refresh'));
        button.type = 'button';
        button.addEventListener('click', refresh);
        header.append(button);
        const status = node('p', 'mlx-energy-muted', tr('Lade Messwerte …', 'Loading …'));
        status.dataset.energyStatus = '1';
        const stats = node('div', 'mlx-energy-stat-grid');
        stats.dataset.energyStats = '1';
        const subheading = node('h4', '', tr('Letzte 7 Tage', 'Last 7 days'));
        const days = node('div', 'mlx-energy-bars');
        days.dataset.energyDays = '1';
        const hoursHeading = node('h4', '', tr('Letzte erfasste Stunden', 'Recent measured hours'));
        const hours = node('div');
        hours.dataset.energyHours = '1';
        const details = node('p', 'mlx-energy-details');
        details.dataset.energyDetails = '1';
        const note = node('p', 'mlx-energy-muted mlx-energy-note',
            tr('Interne Systemleistung (macmon sys_power), kein Steckdosenverbrauch. ' +
               'CPU/GPU sind darin bereits enthalten. Nur gemessene Zeiträume werden gezählt.',
               'Internal macmon system power, not wall power. CPU/GPU already included. ' +
               'Only measured intervals are counted.'));
        root.append(header, status, stats, subheading, days, hoursHeading, hours, details, note);
        anchor.insertAdjacentElement('afterend', root);
        timer = setInterval(refresh, REFRESH_MS);
        document.addEventListener('visibilitychange', refresh);
        refresh();
        return true;
    }

    function boot() {
        if (mount()) return;
        if (typeof MutationObserver !== 'function') return;
        mountObserver = new MutationObserver(() => {
            if (mount()) {
                mountObserver.disconnect();
                mountObserver = null;
            }
        });
        mountObserver.observe(document.body, {childList: true, subtree: true});
    }

    window.MLXEnergyMonitor = {refresh};
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot, {once: true});
    } else {
        boot();
    }
    window.addEventListener('beforeunload', () => {
        if (timer != null) clearInterval(timer);
        mountObserver?.disconnect();
        document.removeEventListener('visibilitychange', refresh);
    });
})();
