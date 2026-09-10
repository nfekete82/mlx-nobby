(() => {
    const $ = id => document.getElementById(id);

    let customFields = [];

    async function request(path, options = {}) {
        const response = await fetch(path, options);
        let data = {};

        try {
            data = await response.json();
        } catch (_) {}

        if (!response.ok) {
            throw new Error(
                data.detail ||
                data.error ||
                `HTTP ${response.status}`
            );
        }

        return data;
    }

    function createCustomField(item = {}, options = {}) {
        const card = document.createElement('div');
        card.className = 'profile-info-card';

        const header = document.createElement('button');
        header.type = 'button';
        header.className = 'profile-info-card-header';

        const summary = document.createElement('div');
        summary.className = 'profile-info-summary';

        const summaryLabel = document.createElement('strong');
        summaryLabel.className = 'profile-info-label';

        const summaryValue = document.createElement('span');
        summaryValue.className = 'profile-info-value';

        const chevron = document.createElement('span');
        chevron.className = 'profile-info-chevron';
        chevron.setAttribute('aria-hidden', 'true');
        chevron.textContent = '›';

        summary.append(summaryLabel, summaryValue);
        header.append(summary, chevron);

        const editor = document.createElement('div');
        editor.className = 'profile-info-editor';

        const labelField = document.createElement('div');
        labelField.className = 'field';

        const labelCaption = document.createElement('label');
        labelCaption.textContent = 'Bezeichnung';

        const label = document.createElement('input');
        label.type = 'text';
        label.placeholder = 'z. B. Betriebssystem';
        label.value = item.label || '';

        labelField.append(labelCaption, label);

        const valueField = document.createElement('div');
        valueField.className = 'field';

        const valueCaption = document.createElement('label');
        valueCaption.textContent = 'Information';

        const value = document.createElement('textarea');
        value.rows = 4;
        value.placeholder =
            'Information eingeben. Auch längere Texte sind möglich.';
        value.value = item.value || '';

        valueField.append(valueCaption, value);

        const footer = document.createElement('div');
        footer.className = 'profile-info-editor-footer';

        const sensitive = document.createElement('label');
        sensitive.className = 'settings-toggle';

        const sensitiveInput = document.createElement('input');
        sensitiveInput.type = 'checkbox';
        sensitiveInput.checked = item.sensitive === true;

        sensitive.append(
            sensitiveInput,
            document.createTextNode(' Sensibel')
        );

        const actions = document.createElement('div');
        actions.className = 'profile-info-editor-actions';

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'settings-button danger';
        remove.textContent = 'Entfernen';

        const done = document.createElement('button');
        done.type = 'button';
        done.className = 'settings-button';
        done.textContent = 'Fertig';

        actions.append(remove, done);
        footer.append(sensitive, actions);

        editor.append(
            labelField,
            valueField,
            footer
        );

        card.append(header, editor);

        const state = {
            row: card,
            label,
            value,
            sensitive: sensitiveInput,
            category: item.category || 'other',
            enabled: item.enabled !== false
        };

        function updateSummary() {
            const labelText = label.value.trim();
            const valueText = value.value.trim();

            summaryLabel.textContent =
                labelText || 'Neue Information';

            summaryValue.textContent =
                valueText || 'Noch keine Information eingetragen';

            card.classList.toggle(
                'is-empty',
                !labelText && !valueText
            );
        }

        function setExpanded(expanded) {
            card.classList.toggle(
                'is-expanded',
                expanded
            );

            header.setAttribute(
                'aria-expanded',
                expanded ? 'true' : 'false'
            );

            editor.hidden = !expanded;

            if (expanded && !label.value.trim()) {
                requestAnimationFrame(() => label.focus());
            }
        }

        header.addEventListener('click', () => {
            setExpanded(
                !card.classList.contains('is-expanded')
            );
        });

        done.addEventListener('click', () => {
            updateSummary();
            setExpanded(false);
        });

        remove.addEventListener('click', () => {
            customFields = customFields.filter(
                field => field !== state
            );

            card.remove();
        });

        label.addEventListener('input', updateSummary);
        value.addEventListener('input', updateSummary);

        updateSummary();

        $('profileCustomFields')?.appendChild(card);
        customFields.push(state);

        setExpanded(options.expanded === true);
    }

    function renderCustomFields(items) {
        customFields = [];

        const target = $('profileCustomFields');
        if (!target) return;

        target.innerHTML = '';

        for (const item of items || []) {
            createCustomField(item);
        }
    }

    async function load() {
        const status = $('profileSaveStatus');

        if (status) {
            status.textContent = 'Profil wird geladen…';
        }

        try {
            const data = await request('/api/mlx/profile');
            const fields = data.fields || {};

            $('profileEnabled').checked = data.enabled !== false;

            $('profileResponsePreferences').value =
                fields.response_preferences || '';

            renderCustomFields(data.custom_fields || []);

            if (status) {
                status.textContent = '';
            }
        } catch (error) {
            if (status) {
                status.textContent =
                    'Profil konnte nicht geladen werden: ' +
                    error.message;
            }
        }
    }

    async function save() {
        const button = $('profileSave');
        const status = $('profileSaveStatus');

        if (button) button.disabled = true;
        if (status) status.textContent = 'Speichere…';

        const payload = {
            enabled: $('profileEnabled')?.checked !== false,
            fields: {
                response_preferences:
                    $('profileResponsePreferences')?.value.trim() || ''
            },
            custom_fields: customFields
                .map(field => ({
                    label: field.label.value.trim(),
                    value: field.value.value.trim(),
                    category: field.category,
                    sensitive: field.sensitive.checked,
                    enabled: field.enabled
                }))
                .filter(item => item.label && item.value)
        };

        try {
            await request('/api/mlx/profile', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (status) {
                status.textContent = '✓ Profil gespeichert';
            }
        } catch (error) {
            if (status) {
                status.textContent =
                    'Speichern fehlgeschlagen: ' +
                    error.message;
            }
        } finally {
            if (button) button.disabled = false;
        }
    }

    function init() {
        $('profileAddField')?.addEventListener(
            'click',
            () => createCustomField({}, { expanded: true })
        );

        $('profileSave')?.addEventListener(
            'click',
            save
        );
    }

    if (document.readyState === 'loading') {
        document.addEventListener(
            'DOMContentLoaded',
            init,
            { once: true }
        );
    } else {
        init();
    }

    window.MLXProfile = {
        load,
        save
    };
})();
