import logging
import random
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from appExam.models import Answer
from appExam.models import Question
from appExam.models import StudentExamEnrollment

from .models import Candidate
from .serializers import CandidateLoginSerializer
from .serializers import CandidateRegistrationSerializer
from .utils.closest_enrollment import get_closest_enrollment
from .utils.closest_session import get_closest_session
from .utils.tokens import get_tokens_for_user

User = get_user_model()
logger = logging.getLogger(__name__)


# def get_tokens_for_user(user):
#     refresh = RefreshToken.for_user(user)
#     return {
#         "refresh": str(refresh),
#         "access": str(refresh.access_token),
#     }


# ==========================================================
@api_view(["GET"])
@permission_classes([AllowAny])
def closest_session_view(request):
    session = get_closest_session()

    if session:
        exam = session.exam
        program = exam.program
        institute = program.institute

        return Response(
            {
                "session_id": session.id,
                "start_time": session.base_start,
                "status": session.status,
                "program_id": program.id,
                "program_name": program.name,
                "institute_name": institute.name,
                "institute_logo": institute.logo.url if institute.logo else None,
            },
        )

    return Response({"message": "No session found"}, status=status.HTTP_204_NO_CONTENT)


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

    # Check if candidate has enrollment - if not, they can't login
    enrollment = get_closest_enrollment(candidate)
    if not enrollment:
        return Response(
            {"error": "You are not enrolled in any exam session."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    if enrollment.status == "submitted":
        return Response(
            {"error": "Session already Submitted."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # If enrollment exists but questions haven't been randomized yet, do it now
    if not enrollment.question_order or not enrollment.answer_order:
        randomize_questions_and_answers_for_enrollment(enrollment)
        enrollment.save()

    tokens = get_tokens_for_user(user)
    access_token = tokens["access"]

    data = build_candidate_login_payload(candidate, access_token, enrollment)
    return Response({"data": data, "message": "Success", "error": None, "status": 200})


# ------------------------- Helper Functions -------------------------
def randomize_questions_and_answers_for_enrollment(enrollment):
    """
    Randomize questions and answers for an existing enrollment.
    This happens only once when the candidate first logs in successfully.
    """
    session = enrollment.session

    # 1) Get all question IDs for this session
    question_ids = list(
        Question.objects.filter(session=session).values_list("id", flat=True),
    )
    random.shuffle(question_ids)
    enrollment.question_order = question_ids

    # 2) Fetch all (question_id, answer_id) in a single query
    all_pairs = Answer.objects.filter(
        question__session=session,
    ).values_list("question_id", "id")

    # Group them: { question_id: [answer_id, ...], ... }
    grouped = defaultdict(list)
    for qid, aid in all_pairs:
        grouped[qid].append(aid)

    # 3) For each question in our shuffled question_order, shuffle that question's answers  # noqa: E501
    answer_order = {}
    for qid in question_ids:
        answer_list = grouped.get(qid, [])
        random.shuffle(answer_list)
        answer_order[str(qid)] = answer_list

    enrollment.answer_order = answer_order


def build_candidate_login_payload(candidate, access_token, enrollment):
    """
    Build the response payload for successful candidate login.
    """
    try:
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
            timezone.localtime(session.base_start).isoformat()
            if session and session.base_start
            else None
        )

        duration = session.base_duration if session and session.base_duration else None

    except StudentExamEnrollment.DoesNotExist:
        shift_id = shift_plan_id = shift_plan_program_id = seat_number = start_time = (  # noqa: F841
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
        "institute": {
            "name": candidate.institute.name,
            "image": get_image_url(candidate.institute.logo),
        },
        "photo": get_image_url("candidate.initial_image"),
        "biometric_image": get_image_url("candidate.profile_image"),
        # "seat_number": seat_number,``
        "start_time": start_time,
        "duration": duration,
        "access_token": access_token,
    }


def get_image_url(image_field):
    if not image_field:
        return None
    try:
        return image_field.url
    except:  # noqa: E722
        # Handles cases where ImageField exists but no file is attached
        return None
