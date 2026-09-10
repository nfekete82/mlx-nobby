(function () {
    // Cache ist jetzt Bestandteil der gemeinsamen Modellbibliothek.
    async function loadCache() {
        if (window.MLXModels?.loadModels) return window.MLXModels.loadModels();
    }
    window.MLXCache = { loadCache };
})();
