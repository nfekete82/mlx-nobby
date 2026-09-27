(function () {
    'use strict';

    if (window.__mlxRuntimeBudgetLoaded) return;
    window.__mlxRuntimeBudgetLoaded = true;

    const REFRESH_MS = 3000;
    const ELEVATED_FREE_PERCENT = 18;
    const CRITICAL_FREE_PERCENT = 8;
    let refreshTimer = null;
    let refreshing = false;

    function language() {
        return window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    }

    function t(german, english) {
        return language() === 'de' ? german : english;
    }

    function finite(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    }

    function formatGb(value) {
        const number = finite(value);
        if (number === null) return '–';
        return number.toLocaleString(language() === 'de' ? 'de-DE' : 'en-US', {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
        }) + ' GB';
    }

    function computeBudget(systemData) {
        const system = systemData?.system || {};
        const totalGb = finite(system.total_gb);
        const freePercent = finite(system.free_percent);
        const availableGb = (
            totalGb !== null && freePercent !== null
                ? totalGb * Math.max(0, Math.min(100, freePercent)) / 100
                : null
        );
        const usedGb = (
            totalGb !== null && availableGb !== null
                ? Math.max(0, totalGb - availableGb)
                : null
        );
        const usedPercent = (
            freePercent !== null
                ? Math.max(0, Math.min(100, 100 - freePercent))
                : null
        );
        let pressure = 'unknown';
        if (freePercent !== null) {
            pressure = freePercent <= CRITICAL_FREE_PERCENT
                ? 'critical'
                : freePercent <= ELEVATED_FREE_PERCENT
                    ? 'elevated'
                    : 'normal';
        }

        return {
            totalGb,
            freePercent,
            availableGb,
            usedGb,
            usedPercent,
            swapUsedGb: finite(system.swap_used_gb),
            mlxGb: finite(systemData?.mlx?.memory_mb) !== null
                ? finite(systemData.mlx.memory_mb) / 1024
                : null,
            pressure
        };
    }

    function pressureCopy(pressure) {
        if (pressure === 'critical') {
            return {
                label: t('Kritisch', 'Critical'),
                hint: t('Sehr wenig freier Unified Memory. Schwere Jobs werden seriell ausgeführt und vorhandene Runtimes freigegeben.', 'Very little unified memory is free. Heavy jobs are serialized and existing runtimes are released.')
            };
        }
        if (pressure === 'elevated') {
            return {
                label: t('Erhöht', 'Elevated'),
                hint: t('Der Speicher wird knapp. MLX nobby hält schwere Media-Runtimes voneinander getrennt.', 'Memory is getting tight. MLX nobby keeps heavy media runtimes separated.')
            };
        }
        if (pressure === 'normal') {
            return {
                label: t('Normal', 'Normal'),
                hint: t('Genügend Speicherreserve für den normalen Betrieb.', 'Enough memory headroom for normal operation.')
            };
        }
        return {
            label: t('Unbekannt', 'Unknown'),
            hint: t('macOS-Speicherdruck konnte nicht ermittelt werden.', 'macOS memory pressure could not be determined.')
        };
    }

    function injectStyles() {
        if (document.getElementById('mlxRuntimeBudgetStyles')) return;
        const style = document.createElement('style');
        style.id = 'mlxRuntimeBudgetStyles';
        style.textContent = `
            #mlxRuntimeBudget{margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}
            .runtime-budget-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
            .runtime-budget-title{color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
            .runtime-budget-pressure{font-size:10px;font-weight:700;padding:3px 7px;border:1px solid var(--border);border-radius:999px;color:var(--muted)}
            .runtime-budget-pressure[data-pressure="normal"]{color:var(--green)}
            .runtime-budget-pressure[data-pressure="elevated"]{color:#e0a84f}
            .runtime-budget-pressure[data-pressure="critical"]{color:var(--red)}
            .runtime-budget-meter{height:8px;margin:8px 0 9px;overflow:hidden;border-radius:999px;background:rgba(127,140,160,.16)}
            .runtime-budget-fill{height:100%;width:0;border-radius:inherit;background:var(--green);transition:width .2s ease}
            .runtime-budget-fill[data-pressure="elevated"]{background:#e0a84f}
            .runtime-budget-fill[data-pressure="critical"]{background:var(--red)}
            .runtime-budget-grid{display:grid;grid-template-columns:1fr auto;gap:5px 12px;color:var(--muted);font-size:12px}
            .runtime-budget-grid strong{color:var(--text);font-weight:600;text-align:right}
            .runtime-budget-hint{margin-top:9px;color:var(--muted);font-size:10px;line-height:1.45}
        `;
        document.head.appendChild(style);
    }

    function ensureSection() {
        const popover = document.getElementById('runtimePopover');
        const content = document.getElementById('runtimeInfoContent');
        if (!popover || !content) return null;

        let section = document.getElementById('mlxRuntimeBudget');
        if (section) return section;

        section = document.createElement('section');
        section.id = 'mlxRuntimeBudget';
        section.setAttribute('aria-live', 'polite');
        content.insertAdjacentElement('afterend', section);
        return section;
    }

    function render(section, budget) {
        const pressure = pressureCopy(budget.pressure);
        const usedLabel = (
            budget.usedGb !== null && budget.totalGb !== null
                ? `${formatGb(budget.usedGb)} / ${formatGb(budget.totalGb)}`
                : '–'
        );
        const usedPercent = budget.usedPercent ?? 0;
        const freeLabel = budget.availableGb !== null
            ? formatGb(budget.availableGb)
            : '–';
        const mlxLabel = budget.mlxGb !== null ? formatGb(budget.mlxGb) : '–';
        const swapLabel = budget.swapUsedGb !== null ? formatGb(budget.swapUsedGb) : '–';

        section.innerHTML = `
            <div class="runtime-budget-head">
                <div class="runtime-budget-title">${t('Unified Memory', 'Unified memory')}</div>
                <div class="runtime-budget-pressure" data-pressure="${budget.pressure}">${pressure.label}</div>
            </div>
            <div class="runtime-budget-meter" title="${usedLabel}">
                <div class="runtime-budget-fill" data-pressure="${budget.pressure}" style="width:${usedPercent}%"></div>
            </div>
            <div class="runtime-budget-grid">
                <span>${t('Belegt (Schätzung)', 'Used (estimate)')}</span><strong>${usedLabel}</strong>
                <span>${t('Verfügbar (Schätzung)', 'Available (estimate)')}</span><strong>${freeLabel}</strong>
                <span>${t('Chat-Runtime', 'Chat runtime')}</span><strong>${mlxLabel}</strong>
                <span>Swap</span><strong>${swapLabel}</strong>
            </div>
            <div class="runtime-budget-hint">${pressure.hint}</div>
        `;
    }

    async function refresh() {
        const popover = document.getElementById('runtimePopover');
        if (!popover || popover.hidden || refreshing) return;
        const section = ensureSection();
        if (!section) return;

        refreshing = true;
        try {
            const response = await fetch('/api/mlx/system', { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            render(section, computeBudget(data));
        } catch (error) {
            section.innerHTML = `
                <div class="runtime-budget-title">${t('Unified Memory', 'Unified memory')}</div>
                <div class="runtime-budget-hint">${t('Speicherinformationen sind momentan nicht verfügbar.', 'Memory information is currently unavailable.')}</div>
            `;
        } finally {
            refreshing = false;
        }
    }

    function start() {
        injectStyles();
        ensureSection();

        const button = document.getElementById('runtimeInfoButton');
        if (button) {
            button.addEventListener('click', () => {
                window.setTimeout(refresh, 0);
            });
        }

        document.addEventListener('mlx-language-changed', refresh);
        document.addEventListener('mlx-i18n-ready', refresh);

        if (refreshTimer !== null) clearInterval(refreshTimer);
        refreshTimer = window.setInterval(refresh, REFRESH_MS);
    }

    window.MLXRuntimeBudget = {
        refresh,
        computeBudget
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
