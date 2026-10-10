(() => {
  "use strict";
  const list = document.getElementById("chatList");
  const search = document.getElementById("recentSearch");
  const filterPanel = document.getElementById("recentFilter");
  const filterToggle = document.getElementById("recentFilterToggle");
  const collapse = document.getElementById("recentToggle");
  const newChat = document.getElementById("recentNewChat");
  if (!list || !search || !filterPanel || !filterToggle || !collapse) return;

  // Filter only the visible chat rows. Do not alter server history or DOM order.
  const applyFilter = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const rows = Array.from(list.children);
    for (const row of rows) {
      const titleNode = row.querySelector("[data-session-title], .chat-title, .session-title, .chat-item-title, .chat-name") || row.querySelector("button");
      const label = (titleNode?.textContent || row.getAttribute("data-session-title") || "").toLocaleLowerCase();
      row.hidden = Boolean(query) && !label.includes(query);
    }
  };
  const observer = new MutationObserver(applyFilter);
  observer.observe(list, { childList: true });
  search.addEventListener("input", applyFilter);

  filterToggle.addEventListener("click", () => {
    const showing = filterPanel.hidden;
    filterPanel.hidden = !showing;
    filterToggle.setAttribute("aria-expanded", String(showing));
    if (showing) search.focus();
    else { search.value = ""; applyFilter(); }
  });
  collapse.addEventListener("click", () => {
    const expanded = collapse.getAttribute("aria-expanded") !== "true";
    collapse.setAttribute("aria-expanded", String(expanded));
    list.hidden = !expanded;
    if (!expanded) {
      filterPanel.hidden = true;
      filterToggle.setAttribute("aria-expanded", "false");
    }
  });
  newChat?.addEventListener("click", () => document.getElementById("newChat")?.click());
})();
