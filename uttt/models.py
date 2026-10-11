"""
UTTT Platform models.

Relationship summary:
  Product  ──< RegisteredTestCase
  Product  ──< WorkflowRun
  WorkflowRun ──< TestExecution
  WorkflowRun ──< Dispatch >──< TestExecution  (M2M)
  TestExecution ──< CallbackReceipt
"""
import uuid

from django.db import models


# ---------------------------------------------------------------------------
# Choice enumerations
# ---------------------------------------------------------------------------

class WorkflowStatus(models.TextChoices):
    PENDING      = 'PENDING',      'Pending'
    RUNNING_PRE  = 'RUNNING_PRE',  'Running pre-tests'
    PATCHING     = 'PATCHING',     'Patching'
    RUNNING_POST = 'RUNNING_POST', 'Running post-tests'
    PASSED       = 'PASSED',       'Passed'
    FAILED       = 'FAILED',       'Failed'
    ERROR        = 'ERROR',        'Error'


class WorkflowPhase(models.TextChoices):
    PRE  = 'PRE',  'Pre-test'
    POST = 'POST', 'Post-test'


class ExecutionStatus(models.TextChoices):
    QUEUED    = 'QUEUED',    'Queued'
    RUNNING   = 'RUNNING',   'Running'
    PASSED    = 'PASSED',    'Passed'
    FAILED    = 'FAILED',    'Failed'
    ERROR     = 'ERROR',     'Error'
    TIMED_OUT = 'TIMED_OUT', 'Timed out'
    SKIPPED   = 'SKIPPED',   'Skipped'

TERMINAL_STATUSES = frozenset({
    ExecutionStatus.PASSED,
    ExecutionStatus.FAILED,
    ExecutionStatus.ERROR,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.SKIPPED,
})


class DispatchStatus(models.TextChoices):
    PENDING   = 'PENDING',   'Pending'
    SENDING   = 'SENDING',   'Sending'    # claimed by worker; crash-recovery resets to UNCERTAIN
    ACCEPTED  = 'ACCEPTED',  'Accepted'   # external service confirmed 202
    REJECTED  = 'REJECTED',  'Rejected'   # external service confirmed 4xx
    UNCERTAIN = 'UNCERTAIN', 'Uncertain'  # transient HTTP failure; will retry
    FAILED    = 'FAILED',    'Failed'     # max retries exhausted


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class Product(models.Model):
    """
    An external product team whose tests UTTT orchestrates.

    Credentials for the external service are NOT stored here.
    `credential_env_key` names the env var that holds the API key UTTT sends
    when calling the external service.
    `callback_secret_env_key` names the env var that holds the shared secret
    the external service sends in the X-Callback-Api-Key header.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    external_api_base_url = models.URLField(max_length=500)
    credential_env_key = models.CharField(
        max_length=200,
        help_text="Env var name holding the API key sent to the external service",
    )
    callback_secret_env_key = models.CharField(
        max_length=200,
        help_text="Env var name holding the expected X-Callback-Api-Key value",
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# RegisteredTestCase
# ---------------------------------------------------------------------------

class RegisteredTestCase(models.Model):
    """
    A test case registered with UTTT before execution.

    `external_test_case_id` is the identifier used by the external service.
    It must be unique within a product.
    A test case may be used in either pre-tests or post-tests when creating
    a workflow; there is no fixed phase assignment here.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='test_cases'
    )
    external_test_case_id = models.CharField(max_length=200)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['product', 'external_test_case_id']]

    def __str__(self):
        return f"{self.product.name}/{self.external_test_case_id}"


# ---------------------------------------------------------------------------
# WorkflowRun
# ---------------------------------------------------------------------------

class WorkflowRun(models.Model):
    """
    One execution of the pre-test → patch → post-test pipeline.

    State machine (see worker.py):
      PENDING → RUNNING_PRE → PATCHING → RUNNING_POST → PASSED
                           ↘ FAILED (pre fail, skips patch and post)
                                               ↘ FAILED (post fail)
      Any state → ERROR (dispatch permanently rejected / system fault)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='workflows'
    )
    status = models.CharField(
        max_length=20, choices=WorkflowStatus.choices,
        default=WorkflowStatus.PENDING,
        db_index=True,
    )
    current_phase = models.CharField(
        max_length=10, choices=WorkflowPhase.choices, null=True, blank=True
    )

    # Lifecycle timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Patch step timestamps (visible even though patching is simulated)
    patch_started_at = models.DateTimeField(null=True, blank=True)
    patch_completed_at = models.DateTimeField(null=True, blank=True)

    error_summary = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Workflow {self.id} [{self.status}]"


# ---------------------------------------------------------------------------
# TestExecution
# ---------------------------------------------------------------------------

class TestExecution(models.Model):
    """
    One test case within one workflow phase.

    Metadata is snapshotted at creation time so later edits to the
    RegisteredTestCase do not alter historical records.
    A test case can appear in both PRE and POST phases; each gets a
    separate TestExecution record.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name='executions'
    )
    phase = models.CharField(max_length=10, choices=WorkflowPhase.choices)
    registered_test_case = models.ForeignKey(
        RegisteredTestCase, on_delete=models.PROTECT, related_name='executions'
    )

    # Snapshot fields — copied from RegisteredTestCase at creation
    snapshot_external_test_case_id = models.CharField(max_length=200)
    snapshot_test_case_name = models.CharField(max_length=200)

    status = models.CharField(
        max_length=20, choices=ExecutionStatus.choices,
        default=ExecutionStatus.QUEUED,
        db_index=True,
    )
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Result — populated from the terminal callback
    result_message = models.TextField(blank=True, default='')
    result_duration_ms = models.IntegerField(null=True, blank=True)
    result_data = models.JSONField(null=True, blank=True)

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES

    def __str__(self):
        return f"Exec {self.id} [{self.status}] {self.phase}"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

class Dispatch(models.Model):
    """
    One dispatch of a workflow phase to the external service.

    `id` is used as the stable `request_id` in all outbound HTTP calls.
    Retries reuse the same Dispatch record (and thus the same request_id and
    payload), allowing the external service to deduplicate them.

    Dispatch status flow:
      PENDING → SENDING (claimed by worker; HTTP call about to be made)
      SENDING → ACCEPTED  (external service returned 202)
      SENDING → REJECTED  (external service returned 4xx; permanent failure)
      SENDING → UNCERTAIN (network error or 5xx; will retry)
      UNCERTAIN → SENDING (retry attempt)
      UNCERTAIN → FAILED  (max retries exhausted)
    Stale SENDING records (worker crashed mid-send) are reset to UNCERTAIN
    by recover_stale_dispatches() at the start of each worker cycle.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name='dispatches'
    )
    phase = models.CharField(max_length=10, choices=WorkflowPhase.choices)
    executions = models.ManyToManyField(TestExecution, related_name='dispatches')
    status = models.CharField(
        max_length=20, choices=DispatchStatus.choices,
        default=DispatchStatus.PENDING,
        db_index=True,
    )
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dispatch {self.id} [{self.status}] {self.phase}"


# ---------------------------------------------------------------------------
# CallbackReceipt
# ---------------------------------------------------------------------------

class CallbackReceipt(models.Model):
    """
    Every inbound callback event is recorded here before processing.

    `event_id` has a unique constraint so duplicate deliveries are detected.
    If an execution is already in a terminal state when the callback arrives,
    the receipt is stored with `processed=False` and a `processing_error`,
    but the execution status is NOT changed. This preserves late results for
    inspection without reopening completed workflows.
    """
    event_id = models.UUIDField(unique=True)
    execution = models.ForeignKey(
        TestExecution, on_delete=models.CASCADE, related_name='callback_receipts'
    )
    dispatch = models.ForeignKey(
        Dispatch, on_delete=models.CASCADE, related_name='callback_receipts'
    )
    received_at = models.DateTimeField(auto_now_add=True)
    occurred_at = models.DateTimeField()
    status_received = models.CharField(max_length=20)
    processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, default='')

    def __str__(self):
        return f"CallbackReceipt {self.event_id} [{self.status_received}]"
