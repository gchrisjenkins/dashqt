import logging
import socket
import threading
import time
import traceback
from abc import abstractmethod, ABC
from typing import Callable

import requests
import werkzeug
from PySide6.QtCore import (
    QUrl, QtMsgType, qInstallMessageHandler, QMessageLogContext, QCoreApplication, QEvent, QMetaObject, Qt
)
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow
from dash import Dash, Output, Input
from dash.development.base_component import Component
from flask import Flask
from plotly.graph_objs import Figure


class EmbeddedDashApplicationListener(ABC):
    """
    Abstract base class for listeners that react to lifecycle events
    from an EmbeddedDashApplication instance.
    """

    @abstractmethod
    def on_dash_app_started(self, app: 'EmbeddedDashApplication'):
        """
        Called by the EmbeddedDashApplication after its server and browser have successfully started.
        """
        pass

    @abstractmethod
    def on_dash_app_stopped(self, app: 'EmbeddedDashApplication', exit_code: int):
        """
        Called by the EmbeddedDashApplication just before its run_forever method returns.
        """
        pass


class EmbeddedDashApplication(ABC):

    def __init__(self, listener: EmbeddedDashApplicationListener | None = None, name: str | None = None):

        cls = type(self)
        self._logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")

        self.__listener: EmbeddedDashApplicationListener | None = listener
        self.__name: str | None = name

        self.__server: Dash | None = None
        self.__server_port: int | None = None
        self.__server_thread: threading.Thread | None = None
        self.__wsgi_server: werkzeug.serving.BaseWSGIServer | None = None
        self.__exit_code: int = 0

        server = Flask(type(self).__name__)
        self.__server = Dash(type(self).__name__, server=server)

        @server.route('/health')
        def health_check():
            return "OK", 200

        self.__browser: EmbeddedDashApplication._EmbeddedBrowser | None = None
        self.__browser_thread: threading.Thread | None = None

    def run_forever(self):

        self._logger.info(f"Starting {type(self).__name__}...")
        # Removed server_started/browser_started flags as requested
        started_successfully = False  # Use a single flag

        try:
            if not self._start_server():
                self._logger.error("The Dash server failed to start. Shutting down...")
                self.__exit_code = 1
                # Proceed to finally block for stop notification

            elif not self._start_browser():  # Only run if server started
                self._logger.error("The browser failed to start. Shutting down...")
                self._request_server_shutdown_from_main()
                if self.__server_thread:
                    self.__server_thread.join(timeout=5)
                self.__exit_code = 1
                # Proceed to finally block for stop notification
            else:
                # --- Both started successfully ---
                started_successfully = True
                self._logger.info("The Dash server and browser started successfully")
                # --- Call listener on successful start ---
                if self.__listener:
                    try:
                        self.__listener.on_dash_app_started(self)
                    except Exception as e:
                        self._logger.error(f"Error calling listener.on_app_started: {e}")

                # --- Main Wait Logic ---
                self._logger.info("Dash application is running and monitoring threads...")
                if self.__server_thread:
                    self.__server_thread.join()
                    if self.__exit_code != 0 and self.__browser_thread and self.__browser_thread.is_alive():
                        self._logger.warning(
                            "The Dash server terminated unexpectedly (with error), requesting a browser close"
                        )
                        self.request_browser_close()  # Use public method

                if self.__browser_thread:
                    self.__browser_thread.join(timeout=5)
                    if self.__browser_thread.is_alive():
                        self._logger.error("Browser thread did not terminate after join timeout!")

        except Exception as e:
            self._logger.error(f"An unexpected error occurred while running Dash application: {e}")
            self._logger.error(traceback.format_exc())
            self.__exit_code = 1  # Ensure exit code reflects error
            # Attempt cleanup only if startup was likely successful enough to warrant it
            if started_successfully:
                self._cleanup_on_error()

        finally:
            # --- Notify listener on stop, regardless of success/failure ---
            self._logger.info(f"{type(self).__name__} finishing with exit code: {self.__exit_code}")
            # --- Call listener on stop ---
            if self.__listener:
                try:
                    # Pass the final exit code
                    self.__listener.on_dash_app_stopped(self, self.__exit_code)
                except Exception as e:  # Catch potential errors in listener code
                    self._logger.error(f"Error calling listener.on_app_stopped: {e}")

            # Final thread status check
            if self.__server_thread and self.__server_thread.is_alive():
                self._logger.warning("Server thread still alive in final cleanup.")
            if self.__browser_thread and self.__browser_thread.is_alive():
                self._logger.warning("Browser thread still alive in final cleanup.")

    def request_browser_close(self):
        """
        Requests the embedded browser window to close gracefully.
        """
        self._logger.info("Received external request to close browser window.")
        if self.__browser:
            self.__browser.close_main_window()  # Delegate to EmbeddedBrowser instance
        else:
            self._logger.warning("Cannot request browser close: browser instance not available.")

    @property
    def exit_code(self):
        return self.__exit_code

    @abstractmethod
    def _build_layout(self) -> Component | list[Component]:
        """
        Return either a single Dash component (e.g. html.Div, dcc.Graph, …)
        or a list thereof.
        """

    @abstractmethod
    def _build_callbacks(self) -> list[tuple[Output | list[Output], Input | list[Input], Callable[..., Figure]]]:
        """
        Return a list of (outputs, inputs, callback_fn) triples.
        Each `outputs` can be either one Output or a list of Outputs;
        similarly `inputs` can be either one Input or a list of Inputs.
        """

    def _start_server(self) -> bool:

        try:
            self.__server.layout = self._build_layout()

            for outputs, inputs, func in self._build_callbacks():
                # note: `outputs` can be Output or list[Output]
                #       `inputs`  can be Input  or list[Input]
                self.__server.callback(outputs, inputs)(func)

            self.__server_port = self._find_available_port()
            self._logger.debug(f"Starting the Dash server on '127.0.0.1:{self.__server_port}'...")

            self.__server_thread = threading.Thread(
                target=self._run_server,
                name=f"{Dash.__name__}Thread",
                daemon=False
            )
            self.__server_thread.start()

            startup_time = time.time()
            startup_max_wait = 15  # seconds
            retry_interval = .25  # seconds
            while True:

                if time.time() - startup_time > startup_max_wait:
                    self._logger.error(f"Dash server health check timed out after {startup_max_wait} seconds")
                    # Attempt to stop a potentially hanging server thread
                    self._request_server_shutdown_from_main()
                    return False  # Indicate startup failure

                try:
                    response = requests.get(f"http://127.0.0.1:{self.__server_port}/health", timeout=1)
                    if response.status_code == 200:
                        self._logger.debug("The Dash server is ready")
                        return True  # Indicate successful startup
                except requests.exceptions.ConnectionError:
                    # Server not up yet, wait and retry
                    self._logger.warning(f"The Dash server is not ready, retrying again in {retry_interval} seconds...")
                    time.sleep(retry_interval)
                except requests.exceptions.RequestException as e:
                    self._logger.warning(
                        f"Health check request failed: {e}, retrying again in {retry_interval} seconds..."
                    )
                    time.sleep(retry_interval)

                # Check if the server thread died during startup
                if not self.__server_thread.is_alive():
                    self._logger.error("Dash server thread terminated unexpectedly during startup")
                    return False  # Indicate startup failure

        except Exception as e:
            self._logger.error(f"Failed to start Dash server: {e}")
            self._logger.error(traceback.format_exc())
            # Attempt shutdown if in a partially started state
            if self.__server_thread and self.__server_thread.is_alive():
                self._request_server_shutdown_from_main()
            return False  # Indicate startup failure

    def _run_server(self):

        try:
            self.__wsgi_server = werkzeug.serving.make_server(
                "127.0.0.1",
                self.__server_port,
                self.__server.server,
                threaded=True
            )
            self.__wsgi_server.serve_forever()

        except Exception as e:
            self._logger.error(f"Error occurred while running the Dash server: {e}")
            self._logger.error(traceback.format_exc())
            self.__exit_code = 1

        finally:
            self._logger.debug("The Dash server thread has terminated")

    def _start_browser(self) -> bool:

        try:
            self.__browser_thread = threading.Thread(
                target=self._run_browser,
                name=f"{EmbeddedDashApplication._EmbeddedBrowser.__name__}Thread",
                daemon=False
            )
            self.__browser_thread.start()
            return True  # Indicate successful startup

        except Exception as e:
            self._logger.error(f"Failed to start browser thread: {e}")
            self._logger.error(traceback.format_exc())
            return False  # Indicate startup failure

    def _run_browser(self):

        try:
            self.__browser = EmbeddedDashApplication._EmbeddedBrowser(
                url=f"http://127.0.0.1:{self.__server_port}", title=self.__name
            )

            if self.__wsgi_server:
                try:
                    # Set the server shutdown callback on the browser instance
                    self.__browser.set_server_shutdown_callback(self.__wsgi_server.shutdown)
                    exit_code = self.__browser.run_forever()

                    # Update main exit code if browser had an error, but prioritize server errors
                    if self.__exit_code == 0 and exit_code != 0:
                        self.__exit_code = exit_code

                except Exception as e:
                    self._logger.error(f"Error occurred while running the browser: {e}")
                    self._logger.error(traceback.format_exc())
                    self.__exit_code = 1

            else:
                self._logger.error("Can't set shutdown callback: WSGI server instance not available")
                self.__exit_code = 1

        except Exception as e:
            self._logger.error(f"Error occurred while starting the browser: {e}")
            self._logger.error(traceback.format_exc())
            self.__exit_code = 1

        self._logger.debug("The browser thread has terminated")

    def _request_server_shutdown_from_main(self):
        """
        Helper method to request server shutdown from main thread (e.g., on startup error).
        """
        if self.__wsgi_server:
            self._logger.info("Requesting WSGI server shutdown from main thread...")
            try:
                # Call shutdown on the server instance
                self.__wsgi_server.shutdown()
            except Exception as e:
                self._logger.error(f"Error calling wsgi_server.shutdown(): {e}")
        else:
            self._logger.warning("Cannot request server shutdown: WSGI server instance not available.")

    def _cleanup_on_error(self):
        """
        Helper method for cleanup on major error in run_forever() method.
        """
        self._logger.warning("Attempting cleanup after error in run_forever()...")
        # Request browser close if it's running
        if self.__browser_thread and self.__browser_thread.is_alive():
            self._logger.info("Requesting browser close due to error")
            self.request_browser_close()  # Use the public method
        # Request server shutdown if it's running
        if self.__server_thread and self.__server_thread.is_alive():
            self._logger.info("Requesting server shutdown due to error")
            self._request_server_shutdown_from_main()
        # Give threads a moment to potentially react
        time.sleep(0.5)

    @staticmethod
    def _find_available_port():
        """
        Find an available port on localhost.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    class _EmbeddedBrowser:

        _server_shutdown_callback: Callable[[], None] | None = None

        def __init__(self,
            url: str,
            background_color: str = "#111111",
            title: str = None,
            x: int = 100,
            y: int = 100,
            width: int = 800,
            height: int = 600
        ):
            super().__init__()

            self.__url: str = url
            self.__background_color: str = background_color
            self.__title: str = title if title else "Browser Window"
            self.__x: int = x
            self.__y: int = y
            self.__width: int = width
            self.__height: int = height

            cls = type(self)
            self.__logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")

            self.__original_qt_message_handler: object = qInstallMessageHandler(self._qt_message_handler)
            self.__qt_logger = logging.getLogger("Qt")

            self.__app: QApplication | None = None
            self.__main_window: QMainWindow | None = None

        def run_forever(self) -> int:

            exit_code = 1
            try:
                self.__app = QCoreApplication.instance() or QApplication([])
                self._build_main_window()
                exit_code = self.__app.exec()  # this thread blocks until event loop has terminated
                self.__logger.debug(f"The browser event loop has terminated with exit code: {exit_code}")
            except Exception as e:
                self.__logger.error(f"Error occurred in the browser event loop: {e}")
                self.__logger.error(traceback.format_exc())
            finally:
                if self.__original_qt_message_handler:
                    qInstallMessageHandler(self.__original_qt_message_handler)
                    self.__logger.debug("Restored original Qt message handler")
                return exit_code

        def set_server_shutdown_callback(self, callback: Callable[[], None]):
            """
            Sets the function to call to trigger a server shutdown.
            """
            self._server_shutdown_callback = callback

        def close_main_window(self):
            """
            Queue a request to close the browser window from another thread.
            """
            self.__logger.info("Received request to close browser window.")
            if self.__app and self.__main_window:
                # Use invokeMethod for thread-safe Qt calls from non-GUI threads
                # QueuedConnection ensures the request runs in the Qt event loop when allotted time
                # noinspection PyTypeChecker
                request_successful = QMetaObject.invokeMethod(
                    self.__main_window,
                    "close",  # Call the QWidget.close() method
                    Qt.QueuedConnection  # type: ignore
                )
                if not request_successful:
                    self.__logger.error("Failed to queue the close request to the browser event loop.")
                else:
                    self.__logger.debug("Successfully queued close request.")
            else:
                self.__logger.warning("Cannot request close: browser app or main window not available.")

        def _build_main_window(self):

            self.__main_window = self._BrowserMainWindow(self)
            self.__main_window.setWindowTitle(self.__title)
            self.__main_window.setGeometry(self.__x, self.__y, self.__width, self.__height)

            view = QWebEngineView()
            view.page().setBackgroundColor(QColor(self.__background_color))
            view.setUrl(QUrl(self.__url))

            self.__main_window.setCentralWidget(view)
            self.__main_window.show()

        def _qt_message_handler(self, type_: QtMsgType, context: QMessageLogContext, message: str) -> None:
            """
            Redirects Qt messages to Python's logging system.
            """

            # Map Qt message types to Python logging levels
            match type_:
                case QtMsgType.QtDebugMsg:
                    level = logging.DEBUG
                case QtMsgType.QtInfoMsg:
                    level = logging.INFO
                case QtMsgType.QtWarningMsg:
                    level = logging.WARNING
                case QtMsgType.QtCriticalMsg:
                    level = logging.ERROR
                case QtMsgType.QtFatalMsg:
                    level = logging.CRITICAL  # Fatal is critical in Python logging context
                case _:
                    level = logging.WARNING  # Default for unknown types

            self.__qt_logger.log(level, message)

        class _BrowserMainWindow(QMainWindow):
            """
            Internal MainWindow class to handle the close event.
            """

            def __init__(self, browser: 'EmbeddedDashApplication._EmbeddedBrowser', *args, **kwargs):
                super().__init__(*args, **kwargs)

                cls = type(self)
                self.__logger: logging.Logger = logging.getLogger(f"{cls.__module__}.{cls.__name__}")

                self._browser = browser

            def closeEvent(self, event: QEvent) -> None:
                """Override closeEvent to trigger server shutdown before closing."""
                self.__logger.debug("Close event triggered on browser window")

                # Check if the shutdown callback exists and call it
                if self._browser._server_shutdown_callback:
                    self.__logger.info("Initiating server shutdown via callback...")
                    try:
                        # Call the actual self.__wsgi_server.shutdown() method
                        self._browser._server_shutdown_callback()
                    except Exception as e:
                        # Log if calling the shutdown function fails
                        self.__logger.error(f"Error occurred during server shutdown callback: {e}")
                else:
                    # This shouldn't happen if setup is correct, but good to check
                    self.__logger.warning("Server shutdown callback not set, cannot shut down server.")

                # Accept the event to allow the window to close and Qt event loop to exit
                event.accept()
                self.__logger.debug("Close event on browser window accepted")
                # Note: Accepting the event will lead to QApplication.exec() returning in the run_forever() method
