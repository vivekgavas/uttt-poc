#!/usr/bin/env python
"""
Mock external team service — manage.py.

Run from the repo root:
    python mock_service/manage.py runserver 0.0.0.0:8001
    python mock_service/manage.py migrate
    python mock_service/manage.py seed_mock
    python mock_service/manage.py run_mock_worker

sys.path is patched so the 'config' package inside mock_service/ is importable
whether this script is run from the repo root or from within mock_service/.
"""
import os
import sys


def main():
    # Ensure mock_service/ is on sys.path so 'config.settings' is importable
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Make sure the virtual environment is activated."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
