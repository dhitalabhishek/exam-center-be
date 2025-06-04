# appExam/views.py

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from appExam.models import StudentExamEnrollment

from .models import Candidate
from .serializers import AdminLoginSerializer
from .serializers import AdminRegistrationSerializer
from .serializers import CandidateLoginSerializer
from .serializers import CandidateRegistrationSerializer

User = get_user_model()


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


# ------------------------- Admin Registration -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def admin_register_view(request):
    serializer = AdminRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        tokens = get_tokens_for_user(user)
        return Response(
            {"message": "Admin registered successfully.", "tokens": tokens},
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------- Admin Login -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def admin_login_view(request):
    serializer = AdminLoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data["user"]
        tokens = get_tokens_for_user(user)
        return Response(
            {"message": "Admin logged in successfully.", "tokens": tokens},
            status=status.HTTP_200_OK,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------- Candidate Registration -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_register_view(request):
    serializer = CandidateRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        candidate = serializer.save()
        tokens = get_tokens_for_user(candidate.user)
        return Response(
            {
                "message": "Candidate registered successfully.",
                "symbol_number": candidate.symbol_number,
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------- Candidate Login -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_login_view(request):
    serializer = CandidateLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    symbol_number = serializer.validated_data["symbol_number"]
    password = serializer.validated_data["password"]

    try:
        candidate = Candidate.objects.get(symbol_number=symbol_number)
    except Candidate.DoesNotExist:
        return Response(
            {"error": "Invalid symbol number."},
            status=status.HTTP_404_NOT_FOUND,
        )

    user = candidate.user
    if not user.check_password(password):
        return Response(
            {"error": "Invalid password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    tokens = get_tokens_for_user(user)
    access_token = tokens["access"]

    data = build_candidate_login_payload(candidate, access_token)
    return Response({"data": data, "message": "Success", "error": None, "status": 200})


# ------------------------- Helper Functions -------------------------
def build_candidate_login_payload(candidate, access_token):
    try:
        enrollment = StudentExamEnrollment.objects.select_related(
            "session",
            "session__exam",
            "session__exam__program",
            "hall_assignment",
            "hall_assignment__hall",
        ).get(candidate=candidate)

        exam = enrollment.session.exam
        session = enrollment.session

        shift_id = exam.id
        shift_plan_id = session.id
        shift_plan_program_id = exam.program.program_id
        seat_number = (
            enrollment.hall_assignment.roll_number_range
            if enrollment.hall_assignment
            else None
        )

        start_time = (
            session.start_time.strftime("%H:%M:%S")
            if session and session.start_time
            else None
        )
        duration = (
            int((session.end_time - session.start_time).total_seconds() // 60)
            if session and session.end_time
            else None
        )

    except StudentExamEnrollment.DoesNotExist:
        shift_id = shift_plan_id = shift_plan_program_id = seat_number = start_time = (
            duration
        ) = None

    return {
        "id": candidate.id,
        "level": {"name": candidate.level, "id": candidate.level_id},
        "level_id": candidate.level_id,
        "program": {"name": candidate.program, "id": candidate.program_id},
        "program_id": candidate.program_id,
        "shift_id": shift_id,
        "shift_plan_id": shift_plan_id,
        "shift_plan_program_id": shift_plan_program_id,
        "name": f"{candidate.first_name} {candidate.last_name}",
        "email": candidate.email,
        "phone": candidate.phone,
        "symbol_number": candidate.symbol_number,
        "date_of_birth": candidate.dob_nep,
        "photo": get_image_url(candidate.profile_image),
        "biometric_image": get_image_url(candidate.biometric_image),
        "right_thumb_image": get_image_url(candidate.right_thumb_image),
        "left_thumb_image": get_image_url(candidate.left_thumb_image),
        "seat_number": seat_number,
        "start_time": start_time,
        "duration": duration,
        "access_token": access_token,
    }


def get_image_url(image_field):
    return image_field.url if getattr(image_field, "url", None) else None
