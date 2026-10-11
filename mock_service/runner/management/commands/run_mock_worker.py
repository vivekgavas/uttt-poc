"""
Management command: run_mock_worker

Runs the mock service worker loop, which:
  1. Transitions QUEUED executions to RUNNING when their start time arrives.
  2. Transitions RUNNING executions to DONE when their complete time arrives.
  3. Delivers pending callbacks to the UTTT platform.

Usage:
    python mock_service/manage.py run_mock_worker
    python mock_service/manage.py run_mock_worker --once   # single cycle then exit
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from runner.worker import run_mock_cycle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the mock service worker loop'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run exactly one cycle then exit (useful for tests)',
        )

    def handle(self, *args, **options):
        poll = settings.MOCK_WORKER_POLL_INTERVAL_SECONDS
        self.stdout.write(self.style.SUCCESS('Mock worker started.'))
        self.stdout.write(
            f'  Poll interval: {poll}s | Max callback retries: {settings.CALLBACK_MAX_RETRIES}'
        )
        while True:
            try:
                run_mock_cycle()
            except Exception as exc:
                logger.exception("Error in mock worker cycle: %s", exc)
                self.stderr.write(f'Worker cycle error: {exc}')

            if options['once']:
                break

            # Close the DB connection before sleeping so Django reopens a fresh one.
            connection.close()
            time.sleep(poll)

        self.stdout.write('Mock worker stopped.')
