
from rest_framework import serializers

from appAuthentication.serializers import CandidateSerializer
from appInstitutions.serializers import ProgramSerializer
from appInstitutions.serializers import SubjectSerializer

from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import HallAssignment
from .models import Question
from .models import QuestionSet
from .models import StudentExamEnrollment


class ExamSerializer(serializers.ModelSerializer):
    program = ProgramSerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id",
            "program",
            "subject",
            "total_marks",
            "description",
        ]


class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ["id", "text", "is_correct"]


class QuestionWithAnswersSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = ["id", "text", "answers"]


class QuestionSetSerializer(serializers.ModelSerializer):
    questions = QuestionWithAnswersSerializer(
        many=True,
        read_only=True,
        source="questions",
    )

    class Meta:
        model = QuestionSet
        fields = ["id", "name", "questions"]


class HallAssignmentSerializer(serializers.ModelSerializer):
    hall = serializers.StringRelatedField(read_only=True)
    roll_number_range = serializers.CharField(read_only=True)

    # if you want to include question_sets on the assignment detail:
    question_sets = QuestionSetSerializer(
        many=True, read_only=True, source="question_sets",
    )

    class Meta:
        model = HallAssignment
        fields = ["id", "hall", "roll_number_range", "question_sets"]


class ExamSessionSerializer(serializers.ModelSerializer):
    exam = ExamSerializer(read_only=True)
    hall_assignments = HallAssignmentSerializer(
        many=True, read_only=True, source="hall_assignments",
    )

    class Meta:
        model = ExamSession
        fields = [
            "id",
            "exam",
            "start_time",
            "end_time",
            "status",
            "hall_assignments",
        ]


class StudentExamEnrollmentSerializer(serializers.ModelSerializer):
    candidate = CandidateSerializer(read_only=True)
    session = ExamSessionSerializer(read_only=True)
    hall_assignment = HallAssignmentSerializer(read_only=True)

    class Meta:
        model = StudentExamEnrollment
        fields = [
            "id",
            "candidate",
            "session",
            "hall_assignment",
            "Time_Remaining",
        ]
