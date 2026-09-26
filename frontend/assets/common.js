(function () {
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

    function loadChatVoiceControls() {
        if (!document.getElementById('input')) return;
        if (!document.querySelector('script[data-mlx-voice-controls]')) {
            const script = document.createElement('script');
            script.src = '/assets/chat/voice.js?v=20260926-voice-popover';
            script.dataset.mlxVoiceControls = '1';
            script.defer = true;
            document.head.appendChild(script);
        }

        if (!document.querySelector('script[data-mlx-user-voice-controls]')) {
            const script = document.createElement('script');
            script.src = '/assets/chat/user-voice.js?v=20260926-user-voice';
            script.dataset.mlxUserVoiceControls = '1';
            script.defer = true;
            document.head.appendChild(script);
        }
    }

    window.MLXCommon = {
        fetchJson: fetchJson,
        fastApiDetailError: fastApiDetailError,
        jsonRequest: jsonRequest
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadChatVoiceControls, { once: true });
    } else {
        loadChatVoiceControls();
    }
})();
