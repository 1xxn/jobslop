// Theme vor dem ersten Paint setzen (kein Aufblitzen). Eigene Datei statt Inline-Skript: die Content-Security-Policy
// des Dashboards erlaubt nur Skripte vom eigenen Server.
try {
  const t = localStorage.getItem("jobslop.theme") || "system";
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
} catch {}
