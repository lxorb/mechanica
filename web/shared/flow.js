(function () {
  const D = window.HANDY;
  const state = {
    photoUrl: null,
    part: null,
    system: null,
    quoteEmail: "",
    channel: null,
    delivered: null,
    libFor: null
  };

  const FLOW = ["identify", "confirm", "pick", "library", "repair", "invoice"];

  function $(id) {
    return document.getElementById(id);
  }

  function screens() {
    return [...document.querySelectorAll("screen")];
  }

  function go(id) {
    screens().forEach((s) => s.classList.toggle("on", s.id === id));
    const i = FLOW.indexOf(id);
    document.querySelectorAll("[data-step]").forEach((el) => {
      el.classList.toggle("now", el.dataset.step === id);
      el.classList.toggle("done", FLOW.indexOf(el.dataset.step) < i);
    });
    const nav = $("nav") || $("dock");
    if (nav) nav.hidden = id === "identify";
    if (cfg.titleEl && cfg.titles) {
      const t = $(cfg.titleEl);
      if (t && cfg.titles[id]) t.textContent = cfg.titles[id];
    }
    if (id === "confirm") fillConfirm();
    if (id === "pick") sysGrid();
    if (id === "library") {
      if (state.part) {
        if (state.libFor !== state.part.id) {
          state.libFor = state.part.id;
          runLibrary(state.part);
        } else if ($("libPage")) $("libPage").hidden = false;
      } else if ($("libLog")) {
        $("libLog").textContent = "Pick a part first.";
      }
    }
    if (id === "repair" && state.part) fillRepair();
    if (id === "invoice" && state.part) fillInvoice();
    if (typeof cfg.afterGo === "function") cfg.afterGo(id);
  }

  function bikeCopy() {
    return {
      name: D.bike.name,
      year: D.bike.year,
      color: D.bike.color,
      engine: D.bike.engine
    };
  }

  function setPhoto(url) {
    state.photoUrl = url;
    document.querySelectorAll("[data-photo]").forEach((el) => {
      if (url) {
        el.style.backgroundImage = `url(${url})`;
        el.style.backgroundSize = "cover";
        el.style.backgroundPosition = "center";
        el.classList.add("has-photo");
      }
    });
  }

  function fillConfirm() {
    const b = bikeCopy();
    if ($("bikeName")) $("bikeName").textContent = b.name;
    if ($("bikeYear")) $("bikeYear").textContent = b.year;
    if ($("bikeMeta")) $("bikeMeta").textContent = b.year + " · " + b.color;
    if ($("bikeEngine")) $("bikeEngine").textContent = b.engine;
    if ($("bikeMatch")) $("bikeMatch").textContent = D.bike.match;
  }

  function sysGrid() {
    const root = $("sysGrid");
    if (!root) return;
    root.innerHTML = D.systems
      .map((s) => {
        const n = D.bySystem(s.id).length;
        return `<button type="button" class="sys ${state.system === s.id ? "open" : ""}" data-sys="${s.id}">
          <strong>${s.name}</strong>
          <span>${s.blurb}</span>
          <em>${n}</em>
        </button>`;
      })
      .join("");
    renderParts();
  }

  function renderParts() {
    const box = $("partGrid");
    if (!box) return;
    if (!state.system) {
      box.innerHTML = `<p class="hint">Pick a system.</p>`;
      return;
    }
    const sys = D.systems.find((s) => s.id === state.system);
    box.innerHTML =
      `<p class="hint">${sys.name}</p>` +
      D.bySystem(state.system)
        .map(
          (p) => `<button type="button" class="partcard" data-part="${p.id}">
            <strong>${p.name}</strong>
            <span>${p.sku}</span>
            <b>p.${p.page}</b>
          </button>`
        )
        .join("");
  }

  function crop(part, figure) {
    return `<figure class="man-crop">
      ${D.pageArt(part, figure)}
      <figcaption>Fig. ${figure || part.figure} · p.${part.page} · §${part.section}</figcaption>
    </figure>`;
  }

  function runLibrary(part) {
    const log = $("libLog");
    const bar = $("libBar");
    const page = $("libPage");
    if (page) page.hidden = true;
    if (log) log.innerHTML = "";
    if (bar) bar.style.width = "4%";
    const hits = [
      "Opening the library…",
      "Hit · Honda CB650R Shop Manual",
      "File · " + D.book.file,
      "Page " + part.page + " · §" + part.section,
      part.name
    ];
    let i = 0;
    function tick() {
      if (log) {
        const row = document.createElement("div");
        row.textContent = hits[i];
        log.appendChild(row);
      }
      if (bar) bar.style.width = (12 + i * 22) + "%";
      i += 1;
      if (i < hits.length) {
        setTimeout(tick, 320);
      } else {
        setTimeout(() => showPage(part), 280);
      }
    }
    tick();
  }

  function showPage(part) {
    const page = $("libPage");
    if (!page) return;
    page.hidden = false;
    page.innerHTML = `
      <div class="lib-meta">${D.book.title} · ${D.book.file} · ${D.book.pages} pages</div>
      <div class="lib-sec">§ ${part.section} · p.${part.page}</div>
      <pre class="verbatim">${escapeHtml(part.excerpt)}</pre>
      ${crop(part, part.figure)}
      <div class="row">
        <button type="button" class="primary" data-act="to-repair">Follow these pages</button>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function fillRepair() {
    const part = state.part;
    const root = $("repairBody");
    if (!root || !part) return;
    root.innerHTML =
      `<p class="hint">Only the book. ${part.name}.</p>` +
      part.steps
        .map(
          (s) => `<article class="step">
            <header><b>${s.n}</b><span>${s.pointer}</span><strong>p.${s.page}</strong></header>
            <blockquote>${escapeHtml(s.quote)}</blockquote>
            ${crop(part, s.figure)}
          </article>`
        )
        .join("") +
      `<div class="row">
         <button type="button" data-act="help">Show the related page</button>
         <button type="button" class="primary" data-act="want-part">I need this part</button>
       </div>
       <div id="helpBox" hidden></div>`;
  }

  function showHelp() {
    const part = state.part;
    const box = $("helpBox");
    if (!box || !part || !part.help) return;
    box.hidden = false;
    box.innerHTML = `<article class="step">
      <header><span>Related · §${part.help.section}</span><strong>p.${part.help.page}</strong></header>
      <blockquote>${escapeHtml(part.help.quote)}</blockquote>
      ${crop(part, part.help.figure)}
    </article>`;
  }

  function invoiceTotals(part) {
    const goods = part.price;
    const ship = part.ship;
    const tax = Math.round((goods + ship) * D.taxRate * 100) / 100;
    const total = Math.round((goods + ship + tax) * 100) / 100;
    return { goods, ship, tax, total };
  }

  function fillInvoice() {
    const part = state.part;
    const root = $("invoiceBody");
    if (!root || !part) return;
    const used = (part.used || [])
      .map(
        (u) => `<li><strong>${u.from}</strong> · ${money(u.price)}<span>${u.note} · ${u.where}</span></li>`
      )
      .join("") || "<li>No used listings in this sample.</li>";
    const alts = (part.alts || []).map((a) => `<li>${a}</li>`).join("");
    root.innerHTML = `
      <p class="hint">${part.name} · ${part.sku}</p>
      <div class="buygrid">
        <button type="button" data-act="channel" data-ch="quote">Email a quote</button>
        <button type="button" data-act="channel" data-ch="buy">Buy from ${part.from}</button>
        <button type="button" data-act="channel" data-ch="used">Search used</button>
        <button type="button" data-act="channel" data-ch="alt">Other</button>
      </div>
      <div id="channelBox"></div>
      <ul class="used" id="usedList">${used}</ul>
      <ul class="alts">${alts}</ul>
      <div id="sheet"></div>`;
    drawSheet();
  }

  function drawSheet() {
    const part = state.part;
    const sheet = $("sheet");
    if (!sheet || !part) return;
    const t = invoiceTotals(part);
    const ch =
      state.channel === "quote"
        ? "Quote requested"
        : state.channel === "buy"
          ? "Buy new · " + part.from
          : state.channel === "used"
            ? "Used listing"
            : state.channel === "alt"
              ? "Other source"
              : "Not chosen yet";
    sheet.innerHTML = `
      <div class="receipt">
        <h3>Statement</h3>
        <div><span>${part.name}</span><b>${money(t.goods)}</b></div>
        <div><span>Ship (${part.days} day)</span><b>${money(t.ship)}</b></div>
        <div><span>Tax (mock 8.25%)</span><b>${money(t.tax)}</b></div>
        <div class="due"><span>Total</span><b>${money(t.total)}</b></div>
        <p class="hint">${ch}${state.quoteEmail ? " · " + state.quoteEmail : ""}</p>
        <div class="row">
          <button type="button" class="primary" data-act="deliver" data-how="email">Send</button>
          <button type="button" data-act="deliver" data-how="download">Download</button>
        </div>
        <p id="deliverMsg" class="hint"></p>
      </div>`;
  }

  function identify(fromPhoto) {
    go("identify");
    const scan = $("scanNote");
    if (scan) scan.hidden = false;
    setTimeout(() => {
      if (scan) scan.hidden = true;
      fillConfirm();
      go("confirm");
    }, fromPhoto ? 900 : 280);
  }

  function bindIdentify() {
    const find = $("find");
    const q = $("q");
    const cam = $("camBtn") || $("cam");
    const file = $("file");
    if (find) find.onclick = () => identify(false);
    if (q) q.addEventListener("keydown", (e) => e.key === "Enter" && identify(false));
    if (cam && file) cam.onclick = () => file.click();
    if (file) {
      file.onchange = (e) => {
        const f = e.target.files[0];
        if (!f) return;
        setPhoto(URL.createObjectURL(f));
        identify(true);
      };
    }
  }

  function onClick(e) {
    const t = e.target.closest("[data-act], [data-go], [data-sys], [data-part]");
    if (!t) return;
    if (t.dataset.go) {
      go(t.dataset.go);
      return;
    }
    if (t.dataset.sys) {
      state.system = t.dataset.sys;
      sysGrid();
      return;
    }
    if (t.dataset.part) {
      state.part = D.part(t.dataset.part);
      state.libFor = null;
      go("library");
      return;
    }
    const act = t.dataset.act;
    if (act === "yes") {
      sysGrid();
      go("pick");
    } else if (act === "no") {
      state.photoUrl = null;
      go("identify");
    } else if (act === "to-repair") {
      fillRepair();
      go("repair");
    } else if (act === "help") {
      showHelp();
    } else if (act === "want-part") {
      fillInvoice();
      go("invoice");
    } else if (act === "channel") {
      state.channel = t.dataset.ch;
      const box = $("channelBox");
      if (state.channel === "quote" && box) {
        box.innerHTML = `<label for="em">Email</label>
          <input id="em" type="email" placeholder="you@shop.com">
          <button type="button" class="primary" data-act="save-email">Request quote</button>`;
      } else if (box) {
        const msg = {
          buy: "New from " + state.part.from + " · " + money(state.part.price),
          used: "Used listings below.",
          alt: "Other sources listed below."
        };
        box.innerHTML = `<p class="hint">${msg[state.channel]}</p>`;
        drawSheet();
      }
    } else if (act === "save-email") {
      const em = $("em");
      state.quoteEmail = em && em.value ? em.value : "you@shop.com";
      drawSheet();
    } else if (act === "deliver") {
      state.delivered = t.dataset.how;
      const ttl = invoiceTotals(state.part);
      const text = [
        "HANDY BOOK STATEMENT",
        D.bike.year + " " + D.bike.name,
        state.part.name + "  " + state.part.sku,
        "Parts  " + money(ttl.goods),
        "Ship   " + money(ttl.ship),
        "Tax    " + money(ttl.tax),
        "TOTAL  " + money(ttl.total)
      ].join("\n");
      const msg = $("deliverMsg");
      if (t.dataset.how === "download") {
        const blob = new Blob([text], { type: "text/plain" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "handy-book-statement.txt";
        a.click();
        if (msg) msg.textContent = "Saved as a text file.";
      } else {
        location.href = "mailto:" + (state.quoteEmail || "") + "?subject=Handy Book statement&body=" + encodeURIComponent(text);
        if (msg) msg.textContent = "Opens your mail app.";
      }
    }
  }

  let cfg = {};

  window.HandyFlow = {
    state,
    go,
    bind(options) {
      cfg = options || {};
      bindIdentify();
      document.addEventListener("click", onClick);
      if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
    }
  };
})();
