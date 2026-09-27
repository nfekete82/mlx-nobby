(function () {
    const commonScript = document.currentScript;
    const commonScriptUrl = commonScript?.src
        ? new URL(commonScript.src, window.location.href)
        : null;
    const frontendBuildRevision = commonScriptUrl?.searchParams.get('v') || '';

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();

        return {
            response: response,
            data: data
        };
    }

    function fastApiDetailError(data) {
        return new Error(
            typeof data.detail === 'string'
                ? data.detail
                : JSON.stringify(data.detail)
        );
    }

    function jsonRequest(method, data) {
        return {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        };
    }

    function versionedAssetUrl(src) {
        if (!frontendBuildRevision) return src;

        const url = new URL(src, window.location.href);
        url.searchParams.set('build', frontendBuildRevision);
        return `${url.pathname}${url.search}${url.hash}`;
    }

    function loadScript(src, datasetKey) {
        return new Promise((resolve, reject) => {
            const selector = `script[data-${datasetKey}]`;
            const existing = document.querySelector(selector);
            if (existing) {
                if (existing.dataset.loaded === '1') {
                    resolve();
                } else {
                    existing.addEventListener('load', resolve, { once: true });
                    existing.addEventListener('error', reject, { once: true });
                }
                return;
            }

            const script = document.createElement('script');
            script.src = versionedAssetUrl(src);
            script.setAttribute(`data-${datasetKey}`, '1');
            script.addEventListener('load', () => {
                script.dataset.loaded = '1';
                resolve();
            }, { once: true });
            script.addEventListener('error', reject, { once: true });
            document.head.appendChild(script);
        });
    }

    function ensureHelpVisibilityFix() {
        if (document.getElementById('mlxHelpVisibilityFix')) return;

        const style = document.createElement('style');
        style.id = 'mlxHelpVisibilityFix';
        style.textContent = [
            '.mlx-help-backdrop[hidden],',
            '.mlx-help-panel[hidden]{display:none!important;}'
        ].join('');
        document.head.appendChild(style);
    }

    function ensureTopbarActionCleanup() {
        if (document.getElementById('mlxTopbarActionCleanup')) return;

        const style = document.createElement('style');
        style.id = 'mlxTopbarActionCleanup';
        style.textContent = '#settingsButton,#mlxHelpButton{display:none!important;}';
        document.head.appendChild(style);
    }

    function removeRedundantTopActions() {
        document.getElementById('settingsButton')?.remove();
        document.getElementById('mlxHelpButton')?.remove();
    }

    async function loadChatVoiceControls() {
        if (!document.getElementById('input')) return;
        try {
            await loadScript(
                '/assets/chat/voice.js?v=20260926-voice-popover-2',
                'mlx-voice-controls'
            );
            await loadScript(
                '/assets/chat/tts-cache.js?v=20260926-tts-cache',
                'mlx-tts-cache'
            );
            await loadScript(
                '/assets/chat/user-voice.js?v=20260926-user-voice-2',
                'mlx-user-voice-controls'
            );
        } catch (error) {
            console.error('[voice] Failed to load voice controls:', error);
        }
    }

    async function loadModelConsoleEnhancers() {
        if (!document.getElementById('modelConsoleContent')) return;
        try {
            await loadScript(
                '/assets/chat/model-overview.js?v=20260927-overview-v1',
                'model-overview-enhancer'
            );
            await loadScript(
                '/assets/chat/model-path-validation.js?v=20260927-validation-v2',
                'model-path-validator'
            );
        } catch (error) {
            console.error('[models] Failed to load model console enhancements:', error);
        }
    }

    async function loadHelpCenter() {
        if (!document.getElementById('input')) return;
        try {
            ensureHelpVisibilityFix();
            await loadScript(
                '/assets/chat/help.js?v=20260927-help-v1',
                'mlx-help-center'
            );
            removeRedundantTopActions();
        } catch (error) {
            console.error('[help] Failed to load help center:', error);
        }
    }

    async function loadRuntimeBudget() {
        if (!document.getElementById('runtimeInfoButton')) return;
        try {
            await loadScript(
                '/assets/chat/runtime-budget.js?v=20260927-runtime-budget-v1',
                'mlx-runtime-budget'
            );
        } catch (error) {
            console.error('[runtime-budget] Failed to load runtime budget:', error);
        }
    }

    async function loadJobQueue() {
        if (!document.getElementById('jobsPanel')) return;
        try {
            await loadScript(
                '/assets/chat/job-queue.js?v=20260927-unified-queue-v1',
                'mlx-unified-job-queue'
            );
        } catch (error) {
            console.error('[job-queue] Failed to load unified job queue:', error);
        }
    }

    function loadChatEnhancements() {
        removeRedundantTopActions();
        loadChatVoiceControls();
        loadModelConsoleEnhancers();
        loadHelpCenter();
        loadRuntimeBudget();
        loadJobQueue();
    }

    window.MLXCommon = {
        fetchJson: fetchJson,
        fastApiDetailError: fastApiDetailError,
        jsonRequest: jsonRequest
    };

    ensureTopbarActionCleanup();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadChatEnhancements, { once: true });
    } else {
        loadChatEnhancements();
    }
})();
