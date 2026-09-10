(function () {
    // Cache data is now part of the shared model library.
    async function loadCache() {
        if (window.MLXModels?.loadModels) return window.MLXModels.loadModels();
    }
    window.MLXCache = { loadCache };
})();
