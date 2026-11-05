#!/usr/bin/env python3
import os
import sys
from pathlib import Path


def main() -> None:
    for parent in Path(__file__).resolve().parents:
        shared_package = parent / "packages" / "platform-backend"
        if shared_package.is_dir():
            sys.path.insert(0, str(shared_package))
            break
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mj_backend.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
