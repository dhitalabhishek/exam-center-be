from django.core.cache import cache
from django.db import connection
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


# ------------------------- Cache Invalidation Helper -------------------------
def invalidate_student_answer_caches(enrollment_id: int, question_ids: list[int]):
    """Complete cache invalidation for student answers"""
    cache_keys_to_delete = []

    # Get enrollment to build proper cache keys
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)
        q_order = enrollment.question_order or []
    except StudentExamEnrollment.DoesNotExist:
        q_order = []

    # 1. Individual question answer caches
    for qid in question_ids:
        sorted_single = [qid]
        cache_keys_to_delete.append(
            f"student_answers_{enrollment_id}_{len(sorted_single)}_{hash(tuple(sorted_single))}",
        )

    # 2. Bulk answer caches (all possible combinations)
    if question_ids:
        sorted_qids = sorted(question_ids)
        cache_keys_to_delete.append(
            f"student_answers_{enrollment_id}_{len(sorted_qids)}_{hash(tuple(sorted_qids))}",
        )

    # 3. CRITICAL: Clear the static question list cache
    if q_order:
        cache_keys_to_delete.append(
            f"static_qlist_{enrollment_id}_{hash(tuple(q_order))}",
        )

    # 4. Clear full question order cache
    cache_keys_to_delete.append(
        f"student_answers_{enrollment_id}_{len(q_order)}_{hash(tuple(q_order))}",
    )

    # 5. Clear any paginated question caches
    for qid in question_ids:
        # Clear individual question static cache
        enrollment_answer_order = (
            enrollment.answer_order if hasattr(enrollment, "answer_order") else {}
        )
        randomized_answer_ids = enrollment_answer_order.get(str(qid), [])
        if randomized_answer_ids:
            cache_keys_to_delete.append(
                f"q_static_{qid}_{hash(tuple(randomized_answer_ids))}",
            )

    # Delete all cache keys
    if cache_keys_to_delete:
        cache.delete_many(cache_keys_to_delete)


# ------------------------- Cached Data Helpers -------------------------
def get_cached_question_count(session_id: int) -> int:
    """Get question count with aggressive caching"""
    cache_key = f"q_count_{session_id}"
    count = cache.get(cache_key)
    if count is None:
        count = Question.objects.filter(session_id=session_id).count()
        cache.set(cache_key, count, 7200)  # 2 hours cache
    return count


def get_cached_enrollment_data(user_id: int, enrollment_id: int) -> dict | None:
    """Cache enrollment session data for 30 minutes"""
    cache_key = f"enrollment_data_{user_id}_{enrollment_id}"
    data = cache.get(cache_key)
    if data is None:
        try:
            enrollment = StudentExamEnrollment.objects.select_related(
                "session__exam__program__institute",
                "session__exam__subject",
                "hall_assignment__hall",
            ).get(id=enrollment_id)

            data = {
                "session_id": enrollment.session.id,
                "exam_id": enrollment.session.exam.id,
                "exam_title": str(enrollment.session.exam),
                "program": enrollment.session.exam.program.name,
                "subject": enrollment.session.exam.subject.name
                if enrollment.session.exam.subject
                else None,
                "total_marks": enrollment.session.exam.total_marks,
                "description": enrollment.session.exam.description,
                "notice": enrollment.session.notice,
                "status": enrollment.session.status,
                "hall_name": enrollment.hall_assignment.hall.name
                if enrollment.hall_assignment
                else None,
                "seat_range": enrollment.hall_assignment.roll_number_range
                if enrollment.hall_assignment
                else None,
            }
            cache.set(cache_key, data, 1800)  # 30 minutes
        except StudentExamEnrollment.DoesNotExist:
            return None
    return data


# ------------------------- Raw SQL Optimizations -------------------------
def bulk_get_student_answers(
    enrollment_id: int,
    question_ids: list[int],
) -> dict[int, int]:
    """Ultra-fast raw SQL query for student answers with improved caching"""
    if not question_ids:
        return {}

    # Use a more consistent cache key with shorter cache time
    sorted_qids = sorted(question_ids)
    cache_key = (
        f"student_answers_{enrollment_id}_{len(sorted_qids)}_{hash(tuple(sorted_qids))}"
    )
    result = cache.get(cache_key)
    if result is not None:
        return result

    with connection.cursor() as cursor:
        placeholders = ",".join(["%s"] * len(question_ids))
        cursor.execute(
            f"""
            SELECT question_id, selected_answer_id
            FROM "appExam_studentanswer"
            WHERE enrollment_id = %s AND question_id IN ({placeholders})
            AND selected_answer_id IS NOT NULL
        """,  # noqa: S608
            [enrollment_id, *question_ids],
        )

        result = {row[0]: row[1] for row in cursor.fetchall()}
        # Shorter cache time to ensure freshness (1 minute instead of 5)
        cache.set(cache_key, result, 60)
    return result


def bulk_get_questions_and_answers(
    question_ids: list[int],
    answer_ids: list[int],
) -> tuple[dict[int, Question], dict[int, Answer]]:
    """Bulk fetch questions and answers with minimal field selection"""
    cache_key = f"qa_bulk_{hash(tuple(sorted(question_ids + answer_ids)))}"
    cached = cache.get(cache_key)
    if cached:
        return cached["questions"], cached["answers"]

    # Fetch only required fields
    questions = Question.objects.filter(id__in=question_ids).only("id", "text")
    answers = Answer.objects.filter(id__in=answer_ids).only("id", "text")

    q_map = {q.id: q for q in questions}
    a_map = {a.id: a for a in answers}

    cache.set(cache_key, {"questions": q_map, "answers": a_map}, 1800)
    return q_map, a_map


# ------------------------- Get Exam Session Details -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_session_view(request):
    """Ultra-optimized exam session details with aggressive caching"""
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

    # Early status checks
    if enrollment.status != "active":
        return Response(
            {"error": "Exam session has not started yet.", "status": 422},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if enrollment.status == "submitted":
        return Response(
            {"error": "Exam already submitted", "status": 409},
            status=status.HTTP_409_CONFLICT,
        )

    # Use cached enrollment data
    cached_data = get_cached_enrollment_data(request.user.id, enrollment.id)
    if not cached_data:
        return Response(
            {"error": "Session data unavailable", "status": 500},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Cached question count
    total_questions = get_cached_question_count(enrollment.session.id)

    # Time calculations (these are fast property accesses)
    duration_minutes = (
        int(enrollment.individual_duration.total_seconds() // 60)
        if enrollment.individual_duration
        else None
    )

    time_remaining = enrollment.effective_time_remaining
    time_remaining_minutes = (
        int(time_remaining.total_seconds() // 60) if time_remaining else None
    )

    # Merge cached data with time-sensitive data
    session_data = {
        **cached_data,
        "start_time": timezone.localtime(enrollment.session_started_at).isoformat()
        if enrollment.session_started_at
        else None,
        "duration_minutes": duration_minutes,
        "time_remaining_minutes": time_remaining_minutes,
        "total_questions": total_questions,
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
def get_paginated_questions_view(request):
    """Ultra-optimized single question retrieval with fixed caching"""
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate or not enrollment:
        return Response(
            {"error": "Invalid session", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    page = int(request.GET.get("page", 1))
    question_order = enrollment.question_order
    answer_order = enrollment.answer_order

    if not question_order:
        return Response(
            {"error": "Questions not yet randomized for this candidate", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Fast pagination validation
    if page < 1 or page > len(question_order):
        return Response(
            {"error": "Page number out of range", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    question_id = question_order[page - 1]
    randomized_answer_ids = answer_order.get(str(question_id), [])

    # Cache only the static question and answer data (not student answers)
    static_cache_key = f"q_static_{question_id}_{hash(tuple(randomized_answer_ids))}"
    cached_static_data = cache.get(static_cache_key)

    if not cached_static_data:
        # Build static data
        q_map, a_map = bulk_get_questions_and_answers(
            [question_id],
            randomized_answer_ids,
        )

        question = q_map.get(question_id)
        if not question:
            return Response(
                {"error": "Question not found", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Build answers efficiently
        answer_letters = ["a", "b", "c", "d"]
        answers_data = [
            {
                "options": a_map[aid].text,
                "answer_number": answer_letters[idx] if idx < 4 else str(idx + 1),
            }
            for idx, aid in enumerate(randomized_answer_ids)
            if aid in a_map
        ]

        cached_static_data = {
            "id": question.id,
            "shift_plan_program_id": enrollment.session.exam.program.id,
            "question": question.text,
            "answers": answers_data,
            "randomized_answer_ids": randomized_answer_ids,  # Store for student answer lookup
        }

        # Cache static data for longer (30 minutes)
        cache.set(static_cache_key, cached_static_data, 1800)

    # Always fetch fresh student answer data
    student_answer_data = bulk_get_student_answers(enrollment.id, [question_id])
    student_answer = None
    is_answered = False

    if question_id in student_answer_data:
        selected_answer_id = student_answer_data[question_id]
        try:
            answer_index = cached_static_data["randomized_answer_ids"].index(
                selected_answer_id,
            )
            answer_letters = ["a", "b", "c", "d"]
            student_answer = (
                answer_letters[answer_index]
                if answer_index < 4
                else str(answer_index + 1)
            )
            is_answered = True
        except ValueError:
            pass

    # Combine static and dynamic data
    question_data = {
        **{k: v for k, v in cached_static_data.items() if k != "randomized_answer_ids"},
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
    """Hyper-optimized question list with improved caching"""
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate or not enrollment:
        return Response(
            {"error": "Invalid session", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    q_order = enrollment.question_order or []
    a_order = enrollment.answer_order or {}

    if not q_order:
        return Response(
            {"error": "Questions not yet randomized", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Cache static question data separately from student answers
    static_cache_key = f"static_qlist_{enrollment.id}_{hash(tuple(q_order))}"
    cached_static_data = cache.get(static_cache_key)

    if not cached_static_data:
        # Cache miss - build static data
        all_answer_ids = [aid for qid_str in a_order.values() for aid in qid_str]
        q_map, ans_map = bulk_get_questions_and_answers(q_order, all_answer_ids)

        answer_letters = ["a", "b", "c", "d"]
        cached_static_data = []

        # Memory-efficient processing
        for qid in q_order:
            q = q_map.get(qid)
            if not q:
                continue

            randomized_ids = a_order.get(str(qid), [])
            answers_data = [
                {
                    "options": ans_map[aid].text,
                    "answer_number": answer_letters[idx] if idx < 4 else str(idx + 1),
                }
                for idx, aid in enumerate(randomized_ids)
                if aid in ans_map
            ]

            cached_static_data.append(
                {
                    "id": q.id,
                    "question": q.text,
                    "answers": answers_data,
                    "randomized_ids": randomized_ids,  # Store for student answer lookup
                },
            )

        # Cache static data for 30 minutes
        cache.set(static_cache_key, cached_static_data, 1800)

    # Always fetch fresh student answer data
    student_answer_data = bulk_get_student_answers(enrollment.id, q_order)
    answer_letters = ["a", "b", "c", "d"]

    # Combine static and dynamic data
    questions_data = []
    for q_data in cached_static_data:
        qid = q_data["id"]
        randomized_ids = q_data["randomized_ids"]

        # Student answer processing
        student_answer = None
        is_answered = False

        if qid in student_answer_data:
            selected_answer_id = student_answer_data[qid]
            try:
                pos = randomized_ids.index(selected_answer_id)
                student_answer = answer_letters[pos] if pos < 4 else str(pos + 1)
                is_answered = True
            except ValueError:
                pass

        questions_data.append(
            {
                "id": q_data["id"],
                "question": q_data["question"],
                "answers": q_data["answers"],
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
def submit_answer_view(request):
    """Fixed version with proper cache invalidation"""
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate or not enrollment:
        return Response({"error": "Invalid session", "status": 404}, status=404)

    question_id = request.data.get("question_id")
    selected_answer_letter = request.data.get("selected_answer", None)

    if not question_id:
        return Response({"error": "question_id is required", "status": 400}, status=400)

    if not Question.objects.filter(id=question_id).exists():
        return Response({"error": "Question not found", "status": 404}, status=404)

    # CLEAR CACHE BEFORE AND AFTER OPERATION
    invalidate_student_answer_caches(enrollment.id, [question_id])

    # Clear answer case
    if selected_answer_letter is None:
        deleted_count, _ = StudentAnswer.objects.filter(
            enrollment=enrollment,
            question_id=question_id,
        ).delete()

        # Clear cache again after deletion
        invalidate_student_answer_caches(enrollment.id, [question_id])

        return Response(
            {
                "data": {
                    "question_id": question_id,
                    "selected_answer": None,
                    "cleared": bool(deleted_count),
                },
                "message": "Answer cleared successfully",
                "error": None,
                "status": 200,
            },
        )

    # Normal submission logic...
    answer_order = enrollment.answer_order
    randomized_answer_ids = answer_order.get(str(question_id), [])

    if not randomized_answer_ids:
        return Response(
            {"error": "Answer order not found for this question", "status": 400},
            status=400,
        )

    answer_letters = ["a", "b", "c", "d"]
    try:
        answer_index = answer_letters.index(selected_answer_letter.lower())
        selected_answer_id = randomized_answer_ids[answer_index]
    except (ValueError, IndexError):
        return Response(
            {"error": "Invalid answer selection", "status": 400}, status=400,
        )

    if not Answer.objects.filter(id=selected_answer_id).exists():
        return Response(
            {"error": "Invalid answer selection", "status": 400}, status=400,
        )

    # Save answer
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO "appExam_studentanswer" (enrollment_id, question_id, selected_answer_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (enrollment_id, question_id) 
            DO UPDATE SET selected_answer_id = EXCLUDED.selected_answer_id
            """,
            [enrollment.id, question_id, selected_answer_id],
        )

    # CRITICAL: Clear cache again after saving
    invalidate_student_answer_caches(enrollment.id, [question_id])

    return Response(
        {
            "data": {
                "question_id": question_id,
                "selected_answer": selected_answer_letter,
                "submitted_at": True,
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
    """Optimized exam review with smart caching"""
    try:
        candidate = Candidate.objects.get(user=request.user)

        # Cache key for submitted enrollment
        cache_key = f"submitted_enrollment_{candidate.id}"
        enrollment = cache.get(cache_key)

        if not enrollment:
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

            if enrollment:
                cache.set(cache_key, enrollment, 3600)  # 1 hour cache

        if not enrollment:
            return Response(
                {"error": "No submitted exam found", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        institute = enrollment.session.exam.program.institute
        show_submissions = institute.show_student_submissions

        # Cache exam details separately
        exam_cache_key = f"exam_details_{enrollment.session.exam.id}"
        exam_details = cache.get(exam_cache_key)

        if not exam_details:
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
            cache.set(exam_cache_key, exam_details, 7200)  # 2 hours cache

        questions_data = None

        if show_submissions:
            # Use existing optimized question list logic
            q_order = enrollment.question_order or []
            a_order = enrollment.answer_order or {}

            if q_order:
                all_answer_ids = [
                    aid for qid in q_order for aid in a_order.get(str(qid), [])
                ]
                q_map, ans_map = bulk_get_questions_and_answers(q_order, all_answer_ids)
                student_answer_data = bulk_get_student_answers(enrollment.id, q_order)

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
                            if idx < 4
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

                    if (
                        qid in student_answer_data
                        and student_answer_data[qid] in randomized_ids
                    ):
                        pos = randomized_ids.index(student_answer_data[qid])
                        entry["student_answer"] = (
                            answer_letters[pos] if pos < 4 else str(pos + 1)
                        )

                    questions_data.append(entry)

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


# ------------------------- Submit Active Exam -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_active_exam(request):
    """Optimized exam submission with cache cleanup"""
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
                        "Not an active exam user. You are either disconnected from the server "
                        "or have already submitted your exam"
                    ),
                    "status": 404,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Efficient update with specific fields
        now = timezone.now()
        StudentExamEnrollment.objects.filter(id=enrollment.id).update(
            status="submitted",
            present=False,
            disconnected_at=now,
            updated_at=now,
        )

        # Cleanup related caches
        cache_keys_to_delete = [
            f"enrollment_data_{request.user.id}_{enrollment.id}",
            f"submitted_enrollment_{candidate.id}",
            f"static_qlist_{enrollment.id}_{hash(tuple(enrollment.question_order or []))}",
        ]
        cache.delete_many(cache_keys_to_delete)

        # Clear all student answer caches for this enrollment
        if enrollment.question_order:
            invalidate_student_answer_caches(enrollment.id, enrollment.question_order)

        return Response(
            {
                "message": "Exam submitted successfully.",
                "status": 200,
                "error": None,
            },
        )

    except Candidate.DoesNotExist:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )
