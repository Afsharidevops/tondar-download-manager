"""Entry point of the Windows / macOS builds (PyInstaller)."""
import os
import sys
import tempfile

if any(a.startswith("--self-test") for a in sys.argv) and not os.environ.get("TONDAR_HOME"):
    os.environ["TONDAR_HOME"] = tempfile.mkdtemp(prefix="tondar-selftest-")

from tondar.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
