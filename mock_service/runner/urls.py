from django.urls import path

from .views import SubmitTestRunView, TestRunDetailView

urlpatterns = [
    path('test-runs/', SubmitTestRunView.as_view(), name='submit-test-run'),
    path('test-runs/<uuid:request_id>/', TestRunDetailView.as_view(), name='test-run-detail'),
]
