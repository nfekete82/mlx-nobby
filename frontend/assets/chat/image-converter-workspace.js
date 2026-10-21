/* Keep the existing chat session alive while showing the local converter inline. */
(() => {
  'use strict';

  function install() {
    const button = document.getElementById('imageConverterButton');
    const panel = document.getElementById('imageConverterWorkspace');
    const frame = document.getElementById('imageConverterFrame');
    const back = document.getElementById('imageConverterBack');
    if (!button || !panel || !frame || !back) return;

    let active = false;
    const open = () => {
      if (active) return;
      active = true;
      if (!frame.getAttribute('src')) frame.setAttribute('src', '/converter?embedded=1');
      panel.hidden = false;
      document.body.classList.add('mlx-image-converter-open');
      button.classList.add('active');
      button.setAttribute('aria-pressed', 'true');
      document.getElementById('railImageConverter')?.setAttribute('aria-pressed', 'true');
      document.querySelector('.sidebar.mobile-open')?.classList.remove('mobile-open');
      back.focus();
    };
    const close = (restoreFocus = false) => {
      if (!active) return;
      active = false;
      panel.hidden = true;
      document.body.classList.remove('mlx-image-converter-open');
      button.classList.remove('active');
      button.setAttribute('aria-pressed', 'false');
      document.getElementById('railImageConverter')?.setAttribute('aria-pressed', 'false');
      if (restoreFocus) button.focus();
    };
    button.setAttribute('aria-controls', panel.id);
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => active ? close(true) : open());
    back.addEventListener('click', () => close(true));

    // Switching to another sidebar workspace restores the existing chat view.
    // Do not create/delete chat sessions or interfere with running generations.
    const destinations = [
      '#newChat', '#recentNewChat', '#railNewChat', '#railChats',
      '#chatList', '#sidebarLibraryButton', '#railLibrary',
      '#sidebarJobsButton', '#railJobs', '#sidebarSettingsButton', '#railSettings',
      '#talkingPhotoButton', '#railTalkingPhoto',
      '.mlx-shorts-history-launcher', '#railShorts',
      '#sidebarWorkspaceList', '#sidebarWorkspaceAdd'
    ].join(', ');
    document.addEventListener('click', event => {
      if (active && event.target.closest?.(destinations)) close();
    }, true);
    document.addEventListener('keydown', event => {
      if (active && event.key === 'Escape' && event.target !== frame) close(true);
    });
    window.MLXImageConverterWorkspace = Object.freeze({open, close, isOpen: () => active});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once: true});
  } else {
    install();
  }
})();
