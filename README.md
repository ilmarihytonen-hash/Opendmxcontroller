# LumenDesk

LumenDesk is a cross-platform DMX lighting controller with a straightforward,
touch-friendly desktop interface. The application combines a C++17 DMX buffer
and effect engine with a Python/PySide6 user interface.

## Features

- Live editing of all 512 DMX slots in a universe.
- Starts with 100 universes; change the configured count from **Connections**.
  Values are retained when the universe count is changed.
- Custom fixture profile editor with channel names, patching, overlap checks,
  and saved fixture instances.
- Built-in Pulse, Chase, Wave, Strobe, and Sine effects, plus a simple effect
  creator with fixture and channel-attribute targeting.
- Art-Net (UDP 6454), sACN / ANSI E1.31 (UDP 5568), Enttec-style OpenDMX serial,
  and OSC DMX-channel input/output.
- MIDI Control Change input and output mapped to one configurable DMX slot.
- Large controls and rows for touchscreen operation.
- Project configuration saved in the operating system's application-data folder.

OpenDMX uses a serial adapter that supports DMX break signalling. It outputs
universe 1; Art-Net and sACN transmit every configured universe. Art-Net
universe numbers above 32768 are not sent. MIDI uses Windows MIDI Services
(WinMM) on Windows and Mido/python-rtmidi on Linux. OSC uses UDP; the default input and output ports are 9000
and 9001. OSC messages use
`/lumendesk/universe/<universe>/channel/<channel>` with an integer value from
0–255 or a normalized float from 0–1.

## Development run

Requirements: Python 3.10+, CMake 3.16+, and a C++17 compiler. On Ubuntu Server, install a GNOME desktop session to run this graphical application.

```powershell
python -m pip install -r requirements.txt
cmake -S . -B build
cmake --build build --config Release
python run.py
```

On Linux, use `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release` and
`cmake --build build`. Then run `python3 run.py`.

## Windows executable

Open PowerShell in the project directory and run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The runnable executable is `dist\LumenDesk\LumenDesk.exe`. The build requires
CMake, a C++ toolchain, and Python. PyInstaller creates a distributable folder
containing the executable and its runtime files.

## Ubuntu AppImage

Build on Ubuntu/Linux; an AppImage is a Linux binary and cannot be compiled
natively on Windows. Install CMake, a C++17 toolchain, Python 3 with `venv`
support, `libasound2-dev`, the XCB runtime libraries, and `curl`, then run.
The script downloads the official linuxdeploy AppImage into the ignored
`build/tools` folder:

```bash
chmod +x scripts/build_appimage.sh
./scripts/build_appimage.sh
```

The script packages the app with linuxdeploy and places the `.AppImage` in the
`dist` directory. Build on the oldest Ubuntu release you intend to support to
maximize compatibility with newer Ubuntu systems.

GitHub Actions also builds both platform packages on pushes and pull requests.
Download the Windows folder or Ubuntu `.AppImage` from the run's **Artifacts**
section.

## Updating a Git checkout

Use `scripts/update_windows.ps1` on Windows or `scripts/update_linux.sh` on
Ubuntu. Each script performs a fast-forward-only `git pull` and then rebuilds
the platform package. Standalone packages are not self-updating.

## Tests

Run the protocol and OSC message tests with:

```powershell
python -m unittest discover -s tests
```
