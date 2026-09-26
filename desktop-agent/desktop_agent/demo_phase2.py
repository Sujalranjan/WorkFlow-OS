"""Phase 2 Live Demonstration Script.

Demonstrates:
1. Real Windows Window Collector observing active foreground application changes with deduplication.
2. Real File System Collector observing file creation and completion in watch_folder.
3. Queueing in EventQueue and auto-dispatching to Backend POST /api/events.
"""

import os
import shutil
import sys
import time
from desktop_agent.agent import DesktopAgent


def run_phase2_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    watch_folder = os.path.abspath("watch_folder")
    os.makedirs(watch_folder, exist_ok=True)

    print("==========================================================")
    print("       WorkFlowOS Phase 2: Live Activity Collectors       ")
    print("==========================================================")
    print(f"Backend Target URL   : {backend_url}")
    print(f"Watch Directory      : {watch_folder}")
    print("Real Collectors      : WindowsWindowCollector + FileSystemCollector")
    print("Privacy Boundary     : Active title/metadata ONLY (No keylogging/CV)")
    print("==========================================================\n")

    # Initialize DesktopAgent with real OS collectors enabled and auto-dispatch active
    agent = DesktopAgent(
        backend_url=backend_url,
        enable_real_collection=True,
        poll_interval=0.5,
        debounce_seconds=0.3,
        watch_directory=watch_folder,
        auto_dispatch=True,
    )

    status = agent.start()
    print(f"[{agent.name}] Status: {status['status']} (Real collection: {status['real_collection']})")
    print("Active collectors:")
    for col in agent.collectors:
        print(f" - {col.__class__.__name__} (running={col.is_running})")

    print("\n--- Performing Real System Actions ---")
    time.sleep(1.0)

    # 1. Simulate a file download into watch_folder: staged .crdownload -> final .pdf
    print("\n[Action 1] Creating staged download file in watch folder: customer_order_101.pdf.crdownload...")
    staged_file = os.path.join(watch_folder, "customer_order_101.pdf.crdownload")
    with open(staged_file, "w") as f:
        f.write("WorkFlowOS Customer Order Document")
    time.sleep(1.0)

    print("[Action 2] Simulating download completion (rename to customer_order_101.pdf)...")
    final_file = os.path.join(watch_folder, "customer_order_101.pdf")
    if os.path.exists(final_file):
        os.remove(final_file)
    shutil.move(staged_file, final_file)
    time.sleep(1.5)

    print("\n[Action 3] Observing current desktop window focus state...")
    current_focus = agent.window_collector.get_foreground_window_info() if agent.window_collector else None
    if current_focus:
        print(f"Detected Foreground Window -> App: {current_focus[0]}, Title: '{current_focus[1]}'")
    else:
        print("Note: Foreground window inspection active.")

    time.sleep(1.5)
    print(f"\nCurrent agent queue depth: {agent.queue.size()}")
    print("Events auto-dispatched to backend.")

    print("\nCleaning up demo file...")
    try:
        if os.path.exists(final_file):
            os.remove(final_file)
    except OSError:
        pass

    agent.stop()
    print(f"[{agent.name}] Stopped cleanly. Collectors terminated.\n")
    print("Phase 2 demonstration complete. View the frontend to inspect the live events.")


if __name__ == "__main__":
    run_phase2_demo()
