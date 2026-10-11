"""
UTTT Platform Worker — drives the workflow state machine.

Run with:
    python manage.py run_worker

All functions in this module are importable and callable from tests without
running the management command loop.

Concurrency model:
  - select_for_update(skip_locked=True) prevents two concurrent worker cycles
    from claiming the same dispatch or advancing the same workflow.
  - Outbound HTTP calls are ALWAYS made outside a database transaction.
  - Stale SENDING dispatches (from a crashed worker cycle) are reset at the
    start of each cycle by recover_stale_dispatches().
"""
import logging
import os
from datetime import timedelta

import requests as http_client
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Dispatch, DispatchStatus, ExecutionStatus,
    TERMINAL_STATUSES, TestExecution, WorkflowPhase,
    WorkflowRun, WorkflowStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_cycle():
    """One complete sweep of all pending work. Call in a loop from run_worker."""
    recover_stale_dispatches()
    create_pending_dispatches()
    dispatch_pending()
    handle_timeouts()
    advance_workflows()


# ---------------------------------------------------------------------------
# Step 1: Crash recovery — reset SENDING dispatches stuck from a previous crash
# ---------------------------------------------------------------------------

def recover_stale_dispatches():
    stale_cutoff = timezone.now() - timedelta(
        seconds=settings.WORKER_STALE_DISPATCH_SECONDS
    )
    count = Dispatch.objects.filter(
        status=DispatchStatus.SENDING,
        last_attempt_at__lt=stale_cutoff,
    ).update(status=DispatchStatus.UNCERTAIN)
    if count:
        logger.warning("Recovered %d stale SENDING dispatch(es)", count)


# ---------------------------------------------------------------------------
# Step 2: Create PRE dispatch records for PENDING workflows
# ---------------------------------------------------------------------------

def create_pending_dispatches():
    """
    For every PENDING workflow, create a Dispatch for the PRE phase and
    advance the workflow to RUNNING_PRE. Uses row-level locking so concurrent
    worker cycles do not double-dispatch the same workflow.
    """
    pending_ids = list(
        WorkflowRun.objects
        .filter(status=WorkflowStatus.PENDING)
        .values_list('id', flat=True)
    )
    for workflow_id in pending_ids:
        with transaction.atomic():
            try:
                workflow = (
                    WorkflowRun.objects
                    .select_for_update(skip_locked=True)
                    .get(id=workflow_id, status=WorkflowStatus.PENDING)
                )
            except WorkflowRun.DoesNotExist:
                continue  # Another worker claimed it, or status already changed

            pre_executions = list(
                workflow.executions.filter(phase=WorkflowPhase.PRE)
            )
            if not pre_executions:
                logger.error("Workflow %s has no PRE executions", workflow_id)
                workflow.status = WorkflowStatus.ERROR
                workflow.error_summary = "No PRE executions found at dispatch time"
                workflow.completed_at = timezone.now()
                workflow.save()
                continue

            dispatch = Dispatch.objects.create(
                workflow=workflow,
                phase=WorkflowPhase.PRE,
                status=DispatchStatus.PENDING,
                max_retries=settings.WORKER_MAX_DISPATCH_RETRIES,
            )
            dispatch.executions.set(pre_executions)

            workflow.status = WorkflowStatus.RUNNING_PRE
            workflow.current_phase = WorkflowPhase.PRE
            workflow.started_at = timezone.now()
            workflow.save()
            logger.info(
                "Created PRE dispatch %s for workflow %s", dispatch.id, workflow_id
            )


# ---------------------------------------------------------------------------
# Step 3: Send PENDING / retryable UNCERTAIN dispatches
# ---------------------------------------------------------------------------

def dispatch_pending():
    """Claim and send all currently sendable dispatches, one at a time."""
    dispatch_id = _claim_one_dispatch()
    while dispatch_id is not None:
        _send_dispatch(dispatch_id)
        dispatch_id = _claim_one_dispatch()


def _claim_one_dispatch():
    """
    Atomically claims one sendable dispatch by setting status=SENDING.
    The row lock is released at the end of this transaction — before any
    HTTP call is made.
    Returns the dispatch UUID, or None if nothing is available.
    """
    with transaction.atomic():
        dispatch = (
            Dispatch.objects
            .select_for_update(skip_locked=True)
            .filter(
                Q(status=DispatchStatus.PENDING) |
                Q(
                    status=DispatchStatus.UNCERTAIN,
                    retry_count__lt=settings.WORKER_MAX_DISPATCH_RETRIES,
                )
            )
            .first()
        )
        if dispatch is None:
            return None
        dispatch.status = DispatchStatus.SENDING
        dispatch.last_attempt_at = timezone.now()
        dispatch.save(update_fields=['status', 'last_attempt_at'])
        return dispatch.id


def _send_dispatch(dispatch_id):
    """
    Makes the outbound HTTP call for one claimed dispatch.
    Must be called OUTSIDE any open database transaction.
    """
    dispatch = (
        Dispatch.objects
        .select_related('workflow__product')
        .prefetch_related('executions')
        .get(id=dispatch_id)
    )
    product = dispatch.workflow.product
    api_key = os.environ.get(product.credential_env_key, '')
    callback_url = (
        f"{settings.UTTT_BASE_URL.rstrip('/')}/api/execution-events/"
    )

    payload = {
        'request_id': str(dispatch.id),
        'callback_url': callback_url,
        'tests': [
            {
                'execution_id': str(e.id),
                'test_case_id': e.snapshot_external_test_case_id,
            }
            for e in dispatch.executions.all()
        ],
    }

    logger.info(
        "Dispatching %s phase=%s attempt=%d to %s",
        dispatch_id, dispatch.phase,
        dispatch.retry_count + 1,
        product.external_api_base_url,
    )

    try:
        response = http_client.post(
            f"{product.external_api_base_url.rstrip('/')}/api/test-runs/",
            json=payload,
            headers={'X-Api-Key': api_key},
            timeout=settings.WORKER_HTTP_TIMEOUT_SECONDS,
        )
        _record_dispatch_response(dispatch, response)
    except http_client.exceptions.RequestException as exc:
        _record_dispatch_exception(dispatch, str(exc))


def _record_dispatch_response(dispatch, response):
    with transaction.atomic():
        dispatch.refresh_from_db()
        if response.status_code == 202:
            dispatch.status = DispatchStatus.ACCEPTED
            dispatch.dispatched_at = timezone.now()
            dispatch.accepted_at = timezone.now()
            dispatch.last_error = ''
            dispatch.save()
            logger.info("Dispatch %s accepted by external service", dispatch.id)

        elif 400 <= response.status_code < 500:
            error = f"HTTP {response.status_code}: {response.text[:500]}"
            dispatch.status = DispatchStatus.REJECTED
            dispatch.last_error = error
            dispatch.save()
            _mark_workflow_error(
                dispatch.workflow_id,
                f"Dispatch permanently rejected: {error}",
            )
            logger.error("Dispatch %s rejected: %s", dispatch.id, error)

        else:
            dispatch.retry_count += 1
            dispatch.last_error = f"HTTP {response.status_code}"
            if dispatch.retry_count >= dispatch.max_retries:
                dispatch.status = DispatchStatus.FAILED
                dispatch.save()
                _mark_workflow_error(
                    dispatch.workflow_id,
                    f"Dispatch failed after {dispatch.retry_count} attempts",
                )
            else:
                dispatch.status = DispatchStatus.UNCERTAIN
                dispatch.save()
            logger.warning(
                "Dispatch %s HTTP %d (retry %d/%d)",
                dispatch.id, response.status_code,
                dispatch.retry_count, dispatch.max_retries,
            )


def _record_dispatch_exception(dispatch, error_msg):
    with transaction.atomic():
        dispatch.refresh_from_db()
        dispatch.retry_count += 1
        dispatch.last_error = error_msg[:500]
        if dispatch.retry_count >= dispatch.max_retries:
            dispatch.status = DispatchStatus.FAILED
            dispatch.save()
            _mark_workflow_error(
                dispatch.workflow_id,
                f"Dispatch failed after {dispatch.retry_count} attempts: {error_msg[:200]}",
            )
        else:
            dispatch.status = DispatchStatus.UNCERTAIN
            dispatch.save()
        logger.warning(
            "Dispatch %s exception (retry %d/%d): %s",
            dispatch.id, dispatch.retry_count, dispatch.max_retries, error_msg,
        )


def _mark_workflow_error(workflow_id, summary):
    """Mark a workflow as ERROR and SKIP all remaining QUEUED executions."""
    try:
        with transaction.atomic():
            workflow = WorkflowRun.objects.select_for_update().get(id=workflow_id)
            terminal = {
                WorkflowStatus.PASSED, WorkflowStatus.FAILED, WorkflowStatus.ERROR
            }
            if workflow.status not in terminal:
                workflow.status = WorkflowStatus.ERROR
                workflow.error_summary = summary
                workflow.completed_at = timezone.now()
                workflow.save()
                workflow.executions.filter(
                    status=ExecutionStatus.QUEUED
                ).update(status=ExecutionStatus.SKIPPED)
    except WorkflowRun.DoesNotExist:
        pass


# ---------------------------------------------------------------------------
# Step 4: Timeout executions that never received a terminal callback
# ---------------------------------------------------------------------------

def handle_timeouts():
    """
    Mark non-terminal executions as TIMED_OUT when their dispatch was
    accepted but the result deadline has passed.
    """
    cutoff = timezone.now() - timedelta(
        seconds=settings.EXECUTION_TIMEOUT_SECONDS
    )
    candidates = list(
        TestExecution.objects
        .filter(
            status__in=[ExecutionStatus.QUEUED, ExecutionStatus.RUNNING],
            dispatches__status=DispatchStatus.ACCEPTED,
            dispatches__accepted_at__lt=cutoff,
        )
        .distinct()
        .values_list('id', flat=True)
    )
    for exec_id in candidates:
        with transaction.atomic():
            try:
                execution = TestExecution.objects.select_for_update(
                    skip_locked=True
                ).get(
                    id=exec_id,
                    status__in=[ExecutionStatus.QUEUED, ExecutionStatus.RUNNING],
                )
            except TestExecution.DoesNotExist:
                continue
            execution.status = ExecutionStatus.TIMED_OUT
            execution.completed_at = timezone.now()
            execution.save()
            logger.warning("Execution %s timed out", exec_id)


# ---------------------------------------------------------------------------
# Step 5: Advance workflow state machine
# ---------------------------------------------------------------------------

def advance_workflows():
    _advance_pre_tests()
    _simulate_patch()
    _advance_post_tests()


def _advance_pre_tests():
    """
    Check RUNNING_PRE workflows.
    If all PRE executions are terminal:
      - All PASSED → advance to PATCHING
      - Any not-PASSED → advance to FAILED, SKIP remaining POST executions
    """
    candidate_ids = list(
        WorkflowRun.objects
        .filter(status=WorkflowStatus.RUNNING_PRE)
        .values_list('id', flat=True)
    )
    for workflow_id in candidate_ids:
        with transaction.atomic():
            try:
                workflow = (
                    WorkflowRun.objects
                    .select_for_update(skip_locked=True)
                    .get(id=workflow_id, status=WorkflowStatus.RUNNING_PRE)
                )
            except WorkflowRun.DoesNotExist:
                continue

            executions = list(
                workflow.executions.filter(phase=WorkflowPhase.PRE)
            )
            if not all(e.is_terminal for e in executions):
                continue  # Phase not yet complete

            if all(e.status == ExecutionStatus.PASSED for e in executions):
                workflow.status = WorkflowStatus.PATCHING
                workflow.patch_started_at = timezone.now()
                logger.info("Workflow %s: all PRE passed → PATCHING", workflow_id)
            else:
                failed = [
                    e.snapshot_test_case_name
                    for e in executions
                    if e.status != ExecutionStatus.PASSED
                ]
                workflow.status = WorkflowStatus.FAILED
                workflow.completed_at = timezone.now()
                workflow.error_summary = (
                    "Pre-test failure: " + ", ".join(failed)
                )
                workflow.executions.filter(
                    phase=WorkflowPhase.POST,
                    status=ExecutionStatus.QUEUED,
                ).update(status=ExecutionStatus.SKIPPED)
                logger.info(
                    "Workflow %s: PRE FAILED (%s)", workflow_id, workflow.error_summary
                )
            workflow.save()


def _simulate_patch():
    """
    Advance PATCHING workflows to RUNNING_POST.
    Records patch timestamps (both start and end) and creates the POST dispatch.
    In a real system the patch step would be async; here it completes immediately.
    """
    candidate_ids = list(
        WorkflowRun.objects
        .filter(status=WorkflowStatus.PATCHING)
        .values_list('id', flat=True)
    )
    for workflow_id in candidate_ids:
        with transaction.atomic():
            try:
                workflow = (
                    WorkflowRun.objects
                    .select_for_update(skip_locked=True)
                    .get(id=workflow_id, status=WorkflowStatus.PATCHING)
                )
            except WorkflowRun.DoesNotExist:
                continue

            now = timezone.now()
            # patch_started_at was set when entering PATCHING; record completion
            if not workflow.patch_started_at:
                workflow.patch_started_at = now
            workflow.patch_completed_at = now
            workflow.status = WorkflowStatus.RUNNING_POST
            workflow.current_phase = WorkflowPhase.POST
            workflow.save()

            post_executions = list(
                workflow.executions.filter(phase=WorkflowPhase.POST)
            )
            post_dispatch = Dispatch.objects.create(
                workflow=workflow,
                phase=WorkflowPhase.POST,
                status=DispatchStatus.PENDING,
                max_retries=settings.WORKER_MAX_DISPATCH_RETRIES,
            )
            post_dispatch.executions.set(post_executions)
            logger.info(
                "Workflow %s: patch complete → RUNNING_POST (dispatch %s)",
                workflow_id, post_dispatch.id,
            )


def _advance_post_tests():
    """
    Check RUNNING_POST workflows.
    If all POST executions are terminal:
      - All PASSED → PASSED
      - Any not-PASSED → FAILED
    """
    candidate_ids = list(
        WorkflowRun.objects
        .filter(status=WorkflowStatus.RUNNING_POST)
        .values_list('id', flat=True)
    )
    for workflow_id in candidate_ids:
        with transaction.atomic():
            try:
                workflow = (
                    WorkflowRun.objects
                    .select_for_update(skip_locked=True)
                    .get(id=workflow_id, status=WorkflowStatus.RUNNING_POST)
                )
            except WorkflowRun.DoesNotExist:
                continue

            executions = list(
                workflow.executions.filter(phase=WorkflowPhase.POST)
            )
            if not all(e.is_terminal for e in executions):
                continue

            workflow.completed_at = timezone.now()
            if all(e.status == ExecutionStatus.PASSED for e in executions):
                workflow.status = WorkflowStatus.PASSED
                logger.info("Workflow %s: PASSED", workflow_id)
            else:
                failed = [
                    e.snapshot_test_case_name
                    for e in executions
                    if e.status != ExecutionStatus.PASSED
                ]
                workflow.status = WorkflowStatus.FAILED
                workflow.error_summary = (
                    "Post-test failure: " + ", ".join(failed)
                )
                logger.info(
                    "Workflow %s: FAILED (%s)", workflow_id, workflow.error_summary
                )
            workflow.save()
