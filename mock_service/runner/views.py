"""
Mock external service views.

POST /api/test-runs/  — accepts a dispatch from the UTTT worker
GET  /api/test-runs/{request_id}/  — returns status of a submitted run

Authentication: X-Api-Key header validated against settings.MOCK_API_KEY.
Idempotency: duplicate request_id with same payload → 200.
             duplicate request_id with different payload → 409.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MockExecution, MockTestDefinition, MockTestRun
from .serializers import MockTestRunStatusSerializer, SubmitTestRunSerializer

logger = logging.getLogger(__name__)


def _check_api_key(request):
    """Returns True if the X-Api-Key header is valid."""
    expected = settings.MOCK_API_KEY
    provided = request.headers.get('X-Api-Key', '')
    return bool(expected) and provided == expected


class SubmitTestRunView(APIView):
    """
    POST /api/test-runs/
    Called by the UTTT worker to dispatch a batch of test executions.
    Returns 202 on success.
    """

    def post(self, request):
        if not _check_api_key(request):
            return Response(
                {'error': 'Invalid API key.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = SubmitTestRunSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        request_id = data['request_id']
        callback_url = str(data['callback_url'])
        tests = data['tests']

        # Validate callback_url against allowlist
        allowed_bases = getattr(settings, 'ALLOWED_CALLBACK_URLS', [])
        if not any(callback_url.startswith(base) for base in allowed_bases):
            return Response(
                {'error': 'callback_url is not in the allowed list.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Compute hash for idempotency / conflict detection
        payload_hash = MockTestRun.compute_hash(
            [{'execution_id': t['execution_id'], 'test_case_id': t['test_case_id']}
             for t in tests]
        )

        try:
            existing = MockTestRun.objects.get(request_id=request_id)
            if existing.payload_hash == payload_hash:
                # Exact duplicate — idempotent accept
                return Response({'status': 'already_accepted'}, status=status.HTTP_200_OK)
            # Same request_id, different payload
            return Response(
                {'error': 'request_id already exists with a different payload.'},
                status=status.HTTP_409_CONFLICT,
            )
        except MockTestRun.DoesNotExist:
            pass

        # Create the run record
        test_run = MockTestRun.objects.create(
            request_id=request_id,
            payload_hash=payload_hash,
            callback_url=callback_url,
        )

        now = timezone.now()
        for item in tests:
            test_case_id = str(item['test_case_id'])
            execution_id = item['execution_id']

            try:
                defn = MockTestDefinition.objects.get(external_id=test_case_id)
                start_delay = defn.start_delay_seconds
                is_timeout = defn.behavior == 'timeout'
                result_status = 'PASSED' if defn.behavior == 'pass' else 'FAILED'
                result_message = defn.result_message
                complete_delay = defn.complete_delay_seconds
                duration_ms = int((complete_delay or 1.0) * 1000)
            except MockTestDefinition.DoesNotExist:
                logger.warning(
                    "Unknown test case '%s', defaulting to pass/1s", test_case_id
                )
                start_delay = 0.5
                is_timeout = False
                result_status = 'PASSED'
                result_message = ''
                complete_delay = 1.0
                duration_ms = 1000

            scheduled_start_at = now + timedelta(seconds=start_delay)
            if is_timeout:
                scheduled_complete_at = None
            else:
                scheduled_complete_at = now + timedelta(seconds=(complete_delay or 1.0))

            MockExecution.objects.create(
                test_run=test_run,
                execution_id=execution_id,
                test_case_id=test_case_id,
                status='QUEUED',
                scheduled_start_at=scheduled_start_at,
                scheduled_complete_at=scheduled_complete_at,
                result_status=result_status,
                result_message=result_message,
                result_duration_ms=duration_ms if not is_timeout else None,
            )

        logger.info(
            "Accepted test run %s with %d execution(s)", request_id, len(tests)
        )
        return Response({'status': 'accepted'}, status=status.HTTP_202_ACCEPTED)


class TestRunDetailView(APIView):
    """
    GET /api/test-runs/{request_id}/
    Returns the current status of a submitted test run and its executions.
    """

    def get(self, request, request_id):
        if not _check_api_key(request):
            return Response(
                {'error': 'Invalid API key.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            test_run = MockTestRun.objects.get(request_id=request_id)
        except MockTestRun.DoesNotExist:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(MockTestRunStatusSerializer(test_run).data)
