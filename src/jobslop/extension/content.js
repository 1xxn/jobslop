// jobslop Assistent – läuft in jedem Frame der Seite: trägt die von jobslop geplanten Werte ein (jobslopRun)
// und zeigt im obersten Frame ein kleines Panel (Fragen, Prüfen, Absenden). Werte kommen nur von deinem jobslop.
(() => {
  if (self.__jobslopContent) return;
  self.__jobslopContent = true;

  // ---------------------------------------------------------------- Elemente (auch in offenen Shadow Roots)
  function byId(id) {
    const selector = `[data-jp="${CSS.escape(id)}"]`;
    const walk = (root) => {
      const hit = root.querySelector(selector);
      if (hit) return hit;
      for (const el of root.querySelectorAll("*")) {
        if (el.shadowRoot) {
          const found = walk(el.shadowRoot);
          if (found) return found;
        }
      }
      return null;
    };
    return walk(document);
  }
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));
  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && st.visibility !== "hidden" && st.display !== "none";
  };

  // Wert über den nativen Setter setzen – sonst übersehen React & Co. die Änderung
  function setValue(el, value) {
    const proto =
      el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    el.focus();
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    fire(el, "input");
    fire(el, "change");
  }

  function press(el) {
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
    el.click();
  }

  function similarity(a, b) {
    a = norm(a);
    b = norm(b);
    if (!a || !b) return 0;
    if (a === b) return 1;
    if (a.includes(b) || b.includes(a)) return (0.9 * Math.min(a.length, b.length)) / Math.max(a.length, b.length) + 0.1;
    const grams = (s) => {
      const out = new Map();
      for (let i = 0; i < s.length - 1; i++) out.set(s.slice(i, i + 2), (out.get(s.slice(i, i + 2)) || 0) + 1);
      return out;
    };
    const A = grams(a);
    const B = grams(b);
    let shared = 0;
    for (const [g, n] of A) shared += Math.min(n, B.get(g) || 0);
    return (2 * shared) / (a.length - 1 + (b.length - 1) || 1);
  }

  // ---------------------------------------------------------------- Ausführen (wie apply/executor.py)
  async function run(op, files) {
    const el = byId(op.field_id);
    if (!el && op.op !== "check") return { ok: false, detail: "Element ist nicht mehr auf der Seite" };
    try {
      switch (op.op) {
        case "click":
          el.scrollIntoView({ block: "center" });
          press(el);
          return { ok: true, detail: "geklickt" };
        case "fill": {
          el.scrollIntoView({ block: "center" });
          setValue(el, op.value);
          fire(el, "blur");
          const now = el.value || "";
          if (!now.trim()) return { ok: false, detail: "Feld blieb leer" };
          return { ok: true, detail: now.trim() === String(op.value).trim() ? "ok" : `umformatiert zu '${now.slice(0, 60)}'` };
        }
        case "richtext":
          el.focus();
          document.execCommand("selectAll", false);
          document.execCommand("insertText", false, op.value);
          fire(el, "input");
          return { ok: !!(el.innerText || "").trim(), detail: "eingegeben" };
        case "select": {
          const options = Array.from(el.options);
          const opt =
            options.find((o) => op.option_value !== "" && o.value === op.option_value) ||
            options.find((o) => norm(o.textContent) === norm(op.option_label));
          if (!opt) return { ok: false, detail: `Option '${op.option_label}' nicht gefunden` };
          setValue(el, opt.value);
          return { ok: el.value === opt.value, detail: `gewählt: ${op.option_label}` };
        }
        case "check": {
          for (const id of op.ids) {
            const box = byId(id);
            if (!box) return { ok: false, detail: `Option ${id} nicht gefunden` };
            const isInput = box.tagName === "INPUT";
            const state = () => (isInput ? box.checked : box.getAttribute("aria-checked") === "true");
            if (state() !== op.checked) {
              // Visuell versteckte Inputs: über das Label klicken
              const target = isInput && !visible(box) ? (box.labels && box.labels[0]) || box.closest("label") || box : box;
              press(target);
              await sleep(80);
            }
            if (state() !== op.checked) return { ok: false, detail: "Status ließ sich nicht setzen" };
          }
          return { ok: true, detail: op.value ? `gewählt: ${op.value}` : op.checked ? "an" : "aus" };
        }
        case "combobox": {
          el.scrollIntoView({ block: "center" });
          press(el);
          if (el.tagName === "INPUT") setValue(el, String(op.value).slice(0, 40));
          await sleep(600);
          const options = Array.from(document.querySelectorAll('[role="option"], [class*="option"]')).filter(visible).slice(0, 150);
          let best = -1;
          let score = 0;
          options.forEach((o, i) => {
            const sc = similarity(o.innerText || o.textContent, op.value);
            if (sc > score) [best, score] = [i, sc];
          });
          if (best >= 0 && score >= 0.5) {
            press(options[best]);
            return { ok: true, detail: `gewählt: ${(options[best].innerText || "").trim().slice(0, 60)}` };
          }
          if (el.tagName === "INPUT") {
            el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
            return { ok: true, detail: "per Enter übernommen" };
          }
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          return { ok: false, detail: `Option '${op.value}' im Dropdown nicht gefunden` };
        }
        case "upload": {
          const input =
            el.tagName === "INPUT" && el.type === "file"
              ? el
              : (el.closest("form, section, fieldset, div") || document).querySelector('input[type="file"]');
          if (!input) return { ok: false, detail: "Kein Datei-Feld gefunden – bitte die Datei selbst auswählen" };
          const transfer = new DataTransfer();
          for (const f of input.multiple ? files : files.slice(0, 1)) {
            const bytes = Uint8Array.from(atob(f.data), (c) => c.charCodeAt(0));
            transfer.items.add(new File([bytes], f.name, { type: f.type }));
          }
          input.files = transfer.files;
          fire(input, "input");
          fire(input, "change");
          await sleep(1200); // Lebenslauf-Parser der Seite arbeiten lassen
          return { ok: input.files.length > 0, detail: `hochgeladen: ${Array.from(input.files).map((f) => f.name).join(", ")}` };
        }
      }
      return { ok: false, detail: `Unbekannte Anweisung ${op.op}` };
    } catch (e) {
      return { ok: false, detail: String((e && e.message) || e).slice(0, 200) };
    }
  }
  self.jobslopRun = run;

  if (window.top !== window) return; // Panel nur im obersten Frame

  // ---------------------------------------------------------------- Panel
  const CSS_TEXT = `
    :host { all: initial; }
    .card { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; width: 360px; max-height: 70vh;
      overflow: auto; font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1b1f;
      background: #fff; border: 1px solid #d9d6e0; border-radius: 12px; box-shadow: 0 8px 28px rgba(0,0,0,.18); }
    header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #ece9f1; }
    header b { font-size: 13px; } header span { color: #6b6875; font-size: 12px; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; flex: 1; }
    .x { border: 0; background: none; font-size: 16px; cursor: pointer; color: #6b6875; }
    .body { padding: 12px; display: grid; gap: 10px; }
    .muted { color: #6b6875; } .warn { color: #8a5300; } .err { color: #b3261e; } .ok { color: #1b6e3a; }
    .row { display: grid; grid-template-columns: 40% 1fr; gap: 6px; padding: 4px 0; border-bottom: 1px solid #f1eff5; }
    .row span:first-child { color: #6b6875; overflow-wrap: anywhere; } .row span:last-child { overflow-wrap: anywhere; }
    .badge { display: inline-block; margin-left: 4px; padding: 0 6px; border-radius: 6px; background: #fff1d6; color: #8a5300; font-size: 11px; }
    label { display: grid; gap: 4px; } input, select { font: inherit; padding: 6px 8px; border: 1px solid #cfccd6; border-radius: 8px; }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
    button.b { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid #cfccd6; background: #fff; cursor: pointer; }
    button.primary { background: #5b4fd6; border-color: #5b4fd6; color: #fff; }
    .spin { width: 14px; height: 14px; border: 2px solid #d9d6e0; border-top-color: #5b4fd6; border-radius: 50%;
      animation: s 0.8s linear infinite; display: inline-block; vertical-align: -2px; margin-right: 6px; }
    @keyframes s { to { transform: rotate(360deg); } }
    @media (prefers-color-scheme: dark) {
      .card { background: #1d1b22; color: #e7e3ee; border-color: #3a3642; } header { border-color: #2e2b35; }
      .row { border-color: #2a2730; } input, select, button.b { background: #26232d; color: inherit; border-color: #45404f; }
      button.primary { background: #8b80ff; border-color: #8b80ff; color: #120f24; }
    }`;

  let host = null;
  let root = null;

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (v !== undefined && v !== null) el.setAttribute(k, v);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }
  const send = (type, extra) => chrome.runtime.sendMessage({ type, ...(extra || {}) });
  const button = (text, type, primary, extra) =>
    h("button", { class: primary ? "b primary" : "b", on: { click: () => send(type, extra) } }, text);

  function mount() {
    if (host && host.isConnected) return;
    host = document.createElement("jobslop-assistant");
    root = host.attachShadow({ mode: "open" });
    document.documentElement.append(host);
  }

  function render(view) {
    if (view.state === "closed") {
      if (host) host.remove();
      host = null;
      return;
    }
    mount();
    const job = view.job ? `${view.job.company} – ${view.job.title}` : "";
    const body = h("div", { class: "body" });
    const card = h(
      "div",
      { class: "card", role: "dialog", "aria-label": "jobslop" },
      h("header", {}, h("b", {}, "jobslop"), h("span", { title: job }, job), h("button", { class: "x", title: "Schließen", on: { click: () => send("jobslop:cancel") } }, "×")),
      body,
    );
    switch (view.state) {
      case "busy":
        body.append(h("div", {}, h("span", { class: "spin" }), view.text || "Arbeite …"));
        break;
      case "wait":
        body.append(h("div", {}, view.text));
        body.append(h("div", { class: "actions" }, view.selfSubmit ? null : button("Weiter", "jobslop:continue", true), button("Abbrechen", "jobslop:cancel")));
        break;
      case "info":
        body.append(h("div", { class: "muted" }, view.text));
        break;
      case "done":
        body.append(h("div", { class: "ok" }, view.text));
        body.append(h("div", { class: "actions" }, button("Schließen", "jobslop:cancel", true)));
        break;
      case "error":
        body.append(h("div", { class: "err" }, view.text));
        body.append(h("div", { class: "actions" }, view.retry ? button("Erneut versuchen", "jobslop:continue", true) : null, button("Schließen", "jobslop:cancel")));
        break;
      case "questions": {
        body.append(h("div", {}, "Diese Angaben stehen nicht in deinem Profil. jobslop merkt sich deine Antworten."));
        const inputs = view.questions.map((q) => {
          const control = q.options && q.options.length
            ? h("select", {}, h("option", { value: "" }, "Bitte wählen …"), q.options.map((o) => h("option", { value: o }, o)))
            : h("input", { type: "text" });
          body.append(h("label", {}, h("span", {}, q.question), control, q.why ? h("small", { class: "muted" }, q.why) : null));
          return [q, control];
        });
        const submit = () =>
          send("jobslop:answers", {
            answers: inputs.filter(([, c]) => c.value.trim()).map(([q, c]) => ({ question: q.label || q.question, answer: c.value.trim() })),
          });
        body.append(h("div", { class: "actions" }, h("button", { class: "b primary", on: { click: submit } }, "Antworten & weiter"), button("Abbrechen", "jobslop:cancel")));
        break;
      }
      case "review": {
        const review = view.review || { rows: [], missing: [] };
        body.append(h("div", {}, h("b", {}, "Vor dem Absenden prüfen")));
        for (const r of review.rows) {
          body.append(h("div", { class: "row" }, h("span", {}, r.label || r.field_id), h("span", {}, String(r.value || "").slice(0, 160), r.confidence === "low" ? h("span", { class: "badge" }, "unsicher") : null)));
        }
        if (review.missing && review.missing.length) body.append(h("div", { class: "warn" }, `Pflichtfelder leer: ${review.missing.join(", ")}`));
        if (view.failed && view.failed.length) body.append(h("div", { class: "warn" }, `Nicht geklappt: ${view.failed.slice(0, 4).join("; ")}`));
        body.append(h("div", { class: "muted" }, "Du kannst im Formular noch alles ändern."));
        body.append(h("div", { class: "actions" }, button("Abbrechen", "jobslop:cancel"), button("Ich sende selbst", "jobslop:self"), button("Absenden", "jobslop:submit", true)));
        break;
      }
    }
    const style = h("style", {}, CSS_TEXT);
    root.replaceChildren(style, card);
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "jobslop:ui") render(msg.view || {});
  });
})();
