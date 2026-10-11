from rest_framework import serializers

from .models import (
    Dispatch, ExecutionStatus, Product, RegisteredTestCase,
    TestExecution, WorkflowRun,
)


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'external_api_base_url',
            'credential_env_key', 'callback_secret_env_key',
            'enabled', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ---------------------------------------------------------------------------
# RegisteredTestCase
# ---------------------------------------------------------------------------

class RegisteredTestCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredTestCase
        fields = [
            'id', 'product', 'external_test_case_id',
            'name', 'description', 'enabled', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate(self, data):
        # Enforce unique external_test_case_id within product on create/update
        product = data.get('product', getattr(self.instance, 'product', None))
        ext_id = data.get('external_test_case_id',
                          getattr(self.instance, 'external_test_case_id', None))
        qs = RegisteredTestCase.objects.filter(product=product, external_test_case_id=ext_id)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'external_test_case_id': 'This ID is already registered for this product.'}
            )
        return data


# ---------------------------------------------------------------------------
# WorkflowRun (read-only — created via CreateWorkflowSerializer)
# ---------------------------------------------------------------------------

class WorkflowRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRun
        fields = [
            'id', 'product', 'status', 'current_phase',
            'created_at', 'started_at', 'completed_at',
            'patch_started_at', 'patch_completed_at',
            'error_summary',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# TestExecution (read-only)
# ---------------------------------------------------------------------------

class TestExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestExecution
        fields = [
            'id', 'workflow', 'phase',
            'registered_test_case',
            'snapshot_external_test_case_id', 'snapshot_test_case_name',
            'status', 'queued_at', 'started_at', 'completed_at',
            'result_message', 'result_duration_ms', 'result_data',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Workflow creation input
# ---------------------------------------------------------------------------

class CreateWorkflowSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    pre_test_case_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1,
        error_messages={'min_length': 'At least one pre-test case is required.'},
    )
    post_test_case_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1,
        error_messages={'min_length': 'At least one post-test case is required.'},
    )

    def validate(self, data):
        try:
            product = Product.objects.get(id=data['product_id'], enabled=True)
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                {'product_id': 'Product not found or is disabled.'}
            )
        data['product'] = product

        data['pre_test_cases'] = self._resolve_test_cases(
            data['pre_test_case_ids'], product, 'pre_test_case_ids'
        )
        data['post_test_cases'] = self._resolve_test_cases(
            data['post_test_case_ids'], product, 'post_test_case_ids'
        )
        return data

    def _resolve_test_cases(self, ids, product, field_name):
        # Reject duplicates within the same phase
        str_ids = [str(i) for i in ids]
        if len(str_ids) != len(set(str_ids)):
            raise serializers.ValidationError(
                {field_name: 'Duplicate test case IDs within a phase are not allowed.'}
            )
        cases = []
        for tc_id in ids:
            try:
                tc = RegisteredTestCase.objects.get(id=tc_id, product=product, enabled=True)
            except RegisteredTestCase.DoesNotExist:
                raise serializers.ValidationError({
                    field_name: (
                        f"Test case {tc_id} not found, is disabled, "
                        "or belongs to a different product."
                    )
                })
            cases.append(tc)
        return cases


# ---------------------------------------------------------------------------
# Callback event input
# ---------------------------------------------------------------------------

class CallbackResultSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, default='')
    duration_ms = serializers.IntegerField(required=False, allow_null=True)
    data = serializers.JSONField(required=False, allow_null=True)


class CallbackEventSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    request_id = serializers.UUIDField()
    execution_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=[s.value for s in ExecutionStatus])
    occurred_at = serializers.DateTimeField()
    result = CallbackResultSerializer(required=False, allow_null=True)
