"""Planer: entscheidet pro Seite, was in welches Feld kommt und welcher Button als Nächstes dran ist."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from ..cvtext import cv_text
from ..llm import DYNAMIC_BOUNDARY, LLM, file_block, image_block
from ..profile import TODO, Profile
from .extract import PageState

# --------------------------------------------------------------------------- Schemas (Structured Outputs)


class FieldAction(BaseModel):
    field_id: str
    action: Literal["fill", "select", "check", "uncheck", "upload", "click", "skip"]
    value: str
    confidence: Literal["high", "medium", "low"]
    source: Literal["profile", "answer_bank", "job_tailored", "policy", "unknown"]
    reason: str


class OpenQuestion(BaseModel):
    field_id: str
    question: str
    why: str
    options: list[str]


class PagePlan(BaseModel):
    page_kind: Literal[
        "job_posting",
        "application_form",
        "login_or_account",
        "captcha",
        "confirmation",
        "closed_or_error",
        "other",
    ]
    actions: list[FieldAction]
    open_questions: list[OpenQuestion]
    next_step: Literal["click_apply", "click_next", "click_submit", "wait_for_user", "done", "abort"]
    next_target_id: str
    summary: str


# --------------------------------------------------------------------------- Kontext


@dataclass
class JobContext:
    id: int
    company: str
    title: str
    location: str
    url: str
    description: str
    language: str


@dataclass
class PlanInput:
    job: JobContext
    state: PageState
    step: int
    history: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    submit_clicked: bool = False
    screenshots: list[bytes] = field(default_factory=list)


class Planner(Protocol):
    async def plan(self, data: PlanInput) -> PagePlan: ...

    def remember(self, question: str, answer: str) -> None: ...


# --------------------------------------------------------------------------- LLM-Planer


SYSTEM_RULES = """Du bist der Ausfüll-Agent eines privaten Bewerbungs-Tools. Du steuerst einen echten Browser für EINE Person
(Profil unten) und bewirbst sie auf genau die Stelle, die im Auftrag steht. Du bekommst pro Schritt die erkannten Formularfelder
(mit IDs), die Buttons und einen Textauszug der Seite, manchmal zusätzlich Screenshots mit eingezeichneten IDs.

Wahrheit vor Vollständigkeit:
1. Verwende nur Fakten aus Profil, Lebenslauf, Standardantworten und Antwortbank. Erfinde nie Jahre, Abschlüsse, Zertifikate,
   Skills, Gehälter, Staatsangehörigkeit, Termine oder Kontaktdaten. Werte mit "UNBEKANNT" sind unbekannt.
2. Fehlt eine Pflichtangabe: lege eine open_question an (präzise Frage auf Deutsch, bei Auswahlfeldern mit den exakten Optionen)
   und setze für dieses Feld action=skip. Fehlende optionale Angaben: skip ohne Frage.
3. Freitextfragen (Motivation, "Why us", Zusatzinfos) darfst du formulieren (source=job_tailored): in der Sprache des Formulars,
   60–160 Wörter, konkret zur Stelle, nur belegbare Erfahrung, keine Übertreibungen, keine Floskeln.
   Für ein ganzes Anschreiben-Textfeld setze value="@cover_letter" (das Tool fügt ein eigens erzeugtes Anschreiben ein).
4. Uploads: Lebenslauf-Feld -> upload mit value="@cv" (bei englischsprachigem Formular und vorhandenem englischen CV "@cv_en").
   Anschreiben-Upload -> "@cover_letter_pdf", wenn Anschreiben automatisch erzeugt werden; Zeugnisse/Zertifikate -> "@certificates",
   falls vorhanden, sonst skip. Bereits hochgeladene Dateien nicht erneut hochladen.
5. Diversity-, Gender-, Behinderungs-, Herkunftsfragen: bei Präferenz "decline" die Option "Keine Angabe"/"Prefer not to say"/
   "Decline to self-identify" wählen. Gibt es keine solche Option und ist das Feld optional: skip. Sonst open_question.
6. Datenschutz-Einwilligung: check, wenn consent_privacy=true. Talent-Pool und Newsletter nach Präferenz.
   "Ich bestätige die Richtigkeit meiner Angaben": check.
7. Wie hast du von uns erfahren: Präferenz how_did_you_hear, sonst die passendste Option (z. B. "Company website").
8. Auswahlfelder (select, radio, combobox, checkbox_group): value muss exakt einer Optionsbeschriftung entsprechen,
   bei checkbox_group mehrere mit "; " trennen. Bei Radio/Checkbox-Gruppen bezieht sich field_id auf die Gruppe.
9. Formate: Telefon international (+49 …). Datumsfelder vom Typ date als JJJJ-MM-TT, sonst so wie das Feld es verlangt.
   Zahlenfelder ohne Tausenderpunkt. Gehalt als Jahresbrutto in EUR, wenn nicht anders verlangt.
10. Felder, die schon den richtigen Wert haben: skip. Passwortfelder nie ausfüllen; Konto anlegen oder Login heißt
    page_kind=login_or_account und next_step=wait_for_user.
11. Cookie-Banner: Wenn einer die Seite blockiert, ist die richtige Aktion click auf "Nur notwendige"/"Ablehnen", sonst
    "Akzeptieren". Das hat Vorrang vor allem anderen.

Ablaufsteuerung (next_step + next_target_id):
- Stellenanzeige ohne Formular: click_apply mit dem Bewerben-Button/Link ("Apply", "Jetzt bewerben", "Bewerbung starten").
  Gibt es "Mit LinkedIn/Indeed bewerben" und eine manuelle Variante, nimm die manuelle.
- Mehrseitiges Formular: click_next ("Weiter", "Next", "Continue", "Review").
- Nur wenn alle Pflichtfelder gefüllt sind und keine offene Frage bleibt: click_submit mit dem endgültigen Absende-Button.
- Bestätigungsseite ("Danke für deine Bewerbung", "Application submitted"): page_kind=confirmation, next_step=done.
- Stelle geschlossen/404: page_kind=closed_or_error, next_step=abort.
- Sichtbares CAPTCHA oder unklare Lage, die ein Mensch lösen muss: next_step=wait_for_user.
- confidence: high = direkt aus dem Profil/der Antwortbank, medium = abgeleitet/umformatiert, low = unsicher (vermeiden).
"""


def _answer_bank_text(answers: list[tuple[str, str]]) -> str:
    if not answers:
        return "(leer)"
    return "\n".join(f"- F: {q}\n  A: {a}" for q, a in answers[:200])


class LLMPlanner:
    def __init__(
        self,
        llm: LLM,
        profile: Profile,
        profile_base: Path,
        answers: list[tuple[str, str]],
        cover_letter_auto: bool,
        model: str | None = None,
    ) -> None:
        self.llm = llm
        self.profile = profile
        self.model = model
        self.answers = list(answers)
        prefs = profile.preferences
        standard = "\n".join(f"- {k}: {v}" for k, v in profile.standard_answers.items()) or "(keine)"
        cv = profile.cv_path(profile_base)
        self.cv_text = cv_text(cv)
        # Eingescanntes PDF ohne Textebene: Claude liest die Datei bei jedem Schritt selbst (langsamer).
        self.cv_file: Path | None = cv if (cv and cv.exists() and not self.cv_text) else None
        cv_section = self.cv_text or "(siehe beigefügte Lebenslauf-Datei)"
        self._base_system = (
            SYSTEM_RULES
            + "\n\n# Profil\n"
            + profile.to_prompt()
            + f"\n# Präferenzen\ndiversity={prefs.diversity_questions}, consent_privacy={prefs.consent_privacy}, "
            f"talent_pool={prefs.consent_talent_pool}, newsletter={prefs.newsletter}, how_did_you_hear={prefs.how_did_you_hear!r}, "
            f"anschreiben_automatisch={cover_letter_auto}, englischer_cv={'ja' if profile.documents.cv_en else 'nein'}"
            + "\n\n# Standardantworten\n"
            + standard
            + "\n\n# Lebenslauf (Text)\n"
            + cv_section
        )

    @property
    def system(self) -> str:
        # Alles vor der Grenze ist stabil und wird von Claude Code gecacht; die Antwortbank wächst während eines Laufs.
        return (
            self._base_system
            + f"\n\n{DYNAMIC_BOUNDARY}\n\n# Antwortbank (vom Bewerber bestätigt)\n"
            + _answer_bank_text(self.answers)
        )

    def remember(self, question: str, answer: str) -> None:
        self.answers.insert(0, (question, answer))

    async def plan(self, data: PlanInput) -> PagePlan:
        job = data.job
        content: list[dict[str, Any]] = []
        if self.cv_file:
            content.append(file_block(self.cv_file))
        history = "\n".join(f"- {h}" for h in data.history[-12:]) or "- (erster Schritt)"
        failures = "\n".join(f"- {f}" for f in data.failures) or "- keine"
        errors = "\n".join(f"- {e}" for e in data.state.errors[:15]) or "- keine"
        text = (
            f"# Auftrag\nBewirb die Person auf: {job.title} bei {job.company} ({job.location}).\n"
            f"Sprache der Anzeige: {job.language or 'unbekannt'}. Stellen-URL: {job.url}\n\n"
            f"# Stellenbeschreibung (Auszug)\n{job.description[:5000] or '(nicht verfügbar)'}\n\n"
            f"# Bisherige Schritte\n{history}\n\n# Fehlgeschlagene Aktionen im letzten Schritt\n{failures}\n\n"
            f"# Aktuelle Seite (Schritt {data.step})\nURL: {data.state.url}\nTitel: {data.state.title}\n"
            f"Überschriften: {' | '.join(data.state.headings[:10])}\n"
            f"Absenden wurde bereits geklickt: {'ja' if data.submit_clicked else 'nein'}\n"
            f"Sichtbare Fehlermeldungen:\n{errors}\n\n"
            f"# Felder und Buttons (JSON)\n{data.state.compact()}\n\n"
            f"# Seitentext (Auszug)\n{data.state.text[:3500]}"
        )
        content.append({"type": "text", "text": text})
        for shot in data.screenshots[:3]:
            content.append(image_block(shot))
        if data.screenshots:
            content.append(
                {
                    "type": "text",
                    "text": "Die Screenshots (screenshot-*.jpg) zeigen die Seite mit eingezeichneten Element-IDs.",
                }
            )
        return await self.llm.parse(
            PagePlan, system=self.system, content=content, model=self.model, max_tokens=6000
        )


# --------------------------------------------------------------------------- Regel-Planer (offline, Tests, Standardfelder)


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"first ?name|vorname|given name", re.I), "personal.first_name"),
    (re.compile(r"last ?name|nachname|surname|family name", re.I), "personal.last_name"),
    (
        re.compile(r"full name|vollständiger name|^name\b|your name|ihr name|dein name", re.I),
        "personal.full_name",
    ),
    (re.compile(r"e-?mail", re.I), "personal.email"),
    (re.compile(r"phone|telefon|mobil|handy", re.I), "personal.phone"),
    (re.compile(r"linkedin", re.I), "personal.linkedin"),
    (re.compile(r"github", re.I), "personal.github"),
    (re.compile(r"website|portfolio|homepage", re.I), "personal.website"),
    (re.compile(r"\bcity\b|\bstadt\b|wohnort|\bort\b", re.I), "personal.city"),
    (re.compile(r"postal|zip|plz|postleitzahl", re.I), "personal.postal_code"),
    (re.compile(r"street|straße|strasse|address|adresse", re.I), "personal.street"),
    (re.compile(r"\bcountry\b|^\s*land\b", re.I), "personal.country"),
    (re.compile(r"salary|gehalt|vergütung|compensation", re.I), "work.salary_expectation_eur"),
    (re.compile(r"notice|kündigungsfrist", re.I), "work.notice_period"),
    (re.compile(r"start date|eintritt|verfügbar ab|earliest|frühest", re.I), "work.earliest_start"),
    (re.compile(r"current (company|employer)|aktueller arbeitgeber", re.I), "work.current_employer"),
    (re.compile(r"current (title|position|role)|aktuelle position", re.I), "work.current_title"),
]
_CV_RX = re.compile(r"resume|lebenslauf|\bcv\b|curriculum", re.I)
_COVER_RX = re.compile(r"cover letter|anschreiben|motivationsschreiben", re.I)
_CONSENT_RX = re.compile(r"datenschutz|privacy|einwillig|consent|zustimm|agree|akzeptier|terms", re.I)
_TALENT_RX = re.compile(r"talent ?pool|future (opportunities|positions)|weitere stellen|newsletter", re.I)
_SUBMIT_RX = re.compile(
    r"submit|absenden|bewerbung (senden|abschicken)|send application|jetzt bewerben$|^bewerben$|^senden$",
    re.I,
)
_NEXT_RX = re.compile(r"^(weiter|next|continue|fortfahren|review|überprüfen)\b", re.I)
_APPLY_RX = re.compile(r"apply|bewerb", re.I)
_CONFIRM_RX = re.compile(
    r"thank you for (your )?appl|application (has been )?(submitted|received)|we have received your application|"
    r"vielen dank für (deine|ihre) bewerbung|bewerbung (ist )?(erfolgreich )?(eingegangen|versendet|übermittelt)|danke für deine bewerbung",
    re.I,
)


def profile_value(profile: Profile, path: str) -> str:
    if path == "personal.full_name":
        return profile.personal.full_name
    obj: Any = profile
    for part in path.split("."):
        obj = getattr(obj, part, "")
    value = "" if obj is None else str(obj)
    return "" if value == TODO else value


class HeuristicPlanner:
    """Deterministischer Planer für Standardfelder. Wird ohne Claude (--offline) und in Tests verwendet.

    Er beantwortet nur, was eindeutig im Profil steht, und stellt für alles andere Rückfragen.
    """

    def __init__(self, profile: Profile, answers: list[tuple[str, str]] | None = None) -> None:
        self.profile = profile
        self.answers = list(answers or [])

    def remember(self, question: str, answer: str) -> None:
        self.answers.insert(0, (question, answer))

    def _answer_for(self, label: str) -> str:
        from ..profile import normalize_question

        key = normalize_question(label)
        best, best_score = "", 0.0
        for q, a in self.answers:
            s = _sim(normalize_question(q), key)
            if s > best_score:
                best, best_score = a, s
        return best if best_score >= 0.85 else ""

    async def plan(self, data: PlanInput) -> PagePlan:
        st = data.state
        if _CONFIRM_RX.search(st.text):
            return PagePlan(
                page_kind="confirmation",
                actions=[],
                open_questions=[],
                next_step="done",
                next_target_id="",
                summary="Bestätigung erkannt",
            )
        if st.has_password and len(st.form_fields) <= 3:
            return PagePlan(
                page_kind="login_or_account",
                actions=[],
                open_questions=[],
                next_step="wait_for_user",
                next_target_id="",
                summary="Login/Konto nötig",
            )
        actions: list[FieldAction] = []
        questions: list[OpenQuestion] = []
        for f in st.form_fields:
            label = f.get("label", "")
            kind = f["kind"]
            act = self._plan_field(f, label, kind)
            if act is None:
                if f.get("required") and not f.get("value"):
                    questions.append(
                        OpenQuestion(
                            field_id=f["id"],
                            question=label or f.get("name", "Feld"),
                            why="Nicht im Profil",
                            options=[o["label"] for o in f.get("options", [])][:30],
                        )
                    )
                continue
            actions.append(act)

        submit = next((b for b in st.buttons if _SUBMIT_RX.search(b["text"]) and not b.get("disabled")), None)
        nxt = next((b for b in st.buttons if _NEXT_RX.search(b["text"]) and not b.get("disabled")), None)
        apply = next((b for b in st.buttons if _APPLY_RX.search(b["text"])), None)
        if not st.form_fields and apply:
            return PagePlan(
                page_kind="job_posting",
                actions=[],
                open_questions=[],
                next_step="click_apply",
                next_target_id=apply["id"],
                summary="Stellenanzeige – Bewerben klicken",
            )
        if questions:
            step, target = "wait_for_user", ""
        elif nxt and not submit:
            step, target = "click_next", nxt["id"]
        elif submit:
            step, target = "click_submit", submit["id"]
        else:
            step, target = "wait_for_user", ""
        return PagePlan(
            page_kind="application_form",
            actions=actions,
            open_questions=questions,
            next_step=step,
            next_target_id=target,
            summary=f"{len(actions)} Felder geplant (Regel-Planer)",
        )

    def _plan_field(self, f: dict[str, Any], label: str, kind: str) -> FieldAction | None:
        def act(action: str, value: str, source: str = "profile", conf: str = "high") -> FieldAction:
            return FieldAction(
                field_id=f["id"],
                action=action,
                value=value,
                confidence=conf,
                source=source,  # type: ignore[arg-type]
                reason="Regel",
            )

        if kind == "file":
            if _COVER_RX.search(label):
                return (
                    act("upload", "@cover_letter_pdf")
                    if self.profile.documents.cover_letter == "auto"
                    else None
                )
            if _CV_RX.search(label) or not label:
                return None if f.get("value") else act("upload", "@cv")
            return None
        if kind in ("checkbox", "aria_checkbox"):
            if _TALENT_RX.search(label):
                want = self.profile.preferences.consent_talent_pool
                return act("check" if want else "uncheck", "", "policy")
            if _CONSENT_RX.search(label) and self.profile.preferences.consent_privacy:
                return None if f.get("value") == "checked" else act("check", "", "policy")
            return None
        if kind == "textarea" and _COVER_RX.search(label):
            if self.profile.documents.cover_letter == "none" or f.get("value"):
                return None
            return act("fill", "@cover_letter", "job_tailored", "medium")
        if f.get("value"):
            return None
        if answer := self._answer_for(label):
            if kind in ("select", "radio", "combobox", "checkbox_group"):
                return act("select" if kind != "checkbox_group" else "check", answer, "answer_bank")
            return act("fill", answer, "answer_bank")
        for rx, path in _RULES:
            if rx.search(label) or rx.search(f.get("name", "")) or rx.search(f.get("autocomplete", "")):
                value = profile_value(self.profile, path)
                if not value:
                    return None
                if kind in ("select", "radio", "combobox"):
                    options = [o["label"] for o in f.get("options", [])]
                    if options:
                        best = max(options, key=lambda o: _sim(o, value))
                        if _sim(best, value) < 0.6:
                            return None
                        value = best
                    return act("select", value)
                return act("fill", value)
        return None
