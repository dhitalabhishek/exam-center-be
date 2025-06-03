# appExam/views.py

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ExamSession
from .models import StudentExamEnrollment
from .serializers import ExamSessionSerializer
from .serializers import HallAndStudentAssignmentSerializer
from .serializers import StudentExamEnrollmentSerializer


@extend_schema(
    responses=ExamSessionSerializer(many=True),
    description=(
        "List all upcoming exam sessions with their hall assignments "
        "and roll number ranges"
    ),
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def upcoming_sessions(request):
    """
    GET /api/events/upcoming/
    Returns all ExamSession instances whose start_time is today or later,
    including each session's halls and roll number ranges.
    """
    now = timezone.now()
    qs = (
        ExamSession.objects.filter(start_time__gte=now)
        .select_related("exam__program", "exam__subject")
        .prefetch_related("hall_assignments__hall")
        .order_by("start_time")
    )
    serializer = ExamSessionSerializer(qs, many=True)
    return Response(serializer.data)


@extend_schema(
    responses=HallAndStudentAssignmentSerializer,
    description="Get exam session and hall assignment for a particular student",
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_exam_details(request, student_id):
    """
    GET /api/events/student/{student_id}/
    Returns the ExamSession and specific HallAndStudentAssignment for a student.
    """
    try:
        enrollment = StudentExamEnrollment.objects.select_related(
            "session__exam__program",
            "session__exam__subject",
            "hall_assignment__hall",
        ).get(candidate__id=student_id)
    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {"detail": "No exam enrollment found for this student."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        {
            "session": ExamSessionSerializer(enrollment.session).data,
            "hall_assignment": HallAndStudentAssignmentSerializer(
                enrollment.hall_assignment,
            ).data,
        },
    )


@extend_schema(
    responses=StudentExamEnrollmentSerializer,
    description=(
        "Get complete exam details for a student including questions and answers"
    ),
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_full_exam_details(request, student_id):
    """
    GET /api/events/student-full/{student_id}/
    Returns the full ExamSession, HallAndStudentAssignment, Questions,
    and Answers for a student's enrollment.
    """
    try:
        enrollment = (
            StudentExamEnrollment.objects.select_related(
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment__hall",
            )
            .get(candidate__id=student_id)
        )
    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {"detail": "No exam enrollment found for this student."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = StudentExamEnrollmentSerializer(enrollment)
    return Response(serializer.data)
