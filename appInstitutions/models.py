# appInstitutions/models.py

from django.db import models

from appInstitutions.tasks import delete_institute_and_all_users


class Institute(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=14, blank=True)
    description = models.TextField(blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to="institutes/photos/", blank=True)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):  # noqa: FBT002
        """
        Instead of immediately removing this row,
        1) Enqueue our Celery chain to delete all candidates/users and then delete the institute.
        2) Return, leaving the actual deletion to Celery (in delete_institute_record).
        """
        delete_institute_and_all_users(self.id)
        # Do NOT call super().delete() here. The second task (delete_institute_record)
        # will remove this Institute once all users/candidates are cleaned up.


class Subject(models.Model):
    name = models.CharField(max_length=500)
    code = models.CharField(max_length=50)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="subjects",
        null=True,
        blank=True,
        help_text="If created from program, institute defaults to Program's institute",
    )
    description = models.TextField(blank=True)
    credits = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "institute"],
                name="unique_subject_code_per_institute",
            ),
        ]

    def __str__(self):
        return self.name


class Program(models.Model):
    name = models.CharField(max_length=255)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="programs",
    )
    subjects = models.ManyToManyField(Subject, blank=True, related_name="programs")
    program_id = models.CharField(
        max_length=50,
        help_text="Unique identifier for the program, e.g., 2023",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
