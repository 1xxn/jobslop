import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle, Search } from "lucide-react";
import { Slot } from "radix-ui";
import { cloneElement, type ComponentProps, forwardRef, isValidElement, type ReactElement, type ReactNode, useId } from "react";
import { cn } from "@/lib/utils";

/* ----------------------------------------------------------------- Button
 * primary: höchstens einer pro Ansicht · secondary: Rahmen · quiet: nur Text · danger: leise rot (setzt auf Rückgängig
 * statt Rückfrage) · link: Textlink.
 */

const buttonVariants = cva(
  "relative inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors duration-[120ms] ease-out disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-on-accent hover:bg-accent-hover",
        secondary: "border border-line-input text-ink hover:bg-sunken",
        quiet: "text-ink-2 hover:bg-sunken hover:text-ink",
        danger: "text-danger hover:bg-danger-soft",
        link: "h-auto px-0 text-accent underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-7 px-2.5 text-meta",
        md: "h-8 px-3 text-body",
        lg: "h-10 px-4 text-body",
        icon: "size-8 shrink-0",
        "icon-sm": "size-7 shrink-0 [&_svg]:size-[15px]",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild, loading, children, disabled, ...props },
  ref,
) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading && <LoaderCircle className="animate-spin" aria-hidden />}
          {children}
        </>
      )}
    </Comp>
  );
});

/* ----------------------------------------------------------------- Karte
 * Nur für das eine Objekt, an dem du gerade handelst (Freigabe, Rückfrage) – nie als Gliederung, nie verschachtelt.
 */

export function Card({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("rounded-lg border border-line bg-raised", className)} {...props} />;
}

/* ----------------------------------------------------------------- Formular-Abschnitt (Einstellungen, Einrichtung)
 * Überschrift mit Linie statt Kasten; ein Hinweis nur, wo die Bedeutung nicht aus Label und Wert hervorgeht.
 */

export function SectionHeader({
  title,
  description,
  action,
  className,
}: {
  /** ohne Titel, wenn die Seite selbst schon so heißt (z. B. „Antwortbank“) – dann bleiben Hinweis und Aktion */
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4", title && "border-b border-line pb-2", className)}>
      <div className="min-w-0">
        {title && <h2 className="text-heading font-semibold">{title}</h2>}
        {description && <p className={cn("max-w-prose text-meta text-ink-2", title && "mt-0.5")}>{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function SectionBody({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("pt-4", className)} {...props} />;
}

/* ----------------------------------------------------------------- Abschnitt: Überschrift + Linie statt Kasten */

export function Section({
  title,
  aside,
  children,
  className,
  id,
}: {
  title: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={cn("min-w-0", className)} aria-labelledby={id}>
      <div className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
        <h2 id={id} className="text-heading font-semibold">
          {title}
        </h2>
        {aside && <div className="shrink-0 text-meta text-ink-3">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

/* ----------------------------------------------------------------- Badge – nur noch für Zähler und kurze Hinweise */

const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 text-small font-medium [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "bg-sunken text-ink-2",
        accent: "bg-accent-soft text-accent",
        danger: "bg-danger-soft text-danger",
        amber: "text-amber",
        outline: "border border-line text-ink-2",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/** Zähler in Navigation und Tabs: Petrol, wenn etwas auf dich wartet, sonst grau. */
export function Count({ n, you, className }: { n: number; you?: boolean; className?: string }) {
  if (!n) return null;
  return (
    <span className={cn("tabular text-small", you ? "font-semibold text-accent" : "text-ink-3", className)}>{n}</span>
  );
}

/* ----------------------------------------------------------------- Formularfelder */

const fieldBase =
  "w-full rounded-md border border-line-input bg-raised px-2.5 text-body text-ink transition-[border-color,box-shadow] duration-[120ms] placeholder:text-ink-3 focus:border-accent focus:shadow-[0_0_0_1px_var(--accent)] focus:outline-none disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, ComponentProps<"input">>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(fieldBase, "h-8", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, ComponentProps<"textarea">>(function Textarea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={cn(fieldBase, "min-h-24 py-1.5 leading-relaxed", className)} {...props} />;
});

export const Select = forwardRef<HTMLSelectElement, ComponentProps<"select">>(function Select(
  { className, children, ...props },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn(
        fieldBase,
        "h-8 appearance-none bg-[length:16px] bg-[right_8px_center] bg-no-repeat pr-8",
        "bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23696560' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m7 15 5 5 5-5'/%3E%3Cpath d='m7 9 5-5 5 5'/%3E%3C/svg%3E\")]",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
});

export function Label({ className, ...props }: ComponentProps<"label">) {
  return <label className={cn("text-meta font-medium text-ink", className)} {...props} />;
}

/**
 * Beschriftetes Feld. Verknüpft Label und Hinweis automatisch mit dem Eingabeelement (eigene ID per useId, sofern das
 * Kind keine hat) – Screenreader lesen so Beschriftung und Hinweis vor, und ein Klick aufs Label fokussiert das Feld.
 */
export function Field({
  label,
  hint,
  error,
  children,
  className,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  const auto = useId();
  const child = isValidElement<{ id?: string }>(children) ? children : null;
  const id = htmlFor ?? child?.props.id ?? auto;
  const noteId = `${id}-note`;
  const note = error || hint;
  const control =
    child && !htmlFor
      ? cloneElement(child as ReactElement<Record<string, unknown>>, {
          id,
          "aria-describedby": note ? noteId : undefined,
          "aria-invalid": error ? true : undefined,
        })
      : children;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <Label htmlFor={id}>{label}</Label>
      {control}
      {note && (
        <p id={noteId} className={cn("text-small", error ? "text-danger" : "text-ink-3")}>
          {note}
        </p>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- Kleinteile */

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn("size-4 animate-spin text-ink-3", className)} aria-hidden />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("rounded-sm bg-sunken", className)} />;
}

/** Leerzustand: ein Satz, was als Nächstes passiert, und höchstens eine Aktion – linksbündig im Kontext. */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("py-8", className)}>
      <p className="text-heading font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-prose text-meta text-ink-2">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-sunken", className)}>
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-500 ease-standard"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-grid min-w-[18px] place-items-center rounded-sm border border-b-2 border-line px-1 font-mono text-[0.6875rem] leading-4 text-ink-3",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/** Leiste, die unten am Inhalt klebt (über der Handy-Tab-Leiste) und bis an die Ränder des Hauptbereichs reicht. */
export function StickyBar({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "sticky bottom-[var(--tabbar)] z-20 -mx-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-paper px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8",
        className,
      )}
      {...props}
    />
  );
}

/** Suchfeld mit Lupe; optional mit Tastenkürzel-Hinweis rechts. */
export const SearchInput = forwardRef<HTMLInputElement, ComponentProps<"input"> & { hint?: string }>(
  function SearchInput({ className, hint, ...props }, ref) {
    return (
      <div className={cn("relative", className)}>
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
        <Input
          ref={ref}
          type="search"
          className={cn("pl-8 [&::-webkit-search-cancel-button]:appearance-none", hint && "pr-8")}
          {...props}
        />
        {hint && <Kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2">{hint}</Kbd>}
      </div>
    );
  },
);

/** Hover-Fläche für Listenzeilen, die etwas über die Trennlinien hinausragt. */
export const rowHover = "-mx-2 rounded-md px-2 transition-colors duration-[120ms] hover:bg-sunken";

