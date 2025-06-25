# appExam/views.py - Performance Optimized Version

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appAuthentication.models import Candidate
from appExam.models import Answer
from appExam.models import Question
from appExam.models import StudentAnswer
from appExam.models import StudentExamEnrollment

from .utils.active_enrollment import get_candidate_active_enrollment


# ------------------------- Get Exam Session Details -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_session_view(request):
    """
    Get exam session details for the authenticated candidate.
    Returns duration, number of questions, notice, etc.
    """
    candidate, enrollment = get_candidate_active_enrollment(
        request.user,
        require_ongoing=False,
    )

    if not candidate:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not enrollment:
        return Response(
            {"error": "No scheduled exams found for the user", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    session = enrollment.session

    # CRITICAL: Check if session is ongoing
    if enrollment.status != "active":
        return Response(
            {
                "error": "Exam session has not started yet.",
                "status": 422,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    exam = session.exam

    # Use cache for question count if it doesn't change frequently
    cache_key = f"question_count_{session.id}"
    total_questions = cache.get(cache_key)
    if total_questions is None:
        total_questions = Question.objects.filter(session=session).count()
        cache.set(cache_key, total_questions, 3600)  # Cache for 1 hour

    # Calculate duration and time remaining
    duration_minutes = (
        int(enrollment.individual_duration.total_seconds() // 60)
        if enrollment.individual_duration
        else None
    )

    time_remaining = enrollment.effective_time_remaining
    time_remaining_minutes = (
        int(time_remaining.total_seconds() // 60) if time_remaining else None
    )

    # Build response data - all data already loaded via select_related
    session_data = {
        "session_id": session.id,
        "exam_id": exam.id,
        "exam_title": str(exam),
        "program": exam.program.name,
        "subject": exam.subject.name if exam.subject else None,
        "total_marks": exam.total_marks,
        "description": exam.description,
        "start_time": timezone.localtime(enrollment.session_started_at).isoformat()
        if enrollment.session_started_at
        else None,
        "duration_minutes": duration_minutes,
        "time_remaining_minutes": time_remaining_minutes,
        "total_questions": total_questions,
        "notice": session.notice,
        "status": session.status,
        "hall_name": enrollment.hall_assignment.hall.name
        if enrollment.hall_assignment
        else None,
        "seat_range": enrollment.hall_assignment.roll_number_range
        if enrollment.hall_assignment
        else None,
    }

    return Response(
        {
            "data": session_data,
            "message": "Exam session details retrieved successfully",
            "error": None,
            "status": 200,
        },
    )


# ------------------------- Get Paginated Questions -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_paginated_questions_view(request):  # noqa: C901
    """
    Get paginated questions for the authenticated candidate's exam session.
    Optimized with minimal database queries.
    """
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not enrollment:
        return Response(
            {"error": "No scheduled exams found for the user", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get pagination parameters
    page = int(request.GET.get("page", 1))
    page_size = 1

    # Get randomized orders
    question_order = enrollment.question_order
    answer_order = enrollment.answer_order

    if not question_order:
        return Response(
            {"error": "Questions not yet randomized for this candidate", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate page number
    paginator = Paginator(question_order, page_size)
    if page > paginator.num_pages:
        return Response(
            {"error": "Page number out of range", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get single question ID for this page
    page_obj = paginator.get_page(page)
    question_id = page_obj.object_list[0]

    # Single query to get question with prefetch
    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response(
            {"error": "Question not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get randomized answer IDs for this question
    randomized_answer_ids = answer_order.get(str(question_id), [])

    # Bulk fetch answers in one query
    answers = Answer.objects.filter(id__in=randomized_answer_ids)
    answer_map = {ans.id: ans for ans in answers}

    # Build answers in correct order
    answers_data = []
    answer_letters = ["a", "b", "c", "d"]

    for index, answer_id in enumerate(randomized_answer_ids):
        if answer_id in answer_map:
            answers_data.append(
                {
                    "options": answer_map[answer_id].text,
                    "answer_number": answer_letters[index]
                    if index < len(answer_letters)
                    else str(index + 1),
                },
            )

    # Check student's existing answer with single query
    student_answer = None
    is_answered = False

    try:
        student_answer_obj = StudentAnswer.objects.select_related(
            "selected_answer",
        ).get(
            enrollment=enrollment,
            question=question,
        )
        if student_answer_obj.selected_answer:
            selected_answer_id = student_answer_obj.selected_answer.id
            try:
                answer_index = randomized_answer_ids.index(selected_answer_id)
                student_answer = (
                    answer_letters[answer_index]
                    if answer_index < len(answer_letters)
                    else str(answer_index + 1)
                )
                is_answered = True
            except ValueError:
                pass
    except StudentAnswer.DoesNotExist:
        pass

    question_data = {
        "id": question.id,
        "shift_plan_program_id": enrollment.session.exam.program.id,
        "question": question.text,
        "answers": answers_data,
        "student_answer": student_answer,
        "is_answered": is_answered,
    }

    return Response(
        {
            "data": question_data,
            "message": None,
            "error": None,
            "status": 200,
        },
    )


# ------------------------- Get Question List -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_question_list_view(request):
    """
    Get full question list with massive performance optimization.
    Uses bulk queries and efficient data processing.
    """
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate:
        return Response(
            {"error": "Candidate not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not enrollment:
        return Response(
            {"error": "No scheduled exams found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    q_order = enrollment.question_order or []
    a_order = enrollment.answer_order or {}

    if not q_order:
        return Response(
            {"error": "Questions not yet randomized", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # MASSIVE OPTIMIZATION: Single bulk query for all questions
    questions = Question.objects.filter(id__in=q_order).only("id", "text")
    q_map = {q.id: q for q in questions}

    # MASSIVE OPTIMIZATION: Single bulk query for all answers
    all_answer_ids = [aid for qid_str in a_order.values() for aid in qid_str]
    answers = Answer.objects.filter(id__in=all_answer_ids).only("id", "text")
    ans_map = {ans.id: ans for ans in answers}

    # MASSIVE OPTIMIZATION: Single bulk query for all student answers
    student_answers = (
        StudentAnswer.objects.filter(
            enrollment=enrollment,
            question_id__in=q_order,
        )
        .select_related("selected_answer")
        .only("question_id", "selected_answer_id")
    )
    sa_map = {sa.question_id: sa for sa in student_answers}

    answer_letters = ["a", "b", "c", "d"]
    questions_data = []

    # Process all questions in memory (very fast)
    for qid in q_order:
        q = q_map.get(qid)
        if not q:
            continue

        # Build answers for this question
        randomized_ids = a_order.get(str(qid), [])
        answers_data = []

        for idx, aid in enumerate(randomized_ids):
            ans = ans_map.get(aid)
            if ans:
                letter = (
                    answer_letters[idx] if idx < len(answer_letters) else str(idx + 1)
                )
                answers_data.append(
                    {
                        "options": ans.text,
                        "answer_number": letter,
                    },
                )

        # Check student answer
        student_answer = None
        is_answered = False
        sa = sa_map.get(qid)

        if sa and sa.selected_answer_id:
            try:
                pos = randomized_ids.index(sa.selected_answer_id)
                student_answer = (
                    answer_letters[pos] if pos < len(answer_letters) else str(pos + 1)
                )
                is_answered = True
            except ValueError:
                pass

        questions_data.append(
            {
                "id": q.id,
                "question": q.text,
                "answers": answers_data,
                "student_answer": student_answer,
                "is_answered": is_answered,
            },
        )

    return Response(
        {
            "data": questions_data,
            "message": None,
            "error": None,
            "status": 200,
        },
    )


# ------------------------- Submit Answer -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_answer_view(request):  # noqa: PLR0911
    """
    Submit or clear an answer for a question.
    """
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not enrollment:
        return Response(
            {"error": "No scheduled exams found for the user", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    question_id = request.data.get("question_id")
    selected_answer_letter = request.data.get("selected_answer", None)

    if not question_id:
        return Response(
            {"error": "question_id is required", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        question = Question.objects.get(id=question_id)
    except Question.DoesNotExist:
        return Response(
            {"error": "Question not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    # If selected_answer is null → clear answer
    if selected_answer_letter is None:
        deleted, _ = StudentAnswer.objects.filter(
            enrollment=enrollment,
            question=question,
        ).delete()
        return Response(
            {
                "data": {
                    "question_id": question_id,
                    "selected_answer": None,
                    "cleared": bool(deleted),
                },
                "message": "Answer cleared successfully",
                "error": None,
                "status": 200,
            },
        )

    # Proceed with normal answer submission
    answer_order = enrollment.answer_order
    randomized_answer_ids = answer_order.get(str(question_id), [])

    if not randomized_answer_ids:
        return Response(
            {"error": "Answer order not found for this question", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    answer_letters = ["a", "b", "c", "d"]
    try:
        answer_index = answer_letters.index(selected_answer_letter.lower())
        selected_answer_id = randomized_answer_ids[answer_index]
        selected_answer = Answer.objects.get(id=selected_answer_id)
    except (ValueError, IndexError, Answer.DoesNotExist):
        return Response(
            {"error": "Invalid answer selection", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        student_answer, created = StudentAnswer.objects.get_or_create(
            enrollment=enrollment,
            question=question,
            defaults={"selected_answer": selected_answer},
        )

        if not created:
            student_answer.selected_answer = selected_answer
            student_answer.save(update_fields=["selected_answer"])

    return Response(
        {
            "data": {
                "question_id": question_id,
                "selected_answer": selected_answer_letter,
                "submitted_at": student_answer.id,
            },
            "message": "Answer submitted successfully",
            "error": None,
            "status": 200,
        },
    )


# ------------------------- Get Exam Review -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_review(request):
    """
    Returns exam review data for the most recent submitted exam.
    If institute.show_student_submissions = False, student answers are hidden.
    """
    try:
        candidate = Candidate.objects.get(user=request.user)

        enrollment = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
                status="submitted",
            )
            .select_related(
                "session__exam__program__institute",
                "session__exam__subject",
            )
            .order_by("-session__base_start")
            .first()
        )

        if not enrollment:
            return Response(
                {"error": "No submitted exam found", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        institute = enrollment.session.exam.program.institute
        show_submissions = institute.show_student_submissions

        q_order = enrollment.question_order or []
        a_order = enrollment.answer_order or {}

        if not q_order:
            return Response(
                {"error": "Exam data not available", "status": 400},
                status=status.HTTP_400_BAD_REQUEST,
            )

        questions = Question.objects.filter(id__in=q_order)
        q_map = {q.id: q for q in questions}

        all_answer_ids = [aid for qid in q_order for aid in a_order.get(str(qid), [])]
        answers = Answer.objects.filter(id__in=all_answer_ids)
        ans_map = {ans.id: ans for ans in answers}

        sa_map = {}

        questions_data = None

        if show_submissions:
            student_answers = StudentAnswer.objects.filter(
                enrollment=enrollment,
                question_id__in=q_order,
            )
            sa_map = {sa.question_id: sa for sa in student_answers}

            answer_letters = ["a", "b", "c", "d"]
            questions_data = []

            for qid in q_order:
                q = q_map.get(qid)
                if not q:
                    continue

                randomized_ids = a_order.get(str(qid), [])
                answers_data = [
                    {
                        "options": ans_map[aid].text,
                        "answer_number": answer_letters[idx]
                        if idx < len(answer_letters)
                        else str(idx + 1),
                    }
                    for idx, aid in enumerate(randomized_ids)
                    if aid in ans_map
                ]

                entry = {
                    "id": q.id,
                    "question": q.text,
                    "answers": answers_data,
                }

                sa = sa_map.get(qid)
                if sa and sa.selected_answer_id in randomized_ids:
                    pos = randomized_ids.index(sa.selected_answer_id)
                    entry["student_answer"] = (
                        answer_letters[pos]
                        if pos < len(answer_letters)
                        else str(pos + 1)
                    )

                questions_data.append(entry)

        session = enrollment.session
        exam = session.exam
        exam_details = {
            "exam_title": str(exam),
            "program": exam.program.name,
            "subject": exam.subject.name if exam.subject else None,
            "total_marks": exam.total_marks,
            "session_id": session.id,
            "start_time": timezone.localtime(session.base_start).isoformat()
            if session.base_start
            else None,
            "end_time": timezone.localtime(
                session.base_start + enrollment.individual_duration,
            ).isoformat()
            if session.base_start
            else None,
            "submitted_at": timezone.localtime(enrollment.updated_at).isoformat()
            if enrollment.updated_at
            else None,
        }

        return Response(
            {
                "data": {
                    "exam": exam_details,
                    "questions": questions_data,
                },
                "message": "Exam review retrieved successfully",
                "error": None,
                "status": 200,
            },
        )

    except Candidate.DoesNotExist:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )


# ------------------------- complete and send Exam submission -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_active_exam(request):
    """
    Marks the active exam for the candidate as submitted.
    Only allowed if enrollment status is 'active'.
    """
    try:
        candidate = Candidate.objects.get(user=request.user)

        enrollment = (
            StudentExamEnrollment.objects.filter(candidate=candidate, status="active")
            .select_related("session__exam__program__institute")
            .order_by("-session__base_start")
            .first()
        )

        if not enrollment:
            return Response(
                {
                    "error": (
                        "Not an active exam user. You are either disconnected from the server "  # noqa: E501
                        "or have already submitted your exam"
                    ),
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollment.status = "submitted"
        enrollment.present = False
        enrollment.disconnected_at = timezone.now()
        enrollment.save()

        return Response(
            {
                "message": "Exam submitted successfully.",
                "status": 200,
                "error": None,
            },
            status=status.HTTP_200_OK,
        )

    except Candidate.DoesNotExist:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )
