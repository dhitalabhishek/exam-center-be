# appExam/models.py
import logging
from datetime import timedelta

from ckeditor.fields import RichTextField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from appAuthentication.models import Candidate
from appInstitutions.models import Program
from appInstitutions.models import Subject

logger = logging.getLogger(__name__)


# ======================== Hall Model =========================
class Hall(models.Model):
    name = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


# ======================== Exam Model =========================
class Exam(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    total_marks = models.PositiveIntegerField()
    description = models.TextField(blank=True)

    def __str__(self):
        name = f"{self.program.name}"
        if self.subject:
            name += f" - {self.subject.name}"
        return f"Exam: {name}"

    def clean(self):
        if self.subject and self.subject not in self.program.subjects.all():
            msg = "Subject does not belong to the selected program"
            raise ValidationError(msg)


# ======================== Exam Session Model =========================
class ExamSession(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("ongoing", "Ongoing"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    exam = models.ForeignKey("Exam", on_delete=models.CASCADE)
    base_start = models.DateTimeField(default=timezone.now)
    base_duration = models.DurationField(default=timedelta(minutes=120))
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="scheduled",
    )
    notice = RichTextField(
        blank=True,
        null=True,
        help_text="Important instructions or notices for the exam session",
    )

    # Pause tracking
    pause_start = models.DateTimeField(null=True, blank=True)
    total_paused = models.DurationField(default=timedelta(0))

    # Completion tracking
    completed_at = models.DateTimeField(null=True, blank=True)

    # System fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "base_start"]),
        ]

    def __str__(self):
        return f"{self.exam} - {self.base_start}"

    @property
    def effective_start(self):
        """Actual session start time after delays"""
        return self.base_start + self.total_paused

    @property
    def expected_end(self):
        """Projected end time accounting for pauses"""
        return self.base_start + self.base_duration + self.total_paused

    @property
    def is_active(self):
        return self.status == "ongoing"

    @property
    def is_paused(self):
        return self.status == "paused"

    def clean(self):
        if self.status == "completed" and not self.completed_at:
            msg = "Completion time must be set when marking as completed"
            raise ValidationError(msg)

    def start_session(self):
        if self.status == "scheduled":
            start_time = timezone.now()
            self.status = "ongoing"
            self.save()
            # Activate all student enrollments
            self.enrollments.update(status="active", session_started_at=start_time)
            return True
        return False

    def pause_session(self):
        if self.status == "ongoing":
            self.status = "paused"
            self.pause_start = timezone.now()
            self.save()
            return True
        return False

    def resume_session(self):
        if self.status == "paused" and self.pause_start:
            pause_duration = timezone.now() - self.pause_start
            self.total_paused += pause_duration
            self.status = "ongoing"
            self.pause_start = None
            self.save()
            return True
        return False

    def end_session(self):
        if self.status in ["ongoing", "paused"]:
            self.status = "completed"
            self.completed_at = timezone.now()
            self.save()

            # Submit connected students immediately
            connected = self.enrollments.filter(present=True)
            connected.update(status="submitted")

            # Handle disconnected students
            disconnected = self.enrollments.filter(present=False, status="active")
            for enrollment in disconnected:
                from .tasks import submit_when_time_expires

                submit_when_time_expires.apply_async(
                    (enrollment.id,),
                    countdown=enrollment.effective_time_remaining.total_seconds(),
                )
            return True
        return False


# ============================ Hall Assignment Model ====================
class HallAndStudentAssignment(models.Model):
    session = models.ForeignKey(
        ExamSession,
        on_delete=models.CASCADE,
        related_name="hall_assignments",
    )
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    roll_number_range = models.CharField(
        max_length=100,
        help_text="Format: MG12XX10 - MG12XX20",
    )

    def __str__(self):
        exam = self.session.exam
        exam_name = f"{exam.program.name}"
        if exam.subject:
            exam_name += f" - {exam.subject.name}"

        local_start = timezone.localtime(self.session.base_start)
        date_str = local_start.strftime("%Y-%m-%d %H:%M")

        return f"{exam_name} on {date_str} at {self.hall.name}"


# ===================== Question Model ===============================
class Question(models.Model):
    text = models.TextField()
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "text"],
                name="unique_session_text",
            ),
        ]

    def __str__(self):
        return self.text[:50]


# ======================== Answer Model ========================
class Answer(models.Model):
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    text = models.TextField()
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"Answer to Q#{self.question.id} - {self.text[:50]}"


# ======================== Student Exam Enrollment Model ========================
class StudentExamEnrollment(models.Model):
    STATUS_CHOICES = [
        ("inactive", "Inactive"),
        ("active", "Active"),
        ("paused", "Paused"),
        ("submitted", "Submitted"),
    ]

    hall_assignment = models.ForeignKey(
        HallAndStudentAssignment,
        on_delete=models.CASCADE,
        null=True,
        related_name="enrollments",
    )
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    session = models.ForeignKey(
        ExamSession,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="inactive")

    # Timing management
    session_started_at = models.DateTimeField(null=True, blank=True)
    individual_duration = models.DurationField(default=timedelta(minutes=60))
    connection_start = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_duration = models.DurationField(default=timedelta())

    individual_paused_at = models.DateTimeField(null=True, blank=True)
    individual_paused_duration = models.DurationField(default=timedelta())

    # Connection status
    present = models.BooleanField(default=False)

    # Exam content
    question_order = models.JSONField(default=list)
    answer_order = models.JSONField(default=dict)

    # System fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"

    @property
    def effective_time_remaining(self):
        if not self.session_started_at or self.status not in ["active", "paused"]:
            return timedelta(0)

        base_elapsed = timezone.now() - self.session_started_at

        ongoing_pause = timedelta()
        if self.status == "paused":
            if self.paused_at:
                ongoing_pause += timezone.now() - self.paused_at
            if self.individual_paused_at:
                ongoing_pause += timezone.now() - self.individual_paused_at

        total_pause = (
            self.paused_duration + self.individual_paused_duration + ongoing_pause
        )
        adjusted_elapsed = base_elapsed - total_pause

        return max(self.individual_duration - adjusted_elapsed, timedelta(0))

    @property
    def should_submit(self):
        """Check if time has expired"""
        return self.effective_time_remaining <= timedelta(0)

    def pause(self):
        if self.status == "active":
            self.status = "paused"
            self.paused_at = timezone.now()
            self.save()
            return True
        return False

    def resume(self):
        now = timezone.now()

        # Resume individual pause
        if self.individual_paused_at:
            self.individual_paused_duration += now - self.individual_paused_at
            self.individual_paused_at = None

        # Resume session-level pause
        if self.status == "paused" and self.paused_at:
            self.paused_duration += now - self.paused_at
            self.paused_at = None

        self.status = "active"
        self.save()
        return True

    def handle_connect(self):
        """Simplified: Always treat connection as start/resume"""
        if self.session.status != "ongoing":
            return False

        self.present = True
        self.connection_start = timezone.now()
        self.status = "active"
        self.disconnected_at = None
        self.save()
        return True

    def handle_disconnect(self):
        """Log disconnection time"""
        self.present = False
        self.disconnected_at = timezone.now()
        self.save()
        return True

    def submit_exam(self):
        """Finalize exam submission"""
        if self.status == "active":
            self.status = "submitted"
            self.present = False
            self.save()
            return True
        return False

    def grant_extra_time(self):
        self.individual_duration += self.individual_paused_duration
        self.individual_paused_duration = timedelta()
        self.save()
        return True



# ======================== Student Answer Model ========================
class StudentAnswer(models.Model):
    enrollment = models.ForeignKey(
        StudentExamEnrollment,
        on_delete=models.CASCADE,
        related_name="student_answers",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="student_responses",
    )
    selected_answer = models.ForeignKey(
        Answer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = [
            ("enrollment", "question"),
        ]

        indexes = [
            models.Index(fields=["enrollment", "question"]),
        ]

    def __str__(self):
        if self.selected_answer:
            return f"{self.enrollment.candidate.symbol_number} → Q#{self.question.id}: A#{self.selected_answer.id}"  # noqa: E501
        return f"{self.enrollment.candidate.symbol_number} → Q#{self.question.id}: <unanswered>"  # noqa: E501
