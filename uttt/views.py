"""
UTTT Platform API views.

Platform management endpoints require X-Platform-Api-Key.
The callback endpoint (POST /api/execution-events/) authenticates inline
using a per-product key bound to the specific dispatch being reported.
"""
import logging

from decouple import config as env
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import PlatformApiKeyAuthentication
from .models import (
    CallbackReceipt, Dispatch, ExecutionStatus,
    Product, RegisteredTestCase, TERMINAL_STATUSES,
    TestExecution, WorkflowPhase, WorkflowRun, WorkflowStatus,
)
from .serializers import (
    CallbackEventSerializer, CreateWorkflowSerializer,
    ProductSerializer, RegisteredTestCaseSerializer,
    TestExecutionSerializer, WorkflowRunSerializer,
)

logger = logging.getLogger(__name__)

_PLATFORM_AUTH = [PlatformApiKeyAuthentication]
_PLATFORM_PERM = [IsAuthenticated]


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductListCreateView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def get(self, request):
        qs = Product.objects.all().order_by('name')
        return Response(ProductSerializer(qs, many=True).data)

    def post(self, request):
        serializer = ProductSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestCaseListCreateView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def get(self, request):
        qs = RegisteredTestCase.objects.select_related('product').order_by('created_at')
        product_id = request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return Response(RegisteredTestCaseSerializer(qs, many=True).data)

    def post(self, request):
        serializer = RegisteredTestCaseSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TestCaseDetailView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def _get_object(self, pk):
        try:
            return RegisteredTestCase.objects.get(pk=pk)
        except RegisteredTestCase.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get_object(pk)
        if not obj:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(RegisteredTestCaseSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._get_object(pk)
        if not obj:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = RegisteredTestCaseSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

class WorkflowCreateView(APIView):
    """
    POST /api/workflows/
    Creates a workflow and its execution records, then returns 202 immediately.
    The worker picks up PENDING workflows and drives the state machine.
    """
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def post(self, request):
        serializer = CreateWorkflowSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        product = data['product']

        with transaction.atomic():
            workflow = WorkflowRun.objects.create(
                product=product,
                status=WorkflowStatus.PENDING,
            )
            for tc in data['pre_test_cases']:
                TestExecution.objects.create(
                    workflow=workflow,
                    phase=WorkflowPhase.PRE,
                    registered_test_case=tc,
                    snapshot_external_test_case_id=tc.external_test_case_id,
                    snapshot_test_case_name=tc.name,
                )
            for tc in data['post_test_cases']:
                TestExecution.objects.create(
                    workflow=workflow,
                    phase=WorkflowPhase.POST,
                    registered_test_case=tc,
                    snapshot_external_test_case_id=tc.external_test_case_id,
                    snapshot_test_case_name=tc.name,
                )

        status_url = request.build_absolute_uri(f'/api/workflows/{workflow.id}/')
        return Response(
            {
                'workflow_id': str(workflow.id),
                'status': workflow.status,
                'status_url': status_url,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class WorkflowListView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def get(self, request):
        qs = WorkflowRun.objects.all().order_by('-created_at')
        product_id = request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return Response(WorkflowRunSerializer(qs, many=True).data)


class WorkflowDetailView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def get(self, request, pk):
        try:
            workflow = WorkflowRun.objects.get(pk=pk)
        except WorkflowRun.DoesNotExist:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(WorkflowRunSerializer(workflow).data)


class WorkflowExecutionsView(APIView):
    authentication_classes = _PLATFORM_AUTH
    permission_classes = _PLATFORM_PERM

    def get(self, request, pk):
        try:
            workflow = WorkflowRun.objects.get(pk=pk)
        except WorkflowRun.DoesNotExist:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        executions = workflow.executions.all().order_by('phase', 'queued_at')
        return Response(TestExecutionSerializer(executions, many=True).data)


# ---------------------------------------------------------------------------
# Callback endpoint — receives execution status events from external services
# ---------------------------------------------------------------------------

class ExecutionEventView(APIView):
    """
    POST /api/execution-events/

    Authentication: per-product X-Callback-Api-Key, validated against the
    product that owns the dispatch identified by request_id in the payload.
    This binds the credential to a specific product.

    Idempotency: duplicate event_ids are accepted but not processed twice.
    Out-of-order events: RUNNING/QUEUED status updates are ignored if the
    execution is already in a terminal state.
    Late results after workflow completion are stored in CallbackReceipt
    with processed=False for inspection, but do not reopen the workflow.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = CallbackEventSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Resolve the dispatch and validate the callback key
        try:
            dispatch = (
                Dispatch.objects
                .select_related('workflow__product')
                .get(id=data['request_id'])
            )
        except Dispatch.DoesNotExist:
            return Response(
                {'error': 'Unknown request_id.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        product = dispatch.workflow.product
        expected_key = env(product.callback_secret_env_key, default='')
        provided_key = request.headers.get('X-Callback-Api-Key', '')
        if not expected_key or provided_key != expected_key:
            logger.warning(
                "Callback auth failure for dispatch %s product %s",
                dispatch.id, product.id,
            )
            return Response(
                {'error': 'Invalid callback API key.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Verify the execution belongs to this dispatch
        if not dispatch.executions.filter(id=data['execution_id']).exists():
            return Response(
                {'error': 'execution_id does not belong to this dispatch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = self._process_event(data, dispatch)
            return Response(result, status=status.HTTP_200_OK)
        except IntegrityError:
            # Concurrent request for the same event_id — treat as duplicate
            return Response({'status': 'already_received'}, status=status.HTTP_200_OK)

    def _process_event(self, data, dispatch):
        with transaction.atomic():
            execution = (
                TestExecution.objects
                .select_for_update()
                .get(id=data['execution_id'])
            )

            # Idempotency: check for duplicate event_id inside the transaction
            if CallbackReceipt.objects.filter(event_id=data['event_id']).exists():
                return {'status': 'already_received'}

            status_received = data['status']
            occurred_at = data['occurred_at']
            result_data = data.get('result') or {}

            receipt = CallbackReceipt.objects.create(
                event_id=data['event_id'],
                execution=execution,
                dispatch=dispatch,
                occurred_at=occurred_at,
                status_received=status_received,
                processed=False,
            )

            # Don't overwrite a terminal status
            if execution.is_terminal:
                receipt.processing_error = (
                    f"Execution already in terminal state: {execution.status}"
                )
                receipt.save()
                logger.info(
                    "Late callback event %s for execution %s (already %s)",
                    data['event_id'], execution.id, execution.status,
                )
                return {'status': 'received_not_applied'}

            # Don't let a non-terminal status overwrite a terminal one
            # (extra guard for out-of-order RUNNING arriving after PASSED)
            new_status = ExecutionStatus(status_received)
            if new_status not in TERMINAL_STATUSES and execution.status in TERMINAL_STATUSES:
                receipt.processing_error = (
                    f"Non-terminal status '{status_received}' arrived after terminal"
                )
                receipt.save()
                return {'status': 'received_not_applied'}

            # Apply the update
            execution.status = new_status
            if new_status == ExecutionStatus.RUNNING:
                if not execution.started_at:
                    execution.started_at = occurred_at
            elif new_status in TERMINAL_STATUSES:
                execution.completed_at = occurred_at
                if result_data:
                    execution.result_message = result_data.get('message', '')
                    execution.result_duration_ms = result_data.get('duration_ms')
                    execution.result_data = result_data.get('data')
            execution.save()

            receipt.processed = True
            receipt.save()

            logger.info(
                "Execution %s → %s (event %s)",
                execution.id, new_status, data['event_id'],
            )
            return {'status': 'received'}
