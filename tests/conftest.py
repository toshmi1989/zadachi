import os
import tempfile

import fake_telegram

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="zadachi-test-")
os.environ["APP_PASSWORD"] = "secret123"
os.environ["ZADACHI_NO_BACKUP"] = "1"
os.environ["ZADACHI_NO_TELEGRAM"] = "1"   # the tests drive the poller and the scheduler by hand
os.environ["ZADACHI_TODAY"] = "2026-11-16"
os.environ["TELEGRAM_BOT_TOKEN"] = fake_telegram.TOKEN
os.environ["TELEGRAM_API"] = fake_telegram.start()
