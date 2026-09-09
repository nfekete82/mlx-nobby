(function () {
    // Download-/Jobstatus wird direkt am jeweiligen Modell dargestellt.
    async function loadJobs() {
        if (window.MLXModels?.loadModels) return window.MLXModels.loadModels();
    }
    window.MLXJobs = { loadJobs };
})();
