"""
URL routing for the tasks app.

DefaultRouter automatically generates these URL patterns from TaskViewSet:

    GET    /api/tasks/        list all tasks
    POST   /api/tasks/        create a task
    GET    /api/tasks/{id}/   retrieve one task
    PUT    /api/tasks/{id}/   fully update a task
    PATCH  /api/tasks/{id}/   partially update a task
    DELETE /api/tasks/{id}/   delete a task
    GET    /api/              API root (lists available endpoints)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')

urlpatterns = [
    path('', include(router.urls)),
]
