"""
WSGI config for logitrack project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'logitrack.settings')

application = get_wsgi_application()


def _bootstrap_demo():
    """In demo mode the database is a fresh file in /tmp on every cold start: build it once."""
    from django.conf import settings

    if not getattr(settings, "DEMO_MODE", False):
        return
    import fcntl

    from django.core.management import call_command

    lock_path = str(settings.DEMO_DB_PATH) + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = str(settings.DEMO_DB_PATH) + ".ready"
        if os.path.exists(ready):
            return
        call_command("migrate", interactive=False, verbosity=0)
        call_command("seed_demo")
        open(ready, "w").close()


_bootstrap_demo()
