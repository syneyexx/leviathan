/* HADES FINALBETA v2 — light interactions for mockup browsing */
(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  // Mode cards
  qsa("[data-mode]").forEach(function (card) {
    card.addEventListener("click", function () {
      qsa("[data-mode]").forEach(function (c) {
        c.classList.remove("active");
      });
      card.classList.add("active");
    });
  });

  // Local tabs (within page)
  qsa("[data-tabs]").forEach(function (tabs) {
    var group = tabs.getAttribute("data-tabs");
    qsa(".tab", tabs).forEach(function (tab) {
      tab.addEventListener("click", function () {
        qsa(".tab", tabs).forEach(function (t) {
          t.classList.remove("active");
        });
        tab.classList.add("active");
        if (group) {
          qsa('[data-tab-panel="' + group + '"]').forEach(function (panel) {
            panel.hidden = panel.getAttribute("data-panel-id") !== tab.getAttribute("data-tab");
          });
        }
      });
    });
  });

  // Demo toast
  var toast = document.createElement("div");
  toast.style.cssText =
    "position:fixed;z-index:100;right:20px;bottom:20px;background:#111d22;border:1px solid #34454d;border-radius:8px;padding:10px 14px;box-shadow:0 12px 28px rgba(0,0,0,.4);opacity:0;pointer-events:none;transition:.2s;font-size:12px;color:#e8edef";
  document.body.appendChild(toast);
  var timer = null;

  function showToast(msg) {
    toast.textContent = msg;
    toast.style.opacity = "1";
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      toast.style.opacity = "0";
    }, 1400);
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-toast]");
    if (el) {
      e.preventDefault();
      showToast(el.getAttribute("data-toast") || "Demoactie");
    }
  });

  // Animate loss chart if present
  var path = qs("#loss-path");
  if (path) {
    var len = path.getTotalLength();
    path.style.strokeDasharray = String(len);
    path.style.strokeDashoffset = String(len);
    path.getBoundingClientRect();
    path.style.transition = "stroke-dashoffset 1.4s ease";
    path.style.strokeDashoffset = "0";
  }
})();
