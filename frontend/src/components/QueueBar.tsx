import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { formatWhen } from "@/lib/utils";
import { ApplyDialog } from "./actions";
import { Button, StickyBar } from "./ui/primitives";

/**
 * Leiste unter der Stellenliste, sobald Stellen als Nächstes vorgemerkt sind: sagt, wann jobslop sich ohne dich
 * bewirbt, und trägt die einzige Hauptaktion der Seite („Jetzt bewerben“).
 */
export function QueueBar() {
  const { t, tp, lang } = useI18n();
  const { data: status } = useStatus();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [open, setOpen] = useState(false);
  const queued = status?.counts.queued ?? 0;
  if (!queued) return null;
  // „bewirbt sich“ nur, wenn der Autopilot nach der Suche auch bewirbt – sonst sucht er bloß
  const when = status?.autopilot.enabled && settings.data?.autopilot_apply && status.autopilot.next_run;
  return (
    <StickyBar className="justify-between gap-x-4">
      <p className="text-meta text-ink-2">
        <span className="font-semibold text-ink">{tp("queue.up_next", queued)}</span>
        {" · "}
        {when ? t("queue.bar_autopilot", { when: formatWhen(when, lang) }) : t("queue.bar_manual")}
      </p>
      <Button variant="primary" onClick={() => setOpen(true)} disabled={!!status?.runner.active}>
        {t("queue.apply_now")}
      </Button>
      <ApplyDialog open={open} onOpenChange={setOpen} queuedCount={queued} />
    </StickyBar>
  );
}
