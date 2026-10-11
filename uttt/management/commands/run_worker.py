"""
python manage.py run_worker [--once]

Runs the UTTT workflow worker. In normal operation it loops indefinitely,
sleeping WORKER_POLL_INTERVAL_SECONDS between cycles. Pass --once to run
a single cycle and exit (useful for testing and cron-based operation).

The worker drives all workflow state transitions. It must be running for
workflows to progress beyond PENDING. It is safe to restart at any time —
stale SENDING dispatches are recovered automatically at the start of each cycle.
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from uttt.worker import run_cycle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the UTTT workflow worker'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run one cycle and exit instead of looping',
        )

    def handle(self, *args, **options):
        once = options['once']
        interval = settings.WORKER_POLL_INTERVAL_SECONDS

        self.stdout.write('UTTT worker starting.')
        if once:
            self.stdout.write('Running one cycle (--once).')

        while True:
            try:
                run_cycle()
            except Exception:
                logger.exception("Unhandled exception in worker cycle")

            if once:
                break

            # Close idle DB connection to avoid holding connections during sleep
            connection.close()
            time.sleep(interval)

        self.stdout.write('UTTT worker stopped.')
