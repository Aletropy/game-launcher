param(
  [string]$Target = (Join-Path $env:LOCALAPPDATA "MilsoLauncher"),
  [switch]$Yes,
  [switch]$Check
)
$ErrorActionPreference = "Stop"
function Find-Python {
  foreach ($c in @("python", "py")) {
    try {
      $v = & $c -c "import sys; print(1 if sys.version_info>=(3,11) else 0)" 2>$null
      if ($v -eq "1") { return $c }
    } catch {}
  }
  return $null
}
function Ensure-Python {
  $py = Find-Python
  if ($py) { return $py }
  Write-Host "Python 3.11+ not found. Trying winget..."
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if ($py) { return $py }
    throw "winget finished but python is still not on PATH. Reopen the terminal and retry."
  }
  throw "Install Python 3.11+ from https://www.python.org/downloads/ (Add to PATH), then retry."
}
if ($Check) { $null = Ensure-Python; Write-Host "Checks passed."; exit 0 }
$py = Ensure-Python
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
# The script may live at the zip root or in installer\.
# Prefer the folder containing requirements.txt / run.py.
$src = $here
if (!(Test-Path (Join-Path $src "requirements.txt")) -and (Test-Path (Join-Path (Join-Path $src "..") "requirements.txt"))) {
  $src = (Resolve-Path (Join-Path $src "..")).Path
}
if (!(Test-Path (Join-Path $src "requirements.txt"))) {
  throw "requirements.txt not found in $src. Run setup-win.ps1 from the extracted milso-launcher-*-win folder (top level or installer\)."
}
if (!(Test-Path $Target)) { New-Item -ItemType Directory -Path $Target | Out-Null }
$exclude = @(".venv", "Prefix", "prefixes", "backups", "Saves", "dist", ".git")
Get-ChildItem -Path $src -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
  Copy-Item -Path $_.FullName -Destination (Join-Path $Target $_.Name) -Recurse -Force
}
Set-Location $Target
if (!(Test-Path (Join-Path $Target "requirements.txt"))) {
  throw "Install copy is incomplete, requirements.txt missing in $Target."
}
if (!(Test-Path ".venv")) { & $py -m venv ".venv" }
& ".\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
& ".\.venv\Scripts\python.exe" -c "import PySide6"
$sm = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Milso Launcher"
New-Item -ItemType Directory -Path $sm -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut((Join-Path $sm "Milso Launcher.lnk"))
$s.TargetPath = (Join-Path $Target ".venv\Scripts\pythonw.exe")
$s.Arguments = "`"$Target\run.py`""
$s.WorkingDirectory = $Target
$s.IconLocation = "$Target\icon.png"
$s.Save()
Write-Host "Done. Launch from Start Menu or run-win.bat in $Target"
