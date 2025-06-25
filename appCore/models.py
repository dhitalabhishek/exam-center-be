from django.db import models
from django.utils import timezone


class CeleryTask(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("STARTED", "Started"),
        ("RETRY", "Retrying"),
        ("FAILURE", "Failed"),
        ("SUCCESS", "Succeeded"),
    )

    task_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="PENDING")
    progress = models.PositiveSmallIntegerField(default=0)
    message = models.TextField(blank=True)
    result = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "Celery Task"
        verbose_name_plural = "Celery Tasks"

    def __str__(self):
        return f"{self.name} ({self.status})"

    @classmethod
    def get_status_value(cls, key):
        return dict(cls.STATUS_CHOICES).get(key, cls.STATUS_CHOICES[0][0])


class AdminNotification(models.Model):
    text = models.TextField()
    level = models.CharField(
        max_length=20,
        default="info",
    )  # info, success, warning, error
    created_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"[{self.level}] {self.text[:30]}..."
