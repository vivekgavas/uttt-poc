from django.contrib import admin

from .models import MockExecution, MockTestDefinition, MockTestRun, PendingCallback


@admin.register(MockTestDefinition)
class MockTestDefinitionAdmin(admin.ModelAdmin):
    list_display = ['external_id', 'name', 'behavior', 'start_delay_seconds', 'complete_delay_seconds']
    list_filter = ['behavior']
    search_fields = ['external_id', 'name']


@admin.register(MockTestRun)
class MockTestRunAdmin(admin.ModelAdmin):
    list_display = ['request_id', 'callback_url', 'received_at']
    readonly_fields = ['request_id', 'received_at']


@admin.register(MockExecution)
class MockExecutionAdmin(admin.ModelAdmin):
    list_display = ['execution_id', 'test_case_id', 'status', 'result_status', 'scheduled_start_at']
    list_filter = ['status', 'result_status']
    readonly_fields = ['execution_id']


@admin.register(PendingCallback)
class PendingCallbackAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'status_to_report', 'delivered', 'retry_count', 'created_at']
    list_filter = ['delivered', 'status_to_report']
    readonly_fields = ['event_id', 'created_at']
