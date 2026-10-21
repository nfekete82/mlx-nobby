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

    // Collect Files & Jobs, Help, System Info, and Settings into one expandable group.
    // Help is inserted asynchronously; move its existing button instead of
    // cloning it, so all original click handlers remain attached.
    const group = document.createElement('details');
    group.className = 'sidebar-system-tools';
    group.id = 'sidebarSystemTools';
    const summary = document.createElement('summary');
    summary.className = 'sidebar-action';
    summary.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h8M8 17h5"/></svg><span class="sidebar-action-label">System &amp; Tools</span><span class="sidebar-system-chevron" aria-hidden="true">⌄</span>';
    const items = document.createElement('div');
    items.className = 'sidebar-system-tools-items';
    group.append(summary, items);
    const runtimeLabel = bottom.querySelector('.sidebar-runtime');
    bottom.insertBefore(group, runtimeLabel || null);

    function syncSystemTools() {
      for (const id of ['sidebarConverterLink', 'sidebarJobsButton', 'mlxSidebarHelpButton', 'runtimeInfoButton', 'sidebarSettingsButton']) {
        const button = document.getElementById(id);
        if (button && button.parentElement !== items) items.appendChild(button);
      }
    }
    syncSystemTools();

    const utilities = [
      ['sidebarConverterLink', 'railConverter', 'Dateikonverter'],
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
        // Other layout scripts may move railSettings after this module starts.
        // insertBefore requires the reference to be a current direct child.
        const anchor = settings?.parentNode === rail ? settings : null;
        rail.insertBefore(button, anchor);
      }
    }
    sync();
    // Help, Shorts and Talking Photo insert controls after initial page load.
    const observer = new MutationObserver(() => {
      syncSystemTools();
      sync();
    });
    observer.observe(bottom, {childList:true, subtree:true});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once:true});
  } else install();
})();
