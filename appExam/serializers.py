# appExam/serializers.py

from rest_framework import serializers

from appAuthentication.serializers import CandidateSerializer
from appInstitutions.serializers import ProgramSerializer
from appInstitutions.serializers import SubjectSerializer

from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import HallAllocation
from .models import Question
from .models import QuestionSet
from .models import StudentExamEnrollment


class ExamSerializer(serializers.ModelSerializer):
    program = ProgramSerializer()
    subject = SubjectSerializer(required=False)

    class Meta:
        model = Exam
        fields = ["id", "program", "subject", "duration_minutes", "total_marks", "description"]  # noqa: E501

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ["id", "text"]

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ["id", "text", "is_correct"]

class QuestionWithAnswersSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True)

    class Meta:
        model = Question
        fields = ["id", "text", "answers"]

class QuestionSetSerializer(serializers.ModelSerializer):
    questions = QuestionWithAnswersSerializer(many=True)

    class Meta:
        model = QuestionSet
        fields = ["id", "name", "questions"]

class HallAllocationSerializer(serializers.ModelSerializer):
    hall = serializers.StringRelatedField()
    program = ProgramSerializer()
    subject = SubjectSerializer(required=False)
    question_set = QuestionSetSerializer()

    class Meta:
        model = HallAllocation
        fields = ["id", "hall", "program", "subject", "question_set"]

class ExamSessionSerializer(serializers.ModelSerializer):
    exam = ExamSerializer()
    hall_allocations = HallAllocationSerializer(many=True)
    end_time = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ExamSession
        fields = [
            "id", "exam", "start_time", "end_time", "status",
            "roll_number_start", "roll_number_end", "hall_allocations",
        ]

class StudentExamEnrollmentSerializer(serializers.ModelSerializer):
    candidate = CandidateSerializer()
    session = ExamSessionSerializer()
    hall_allocation = HallAllocationSerializer()

    class Meta:
        model = StudentExamEnrollment
        fields = [
            "id", "candidate", "session", "hall_allocation",
            "exam_started_at", "exam_ended_at",
        ]
