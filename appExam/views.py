import hashlib
from contextlib import contextmanager

from django.core.cache import cache
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


# ------------------------- Cache Management -------------------------
def generate_cache_key(prefix: str, *args) -> str:
    """Generate consistent cache keys with length limits"""
    key_data = f"{prefix}_{'_'.join(str(arg) for arg in args)}"
    if len(key_data) > 200:  # noqa: PLR2004
        return f"{prefix}_{hashlib.md5(key_data.encode()).hexdigest()}"  # noqa: S324
    return key_data


def invalidate_student_answer_caches(enrollment_id: int, question_ids: list[int]):
    """Efficient cache invalidation with minimal DB queries"""
    cache_keys = []

    try:
        enrollment = StudentExamEnrollment.objects.only(
            "question_order",
            "answer_order",
        ).get(id=enrollment_id)
        q_order = enrollment.question_order or []
    except StudentExamEnrollment.DoesNotExist:
        q_order = []

    # Individual question caches
    for qid in question_ids:
        cache_keys.append(generate_cache_key("student_answers", enrollment_id, qid))  # noqa: PERF401

    # Bulk answer caches
    if question_ids:
        sorted_qids = sorted(question_ids)
        cache_keys.append(
            generate_cache_key(
                "student_answers",
                enrollment_id,
                "bulk",
                hash(tuple(sorted_qids)),
            ),
        )

    # Question list caches
    if q_order:
        cache_keys.append(
            generate_cache_key("static_qlist", enrollment_id, hash(tuple(q_order))),
        )
        cache_keys.append(
            generate_cache_key(
                "student_answers",
                enrollment_id,
                "full",
                hash(tuple(q_order)),
            ),
        )

    # Question static caches
    answer_order = enrollment.answer_order if enrollment else {}
    for qid in question_ids:
        randomized_ids = answer_order.get(str(qid), [])
        if randomized_ids:
            cache_keys.append(
                generate_cache_key("q_static", qid, hash(tuple(randomized_ids))),
            )

    if cache_keys:
        cache.delete_many(cache_keys)


# ------------------------- Transaction Handling -------------------------
@contextmanager
def atomic_with_cache_cleanup(cache_keys: list = None):  # noqa: RUF013
    """Atomic operations with automatic cache invalidation"""
    try:
        with transaction.atomic():
            yield
    finally:
        if cache_keys:
            cache.delete_many(cache_keys)


# ------------------------- Data Access Helpers -------------------------
def get_cached_question_count(session_id: int) -> int:
    """Cached question count with validation"""
    cache_key = generate_cache_key("q_count", session_id)
    count = cache.get(cache_key)

    if count is None:
        count = Question.objects.filter(session_id=session_id).count()
        cache.set(cache_key, count, 7200)  # 2 hours

    return count


def get_cached_enrollment_data(user_id: int, enrollment_id: int) -> dict:
    """Optimized enrollment data caching"""
    cache_key = generate_cache_key("enrollment_data", user_id, enrollment_id)
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
                "subject": enrollment.session.exam.subject.name or None,
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


def bulk_get_student_answers(
    enrollment_id: int,
    question_ids: list[int],
) -> dict[int, int]:
    """Optimized student answers with efficient caching"""
    if not question_ids:
        return {}

    sorted_ids = sorted(question_ids)
    cache_key = generate_cache_key(
        "student_answers",
        enrollment_id,
        "bulk",
        hash(tuple(sorted_ids)),
    )

    result = cache.get(cache_key)
    if result is not None:
        return result

    answers = StudentAnswer.objects.filter(
        enrollment_id=enrollment_id,
        question_id__in=question_ids,
        selected_answer_id__isnull=False,
    ).values_list("question_id", "selected_answer_id")

    result = dict(answers)
    cache.set(cache_key, result, 60)  # 1 minute
    return result


def bulk_get_questions_and_answers(
    question_ids: list[int],
    answer_ids: list[int],
) -> tuple[dict, dict]:
    """Memory-efficient bulk fetch with chunking"""
    cache_key = generate_cache_key(
        "qa_bulk",
        hash(tuple(sorted(question_ids + answer_ids))),
    )
    cached = cache.get(cache_key)

    if cached:
        return cached["questions"], cached["answers"]

    CHUNK_SIZE = 100  # noqa: N806
    q_map = {}
    a_map = {}

    for i in range(0, len(question_ids), CHUNK_SIZE):
        chunk = question_ids[i : i + CHUNK_SIZE]
        for q in Question.objects.filter(id__in=chunk).only("id", "text"):
            q_map[q.id] = q

    for i in range(0, len(answer_ids), CHUNK_SIZE):
        chunk = answer_ids[i : i + CHUNK_SIZE]
        for a in Answer.objects.filter(id__in=chunk).only("id", "text"):
            a_map[a.id] = a

    result = {"questions": q_map, "answers": a_map}
    cache.set(cache_key, result, 1800)  # 30 minutes

    return q_map, a_map


# ------------------------- Exam Session Details -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_session_view(request):
    """Optimized session details with proper status handling"""
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
            {"error": "No scheduled exams found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    if enrollment.status == "scheduled":
        return Response(
            {"error": "Exam session has not started", "status": 403},
            status=status.HTTP_403_FORBIDDEN,
        )

    if enrollment.status == "submitted":
        return Response(
            {"error": "Exam already submitted", "status": 409},
            status=status.HTTP_409_CONFLICT,
        )

    cached_data = get_cached_enrollment_data(request.user.id, enrollment.id)
    if not cached_data:
        return Response(
            {"error": "Session data unavailable", "status": 500},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    duration = enrollment.individual_duration
    time_remaining = enrollment.effective_time_remaining

    response_data = {
        **cached_data,
        "start_time": timezone.localtime(enrollment.session_started_at).isoformat()
        if enrollment.session_started_at
        else None,
        "duration_minutes": int(duration.total_seconds() // 60) if duration else None,
        "time_remaining_minutes": int(time_remaining.total_seconds() // 60)
        if time_remaining
        else None,
        "total_questions": get_cached_question_count(enrollment.session.id),
    }

    return Response(
        {"data": response_data, "message": "Exam details retrieved", "status": 200},
    )


# ------------------------- Paginated Questions -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_paginated_questions_view(request):
    """Optimized single question retrieval with caching"""
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
            {"error": "Questions not randomized for candidate", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if page < 1 or page > len(question_order):
        return Response(
            {"error": "Page number out of range", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    question_id = question_order[page - 1]
    randomized_answer_ids = answer_order.get(str(question_id), [])

    static_cache_key = generate_cache_key(
        "q_static",
        question_id,
        hash(tuple(randomized_answer_ids)),
    )
    cached_static_data = cache.get(static_cache_key)

    if not cached_static_data:
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

        answer_letters = ["a", "b", "c", "d"]
        answers_data = [
            {
                "options": a_map[aid].text,
                "answer_number": answer_letters[idx] if idx < 4 else str(idx + 1),  # noqa: PLR2004
            }
            for idx, aid in enumerate(randomized_answer_ids)
            if aid in a_map
        ]

        cached_static_data = {
            "id": question.id,
            "shift_plan_program_id": enrollment.session.exam.program.id,
            "question": question.text,
            "answers": answers_data,
            "randomized_answer_ids": randomized_answer_ids,
        }
        cache.set(static_cache_key, cached_static_data, 1800)

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
                if answer_index < 4  # noqa: PLR2004
                else str(answer_index + 1)
            )
            is_answered = True
        except ValueError:
            pass

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


# ------------------------- Question List -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_question_list_view(request):
    """Optimized question list with caching"""
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
            {"error": "Questions not randomized", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    static_cache_key = generate_cache_key(
        "static_qlist",
        enrollment.id,
        hash(tuple(q_order)),
    )
    cached_static_data = cache.get(static_cache_key)

    if not cached_static_data:
        all_answer_ids = [aid for qid in q_order for aid in a_order.get(str(qid), [])]
        q_map, ans_map = bulk_get_questions_and_answers(q_order, all_answer_ids)

        answer_letters = ["a", "b", "c", "d"]
        cached_static_data = []

        for qid in q_order:
            q = q_map.get(qid)
            if not q:
                continue

            randomized_ids = a_order.get(str(qid), [])
            answers_data = [
                {
                    "options": ans_map[aid].text,
                    "answer_number": answer_letters[idx] if idx < 4 else str(idx + 1),  # noqa: PLR2004
                }
                for idx, aid in enumerate(randomized_ids)
                if aid in ans_map
            ]

            cached_static_data.append(
                {
                    "id": q.id,
                    "question": q.text,
                    "answers": answers_data,
                    "randomized_ids": randomized_ids,
                },
            )

        cache.set(static_cache_key, cached_static_data, 1800)

    student_answer_data = bulk_get_student_answers(enrollment.id, q_order)
    answer_letters = ["a", "b", "c", "d"]

    questions_data = []
    for q_data in cached_static_data:
        qid = q_data["id"]
        randomized_ids = q_data["randomized_ids"]

        student_answer = None
        is_answered = False

        if qid in student_answer_data:
            selected_answer_id = student_answer_data[qid]
            try:
                pos = randomized_ids.index(selected_answer_id)
                student_answer = answer_letters[pos] if pos < 4 else str(pos + 1)  # noqa: PLR2004
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


# ------------------------- Exam Review -------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_review(request):  # noqa: C901
    """Optimized exam review with caching"""
    try:
        candidate = Candidate.objects.get(user=request.user)

        cache_key = generate_cache_key("submitted_enrollment", candidate.id)
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
                cache.set(cache_key, enrollment, 3600)

        if not enrollment:
            return Response(
                {"error": "No submitted exam found", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        institute = enrollment.session.exam.program.institute
        show_submissions = institute.show_student_submissions

        exam_cache_key = generate_cache_key("exam_details", enrollment.session.exam.id)
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
            cache.set(exam_cache_key, exam_details, 7200)

        questions_data = None

        if show_submissions:
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
                            if idx < 4  # noqa: PLR2004
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
                            answer_letters[pos] if pos < 4 else str(pos + 1)  # noqa: PLR2004
                        )

                    questions_data.append(entry)

        return Response(
            {
                "data": {
                    "exam": exam_details,
                    "questions": questions_data,
                },
                "message": "Exam review retrieved",
                "status": 200,
            },
        )

    except Candidate.DoesNotExist:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )


# ------------------------- Submit Answer -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_answer_view(request):  # noqa: PLR0911
    """Secure answer submission with validation and rate limiting"""
    candidate, enrollment = get_candidate_active_enrollment(request.user)

    if not candidate or not enrollment:
        return Response(
            {"error": "Invalid session", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )

    question_id = request.data.get("question_id")
    selected_letter = request.data.get("selected_answer")

    if not question_id:
        return Response(
            {"error": "Question ID required", "status": 400},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cache_keys = [
        generate_cache_key("student_answers", enrollment.id, question_id),
        generate_cache_key("static_qlist", enrollment.id),
    ]

    try:
        with atomic_with_cache_cleanup(cache_keys):
            if selected_letter is None:
                StudentAnswer.objects.filter(
                    enrollment=enrollment,
                    question_id=question_id,
                ).delete()

                return Response(
                    {
                        "data": {"question_id": question_id, "cleared": True},
                        "status": 200,
                    },
                )

            if not Question.objects.filter(
                id=question_id,
                session=enrollment.session,
            ).exists():
                return Response(
                    {"error": "Invalid question", "status": 400},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            answer_order = enrollment.answer_order or {}
            answer_ids = answer_order.get(str(question_id), [])

            if not answer_ids:
                return Response(
                    {"error": "Answer order not available", "status": 400},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                letter_index = ["a", "b", "c", "d"].index(selected_letter.lower())
                answer_id = answer_ids[letter_index]
            except (ValueError, IndexError):
                return Response(
                    {"error": "Invalid answer selection", "status": 400},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not Answer.objects.filter(id=answer_id).exists():
                return Response(
                    {"error": "Invalid answer ID", "status": 400},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            StudentAnswer.objects.update_or_create(
                enrollment=enrollment,
                question_id=question_id,
                defaults={"selected_answer_id": answer_id},
            )

            return Response(
                {
                    "data": {
                        "question_id": question_id,
                        "selected_answer": selected_letter,
                    },
                    "status": 200,
                },
            )

    except Exception as e:  # noqa: BLE001
        return Response(
            {"error": f"Submission failed: {e!s}", "status": 500},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ------------------------- Submit Exam -------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_active_exam(request):
    """Exam submission with comprehensive cleanup"""
    try:
        candidate = Candidate.objects.get(user=request.user)

        enrollment = (
            StudentExamEnrollment.objects.filter(candidate=candidate, status="active")
            .select_related("session")
            .first()
        )

        if not enrollment:
            return Response(
                {"error": "No active exam found", "status": 404},
                status=status.HTTP_404_NOT_FOUND,
            )

        cache_keys = [
            generate_cache_key("enrollment_data", request.user.id, enrollment.id),
            generate_cache_key("submitted_enrollment", candidate.id),
            generate_cache_key("static_qlist", enrollment.id),
        ]

        if enrollment.question_order:
            for qid in enrollment.question_order:
                cache_keys.append(  # noqa: PERF401
                    generate_cache_key("student_answers", enrollment.id, qid),
                )

        with transaction.atomic():
            now = timezone.now()
            enrollment.status = "submitted"
            enrollment.disconnected_at = now
            enrollment.updated_at = now
            enrollment.save(update_fields=["status", "disconnected_at", "updated_at"])

            cache.delete_many(cache_keys)

        return Response({"message": "Exam submitted successfully", "status": 200})

    except Candidate.DoesNotExist:
        return Response(
            {"error": "Candidate profile not found", "status": 404},
            status=status.HTTP_404_NOT_FOUND,
        )
