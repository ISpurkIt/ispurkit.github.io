"""Subprocess helpers."""

import subprocess
import sys

# A GUI build has no console: without this every child process (pip, dialogs) flashes its own console window
NO_WINDOW = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
