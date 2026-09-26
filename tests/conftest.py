import sys
import os

# Ensure backend and desktop-agent are on sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
agent_dir = os.path.join(root_dir, "desktop-agent")

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)
