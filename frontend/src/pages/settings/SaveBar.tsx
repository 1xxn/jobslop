import { Button, StickyBar } from "@/components/ui/primitives";
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
    <StickyBar className="mt-0 flex-nowrap animate-fade-in">
      <span className="mr-auto text-meta font-medium" role="status">
        {t("common.unsaved")}
      </span>
      <Button variant="quiet" size="sm" onClick={onReset}>
        {t("common.discard")}
      </Button>
      <Button variant="primary" size="sm" onClick={onSave} loading={saving}>
        {t("common.save")}
      </Button>
    </StickyBar>
  );
}
