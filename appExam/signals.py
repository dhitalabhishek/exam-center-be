from django.db.models import F
from django.db.models.signals import pre_save
from django.dispatch import receiver

from appExam.models import ExamSession


@receiver(pre_save, sender=ExamSession)
def update_enrollment_durations(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        original = ExamSession.objects.get(pk=instance.pk)
        if original.base_duration != instance.base_duration:
            time_diff = instance.base_duration - original.base_duration
            instance.enrollments.update(
                individual_duration=F("individual_duration") + time_diff,
            )
    except ExamSession.DoesNotExist:
        pass
