"""Background loop that polls due email triggers while the API server runs."""

import asyncio
import logging
from typing import Optional

from app.services.trigger_service import TriggerService

logger = logging.getLogger(__name__)


class TriggerScheduler:
    """Every `tick_seconds`, polls enabled triggers whose own interval has elapsed.

    Gmail calls are blocking, so each tick runs in a worker thread. Polling only queues runs
    for approval; it never executes a workflow.
    """

    def __init__(self, service: TriggerService, tick_seconds: float = 15.0) -> None:
        self.service = service
        self.tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="workflowos-trigger-scheduler")
            logger.info("Email trigger scheduler started (tick=%ss)", self.tick_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.service.poll_due)
            except Exception:  # noqa: BLE001 - one bad tick must not stop future polling
                logger.exception("Email trigger poll tick failed")
            await asyncio.sleep(self.tick_seconds)
