"""Collectors package for desktop activity observation."""

from desktop_agent.collectors.base import BaseCollector, EventCallback
from desktop_agent.collectors.file_collector import FileSystemCollector
from desktop_agent.collectors.test_collector import ActivityCollector, TestActivityCollector
from desktop_agent.collectors.window_collector import WindowsWindowCollector

__all__ = [
    "BaseCollector",
    "EventCallback",
    "TestActivityCollector",
    "ActivityCollector",
    "WindowsWindowCollector",
    "FileSystemCollector",
]
