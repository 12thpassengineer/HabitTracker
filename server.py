"""
AdatTracker Pro - Root Server Entrypoint
Forwards directly to backend/server.py
"""

import sys
import os
from pathlib import Path

# Add backend directory to python path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from config import HOST, PORT, IS_PRODUCTION
import uvicorn

if __name__ == "__main__":
    print(f"🚀 Starting AdatTracker Pro from root on http://{HOST}:{PORT}")
    uvicorn.run("server:app", host=HOST, port=PORT, reload=not IS_PRODUCTION, app_dir=str(BACKEND_DIR))
