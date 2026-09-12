param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$ReleaseDir = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Windows packaging requires Windows"
}
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "Version must use X.Y.Z"
}
if (-not $ReleaseDir) {
    $ReleaseDir = Join-Path $ProjectRoot "packaging/runtime/$Version"
}
$ReleaseDir = (Resolve-Path $ReleaseDir).Path

& $PythonBin -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 is required" }
& $PythonBin -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) { throw "Install the pinned PyInstaller dependency" }

$SourceRevision = (& git -C $ProjectRoot rev-parse --verify 'HEAD^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw "Source tree must have a Git commit" }
$SourceStatus = (& git -C $ProjectRoot status --porcelain=v1 --untracked-files=all) -join "`n"
if ($LASTEXITCODE -ne 0 -or $SourceStatus) {
    throw "Source tree must be clean before packaging"
}

$ReleaseManifest = Join-Path $ReleaseDir "release-manifest.json"
$ClrConfig = (Resolve-Path (Join-Path $ProjectRoot "desktop/windows/E-Waste Triage.exe.config")).Path
$ReleaseRecord = Get-Content -Raw $ReleaseManifest | ConvertFrom-Json
if ($ReleaseRecord.app_version -ne $Version) { throw "Release version does not match" }
if (
    $ReleaseRecord.target.platform -ne "windows" -or
    $ReleaseRecord.target.architecture -ne "x86_64" -or
    $ReleaseRecord.target.minimum_version -ne "11"
) {
    throw "Release target must be Windows 11 x64"
}

$BuildRoot = Join-Path $ProjectRoot "build/windows/$Version"
$PyInstallerDist = Join-Path $BuildRoot "pyinstaller-dist"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller-work"
$Generated = Join-Path $BuildRoot "generated"
$BuildMetadata = Join-Path $Generated "build-metadata.json"
$FinalDist = Join-Path $ProjectRoot "dist"
$ZipPath = Join-Path $FinalDist "E-Waste-Triage-$Version-windows-x64.zip"

if (Test-Path $BuildRoot) { Remove-Item -Recurse -Force $BuildRoot }
New-Item -ItemType Directory -Force $PyInstallerDist, $PyInstallerWork, $Generated, $FinalDist | Out-Null

$ManifestHash = (Get-FileHash -Algorithm SHA256 $ReleaseManifest).Hash.ToLowerInvariant()
$BuildRecord = [ordered]@{
    schema_version = 1
    app_version = $Version
    source_revision = $SourceRevision
    release_manifest_sha256 = $ManifestHash
}
$BuildJson = $BuildRecord | ConvertTo-Json
[System.IO.File]::WriteAllText(
    $BuildMetadata,
    $BuildJson + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)

$env:EWASTE_RELEASE_DIR = $ReleaseDir
$env:EWASTE_ICON_PATH = Join-Path $ProjectRoot "desktop/assets/app-icon.ico"
$env:EWASTE_BUILD_METADATA = $BuildMetadata
$env:EWASTE_APP_VERSION = $Version
& $PythonBin -m PyInstaller --noconfirm --clean --workpath $PyInstallerWork --distpath $PyInstallerDist (Join-Path $ProjectRoot "packaging/EWasteTriage-Windows.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$BuiltApp = Join-Path $PyInstallerDist "E-Waste Triage"
Copy-Item -LiteralPath $ClrConfig -Destination (Join-Path $BuiltApp "E-Waste Triage.exe.config")
& $PythonBin (Join-Path $ProjectRoot "scripts/verify_windows_bundle.py") --release-dir $ReleaseDir --app-dir $BuiltApp --expected-version $Version
if ($LASTEXITCODE -ne 0) { throw "Windows bundle verification failed" }

if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $BuiltApp -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Output $ZipPath
