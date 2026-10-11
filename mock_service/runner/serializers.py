"""
Serializers for the mock external service API.
"""
from rest_framework import serializers

from .models import MockExecution, MockTestRun


class TestItemSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField()
    test_case_id = serializers.CharField(max_length=200)


class SubmitTestRunSerializer(serializers.Serializer):
    """Validates an incoming dispatch request from the UTTT worker."""
    request_id = serializers.UUIDField()
    callback_url = serializers.URLField(max_length=500)
    tests = serializers.ListField(
        child=TestItemSerializer(),
        min_length=1,
        error_messages={'min_length': 'At least one test is required.'},
    )


class MockExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MockExecution
        fields = [
            'execution_id', 'test_case_id', 'status',
            'scheduled_start_at', 'scheduled_complete_at',
            'result_status',
        ]


class MockTestRunStatusSerializer(serializers.ModelSerializer):
    executions = MockExecutionSerializer(many=True, read_only=True)

    class Meta:
        model = MockTestRun
        fields = ['request_id', 'received_at', 'executions']
