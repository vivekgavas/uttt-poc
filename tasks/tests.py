"""
Tests for the Task API.

Run with:
    python manage.py test tasks

These tests use Django's test runner, which creates a temporary test database,
runs the tests, then tears the database down. Your real 'uttt' database is
never touched by the test runner.
"""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Task


class TaskCreateTests(APITestCase):
    """Tests for POST /api/tasks/ — creating new tasks."""

    def test_create_task_with_title_only(self):
        """A task can be created with only a title (description is optional)."""
        url = reverse('task-list')
        data = {'title': 'Buy groceries'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Task.objects.count(), 1)
        task = Task.objects.get()
        self.assertEqual(task.title, 'Buy groceries')
        self.assertFalse(task.completed)       # defaults to False
        self.assertEqual(task.description, '') # defaults to empty string

    def test_create_task_with_all_fields(self):
        """A task can be created with title, description, and completed."""
        url = reverse('task-list')
        data = {
            'title': 'Write tests',
            'description': 'Add unit tests to the project',
            'completed': True,
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get()
        self.assertEqual(task.title, 'Write tests')
        self.assertEqual(task.description, 'Add unit tests to the project')
        self.assertTrue(task.completed)

    def test_create_task_response_contains_id_and_created_at(self):
        """The response for a created task includes the auto-generated id and created_at."""
        url = reverse('task-list')
        data = {'title': 'Check response fields'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('id', response.data)
        self.assertIn('created_at', response.data)

    def test_create_task_without_title_fails(self):
        """A task without a title is rejected with 400 Bad Request."""
        url = reverse('task-list')
        data = {'description': 'No title provided'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)

    def test_create_task_with_blank_title_fails(self):
        """A title that is whitespace-only is rejected with 400 Bad Request."""
        url = reverse('task-list')
        data = {'title': '   '}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)

    def test_create_task_title_is_stripped(self):
        """Leading and trailing whitespace is stripped from the title."""
        url = reverse('task-list')
        data = {'title': '  Trimmed title  '}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Trimmed title')

    def test_create_task_title_too_long_fails(self):
        """A title longer than 200 characters is rejected."""
        url = reverse('task-list')
        data = {'title': 'x' * 201}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)


class TaskRetrieveTests(APITestCase):
    """Tests for GET /api/tasks/ and GET /api/tasks/{id}/ — reading tasks."""

    def setUp(self):
        """Create some tasks before each test in this class."""
        self.task1 = Task.objects.create(
            title='First task',
            description='Created in setUp',
        )
        self.task2 = Task.objects.create(
            title='Second task',
            completed=True,
        )

    def test_list_tasks_returns_all_tasks(self):
        """GET /api/tasks/ returns all tasks."""
        url = reverse('task-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_tasks_empty_when_no_tasks(self):
        """GET /api/tasks/ returns an empty list when no tasks exist."""
        Task.objects.all().delete()
        url = reverse('task-list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_retrieve_single_task(self):
        """GET /api/tasks/{id}/ returns the correct task."""
        url = reverse('task-detail', args=[self.task1.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'First task')
        self.assertEqual(response.data['description'], 'Created in setUp')
        self.assertFalse(response.data['completed'])

    def test_retrieve_nonexistent_task_returns_404(self):
        """GET /api/tasks/99999/ returns 404 when the task does not exist."""
        url = reverse('task-detail', args=[99999])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_task_fields_present(self):
        """The task response contains all expected fields."""
        url = reverse('task-detail', args=[self.task1.id])
        response = self.client.get(url)

        expected_fields = {'id', 'title', 'description', 'completed', 'created_at'}
        self.assertEqual(set(response.data.keys()), expected_fields)


class TaskUpdateTests(APITestCase):
    """Tests for PUT and PATCH /api/tasks/{id}/ — updating tasks."""

    def setUp(self):
        self.task = Task.objects.create(title='Original title')

    def test_partial_update_completed_flag(self):
        """PATCH can update just the completed field."""
        url = reverse('task-detail', args=[self.task.id])
        response = self.client.patch(url, {'completed': True}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertTrue(self.task.completed)

    def test_full_update_task(self):
        """PUT replaces all editable fields."""
        url = reverse('task-detail', args=[self.task.id])
        data = {'title': 'Updated title', 'description': 'New description', 'completed': True}
        response = self.client.put(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Updated title')
        self.assertTrue(self.task.completed)


class TaskDeleteTests(APITestCase):
    """Tests for DELETE /api/tasks/{id}/ — deleting tasks."""

    def setUp(self):
        self.task = Task.objects.create(title='To be deleted')

    def test_delete_task(self):
        """DELETE removes the task and returns 204 No Content."""
        url = reverse('task-detail', args=[self.task.id])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Task.objects.count(), 0)

    def test_delete_nonexistent_task_returns_404(self):
        """DELETE on a nonexistent task returns 404."""
        url = reverse('task-detail', args=[99999])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
