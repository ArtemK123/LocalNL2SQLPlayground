"""Django playground API (premsql launch api) bound to 0.0.0.0 for Docker."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django
import premsql


def main() -> None:
    host = os.environ.get("PREMSQL_PLAYGROUND_API_HOST", "0.0.0.0")
    port = os.environ.get("PREMSQL_PLAYGROUND_API_PORT", "8000")
    premsql_root = Path(premsql.__file__).resolve().parent
    backend_dir = premsql_root / "playground" / "backend"
    sys.path.insert(0, str(backend_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    os.chdir(backend_dir)

    django.setup()
    from django.conf import settings

    settings.ALLOWED_HOSTS = ["*"]

    from django.core.management import call_command, execute_from_command_line

    call_command("makemigrations", interactive=False, verbosity=0)
    call_command("migrate", interactive=False, verbosity=1)
    # --noreload: autoreload cannot resolve start_playground_api.py inside Docker.
    call_command("runserver", f"{host}:{port}", use_reloader=False)


if __name__ == "__main__":
    main()
