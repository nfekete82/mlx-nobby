/* Opt-in, in-memory request-shape diagnostics; never logs prompt text or hashes. */
(function (root) {
    'use strict';
    const enabled = () => root.sessionStorage?.getItem('mlx-apc-prefix-diagnostic') === '1';
    let previous = null;
    function contentOf(message) {
        return typeof message?.content === 'string' ? message.content : JSON.stringify(message?.content ?? null);
    }
    function commonPrefix(a, b) {
        let i = 0;
        const limit = Math.min(a.length, b.length);
        while (i < limit && a.charCodeAt(i) === b.charCodeAt(i)) i++;
        return i;
    }
    function record(payload) {
        if (!enabled()) { previous = null; return null; }
        const messages = Array.isArray(payload?.messages) ? payload.messages : [];
        const system = String(payload?.system_prompt || '');
        const sources = JSON.stringify(payload?.context_sources ?? null);
        const data = {
            system_prompt_characters: system.length,
            system_prompt_same: previous ? system === previous.system : null,
            context_sources_same: previous ? sources === previous.sources : null,
            messages: messages.length,
            roles: messages.map(m => m?.role || 'unknown'),
            message_characters: messages.map(m => contentOf(m).length),
            exact_unchanged_messages: 0,
            first_changed_message: null,
            common_first_message_characters: null,
        };
        if (previous) {
            const count = Math.min(messages.length, previous.messages.length);
            let i = 0;
            while (i < count && messages[i]?.role === previous.messages[i].role &&
                contentOf(messages[i]) === previous.messages[i].content) i++;
            data.exact_unchanged_messages = i;
            data.first_changed_message = i < count ? i : null;
            if (i < count) {
                data.common_first_message_characters =
                    commonPrefix(contentOf(messages[i]), previous.messages[i].content);
            }
        }
        previous = { system, sources, messages: messages.map(m => ({
            role: m?.role, content: contentOf(m)
        })) };
        root.console?.info?.('[MLX APC prefix diagnostic]', data);
        return data;
    }
    root.MLXHybridPrefixDiagnostics = { record };
})(window);
