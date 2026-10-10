"""
ASGI config for taskapi project.

It exposes the ASGI callable as a module-level variable named ``application``.
This is used by async-capable servers (e.g. Daphne, Uvicorn).
Not needed for this learning project but included for completeness.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taskapi.settings')
application = get_asgi_application()
