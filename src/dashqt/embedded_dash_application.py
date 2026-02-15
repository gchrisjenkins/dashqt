import logging
import socket
import threading
import time
import traceback
from abc import ABC, abstractmethod
from os import PathLike
from typing import Any, Callable, cast

import requests
import werkzeug
from dash import Dash, Input, Output
from dash.development.base_component import Component
from flask import Flask
from plotly.graph_objs import Figure

try:
    from PySide6.QtCore import (
        QCoreApplication,
        QEvent,
        QMetaObject,
        QMessageLogContext,
        Qt,
        QtMsgType,
        QUrl,
        qInstallMessageHandler,
    )
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow
except ImportError as exc:
    raise ImportError(
        "Failed to import PySide6 Qt runtime dependencies. "
        "Install Linux system libraries and try again: "
        "`sudo apt-get update && COMMON_PACKAGES=\"libegl1 libgl1 "
        "libxkbcommon-x11-0 libdbus-1-3 libnss3 libxcomposite1 "
        "libxdamage1 libxrandr2\" && sudo apt-get install -y "
        "--no-install-recommends $COMMON_PACKAGES libasound2t64 || "
        "sudo apt-get install -y --no-install-recommends "
        "$COMMON_PACKAGES libasound2`. "
        "See README.md: Linux Runtime Dependencies."
    ) from exc


class EmbeddedDashApplicationListener(ABC):
    """Receives lifecycle events from an :class:`EmbeddedDashApplication`."""

    @abstractmethod
    def on_dash_app_started(self, app: "EmbeddedDashApplication") -> None:
        """Called after server and browser threads have started successfully."""

    @abstractmethod
    def on_dash_app_stopped(self, app: "EmbeddedDashApplication", exit_code: int) -> None:
        """Called immediately before :meth:`EmbeddedDashApplication.run_forever` returns."""


class EmbeddedDashApplication(ABC):
    """Run a Dash app embedded in a Qt WebEngine window."""

    def __init__(
        self,
        listener: EmbeddedDashApplicationListener | None = None,
        name: str | None = None,
        assets_folder: str | PathLike[str] | None = None,
    ) -> None:
        cls = type(self)
        self._logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")

        self._listener = listener
        self._name = name

        server = Flask(type(self).__name__)
        dash_kwargs: dict[str, Any] = {"server": server}
        if assets_folder is not None:
            dash_kwargs["assets_folder"] = str(assets_folder)
        self._server = Dash(type(self).__name__, **dash_kwargs)

        @server.route("/health")
        def health_check() -> tuple[str, int]:
            return "OK", 200

        self._server_port: int | None = None
        self._server_thread: threading.Thread | None = None
        self._wsgi_server: werkzeug.serving.BaseWSGIServer | None = None

        self._browser: EmbeddedDashApplication._EmbeddedBrowser | None = None
        self._browser_thread: threading.Thread | None = None

        self._exit_code = 0
        self._exit_code_lock = threading.Lock()

        self._server_shutdown_requested = threading.Event()
        self._browser_close_requested = threading.Event()

    def run_forever(self) -> None:
        self._logger.info("Starting %s...", type(self).__name__)
        started_successfully = False

        try:
            if not self._start_server():
                self._logger.error("The Dash server failed to start. Shutting down...")
                self._set_exit_code(1)
            elif not self._start_browser():
                self._logger.error("The browser failed to start. Shutting down...")
                self._shutdown_server_and_wait(timeout=5)
                self._set_exit_code(1)
            else:
                started_successfully = True
                self._logger.info("The Dash server and browser started successfully")
                self._notify_started()
                self._monitor_threads_until_exit()

        except Exception as exc:
            self._logger.error("Unexpected error while running Dash application: %s", exc)
            self._logger.error(traceback.format_exc())
            self._set_exit_code(1)
            if started_successfully:
                self._cleanup_on_error()

        finally:
            self._notify_stopped()
            self._logger.info("%s finishing with exit code: %s", type(self).__name__, self.exit_code)

            if self._server_thread and self._server_thread.is_alive():
                self._logger.warning("Server thread is still alive during final cleanup")
            if self._browser_thread and self._browser_thread.is_alive():
                self._logger.warning("Browser thread is still alive during final cleanup")

    def request_browser_close(self) -> None:
        """Request a graceful close of the embedded browser window."""
        first_attempt = not self._browser_close_requested.is_set()
        self._browser_close_requested.set()
        if first_attempt:
            self._logger.info("Received request to close browser window")
        if self._browser:
            self._browser.close_main_window()
        elif first_attempt:
            self._logger.warning("Cannot request browser close: browser instance is not available")

    @property
    def exit_code(self) -> int:
        with self._exit_code_lock:
            return self._exit_code

    @abstractmethod
    def _build_layout(self) -> Component | list[Component]:
        """Return either a single Dash component or a list of components."""

    @abstractmethod
    def _build_callbacks(self) -> list[tuple[Output | list[Output], Input | list[Input], Callable[..., Figure]]]:
        """Return `(outputs, inputs, callback_fn)` callback descriptors."""

    def _start_server(self) -> bool:
        try:
            self._server.layout = self._build_layout()
            for outputs, inputs, func in self._build_callbacks():
                self._server.callback(outputs, inputs)(func)

            self._server_port = self._find_available_port()
            self._logger.debug("Starting Dash server on 127.0.0.1:%s", self._server_port)

            self._server_thread = threading.Thread(
                target=self._run_server,
                name=f"{Dash.__name__}Thread",
                daemon=False,
            )
            self._server_thread.start()

            return self._wait_for_server_ready(max_wait_seconds=15.0, retry_interval_seconds=0.25)

        except Exception as exc:
            self._logger.error("Failed to start Dash server: %s", exc)
            self._logger.error(traceback.format_exc())
            if self._server_thread and self._server_thread.is_alive():
                self._request_server_shutdown_from_main()
            return False

    def _wait_for_server_ready(self, max_wait_seconds: float, retry_interval_seconds: float) -> bool:
        if self._server_port is None:
            return False

        start_time = time.time()
        while True:
            if time.time() - start_time > max_wait_seconds:
                self._logger.error(
                    "Dash server health check timed out after %.2f seconds",
                    max_wait_seconds,
                )
                self._shutdown_server_and_wait(timeout=5)
                return False

            if self._server_thread and not self._server_thread.is_alive():
                self._logger.error("Dash server thread terminated unexpectedly during startup")
                return False

            try:
                response = requests.get(
                    f"http://127.0.0.1:{self._server_port}/health",
                    timeout=1,
                )
                if response.status_code == 200:
                    self._logger.debug("Dash server is ready")
                    return True
            except requests.exceptions.ConnectionError:
                # Server is still warming up.
                time.sleep(retry_interval_seconds)
            except requests.exceptions.RequestException as exc:
                self._logger.warning(
                    "Health check request failed: %s; retrying in %.2f seconds",
                    exc,
                    retry_interval_seconds,
                )
                time.sleep(retry_interval_seconds)

    def _run_server(self) -> None:
        try:
            if self._server_port is None:
                raise RuntimeError("Server port was not initialized before server thread startup")

            self._wsgi_server = werkzeug.serving.make_server(
                "127.0.0.1",
                self._server_port,
                self._server.server,
                threaded=True,
            )
            self._wsgi_server.serve_forever()

        except Exception as exc:
            self._logger.error("Error while running Dash server: %s", exc)
            self._logger.error(traceback.format_exc())
            self._set_exit_code(1)

        finally:
            self._logger.debug("Dash server thread has terminated")

    def _start_browser(self) -> bool:
        try:
            self._browser_thread = threading.Thread(
                target=self._run_browser,
                name=f"{EmbeddedDashApplication._EmbeddedBrowser.__name__}Thread",
                daemon=False,
            )
            self._browser_thread.start()
            return True

        except Exception as exc:
            self._logger.error("Failed to start browser thread: %s", exc)
            self._logger.error(traceback.format_exc())
            return False

    def _run_browser(self) -> None:
        try:
            if self._server_port is None:
                raise RuntimeError("Server port is unavailable for browser startup")

            self._browser = EmbeddedDashApplication._EmbeddedBrowser(
                url=f"http://127.0.0.1:{self._server_port}",
                title=self._name,
            )

            if self._wsgi_server is None:
                self._logger.error("Cannot set shutdown callback: WSGI server instance is not available")
                self._set_exit_code(1)
                return

            self._browser.set_server_shutdown_callback(self._wsgi_server.shutdown)
            browser_exit_code = self._browser.run_forever()
            self._set_exit_code(browser_exit_code)

        except Exception as exc:
            self._logger.error("Error while running browser thread: %s", exc)
            self._logger.error(traceback.format_exc())
            self._set_exit_code(1)

        finally:
            self._logger.debug("Browser thread has terminated")

    def _monitor_threads_until_exit(self) -> None:
        self._logger.info("Dash application is running and monitoring threads")
        server_stopped_first = False
        browser_stopped_first = False

        while True:
            server_alive = bool(self._server_thread and self._server_thread.is_alive())
            browser_alive = bool(self._browser_thread and self._browser_thread.is_alive())

            if not server_alive and not browser_alive:
                break

            if not server_alive and browser_alive:
                if not server_stopped_first:
                    self._logger.warning(
                        "Dash server terminated while browser is still running; requesting browser close",
                    )
                    server_stopped_first = True
                self.request_browser_close()

            if not browser_alive and server_alive:
                if not browser_stopped_first:
                    self._logger.warning(
                        "Browser terminated while Dash server is still running; requesting server shutdown",
                    )
                    browser_stopped_first = True
                self._request_server_shutdown_from_main()

            time.sleep(0.1)

        self._join_thread(self._server_thread, "server", timeout=5)
        self._join_thread(self._browser_thread, "browser", timeout=5)

    def _request_server_shutdown_from_main(self) -> bool:
        """Request WSGI server shutdown from a non-server thread."""
        first_attempt = not self._server_shutdown_requested.is_set()
        self._server_shutdown_requested.set()

        if self._wsgi_server is None:
            if first_attempt:
                self._logger.warning("Cannot request server shutdown: WSGI server instance is not available")
            return False

        if first_attempt:
            self._logger.info("Requesting WSGI server shutdown")
        try:
            self._wsgi_server.shutdown()
            return True
        except Exception as exc:
            self._logger.error("Error calling wsgi_server.shutdown(): %s", exc)
            return False

    def _shutdown_server_and_wait(self, timeout: float) -> None:
        """Request server shutdown and keep retrying while waiting for thread exit."""
        if self._server_thread is None:
            return

        deadline = time.monotonic() + timeout
        while self._server_thread.is_alive() and time.monotonic() < deadline:
            self._request_server_shutdown_from_main()
            self._server_thread.join(timeout=0.1)

        if self._server_thread.is_alive():
            self._logger.warning("Server thread did not terminate after %.1f second(s)", timeout)

    def _cleanup_on_error(self) -> None:
        """Best-effort cleanup for unexpected runtime failures."""
        self._logger.warning("Attempting cleanup after error in run_forever()")

        if self._browser_thread and self._browser_thread.is_alive():
            self._logger.info("Requesting browser close due to error")
            self.request_browser_close()

        if self._server_thread and self._server_thread.is_alive():
            self._logger.info("Requesting server shutdown due to error")
            self._request_server_shutdown_from_main()

        self._join_thread(self._browser_thread, "browser", timeout=5)
        self._join_thread(self._server_thread, "server", timeout=5)

    def _notify_started(self) -> None:
        if self._listener is None:
            return

        try:
            self._listener.on_dash_app_started(self)
        except Exception as exc:
            self._logger.error("Error calling listener.on_dash_app_started: %s", exc)

    def _notify_stopped(self) -> None:
        if self._listener is None:
            return

        try:
            self._listener.on_dash_app_stopped(self, self.exit_code)
        except Exception as exc:
            self._logger.error("Error calling listener.on_dash_app_stopped: %s", exc)

    def _set_exit_code(self, exit_code: int) -> None:
        if exit_code == 0:
            return

        with self._exit_code_lock:
            if self._exit_code == 0:
                self._exit_code = exit_code

    def _join_thread(self, thread: threading.Thread | None, label: str, timeout: float) -> None:
        if thread is None:
            return

        thread.join(timeout=timeout)
        if thread.is_alive():
            self._logger.warning("%s thread did not terminate after %.1f second(s)", label, timeout)

    @staticmethod
    def _find_available_port() -> int:
        """Find an available localhost port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return int(sock.getsockname()[1])

    class _EmbeddedBrowser:
        def __init__(
            self,
            url: str,
            background_color: str = "#111111",
            title: str | None = None,
            x: int = 100,
            y: int = 100,
            width: int = 800,
            height: int = 600,
        ) -> None:
            self._url = url
            self._background_color = background_color
            self._title = title if title else "Browser Window"
            self._x = x
            self._y = y
            self._width = width
            self._height = height

            cls = type(self)
            self._logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")
            self._qt_logger = logging.getLogger("Qt")

            self._server_shutdown_callback: Callable[[], None] | None = None
            self._original_qt_message_handler: Any = qInstallMessageHandler(self._qt_message_handler)

            self._app: QApplication | None = None
            self._main_window: QMainWindow | None = None

        def run_forever(self) -> int:
            exit_code = 1
            try:
                existing_app = QApplication.instance()
                if existing_app is None:
                    app = QApplication([])
                elif isinstance(existing_app, QApplication):
                    app = existing_app
                else:
                    self._logger.error("Existing Qt application instance is not a QApplication")
                    return exit_code
                self._app = app
                self._build_main_window()
                # Blocks until the Qt event loop exits.
                exit_code = app.exec()
                self._logger.debug("Browser event loop terminated with exit code: %s", exit_code)
            except Exception as exc:
                self._logger.error("Error in browser event loop: %s", exc)
                self._logger.error(traceback.format_exc())
            finally:
                if self._original_qt_message_handler:
                    qInstallMessageHandler(self._original_qt_message_handler)
                    self._logger.debug("Restored original Qt message handler")
            return exit_code

        def set_server_shutdown_callback(self, callback: Callable[[], None]) -> None:
            """Set callback used to shut down the WSGI server from Qt close events."""
            self._server_shutdown_callback = callback

        def close_main_window(self) -> None:
            """Queue a window close request from a non-GUI thread."""
            self._logger.info("Received request to close browser window")
            if not self._app or not self._main_window:
                self._logger.warning("Cannot request close: browser app or main window is not available")
                return

            # QueuedConnection schedules the close call in the Qt GUI event loop.
            connection_type: Any = (
                Qt.ConnectionType.QueuedConnection
                if hasattr(Qt, "ConnectionType")
                else getattr(Qt, "QueuedConnection")
            )
            try:
                # PySide6 runtime expects str here on some builds, while stubs
                # still type this parameter as bytes-like.
                method_name = cast(Any, "close")
                request_successful = QMetaObject.invokeMethod(
                    self._main_window,
                    method_name,
                    connection_type,
                )
            except Exception:
                self._logger.warning("Failed to queue browser close request; posting close event", exc_info=True)
                close_event_type: Any = (
                    QEvent.Type.Close if hasattr(QEvent, "Type") else getattr(QEvent, "Close")
                )
                QCoreApplication.postEvent(self._main_window, QEvent(close_event_type))
                return

            if not request_successful:
                self._logger.warning("Failed to queue browser close request; posting close event")
                close_event_type = (
                    QEvent.Type.Close if hasattr(QEvent, "Type") else getattr(QEvent, "Close")
                )
                QCoreApplication.postEvent(self._main_window, QEvent(close_event_type))
            else:
                self._logger.debug("Queued browser close request")

        def _build_main_window(self) -> None:
            self._main_window = self._BrowserMainWindow(self)
            self._main_window.setWindowTitle(self._title)
            self._main_window.setGeometry(self._x, self._y, self._width, self._height)

            view = QWebEngineView()
            view.page().setBackgroundColor(QColor(self._background_color))
            view.setUrl(QUrl(self._url))

            self._main_window.setCentralWidget(view)
            self._main_window.show()

        def _qt_message_handler(
            self,
            message_type: QtMsgType,
            _context: QMessageLogContext,
            message: str,
        ) -> None:
            """Route Qt log messages into Python logging."""
            match message_type:
                case QtMsgType.QtDebugMsg:
                    level = logging.DEBUG
                case QtMsgType.QtInfoMsg:
                    level = logging.INFO
                case QtMsgType.QtWarningMsg:
                    level = logging.WARNING
                case QtMsgType.QtCriticalMsg:
                    level = logging.ERROR
                case QtMsgType.QtFatalMsg:
                    level = logging.CRITICAL
                case _:
                    level = logging.WARNING

            self._qt_logger.log(level, message)

        class _BrowserMainWindow(QMainWindow):
            """Main window wrapper that requests server shutdown on close."""

            def __init__(
                self,
                browser: "EmbeddedDashApplication._EmbeddedBrowser",
                *args: Any,
                **kwargs: Any,
            ) -> None:
                super().__init__(*args, **kwargs)

                cls = type(self)
                self._logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")
                self._browser = browser

            def closeEvent(self, event: QEvent) -> None:  # noqa: N802
                self._logger.debug("Close event triggered on browser window")

                if self._browser._server_shutdown_callback:
                    self._logger.info("Initiating server shutdown via callback")
                    try:
                        self._browser._server_shutdown_callback()
                    except Exception as exc:
                        self._logger.error("Error during server shutdown callback: %s", exc)
                else:
                    self._logger.warning("Server shutdown callback not set; cannot shut down server")

                event.accept()
                self._logger.debug("Accepted close event on browser window")
