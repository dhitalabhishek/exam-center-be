from django.utils import timezone

from appExam.models import ExamSession


def get_closest_session():
    """
    Return the ExamSession that is:
    1) Currently ongoing (base_start ≤ now and status in ongoing/paused),
    2) Or, the next scheduled one (base_start ≥ now and status = scheduled),
    3) Or None if nothing matches.
    """
    now = timezone.now()

    # 1) Ongoing
    ongoing = ExamSession.objects.filter(
        base_start__lte=now,
        status__in=["ongoing", "paused"],
    ).order_by("base_start").first()
    if ongoing:
        return ongoing

    # 2) Scheduled
    scheduled = ExamSession.objects.filter(
        base_start__gte=now,
        status="scheduled",
    ).order_by("base_start").first()
    if scheduled:
        return scheduled

    return None
