"""Windows Active Window Collector for observing focused application changes."""

import ctypes
import ctypes.wintypes
import platform
import threading
import time
from typing import Optional, Tuple
import psutil
from desktop_agent.collectors.base import BaseCollector, EventCallback
from desktop_agent.models.event import ActivityEvent, ActivityEventType


class WindowsWindowCollector(BaseCollector):
    """Monitors the active foreground window on Windows using non-invasive Win32 APIs.

    Detects when focus changes to a different window or application.
    Implements deduplication and configurable debounce so identical events
    are not continuously emitted while focus remains steady.
    """

    def __init__(
        self,
        callback: Optional[EventCallback] = None,
        source_name: str = "desktop_agent",
        poll_interval: float = 0.5,
        debounce_seconds: float = 0.3,
    ) -> None:
        super().__init__(callback=callback, source_name=source_name)
        self.poll_interval = poll_interval
        self.debounce_seconds = debounce_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_state: Optional[Tuple[str, str]] = None
        self._last_event_time: float = 0.0

        # Load Win32 user32 DLL if on Windows
        self._is_windows = platform.system() == "Windows"
        if self._is_windows:
            self._user32 = ctypes.windll.user32

    def get_foreground_window_info(self) -> Optional[Tuple[str, str]]:
        """Query the currently focused window title and process name.

        Returns:
            Tuple of (app_name, window_title) or None if no valid foreground window.
        """
        if not self._is_windows:
            return None

        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return None

            # Get Window Title
            length = self._user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buff, length + 1)
            window_title = buff.value.strip()

            # Get Process ID and Executable Name
            pid = ctypes.wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == 0:
                return None

            try:
                proc = psutil.Process(pid.value)
                app_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                app_name = "Unknown"

            # Clean application name (e.g. 'chrome.exe' -> 'Google Chrome')
            app_name = self.normalize_app_name(app_name)
            return app_name, window_title
        except Exception:
            return None

    @staticmethod
    def normalize_app_name(raw_name: str) -> str:
        """Map common executable names to friendly user-facing application names."""
        mapping = {
            "chrome.exe": "Google Chrome",
            "msedge.exe": "Microsoft Edge",
            "firefox.exe": "Mozilla Firefox",
            "code.exe": "Visual Studio Code",
            "explorer.exe": "File Explorer",
            "notepad.exe": "Notepad",
            "slack.exe": "Slack",
            "excel.exe": "Microsoft Excel",
            "cmd.exe": "Command Prompt",
            "powershell.exe": "PowerShell",
            "windowsterminal.exe": "Windows Terminal",
        }
        return mapping.get(raw_name.lower(), raw_name)

    def should_emit_event(self, app_name: str, window_title: str, now: float) -> bool:
        """Evaluate deduplication and debounce logic."""
        current_state = (app_name, window_title)
        if current_state == self._last_state:
            # Identical state, deduplicate
            return False

        if (now - self._last_event_time) < self.debounce_seconds:
            # Focus changed too rapidly, debounce
            return False

        return True

    def _poll_loop(self) -> None:
        """Background polling loop for active window detection."""
        while not self._stop_event.is_set():
            info = self.get_foreground_window_info()
            if info:
                app_name, window_title = info
                now = time.time()
                if self.should_emit_event(app_name, window_title, now):
                    self._last_state = (app_name, window_title)
                    self._last_event_time = now

                    event = ActivityEvent(
                        event_type=ActivityEventType.WINDOW_FOCUSED,
                        application=app_name,
                        source=self.source_name,
                        metadata={
                            "window_title": window_title,
                            "collector": "WindowsWindowCollector",
                            "detection_method": "Win32_GetForegroundWindow",
                        },
                    )
                    self.emit(event)

            self._stop_event.wait(self.poll_interval)

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="WindowsWindowCollectorThread",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background monitoring thread cleanly."""
        if not self._is_running:
            return
        self._is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
