import { useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/primitives";

/** Schwebende Leiste für ungespeicherte Änderungen (wie in den macOS-Einstellungen mit „Sichern“). */
export function SaveBar({
  dirty,
  saving,
  onSave,
  onReset,
}: {
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onReset: () => void;
}) {
  const { t } = useI18n();
  if (!dirty) return null;
  return (
    <div className="glass fixed inset-x-4 bottom-20 z-30 mx-auto flex max-w-xl items-center gap-3 rounded-xl border border-border px-4 py-3 shadow-lg animate-slide-up lg:bottom-6 lg:left-[248px]">
      <span className="mr-auto text-[0.875rem] font-medium">{t("common.unsaved")}</span>
      <Button variant="ghost" size="sm" onClick={onReset}>
        {t("common.discard")}
      </Button>
      <Button variant="primary" size="sm" onClick={onSave} loading={saving}>
        {t("common.save")}
      </Button>
    </div>
  );
}
