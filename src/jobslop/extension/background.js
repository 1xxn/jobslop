// jobslop Assistent – Ablaufsteuerung (Service Worker).
// Spricht nur mit deinem lokalen jobslop (config.js) und arbeitet nur in dem Tab, in dem du auf das Symbol geklickt
// hast. Abgeschickt wird erst nach deinem Klick auf „Absenden“; Sicherheitsabfragen (CAPTCHAs) löst du selbst.
importScripts("config.js");

const CFG = self.JOBSLOP_CONFIG;
// Dieselbe Liste wie die Engine (extract.CAPTCHA_HOST_HINTS) – jobslop schreibt sie in config.js
const isCaptcha = (url) => CFG.captchaHosts.some((host) => (url || "").toLowerCase().includes(host));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const running = new Set(); // Tabs, für die gerade ein Schritt läuft

// ------------------------------------------------------------------ jobslop
async function api(path, body) {
  const init = { method: body === undefined ? "GET" : "POST", headers: { "X-Jobslop": "1", "X-Jobslop-Token": CFG.token } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(CFG.server + path, init);
  } catch {
    throw new Error("jobslop ist nicht erreichbar – läuft jobslop auf diesem Rechner?");
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // Klartext-Fehler: Statuszeile genügt
  }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `jobslop antwortet mit ${res.status}`);
  }
  return data;
}

async function fetchFile(appId, value, index) {
  const url = `${CFG.server}/api/assist/file?application_id=${appId}&value=${encodeURIComponent(value)}&index=${index}`;
  const res = await fetch(url, { headers: { "X-Jobslop-Token": CFG.token } });
  if (!res.ok) throw new Error("Datei bei jobslop nicht verfügbar");
  const bytes = new Uint8Array(await res.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return { data: btoa(binary), type: res.headers.get("content-type") || "application/pdf" };
}

// ------------------------------------------------------------------ Zustand pro Tab (überlebt Seitenwechsel)
const key = (tabId) => `tab:${tabId}`;
async function load(tabId) {
  return (await chrome.storage.session.get(key(tabId)))[key(tabId)] || null;
}
async function save(tabId, s) {
  await chrome.storage.session.set({ [key(tabId)]: s });
}

// ------------------------------------------------------------------ Seite
// Frames des Tabs ohne CAPTCHA-Frames – deren Adresse kommt vom Browser (webNavigation), nicht aus einem Skript im
// Frame: in eine Sicherheitsabfrage wird nie Code eingeschleust.
async function frames(tabId) {
  const all = (await chrome.webNavigation.getAllFrames({ tabId }).catch(() => null)) || [];
  return all.filter((f) => f.frameId === 0 || !isCaptcha(f.url));
}

async function inject(tabId) {
  const frameIds = (await frames(tabId)).map((f) => f.frameId);
  if (!frameIds.length) return;
  await chrome.scripting
    .executeScript({ target: { tabId, frameIds }, files: ["extract.js", "content.js"] })
    .catch(() => {});
}

async function ui(tabId, view) {
  await chrome.tabs.sendMessage(tabId, { type: "jobslop:ui", view }, { frameId: 0 }).catch(() => {});
}

async function show(tabId, s, view) {
  s.view = { ...view, job: s.job };
  await save(tabId, s);
  await ui(tabId, s.view);
}

async function readPage(tabId) {
  const all = (await chrome.webNavigation.getAllFrames({ tabId }).catch(() => null)) || [];
  // Jeder Frame braucht seine eigene Nummer – also einzeln, aber parallel auslesen
  const extract = async (frame) => {
    if (frame.frameId !== 0 && isCaptcha(frame.url)) {
      // CAPTCHA-Frames nie auslesen oder bedienen – jobslop meldet nur, dass eine da ist
      return { index: frame.frameId, data: { url: frame.url, title: "", fields: [], buttons: [], errors: [], captcha: [], headings: [], text: "" } };
    }
    try {
      const [result] = await chrome.scripting.executeScript({
        target: { tabId, frameIds: [frame.frameId] },
        func: (index) => (self.jobslopExtract ? self.jobslopExtract(index) : null),
        args: [frame.frameId],
      });
      return result && result.result ? { index: frame.frameId, data: result.result } : null;
    } catch {
      return null; // Frame während des Ladens weg – beim nächsten Schritt wieder dabei
    }
  };
  const jsonLd = chrome.scripting
    .executeScript({
      target: { tabId, frameIds: [0] },
      func: () =>
        Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
          .map((el) => el.textContent || "")
          .filter((text) => /JobPosting/.test(text))
          .slice(0, 3),
    })
    .then(([result]) => (result && result.result) || [])
    .catch(() => []); // ohne JSON-LD: jobslop nimmt Seitentitel und Überschrift
  const [read, ld] = await Promise.all([Promise.all(all.map(extract)), jsonLd]);
  return { frames: read.filter(Boolean), ld };
}

const frameOf = (id) => parseInt(String(id).split("-")[0], 10) || 0;

async function runIn(tabId, op, files) {
  const frame = frameOf(op.field_id);
  if (frame !== 0 && !(await frames(tabId)).some((f) => f.frameId === frame)) {
    return { ok: false, detail: "Frame nicht (mehr) da oder eine Sicherheitsabfrage" };
  }
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId, frameIds: [frame] },
      func: (o, f) => self.jobslopRun(o, f),
      args: [op, files || null],
    });
    return (result && result.result) || { ok: false, detail: "keine Antwort aus dem Frame" };
  } catch (e) {
    return { ok: false, detail: String((e && e.message) || e) };
  }
}

async function tabUrl(tabId) {
  const [result] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: () => location.href });
  return (result && result.result) || "";
}

// ------------------------------------------------------------------ Ablauf
async function step(tabId) {
  if (running.has(tabId)) return;
  const s = await load(tabId);
  if (!s || !s.active) return;
  running.add(tabId);
  s.awaitNav = false; // sofort speichern: sonst startet der Zeitgeber nach einem Klick einen zweiten Schritt
  s.waiting = null;
  await save(tabId, s);
  try {
    await ui(tabId, { state: "busy", text: "Lese das Formular …", job: s.job });
    const page = await readPage(tabId);
    const r = await api("/api/assist/step", {
      frames: page.frames,
      application_id: s.appId,
      history: s.history.slice(-20),
      submit_clicked: s.submitClicked,
      step: s.step + 1,
      ld_json: page.ld,
    });
    s.step += 1;
    s.appId = r.application_id || s.appId;
    s.job = r.job || s.job;
    if (r.blocked) {
      s.active = false;
      return await show(tabId, s, { state: "error", text: r.blocked });
    }
    if (r.confirmed) {
      s.active = false;
      return await show(tabId, s, { state: "done", text: "Bewerbung abgeschickt und in jobslop eingetragen." });
    }
    if (r.wait) {
      s.waiting = "user";
      return await show(tabId, s, { state: "wait", text: r.wait });
    }

    const plan = r.plan;
    await ui(tabId, { state: "busy", text: plan.summary || "Fülle aus …", job: s.job });
    const results = [];
    for (const op of r.ops) {
      let result;
      if (op.op === "error") {
        result = { ok: false, detail: op.detail };
      } else if (op.op === "upload") {
        try {
          const files = [];
          for (let i = 0; i < op.names.length; i++) files.push({ name: op.names[i], ...(await fetchFile(s.appId, op.value, i)) });
          result = await runIn(tabId, op, files);
        } catch (e) {
          result = { ok: false, detail: String((e && e.message) || e) };
        }
      } else {
        result = await runIn(tabId, op);
      }
      results.push({ ...op, ...result, value: op.op === "upload" ? op.names.join(", ") : op.value });
      await sleep(120);
    }
    if (results.length) await api("/api/assist/result", { application_id: s.appId, step: s.step, summary: plan.summary, results });
    const failed = results.filter((x) => !x.ok).map((x) => `${x.label || x.field_id}: ${x.detail}`);
    s.history.push(`Schritt ${s.step}: ${plan.summary} – ${results.length - failed.length}/${results.length} Aktionen ok`);
    s.history.push(...(r.notes || []));
    if (failed.length) s.history.push(`Fehlgeschlagen: ${failed.slice(0, 5).join("; ")}`);

    if (plan.questions.length) {
      s.waiting = "questions";
      return await show(tabId, s, { state: "questions", questions: plan.questions, failed });
    }
    switch (plan.next_step) {
      case "click_apply":
      case "click_next":
        if (!plan.next_target_id) {
          s.waiting = "user";
          return await show(tabId, s, { state: "wait", text: "Ich finde keinen Weiter-Button – bitte selbst klicken, dann „Weiter“." });
        }
        s.history.push(`Schritt ${s.step}: Klick auf ${plan.next_target_id}`);
        return await clickThenContinue(tabId, s, plan.next_target_id);
      case "click_submit":
        s.waiting = "submit";
        s.submitTarget = plan.next_target_id;
        return await show(tabId, s, { state: "review", review: r.review, failed });
      case "done":
        if (s.submitClicked) {
          await api("/api/assist/finish", { application_id: s.appId, status: "submitted", url: await tabUrl(tabId), message: plan.summary });
          s.active = false;
          return await show(tabId, s, { state: "done", text: "Abgeschickt – keine eindeutige Bestätigung erkannt, bitte kurz prüfen." });
        }
        s.waiting = "user";
        return await show(tabId, s, { state: "wait", text: `${plan.summary} – bitte prüfen, dann „Weiter“.` });
      case "abort":
        s.active = false;
        await api("/api/assist/finish", { application_id: s.appId, status: "aborted", message: plan.summary });
        return await show(tabId, s, { state: "error", text: `Abgebrochen: ${plan.summary}` });
      default:
        s.waiting = "user";
        return await show(tabId, s, { state: "wait", text: plan.summary || "Bitte im Formular übernehmen, dann „Weiter“." });
    }
  } catch (e) {
    s.waiting = "user";
    return await show(tabId, s, { state: "error", text: String((e && e.message) || e), retry: true });
  } finally {
    running.delete(tabId);
  }
}

// Klick (Weiter, Bewerben, freigegebenes Absenden). Lädt die Seite neu, geht es über onUpdated weiter;
// bleibt sie stehen (Formulare ohne Seitenwechsel), nach einer kurzen Pause.
async function clickThenContinue(tabId, s, targetId) {
  s.awaitNav = true;
  await save(tabId, s);
  await runIn(tabId, { op: "click", field_id: targetId });
  setTimeout(async () => {
    const now = await load(tabId);
    if (now && now.active && now.awaitNav) {
      await inject(tabId);
      await step(tabId);
    }
  }, 2500);
}

async function start(tab) {
  await inject(tab.id);
  const existing = await load(tab.id);
  if (existing && existing.active) {
    if (existing.view) await ui(tab.id, existing.view);
    return;
  }
  try {
    await api("/api/assist/status");
  } catch (e) {
    await ui(tab.id, { state: "error", text: String((e && e.message) || e) });
    return;
  }
  await save(tab.id, { active: true, appId: null, job: null, step: 0, history: [], submitClicked: false });
  await step(tab.id);
}
self.jobslopStart = start; // für Tests

// Antworten aus dem Panel: höchstens 50, Texte gekürzt – alles andere verwirft der Server ohnehin
function cleanAnswers(answers) {
  if (!Array.isArray(answers)) return [];
  return answers
    .filter((a) => a && typeof a.question === "string" && typeof a.answer === "string")
    .slice(0, 50)
    .map((a) => ({ question: a.question.slice(0, 500), answer: a.answer.slice(0, 5000) }));
}

async function handle(tabId, msg) {
  const s = await load(tabId);
  switch (msg.type) {
    case "jobslop:continue":
      if (!s) return;
      s.active = true;
      await save(tabId, s);
      return step(tabId);
    case "jobslop:answers": {
      if (!s || s.waiting !== "questions") return;
      const answers = cleanAnswers(msg.answers);
      s.waiting = null;
      await api("/api/assist/answers", { application_id: s.appId, answers });
      s.history.push(`${answers.length} Rückfrage(n) beantwortet und gespeichert`);
      await save(tabId, s);
      return step(tabId);
    }
    case "jobslop:submit":
      if (!s || s.waiting !== "submit") return;
      s.submitClicked = true;
      s.waiting = null;
      s.history.push("Absenden geklickt (von dir freigegeben)");
      await ui(tabId, { state: "busy", text: "Sende ab …", job: s.job });
      return clickThenContinue(tabId, s, s.submitTarget);
    case "jobslop:self":
      if (!s || s.waiting !== "submit") return;
      s.submitClicked = true;
      s.awaitNav = true;
      s.waiting = "self";
      return show(tabId, s, { state: "wait", text: "Sende das Formular selbst ab – ich erkenne die Bestätigung und trage die Bewerbung ein.", selfSubmit: true });
    case "jobslop:cancel":
      if (s && s.appId && s.active) {
        await api("/api/assist/finish", { application_id: s.appId, status: "aborted", message: "In der Erweiterung abgebrochen" }).catch(() => {});
      }
      await chrome.storage.session.remove(key(tabId));
      return ui(tabId, { state: "closed" });
  }
}

chrome.action.onClicked.addListener((tab) => start(tab));

// Nur das Panel spricht mit dem Service Worker: eigene Erweiterung, oberster Frame eines Tabs, bekannte Nachricht
const PANEL_MESSAGES = new Set(["jobslop:continue", "jobslop:answers", "jobslop:submit", "jobslop:self", "jobslop:cancel"]);
chrome.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab && sender.tab.id;
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !tabId) return false;
  if (msg && typeof msg.type === "string" && PANEL_MESSAGES.has(msg.type)) handle(tabId, msg);
  return false;
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.status !== "complete") return;
  const s = await load(tabId);
  if (!s || !s.active) return;
  await inject(tabId);
  if (s.awaitNav) return step(tabId);
  if (s.view) await ui(tabId, s.view); // Seite neu geladen, während jobslop auf dich wartet
});

// Öffnet ein Klick einen neuen Tab (z. B. „Auf Unternehmenswebsite bewerben“), geht es dort weiter.
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId) return;
  const s = await load(tab.openerTabId);
  if (!s || !s.active || !s.awaitNav) return;
  await save(tab.id, { ...s, awaitNav: true, history: [...s.history, "Neuer Tab geöffnet"] });
  await save(tab.openerTabId, { ...s, active: false, awaitNav: false });
  await ui(tab.openerTabId, { state: "info", text: "Weiter im neuen Tab.", job: s.job });
});
