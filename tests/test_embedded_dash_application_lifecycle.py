import threading
import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("dash")
pytest.importorskip("plotly")

from dashqt import EmbeddedDashApplication, EmbeddedDashApplicationListener


class _RecordingListener(EmbeddedDashApplicationListener):
    def __init__(self) -> None:
        self.started_calls = 0
        self.stopped_exit_codes: list[int] = []

    def on_dash_app_started(self, app: EmbeddedDashApplication) -> None:
        self.started_calls += 1

    def on_dash_app_stopped(self, app: EmbeddedDashApplication, exit_code: int) -> None:
        self.stopped_exit_codes.append(exit_code)


class _DummyApp(EmbeddedDashApplication):
    def _build_layout(self):
        return []

    def _build_callbacks(self):
        return []


def _start_thread(target) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def _start_sleeping_thread(app: _DummyApp, attr_name: str, sleep_seconds: float) -> bool:
    setattr(app, attr_name, _start_thread(lambda: time.sleep(sleep_seconds)))
    return True


def _set_event_and_return_true(event: threading.Event) -> bool:
    event.set()
    return True


def test_successful_start_and_stop_notifies_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _RecordingListener()
    app = _DummyApp(listener=listener, name="DummyApp")

    monkeypatch.setattr(app, "_start_server", lambda: _start_sleeping_thread(app, "_server_thread", 0.1))
    monkeypatch.setattr(app, "_start_browser", lambda: _start_sleeping_thread(app, "_browser_thread", 0.1))

    app.run_forever()

    assert app.exit_code == 0
    assert listener.started_calls == 1
    assert listener.stopped_exit_codes == [0]


def test_server_start_failure_sets_nonzero_exit_code() -> None:
    listener = _RecordingListener()
    app = _DummyApp(listener=listener, name="DummyApp")

    app._start_server = lambda: False  # type: ignore[method-assign]

    app.run_forever()

    assert app.exit_code == 1
    assert listener.started_calls == 0
    assert listener.stopped_exit_codes == [1]


def test_browser_start_failure_requests_server_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _RecordingListener()
    app = _DummyApp(listener=listener, name="DummyApp")
    stop_server = threading.Event()

    def start_server() -> bool:
        app._server_thread = _start_thread(lambda: stop_server.wait(timeout=5))
        return True

    monkeypatch.setattr(app, "_start_server", start_server)
    monkeypatch.setattr(app, "_start_browser", lambda: False)
    monkeypatch.setattr(
        app,
        "_request_server_shutdown_from_main",
        lambda: _set_event_and_return_true(stop_server),
    )

    app.run_forever()

    assert app.exit_code == 1
    assert stop_server.is_set()
    assert listener.started_calls == 0
    assert listener.stopped_exit_codes == [1]


def test_browser_exit_while_server_running_triggers_server_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _RecordingListener()
    app = _DummyApp(listener=listener, name="DummyApp")
    stop_server = threading.Event()

    def start_server() -> bool:
        app._server_thread = _start_thread(lambda: stop_server.wait(timeout=5))
        return True

    def start_browser() -> bool:
        app._browser_thread = _start_thread(lambda: app._set_exit_code(2))
        return True

    monkeypatch.setattr(app, "_start_server", start_server)
    monkeypatch.setattr(app, "_start_browser", start_browser)
    monkeypatch.setattr(
        app,
        "_request_server_shutdown_from_main",
        lambda: _set_event_and_return_true(stop_server),
    )

    app.run_forever()

    assert app.exit_code == 2
    assert stop_server.is_set()
    assert listener.started_calls == 1
    assert listener.stopped_exit_codes == [2]


def test_server_exit_while_browser_running_triggers_browser_close(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _RecordingListener()
    app = _DummyApp(listener=listener, name="DummyApp")
    close_browser = threading.Event()

    def start_server() -> bool:
        app._server_thread = _start_thread(lambda: app._set_exit_code(3))
        return True

    def start_browser() -> bool:
        app._browser_thread = _start_thread(lambda: close_browser.wait(timeout=5))
        return True

    monkeypatch.setattr(app, "_start_server", start_server)
    monkeypatch.setattr(app, "_start_browser", start_browser)
    monkeypatch.setattr(
        app,
        "request_browser_close",
        lambda: _set_event_and_return_true(close_browser),
    )

    app.run_forever()

    assert app.exit_code == 3
    assert close_browser.is_set()
    assert listener.started_calls == 1
    assert listener.stopped_exit_codes == [3]
