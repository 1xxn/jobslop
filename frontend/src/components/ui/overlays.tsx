import { X } from "lucide-react";
import { Dialog as D, DropdownMenu as DM, Tooltip as T } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

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
      <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
      <D.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 flex max-h-[min(88dvh,820px)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-surface shadow-lg focus:outline-none data-[state=open]:animate-scale-in",
          wide ? "max-w-3xl" : "max-w-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-2">
          <div>
            <D.Title className="text-title3 font-semibold tracking-[-0.015em]">{title}</D.Title>
            {description ? (
              <D.Description className="mt-1 text-footnote text-fg-muted">{description}</D.Description>
            ) : (
              <D.Description className="sr-only">{String(title)}</D.Description>
            )}
          </div>
          <D.Close className="-mr-2 -mt-1 grid size-8 place-items-center rounded-full text-fg-muted hover:bg-surface-2 hover:text-fg">
            <X className="size-4" />
            <span className="sr-only">Schließen</span>
          </D.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>}
      </D.Content>
    </D.Portal>
  );
}

/* ----------------------------------------------------------------- Sheet (Seitenpanel) */

export function Sheet({
  open,
  onOpenChange,
  title,
  children,
  actions,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/25 data-[state=open]:animate-fade-in" />
        <D.Content
          // Fokus auf das Panel selbst statt auf „Schließen“ – kein Fokusring beim Öffnen, Tastatur bleibt im Panel
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement).focus();
          }}
          tabIndex={-1}
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[720px] flex-col border-l border-border bg-surface shadow-lg focus:outline-none data-[state=open]:animate-sheet-in"
        >
          <div className="glass sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border px-5 py-3">
            <D.Title className="truncate text-headline font-semibold">{title}</D.Title>
            <D.Description className="sr-only">{String(title)}</D.Description>
            <div className="flex items-center gap-1">
              {actions}
              <D.Close className="grid size-8 place-items-center rounded-full text-fg-muted hover:bg-surface-2 hover:text-fg">
                <X className="size-4" />
                <span className="sr-only">Schließen</span>
              </D.Close>
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

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  if (!content) return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-[60] max-w-xs rounded-md bg-fg px-2.5 py-1.5 text-caption text-bg shadow-md data-[state=delayed-open]:animate-fade-in"
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

export function MenuContent({ className, align = "end", ...props }: ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn(
          "z-50 min-w-48 rounded-lg border border-border bg-surface p-1 shadow-lg data-[state=open]:animate-fade-in",
          className,
        )}
        {...props}
      />
    </DM.Portal>
  );
}

export function MenuItem({
  className,
  danger,
  icon,
  children,
  ...props
}: ComponentProps<typeof DM.Item> & { danger?: boolean; icon?: ReactNode }) {
  return (
    <DM.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[0.875rem] outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-surface-2 data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-fg-muted",
        danger && "text-danger [&_svg]:text-danger",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </DM.Item>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <DM.Label className="px-2.5 pt-2 pb-1 text-caption font-medium text-fg-subtle">{children}</DM.Label>;
}

export function MenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-border" />;
}
