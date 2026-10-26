// Wird in jedem Frame ausgeführt. Findet alle bedienbaren Formularelemente (auch in offenen Shadow Roots),
// vergibt stabile IDs (data-jp) und liefert Label, Typ, Optionen, Pflicht-Status und aktuellen Wert.
(frameIndex) => {
  const W = window;
  if (!W.__jp) W.__jp = { n: 0 };
  const PREFIX = `${frameIndex}-`;
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const textOf = (el) => (el ? clean(el.innerText || el.textContent || "") : "");

  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll("*")) {
      all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);

  const styleHidden = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement || (e.getRootNode && e.getRootNode().host)) {
      const st = getComputedStyle(e);
      if (st.display === "none" || st.visibility === "hidden") return true;
      if (e === document.body) break;
    }
    return false;
  };
  const visible = (el) => {
    if (!el || !el.isConnected || styleHidden(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  };
  // Hilfsfelder für Screenreader/Validierung (z. B. react-select "requiredInput") sind keine echten Eingaben.
  const ariaHidden = (el) => el.getAttribute("aria-hidden") === "true" || !!(el.closest && el.closest('[aria-hidden="true"]'));
  const shimInput = (el) => el.tabIndex < 0 && parseFloat(getComputedStyle(el).opacity || "1") === 0;
  // Datei-Inputs sind oft selbst unsichtbar. Liegen sie aber in einem ausgeblendeten Formularbereich
  // (z. B. Formular erst nach Klick auf "Apply" sichtbar), gehören sie noch nicht zur aktuellen Seite.
  const inHiddenSection = (el) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const st = getComputedStyle(e);
      if (st.display === "none" || st.visibility === "hidden") {
        return e.querySelectorAll('input:not([type="file"]):not([type="hidden"]), textarea, select').length > 0;
      }
    }
    return false;
  };
  const COOKIE_RX = /cookie|consent|gdpr|dsgvo|onetrust|usercentrics|didomi|cookiebot|sp_message|truste|borlabs|klaro|iubenda|cmp-|cmp_|\bcmp\b|cc-banner|cookiefirst|axeptio/i;
  const inCookieBanner = (el) => {
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 15; i++, e = e.parentElement || (e.getRootNode && e.getRootNode().host)) {
      const sig = `${e.id || ""} ${typeof e.className === "string" ? e.className : ""} ${e.getAttribute("aria-label") || ""}`;
      if (COOKIE_RX.test(sig)) return true;
    }
    return false;
  };

  const tag = (el) => {
    let id = el.getAttribute("data-jp");
    if (!id || !id.startsWith(PREFIX)) {
      id = PREFIX + (++W.__jp.n);
      el.setAttribute("data-jp", id);
    }
    return id;
  };

  const lookup = (root, id) => {
    try {
      return (root.getElementById && root.getElementById(id)) || document.getElementById(id);
    } catch (e) {
      return null;
    }
  };

  const labelsOf = (el) => {
    const out = [];
    const root = el.getRootNode();
    const lb = el.getAttribute("aria-labelledby");
    if (lb) out.push(lb.split(/\s+/).map((id) => textOf(lookup(root, id))).join(" "));
    const al = el.getAttribute("aria-label");
    if (al) out.push(al);
    if (el.labels && el.labels.length) out.push(Array.from(el.labels).map(textOf).join(" "));
    else if (el.id && root.querySelector) {
      try {
        const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (l) out.push(textOf(l));
      } catch (e) {}
    }
    const anc = el.closest && el.closest("label");
    if (anc && !out.includes(textOf(anc))) out.push(textOf(anc));
    return out.filter(Boolean);
  };

  const contextLabel = (el) => {
    // Text des nächsten kleinen Containers (z. B. <div><span>Vorname</span><input></div>)
    let c = el.parentElement;
    for (let hops = 0; c && hops < 5; hops++, c = c.parentElement) {
      const t = textOf(c);
      if (t && t.length <= 240) return t;
      if (t && t.length > 240) {
        // Vorangehende Geschwister durchsuchen
        let p = el.previousElementSibling || (el.parentElement && el.parentElement.previousElementSibling);
        for (let i = 0; p && i < 3; i++, p = p.previousElementSibling) {
          const pt = textOf(p);
          if (pt && pt.length <= 200) return pt;
        }
        return "";
      }
    }
    return "";
  };

  const describedBy = (el) => {
    const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    const root = el.getRootNode();
    return clean(ids.map((id) => textOf(lookup(root, id))).join(" ")).slice(0, 300);
  };

  const labelOf = (el) => {
    const parts = labelsOf(el);
    if (!parts.length) {
      const ctx = contextLabel(el);
      if (ctx) parts.push(ctx);
    }
    const ph = el.getAttribute("placeholder");
    if (ph && !parts.join(" ").includes(ph)) parts.push(`(Platzhalter: ${ph})`);
    if (!parts.length && el.name) parts.push(el.name);
    return clean(parts.join(" | ")).slice(0, 300);
  };

  // Upload-Felder heißen oft nur "Attach"/"Hochladen" – worum es geht (Lebenslauf, Anschreiben), steht drumherum.
  const GENERIC_UPLOAD_RX = /^(\+\s*)?(attach( a)?( file)?|upload( a)?( file)?|datei (auswählen|hochladen|anhängen)|choose file|browse|durchsuchen|hochladen|auswählen|select (a )?file|drop (your )?files? here|dateien? hierher ziehen|anhängen)$/i;
  const uploadContext = (el) => {
    let c = el.parentElement;
    for (let hops = 0; c && hops < 6; hops++, c = c.parentElement) {
      const t = textOf(c);
      if (t.length > 300) break;
      const core = clean(t.replace(/attach|dropbox|google drive|enter manually|manuell eingeben|upload|hochladen|datei|choose file|browse|durchsuchen|accepted file types?:?[^.]*\.?|max(imum)?\.? (file )?size[^.]*\.?|\+/gi, " "));
      if (core.length >= 4) return t.slice(0, 200);
    }
    return "";
  };

  const isRequired = (el, label) =>
    !!(el.required || el.getAttribute("aria-required") === "true" || /\*\s*$|\*\s*\||\(required\)|pflicht/i.test(label));

  const groupQuestion = (members, optionLabels) => {
    const fs = members[0].closest && members[0].closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg) return textOf(lg);
    }
    const rg = members[0].closest && members[0].closest('[role="radiogroup"],[role="group"]');
    if (rg) {
      const l = labelsOf(rg);
      if (l.length) return l.join(" ");
    }
    // kleinster Container, der alle Mitglieder enthält
    let c = members[0].parentElement;
    while (c && !members.every((m) => c.contains(m))) c = c.parentElement;
    for (let hops = 0; c && hops < 3; hops++, c = c.parentElement) {
      let t = textOf(c);
      for (const o of optionLabels) if (o) t = t.replace(o, " ");
      t = clean(t);
      if (t) return t.slice(0, 300);
    }
    return "";
  };

  const PLACEHOLDER_RX = /^(|-+|select.*|choose.*|please select.*|bitte (wählen|auswählen).*|auswählen.*|wählen.*|keine auswahl|\.\.\.)$/i;
  const fields = [];
  const seenGroups = new Set();
  const TEXT_TYPES = new Set(["", "text", "email", "tel", "url", "number", "search", "date", "month", "week", "time", "datetime-local"]);

  for (const el of all) {
    const t = el.tagName;
    if (t === "INPUT") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (["hidden", "submit", "button", "image", "reset"].includes(type)) continue;
      if (type === "file") {
        if (inHiddenSection(el)) continue;
        let label = labelOf(el) || contextLabel(el.parentElement || el);
        if (!label || GENERIC_UPLOAD_RX.test(label.split(" | ")[0].trim())) label = uploadContext(el) || label;
        fields.push({ id: tag(el), kind: "file", label, required: isRequired(el, label), accept: el.accept || "",
          name: el.name || "", html_id: el.id || "",
          multiple: !!el.multiple, value: el.files && el.files.length ? Array.from(el.files).map((f) => f.name).join(", ") : "",
          hint: describedBy(el) });
        continue;
      }
      if (type === "radio" || type === "checkbox") {
        const name = el.name;
        const vis = visible(el) || (el.labels && Array.from(el.labels).some(visible)) || (el.closest("label") && visible(el.closest("label")));
        if (!vis) continue;
        const root = el.getRootNode();
        const members = name && root.querySelectorAll
          ? Array.from(root.querySelectorAll(`input[type="${type}"][name="${CSS.escape(name)}"]`))
          : [el];
        if (type === "checkbox" && members.length <= 1) {
          const label = labelOf(el);
          fields.push({ id: tag(el), kind: "checkbox", label, required: isRequired(el, label), value: el.checked ? "checked" : "",
            hint: describedBy(el) });
          continue;
        }
        const key = `${type}:${name}`;
        if (seenGroups.has(key)) continue;
        seenGroups.add(key);
        const options = members.map((m) => ({ id: tag(m), label: clean(labelsOf(m).join(" ")) || m.value, checked: m.checked }));
        const question = groupQuestion(members, options.map((o) => o.label));
        fields.push({ id: tag(members[0]), kind: type === "radio" ? "radio" : "checkbox_group", label: question,
          required: members.some((m) => m.required) || /\*/.test(question), options,
          value: options.filter((o) => o.checked).map((o) => o.label).join("; ") });
        continue;
      }
      if (!visible(el) || ariaHidden(el) || shimInput(el)) continue;
      if (type === "password") {
        fields.push({ id: tag(el), kind: "password", label: labelOf(el), required: !!el.required, value: "" });
        continue;
      }
      if (!TEXT_TYPES.has(type)) continue;
      const label = labelOf(el);
      const role = el.getAttribute("role");
      const combo = role === "combobox" || el.getAttribute("aria-autocomplete") === "list" || !!el.getAttribute("aria-controls") && el.getAttribute("aria-expanded") !== null;
      fields.push({ id: tag(el), kind: combo ? "combobox" : (type === "date" ? "date" : "text"), input_type: type || "text",
        label, required: isRequired(el, label), value: el.value || "", hint: describedBy(el),
        autocomplete: el.getAttribute("autocomplete") || "", name: el.name || "",
        max_length: el.maxLength > 0 ? el.maxLength : 0, invalid: el.getAttribute("aria-invalid") === "true" });
    } else if (t === "TEXTAREA") {
      if (!visible(el) || ariaHidden(el) || shimInput(el)) continue;
      const label = labelOf(el);
      fields.push({ id: tag(el), kind: "textarea", label, required: isRequired(el, label), value: el.value || "",
        hint: describedBy(el), max_length: el.maxLength > 0 ? el.maxLength : 0, name: el.name || "",
        invalid: el.getAttribute("aria-invalid") === "true" });
    } else if (t === "SELECT") {
      if (!visible(el) && !(el.parentElement && visible(el.parentElement))) continue;
      const label = labelOf(el);
      const options = Array.from(el.options).slice(0, 250).map((o) => ({ label: clean(o.text), value: o.value }));
      const chosen = Array.from(el.selectedOptions).filter((o) => o.value !== "" && !PLACEHOLDER_RX.test(clean(o.text)));
      fields.push({ id: tag(el), kind: "select", label, required: isRequired(el, label), multiple: !!el.multiple, options,
        value: chosen.map((o) => clean(o.text)).join("; "), name: el.name || "",
        invalid: el.getAttribute("aria-invalid") === "true" });
    } else if (el.isContentEditable && el.getAttribute("contenteditable") !== null && !(el.parentElement && el.parentElement.isContentEditable)) {
      if (!visible(el)) continue;
      const label = labelOf(el);
      fields.push({ id: tag(el), kind: "richtext", label, required: isRequired(el, label), value: textOf(el).slice(0, 500) });
    } else {
      const role = el.getAttribute && el.getAttribute("role");
      if (!role || !visible(el)) continue;
      if ((role === "combobox" || (role === "button" && el.getAttribute("aria-haspopup") === "listbox")) && t !== "INPUT") {
        const label = labelOf(el);
        const shown = textOf(el).slice(0, 120);
        fields.push({ id: tag(el), kind: "combobox", label, required: isRequired(el, label),
          value: PLACEHOLDER_RX.test(shown) ? "" : shown });
      } else if ((role === "radio" || role === "checkbox" || role === "switch") && !el.querySelector("input")) {
        const label = labelOf(el) || textOf(el);
        fields.push({ id: tag(el), kind: role === "radio" ? "aria_radio" : "aria_checkbox", label,
          required: isRequired(el, label), value: el.getAttribute("aria-checked") === "true" ? "checked" : "" });
      }
    }
  }

  // Buttons und Links, die den Ablauf steuern
  const ACTION_RX = /apply|bewerb|submit|absenden|senden|send|weiter|next|continue|fortfahren|review|überprüf|ueberpruef|start|jetzt|interessiert|upload|hochladen|lebenslauf|resume|cv|manuell|manually|accept|akzeptier|zustimm|agree|allow|alle|cookie|ok\b|got it|verstanden|schließen|close|autofill|ausfüllen/i;
  const AUTOFILL_RX = /auto-?fill|automatisch ausfüllen|(aus|mit) (dem |meinem )?lebenslauf (ausfüllen|befüllen|übernehmen|bewerben)|lebenslauf (importieren|hochladen und ausfüllen)|import (from )?(your )?(resume|cv)|(resume|cv) (import|parsing|autofill)|fill (out )?(the form )?(from|with) (your )?(resume|cv)|apply with (your )?(resume|cv)|mit lebenslauf bewerben|quick ?apply/i;
  const found = [];
  for (const el of all) {
    const t = el.tagName;
    const role = el.getAttribute && el.getAttribute("role");
    const isBtn = t === "BUTTON" || (t === "INPUT" && /^(submit|button)$/i.test(el.type)) || role === "button" || role === "link" || t === "A";
    if (!isBtn || !visible(el)) continue;
    if (role === "button" && el.getAttribute("aria-haspopup") === "listbox") continue;
    const text = clean(textOf(el) || el.value || el.getAttribute("aria-label") || el.title || "").slice(0, 120);
    if (!text) continue;
    if (t === "A" && !ACTION_RX.test(text)) continue;
    const btn = { id: tag(el), text, kind: t === "A" ? "link" : (el.type === "submit" || /submit/i.test(el.getAttribute("type") || "") ? "submit" : "button"),
      href: t === "A" ? (el.href || "").slice(0, 300) : "", disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
      form: !!(el.closest && el.closest("form")), autofill: AUTOFILL_RX.test(text), cookie: inCookieBanner(el) };
    // Wichtiges zuerst: Formular-Buttons, Autofill, Ablauf-Buttons; Navigation zuletzt.
    btn._rank = (btn.form ? 0 : 2) + (btn.autofill ? -2 : 0) + (ACTION_RX.test(text) ? 0 : 1) + (btn.cookie ? 1 : 0);
    found.push(btn);
    if (found.length >= 400) break;
  }
  const buttons = found.map((b, i) => [b, i]).sort((a, b) => a[0]._rank - b[0]._rank || a[1] - b[1]).slice(0, 80)
    .sort((a, b) => a[1] - b[1]).map(([b]) => { delete b._rank; return b; });

  // Fehlermeldungen
  const errors = [];
  for (const el of all) {
    const cls = typeof el.className === "string" ? el.className : "";
    const role = el.getAttribute && el.getAttribute("role");
    if (role === "alert" || /(^|[\s_-])(error|invalid|danger)([\s_-]|$)/i.test(cls) || el.getAttribute("aria-live") === "assertive") {
      if (!visible(el)) continue;
      const t = textOf(el);
      if (t && t.length < 220 && !errors.includes(t)) errors.push(t);
      if (errors.length >= 20) break;
    }
  }

  // CAPTCHA-Signale
  const captcha = [];
  for (const el of all) {
    const src = (el.tagName === "IFRAME" ? el.src || "" : "").toLowerCase();
    const cls = typeof el.className === "string" ? el.className : "";
    const hit = /recaptcha|hcaptcha|turnstile|challenges\.cloudflare|captcha/.test(src) ||
      /g-recaptcha|h-captcha|cf-turnstile|frc-captcha/.test(cls) || (el.getAttribute && el.getAttribute("data-sitekey"));
    if (!hit) continue;
    const r = el.getBoundingClientRect();
    if (/size=invisible/.test(src) || (el.getAttribute && el.getAttribute("data-size") === "invisible")) continue;
    const challenge = /bframe|challenge|api2\/anchor|hcaptcha|turnstile/.test(src) || /h-captcha|cf-turnstile|g-recaptcha/.test(cls);
    captcha.push({ src: src.slice(0, 120), cls: cls.slice(0, 60), visible: visible(el) && r.width > 40 && r.height > 40, challenge });
  }

  const headings = Array.from(document.querySelectorAll("h1,h2,h3")).filter(visible).map(textOf).filter(Boolean).slice(0, 15);
  return {
    url: location.href,
    title: document.title,
    fields,
    buttons,
    errors,
    captcha,
    headings,
    text: (document.body ? document.body.innerText : "").slice(0, frameIndex === 0 ? 6000 : 1500),
  };
}
