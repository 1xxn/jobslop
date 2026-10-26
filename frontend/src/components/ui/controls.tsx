import { X } from "lucide-react";
import { Checkbox as C, Switch as S, Tabs as T, ToggleGroup as TG } from "radix-ui";
import { Check } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { cn } from "@/lib/utils";

/* ----------------------------------------------------------------- Switch (iOS-Stil) */

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
      className="relative inline-flex h-[26px] w-[44px] shrink-0 items-center rounded-full bg-surface-3 transition-colors duration-200 ease-standard data-[state=checked]:bg-success disabled:opacity-50"
    >
      <S.Thumb className="block size-[22px] translate-x-[2px] rounded-full bg-white shadow-[0_2px_6px_rgb(0_0_0/0.2)] transition-transform duration-200 ease-standard data-[state=checked]:translate-x-[20px]" />
    </S.Root>
  );
}

/** Zeile mit Titel, Beschreibung und Schalter – wie in den iOS/macOS-Einstellungen. */
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
    <label className="flex cursor-pointer items-center justify-between gap-6 py-3">
      <span className="min-w-0">
        <span className="block text-[0.875rem] font-medium">{title}</span>
        {description && <span className="mt-0.5 block text-footnote text-fg-muted">{description}</span>}
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
      className={cn(
        "grid size-[18px] shrink-0 place-items-center rounded-[5px] border border-border-strong bg-surface transition-colors data-[state=checked]:border-primary data-[state=checked]:bg-primary",
        className,
      )}
    >
      <C.Indicator>
        <Check className="size-3 text-primary-fg" strokeWidth={3} />
      </C.Indicator>
    </C.Root>
  );
}

/* ----------------------------------------------------------------- Tabs */

export const Tabs = T.Root;
export const TabsContent = T.Content;

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <T.List
      className={cn(
        "flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
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
      className="relative -mb-px flex items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 py-2.5 text-[0.875rem] font-medium text-fg-muted transition-colors hover:text-fg data-[state=active]:border-primary data-[state=active]:text-fg"
    >
      {children}
      {count !== undefined && count > 0 && (
        <span className="tabular rounded-full bg-surface-2 px-1.5 text-caption text-fg-muted">{count}</span>
      )}
    </T.Trigger>
  );
}

/* ----------------------------------------------------------------- Segmented Control (HIG) */

export function Segmented<V extends string>({
  value,
  onChange,
  options,
  className,
  size = "md",
}: {
  value: V;
  onChange: (v: V) => void;
  options: { value: V; label: ReactNode; icon?: ReactNode }[];
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <TG.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as V)}
      className={cn("inline-flex rounded-md bg-surface-2 p-0.5", className)}
    >
      {options.map((o) => (
        <TG.Item
          key={o.value}
          value={o.value}
          className={cn(
            "flex items-center gap-1.5 whitespace-nowrap rounded-[7px] font-medium text-fg-muted transition-all duration-150 hover:text-fg data-[state=on]:bg-surface data-[state=on]:text-fg data-[state=on]:shadow-sm dark:data-[state=on]:bg-surface-3 [&_svg]:size-3.5",
            size === "sm" ? "px-2.5 py-1 text-caption" : "px-3 py-1.5 text-footnote",
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
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  className?: string;
  tone?: "neutral" | "danger";
}) {
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
        "flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2 py-1.5 shadow-sm focus-within:border-primary focus-within:ring-4 focus-within:ring-primary/15",
        className,
      )}
    >
      {value.map((v) => (
        <span
          key={v}
          className={cn(
            "inline-flex items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-footnote",
            tone === "danger" ? "bg-danger-soft text-danger" : "bg-surface-2 text-fg",
          )}
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== v))}
            className="grid size-4 place-items-center rounded-full text-fg-muted hover:bg-surface-3 hover:text-fg"
            aria-label={`${v} entfernen`}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
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
        className="min-w-24 flex-1 bg-transparent px-1 text-[0.875rem] outline-none placeholder:text-fg-subtle"
      />
    </div>
  );
}
