"""
Launcher for local development that makes the `app` package importable
regardless of current working directory and starts Uvicorn.

Usage:
    python start.py

This is helpful when `uvicorn app.main:app` fails with ModuleNotFoundError
because the Python path doesn't include the project folder containing `app`.
"""
import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path and 'app' is importable
ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / 'app'
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(APP_DIR))

import uvicorn

if __name__ == '__main__':
    uvicorn.run('app.main:app', host=os.getenv('HOST', '0.0.0.0'), port=int(os.getenv('PORT', 8000)), reload=True)
