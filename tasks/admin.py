from django.contrib import admin
from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """
    Configuration for the Task model in the Django admin interface.
    Access the admin at http://127.0.0.1:8000/admin/ after creating a superuser.
    """
    list_display = ['id', 'title', 'completed', 'created_at']
    list_filter = ['completed']
    search_fields = ['title', 'description']
    ordering = ['-created_at']
