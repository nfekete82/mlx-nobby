/* Keep the active chat mounted behind the converter glass modal. */
(() => {
  'use strict';

  function install() {
    const button = document.getElementById('imageConverterButton');
    const panel = document.getElementById('imageConverterWorkspace');
    const frame = document.getElementById('imageConverterFrame');
    const back = document.getElementById('imageConverterBack');
    const backdrop = document.getElementById('imageConverterBackdrop');
    if (!button || !panel || !frame || !back || !backdrop) return;

    // Mount directly under <body>: the chat grid is a separate stacking context.
    // A z-index on a modal nested inside .main cannot overtake the composer.
    document.body.appendChild(panel);
    const backgroundLayers = [document.querySelector('.app'), document.querySelector('.composer-wrap')]
      .filter(Boolean);
    const originalInert = backgroundLayers.map(element => element.inert);

    const selectedLanguage = () =>
      window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    const forwardLanguage = language => {
      frame.contentWindow?.postMessage({
        type: 'mlx-image-converter-language',
        language: language === 'de' ? 'de' : 'en'
      }, location.origin);
    };
    frame.addEventListener('load', () => forwardLanguage(selectedLanguage()));
    document.addEventListener('mlx-language-changed', event => {
      if (frame.getAttribute('src')) forwardLanguage(event.detail?.language);
    });

    let active = false;
    let previousFocus = null;
    const open = () => {
      if (active) return;
      active = true;
      previousFocus = document.activeElement;
      if (!frame.getAttribute('src')) {
        frame.setAttribute('src', '/converter?embedded=1&lang=' + selectedLanguage());
      } else {
        forwardLanguage(selectedLanguage());
      }
      panel.hidden = false;
      panel.setAttribute('aria-hidden', 'false');
      document.body.classList.add('mlx-image-converter-open');
      backgroundLayers.forEach(element => { element.inert = true; });
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
      panel.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('mlx-image-converter-open');
      backgroundLayers.forEach((element, index) => { element.inert = originalInert[index]; });
      button.classList.remove('active');
      button.setAttribute('aria-pressed', 'false');
      document.getElementById('railImageConverter')?.setAttribute('aria-pressed', 'false');
      if (restoreFocus && previousFocus?.isConnected) previousFocus.focus();
      previousFocus = null;
    };
    button.setAttribute('aria-controls', panel.id);
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => active ? close(true) : open());
    back.addEventListener('click', () => close(true));
    backdrop.addEventListener('click', () => close(true));

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
      if (!active) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        close(true);
      } else if (event.key === 'Tab' && document.activeElement === back && event.shiftKey) {
        // Keep keyboard navigation in the modal, not in the background chat.
        event.preventDefault();
        frame.focus();
      }
    });
    // Escape pressed inside a same-origin converter iframe cannot bubble to the parent.
    window.addEventListener('message', event => {
      if (active && event.origin === location.origin &&
          event.source === frame.contentWindow &&
          event.data?.type === 'mlx-image-converter-close') close(true);
    });
    window.MLXImageConverterWorkspace = Object.freeze({open, close, isOpen: () => active});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once: true});
  } else {
    install();
  }
})();
