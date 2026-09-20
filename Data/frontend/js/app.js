(() => {
  const toastEl = document.getElementById("toast");
  let toastTimer = 0;

  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toastEl.classList.remove("show"), 1800);
  }

  function updateClock() {
    const now = new Date();
    const days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
    const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    const dateEl = document.getElementById("clockDate");
    const timeEl = document.getElementById("clockTime");
    if (!dateEl || !timeEl) return;

    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    dateEl.textContent = `${days[now.getDay()]}, ${months[now.getMonth()]} ${String(now.getDate()).padStart(2, "0")}, ${now.getFullYear()}`;
    timeEl.textContent = `${hh}:${mm}`;
  }

  function wireToggleGroup(selector) {
    const items = Array.from(document.querySelectorAll(selector));
    items.forEach((item) => {
      item.addEventListener("click", (event) => {
        // Allow real navigation for links between pages
        if (item.tagName === "A" && item.getAttribute("href")) return;
        event.preventDefault();
        items.forEach((el) => el.classList.remove("is-active"));
        item.classList.add("is-active");
        const label = item.textContent.trim().replace(/\s+/g, " ");
        toast(label);
      });
    });
  }

  wireToggleGroup(".lv-nav-item");
  wireToggleGroup(".lv-tab");
  wireToggleGroup(".lv-dock-item");

  document.querySelectorAll(".lv-feature, .lv-tool, .lv-prompt-attach").forEach((btn) => {
    btn.addEventListener("click", () => toast(btn.textContent.trim() || "Action"));
  });

  const sendBtn = document.getElementById("sendBtn");
  if (sendBtn) {
    sendBtn.addEventListener("click", () => toast("Message queued (demo)"));
  }

  const menuBtn = document.getElementById("menuBtn");
  const sidebar = document.getElementById("sidebar");
  if (menuBtn && sidebar) {
    menuBtn.addEventListener("click", () => {
      sidebar.classList.toggle("is-open");
    });
    document.addEventListener("click", (event) => {
      if (!sidebar.classList.contains("is-open")) return;
      if (sidebar.contains(event.target) || menuBtn.contains(event.target)) return;
      sidebar.classList.remove("is-open");
    });
  }

  updateClock();
  window.setInterval(updateClock, 15000);
})();
