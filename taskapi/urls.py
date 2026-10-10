"""
URL configuration for the taskapi project.

All task API endpoints are mounted under /api/
The Django admin interface is available at /admin/
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Include all URLs defined in tasks/urls.py under the /api/ prefix
    path('api/', include('tasks.urls')),
]
