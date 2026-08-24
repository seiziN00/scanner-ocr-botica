/* FarmaScan · utilidades de UI compartidas (toasts, flash, modales HTMX) */
(function () {
  "use strict";

  window.FarmaScan = window.FarmaScan || {};

  /* ---------- CSRF ---------- */
  FarmaScan.csrfToken = function () {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  };

  /* ---------- Toasts ---------- */
  FarmaScan.toast = function (msg, type = "ok") {
    const box = document.getElementById("toasts");
    if (!box) return;
    const t = document.createElement("div");
    t.className = "toast " + type;
    const dot = document.createElement("span");
    dot.className = "dot";
    t.appendChild(dot);
    t.appendChild(document.createTextNode(msg));
    box.appendChild(t);
    setTimeout(() => {
      t.classList.add("out");
      setTimeout(() => t.remove(), 320);
    }, 3200);
  };

  /* ---------- Flash de obturador ---------- */
  FarmaScan.flash = function () {
    const f = document.getElementById("flash");
    if (!f) return;
    f.classList.remove("go");
    void f.offsetWidth;
    f.classList.add("go");
  };

  /* ---------- Modales (contenido llega por HTMX a #modal-root) ---------- */
  FarmaScan.openModal = function () {
    const overlay = document.querySelector("#modal-root .overlay");
    if (!overlay) return;
    requestAnimationFrame(() => overlay.classList.add("open"));
    const first = overlay.querySelector("input, select, button.icon-btn");
    if (first) setTimeout(() => first.focus(), 160);
  };

  FarmaScan.closeModal = function () {
    const overlay = document.querySelector("#modal-root .overlay");
    if (!overlay) return;
    overlay.classList.remove("open");
    setTimeout(() => {
      const root = document.getElementById("modal-root");
      if (root) root.innerHTML = "";
    }, 210);
  };

  /* Abrir modal cuando HTMX inserta contenido en #modal-root */
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "modal-root") {
      FarmaScan.openModal();
    }
  });

  /* Cierre por botones con data-close-modal, clic fuera y tecla Escape */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-close-modal]")) {
      FarmaScan.closeModal();
      return;
    }
    const overlay = document.querySelector("#modal-root .overlay.open");
    if (overlay && e.target === overlay) FarmaScan.closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") FarmaScan.closeModal();
  });

  /* ---------- Eventos personalizados disparados por el servidor ----------
     Las respuestas de mutación devuelven cabeceras HX-Trigger con:
       - closeModal: cerrar el modal
       - showToast: {message, kind}
       - itemsChanged: refrescar la región de ítems (la página define el handler)
  */
  document.body.addEventListener("closeModal", function () {
    FarmaScan.closeModal();
  });
  document.body.addEventListener("showToast", function (e) {
    const d = e.detail || {};
    FarmaScan.toast(d.message || "Listo", d.kind || "ok");
  });
})();
