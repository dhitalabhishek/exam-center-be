from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models

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
        Subject, on_delete=models.SET_NULL, null=True, blank=True,
    )
    duration_minutes = models.PositiveIntegerField()
    total_marks = models.PositiveIntegerField()
    description = models.TextField(blank=True)

    def __str__(self):
        name = f"{self.program.name}"
        if self.subject:
            name += f" - {self.subject.name}"
        return f"Exam: {name}"

    def clean(self):
        # Validate subject belongs to program
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
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default="scheduled",
    )

    # Roll number range for this session
    roll_number_start = models.CharField(max_length=20)
    roll_number_end = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.exam} at {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    @property
    def end_time(self):
        return self.start_time + timedelta(minutes=self.exam.duration_minutes)


class HallAllocation(models.Model):
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE, related_name="hall_allocations",
    )
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    # For subject-specific exams
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Required if exam has a subject",
    )

    def __str__(self):
        return f"{self.session} in {self.hall.name}"

    def clean(self):
        # Validate subject matches exam's subject
        if self.subject and self.subject != self.session.exam.subject:
            msg = "Subject does not match the exam's subject"
            raise ValidationError(msg)

        # Validate program matches exam's program
        if self.program != self.session.exam.program:
            msg = "Program does not match the exam's program"
            raise ValidationError(msg)


class QuestionSet(models.Model):
    name = models.CharField(max_length=255)
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, null=True, blank=True,
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, null=True, blank=True,
    )
    hall_allocation = models.ForeignKey(
        HallAllocation,
        on_delete=models.CASCADE,
        related_name="question_sets",
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name

    def clean(self):
        # Must be attached to either program or subject
        if not self.program and not self.subject:
            msg = "Question set must be linked to a Program or Subject"
            raise ValidationError(msg)

        # If both set, validate subject belongs to program
        if (
            self.program
            and self.subject
            and self.subject not in self.program.subjects.all()
        ):
            msg = "Subject does not belong to the specified Program"
            raise ValidationError(msg)


class Question(models.Model):
    text = models.TextField()
    question_set = models.ForeignKey(
        QuestionSet,
        on_delete=models.CASCADE,
        related_name="questions",
    )

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
        return f"Answer to Q#{self.question.id}"


class StudentExamEnrollment(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE)
    hall_allocation = models.ForeignKey(HallAllocation, on_delete=models.CASCADE)
    exam_started_at = models.DateTimeField(null=True, blank=True)
    exam_ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"

    def clean(self):
        # Validate student's roll number is in session's range
        if not (
            self.session.roll_number_start
            <= self.candidate.symbol_number
            <= self.session.roll_number_end
        ):
            msg = "Student roll number not in allowed range for this session"
            raise ValidationError(
                msg,
            )
