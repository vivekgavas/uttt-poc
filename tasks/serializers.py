from rest_framework import serializers
from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    """
    Converts Task model instances to/from JSON.

    - id and created_at are read-only (set by the database, not by the client)
    - title is required and cannot be blank or whitespace-only
    - description and completed are optional
    """

    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'completed', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_title(self, value):
        """
        Custom validation for the title field.
        Strips surrounding whitespace and rejects blank titles.
        """
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError(
                "Title cannot be blank or contain only whitespace."
            )
        return stripped
