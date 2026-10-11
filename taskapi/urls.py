"""
URL configuration for the taskapi project.

The Django admin interface is available at /admin/
All UTTT platform endpoints are mounted under /api/
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('uttt.urls')),
]
