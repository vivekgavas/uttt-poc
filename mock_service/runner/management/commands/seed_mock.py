"""
Management command: seed_mock

Creates the four MockTestDefinition records (TC001–TC004) used by all demo scenarios.
Safe to run multiple times — uses update_or_create.

Behaviors:
    TC001 — pass,    fast  (~1.5 s total)
    TC002 — pass,    slow  (start + TC002_DELAY_SECONDS from settings)
    TC003 — fail,    fast  (~1.5 s total)
    TC004 — timeout, never sends a terminal result

Usage:
    python mock_service/manage.py seed_mock
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from runner.models import MockTestDefinition


class Command(BaseCommand):
    help = 'Seed TC001–TC004 test case definitions in the mock service'

    def handle(self, *args, **options):
        definitions = [
            {
                'external_id': 'TC001',
                'name': 'Fast passing test',
                'behavior': 'pass',
                'start_delay_seconds': 0.5,
                'complete_delay_seconds': 1.0,
                'result_message': 'TC001 passed.',
            },
            {
                'external_id': 'TC002',
                'name': 'Slow passing test',
                'behavior': 'pass',
                'start_delay_seconds': 0.5,
                'complete_delay_seconds': settings.TC002_DELAY_SECONDS,
                'result_message': 'TC002 passed.',
            },
            {
                'external_id': 'TC003',
                'name': 'Failing test',
                'behavior': 'fail',
                'start_delay_seconds': 0.5,
                'complete_delay_seconds': 1.0,
                'result_message': 'TC003 failed: assertion error.',
            },
            {
                'external_id': 'TC004',
                'name': 'Timeout test (never completes)',
                'behavior': 'timeout',
                'start_delay_seconds': 0.5,
                'complete_delay_seconds': None,
                'result_message': '',
            },
        ]

        for d in definitions:
            ext_id = d.pop('external_id')
            name = d.pop('name')
            obj, created = MockTestDefinition.objects.update_or_create(
                external_id=ext_id,
                defaults={'name': name, **d},
            )
            verb = 'Created' if created else 'Updated'
            self.stdout.write(f'  {verb} {ext_id}: {obj.behavior} ({name})')

        self.stdout.write(self.style.SUCCESS('seed_mock complete.'))
