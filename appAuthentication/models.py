from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from appInstitutions.models import Institute


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            msg = "The Email field must be set."
            raise ValueError(msg)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_admin", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    is_staff = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    is_candidate = models.BooleanField(default=False)

    # Store second admin password (optional)
    admin_password2 = models.CharField(max_length=128, blank=True, null=True)  # noqa: DJ001

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email


class Candidate(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")

    class ExamStatus(models.TextChoices):
        ABSENT = "absent", _("Absent")
        PRESENT = "present", _("Present")
        COMPLETED = "completed", _("Completed")

    verification_status = models.CharField(
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    exam_status = models.CharField(
        max_length=10,
        choices=ExamStatus.choices,
        default=ExamStatus.ABSENT,
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
    )
    admit_card_id = models.IntegerField()
    profile_id = models.IntegerField()
    symbol_number = models.CharField(max_length=100, unique=True)
    exam_processing_id = models.IntegerField()
    gender = models.CharField(max_length=10)
    citizenship_no = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    last_name = models.CharField(max_length=100)
    dob_nep = models.CharField(max_length=20)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    level_id = models.IntegerField()
    level = models.CharField(max_length=100)
    program_id = models.IntegerField()
    program = models.CharField(max_length=100)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="candidates",
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.symbol_number})"
