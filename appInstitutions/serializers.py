# appInstitutions/serializers.py
from rest_framework import serializers

from .models import Institute
from .models import Program
from .models import Subject


class InstituteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institute
        fields = ["id", "name", "email", "description", "created_at", "updated_at"]


class ProgramSerializer(serializers.ModelSerializer):
    institute = InstituteSerializer(read_only=True)

    class Meta:
        model = Program
        fields = [
            "id",
            "name",
            "level",
            "institute",
            "has_subjects",
            "created_at",
            "updated_at",
        ]


class SubjectSerializer(serializers.ModelSerializer):
    program = ProgramSerializer(read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "name", "program", "created_at", "updated_at"]
