(function () {
    'use strict';

    let timer = null;
    let requestId = 0;
    let observedForm = null;

    function isGerman() {
        const locale = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(locale).toLowerCase().startsWith('de');
    }

    function t(de, en) {
        return isGerman() ? de : en;
    }

    function injectStyles() {
        if (document.getElementById('modelPathValidationStyles')) return;
        const style = document.createElement('style');
        style.id = 'modelPathValidationStyles';
        style.textContent = `
            .model-path-validation {
                margin-top: 10px;
                padding: 11px 12px;
                border: 1px solid #2b3444;
                border-radius: 10px;
                background: rgba(10, 14, 21, .52);
                font-size: 11px;
            }
            .model-path-validation[hidden] { display: none !important; }
            .model-path-validation-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-bottom: 8px;
            }
            .model-path-validation-head strong { font-size: 11px; }
            .model-path-validation-state {
                color: #94a3b8;
                font-size: 10px;
                font-weight: 700;
            }
            .model-path-validation-state.ok { color: #76deb7; }
            .model-path-validation-state.error { color: #f2a0a0; }
            .model-path-validation-checks {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 5px 12px;
            }
            .model-path-validation-check {
                display: flex;
                align-items: center;
                gap: 7px;
                min-width: 0;
                color: #9ca9ba;
            }
            .model-path-validation-check.ok { color: #b9c6d6; }
            .model-path-validation-check.bad { color: #e6a2a2; }
            .model-path-validation-icon {
                width: 14px;
                flex: 0 0 14px;
                text-align: center;
                font-weight: 800;
            }
            .model-path-validation-check.ok .model-path-validation-icon { color: #55d6a4; }
            .model-path-validation-check.bad .model-path-validation-icon { color: #ef8e8e; }
            .model-path-validation-detected {
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
                margin-top: 9px;
                padding-top: 9px;
                border-top: 1px solid #252e3d;
            }
            .model-path-validation-chip {
                padding: 3px 7px;
                border: 1px solid #30394a;
                border-radius: 999px;
                color: #b7c1cf;
                background: rgba(24, 31, 43, .68);
                font-size: 9px;
                font-weight: 700;
            }
            .model-path-validation-error {
                margin-top: 8px;
                color: #e6a2a2;
                line-height: 1.4;
            }
            @media (max-width: 620px) {
                .model-path-validation-checks { grid-template-columns: 1fr; }
            }
        `;
        document.head.appendChild(style);
    }

    function isLocalPath(value) {
        const path = String(value || '').trim();
        return path.startsWith('/') || path.startsWith('~/');
    }

    function formatSize(bytes) {
        const value = Number(bytes);
        if (!Number.isFinite(value) || value <= 0) return null;
        const gb = value / (1024 ** 3);
        return gb >= 1 ? `${gb.toFixed(gb >= 10 ? 1 : 2)} GB` : `${Math.round(value / (1024 ** 2))} MB`;
    }

    function submitButton() {
        return document.querySelector('#modelConsoleDialogActions [data-action="submit-model"]');
    }

    function panelFor(input) {
        let panel = document.getElementById('modelPathValidation');
        if (panel) return panel;
        panel = document.createElement('div');
        panel.id = 'modelPathValidation';
        panel.className = 'model-path-validation';
        panel.hidden = true;
        const error = document.getElementById('modelAddRepoError');
        (error || input).insertAdjacentElement('afterend', panel);
        return panel;
    }

    function resetPanel(input) {
        const panel = panelFor(input);
        panel.hidden = true;
        panel.innerHTML = '';
        const submit = submitButton();
        if (submit) submit.disabled = false;
    }

    function renderLoading(input) {
        const panel = panelFor(input);
        panel.hidden = false;
        panel.innerHTML = `
            <div class="model-path-validation-head">
                <strong>${t('Lokales Modell prüfen', 'Validate local model')}</strong>
                <span class="model-path-validation-state">${t('Prüfe …', 'Checking …')}</span>
            </div>
        `;
        const submit = submitButton();
        if (submit) submit.disabled = true;
    }

    function renderResult(input, result) {
        const panel = panelFor(input);
        panel.hidden = false;
        panel.innerHTML = '';

        const head = document.createElement('div');
        head.className = 'model-path-validation-head';
        const title = document.createElement('strong');
        title.textContent = t('Lokales Modell geprüft', 'Local model checked');
        const state = document.createElement('span');
        state.className = 'model-path-validation-state ' + (result.valid ? 'ok' : 'error');
        state.textContent = result.valid ? t('✓ Bereit', '✓ Ready') : t('✕ Nicht verwendbar', '✕ Not usable');
        head.append(title, state);
        panel.appendChild(head);

        const checks = document.createElement('div');
        checks.className = 'model-path-validation-checks';
        (result.checks || []).forEach(check => {
            const row = document.createElement('div');
            row.className = 'model-path-validation-check ' + (check.ok ? 'ok' : 'bad');
            const icon = document.createElement('span');
            icon.className = 'model-path-validation-icon';
            icon.textContent = check.ok ? '✓' : '✕';
            const label = document.createElement('span');
            label.textContent = check.label || check.key;
            row.append(icon, label);
            checks.appendChild(row);
        });
        panel.appendChild(checks);

        const detected = result.detected || {};
        const chips = [
            detected.model_type,
            detected.backend ? detected.backend.toUpperCase() : null,
            detected.vision ? 'Vision' : null,
            detected.quantization,
            detected.weight_files ? `${detected.weight_files} safetensors` : null,
            formatSize(detected.size_bytes),
        ].filter(Boolean);
        if (chips.length) {
            const detectedRow = document.createElement('div');
            detectedRow.className = 'model-path-validation-detected';
            chips.forEach(value => {
                const chip = document.createElement('span');
                chip.className = 'model-path-validation-chip';
                chip.textContent = value;
                detectedRow.appendChild(chip);
            });
            panel.appendChild(detectedRow);
        }

        if (Array.isArray(result.errors) && result.errors.length) {
            const errors = document.createElement('div');
            errors.className = 'model-path-validation-error';
            errors.textContent = result.errors.join(' · ');
            panel.appendChild(errors);
        }

        const submit = submitButton();
        if (submit) submit.disabled = !result.valid;
    }

    async function validate(input) {
        const value = input.value.trim();
        if (!isLocalPath(value)) {
            resetPanel(input);
            return;
        }

        const current = ++requestId;
        renderLoading(input);
        try {
            const response = await fetch('/api/models/validate-local', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: value }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const result = await response.json();
            if (current !== requestId || input.value.trim() !== value) return;
            renderResult(input, result);
        } catch (error) {
            if (current !== requestId) return;
            renderResult(input, {
                valid: false,
                checks: [],
                errors: [t('Modellprüfung nicht möglich.', 'Model validation failed.') + ` ${error.message}`],
            });
        }
    }

    function schedule(input, delay = 350) {
        clearTimeout(timer);
        timer = setTimeout(() => validate(input), delay);
    }

    function bindForm() {
        const input = document.getElementById('modelAddRepo');
        if (!input || input === observedForm) return;
        observedForm = input;
        input.addEventListener('input', () => schedule(input));
        input.addEventListener('change', () => schedule(input, 0));
        input.addEventListener('blur', () => schedule(input, 0));
        if (input.value.trim()) schedule(input, 0);
    }

    function init() {
        injectStyles();
        const dialog = document.getElementById('modelConsoleDialog');
        if (!dialog) {
            setTimeout(init, 250);
            return;
        }
        new MutationObserver(bindForm).observe(dialog, { childList: true, subtree: true });
        bindForm();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
