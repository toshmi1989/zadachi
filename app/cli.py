"""Maintenance, inside the container:

    docker exec zadachi python -m app.cli init                  # create/upgrade the database (the image does this before start)
    docker exec zadachi python -m app.cli import /data/file.xlsx  # load an Excel export without the browser
    docker exec zadachi python -m app.cli password LOGIN         # issue a new password for a user (printed once)
    docker exec zadachi python -m app.cli backup                 # a consistent copy of the database now
    docker exec zadachi python -m app.cli verify                 # check the newest backup
"""
import sys

from . import auth, backup, importer
from .db import audit, connect, init_db, tx


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    init_db()
    if cmd == "init":
        print("database ready")
        return 0
    if cmd == "import" and len(argv) == 2:
        rows, warnings = importer.read(open(argv[1], "rb").read())
        with tx() as c:
            s = importer.apply(c, rows, warnings, argv[1].split("/")[-1], None, False)
        print({k: v for k, v in s.items() if k != "warnings"}, f"warnings: {len(s['warnings'])}")
        return 0
    if cmd == "password" and len(argv) == 2:
        password = auth.generate_password()
        with tx() as c:
            n = c.execute("UPDATE users SET password_hash=?, pw_set=1 WHERE login=?", (auth.hash_password(password), argv[1])).rowcount
            c.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE login=?)", (argv[1],))
            audit(c, "password.reset_cli", "user", None, {"login": argv[1]})
        print(f"new password for {argv[1]}: {password}" if n else "no such user")
        return 0 if n else 1
    if cmd == "backup":
        print(backup.make_now())
        return 0
    if cmd == "verify":
        r = backup.verify_latest()
        print(r)
        return 0 if r["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
