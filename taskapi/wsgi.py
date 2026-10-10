"""
WSGI config for taskapi project.

It exposes the WSGI callable as a module-level variable named ``application``.
This is the entry point used by production WSGI servers (e.g. Gunicorn, uWSGI).
For this learning project we use Django's built-in development server instead.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taskapi.settings')
application = get_wsgi_application()
