# appExam/models.py

import random
from collections import defaultdict
from datetime import timedelta

from ckeditor.fields import RichTextField
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

    def __str__(self):
        halls = " ".join(f"{ha.hall.name}," for ha in self.hall_assignments.all())
        return f"{self.exam} at {self.start_time.strftime('%Y-%m-%d %H:%M')} in {halls}"

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
        return f"{self.hall.name} [{self.roll_number_range}]"


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
        return f"Answer to Q#{self.question.id}"


class StudentExamEnrollment(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE)
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

    def __str__(self):
        return f"{self.candidate.symbol_number} - {self.session}"

    def save(self, *args, **kwargs):
        """
        On initial creation (when self._state.adding is True), we want to:
          1. Fetch all question IDs for this session in one query.
          2. Randomize that list and assign to self.question_order.
          3. Fetch all (question_id, answer_id) pairs in one query, group by question_id.
          4. For each question in the randomized question_order, shuffle its answer IDs and
             store them under answer_order[str(question_id)].
          5. Finally, call super().save() once so that both JSONFields get persisted in a single write.

        Subsequent saves (when updating e.g. hall_assignment or Time_Remaining) do not
        re-shuffle; question_order and answer_order remain intact.
        """  # noqa: E501
        from appExam.models import Answer  # avoid circular import
        from appExam.models import Question  # avoid circular import

        # If this is a brand new instance,
        # populate the two JSONFields before the first save.
        if self._state.adding:
            # 1) Get all question IDs for this session
            question_ids = list(
                Question.objects.filter(session=self.session).values_list(
                    "id",
                    flat=True,
                ),
            )
            random.shuffle(question_ids)
            self.question_order = question_ids

            # 2) Fetch all (question_id, answer_id) in a single query
            all_pairs = Answer.objects.filter(
                question__session=self.session,
            ).values_list("question_id", "id")
            # Group them: { question_id: [answer_id, ...], ... }
            grouped = defaultdict(list)
            for qid, aid in all_pairs:
                grouped[qid].append(aid)

            # 3) For each question in our shuffled question_order, shuffle that questions answers  # noqa: E501
            ao = {}
            for qid in question_ids:
                answer_list = grouped.get(qid, [])
                random.shuffle(answer_list)
                ao[str(qid)] = answer_list

            self.answer_order = ao

            # Now call super().save once, writing question_order & answer_order in one go  # noqa: E501
            super().save(*args, **kwargs)
        else:
            # Just a normal update (don't reshuffle)
            super().save(*args, **kwargs)


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

    def __str__(self):
        if self.selected_answer:
            return f"{self.enrollment.candidate.symbol_number} → Q#{self.question.id}: A#{self.selected_answer.id}"  # noqa: E501
        return f"{self.enrollment.candidate.symbol_number} → Q#{self.question.id}: <unanswered>"  # noqa: E501
