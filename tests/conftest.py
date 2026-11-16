import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="zadachi-test-")
os.environ["APP_PASSWORD"] = "secret123"
os.environ["ZADACHI_NO_BACKUP"] = "1"
os.environ["ZADACHI_TODAY"] = "2026-11-16"
