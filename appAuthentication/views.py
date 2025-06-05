from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from rest_framework.decorators import api_view, permission_classes

from rest_framework.response import Response

from appExam.models import Answer
from appExam.models import Question
from appExam.models import StudentExamEnrollment

from .models import Candidate
from .serializers import AdminLoginSerializer
from .serializers import AdminRegistrationSerializer
from .serializers import CandidateLoginSerializer
from .serializers import CandidateRegistrationSerializer

from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .forms import AdminRegisterForm, DualPasswordAdminLoginForm



import random
from collections import defaultdict

from django.contrib.auth import get_user_model
User = get_user_model()


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }




def admin_register_view(request):
    if request.method == 'POST':
        form = AdminRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Admin registered successfully. You can now log in.')
            return redirect('customadmin:login')
    else:
        form = AdminRegisterForm()
    return render(request, 'custom_admin/register.html', {'form': form})


def custom_admin_login_view(request):
    form = DualPasswordAdminLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.cleaned_data['user']
        login(request, user)
        return redirect('admin:index')
    return render(request, 'custom_admin/login.html', {'form': form})



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
    try:
        enrollment = StudentExamEnrollment.objects.select_related(
            "session",
            "session__exam",
            "session__exam__program",
            "hall_assignment",
            "hall_assignment__hall",
        ).get(candidate=candidate)
    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {"error": "You are not enrolled in any exam session."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # If enrollment exists but questions haven't been randomized yet, do it now
    if not enrollment.question_order or not enrollment.answer_order:
        randomize_questions_and_answers_for_enrollment(enrollment)
        enrollment.save()

    tokens = get_tokens_for_user(user)
    access_token = tokens["access"]

    data = build_candidate_login_payload(candidate, access_token)
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


def build_candidate_login_payload(candidate, access_token):
    """
    Build the response payload for successful candidate login.
    """
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
        "photo": get_image_url("candidate.profile_image"),
        "biometric_image": get_image_url("candidate.biometric_image"),
        "right_thumb_image": get_image_url("candidate.right_thumb_image"),
        "left_thumb_image": get_image_url("candidate.left_thumb_image"),
        "seat_number": seat_number,
        "start_time": start_time,
        "duration": duration,
        "access_token": access_token,
    }


def get_image_url(image_field):
    return image_field.url if getattr(image_field, "url", None) else None
