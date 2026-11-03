/* Local-only media privacy mode: never changes generated files or API URLs. */
(() => {
    'use strict';
    if (window.MLXMediaPrivacy) return;

    const KEY = 'mlx.mediaPrivacy.enabled.v1';
    const FLAG = 'mlx-media-privacy-on';
    const SELECTOR = [
        '.message-attachment-preview',
        '.image-artifact-preview',
        '.video-artifact-player',
        '.image-variant-preview',
        '.nobby-library-media > img',
        '.nobby-library-preview-body > img',
        '.nobby-library-preview-body > video',
        '.image-preview-dialog img',
        '.image-compare-stage img',
        '.multi-image-video-preview img',
        '.multi-image-video-preview video',
        '.shorts-preview video'
    ].join(', ');

    function stored() {
        try { return localStorage.getItem(KEY) === '1'; }
        catch (_) { return false; }
    }

    // Run synchronously in <head> so existing thumbnails never flash unblurred.
    let enabled = stored();
    document.documentElement.classList.toggle(FLAG, enabled);

    function label(key, fallback) {
        return window.MLXI18n?.t('ui.' + key, fallback) ?? fallback;
    }

    function setEnabled(next) {
        enabled = !!next;
        document.documentElement.classList.toggle(FLAG, enabled);
        try { localStorage.setItem(KEY, enabled ? '1' : '0'); }
        catch (_) { /* Storage may be unavailable in private browsing. */ }
        if (!enabled) {
            document.querySelectorAll('.mlx-media-tap-revealed').forEach(node =>
                node.classList.remove('mlx-media-tap-revealed'));
        }
        syncControls();
    }

    function syncControls() {
        const setting = document.getElementById('mediaPrivacyToggle');
        const quick = document.getElementById('mediaPrivacyQuickToggle');
        if (setting) setting.checked = enabled;
        if (quick) {
            quick.setAttribute('aria-pressed', String(enabled));
            quick.classList.toggle('is-active', enabled);
            const title = enabled
                ? label('media_privacy_disable', 'Disable private media previews')
                : label('media_privacy_enable', 'Blur private media previews');
            quick.setAttribute('aria-label', title);
            quick.title = title;
        }
    }

    // Pointer events from touch devices do not reliably support :hover.
    // The FIRST tap only reveals the selected item, a subsequent tap can
    // open the preview or use video controls. Other items remain blurred.
    let firstTap = null;
    document.addEventListener('pointerdown', event => {
        firstTap = null;
        if (!enabled || event.pointerType !== 'touch') return;
        const media = event.target.closest?.(SELECTOR);
        if (!media || media.classList.contains('mlx-media-tap-revealed')) return;
        firstTap = media;
    }, true);

    document.addEventListener('click', event => {
        if (!enabled) return;
        if (firstTap && (event.target === firstTap || firstTap.contains(event.target))) {
            firstTap.classList.add('mlx-media-tap-revealed');
            firstTap = null;
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        firstTap = null;
        const clickedMedia = event.target.closest?.(SELECTOR);
        if (!clickedMedia) {
            document.querySelectorAll('.mlx-media-tap-revealed').forEach(node =>
                node.classList.remove('mlx-media-tap-revealed'));
        }
    }, true);

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('mediaPrivacyToggle')
            ?.addEventListener('change', event => setEnabled(event.target.checked));
        document.getElementById('mediaPrivacyQuickToggle')
            ?.addEventListener('click', () => setEnabled(!enabled));
        syncControls();
    });

    document.addEventListener('mlx-language-changed', syncControls);

    window.MLXMediaPrivacy = {
        enabled: () => enabled,
        setEnabled,
        storageKey: KEY
    };
})();
