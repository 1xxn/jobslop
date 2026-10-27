import { Check, X } from "lucide-react";
import { Checkbox as C, Switch as S, Tabs as T, ToggleGroup as TG } from "radix-ui";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/* ----------------------------------------------------------------- Schalter */

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  id,
  label,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
  id?: string;
  label?: string;
}) {
  return (
    <S.Root
      id={id}
      aria-label={label}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      // sichtbar 32 × 18 px, Klickfläche 24 px hoch (WCAG 2.5.8)
      className="relative inline-flex h-[18px] w-8 shrink-0 items-center rounded-full bg-line-input transition-colors duration-[120ms] before:absolute before:-inset-y-[3px] before:inset-x-0 data-[state=checked]:bg-accent disabled:opacity-50"
    >
      <S.Thumb className="block size-[14px] translate-x-[2px] rounded-full bg-raised transition-transform duration-[120ms] ease-out data-[state=checked]:translate-x-[16px] data-[state=checked]:bg-on-accent" />
    </S.Root>
  );
}

/** Zeile mit Titel, optionalem Hinweis und Schalter rechts. */
export function SwitchRow({
  title,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  title: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-6 border-b border-line py-2.5 last:border-b-0">
      <span className="min-w-0">
        <span className="block text-body">{title}</span>
        {description && <span className="mt-0.5 block text-meta text-ink-2">{description}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </label>
  );
}

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  className,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label?: string;
  className?: string;
}) {
  return (
    <C.Root
      checked={checked}
      onCheckedChange={(v) => onCheckedChange(v === true)}
      aria-label={label}
      onClick={(e) => e.stopPropagation()}
      // sichtbar 16 px, Klickfläche 24 px
      className={cn(
        "relative grid size-4 shrink-0 place-items-center rounded-sm border border-line-input bg-raised transition-colors before:absolute before:-inset-1 data-[state=checked]:border-accent data-[state=checked]:bg-accent",
        className,
      )}
    >
      <C.Indicator>
        <Check className="size-3 text-on-accent" strokeWidth={3} />
      </C.Indicator>
    </C.Root>
  );
}

/* ----------------------------------------------------------------- Tabs: Unterstrich in Tinte, Zähler grau */

export const Tabs = T.Root;
export const TabsContent = T.Content;

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <T.List
      className={cn(
        "flex gap-5 overflow-x-auto border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {children}
    </T.List>
  );
}

export function TabsTrigger({ value, children, count }: { value: string; children: ReactNode; count?: number }) {
  return (
    <T.Trigger
      value={value}
      className="relative flex items-center gap-1.5 whitespace-nowrap py-2 text-body text-ink-2 transition-colors hover:text-ink data-[state=active]:font-semibold data-[state=active]:text-ink data-[state=active]:shadow-[inset_0_-2px_0_var(--ink)]"
    >
      {children}
      {count !== undefined && count > 0 && <span className="tabular font-normal text-ink-3">{count}</span>}
    </T.Trigger>
  );
}

/* ----------------------------------------------------------------- Segmente (wenige gleichwertige Optionen) */

export function Segmented<V extends string>({
  value,
  onChange,
  options,
  className,
  size = "md",
  label,
}: {
  value: V;
  onChange: (v: V) => void;
  options: { value: V; label: ReactNode; icon?: ReactNode }[];
  className?: string;
  size?: "sm" | "md";
  label?: string;
}) {
  return (
    <TG.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as V)}
      aria-label={label}
      className={cn("inline-flex gap-0.5 rounded-md border border-line p-0.5", className)}
    >
      {options.map((o) => (
        <TG.Item
          key={o.value}
          value={o.value}
          className={cn(
            "flex items-center gap-1.5 whitespace-nowrap rounded-sm text-ink-2 transition-colors duration-[120ms] hover:text-ink data-[state=on]:bg-sunken data-[state=on]:font-medium data-[state=on]:text-ink [&_svg]:size-3.5",
            size === "sm" ? "px-2 py-0.5 text-small" : "px-2.5 py-1 text-meta",
          )}
        >
          {o.icon}
          {o.label}
        </TG.Item>
      ))}
    </TG.Root>
  );
}

/* ----------------------------------------------------------------- Tag-Eingabe */

export function ChipsInput({
  value,
  onChange,
  placeholder,
  className,
  tone = "neutral",
  id,
  "aria-describedby": describedBy,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  className?: string;
  tone?: "neutral" | "danger";
  /** landet am Texteingabefeld, damit ein umgebendes Field-Label es beschriftet */
  id?: string;
  "aria-describedby"?: string;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const items = raw
      .split(/[,;\n]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .filter((s) => !value.some((v) => v.toLowerCase() === s.toLowerCase()));
    if (items.length) onChange([...value, ...items]);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if ((e.key === "Enter" || e.key === ",") && draft.trim()) {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return (
    <div
      className={cn(
        "flex min-h-8 w-full flex-wrap items-center gap-1 rounded-md border border-line-input bg-raised px-1.5 py-1 focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--accent)]",
        className,
      )}
    >
      {value.map((v) => (
        <span
          key={v}
          className={cn(
            "inline-flex items-center gap-0.5 rounded-sm py-px pr-0.5 pl-1.5 text-meta",
            tone === "danger" ? "bg-danger-soft text-danger" : "bg-sunken text-ink",
          )}
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== v))}
            className="grid size-4 place-items-center rounded-sm text-ink-3 hover:bg-line hover:text-ink"
            aria-label={t("common.remove_item", { item: v })}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        aria-describedby={describedBy}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => draft.trim() && add(draft)}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text");
          if (/[,;\n]/.test(text)) {
            e.preventDefault();
            add(text);
          }
        }}
        placeholder={value.length ? "" : placeholder}
        className="min-w-24 flex-1 bg-transparent px-1 text-body outline-none placeholder:text-ink-3"
      />
    </div>
  );
}
