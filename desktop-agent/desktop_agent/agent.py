"""WorkFlowOS Desktop Activity Agent entry point and lifecycle manager."""

import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from desktop_agent.client import BackendClient
from desktop_agent.collectors.base import BaseCollector
from desktop_agent.collectors.file_collector import FileSystemCollector
from desktop_agent.collectors.test_collector import ActivityCollector
from desktop_agent.collectors.window_collector import WindowsWindowCollector
from desktop_agent.event_queue import EventQueue
from desktop_agent.models.event import ActivityEvent


class DesktopAgent:
    """Desktop Activity Agent managing collection, queuing, and dispatching."""

    def __init__(
        self,
        name: str = "WorkFlowOS-Desktop-Agent",
        version: str = "0.2.0",
        backend_url: Optional[str] = None,
        enable_real_collection: Optional[bool] = None,
        poll_interval: Optional[float] = None,
        debounce_seconds: Optional[float] = None,
        watch_directory: Optional[str] = None,
        auto_dispatch: bool = False,
    ) -> None:
        self.name = name
        self.version = version
        self.is_running = False
        self.queue = EventQueue()
        self.client = BackendClient(backend_url=backend_url)

        # Retain deterministic test collector for testing and manual event creation
        self.collector = ActivityCollector(callback=self.record_activity, source_name=self.name)

        # Configuration for real OS collectors
        if enable_real_collection is None:
            enable_real_collection = os.getenv("ENABLE_REAL_COLLECTION", "false").lower() in ("true", "1", "yes")
        self.enable_real_collection = enable_real_collection

        self.poll_interval = float(poll_interval or os.getenv("WINDOW_POLL_INTERVAL", "0.5"))
        self.debounce_seconds = float(debounce_seconds or os.getenv("WINDOW_DEBOUNCE_SECONDS", "0.3"))
        self.watch_directory = watch_directory or os.getenv("FILE_WATCH_DIRECTORY")

        # Registered active collectors list
        self.collectors: List[BaseCollector] = [self.collector]

        if self.enable_real_collection:
            self.window_collector = WindowsWindowCollector(
                callback=self.record_activity,
                source_name=self.name,
                poll_interval=self.poll_interval,
                debounce_seconds=self.debounce_seconds,
            )
            self.file_collector = FileSystemCollector(
                watch_directory=self.watch_directory,
                callback=self.record_activity,
                source_name=self.name,
            )
            self.collectors.extend([self.window_collector, self.file_collector])
        else:
            self.window_collector = None
            self.file_collector = None

        # Auto-dispatching background worker
        self.auto_dispatch = auto_dispatch
        self._dispatch_thread: Optional[threading.Thread] = None
        self._stop_dispatch = threading.Event()

    def add_collector(self, collector: BaseCollector) -> None:
        """Register an additional collector conforming to BaseCollector."""
        collector.set_callback(self.record_activity)
        self.collectors.append(collector)
        if self.is_running and not collector.is_running:
            collector.start()

    def record_activity(self, event: ActivityEvent) -> None:
        """Place an activity event into the local queue."""
        self.queue.enqueue(event)

    def dispatch_next(self) -> Optional[Dict[str, Any]]:
        """Pop the oldest event from the queue and send it to the backend."""
        event = self.queue.dequeue()
        if not event:
            return None
        return self.client.send_event(event)

    def dispatch_all(self) -> List[Dict[str, Any]]:
        """Dispatch all queued events to the backend."""
        results = []
        while not self.queue.is_empty():
            res = self.dispatch_next()
            if res:
                results.append(res)
        return results

    def _auto_dispatch_worker(self) -> None:
        """Background thread dispatching queued events periodically."""
        while not self._stop_dispatch.is_set():
            while not self.queue.is_empty():
                try:
                    self.dispatch_next()
                except Exception as err:
                    print(f"[{self.name}] Error during auto dispatch: {err}", file=sys.stderr)
                    break
            self._stop_dispatch.wait(0.5)

    def start(self) -> dict[str, str]:
        """Start the desktop activity agent and active collectors."""
        self.is_running = True
        for collector in self.collectors:
            collector.start()

        if self.auto_dispatch:
            self._stop_dispatch.clear()
            self._dispatch_thread = threading.Thread(
                target=self._auto_dispatch_worker,
                name="AutoDispatchWorker",
                daemon=True,
            )
            self._dispatch_thread.start()

        return {
            "status": "started",
            "name": self.name,
            "version": self.version,
            "real_collection": "enabled" if self.enable_real_collection else "disabled",
        }

    def stop(self) -> dict[str, str]:
        """Stop the desktop activity agent and all collectors cleanly."""
        self.is_running = False
        if self.auto_dispatch:
            self._stop_dispatch.set()
            if self._dispatch_thread and self._dispatch_thread.is_alive():
                self._dispatch_thread.join(timeout=2.0)
            self._dispatch_thread = None

        for collector in self.collectors:
            collector.stop()

        return {
            "status": "stopped",
            "name": self.name,
        }


def main() -> int:
    """CLI entry point for running the desktop agent."""
    agent = DesktopAgent(enable_real_collection=True, auto_dispatch=True)
    status = agent.start()
    print(f"[{status['name']} v{status['version']}] Status: {status['status']} (Real collection: {status['real_collection']})")
    print("Agent running with Windows active window & filesystem collectors. Press Ctrl+C to terminate.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Desktop Agent...")
        agent.stop()
        print("Desktop Agent stopped cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
