"""
Mock external service models (SQLite).

These models are completely independent of the UTTT platform models.
The mock service communicates with UTTT only through HTTP callbacks.
"""
import hashlib
import json
import uuid

from django.db import models


class MockTestDefinition(models.Model):
    """
    Defines how a test case behaves in the mock service.
    Seeded by: python mock_service/manage.py seed_mock
    """
    BEHAVIORS = [
        ('pass', 'Always passes'),
        ('fail', 'Always fails'),
        ('timeout', 'Never sends a terminal result'),
    ]
    external_id = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    behavior = models.CharField(max_length=20, choices=BEHAVIORS)
    # Seconds from acceptance before RUNNING callback is sent
    start_delay_seconds = models.FloatField(default=0.5)
    # Seconds from RUNNING before terminal callback. None = timeout (no terminal).
    complete_delay_seconds = models.FloatField(null=True, blank=True)
    result_message = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.external_id} ({self.behavior})"


class MockTestRun(models.Model):
    """
    Represents one accepted dispatch request from UTTT.

    `payload_hash` is used to detect duplicate submissions with a different
    payload (same request_id but different tests) — these get HTTP 409.
    """
    request_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    callback_url = models.URLField(max_length=500)
    received_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def compute_hash(tests):
        """Deterministic hash of the tests list for duplicate detection."""
        canonical = sorted(
            (str(t['execution_id']), str(t['test_case_id'])) for t in tests
        )
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()

    def __str__(self):
        return f"Run {self.request_id}"


class MockExecution(models.Model):
    """
    One test execution within a MockTestRun.

    `execution_id` is the opaque UTTT execution UUID, returned unchanged in callbacks.
    Scheduled timestamps control when the mock worker sends RUNNING and terminal callbacks.
    """
    test_run = models.ForeignKey(
        MockTestRun, on_delete=models.CASCADE, related_name='executions'
    )
    execution_id = models.UUIDField()          # UTTT's UUID — opaque to this service
    test_case_id = models.CharField(max_length=200)

    STATUS_CHOICES = [
        ('QUEUED', 'Queued'),
        ('RUNNING', 'Running'),
        ('DONE', 'Done'),       # terminal callback sent
        ('TIMEOUT', 'Timeout'), # never sends terminal
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='QUEUED')

    scheduled_start_at = models.DateTimeField()
    scheduled_complete_at = models.DateTimeField(null=True, blank=True)

    result_status = models.CharField(max_length=20, default='PASSED')  # 'PASSED' or 'FAILED'
    result_message = models.TextField(blank=True, default='')
    result_duration_ms = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"MockExec {self.execution_id} [{self.status}]"


class PendingCallback(models.Model):
    """
    A callback that the mock worker needs to deliver to UTTT.

    `event_id` is stable across retries — UTTT uses it for deduplication.
    Retries happen on transient HTTP failures using the same event_id and payload.
    """
    execution = models.ForeignKey(
        MockExecution, on_delete=models.CASCADE, related_name='pending_callbacks'
    )
    event_id = models.UUIDField(default=uuid.uuid4, unique=True)
    status_to_report = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    result = models.JSONField(null=True, blank=True)

    delivered = models.BooleanField(default=False)
    retry_count = models.IntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Callback {self.event_id} [{self.status_to_report}] delivered={self.delivered}"
