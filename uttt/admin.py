from django.contrib import admin

from .models import (
    CallbackReceipt, Dispatch, Product,
    RegisteredTestCase, TestExecution, WorkflowRun,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'external_api_base_url', 'enabled', 'created_at']
    list_filter = ['enabled']
    search_fields = ['name']


@admin.register(RegisteredTestCase)
class RegisteredTestCaseAdmin(admin.ModelAdmin):
    list_display = ['external_test_case_id', 'name', 'product', 'enabled', 'created_at']
    list_filter = ['product', 'enabled']
    search_fields = ['name', 'external_test_case_id']


@admin.register(WorkflowRun)
class WorkflowRunAdmin(admin.ModelAdmin):
    list_display = ['id', 'product', 'status', 'current_phase', 'created_at', 'completed_at']
    list_filter = ['status', 'product']
    readonly_fields = ['id', 'created_at']


@admin.register(TestExecution)
class TestExecutionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'workflow', 'phase',
        'snapshot_external_test_case_id', 'status', 'queued_at',
    ]
    list_filter = ['phase', 'status']
    readonly_fields = ['id', 'queued_at']


@admin.register(Dispatch)
class DispatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'workflow', 'phase', 'status', 'retry_count', 'created_at']
    list_filter = ['status', 'phase']
    readonly_fields = ['id', 'created_at']


@admin.register(CallbackReceipt)
class CallbackReceiptAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'execution', 'status_received', 'processed', 'received_at']
    list_filter = ['processed', 'status_received']
    readonly_fields = ['event_id', 'received_at']
