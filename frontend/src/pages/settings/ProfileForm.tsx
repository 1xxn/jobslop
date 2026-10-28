import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, FileText, Plus, Trash2, Upload } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChipsInput, Switch } from "@/components/ui/controls";
import { Button, SectionBody, SectionHeader, Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Profile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SaveBar } from "./SaveBar";
import { Pending } from "@/components/domain";

type Section = "personal" | "work" | "documents" | "preferences" | "experience" | "answers";

export function ProfileForm({
  sections,
  onSaved,
  autosave,
}: {
  sections?: Section[];
  onSaved?: () => void;
  autosave?: boolean;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const [p, setP] = useState<Profile | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data.data && !dirty) setP(structuredClone(data.data.profile));
  }, [data.data, dirty]);
  const save = useMutation({
    mutationFn: (profile: Profile) => api.saveProfile(profile),
    onSuccess: (r) => {
      qc.setQueryData(["profile"], r);
      setDirty(false);
      if (!autosave) toast.success(t("common.saved"));
      onSaved?.();
    },
  });
  // Im Assistenten: Änderungen nach kurzer Pause automatisch speichern
  useEffect(() => {
    if (!autosave || !dirty || !p) return;
    const id = setTimeout(() => save.mutate(p), 700);
    return () => clearTimeout(id);
  }, [p, dirty, autosave]); // save absichtlich nicht als Abhängigkeit (neue Referenz je Render)
  const show = (s: Section) => !sections || sections.includes(s);

  if (!p) return <Pending query={data} className="h-96 rounded-lg" />;
  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => {
    setP({ ...p, [key]: value });
    setDirty(true);
  };
  const personal = (k: keyof Profile["personal"]) => ({
    value: p.personal[k],
    onChange: (e: { target: { value: string } }) => set("personal", { ...p.personal, [k]: e.target.value }),
  });
  const work = (k: keyof Profile["work"]) => ({
    value: String(p.work[k] ?? ""),
    onChange: (e: { target: { value: string } }) => set("work", { ...p.work, [k]: e.target.value }),
  });
  const missing = new Set(data.data?.missing ?? []);
  const warn = (key: string) => (missing.has(key) ? t("profile.missing") : undefined);

  return (
    <div className={cn("space-y-6", !autosave && "pb-24")}>
      {show("documents") && <DocumentsCard />}

      {show("personal") && (
        <section>
          <SectionHeader title={t("profile.personal")} description={t("profile.personal_hint")} />
          <SectionBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t("profile.first_name")} error={warn("personal.first_name")}>
              <Input autoComplete="given-name" {...personal("first_name")} />
            </Field>
            <Field label={t("profile.last_name")} error={warn("personal.last_name")}>
              <Input autoComplete="family-name" {...personal("last_name")} />
            </Field>
            <Field label={t("profile.email")} error={warn("personal.email")}>
              <Input type="email" autoComplete="email" {...personal("email")} />
            </Field>
            <Field label={t("profile.phone")} hint={t("profile.phone_hint")} error={warn("personal.phone")}>
              <Input type="tel" autoComplete="tel" {...personal("phone")} />
            </Field>
            <Field label={t("profile.city")} error={warn("personal.city")}>
              <Input autoComplete="address-level2" {...personal("city")} />
            </Field>
            <Field label={t("profile.postal_code")}>
              <Input autoComplete="postal-code" {...personal("postal_code")} />
            </Field>
            <Field label={t("profile.street")} className="sm:col-span-2" hint={t("profile.optional")}>
              <Input autoComplete="street-address" {...personal("street")} />
            </Field>
            <Field label="LinkedIn">
              <Input type="url" placeholder="https://linkedin.com/in/…" {...personal("linkedin")} />
            </Field>
            <Field label="GitHub / Portfolio">
              <Input type="url" placeholder="https://…" {...personal("github")} />
            </Field>
          </SectionBody>
        </section>
      )}

      {show("work") && (
        <section>
          <SectionHeader title={t("profile.work")} description={t("profile.work_hint")} />
          <SectionBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t("profile.current_title")}>
              <Input {...work("current_title")} />
            </Field>
            <Field label={t("profile.current_employer")}>
              <Input {...work("current_employer")} />
            </Field>
            <Field label={t("profile.years_total")} error={warn("work.years_experience_total")}>
              <Input inputMode="numeric" placeholder="4" {...work("years_experience_total")} />
            </Field>
            <Field label={t("profile.years_relevant")}>
              <Input inputMode="numeric" placeholder="2" {...work("years_experience_relevant")} />
            </Field>
            <Field label={t("profile.salary")} hint={t("profile.salary_hint")} error={warn("work.salary_expectation_eur")}>
              <Input inputMode="numeric" placeholder="65000" {...work("salary_expectation_eur")} />
            </Field>
            <Field label={t("profile.notice")} error={warn("work.notice_period")}>
              <Input placeholder={t("profile.notice_placeholder")} {...work("notice_period")} />
            </Field>
            <Field label={t("profile.start")} error={warn("work.earliest_start")}>
              <Input placeholder="01.03.2027" {...work("earliest_start")} />
            </Field>
            <Field label={t("profile.workplace")}>
              <Input placeholder={t("profile.workplace_placeholder")} {...work("workplace_preference")} />
            </Field>
            <div className="sm:col-span-2 grid gap-1 sm:grid-cols-2">
              <ToggleLine
                label={t("profile.eu_auth")}
                checked={p.work.work_authorization_eu}
                onChange={(v) => set("work", { ...p.work, work_authorization_eu: v })}
              />
              <ToggleLine
                label={t("profile.visa")}
                checked={p.work.requires_visa_sponsorship}
                onChange={(v) => set("work", { ...p.work, requires_visa_sponsorship: v })}
              />
              <ToggleLine
                label={t("profile.relocate")}
                checked={p.work.willing_to_relocate}
                onChange={(v) => set("work", { ...p.work, willing_to_relocate: v })}
              />
            </div>
          </SectionBody>
        </section>
      )}

      {show("experience") && (
        <section>
          <SectionHeader title={t("profile.skills")} description={t("profile.skills_hint")} />
          <SectionBody className="space-y-4">
            <Field label={t("profile.summary")}>
              <Textarea value={p.summary} onChange={(e) => set("summary", e.target.value)} />
            </Field>
            <Field label={t("profile.skills")}>
              <ChipsInput value={p.skills} onChange={(v) => set("skills", v)} placeholder="Kubernetes, Python, …" />
            </Field>
            <Field label={t("profile.languages")}>
              <ChipsInput
                value={p.languages.map((l) => `${l.language} ${l.level}`.trim())}
                onChange={(v) =>
                  set(
                    "languages",
                    v.map((s) => {
                      const [language, ...rest] = s.split(" ");
                      return { language, level: rest.join(" ") };
                    }),
                  )
                }
                placeholder={t("profile.languages_placeholder")}
              />
            </Field>
            <ExperienceList value={p.experience} onChange={(v) => set("experience", v)} />
          </SectionBody>
        </section>
      )}

      {show("preferences") && (
        <section>
          <SectionHeader title={t("profile.preferences")} description={t("profile.preferences_hint")} />
          <SectionBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t("profile.cover_letter")} hint={t("profile.cover_letter_hint")}>
              <Select
                value={p.documents.cover_letter === "none" ? "none" : "auto"}
                onChange={(e) => set("documents", { ...p.documents, cover_letter: e.target.value })}
              >
                <option value="auto">{t("profile.cover_auto")}</option>
                <option value="none">{t("profile.cover_none")}</option>
              </Select>
            </Field>
            <Field label={t("profile.cover_lang")}>
              <Select
                value={p.preferences.cover_letter_language}
                onChange={(e) =>
                  set("preferences", { ...p.preferences, cover_letter_language: e.target.value as "auto" | "de" | "en" })
                }
              >
                <option value="auto">{t("profile.lang_auto")}</option>
                <option value="de">Deutsch</option>
                <option value="en">English</option>
              </Select>
            </Field>
            <Field label={t("profile.diversity")} hint={t("profile.diversity_hint")}>
              <Select
                value={p.preferences.diversity_questions}
                onChange={(e) =>
                  set("preferences", { ...p.preferences, diversity_questions: e.target.value as "decline" | "answer" })
                }
              >
                <option value="decline">{t("profile.diversity_decline")}</option>
                <option value="answer">{t("profile.diversity_answer")}</option>
              </Select>
            </Field>
            <Field label={t("profile.how_heard")}>
              <Input
                value={p.preferences.how_did_you_hear}
                onChange={(e) => set("preferences", { ...p.preferences, how_did_you_hear: e.target.value })}
              />
            </Field>
            <Field label={t("profile.tone")} className="sm:col-span-2">
              <Input value={p.preferences.tone} onChange={(e) => set("preferences", { ...p.preferences, tone: e.target.value })} />
            </Field>
            <div className="sm:col-span-2 grid gap-1 sm:grid-cols-2">
              <ToggleLine
                label={t("profile.consent_privacy")}
                checked={p.preferences.consent_privacy}
                onChange={(v) => set("preferences", { ...p.preferences, consent_privacy: v })}
              />
              <ToggleLine
                label={t("profile.talent_pool")}
                checked={p.preferences.consent_talent_pool}
                onChange={(v) => set("preferences", { ...p.preferences, consent_talent_pool: v })}
              />
            </div>
          </SectionBody>
        </section>
      )}

      {!autosave && (
        <SaveBar dirty={dirty} saving={save.isPending} onSave={() => save.mutate(p)} onReset={() => setDirty(false)} />
      )}
    </div>
  );
}

function ToggleLine({ label, checked, onChange }: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-md px-1 py-2 text-body">
      {label}
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}

function ExperienceList({ value, onChange }: { value: Profile["experience"]; onChange: (v: Profile["experience"]) => void }) {
  const { t } = useI18n();
  const update = (i: number, patch: Partial<Profile["experience"][number]>) =>
    onChange(value.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-meta font-medium">{t("profile.experience")}</span>
        <Button
          size="sm"
          variant="quiet"
          onClick={() => onChange([...value, { company: "", title: "", start: "", end: "heute", location: "", highlights: [] }])}
        >
          <Plus />
          {t("common.add")}
        </Button>
      </div>
      <div className="space-y-3">
        {value.map((e, i) => (
          <div key={i} className="grid gap-2 border-b border-line pb-3 last:border-b-0 sm:grid-cols-[1fr_1fr_110px_110px_auto]">
            <Input aria-label={t("profile.exp_title")} placeholder={t("profile.exp_title")} value={e.title} onChange={(ev) => update(i, { title: ev.target.value })} />
            <Input aria-label={t("profile.exp_company")} placeholder={t("profile.exp_company")} value={e.company} onChange={(ev) => update(i, { company: ev.target.value })} />
            <Input aria-label={t("profile.exp_start")} placeholder="2022-01" value={e.start} onChange={(ev) => update(i, { start: ev.target.value })} />
            <Input aria-label={t("profile.exp_end")} placeholder={t("profile.exp_today")} value={e.end} onChange={(ev) => update(i, { end: ev.target.value })} />
            <Button size="icon" variant="quiet" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label={t("common.delete")}>
              <Trash2 />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Lebenslauf per Drag & Drop. Beim Hochladen kann Claude das Profil automatisch befüllen. */
export function DocumentsCard({ importOnUpload = false, onImported }: { importOnUpload?: boolean; onImported?: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const [over, setOver] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: ({ file, kind }: { file: File; kind: "cv" | "cv_en" }) => api.uploadDocument(file, kind, importOnUpload && kind === "cv"),
    onSuccess: (r) => {
      qc.setQueryData(["profile"], r);
      toast.success(r.message || t("profile.uploaded"));
      if (importOnUpload) onImported?.();
    },
  });
  const docs = data.data?.documents;
  const slot = (kind: "cv" | "cv_en", title: string, hint: string) => {
    const doc = kind === "cv" ? docs?.cv : docs?.cv_en;
    return (
      <DropZone
        key={kind}
        title={title}
        hint={hint}
        file={doc?.exists ? doc.name : undefined}
        missing={!!doc && !doc.exists}
        active={over === kind}
        busy={upload.isPending && upload.variables?.kind === kind}
        onOver={(v) => setOver(v ? kind : null)}
        onFile={(file) => upload.mutate({ file, kind })}
        busyText={importOnUpload && kind === "cv" ? t("profile.importing") : t("profile.uploading")}
      />
    );
  };
  return (
    <section>
      <SectionHeader title={t("profile.documents")} description={t("profile.documents_hint")} />
      <SectionBody className="grid gap-3 sm:grid-cols-2">
        {slot("cv", t("profile.cv"), t("profile.cv_hint"))}
        {slot("cv_en", t("profile.cv_en"), t("profile.cv_en_hint"))}
      </SectionBody>
    </section>
  );
}

function DropZone({
  title,
  hint,
  file,
  missing,
  active,
  busy,
  busyText,
  onOver,
  onFile,
}: {
  title: string;
  hint: string;
  file?: string;
  missing?: boolean;
  active: boolean;
  busy: boolean;
  busyText: string;
  onOver: (v: boolean) => void;
  onFile: (f: File) => void;
}) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  return (
    <button
      type="button"
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        onOver(true);
      }}
      onDragLeave={() => onOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        onOver(false);
        const f = e.dataTransfer.files[0];
        if (f) onFile(f);
      }}
      disabled={busy}
      className={cn(
        "flex items-center gap-3.5 rounded-lg border-2 border-dashed p-4 text-left transition-colors",
        active ? "border-accent bg-accent-soft" : "border-line-input hover:border-accent/60 hover:bg-sunken",
      )}
    >
      <span
        className={cn(
          "grid size-10 shrink-0 place-items-center rounded-md [&_svg]:size-5",
          file ? "bg-sunken text-positive" : "bg-sunken text-ink-2",
        )}
      >
        {busy ? <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : file ? <FileText /> : <Upload />}
      </span>
      <span className="min-w-0">
        <span className="block text-body font-semibold">{title}</span>
        <span className="block truncate text-meta text-ink-2">
          {busy ? busyText : file ? file : hint}
        </span>
        {missing && (
          <span className="mt-0.5 flex items-center gap-1 text-small text-danger">
            <CircleAlert className="size-3" />
            {t("profile.file_missing")}
          </span>
        )}
      </span>
      <input
        ref={input}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </button>
  );
}
