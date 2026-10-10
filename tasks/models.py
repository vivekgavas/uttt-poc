from django.db import models


class Task(models.Model):
    """
    Represents a single to-do task.

    Fields:
        title       — short label for the task (required, max 200 chars)
        description — longer details (optional, defaults to empty string)
        completed   — whether the task is done (defaults to False)
        created_at  — timestamp set automatically when the task is first saved
    """
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = 'done' if self.completed else 'pending'
        return f'[{status}] {self.title}'
