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

    function createCustomField(item = {}) {
        const row = document.createElement('div');
        row.className = 'profile-custom-field';

        const label = document.createElement('input');
        label.type = 'text';
        label.placeholder = 'Bezeichnung';
        label.value = item.label || '';

        const value = document.createElement('input');
        value.type = 'text';
        value.placeholder = 'Information';
        value.value = item.value || '';

        const sensitive = document.createElement('label');
        sensitive.className = 'settings-toggle';

        const sensitiveInput = document.createElement('input');
        sensitiveInput.type = 'checkbox';
        sensitiveInput.checked = item.sensitive === true;

        sensitive.append(
            sensitiveInput,
            document.createTextNode(' Sensibel')
        );

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'settings-button danger';
        remove.textContent = 'Entfernen';

        const state = {
            row,
            label,
            value,
            sensitive: sensitiveInput,
            category: item.category || 'other',
            enabled: item.enabled !== false
        };

        remove.addEventListener('click', () => {
            customFields = customFields.filter(
                field => field !== state
            );
            row.remove();
        });

        row.append(label, value, sensitive, remove);
        $('profileCustomFields')?.appendChild(row);

        customFields.push(state);
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
            $('profileName').value = fields.name || '';
            $('profileAge').value = fields.age || '';
            $('profileProfession').value = fields.profession || '';
            $('profileLocation').value = fields.location || '';
            $('profileAbout').value = fields.about || '';
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
                name: $('profileName')?.value.trim() || '',
                age: $('profileAge')?.value.trim() || '',
                profession:
                    $('profileProfession')?.value.trim() || '',
                location:
                    $('profileLocation')?.value.trim() || '',
                about: $('profileAbout')?.value.trim() || '',
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
            () => createCustomField()
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
