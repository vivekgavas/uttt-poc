"""
Mock service worker — transitions execution states and delivers callbacks to UTTT.

Run with:
    python mock_service/manage.py run_mock_worker

Flow each cycle:
  1. schedule_running_callbacks  — QUEUED execs whose start time has passed → RUNNING
  2. schedule_terminal_callbacks — RUNNING execs whose complete time has passed → DONE
  3. deliver_pending_callbacks   — POST each PendingCallback to UTTT, retry on failure

TIMEOUT executions (complete_delay_seconds is NULL) never reach step 2, so UTTT
detects them via its own timeout logic.
"""
import logging

import requests as http_client
from django.conf import settings
from django.utils import timezone

from .models import MockExecution, PendingCallback

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_mock_cycle():
    """One complete sweep of all pending work. Call in a loop from run_mock_worker."""
    schedule_running_callbacks()
    schedule_terminal_callbacks()
    deliver_pending_callbacks()


# ---------------------------------------------------------------------------
# Step 1: QUEUED → RUNNING
# ---------------------------------------------------------------------------

def schedule_running_callbacks():
    """
    Transition QUEUED executions whose start time has passed to RUNNING
    and queue a RUNNING callback for delivery.
    """
    now = timezone.now()
    ready = list(
        MockExecution.objects
        .filter(status='QUEUED', scheduled_start_at__lte=now)
        .select_related('test_run')
    )
    for execution in ready:
        execution.status = 'RUNNING'
        execution.save(update_fields=['status'])
        PendingCallback.objects.create(
            execution=execution,
            status_to_report='RUNNING',
            occurred_at=now,
            result=None,
        )
        logger.info("Execution %s → RUNNING", execution.execution_id)


# ---------------------------------------------------------------------------
# Step 2: RUNNING → DONE
# ---------------------------------------------------------------------------

def schedule_terminal_callbacks():
    """
    Transition RUNNING executions whose completion time has passed to DONE
    and queue a PASSED/FAILED callback for delivery.
    Executions with scheduled_complete_at=NULL (timeout behavior) are skipped.
    """
    now = timezone.now()
    ready = list(
        MockExecution.objects
        .filter(
            status='RUNNING',
            scheduled_complete_at__isnull=False,
            scheduled_complete_at__lte=now,
        )
        .select_related('test_run')
    )
    for execution in ready:
        execution.status = 'DONE'
        execution.save(update_fields=['status'])
        result = {
            'message': execution.result_message,
            'duration_ms': execution.result_duration_ms,
        }
        PendingCallback.objects.create(
            execution=execution,
            status_to_report=execution.result_status,  # 'PASSED' or 'FAILED'
            occurred_at=now,
            result=result,
        )
        logger.info(
            "Execution %s → %s", execution.execution_id, execution.result_status
        )


# ---------------------------------------------------------------------------
# Step 3: Deliver queued callbacks
# ---------------------------------------------------------------------------

def deliver_pending_callbacks():
    """
    Attempt to POST each undelivered PendingCallback to UTTT.
    Backs off by incrementing retry_count; gives up at CALLBACK_MAX_RETRIES.
    """
    pending = list(
        PendingCallback.objects
        .filter(delivered=False, retry_count__lt=settings.CALLBACK_MAX_RETRIES)
        .select_related('execution__test_run')
        .order_by('created_at')
    )
    for callback in pending:
        _deliver_one(callback)


def _deliver_one(callback):
    execution = callback.execution
    test_run = execution.test_run
    uttt_callback_key = getattr(settings, 'UTTT_CALLBACK_API_KEY', '')

    payload = {
        'event_id': str(callback.event_id),
        'request_id': str(test_run.request_id),
        'execution_id': str(execution.execution_id),
        'status': callback.status_to_report,
        'occurred_at': callback.occurred_at.isoformat(),
        'result': callback.result,
    }

    try:
        response = http_client.post(
            test_run.callback_url,
            json=payload,
            headers={'X-Callback-Api-Key': uttt_callback_key},
            timeout=settings.CALLBACK_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            callback.delivered = True
            callback.last_error = ''
            callback.last_attempt_at = timezone.now()
            callback.save()
            logger.info(
                "Delivered %s callback (event=%s execution=%s)",
                callback.status_to_report, callback.event_id, execution.execution_id,
            )
        else:
            _record_failure(
                callback,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )
    except http_client.exceptions.RequestException as exc:
        _record_failure(callback, str(exc)[:200])


def _record_failure(callback, error):
    callback.retry_count += 1
    callback.last_attempt_at = timezone.now()
    callback.last_error = error
    callback.save(update_fields=['retry_count', 'last_attempt_at', 'last_error'])
    logger.warning(
        "Callback delivery failed (event=%s attempt=%d/%d): %s",
        callback.event_id, callback.retry_count,
        settings.CALLBACK_MAX_RETRIES, error,
    )
