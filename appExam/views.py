# appExam/views.py - Add these APIs to your existing views

from django.core.paginator import Paginator
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appExam.models import Answer
from appExam.models import Question
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
        # Get the candidate from the authenticated user
        candidate = Candidate.objects.get(user=request.user)

        # Get the enrollment for this candidate
        enrollment = StudentExamEnrollment.objects.select_related(
            "session",
            "session__exam",
            "session__exam__program",
            "session__exam__subject",
            "hall_assignment",
            "hall_assignment__hall",
        ).get(candidate=candidate)

        session = enrollment.session
        exam = session.exam

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
                enrollment.time_remaining.total_seconds() // 60
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
def get_paginated_questions_view(request):
    """
    Get paginated questions for the authenticated candidate's exam session.
    Questions and answers are returned in the randomized order specific to this candidate.
    Each page contains exactly 1 question.

    Query Parameters:
    - page: Page number (default: 1)
    """
    try:
        # Get the candidate from the authenticated user
        candidate = Candidate.objects.get(user=request.user)

        # Get the enrollment for this candidate
        enrollment = StudentExamEnrollment.objects.select_related("session").get(
            candidate=candidate,
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
            for answer_id in randomized_answer_ids:
                try:
                    answer = Answer.objects.get(id=answer_id)
                    answers_data.append(
                        {
                            "id": answer.id,
                            "text": answer.text,
                            # Don't include is_correct in the response for security
                        }
                    )
                except Answer.DoesNotExist:
                    continue

            question_data = {
                "id": question.id,
                "text": question.text,
                "answers": answers_data,
            }

        except Question.DoesNotExist:
            return Response(
                {
                    "error": "Question not found",
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Build response
        response_data = {
            "question": question_data,  # Single question instead of array
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "total_questions": len(question_order),
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
                "next_page": page + 1 if page_obj.has_next() else None,
                "previous_page": page - 1 if page_obj.has_previous() else None,
            },
        }

        return Response(
            {
                "data": response_data,
                "message": "Question retrieved successfully",
                "error": None,
                "status": 200,
            }
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
