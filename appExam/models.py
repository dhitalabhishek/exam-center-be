# appExam/models.py
from datetime import timedelta

from ckeditor.fields import RichTextField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from appAuthentication.models import Candidate
from appInstitutions.models import Program
from appInstitutions.models import Subject


class Hall(models.Model):
    name = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


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


class ExamSession(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("ongoing", "Ongoing"),
        ("paused", "Paused"),  # Add paused status
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True)

    # Session-level pause tracking
    pause_started_at = models.DateTimeField(null=True, blank=True)
    total_pause_duration = models.DurationField(default=timedelta(0))
    expected_end_time = models.DateTimeField(null=True, blank=True)

    notice = RichTextField(
        blank=True,
        help_text="Notice for the exam session, can include instructions or important information.",
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="scheduled",
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "start_time"]),
        ]

    def __str__(self):
        local_start = timezone.localtime(self.start_time)
        halls = " ".join(f"{ha.hall.name}," for ha in self.hall_assignments.all())
        return f"{self.exam} at {local_start.strftime('%Y-%m-%d %H:%M')} in {halls}"

    def save(self, *args, **kwargs):
        # Set expected_end_time on first save
        if not self.expected_end_time and self.end_time:
            self.expected_end_time = self.end_time
        super().save(*args, **kwargs)

    @property
    def effective_end_time(self):
        """Calculate end time with pauses accounted for"""
        if self.expected_end_time and self.total_pause_duration:
            return self.expected_end_time + self.total_pause_duration
        return self.end_time

    @property
    def is_session_paused(self):
        """Check if the entire session is paused"""
        return self.status == "paused"

    @property
    def current_session_pause_duration(self):
        """Get current pause duration if session is paused"""
        if self.is_session_paused and self.pause_started_at:
            return timezone.now() - self.pause_started_at
        return timedelta(0)

    @property
    def total_session_pause_duration(self):
        """Get total pause duration including current pause"""
        total = self.total_pause_duration
        if self.is_session_paused and self.pause_started_at:
            total += timezone.now() - self.pause_started_at
        return total

    def pause_session(self):
        """Pause the entire session"""
        if self.status == "ongoing":
            self.pause_started_at = timezone.now()
            self.status = "paused"
            self.save(update_fields=["pause_started_at", "status"])

    def resume_session(self):
        """Resume the paused session"""
        if self.status == "paused" and self.pause_started_at:
            pause_duration = timezone.now() - self.pause_started_at
            self.total_pause_duration += pause_duration
            self.pause_started_at = None
            self.status = "ongoing"
            self.save(
                update_fields=["total_pause_duration", "pause_started_at", "status"]
            )

    @property
    def duration(self) -> timedelta:
        """
        Returns the duration of this exam session as a timedelta.
        If end_time is not set yet, returns None.
        """
        if self.end_time:
            return self.end_time - self.start_time
        return None


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

        local_start = timezone.localtime(self.session.start_time)
        date_str = local_start.strftime("%Y-%m-%d %H:%M")

        return f"{exam_name} on {date_str} at {self.hall.name}"


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


class StudentExamEnrollment(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    session = models.ForeignKey("ExamSession", on_delete=models.CASCADE)

    status = models.CharField(
        max_length=20,
        choices=[
            ("inactive", "Inactive"),
            ("active", "Active"),
            ("submitted", "Submitted"),
        ],
        default="inactive",
    )

    hall_assignment = models.ForeignKey(
        "HallAndStudentAssignment",
        on_delete=models.CASCADE,
        null=True,
    )

    # --- Existing field: will hold a random permutation of question IDs
    question_order = models.JSONField(
        default=list,
        help_text="Randomized list of question IDs assigned to this student.",
    )

    # --- New field: for each question_id,
    #   a randomized list of that question's answer IDs
    answer_order = models.JSONField(
        default=dict,
        help_text=(
            "Maps each question_id (as string) to a randomized list of Answer IDs. "
            "e.g. { '632': [57, 43, 89, 61], '633': [102, 99, 105] }"
        ),
    )

    # Total time allocated for this student
    time_remaining = models.DurationField(
        default=timedelta(minutes=60),
        help_text="Total time allocated for this student in the exam session.",
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    present = models.BooleanField(
        default=False,
        help_text="Is student currently connected via WebSocket?",
    )

    # Timer tracking fields
    is_paused = models.BooleanField(default=False)
    active_exam_time_used = models.DurationField(default=timedelta(0))
    last_active_timestamp = models.DateTimeField(null=True, blank=True)

    # NEW FIELD: Store time remaining when paused
    time_remaining_at_pause = models.DurationField(
        null=True,
        blank=True,
        help_text="Time remaining when the exam was paused. Used to display consistent time during pause.",  # noqa: E501
    )

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"

    @property
    def effective_time_remaining(self):
        """Calculate remaining time - if paused, return stored pause time"""
        if not self.time_remaining:
            return timedelta(0)

        # If paused, return the time that was remaining when pause started
        if self.is_paused and self.time_remaining_at_pause is not None:
            return max(self.time_remaining_at_pause, timedelta(0))

        # If not paused, calculate normally
        # Calculate total time elapsed since session started
        session_elapsed = timezone.now() - self.session.start_time

        # Subtract any previously paused time
        total_paused = self.active_exam_time_used
        if self.last_active_timestamp:
            # Add current active session time
            # current_active = timezone.now() - self.last_active_timestamp
            # Don't subtract current active time, we want total elapsed minus paused time
            actual_elapsed = session_elapsed - total_paused
        else:
            actual_elapsed = session_elapsed - total_paused

        # Calculate remaining time
        remaining = self.time_remaining - actual_elapsed
        remaining = max(remaining, timedelta(0))
        return timedelta(seconds=int(remaining.total_seconds()))

    def get_current_active_time_used(self):
        """Get total time used (excluding current active session if not paused)"""
        return self.active_exam_time_used

    def pause_exam_timer(self):
        """Pause the timer and store the current time remaining"""
        if not self.is_paused:
            # Store current effective time remaining
            self.time_remaining_at_pause = self.effective_time_remaining

            # If we're currently in an active session, add that time to used time
            if self.last_active_timestamp:
                active_duration = timezone.now() - self.last_active_timestamp
                self.active_exam_time_used += active_duration

            self.is_paused = True
            self.last_active_timestamp = timezone.now()  # Mark when pause started
            self.save(
                update_fields=[
                    "is_paused",
                    "last_active_timestamp",
                    "time_remaining_at_pause",
                    "active_exam_time_used",
                ]
            )

    def start_exam_timer(self):
        """Call when student becomes active"""
        if not self.is_paused and not self.last_active_timestamp:
            self.last_active_timestamp = timezone.now()
            # Don't auto-save here, let caller decide what fields to save

    def resume_exam_timer(self):
        """Resume the timer from paused state"""
        if self.is_paused:
            # Update the actual time_remaining to what was stored at pause
            if self.time_remaining_at_pause is not None:
                self.time_remaining = self.time_remaining_at_pause

            self.is_paused = False
            self.time_remaining_at_pause = None  # Clear the pause time
            self.last_active_timestamp = timezone.now()  # Mark resume time
            self.save(
                update_fields=[
                    "is_paused",
                    "last_active_timestamp",
                    "time_remaining_at_pause",
                    "time_remaining",
                ],
            )

    def stop_exam_timer(self):
        """Call when exam ends/submits"""
        if self.last_active_timestamp and not self.is_paused:
            # Add final active time
            active_duration = timezone.now() - self.last_active_timestamp
            self.active_exam_time_used += active_duration

        self.last_active_timestamp = timezone.now()  # Mark when stopped
        self.save(update_fields=["active_exam_time_used", "last_active_timestamp"])

    def get_detailed_status(self):
        """Get detailed status information for debugging."""
        return {
            "status": self.status,
            "is_paused": self.is_paused,
            "time_remaining": self.time_remaining.total_seconds(),
            "time_remaining_at_pause": self.time_remaining_at_pause.total_seconds()
            if self.time_remaining_at_pause
            else None,
            "active_time_used": self.get_current_active_time_used().total_seconds(),
            "effective_time_remaining": self.effective_time_remaining.total_seconds(),
            "last_active_timestamp": self.last_active_timestamp.isoformat()
            if self.last_active_timestamp
            else None,
        }


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
