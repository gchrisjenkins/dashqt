## Summary

[![CI](https://github.com/gchrisjenkins/dashqt/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/gchrisjenkins/dashqt/actions/workflows/ci.yml?query=branch%3Adevelop)

**DashQt** embeds a Plotly Dash application in a Qt window via `PySide6.QtWebEngineWidgets.QWebEngineView`.
It runs a local Dash/Flask server on an available port, loads it in Qt, and coordinates shutdown so closing the window stops the server.

## Installation

### Linux Runtime Dependencies

`dashqt` uses Qt WebEngine (`PySide6`) and requires system OpenGL/Qt runtime libraries on Linux.

For Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  libegl1 \
  libgl1 \
  libxkbcommon-x11-0 \
  libdbus-1-3 \
  libnss3 \
  libxcomposite1 \
  libxdamage1 \
  libxrandr2 \
  libasound2
```

If these are missing, imports may fail with errors such as
`ImportError: libEGL.so.1: cannot open shared object file`.

### Troubleshooting (Non-Ubuntu)

If you use a different OS or distro, install equivalent runtime packages:

- Fedora/RHEL:
`sudo dnf install mesa-libEGL mesa-libGL libxkbcommon-x11 dbus-libs nss libXcomposite libXdamage libXrandr alsa-lib`
- Arch Linux:
`sudo pacman -S --needed mesa libxkbcommon-x11 dbus nss libxcomposite libxdamage libxrandr alsa-lib`
- macOS:
Most systems do not need extra OpenGL packages. If Qt WebEngine import/runtime fails, install Xcode Command Line Tools with `xcode-select --install`. If you see NSS-related errors, install `nss` with `brew install nss`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

For development tools:

```bash
pip install -e .[dev]
```

Run tests:

```bash
pytest
```

Run lint checks:

```bash
ruff check src tests examples
```

Run type checks:

```bash
mypy
```

## Quick Start

Run the included example app:

```bash
python examples/example_dashqt_app.py
```

## Notes

- `EmbeddedDashApplication` is an abstract base class; implement `_build_layout()` and `_build_callbacks()` in your subclass.
- `exit_code` reports the final process status from the embedded server/browser lifecycle.
- See "Linux Runtime Dependencies" above for required system packages.
- Branch protection setup checklist: `.github/BRANCH_PROTECTION_CHECKLIST.md`.
