# jobslop – Installation für Windows
#   irm https://raw.githubusercontent.com/1xxn/jobslop/main/install.ps1 | iex
# Installiert uv (falls nötig), bietet Claude Code an, installiert jobslop als Befehl und den Browser, startet jobslop.

$ErrorActionPreference = "Stop"
$Repo = if ($env:JOBSLOP_REPO) { $env:JOBSLOP_REPO } else { "git+https://github.com/1xxn/jobslop" }

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $local = Join-Path $env:USERPROFILE ".local\bin"
    if ($env:Path -notlike "*$local*") { $env:Path = "$local;$env:Path" }
}

Write-Host "jobslop – lokaler Bewerbungs-Autopilot" -ForegroundColor Magenta

Step "uv (Python-Paketmanager)"
Refresh-Path
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "uv ist schon installiert."
} else {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
}

Step "Claude Code (dein Claude-Abo)"
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "Claude Code ist schon installiert."
} else {
    $answer = Read-Host "Claude Code jetzt installieren? Ohne Claude geht nur ein einfacher Regel-Modus. [J/n]"
    if ($answer -notmatch "^[nN]") {
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        Refresh-Path
        Write-Host "Die Anmeldung erledigst du gleich in der Einrichtung von jobslop."
    }
}

Step "jobslop installieren"
uv tool install --force $Repo
uv tool update-shell | Out-Null
Refresh-Path

Step "Browser (Chromium) für die Formulare"
jobslop install-browser

Step "Fertig – jobslop startet"
Write-Host "Später einfach 'jobslop' in einem neuen Terminal eingeben." -ForegroundColor Green
jobslop
