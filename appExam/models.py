import re

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
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="scheduled",
    )

    def __str__(self):
        halls = ", ".join(
            f"{ha.hall.name} ({ha.roll_number_range})"
            for ha in self.hall_assignments.all()
        )
        return f"{self.exam} at {self.start_time.strftime('%Y-%m-%d %H:%M')} in {halls}"


class HallAssignment(models.Model):
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
        return f"{self.hall.name} [{self.roll_number_range}]"

    def get_numeric_roll_range(self):
        """
        Returns the list of all integers between the start and end of the
        roll_number_range, ignoring any nondigit characters.
        e.g. "11ch233 - 11CH244" → [11233, 11234, …, 11244]
        """
        try:
            start_str, end_str = [
                p.strip()
                for p in self.roll_number_range.split(
                    "-" if "-" in self.roll_number_range else "-",  # noqa: RUF034
                )
            ]
        except ValueError:
            msg = "Roll number range must be in the format 'XXX - YYY'"
            # raise ValidationError(msg)  # noqa: B904, ERA001
            start_str = msg
            end_str = msg

        # Remove all non digit characters
        start_num = int(re.sub(r"\D", "", start_str))
        end_num = int(re.sub(r"\D", "", end_str))

        if start_num > end_num:
            msg = "Start of range must be less than or equal to end."
            raise ValidationError(msg)

        # Build and return the full list of numbers
        return list(range(start_num, end_num + 1))

    def clean(self):
        # Just validate the numeric interval makes sense
        _ = self.get_numeric_roll_range()


class QuestionSet(models.Model):
    name = models.CharField(max_length=255)
    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    hall_assignment = models.ForeignKey(
        HallAssignment,
        on_delete=models.CASCADE,
        related_name="question_sets",
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name

    def clean(self):
        if not self.program and not self.subject:
            msg = "Question set must be linked to a Program or Subject"
            raise ValidationError(msg)
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
    hall_assignment = models.ForeignKey(
        HallAssignment,
        on_delete=models.CASCADE,
        null=True,
    )
    Time_Remaining = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"
