# utils.py
from django.utils import timezone

from appAuthentication.models import StudentExamEnrollment


def get_closest_enrollment(candidate):
    """
    Return the enrollment that
      1) is currently ongoing (start_time ≤ now < end_time),
      2) or, if none ongoing, the next upcoming one (start_time ≥ now),
      3) or, if none upcoming, the most recently started past one.

    Returns a StudentExamEnrollment instance or None.
    """
    now = timezone.now()
    qs = StudentExamEnrollment.objects.select_related(
        "session",
        "session__exam",
        "session__exam__program",
        "hall_assignment",
        "hall_assignment__hall",
    ).filter(candidate=candidate)

    # 1) Ongoing
    ongoing = (
        qs.filter(
            session__start_time__lte=now,
            session__end_time__gt=now,  # or session__status="ongoing"
        )
        .order_by("session__start_time")
        .first()
    )
    if ongoing:
        return ongoing

    # 2) Upcoming
    upcoming = (
        qs.filter(session__start_time__gte=now).order_by("session__start_time").first()
    )
    if upcoming:
        return upcoming

    # 3) Most recent past
    return (
        qs.filter(session__start_time__lt=now).order_by("-session__start_time").first()
    )
