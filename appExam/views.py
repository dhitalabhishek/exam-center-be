# appExam/views.py - Updated APIs to match expected payload structure

from django.core.paginator import Paginator
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appExam.models import Answer
from appExam.models import Question
from appExam.models import StudentAnswer
from appExam.models import StudentExamEnrollment

from .models import Candidate


# ------------------------- Get Exam Session Details -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_session_view(request):
    """
    Get exam session details for the authenticated candidate.
    Returns duration, number of questions, notice, etc.
    """
    try:
        candidate = Candidate.objects.get(user=request.user)

        # MODIFIED: Get all enrollments and select the earliest ongoing session
        enrollments = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
            )
            .select_related(
                "session",
                "session__exam",
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment",
                "hall_assignment__hall",
            )
            .order_by("session__start_time")
        )

        if not enrollments.exists():
            return Response(
                {"error": "No scheduled exams found for the user", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollment = enrollments.first()

        session = enrollment.session
        exam = session.exam

        if session.status != "ongoing":
            return Response(
                {
                    "error": "Exam session has not started yet.",
                    "status": 422,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Count total questions for this session
        total_questions = Question.objects.filter(session=session).count()

        # Calculate duration
        duration_minutes = None
        if session.start_time and session.end_time:
            duration = session.end_time - session.start_time
            duration_minutes = int(duration.total_seconds() // 60)

        # Get time remaining for this specific candidate
        time_remaining_minutes = None
        if enrollment.time_remaining:
            time_remaining_minutes = int(
                enrollment.time_remaining.total_seconds() // 60,
            )

        # Build response data
        session_data = {
            "session_id": session.id,
            "exam_id": exam.id,
            "exam_title": str(exam),
            "program": exam.program.name,
            "subject": exam.subject.name if exam.subject else None,
            "total_marks": exam.total_marks,
            "description": exam.description,
            "start_time": session.start_time.isoformat()
            if session.start_time
            else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
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

    except Candidate.DoesNotExist:
        return Response(
            {
                "error": "Candidate profile not found",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {
                "error": "No exam enrollment found for this candidate",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )


# ------------------------- Get Paginated Questions -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_paginated_questions_view(request):  # noqa: C901, PLR0911, PLR0912
    """
    Get paginated questions for the authenticated candidate's exam session.
    Questions and answers are returned in the randomized order specific to this candidate.
    Each page contains exactly 1 question.

    Query Parameters:
    - page: Page number (default: 1)
    """
    try:
        candidate = Candidate.objects.get(user=request.user)

        # MODIFIED: Get all enrollments and select the earliest ongoing session
        enrollments = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
            )
            .select_related(
                "session",
                "session__exam",
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment",
                "hall_assignment__hall",
            )
            .order_by("session__start_time")
        )

        if not enrollments.exists():
            return Response(
                {"error": "No scheduled exams found for the user", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollment = enrollments.first()

        if enrollment.session.status != "ongoing":
            return Response(
                {
                    "error": "Exam session has not started yet.",
                    "status": 422,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Get pagination parameters - force page_size to 1
        page = int(request.GET.get("page", 1))
        page_size = 1  # Always 1 question per page

        # Get the randomized question order for this candidate
        question_order = enrollment.question_order
        answer_order = enrollment.answer_order

        if not question_order:
            return Response(
                {
                    "error": "Questions not yet randomized for this candidate",
                    "status": 400,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create paginator with the randomized question IDs
        paginator = Paginator(question_order, page_size)

        if page > paginator.num_pages:
            return Response(
                {
                    "error": "Page number out of range",
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get question ID for the current page (only 1 question)
        page_obj = paginator.get_page(page)
        question_id = page_obj.object_list[0]  # Get the single question ID

        # Fetch the question and its answers
        try:
            question = Question.objects.get(id=question_id)

            # Get randomized answer order for this question
            randomized_answer_ids = answer_order.get(str(question_id), [])

            # Fetch answers in the randomized order
            answers_data = []
            answer_letters = ["a", "b", "c", "d"]  # Standard answer numbering

            for index, answer_id in enumerate(randomized_answer_ids):
                try:
                    answer = Answer.objects.get(id=answer_id)
                    answers_data.append(
                        {
                            "options": answer.text,
                            "answer_number": answer_letters[index]
                            if index < len(answer_letters)
                            else str(index + 1),
                        },
                    )
                except Answer.DoesNotExist:
                    continue

            # Check if student has already answered this question
            student_answer = None
            is_answered = False

            try:
                student_answer_obj = StudentAnswer.objects.get(
                    enrollment=enrollment,
                    question=question,
                )
                if student_answer_obj.selected_answer:
                    # Find which answer letter corresponds to the selected answer
                    selected_answer_id = student_answer_obj.selected_answer.id
                    # Find the position of this answer in the randomized order
                    for index, answer_id in enumerate(randomized_answer_ids):
                        if answer_id == selected_answer_id:
                            student_answer = (
                                answer_letters[index]
                                if index < len(answer_letters)
                                else str(index + 1)
                            )
                            break
                    is_answered = True
            except StudentAnswer.DoesNotExist:
                pass

            # Build the response data matching the expected payload structure
            question_data = {
                "id": question.id,
                "shift_plan_program_id": enrollment.session.exam.program.id,  # Adjust based on your model structure
                "question": question.text,
                "answers": answers_data,
                "student_answer": student_answer,
                "is_answered": is_answered,
            }

        except Question.DoesNotExist:
            return Response(
                {
                    "error": "Question not found",
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Return the response matching the expected payload structure
        return Response(
            {
                "data": question_data,
                "message": None,
                "error": None,
                "status": 200,
            },
        )

    except Candidate.DoesNotExist:
        return Response(
            {
                "error": "Candidate profile not found",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {
                "error": "No exam enrollment found for this candidate",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except ValueError:
        return Response(
            {
                "error": "Invalid page parameter",
                "status": 400,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


# ------------------------- Get Question List -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_question_list_view(request):
    """
    Get a simple list of questions for the authenticated candidate's exam session.
    Returns questions in the randomized order specific to this candidate.

    Returns:
    - List of questions with id and question text only
    """
    try:
        candidate = Candidate.objects.get(user=request.user)

        # MODIFIED: Get all enrollments and select the earliest ongoing session
        enrollments = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
            )
            .select_related(
                "session",
                "session__exam",
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment",
                "hall_assignment__hall",
            )
            .order_by("session__start_time")
        )

        if not enrollments.exists():
            return Response(
                {"error": "No scheduled exams found for the user", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollment = enrollments.first()

        if enrollment.session.status != "ongoing":
            return Response(
                {
                    "error": "Exam session has not started yet.",
                    "status": 422,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Get the randomized question order for this candidate
        question_order = enrollment.question_order

        if not question_order:
            return Response(
                {
                    "error": "Questions not yet randomized for this candidate",
                    "status": 400,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fetch questions in the randomized order
        questions_data = []

        for question_id in question_order:
            try:
                question = Question.objects.get(id=question_id)
                questions_data.append(
                    {
                        "id": question.id,
                        "question": question.text,
                    },
                )
            except Question.DoesNotExist:
                # Skip questions that don't exist
                continue

        # Return the response
        return Response(
            {
                "data": questions_data,
                "message": None,
                "error": None,
                "status": 200,
            },
        )

    except Candidate.DoesNotExist:
        return Response(
            {
                "error": "Candidate profile not found",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {
                "error": "No exam enrollment found for this candidate",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )


# ------------------------- Submit Answer -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_answer_view(request):  # noqa: PLR0911
    """
    Submit an answer for a specific question.

    Expected payload:
    {
        "question_id": 632,
        "selected_answer": "a"
    }
    """
    try:
        candidate = Candidate.objects.get(user=request.user)
        candidate = Candidate.objects.get(user=request.user)

        # MODIFIED: Get all enrollments and select the earliest ongoing session
        enrollments = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
            )
            .select_related(
                "session",
                "session__exam",
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment",
                "hall_assignment__hall",
            )
            .order_by("session__start_time")
        )

        if not enrollments.exists():
            return Response(
                {"error": "No scheduled exams found for the user", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollment = enrollments.first()

        question_id = request.data.get("question_id")
        selected_answer_letter = request.data.get("selected_answer")

        if not question_id or not selected_answer_letter:
            return Response(
                {
                    "error": "question_id and selected_answer are required",
                    "status": 400,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the question
        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return Response(
                {
                    "error": "Question not found",
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get the randomized answer order for this question
        answer_order = enrollment.answer_order
        randomized_answer_ids = answer_order.get(str(question_id), [])

        if not randomized_answer_ids:
            return Response(
                {
                    "error": "Answer order not found for this question",
                    "status": 400,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Convert answer letter to answer ID
        answer_letters = ["a", "b", "c", "d"]
        try:
            answer_index = answer_letters.index(selected_answer_letter.lower())
            selected_answer_id = randomized_answer_ids[answer_index]
            selected_answer = Answer.objects.get(id=selected_answer_id)
        except (ValueError, IndexError, Answer.DoesNotExist):
            return Response(
                {
                    "error": "Invalid answer selection",
                    "status": 400,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create student answer
        student_answer, created = StudentAnswer.objects.get_or_create(
            enrollment=enrollment,
            question=question,
            defaults={"selected_answer": selected_answer},
        )

        if not created:
            # Update existing answer
            student_answer.selected_answer = selected_answer
            student_answer.save()

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

    except Candidate.DoesNotExist:
        return Response(
            {
                "error": "Candidate profile not found",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except StudentExamEnrollment.DoesNotExist:
        return Response(
            {
                "error": "No exam enrollment found for this candidate",
                "status": 404,
            },
            status=status.HTTP_404_NOT_FOUND,
        )
