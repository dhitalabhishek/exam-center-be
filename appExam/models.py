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
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True)

    pause_started_at = models.DateTimeField(null=True, blank=True)
    total_pause_duration = models.DurationField(default=timedelta(0))
    expected_end_time = models.DateTimeField(null=True, blank=True)

    notice = RichTextField(
        blank=True,
        help_text="Notice for the exam session, can include\
            instructions or important information.",
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
        halls = " ".join(f"{ha.hall.name}," for ha in self.hall_assignments.all())
        return f"{self.exam} at {self.start_time.strftime('%Y-%m-%d %H:%M')} in {halls}"

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
        date_str = self.session.start_time.strftime("%Y-%m-%d %H:%M")
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
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE)

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
        HallAndStudentAssignment,
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

    # We no longer store student_answers here;
    # instead we use a separate StudentAnswer model
    time_remaining = models.DurationField(
        default=timedelta(minutes=60),
        help_text="Time remaining for this student in the exam session.",
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    is_paused = models.BooleanField(default=False)
    pause_started_at = models.DateTimeField(null=True, blank=True)
    total_pause_duration = models.DurationField(default=timedelta(0))
    last_activity = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"

    @property
    def effective_time_remaining(self):
        """Calculate time remaining with pauses"""
        if not self.session.start_time or not self.time_remaining:
            return timedelta(0)

        base_remaining = self.time_remaining
        now = timezone.now()

        # Subtract session pauses
        if self.session.total_pause_duration:
            base_remaining -= self.session.total_pause_duration

        # Subtract current session pause
        if self.session.pause_started_at:
            base_remaining -= now - self.session.pause_started_at

        # Subtract student pauses
        if self.total_pause_duration:
            base_remaining -= self.total_pause_duration

        # Subtract current student pause
        if self.is_paused and self.pause_started_at:
            base_remaining -= now - self.pause_started_at

        return max(base_remaining, timedelta(0))


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
