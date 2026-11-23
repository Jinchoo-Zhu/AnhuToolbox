[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Notes = "",
    [string]$NotesFile = "",
    [switch]$Mandatory
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}

$version = (& $python -c "from anhutoolbox.version import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "Unable to read application version"
}
$installerScript = Get-Content -Raw (Join-Path $PSScriptRoot "installer.iss")
if (-not $installerScript.Contains(
        ('#define MyAppVersion "{0}"' -f $version))) {
    throw "installer.iss version does not match $version"
}
$versionInfo = Get-Content -Raw (Join-Path $PSScriptRoot "version_info.txt")
$fileVersion = $version.Replace(".", ", ")
if (-not $versionInfo.Contains("filevers=($fileVersion, 0)")) {
    throw "version_info.txt version does not match $version"
}
if (-not $versionInfo.Contains(
        ("StringStruct(u'FileVersion', u'{0}')" -f $version)) -or
    -not $versionInfo.Contains(
        ("StringStruct(u'ProductVersion', u'{0}')" -f $version))) {
    throw "version_info.txt string version does not match $version"
}

& $python -m PyInstaller --noconfirm (
    Join-Path $PSScriptRoot "AnhuToolbox.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller main application build failed" }

& $python -m PyInstaller --noconfirm (
    Join-Path $PSScriptRoot "AnhuUpdater.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller updater build failed" }

$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 ISCC.exe was not found" }

& $iscc (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }

$installerPath = Join-Path $PSScriptRoot (
    "installer\AnhuToolbox_Setup_{0}.exe" -f $version)
$manifestArgs = @(
    (Join-Path $PSScriptRoot "create_update_manifest.py"),
    "--installer", $installerPath,
    "--version", $version,
    "--output", (Join-Path $PSScriptRoot "installer\latest.json")
)
if ($NotesFile) {
    if (-not (Test-Path -LiteralPath $NotesFile -PathType Leaf)) {
        throw "NotesFile does not exist: $NotesFile. Use -Notes `"text`" for inline release notes."
    }
    $manifestArgs += @(
        "--notes-file",
        (Resolve-Path -LiteralPath $NotesFile).Path
    )
} elseif ($Notes) {
    $manifestArgs += @("--notes", $Notes)
}
if ($Mandatory) { $manifestArgs += "--mandatory" }

& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw "latest.json generation failed" }

Write-Host "Release version: $version"
Write-Host "Installer: $installerPath"
Write-Host "Manifest: $PSScriptRoot\installer\latest.json"
