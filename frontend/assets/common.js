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

    window.MLXCommon = {
        fetchJson: fetchJson,
        fastApiDetailError: fastApiDetailError,
        jsonRequest: jsonRequest
    };
})();
