import { Check, X } from "lucide-react";
import { Dialog as D, DropdownMenu as DM, Tooltip as T } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function CloseButton() {
  const { t } = useI18n();
  return (
    <D.Close className="grid size-8 place-items-center rounded-md text-ink-2 hover:bg-sunken hover:text-ink">
      <X className="size-4" />
      <span className="sr-only">{t("common.close")}</span>
    </D.Close>
  );
}

/* ----------------------------------------------------------------- Dialog (Modal, mittig) */

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  title,
  description,
  children,
  className,
  footer,
  wide,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-scrim data-[state=open]:animate-fade-in" />
      <D.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 flex max-h-[min(88dvh,820px)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-line bg-raised shadow-overlay focus:outline-none data-[state=open]:animate-scale-in",
          wide ? "max-w-3xl" : "max-w-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-2">
          <div className="min-w-0">
            <D.Title className="text-title font-semibold">{title}</D.Title>
            {description ? (
              <D.Description className="mt-0.5 text-meta text-ink-2">{description}</D.Description>
            ) : (
              <D.Description className="sr-only">{String(title)}</D.Description>
            )}
          </div>
          <div className="-mr-2">
            <CloseButton />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </D.Content>
    </D.Portal>
  );
}

/* ----------------------------------------------------------------- Seitenleiste (fährt von rechts herein) */

export function Sheet({
  open,
  onOpenChange,
  title,
  children,
  actions,
  className,
  hotkeys,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
  /** Tastenkürzel der Seite bleiben aktiv, solange die Seitenleiste offen ist (z. B. A/S/X in einer Stelle). */
  hotkeys?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-scrim data-[state=open]:animate-fade-in" />
        <D.Content
          // Fokus auf das Panel selbst statt auf „Schließen“ – kein Fokusring beim Öffnen, Tastatur bleibt im Panel
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement).focus();
          }}
          tabIndex={-1}
          data-hotkeys={hotkeys ? "" : undefined}
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex w-full max-w-[720px] flex-col border-l border-line bg-raised shadow-overlay focus:outline-none data-[state=open]:animate-sheet-in",
            className,
          )}
        >
          <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-2.5">
            <D.Title className="min-w-0 truncate text-heading font-semibold">{title}</D.Title>
            <D.Description className="sr-only">{String(title)}</D.Description>
            <div className="flex shrink-0 items-center gap-1">
              {actions}
              <CloseButton />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

/* ----------------------------------------------------------------- Tooltip */

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <T.Provider delayDuration={350}>{children}</T.Provider>;
}

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  if (!content) return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-[60] max-w-xs rounded-md bg-ink px-2 py-1 text-small text-paper data-[state=delayed-open]:animate-fade-in"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

/* ----------------------------------------------------------------- Dropdown-Menü */

export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;
export const MenuRadioGroup = DM.RadioGroup;

export function MenuContent({ className, align = "end", ...props }: ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn(
          "z-50 min-w-48 rounded-lg border border-line bg-raised p-1 shadow-overlay data-[state=open]:animate-fade-in",
          className,
        )}
        {...props}
      />
    </DM.Portal>
  );
}

const itemBase =
  "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2 py-1.5 text-body outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-sunken data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-ink-3";

export function MenuItem({
  className,
  danger,
  icon,
  children,
  ...props
}: ComponentProps<typeof DM.Item> & { danger?: boolean; icon?: ReactNode }) {
  return (
    <DM.Item className={cn(itemBase, danger && "text-danger [&_svg]:text-danger", className)} {...props}>
      {icon}
      {children}
    </DM.Item>
  );
}

export function MenuRadioItem({ className, children, ...props }: ComponentProps<typeof DM.RadioItem>) {
  return (
    <DM.RadioItem className={cn(itemBase, "relative pl-7", className)} {...props}>
      <DM.ItemIndicator className="absolute left-2 [&_svg]:text-ink">
        <Check />
      </DM.ItemIndicator>
      {children}
    </DM.RadioItem>
  );
}

export function MenuCheckboxItem({ className, children, ...props }: ComponentProps<typeof DM.CheckboxItem>) {
  return (
    <DM.CheckboxItem className={cn(itemBase, "relative pl-7", className)} {...props}>
      <DM.ItemIndicator className="absolute left-2 [&_svg]:text-ink">
        <Check />
      </DM.ItemIndicator>
      {children}
    </DM.CheckboxItem>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <DM.Label className="px-2 pt-2 pb-1 text-small font-medium text-ink-3">{children}</DM.Label>;
}

export function MenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-line" />;
}
