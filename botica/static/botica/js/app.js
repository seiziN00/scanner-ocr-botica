/* ==========================================================================
   BOTICA · Capa UI — Vanilla JS + HTMX
   Todo el manejo de eventos es delegado (sobrevive a los swaps de HTMX).
   ========================================================================== */
(() => {
  "use strict";

  const $  = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const fmt = n => "S/ " + Number(n || 0).toFixed(2);

  /* ============================================================
     TOASTS
  ============================================================ */
  function toast(msg, type = "ok") {
    const wrap = $("#toasts");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = "toast" + (type !== "ok" ? " toast--" + type : "");
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, 2600);
  }

  /* ============================================================
     MODALES GENÉRICOS (Checkout + Ajuste viven en base.html)
  ============================================================ */
  function openModal(sel) {
    const m = $(sel); if (!m) return;
    m.hidden = false;
    document.body.style.overflow = "hidden";
    const f = m.querySelector("input:not([type=hidden]), select");
    if (f) setTimeout(() => f.focus(), 80);
  }
  function closeModal(m) {
    if (typeof m === "string") m = $(m);
    if (!m) return;
    m.hidden = true;
    document.body.style.overflow = "";
  }

  /* ============================================================
     NAVEGACIÓN SPA · estado activo + post-swap
  ============================================================ */
  function setNav(path) {
    $$("[data-nav]").forEach(a => {
      const nav = a.dataset.nav;
      const on = nav === "panel"
        ? path === "/" || path.startsWith("/panel")
        : path.includes("/" + nav);
      a.classList.toggle("is-active", on);
    });
  }
  document.addEventListener("htmx:afterRequest", e => {
    if (e.detail.successful) setNav(e.detail.pathInfo.requestPath);
  });
  document.addEventListener("htmx:afterSwap", e => {
    if (e.detail.target.id !== "app-content") return;
    window.scrollTo({ top: 0 });
    const s = $("#pos-search");           // al entrar al POS, foco directo
    if (s) setTimeout(() => s.focus(), 120);
    pintarFecha();
  });

  /* ============================================================
     ESTADO GLOBAL DEL CARRITO
  ============================================================ */
  const cart = [];
  let gDesc = 0; // descuento general del ticket

  const lineTotal = it => it.price * it.qty - it.desc;
  const totals = () => {
    const sub  = cart.reduce((a, it) => a + it.price * it.qty, 0);
    const dscs = cart.reduce((a, it) => a + it.desc, 0) + gDesc;
    return { sub, dscs, total: Math.max(0, sub - dscs) };
  };
  const nItems = () => cart.reduce((a, it) => a + it.qty, 0);

  function itemHTML(it) {
    return `
    <li class="cart-item" data-id="${it.id}">
      <div class="cart-item__top">
        <div>
          <strong class="cart-item__name">${it.name}</strong>
          <span class="cart-item__meta">${it.unit} · <span class="mono">${fmt(it.price)}</span> c/u${
            it.desc > 0 ? ` · <span class="cart-item__dscto">desc. ${fmt(it.desc)}</span>` : ""
          }</span>
        </div>
        <button class="cart-item__del" type="button" data-cart-act="del" aria-label="Quitar">
          <svg class="ic ic--sm"><use href="#i-trash"/></svg>
        </button>
      </div>
      <div class="cart-item__bottom">
        <div class="stepper">
          <button type="button" data-cart-act="dec" aria-label="Disminuir">−</button>
          <span class="stepper__n">${it.qty}</span>
          <button type="button" data-cart-act="inc" aria-label="Aumentar" ${it.qty >= it.max ? "disabled" : ""}>+</button>
        </div>
        <button class="chose-presentation" data-chose-presentation>
          <span class="material-symbols-outlined">layers</span>
        </button>
        <span class="cart-item__sub mono">${fmt(lineTotal(it))}</span>
      </div>
    </li>`;
  }

  function renderCart() {
    const html = cart.map(itemHTML).join("");
    $$("[data-cart-list]").forEach(ul => (ul.innerHTML = html));
    $$("[data-cart-empty]").forEach(el => (el.hidden = cart.length > 0));
    $$("[data-cart-count]").forEach(el => (el.textContent = nItems() === 1 ? "1 producto" : `${nItems()} productos`));
    $$("[data-cart-count-fab-button]").forEach(el => (el.textContent = nItems()));

    const t = totals();
    $$("[data-cart-sub]").forEach(el => (el.textContent = fmt(t.sub)));
    $$("[data-cart-desc]").forEach(el => (el.textContent = "− " + fmt(t.dscs)));
    $$("[data-cart-total]").forEach(el => (el.textContent = fmt(t.total)));
    $$("[data-cart-btn-total]").forEach(el => (el.textContent = fmt(t.total)));
    $$("[data-open-checkout]").forEach(b => (b.disabled = cart.length === 0));
    $$("[data-global-desc]").forEach(i => {
      i.max = t.sub.toFixed(2);
      if (document.activeElement !== i) i.value = gDesc || 0;
    });
  }

  function addItem(d, unit) {
    const P = { caja: [+d.pCaja, +d.sCaja, "Caja"], blister: [+d.pBlis, +d.sBlis, "Blíster"], unidad: [+d.pUni, +d.sUni, "Unidad"] };
    const [price, max, label] = P[unit];
    if (!max) return;
    const id = d.code + "-" + unit;
    const ex = cart.find(x => x.id === id);
    if (ex) {
      if (ex.qty >= ex.max) { toast("Stock máximo alcanzado", "warn"); return; }
      ex.qty++;
    } else {
      // code + unitKey se envían al backend en el checkout
      cart.push({ id, code: d.code, unitKey: unit, name: d.name, unit: label, price, qty: 1, max, desc: 0 });
    }
    renderCart();
    toast(`${d.name.split(" ·")[0]} · ${label} agregado`);
  }

  /* ============================================================
     POPOVER DE UNIDADES (Caja / Blíster / Unidad)
  ============================================================ */
  const pop = document.createElement("div");
  pop.className = "pop"; pop.id = "unitPop"; pop.hidden = true;
  pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Elegir presentación");
  document.body.appendChild(pop);

  function optHTML(unit, label, price, stock) {
    const dis = +stock <= 0;
    return `<button class="pop-opt" type="button" data-unit="${unit}" ${dis ? "disabled" : ""}>
      <span>${label} <small>${dis ? "sin stock" : "stock " + stock}</small></span>
      <span class="mono">${dis ? "—" : fmt(price)}</span>
    </button>`;
  }
  function openUnitPop(btn) {
    const d = (btn.closest("tr") ?? btn.closest(".item-card"))?.dataset;
    pop.__d = d; // dataset del producto para addItem()
    pop.innerHTML = `
      <div class="pop__head"><strong>${d.name}</strong></div>
      ${optHTML("caja", "Caja", d.pCaja, d.sCaja)}
      ${optHTML("blister", "Blíster", d.pBlis, d.sBlis)}
      ${optHTML("unidad", "Unidad", d.pUni, d.sUni)}`;
    pop.hidden = false;
    const r = btn.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), innerWidth - pw - 8) + "px";
    pop.style.top  = (r.top - ph - 10 < 8 ? r.bottom + 10 : r.top - ph - 10) + "px";
  }
  function closeUnitPop() { pop.hidden = true; }
  window.addEventListener("scroll", closeUnitPop, true);

  /* ============================================================
     CHECKOUT
  ============================================================ */
  let metodo = "efectivo";

  /* N° de ticket mostrado: lo renderiza el servidor en el partial del POS */
  const ticketActual = () => ($("[data-ticket-number]")?.textContent || "").replace(/\D/g, "") || "—";

  function getCSRF() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function openCheckout() {
    const t = totals();
    $("#ck-total").textContent = fmt(t.total);
    $("#ck-nitems").textContent = `${nItems()} productos · Ticket ${ticketActual()}`;
    $("#ck-main").style.display = "";
    $("#ck-ok").classList.remove("show");
    setMetodo("efectivo");
    $("#ck-monto").value = "";
    calcVuelto();
    openModal("#modal-checkout");
    setTimeout(() => $("#ck-monto").focus(), 120);
  }
  function setMetodo(m) {
    metodo = m;
    $$(".pay-btn").forEach(b => b.classList.toggle("is-on", b.dataset.pay === m));
    $("#ck-cash").hidden = m !== "efectivo";
    calcVuelto();
  }
  function calcVuelto() {
    const total = totals().total;
    const vEl = $("#ck-vuelto"), cBtn = $("#ck-confirm");
    if (metodo !== "efectivo") { cBtn.disabled = false; return; }
    const m = parseFloat($("#ck-monto").value) || 0;
    const v = m - total;
    if (v >= 0) {
      vEl.textContent = fmt(v); vEl.classList.remove("neg"); cBtn.disabled = false;
    } else {
      vEl.textContent = "Falta " + fmt(-v); vEl.classList.add("neg"); cBtn.disabled = true;
    }
  }

  /* ============================================================
     DELEGACIÓN PRINCIPAL DE CLICKS
  ============================================================ */
  document.addEventListener("click", e => {
    const T = e.target;

    /* --- abrir modales --- */
    const opener = T.closest("[data-open-modal]");
    if (opener) {
      openModal(opener.dataset.openModal);
      /* El formulario de ajuste llega por hx-get (el servidor preselecciona
         el producto cuando el botón trae ?producto=<id>) */
      return;
    }
    if (T.closest("[data-close-modal]") || T.classList.contains("modal__back")) {
      closeModal(T.closest(".modal")); return;
    }

    /* --- toggler de fecha (dashboard) ---
       Producción: reemplazable por hx-get="?vista=dias" que devuelva el <td>. */
    const tgl = T.closest(".tgl-exp");
    if (tgl) {
      tgl.classList.toggle("show-dias");
      tgl.setAttribute("aria-pressed", tgl.classList.contains("show-dias"));
      tgl.classList.remove("flip"); void tgl.offsetWidth; tgl.classList.add("flip");
      return;
    }

    /* --- pills de rango con fechas custom: solo muestra/oculta los inputs.
       El filtrado en sí lo hace el servidor (hx-get de cada pill). --- */
    const rangoPill = T.closest("[data-rango]");
    if (rangoPill) {
      const grupo = rangoPill.closest(".pills");
      const custom = grupo && grupo.querySelector(".rango-custom");
      if (custom) custom.hidden = rangoPill.dataset.rango !== "custom";
      /* no return: el click también dispara el hx-get de la pill */
    }

    /* --- POS: popover de unidades --- */
    if (T.closest("[data-add]")) { closeUnitPop(); openUnitPop(T.closest("[data-add]")); return; }
    const opt = T.closest(".pop-opt");
    if (opt && !opt.disabled) {
      addItem(pop.__d, opt.dataset.unit);
      closeUnitPop(); return;
    }
    if (pop && !pop.hidden && !T.closest("#unitPop")) closeUnitPop();

    /* --- acciones del carrito --- */
    const act = T.closest("[data-cart-act]");
    if (act) {
      const li = act.closest(".cart-item");
      const it = cart.find(x => x.id === li.dataset.id);
      if (!it) return;
      const a = act.dataset.cartAct;
      if (a === "inc") { if (it.qty < it.max) it.qty++; else { toast("Sin más stock", "warn"); return; } }
      if (a === "dec") { it.qty--; if (it.qty <= 0) { cart.splice(cart.indexOf(it), 1); } }
      if (a === "del") {
        if (act.classList.contains("armado")) cart.splice(cart.indexOf(it), 1);
        else {
          act.classList.add("armado"); act.textContent = "¿Eliminar?";
          setTimeout(() => { if (act.isConnected) { act.classList.remove("armado"); act.innerHTML = '<svg class="ic ic--sm"><use href="#i-trash"/></svg>'; } }, 2400);
          return;
        }
      }
      if (a === "cancel") { renderCart(); return; }
      renderCart();
      return;
    }

    /* --- FAB / Bottom Sheet --- */
    if (T.closest("[data-open-sheet]")) { setSheet(true); return; }
    if (T.closest("[data-close-sheet]")) { setSheet(false); return; }

    /* --- abrir checkout --- */
    if (T.closest("[data-open-checkout]")) { setSheet(false); openCheckout(); return; }

    /* --- métodos de pago --- */
    const pay = T.closest(".pay-btn");
    if (pay) { setMetodo(pay.dataset.pay); return; }

    /* --- chips de monto rápido --- */
    const chip = T.closest(".chip[data-chip]");
    if (chip) {
      const total = totals().total;
      $("#ck-monto").value = chip.dataset.chip === "exacto" ? total.toFixed(2) : (+chip.dataset.chip).toFixed(2);
      calcVuelto(); return;
    }

    /* --- confirmar cobro: POST real al backend (descuento FIFO de stock) --- */
    if (T.closest("#ck-confirm")) {
      const btn = $("#ck-confirm");
      const t = totals();
      const UNIT = { unidad: "UNIDAD", blister: "BLISTER", caja: "CAJA" };
      const payload = {
        metodo,
        descuento: gDesc,
        items: cart.map(it => ({ codigo: it.code, tipo_unidad: UNIT[it.unitKey], cantidad: it.qty })),
      };
      btn.disabled = true;
      fetch(btn.dataset.checkoutUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRF() },
        body: JSON.stringify(payload),
      })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || !data.ok) {
            toast(data.error || "No se pudo registrar la venta.", "err");
            btn.disabled = false;
            return;
          }
          let det = `Ticket ${data.ticket} · ${data.metodo} · ${fmt(data.total)}`;
          if (metodo === "efectivo") {
            const v = (parseFloat($("#ck-monto").value) || 0) - t.total;
            det += ` · Vuelto ${fmt(v)}`;
          }
          $("#ck-ok-det").textContent = det;
          $("#ck-main").style.display = "none";
          $("#ck-ok").classList.add("show");
          /* El servidor ya descontó el stock: refrescar resultados del POS
             y el número del próximo ticket */
          $$("[data-ticket-number]").forEach(el => (el.textContent = "N° " + data.proximo_ticket));
          htmx.trigger(document.body, "refreshPos");
        })
        .catch(() => {
          toast("Error de red al cobrar. Inténtalo de nuevo.", "err");
          btn.disabled = false;
        });
      return;
    }

    /* --- nueva venta (reset) --- */
    if (T.closest("#ck-new")) {
      cart.length = 0; gDesc = 0; renderCart();
      closeModal("#modal-checkout");
      toast("Ticket limpio · listo para la siguiente venta");
      return;
    }

    /* --- filas de inventario → kardex (delega al <a> con hx-get) --- */
    const row = T.closest("#inv-table tbody tr[data-key]");
    if (row && !T.closest("a,button")) { const l = row.querySelector(".row-link"); if (l) l.click(); return; }

    /* --- mostrar/ocultar contraseña (login) --- */
    const pwt = T.closest("[data-pw-toggle]");
    if (pwt) {
      const inp = pwt.closest(".pw-wrap").querySelector("input");
      inp.type = inp.type === "password" ? "text" : "password";
      pwt.setAttribute("aria-label", inp.type === "password" ? "Mostrar contraseña" : "Ocultar contraseña");
      return;
    }
  });



  /* ---------- descuento general ---------- */
  document.addEventListener("input", e => {
    const g = e.target.closest("[data-global-desc]");
    if (!g) return;
    const sub = totals().sub;
    gDesc = Math.min(Math.max(parseFloat(g.value) || 0, 0), sub);
    // sincronizar el input espejo (ticket desktop ↔ sheet mobile)
    $$("[data-global-desc]").forEach(i => { if (i !== g) i.value = g.value; });
    const t = totals();
    $$("[data-cart-desc]").forEach(el => (el.textContent = "− " + fmt(t.dscs)));
    $$("[data-cart-total]").forEach(el => (el.textContent = fmt(t.total)));
    $$("[data-cart-btn-total]").forEach(el => (el.textContent = fmt(t.total)));
  });

  /* ---------- monto recibido del checkout ---------- */
  document.addEventListener("input", e => { if (e.target.id === "ck-monto") calcVuelto(); });

  /* ---------- buscadores genéricos (POS e inventario) ---------- */
  document.addEventListener("input", e => {
    const s = e.target.closest("[data-search]");
    if (!s) return;
    const q = s.value.toLowerCase().trim();
    const tbl = $(s.dataset.search); if (!tbl) return;
    let shown = 0;
    $$("tbody tr[data-key]", tbl).forEach(tr => {
      const ok = tr.dataset.key.toLowerCase().includes(q);
      tr.hidden = !ok; if (ok) shown++;
    });
    $$(".item-cards .item-card").forEach(card => {
      const ok = card.dataset.key.toLowerCase().includes(q);
      card.hidden = !ok;
    });
    const empty = tbl.querySelector(".row-empty"); if (empty) empty.hidden = shown !== 0;
  });

  /* ---------- bottom sheet ---------- */
  function setSheet(open) {
    const wrapper = $(".ticket-wrapper");
    const bk = $("[data-close-sheet]");
    if (wrapper) wrapper.classList.toggle("is-open", open);
    if (bk) { bk.hidden = !open; bk.classList.toggle("is-open", open); }
    document.body.style.overflow = open ? "hidden" : "";
    document.body.classList.toggle("sheet-open", open);
  }

  /* ============================================================
     CAMBIOS (selects)
  ============================================================ */
  document.addEventListener("change", e => {
    /* Tipo de movimiento → habilita motivos válidos */
    if (e.target.id === "aj-tipo") {
      const tipo = e.target.value;
      $$("#aj-motivo option").forEach(o => {
        o.disabled = tipo === "entrada" ? o.dataset.para === "salida"
                   : tipo === "salida"  ? o.dataset.para === "entrada" : false;
      });
      const sel = $("#aj-motivo");
      if (sel.selectedOptions[0] && sel.selectedOptions[0].disabled) {
        const first = $$("#aj-motivo option").find(o => !o.disabled);
        sel.value = first ? first.value : "";
      }
    }
  });

  /* ============================================================
     TECLADO
  ============================================================ */
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (!pop.hidden) { closeUnitPop(); return; }
      const sheet = $(".ticket-wrapper");
      if (sheet && sheet.classList.contains("is-open")) { setSheet(false); return; }
      const open = $$(".modal:not([hidden])");
      if (open.length) closeModal(open[open.length - 1]);
      return;
    }
    /* atajo "/" → buscador POS */
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      const s = $("#pos-search");
      if (s) { e.preventDefault(); s.focus(); }
    }
  });

  /* ============================================================
     FORMULARIO DE AJUSTE (hx-post real)
     Éxito → 204 + HX-Trigger "movimientoRegistrado": aquí se cierra el
     modal y las regiones de datos se refrescan solas (hx-trigger from:body).
     Error de validación → el servidor re-renderiza el formulario (200).
  ============================================================ */
  document.body.addEventListener("movimientoRegistrado", () => {
    closeModal("#modal-ajuste");
    toast("Movimiento registrado en el kardex");
  });

  /* ============================================================
    FECHA ACTUAL · "Miércoles 03 SEP 2026"
  ============================================================ */
  function fechaActual() {
    const fecha = new Date();
    const partes = new Intl.DateTimeFormat('es-ES', {
      weekday: 'long',
      day:     '2-digit',
      month:   'short',
      year:    'numeric'
    }).formatToParts(fecha);
    const get = tipo => partes.find(p => p.type === tipo)?.value;
    const dia = get('weekday');
    return `${dia[0].toUpperCase()}${dia.slice(1)} ${get('day')} ${get('month').toUpperCase()} ${get('year')}`;
  }

  function pintarFecha() {
    const texto = fechaActual();
    const el = $("#fecha");
    if (el) el.textContent = texto;
    $$("[data-fecha]").forEach(el => (el.textContent = texto));
  }

  /* Init */
  renderCart();
  pintarFecha();
})();