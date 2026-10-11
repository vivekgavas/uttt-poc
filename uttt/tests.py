"""
UTTT Platform test suite.

Run with: python manage.py test uttt

Worker functions (create_pending_dispatches, dispatch_pending, etc.) are
called directly so tests do not need a running worker process.
requests.post is patched to avoid real HTTP calls.
"""
import os
import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    CallbackReceipt, Dispatch, DispatchStatus, ExecutionStatus,
    Product, RegisteredTestCase, TestExecution,
    WorkflowPhase, WorkflowRun, WorkflowStatus,
)
from .worker import (
    advance_workflows, create_pending_dispatches,
    dispatch_pending, handle_timeouts, recover_stale_dispatches,
)

PLATFORM_KEY = 'test-platform-key'
CALLBACK_KEY = 'test-callback-secret'
PRODUCT_API_KEY_ENV = 'TEST_PRODUCT_API_KEY'
PRODUCT_CALLBACK_ENV = 'TEST_PRODUCT_CALLBACK_SECRET'


def _auth_headers():
    return {'HTTP_X_PLATFORM_API_KEY': PLATFORM_KEY}


def _callback_headers():
    return {'HTTP_X_CALLBACK_API_KEY': CALLBACK_KEY}


@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class BaseUtttTest(TestCase):
    """Creates a product and four test cases shared by all test classes."""

    def setUp(self):
        os.environ[PRODUCT_API_KEY_ENV] = 'mock-api-key'
        os.environ[PRODUCT_CALLBACK_ENV] = CALLBACK_KEY

        self.product = Product.objects.create(
            name='Test Product',
            external_api_base_url='http://mock-service:8001',
            credential_env_key=PRODUCT_API_KEY_ENV,
            callback_secret_env_key=PRODUCT_CALLBACK_ENV,
            enabled=True,
        )
        self.tc001 = RegisteredTestCase.objects.create(
            product=self.product, external_test_case_id='TC001', name='Quick Pass'
        )
        self.tc002 = RegisteredTestCase.objects.create(
            product=self.product, external_test_case_id='TC002', name='Delayed Pass'
        )
        self.tc003 = RegisteredTestCase.objects.create(
            product=self.product, external_test_case_id='TC003', name='Failing Test'
        )
        self.tc004 = RegisteredTestCase.objects.create(
            product=self.product, external_test_case_id='TC004', name='Timeout Test'
        )

    def tearDown(self):
        os.environ.pop(PRODUCT_API_KEY_ENV, None)
        os.environ.pop(PRODUCT_CALLBACK_ENV, None)

    def _post_callback(self, dispatch, execution, status, result=None, event_id=None):
        """Helper: POST a callback event via the test client."""
        from rest_framework.test import APIClient
        client = APIClient()
        payload = {
            'event_id': str(event_id or uuid.uuid4()),
            'request_id': str(dispatch.id),
            'execution_id': str(execution.id),
            'status': status,
            'occurred_at': timezone.now().isoformat(),
        }
        if result is not None:
            payload['result'] = result
        return client.post(
            '/api/execution-events/',
            payload,
            format='json',
            **_callback_headers(),
        )

    def _make_accepted_dispatch(self, mock_post_return=None):
        """Helper: run worker steps to create and accept a dispatch."""
        if mock_post_return is None:
            mock_post_return = MagicMock(status_code=202)
        with patch('uttt.worker.http_client.post', return_value=mock_post_return):
            create_pending_dispatches()
            dispatch_pending()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@override_settings(PLATFORM_API_KEY=PLATFORM_KEY)
class ProductRegistrationTest(APITestCase):
    def test_create_product(self):
        response = self.client.post(
            '/api/products/',
            {
                'name': 'Widget Team',
                'external_api_base_url': 'http://widget:8001',
                'credential_env_key': 'WIDGET_KEY',
                'callback_secret_env_key': 'WIDGET_CB',
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('id', response.data)

    def test_create_product_requires_auth(self):
        response = self.client.post('/api/products/', {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_list_products(self):
        Product.objects.create(
            name='A', external_api_base_url='http://a',
            credential_env_key='AK', callback_secret_env_key='ACB',
        )
        response = self.client.get('/api/products/', **_auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)


@override_settings(PLATFORM_API_KEY=PLATFORM_KEY)
class TestCaseRegistrationTest(APITestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name='P1', external_api_base_url='http://p1',
            credential_env_key='P1K', callback_secret_env_key='P1CB',
        )

    def test_create_test_case(self):
        response = self.client.post(
            '/api/test-cases/',
            {'product': str(self.product.id), 'external_test_case_id': 'TC-X', 'name': 'Test X'},
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 201)

    def test_duplicate_external_id_rejected(self):
        RegisteredTestCase.objects.create(
            product=self.product, external_test_case_id='TC-DUP', name='Dup'
        )
        response = self.client.post(
            '/api/test-cases/',
            {'product': str(self.product.id), 'external_test_case_id': 'TC-DUP', 'name': 'Dup2'},
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_filter_by_product(self):
        other = Product.objects.create(
            name='P2', external_api_base_url='http://p2',
            credential_env_key='P2K', callback_secret_env_key='P2CB',
        )
        RegisteredTestCase.objects.create(product=self.product, external_test_case_id='T1', name='T1')
        RegisteredTestCase.objects.create(product=other, external_test_case_id='T1', name='T1-other')
        response = self.client.get(
            f'/api/test-cases/?product_id={self.product.id}',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)


# ---------------------------------------------------------------------------
# Workflow creation validation
# ---------------------------------------------------------------------------

@override_settings(PLATFORM_API_KEY=PLATFORM_KEY)
class WorkflowCreationValidationTest(BaseUtttTest, APITestCase):
    def test_disabled_product_rejected(self):
        self.product.enabled = False
        self.product.save()
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_test_case_rejected(self):
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(uuid.uuid4())],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_product_test_case_rejected(self):
        other_product = Product.objects.create(
            name='Other', external_api_base_url='http://other',
            credential_env_key='OTK', callback_secret_env_key='OTCB',
        )
        other_tc = RegisteredTestCase.objects.create(
            product=other_product, external_test_case_id='OTC', name='Other TC'
        )
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(other_tc.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_ids_in_phase_rejected(self):
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id), str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_empty_pre_tests_rejected(self):
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_workflow_returns_202(self):
        response = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn('workflow_id', response.data)
        self.assertIn('status_url', response.data)


# ---------------------------------------------------------------------------
# Successful workflow (full happy path)
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class SuccessfulWorkflowTest(BaseUtttTest, APITestCase):
    @patch('uttt.worker.http_client.post')
    def test_happy_path_pre_patch_post(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)

        # Create workflow
        resp = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        self.assertEqual(resp.status_code, 202)
        workflow_id = resp.data['workflow_id']

        # Worker dispatches PRE
        create_pending_dispatches()
        dispatch_pending()

        workflow = WorkflowRun.objects.get(id=workflow_id)
        self.assertEqual(workflow.status, WorkflowStatus.RUNNING_PRE)
        pre_dispatch = workflow.dispatches.get(phase=WorkflowPhase.PRE)
        self.assertEqual(pre_dispatch.status, DispatchStatus.ACCEPTED)
        pre_execution = workflow.executions.get(phase=WorkflowPhase.PRE)

        # Snapshot was captured at creation
        self.assertEqual(pre_execution.snapshot_external_test_case_id, 'TC001')
        self.assertEqual(pre_execution.snapshot_test_case_name, 'Quick Pass')

        # External service sends RUNNING then PASSED
        self._post_callback(pre_dispatch, pre_execution, 'RUNNING')
        pre_execution.refresh_from_db()
        self.assertEqual(pre_execution.status, ExecutionStatus.RUNNING)

        self._post_callback(
            pre_dispatch, pre_execution, 'PASSED',
            result={'message': 'OK', 'duration_ms': 450},
        )
        pre_execution.refresh_from_db()
        self.assertEqual(pre_execution.status, ExecutionStatus.PASSED)

        # Worker advances: RUNNING_PRE → PATCHING → RUNNING_POST + POST dispatch
        advance_workflows()
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.RUNNING_POST)
        self.assertIsNotNone(workflow.patch_started_at)
        self.assertIsNotNone(workflow.patch_completed_at)

        # Worker dispatches POST
        dispatch_pending()
        post_dispatch = workflow.dispatches.get(phase=WorkflowPhase.POST)
        self.assertEqual(post_dispatch.status, DispatchStatus.ACCEPTED)
        post_execution = workflow.executions.get(phase=WorkflowPhase.POST)

        self._post_callback(
            post_dispatch, post_execution, 'PASSED',
            result={'message': 'OK', 'duration_ms': 600},
        )

        advance_workflows()
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.PASSED)
        self.assertIsNotNone(workflow.completed_at)


# ---------------------------------------------------------------------------
# Pre-test failure blocks patching and post-tests
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class PreTestFailureTest(BaseUtttTest, APITestCase):
    @patch('uttt.worker.http_client.post')
    def test_pre_failure_skips_post(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)

        resp = self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc003.id)],
                'post_test_case_ids': [str(self.tc001.id)],
            },
            format='json',
            **_auth_headers(),
        )
        workflow_id = resp.data['workflow_id']

        create_pending_dispatches()
        dispatch_pending()

        workflow = WorkflowRun.objects.get(id=workflow_id)
        pre_dispatch = workflow.dispatches.get(phase=WorkflowPhase.PRE)
        pre_execution = workflow.executions.get(phase=WorkflowPhase.PRE)

        self._post_callback(pre_dispatch, pre_execution, 'FAILED',
                            result={'message': 'Assertion failed'})

        advance_workflows()
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.FAILED)
        self.assertIn('Pre-test failure', workflow.error_summary)
        self.assertIsNotNone(workflow.completed_at)

        # No patch timestamps
        self.assertIsNone(workflow.patch_started_at)
        self.assertIsNone(workflow.patch_completed_at)

        # POST execution was skipped
        post_execution = workflow.executions.get(phase=WorkflowPhase.POST)
        self.assertEqual(post_execution.status, ExecutionStatus.SKIPPED)


# ---------------------------------------------------------------------------
# Duplicate dispatch submission
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class DuplicateDispatchTest(BaseUtttTest, APITestCase):
    """Verify that an UNCERTAIN dispatch is retried with the same request_id."""

    @patch('uttt.worker.http_client.post')
    def test_retry_uses_same_request_id(self, mock_post):
        # First attempt fails with 503 → UNCERTAIN
        mock_post.return_value = MagicMock(status_code=503)

        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        create_pending_dispatches()
        dispatch_pending()

        dispatch = Dispatch.objects.get(phase=WorkflowPhase.PRE)
        first_request_id = dispatch.id
        self.assertEqual(dispatch.status, DispatchStatus.UNCERTAIN)
        self.assertEqual(dispatch.retry_count, 1)

        # Second attempt succeeds → ACCEPTED, same dispatch ID
        mock_post.return_value = MagicMock(status_code=202)
        dispatch_pending()

        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, DispatchStatus.ACCEPTED)
        self.assertEqual(dispatch.id, first_request_id)  # Same UUID


# ---------------------------------------------------------------------------
# Callback idempotency and out-of-order events
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class CallbackIdempotencyTest(BaseUtttTest, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        workflow = WorkflowRun.objects.latest('created_at')
        with patch('uttt.worker.http_client.post', return_value=MagicMock(status_code=202)):
            create_pending_dispatches()
            dispatch_pending()
        self.workflow = WorkflowRun.objects.get(id=workflow.id)
        self.dispatch = self.workflow.dispatches.get(phase=WorkflowPhase.PRE)
        self.execution = self.workflow.executions.get(phase=WorkflowPhase.PRE)

    def test_duplicate_event_id_is_idempotent(self):
        event_id = uuid.uuid4()
        r1 = self._post_callback(self.dispatch, self.execution, 'RUNNING', event_id=event_id)
        r2 = self._post_callback(self.dispatch, self.execution, 'RUNNING', event_id=event_id)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['status'], 'already_received')
        # Execution updated only once
        self.assertEqual(
            CallbackReceipt.objects.filter(event_id=event_id).count(), 1
        )

    def test_running_after_passed_is_ignored(self):
        # Send PASSED first
        passed_id = uuid.uuid4()
        self._post_callback(
            self.dispatch, self.execution, 'PASSED',
            result={'message': 'OK', 'duration_ms': 100},
            event_id=passed_id,
        )
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.PASSED)

        # Send RUNNING afterwards (out of order)
        running_id = uuid.uuid4()
        r = self._post_callback(self.dispatch, self.execution, 'RUNNING', event_id=running_id)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'received_not_applied')

        # Status must not have reverted
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.PASSED)


# ---------------------------------------------------------------------------
# Callback authentication
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class CallbackAuthTest(BaseUtttTest, APITestCase):
    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient
        self.api_client = APIClient()
        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        workflow = WorkflowRun.objects.latest('created_at')
        with patch('uttt.worker.http_client.post', return_value=MagicMock(status_code=202)):
            create_pending_dispatches()
            dispatch_pending()
        self.dispatch = workflow.dispatches.get(phase=WorkflowPhase.PRE)
        self.execution = workflow.executions.get(phase=WorkflowPhase.PRE)

    def test_wrong_callback_key_returns_401(self):
        r = self.api_client.post(
            '/api/execution-events/',
            {
                'event_id': str(uuid.uuid4()),
                'request_id': str(self.dispatch.id),
                'execution_id': str(self.execution.id),
                'status': 'RUNNING',
                'occurred_at': timezone.now().isoformat(),
            },
            format='json',
            HTTP_X_CALLBACK_API_KEY='wrong-key',
        )
        self.assertEqual(r.status_code, 401)

    def test_unknown_request_id_returns_404(self):
        r = self.api_client.post(
            '/api/execution-events/',
            {
                'event_id': str(uuid.uuid4()),
                'request_id': str(uuid.uuid4()),  # non-existent
                'execution_id': str(self.execution.id),
                'status': 'RUNNING',
                'occurred_at': timezone.now().isoformat(),
            },
            format='json',
            **_callback_headers(),
        )
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# Timeout and late results
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=1,   # 1 second for test speed
    UTTT_BASE_URL='http://testserver',
)
class TimeoutTest(BaseUtttTest, APITestCase):
    @patch('uttt.worker.http_client.post')
    def test_execution_timed_out_after_deadline(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)

        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        create_pending_dispatches()
        dispatch_pending()

        workflow = WorkflowRun.objects.latest('created_at')
        pre_dispatch = workflow.dispatches.get(phase=WorkflowPhase.PRE)

        # Back-date the accepted_at timestamp past the timeout window
        from datetime import timedelta
        Dispatch.objects.filter(id=pre_dispatch.id).update(
            accepted_at=timezone.now() - timedelta(seconds=10)
        )

        handle_timeouts()

        execution = workflow.executions.get(phase=WorkflowPhase.PRE)
        execution.refresh_from_db()
        self.assertEqual(execution.status, ExecutionStatus.TIMED_OUT)

    @patch('uttt.worker.http_client.post')
    def test_late_result_stored_but_not_applied(self, mock_post):
        """A callback arriving after TIMED_OUT is stored but does not reopen the workflow."""
        mock_post.return_value = MagicMock(status_code=202)

        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        create_pending_dispatches()
        dispatch_pending()

        workflow = WorkflowRun.objects.latest('created_at')
        pre_dispatch = workflow.dispatches.get(phase=WorkflowPhase.PRE)
        execution = workflow.executions.get(phase=WorkflowPhase.PRE)

        from datetime import timedelta
        Dispatch.objects.filter(id=pre_dispatch.id).update(
            accepted_at=timezone.now() - timedelta(seconds=10)
        )
        handle_timeouts()
        advance_workflows()  # RUNNING_PRE → FAILED (timed-out = not PASSED)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.FAILED)

        # Late PASSED callback arrives
        late_event_id = uuid.uuid4()
        r = self._post_callback(
            pre_dispatch, execution, 'PASSED',
            result={'message': 'Late result'}, event_id=late_event_id,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'received_not_applied')

        # Workflow must not have reopened
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.FAILED)

        # Late receipt is stored for inspection
        receipt = CallbackReceipt.objects.get(event_id=late_event_id)
        self.assertFalse(receipt.processed)
        self.assertIn('terminal', receipt.processing_error)


# ---------------------------------------------------------------------------
# Worker restart recovery
# ---------------------------------------------------------------------------

@override_settings(
    PLATFORM_API_KEY=PLATFORM_KEY,
    WORKER_MAX_DISPATCH_RETRIES=3,
    WORKER_HTTP_TIMEOUT_SECONDS=5,
    WORKER_STALE_DISPATCH_SECONDS=120,
    EXECUTION_TIMEOUT_SECONDS=300,
    UTTT_BASE_URL='http://testserver',
)
class WorkerRestartRecoveryTest(BaseUtttTest, TestCase):
    def test_stale_sending_dispatch_is_recovered(self):
        """A SENDING dispatch with a stale last_attempt_at is reset to UNCERTAIN."""
        from datetime import timedelta
        self.client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )

        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        workflow_id = resp.data['workflow_id']

        with patch('uttt.worker.http_client.post', return_value=MagicMock(status_code=202)):
            create_pending_dispatches()

        # Simulate a crash: set dispatch to SENDING with stale timestamp
        Dispatch.objects.filter(workflow_id=workflow_id, phase=WorkflowPhase.PRE).update(
            status=DispatchStatus.SENDING,
            last_attempt_at=timezone.now() - timedelta(seconds=300),
        )

        recover_stale_dispatches()

        dispatch = Dispatch.objects.get(workflow_id=workflow_id, phase=WorkflowPhase.PRE)
        self.assertEqual(dispatch.status, DispatchStatus.UNCERTAIN)

    def test_pending_workflow_picked_up_after_restart(self):
        """Worker picks up a PENDING workflow on its first cycle after restart."""
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post(
            '/api/workflows/create/',
            {
                'product_id': str(self.product.id),
                'pre_test_case_ids': [str(self.tc001.id)],
                'post_test_case_ids': [str(self.tc002.id)],
            },
            format='json',
            **_auth_headers(),
        )
        workflow_id = resp.data['workflow_id']

        workflow = WorkflowRun.objects.get(id=workflow_id)
        self.assertEqual(workflow.status, WorkflowStatus.PENDING)

        with patch('uttt.worker.http_client.post', return_value=MagicMock(status_code=202)):
            create_pending_dispatches()
            dispatch_pending()

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowStatus.RUNNING_PRE)
