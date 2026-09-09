(function () {
    // Download-/Jobstatus wird direkt am jeweiligen Modell dargestellt.
    async function loadJobs() {
        if (window.MLXModels?.loadModels) return window.MLXModels.loadModels();
    }
    window.MLXJobs = { loadJobs };
    window.MLXHistoryCleanup?.mount(document.getElementById('downloadHistoryCleanup'), {
        kind: 'downloads', onComplete: loadJobs,
        buttonClass: 'text-red-300 bg-slate-800 hover:bg-red-950 rounded-lg px-3 py-2 text-xs disabled:opacity-40',
    });
})();
