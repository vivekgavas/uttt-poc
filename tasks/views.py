from rest_framework import viewsets
from .models import Task
from .serializers import TaskSerializer


class TaskViewSet(viewsets.ModelViewSet):
    """
    A ViewSet that provides all standard CRUD operations for Task objects.

    DRF's ModelViewSet automatically creates these actions:
        list        GET  /api/tasks/       — returns all tasks
        create      POST /api/tasks/       — creates a new task
        retrieve    GET  /api/tasks/{id}/  — returns one task by id
        update      PUT  /api/tasks/{id}/  — replaces a task (all fields required)
        partial_update PATCH /api/tasks/{id}/ — updates specific fields only
        destroy     DELETE /api/tasks/{id}/ — deletes a task
    """
    queryset = Task.objects.all().order_by('-created_at')
    serializer_class = TaskSerializer
