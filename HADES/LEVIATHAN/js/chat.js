(() => {
  const toastEl = document.getElementById("toast");
  let toastTimer = 0;

  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toastEl.classList.remove("show"), 1600);
  }

  function wireGroup(selector) {
    const items = Array.from(document.querySelectorAll(selector));
    items.forEach((item) => {
      item.addEventListener("click", () => {
        items.forEach((el) => el.classList.remove("is-active"));
        item.classList.add("is-active");
        toast(item.textContent.trim().replace(/\s+/g, " "));
      });
    });
  }

  wireGroup(".lv-chip");
  wireGroup(".lv-thread");
  wireGroup(".lv-right-tab");

  document.querySelectorAll(".lv-quick, .lv-new-chat, .lv-tool-item, .lv-context-item, .lv-add-context").forEach((btn) => {
    btn.addEventListener("click", () => toast(btn.textContent.trim().replace(/\s+/g, " ") || "Action"));
  });

  const sendBtn = document.getElementById("sendBtn");
  if (sendBtn) {
    sendBtn.addEventListener("click", () => toast("Message queued (demo)"));
  }

  // Style nav anchors like buttons
  document.querySelectorAll("a.lv-nav-item, a.lv-dock-item").forEach((el) => {
    el.style.textDecoration = "none";
  });
})();
