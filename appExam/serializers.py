from rest_framework import serializers

from appAuthentication.serializers import CandidateSerializer
from appInstitutions.serializers import ProgramSerializer
from appInstitutions.serializers import SubjectSerializer

from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import Hall
from .models import HallAndStudentAssignment
from .models import Question
from .models import StudentAnswer
from .models import StudentExamEnrollment


class HallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hall
        fields = ["id", "name", "capacity", "location"]


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


class HallAndStudentAssignmentSerializer(serializers.ModelSerializer):
    hall = HallSerializer(read_only=True)
    hall_name = serializers.CharField(source="hall.name", read_only=True)

    class Meta:
        model = HallAndStudentAssignment
        fields = ["id", "hall", "hall_name", "roll_number_range"]


class ExamSessionSerializer(serializers.ModelSerializer):
    exam = ExamSerializer(read_only=True)
    hall_assignments = HallAndStudentAssignmentSerializer(
        many=True,
        read_only=True,
    )
    duration = serializers.ReadOnlyField()

    class Meta:
        model = ExamSession
        fields = [
            "id",
            "exam",
            "start_time",
            "end_time",
            "notice",
            "status",
            "duration",
            "hall_assignments",
        ]


class StudentAnswerSerializer(serializers.ModelSerializer):
    question = serializers.PrimaryKeyRelatedField(read_only=True)
    selected_answer = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = StudentAnswer
        fields = ["id", "question", "selected_answer"]


class StudentExamEnrollmentSerializer(serializers.ModelSerializer):
    candidate = CandidateSerializer(read_only=True)
    session = ExamSessionSerializer(read_only=True)
    hall_assignment = HallAndStudentAssignmentSerializer(read_only=True)
    student_answers = StudentAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = StudentExamEnrollment
        fields = [
            "id",
            "candidate",
            "session",
            "hall_assignment",
            "question_order",
            "answer_order",
            "student_answers",
        ]


class StudentExamEnrollmentDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for student exam enrollment that includes
    questions and answers in the randomized order specific to this student.
    """
    candidate = CandidateSerializer(read_only=True)
    session = ExamSessionSerializer(read_only=True)
    hall_assignment = HallAndStudentAssignmentSerializer(read_only=True)
    questions_with_answers = serializers.SerializerMethodField()
    student_answers = StudentAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = StudentExamEnrollment
        fields = [
            "id",
            "candidate",
            "session",
            "hall_assignment",
            "questions_with_answers",
            "student_answers",
        ]

    def get_questions_with_answers(self, obj):
        """
        Returns questions in the randomized order for this student,
        with answers also in randomized order.
        """
        questions_data = []

        # Get questions in the student's randomized order
        for question_id in obj.question_order:
            try:
                question = Question.objects.get(id=question_id)
                question_data = {
                    "id": question.id,
                    "text": question.text,
                    "answers": [],
                }

                # Get answers in the student's randomized order for this question
                answer_ids = obj.answer_order.get(str(question_id), [])
                for answer_id in answer_ids:
                    try:
                        answer = Answer.objects.get(id=answer_id)
                        # Don't expose is_correct to students during exam
                        answer_data = {
                            "id": answer.id,
                            "text": answer.text,
                        }
                        question_data["answers"].append(answer_data)
                    except Answer.DoesNotExist:
                        continue

                questions_data.append(question_data)
            except Question.DoesNotExist:
                continue

        return questions_data


class StudentExamEnrollmentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating student exam enrollments.
    """
    class Meta:
        model = StudentExamEnrollment
        fields = [
            "candidate",
            "session",
            "hall_assignment",
        ]

    def validate(self, data):
        """
        Validate that the candidate is not already enrolled in this session.
        """
        candidate = data.get("candidate")
        session = data.get("session")

        if StudentExamEnrollment.objects.filter(
            candidate=candidate,
            session=session,
        ).exists():
            raise serializers.ValidationError(
                "Student is already enrolled in this exam session.",
            )

        return data


class StudentAnswerCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating student answers during exam.
    """
    class Meta:
        model = StudentAnswer
        fields = ["enrollment", "question", "selected_answer"]

    def validate(self, data):
        """
        Validate that the answer belongs to the question.
        """
        question = data.get("question")
        selected_answer = data.get("selected_answer")

        if selected_answer and selected_answer.question != question:
            raise serializers.ValidationError(
                "Selected answer does not belong to the specified question.",
            )

        return data
