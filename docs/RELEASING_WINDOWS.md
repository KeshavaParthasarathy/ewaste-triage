# Windows prototype release

The Windows product targets 64-bit Windows 11. It is currently unsigned, so Windows may show an unrecognized-publisher warning.

## Build locally on Windows

Install Python 3.11, then run in PowerShell:

```powershell
python -m pip install -r requirements-app.txt pyinstaller==6.22.2 pytest==9.1.1
./scripts/build_windows_app.ps1 -Version 0.1.0
```

The build writes `dist/E-Waste-Triage-0.1.0-windows-x64.zip`. Extract the ZIP before starting `E-Waste Triage.exe`; do not run the executable from inside the ZIP.

Verify the download in PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 ./E-Waste-Triage-0.1.0-windows-x64.zip
```

## Publish through GitHub

Run the **Windows desktop release** workflow manually first. It builds the EXE, runs the packaged scan smoke test, and uploads the ZIP as a workflow artifact.

After that run passes, publish version 0.1.0:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The tag run attaches the ZIP to the matching GitHub Release. Do not publish the tag if the packaged smoke test fails.
