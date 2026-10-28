import { createContext, useContext } from "react";

/** Öffnet die Lauf-Seitenleiste von überall (Statuszeile, Handy-Kopfzeile, nach „Bewerben“). */
export const RunDrawerContext = createContext<{ open: () => void }>({ open: () => {} });

export function useRunDrawer() {
  return useContext(RunDrawerContext);
}
