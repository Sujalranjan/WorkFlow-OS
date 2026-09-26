"""File system activity collector watching a designated directory."""

import os
import threading
from typing import Optional
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from desktop_agent.collectors.base import BaseCollector, EventCallback
from desktop_agent.models.event import ActivityEvent, ActivityEventType


class FileActivityHandler(FileSystemEventHandler):
    """Handles watchdog filesystem events and emits ActivityEvents."""

    def __init__(self, collector: "FileSystemCollector") -> None:
        super().__init__()
        self.collector = collector

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        file_path = event.src_path
        file_name = os.path.basename(file_path)

        # Skip temporary files often created during writing or download staging
        if file_name.endswith(".tmp") or file_name.startswith("~"):
            return

        activity_event = ActivityEvent(
            event_type=ActivityEventType.FILE_CREATED,
            application="File System",
            source=self.collector.source_name,
            metadata={
                "file_name": file_name,
                "file_path": file_path,
                "directory": self.collector.watch_directory,
                "collector": "FileSystemCollector",
            },
        )
        self.collector.emit(activity_event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src_name = os.path.basename(event.src_path)
        dest_name = os.path.basename(event.dest_path)

        # Detect download completion: when browser renames .crdownload / .tmp to final target file
        event_type = ActivityEventType.FILE_MOVED
        is_download_completed = False
        if src_name.endswith(".crdownload") or src_name.endswith(".tmp") or src_name.endswith(".part"):
            event_type = ActivityEventType.FILE_DOWNLOADED
            is_download_completed = True

        activity_event = ActivityEvent(
            event_type=event_type,
            application="File System",
            source=self.collector.source_name,
            metadata={
                "file_name": dest_name,
                "file_path": event.dest_path,
                "source_path": event.src_path,
                "directory": self.collector.watch_directory,
                "is_download_completed": is_download_completed,
                "collector": "FileSystemCollector",
            },
        )
        self.collector.emit(activity_event)


class FileSystemCollector(BaseCollector):
    """Watches a safe, designated directory for file creation and movement events."""

    def __init__(
        self,
        watch_directory: Optional[str] = None,
        callback: Optional[EventCallback] = None,
        source_name: str = "desktop_agent",
    ) -> None:
        super().__init__(callback=callback, source_name=source_name)
        # Default to a safe 'watch_folder' within the current working directory if not specified
        self.watch_directory = os.path.abspath(
            watch_directory
            or os.getenv("FILE_WATCH_DIRECTORY")
            or os.path.join(os.getcwd(), "watch_folder")
        )
        self._observer: Optional[Observer] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Ensure directory exists and start watchdog observer."""
        with self._lock:
            if self._is_running:
                return

            os.makedirs(self.watch_directory, exist_ok=True)
            self._observer = Observer()
            handler = FileActivityHandler(self)
            self._observer.schedule(handler, path=self.watch_directory, recursive=False)
            self._observer.start()
            self._is_running = True

    def stop(self) -> None:
        """Stop watchdog observer and wait for thread to terminate."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=2.0)
                self._observer = None
