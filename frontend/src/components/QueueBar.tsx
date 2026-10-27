import { useState } from "react";
import { useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { formatWhen } from "@/lib/utils";
import { ApplyDialog } from "./actions";
import { Button } from "./ui/primitives";

/**
 * Leiste unter der Stellenliste, sobald Stellen als Nächstes vorgemerkt sind: sagt, wann jobslop sich ohne dich
 * bewirbt, und trägt die einzige Hauptaktion der Seite („Jetzt bewerben“).
 */
export function QueueBar() {
  const { t, tp, lang } = useI18n();
  const { data: status } = useStatus();
  const [open, setOpen] = useState(false);
  const queued = status?.counts.queued ?? 0;
  if (!queued) return null;
  const when = status?.autopilot.enabled && status.autopilot.next_run;
  return (
    <div className="sticky bottom-[calc(3.25rem+env(safe-area-inset-bottom))] z-20 -mx-4 mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line bg-paper px-4 py-3 sm:-mx-6 sm:px-6 lg:bottom-0 lg:-mx-8 lg:px-8">
      <p className="text-meta text-ink-2">
        <span className="font-semibold text-ink">{tp("queue.up_next", queued)}</span>
        {" · "}
        {when ? t("queue.bar_autopilot", { when: formatWhen(when, lang) }) : t("queue.bar_manual")}
      </p>
      <Button variant="primary" onClick={() => setOpen(true)} disabled={!!status?.runner.active}>
        {t("queue.apply_now")}
      </Button>
      <ApplyDialog open={open} onOpenChange={setOpen} queuedCount={queued} />
    </div>
  );
}
