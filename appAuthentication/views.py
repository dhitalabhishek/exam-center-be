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
            {
                "message": "Admin registered successfully.",
                "tokens": tokens,
            },
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
            {
                "message": "Admin logged in successfully.",
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------- Candidate Registration -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_register_view(request):
    """
    Creates a new Candidate + linked User (whose password = dob_nep).
    """
    serializer = CandidateRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        candidate = serializer.save()
        tokens = get_tokens_for_user(candidate.user)
        return Response(
            {
                "message": "Candidate registered successfully.",
                "symbol_number": candidate.symbol_number,
                # Since we removed generated_password, we don't return it here.
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ------------------------- Candidate Login -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_login_view(request):
    """
    1) Expects JSON: { "symbol_number": "<string>", "password": "<dob_nep>" }
    2) Verifies password against Candidate.user
    3) Returns a "data" object with all required fields (including photo, biometric, shift, etc.)
    """
    serializer = CandidateLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    symbol_number = serializer.validated_data["symbol_number"]
    password = serializer.validated_data["password"]

    # 1) Look up Candidate by symbol_number
    try:
        candidate = Candidate.objects.get(symbol_number=symbol_number)
    except Candidate.DoesNotExist:
        return Response(
            {"error": "Invalid symbol number."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # 2) Check password (dob_nep) against linked User
    user = candidate.user
    if not user.check_password(password):
        return Response(
            {"error": "Invalid password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # 3) Build JWT access token
    tokens = get_tokens_for_user(user)
    access_token = tokens["access"]

    # 4) Try to fetch this candidate's current enrollment (if any)
    try:
        enrollment = StudentExamEnrollment.objects.select_related(
            "session",
            "session__exam",  # Select the exam through session
            "session__exam__program",  # Select the program through exam
            "hall_assignment",
            "hall_assignment__hall",  # Select the hall
        ).get(candidate=candidate)

        # Extract exam (shift) information
        exam = enrollment.session.exam
        shift_id = exam.id  # exam.id is the shift_id

        # Extract exam session (shift plan) information
        session = enrollment.session
        shift_plan_id = session.id  # session.id is the shift_plan_id
        shift_plan_program_id = exam.program.program_id  # exam.program.id is the shift_plan_program_id

        # Extract seat_number from hall_assignment.roll_number_range
        seat_number = (
            enrollment.hall_assignment.roll_number_range
            if enrollment.hall_assignment
            else None
        )

        # Extract start_time (HH:MM:SS) and duration (minutes) from session
        if session and session.start_time:
            start_time = session.start_time.strftime("%H:%M:%S")
        else:
            start_time = None

        if session and session.end_time:
            duration = int(
                (session.end_time - session.start_time).total_seconds() // 60,
            )
        else:
            duration = None

    except StudentExamEnrollment.DoesNotExist:
        shift_id = None
        shift_plan_id = None
        shift_plan_program_id = None
        seat_number = None
        start_time = None
        duration = None

    # 5) Build the "data" payload, including image URLs if present
    data = {
        "id": candidate.id,
        "level": {
            "name": candidate.level,
            "id": candidate.level_id,
        },
        "level_id": candidate.level_id,  # integer
        "program": {
            "name": candidate.program,
            "id": candidate.program_id,
        },
        "program_id": candidate.program_id,  # integer
        "shift_id": shift_id,  # This is exam.id
        "shift_plan_id": shift_plan_id,  # This is session.id
        "shift_plan_program_id": shift_plan_program_id,  # This is exam.program.id
        "name": f"{candidate.first_name} {candidate.last_name}",
        "email": candidate.email,
        "phone": candidate.phone,
        "symbol_number": candidate.symbol_number,
        "date_of_birth": candidate.dob_nep,
        "photo": (
            candidate.profile_image.url
            if getattr(candidate, "profile_image", None)
            else None
        ),
        "biometric_image": (
            candidate.biometric_image.url
            if getattr(candidate, "biometric_image", None)
            else None
        ),
        "right_thumb_image": (
            candidate.right_thumb_image.url
            if getattr(candidate, "right_thumb_image", None)
            else None
        ),
        "left_thumb_image": (
            candidate.left_thumb_image.url
            if getattr(candidate, "left_thumb_image", None)
            else None
        ),
        "seat_number": seat_number,
        "start_time": start_time,
        "duration": duration,
        "access_token": access_token,
    }

    return Response(
        {
            "data": data,
            "message": "Success",
            "error": None,
            "status": 200,
        },
        status=status.HTTP_200_OK,
    )
