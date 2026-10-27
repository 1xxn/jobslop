import { Button } from "@/components/ui/primitives";
import { useI18n } from "@/lib/i18n";

/** Leiste für ungespeicherte Änderungen: klebt unten am Formular und trägt die einzige Hauptaktion der Seite. */
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
    <div className="sticky bottom-[calc(3.25rem+env(safe-area-inset-bottom))] z-20 -mx-4 flex items-center gap-2 border-t border-line bg-paper px-4 py-3 animate-fade-in sm:-mx-6 sm:px-6 lg:bottom-0 lg:-mx-8 lg:px-8">
      <span className="mr-auto text-meta font-medium" role="status">
        {t("common.unsaved")}
      </span>
      <Button variant="quiet" size="sm" onClick={onReset}>
        {t("common.discard")}
      </Button>
      <Button variant="primary" size="sm" onClick={onSave} loading={saving}>
        {t("common.save")}
      </Button>
    </div>
  );
}
