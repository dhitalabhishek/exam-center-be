from django.utils import timezone

from appExam.models import Candidate
from appExam.models import StudentExamEnrollment


def get_candidate_active_enrollment(user, require_ongoing=True):  # noqa: FBT002
    """Get candidate's active enrollment with optimized queries"""
    try:
        candidate = Candidate.objects.select_related("user").get(user=user)

        now = timezone.now()
        qs = StudentExamEnrollment.objects.select_related(
            "session__exam__program__institute",
            "session__exam__subject",
            "hall_assignment__hall",
            "candidate__user",
        ).filter(candidate=candidate)

        if require_ongoing:
            # Only strictly ongoing sessions
            enrollment = (
                qs.filter(session__status="ongoing")
                .order_by("session__base_start")
                .first()
            )
            return candidate, enrollment

        # require_ongoing=False → three tier fallback

        # 1) Ongoing (status and window)
        ongoing = (
            qs.filter(
                session__status="ongoing",
                session__base_start__lte=now,
                # If you have an end-time field, you could add:
                # session__end_time__gt=now,
            )
            .order_by("session__base_start")
            .first()
        )
        if ongoing:
            return candidate, ongoing

        # 2) Next upcoming
        upcoming = (
            qs.filter(session__base_start__gte=now)
            .order_by("session__base_start")
            .first()
        )
        if upcoming:
            return candidate, upcoming

        # 3) Most recent past
        past = (
            qs.filter(session__base_start__lt=now)
            .order_by("-session__base_start")
            .first()
        )
        return candidate, past  # noqa: TRY300

    except Candidate.DoesNotExist:
        return None, None
