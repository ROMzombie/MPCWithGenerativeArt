"""Tests package initialization.
Ensures that running tests never touches or mutates the local repository .env file.
"""

import os
import tempfile
import atexit

# Point ENV_FILE to a temporary file for the duration of tests
_test_env_file = tempfile.NamedTemporaryFile(suffix=".env", delete=False)
_test_env_path = _test_env_file.name
_test_env_file.close()

os.environ["ENV_FILE"] = _test_env_path

def _cleanup_test_env():
    if os.path.exists(_test_env_path):
        try:
            os.remove(_test_env_path)
        except OSError:
            pass

atexit.register(_cleanup_test_env)
