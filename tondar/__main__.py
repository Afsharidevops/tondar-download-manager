import os
import sys
import tempfile

# the self-test must not touch the user's real settings/downloads: isolate it before
# anything reads the config folders
if any(a.startswith("--self-test") for a in sys.argv) and not os.environ.get("TONDAR_HOME"):
    os.environ["TONDAR_HOME"] = tempfile.mkdtemp(prefix="tondar-selftest-")

from tondar.app import main  # noqa: E402

sys.exit(main())
