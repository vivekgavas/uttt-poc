from django.urls import path

from .views import (
    ExecutionEventView,
    ProductListCreateView,
    TestCaseDetailView,
    TestCaseListCreateView,
    WorkflowCreateView,
    WorkflowDetailView,
    WorkflowExecutionsView,
    WorkflowListView,
)

urlpatterns = [
    # Products
    path('products/', ProductListCreateView.as_view(), name='uttt-products'),

    # Test cases
    path('test-cases/', TestCaseListCreateView.as_view(), name='uttt-test-cases'),
    path('test-cases/<uuid:pk>/', TestCaseDetailView.as_view(), name='uttt-test-case-detail'),

    # Workflows
    path('workflows/', WorkflowListView.as_view(), name='uttt-workflows'),
    path('workflows/create/', WorkflowCreateView.as_view(), name='uttt-workflow-create'),
    path('workflows/<uuid:pk>/', WorkflowDetailView.as_view(), name='uttt-workflow-detail'),
    path('workflows/<uuid:pk>/executions/', WorkflowExecutionsView.as_view(), name='uttt-workflow-executions'),

    # Callback receiver
    path('execution-events/', ExecutionEventView.as_view(), name='uttt-execution-events'),
]
