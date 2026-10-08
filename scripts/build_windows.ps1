$ErrorActionPreference = "Stop"

$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
if ($cmakeCommand) {
    $cmake = $cmakeCommand.Source
} else {
    $cmake = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Filter cmake.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $cmake) {
    throw "CMake is required. Install CMake and a C++17 compiler, then rerun this script."
}

python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Could not install Python build dependencies." }

& $cmake -S . -B build
if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed." }
& $cmake --build build --config Release
if ($LASTEXITCODE -ne 0) { throw "The C++ DMX engine build failed." }

$nativeDll = Join-Path (Get-Location) "build\Release\lumendesk_core.dll"
if (-not (Test-Path $nativeDll)) {
    $nativeDll = Join-Path (Get-Location) "build\lumendesk_core.dll"
}
if (-not (Test-Path $nativeDll)) {
    throw "Could not find the built lumendesk_core.dll."
}

python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name LumenDesk --add-binary "$nativeDll;." `
    --hidden-import=mido.backends.rtmidi --hidden-import=rtmidi run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller packaging failed." }

Write-Host "Windows application: dist\LumenDesk\LumenDesk.exe"
