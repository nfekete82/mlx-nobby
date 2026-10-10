/* Reflect persistent sidebar actions in the collapsed desktop icon rail. */
(() => {
  'use strict';
  function install() {
    const rail = document.querySelector('.sidebar-rail');
    const bottom = document.querySelector('.sidebar-bottom');
    if (!rail || !bottom || rail.dataset.utilityMirrorInstalled) return;
    rail.dataset.utilityMirrorInstalled = 'true';

    // Existing rail functions keep their established behavior and handlers.
    const spacer = rail.querySelector('.rail-spacer');
    const jobs = document.getElementById('railJobs');
    const settings = document.getElementById('railSettings');
    if (spacer && jobs) spacer.after(jobs);
    if (settings) rail.appendChild(settings);

    const utilities = [
      ['talkingPhotoButton', 'railTalkingPhoto', 'Talking Photo'],
      ['mlxSidebarHelpButton', 'railHelp', 'Hilfe'],
      ['mlx-shorts-history-launcher', 'railShorts', 'Shorts'],
      ['runtimeInfoButton', 'railRuntimeInfo', 'Systeminfo']
    ];
    const findSource = key => key === 'mlx-shorts-history-launcher'
      ? bottom.querySelector('.mlx-shorts-history-launcher')
      : document.getElementById(key);

    function sync() {
      for (const [sourceId, railId, label] of utilities) {
        const source = findSource(sourceId);
        let button = document.getElementById(railId);
        if (!source) {
          if (button) button.remove();
          continue;
        }
        if (!button) {
          button = document.createElement('button');
          button.id = railId;
          button.type = 'button';
          button.className = 'rail-button';
          button.addEventListener('click', () => {
            const target = findSource(sourceId);
            if (target && !target.disabled) target.click();
          });
        }
        button.title = label;
        button.setAttribute('aria-label', label);
        const icon = source.querySelector('svg');
        if (icon) {
          button.replaceChildren(icon.cloneNode(true));
        } else {
          button.textContent = label.charAt(0);
        }
        rail.insertBefore(button, settings || null);
      }
    }
    sync();
    // Help, Shorts and Talking Photo insert controls after initial page load.
    const observer = new MutationObserver(sync);
    observer.observe(bottom, {childList:true});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once:true});
  } else install();
})();
