"""
python manage.py seed_uttt

Idempotent: safe to run multiple times. Creates or updates the Demo Product
and the four seed test cases (TC001–TC004) used for example workflows.

After seeding, the product's external_api_base_url points to the mock service
at http://127.0.0.1:8001. Credentials are read from:
  PRODUCT_DEMO_API_KEY        — sent to the mock service as X-Api-Key
  PRODUCT_DEMO_CALLBACK_SECRET — expected in X-Callback-Api-Key on callbacks
"""
import os

from django.core.management.base import BaseCommand

from uttt.models import Product, RegisteredTestCase

PRODUCT_NAME = 'Demo Product'
PRODUCT_URL = 'http://127.0.0.1:8001'
CRED_ENV_KEY = 'PRODUCT_DEMO_API_KEY'
CALLBACK_SECRET_ENV_KEY = 'PRODUCT_DEMO_CALLBACK_SECRET'

SEED_TEST_CASES = [
    {
        'external_test_case_id': 'TC001',
        'name': 'Quick Pass Test',
        'description': 'Always passes quickly. Good for pre- or post-test baseline checks.',
    },
    {
        'external_test_case_id': 'TC002',
        'name': 'Delayed Pass Test',
        'description': 'Passes after a configurable delay. Demonstrates async execution.',
    },
    {
        'external_test_case_id': 'TC003',
        'name': 'Failing Test',
        'description': 'Always fails. Use in pre-tests to demo blocking behavior.',
    },
    {
        'external_test_case_id': 'TC004',
        'name': 'Timeout Test',
        'description': 'Never produces a terminal result. Demonstrates the timeout path.',
    },
]


class Command(BaseCommand):
    help = 'Seed UTTT platform with Demo Product and TC001–TC004 test cases'

    def handle(self, *args, **options):
        product, created = Product.objects.update_or_create(
            name=PRODUCT_NAME,
            defaults={
                'external_api_base_url': PRODUCT_URL,
                'credential_env_key': CRED_ENV_KEY,
                'callback_secret_env_key': CALLBACK_SECRET_ENV_KEY,
                'enabled': True,
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(f'{action} product: {product.name} (id={product.id})')

        for tc_data in SEED_TEST_CASES:
            tc, created = RegisteredTestCase.objects.update_or_create(
                product=product,
                external_test_case_id=tc_data['external_test_case_id'],
                defaults={
                    'name': tc_data['name'],
                    'description': tc_data['description'],
                    'enabled': True,
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f'  {action} test case: {tc.external_test_case_id} ({tc.name}) id={tc.id}')

        self.stdout.write('')
        self.stdout.write('Seed complete. Product and test case IDs above are needed for workflow creation.')
        self.stdout.write('')
        self.stdout.write('Ensure these env vars are set in .env:')
        self.stdout.write(f'  {CRED_ENV_KEY}=<api key sent to mock service>')
        self.stdout.write(f'  {CALLBACK_SECRET_ENV_KEY}=<secret expected from mock service>')

        if not os.environ.get(CRED_ENV_KEY):
            self.stdout.write(self.style.WARNING(
                f'WARNING: {CRED_ENV_KEY} is not set in the current environment.'
            ))
        if not os.environ.get(CALLBACK_SECRET_ENV_KEY):
            self.stdout.write(self.style.WARNING(
                f'WARNING: {CALLBACK_SECRET_ENV_KEY} is not set in the current environment.'
            ))
