(() => {
    'use strict';

    if (window.__mlxTalkingPhotoMotionInstalled) return;
    window.__mlxTalkingPhotoMotionInstalled = true;

    const SELECT_ID = 'talkingPhotoMotion';
    const FIELD_ID = 'talkingPhotoMotionField';
    const JOB_PATH = '/api/talking-photo/jobs';

    function language() {
        return (
            document.documentElement.lang ||
            window.I18n?.currentLanguage ||
            navigator.language ||
            'de'
        ).toLowerCase();
    }

    function localText(de, en) {
        return language().startsWith('de') ? de : en;
    }

    function installMotionField() {
        if (document.getElementById(FIELD_ID)) return;
        const text = document.getElementById('talkingPhotoText');
        const textField = text?.closest('.mlx-talking-photo-field');
        const host = textField?.parentElement;
        if (!textField || !host) return;

        const label = document.createElement('label');
        label.id = FIELD_ID;
        label.className = 'mlx-talking-photo-field';

        const title = document.createElement('span');
        title.textContent = localText('Bewegung', 'Motion');

        const select = document.createElement('select');
        select.id = SELECT_ID;
        [
            ['natural', localText('Natürlich · Kopf, Augen & Oberkörper', 'Natural · head, eyes & upper body')],
            ['none', localText('Nur Lippen · schneller', 'Lips only · faster')],
        ].forEach(([value, textContent]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = textContent;
            select.append(option);
        });
        select.value = 'natural';

        const hint = document.createElement('div');
        hint.className = 'mlx-talking-photo-hint';
        hint.textContent = localText(
            'Natürlich erzeugt zuerst mit LTX 2.5 dezente Kopf-, Augen-, Schulter- und Atembewegung und dauert deshalb länger.',
            'Natural first uses LTX 2.5 for subtle head, eye, shoulder and breathing motion, so it takes longer.',
        );

        label.append(title, select, hint);
        host.insertBefore(label, textField);
    }

    function translateMotionStatus() {
        const status = document.getElementById('talkingPhotoStatus');
        if (!status) return;
        if (status.textContent.trim() === 'motion') {
            status.textContent = localText(
                'Natürliche Bewegung wird mit LTX 2.5 erzeugt …',
                'Generating natural motion with LTX 2.5 …',
            );
        }
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = function talkingPhotoMotionFetch(input, init = {}) {
        let path = '';
        try {
            const rawUrl = typeof input === 'string' ? input : input?.url;
            path = new URL(rawUrl, window.location.href).pathname;
        } catch (_error) {
            return nativeFetch(input, init);
        }

        const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
        if (path !== JOB_PATH || method !== 'POST' || typeof init?.body !== 'string') {
            return nativeFetch(input, init);
        }

        try {
            const payload = JSON.parse(init.body);
            if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
                payload.motion = document.getElementById(SELECT_ID)?.value || 'natural';
                return nativeFetch(input, {...init, body: JSON.stringify(payload)});
            }
        } catch (_error) {
            // Keep the original request untouched when it is not JSON.
        }
        return nativeFetch(input, init);
    };

    const observer = new MutationObserver(() => {
        installMotionField();
        translateMotionStatus();
    });

    function start() {
        installMotionField();
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, {once: true});
    } else {
        start();
    }
})();
