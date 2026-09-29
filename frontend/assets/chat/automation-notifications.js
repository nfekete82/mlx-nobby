(function () {
    'use strict';

    if (window.__mlxNobbyAutomationNotifications) return;
    window.__mlxNobbyAutomationNotifications = true;

    const FALLBACK = {
        title: 'Notifications',
        unread: '{count} unread',
        mark_all_read: 'Mark all read',
        mark_read: 'Mark read',
        empty: 'No automation notifications yet.',
        native_delivered: 'Delivered to macOS Notification Center',
        native_failed: 'Native delivery unavailable',
        level_info: 'Info',
        level_success: 'Success',
        level_warning: 'Attention',
        level_error: 'Error'
    };

    let copy = { ...FALLBACK };
    let notifications = [];
    let unread = 0;
    let inbox = null;
    let list = null;
    let unreadBadge = null;
    let markAllButton = null;
    let pollTimer = null;
    let newestSeenAt = 0;
    let initialized = false;

    function locale() {
        const current = window.MLXI18n?.getLocale?.() || navigator.language || 'en';
        return String(current).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function t(key, vars = {}) {
        let value = copy[key] || FALLBACK[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => {
            value = String(value).replaceAll('{' + name + '}', String(replacement ?? ''));
        });
        return value;
    }

    async function loadCopy() {
        copy = { ...FALLBACK };
        try {
            const response = await fetch(
                '/i18n/automation-notifications.' + locale() + '.json',
                { cache: 'no-store' }
            );
            if (response.ok) {
                const data = await response.json();
                if (data && typeof data === 'object') copy = { ...FALLBACK, ...data };
            }
        } catch (_) {}
    }

    async function requestJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.error || ('HTTP ' + response.status));
        return data;
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function formatDate(value) {
        if (!value) return '';
        const date = new Date(Number(value) * 1000);
        if (Number.isNaN(date.getTime())) return '';
        return new Intl.DateTimeFormat(locale() === 'de' ? 'de-DE' : 'en-US', {
            dateStyle: 'short',
            timeStyle: 'short'
        }).format(date);
    }

    function unreadCount(items) {
        return (items || []).filter(item => item?.unread).length;
    }

    function shouldAnnounce(item, cursor) {
        return Boolean(
            item?.unread &&
            !item?.delivered &&
            Number(item?.created_at || 0) > Number(cursor || 0)
        );
    }

    function ensureInbox() {
        if (inbox?.isConnected) return inbox;
        const pane = document.querySelector('[data-settings-pane="automations"]');
        if (!pane) return null;

        inbox = element('section', 'automations-notifications');
        const header = element('div', 'automations-notifications-header');
        const titleWrap = element('div', 'automations-notifications-title-wrap');
        const title = element('h5', '', t('title'));
        title.dataset.automationNotificationsTitle = 'true';
        unreadBadge = element('span', 'automation-notification-count');
        titleWrap.append(title, unreadBadge);

        markAllButton = element('button', 'automation-button');
        markAllButton.type = 'button';
        markAllButton.textContent = t('mark_all_read');
        markAllButton.addEventListener('click', markAllRead);
        header.append(titleWrap, markAllButton);

        list = element('div', 'automations-notifications-list');
        inbox.append(header, list);

        const history = pane.querySelector('.automations-history');
        if (history) pane.insertBefore(inbox, history);
        else pane.appendChild(inbox);
        return inbox;
    }

    function render() {
        if (!ensureInbox() || !list) return;
        const title = inbox.querySelector('[data-automation-notifications-title]');
        if (title) title.textContent = t('title');
        if (markAllButton) markAllButton.textContent = t('mark_all_read');
        if (unreadBadge) {
            unreadBadge.textContent = t('unread', { count: unread });
            unreadBadge.hidden = unread <= 0;
        }
        if (markAllButton) markAllButton.disabled = unread <= 0;

        list.innerHTML = '';
        if (!notifications.length) {
            list.appendChild(element('div', 'automation-empty', t('empty')));
            return;
        }

        notifications.slice(0, 30).forEach(item => {
            const row = element(
                'article',
                'automation-notification level-' + (item.level || 'info') +
                (item.unread ? ' unread' : '')
            );
            const top = element('div', 'automation-notification-top');
            const titleWrap = element('div', 'automation-notification-copy');
            const heading = element('strong', '', item.title || t('title'));
            const meta = element(
                'div',
                'automation-notification-meta',
                [
                    formatDate(item.created_at),
                    item.delivered ? t('native_delivered') :
                        (item.delivery_error ? t('native_failed') : '')
                ].filter(Boolean).join(' · ')
            );
            titleWrap.append(heading, meta);

            if (item.unread) {
                const readButton = element('button', 'automation-button compact', t('mark_read'));
                readButton.type = 'button';
                readButton.addEventListener('click', () => markRead(item.id));
                top.append(titleWrap, readButton);
            } else {
                top.appendChild(titleWrap);
            }

            const message = element('p', 'automation-notification-message', item.message || '');
            row.append(top, message);
            list.appendChild(row);
        });
    }

    function toastContainer() {
        let container = document.getElementById('automationNotificationToasts');
        if (!container) {
            container = element('div', 'automation-notification-toasts');
            container.id = 'automationNotificationToasts';
            container.setAttribute('aria-live', 'polite');
            document.body.appendChild(container);
        }
        return container;
    }

    function showToast(item) {
        const toast = element('button', 'automation-notification-toast level-' + (item.level || 'info'));
        toast.type = 'button';
        toast.append(
            element('strong', '', item.title || t('title')),
            element('span', '', item.message || '')
        );
        toast.addEventListener('click', async () => {
            await markRead(item.id);
            window.MLXAutomationsUI?.show?.();
            toast.remove();
        });
        toastContainer().appendChild(toast);
        setTimeout(() => toast.remove(), 9000);
    }

    async function refresh({ announce = false } = {}) {
        try {
            const data = await requestJson(
                '/api/mlx/automations/notifications?limit=50',
                { cache: 'no-store' }
            );
            const next = Array.isArray(data.notifications) ? data.notifications : [];
            const previousCursor = newestSeenAt;
            notifications = next;
            unread = Number(data.unread_count ?? unreadCount(next));
            newestSeenAt = Math.max(
                newestSeenAt,
                ...next.map(item => Number(item?.created_at || 0)),
                0
            );
            render();
            if (announce && previousCursor > 0) {
                next
                    .filter(item => shouldAnnounce(item, previousCursor))
                    .slice(0, 3)
                    .reverse()
                    .forEach(showToast);
            }
        } catch (error) {
            console.debug('[automation-notifications] refresh failed:', error);
        }
    }

    async function markRead(notificationId) {
        try {
            await requestJson(
                '/api/mlx/automations/notifications/' + encodeURIComponent(notificationId) + '/read',
                { method: 'POST' }
            );
            await refresh();
        } catch (error) {
            console.debug('[automation-notifications] mark read failed:', error);
        }
    }

    async function markAllRead() {
        try {
            await requestJson(
                '/api/mlx/automations/notifications/read-all',
                { method: 'POST' }
            );
            await refresh();
        } catch (error) {
            console.debug('[automation-notifications] mark all read failed:', error);
        }
    }

    function startPolling() {
        clearInterval(pollTimer);
        pollTimer = setInterval(() => refresh({ announce: true }), 15000);
    }

    async function initialize() {
        if (initialized) return true;
        if (!ensureInbox()) return false;
        initialized = true;
        await loadCopy();
        await refresh({ announce: false });
        startPolling();
        return true;
    }

    function retryInitialize() {
        let attempts = 0;
        const attempt = async () => {
            attempts += 1;
            if (await initialize()) return;
            if (attempts < 80) setTimeout(attempt, 75);
        };
        attempt();
    }

    window.MLXAutomationNotifications = {
        refresh,
        markRead,
        markAllRead,
        __test: {
            unreadCount,
            shouldAnnounce,
            formatDate
        }
    };

    document.addEventListener('mlx-language-changed', () => {
        loadCopy().then(render);
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', retryInitialize, { once: true });
    } else {
        retryInitialize();
    }
})();
