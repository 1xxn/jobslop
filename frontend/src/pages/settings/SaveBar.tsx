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
    <div className="fixed inset-x-4 bottom-20 z-30 mx-auto flex max-w-xl items-center gap-3 rounded-lg border border-line bg-raised px-4 py-2.5 shadow-overlay animate-slide-up lg:bottom-6 lg:left-[208px]">
      <span className="mr-auto text-body font-medium">{t("common.unsaved")}</span>
      <Button variant="quiet" size="sm" onClick={onReset}>
        {t("common.discard")}
      </Button>
      <Button variant="primary" size="sm" onClick={onSave} loading={saving}>
        {t("common.save")}
      </Button>
    </div>
  );
}
