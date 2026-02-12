## Summary

[![CI](https://github.com/gchrisjenkins/dashqt/actions/workflows/ci.yml/badge.svg)](https://github.com/gchrisjenkins/dashqt/actions/workflows/ci.yml)

**DashQt** embeds a Plotly Dash application in a Qt window via `PySide6.QtWebEngineWidgets.QWebEngineView`.
It runs a local Dash/Flask server on an available port, loads it in Qt, and coordinates shutdown so closing the window stops the server.

## Installation

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
- Qt WebEngine binaries come from `PySide6`; make sure your environment supports Qt WebEngine runtime dependencies.
- Branch protection setup checklist: `.github/BRANCH_PROTECTION_CHECKLIST.md`.
