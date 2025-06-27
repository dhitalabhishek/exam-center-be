from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from appAuthentication.utils.upload_to_institute import fingerprint_upload_to_institute
from appAuthentication.utils.upload_to_institute import image_upload_to_institute
from appInstitutions.models import Institute


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            msg = "The Email field must be set."
            raise ValueError(msg)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
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
    admin_password2 = models.CharField(max_length=128, blank=True, null=True)  # noqa: DJ001

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    def set_admin_password2(self, raw_password):
        """
        Securely sets the admin second password using Django's password hasher.
        """
        self.admin_password2 = make_password(raw_password)

    def check_admin_password2(self, raw_password):
        """
        Checks if the given password matches the stored admin_password2.
        """
        if not self.admin_password2:
            return False
        return check_password(raw_password, self.admin_password2)


class Candidate(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")

    class ExamStatus(models.TextChoices):
        ABSENT = "absent", _("Absent")
        PRESENT = "present", _("Present")

    verification_status = models.CharField(
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    verification_notes = models.CharField(
        max_length=100,
        blank="",
        default="",
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
    generated_password = models.CharField(max_length=128)
    initial_image = models.ImageField(
        upload_to=image_upload_to_institute,
        blank=True,
        null=True,
    )

    # this is image to be verified
    profile_image = models.ImageField(
        upload_to=image_upload_to_institute,
        blank=True,
        null=True,
    )
    fingerprint_left = models.ImageField(
        upload_to=fingerprint_upload_to_institute,
        blank=True,
        null=True,
    )
    fingerprint_right = models.ImageField(
        upload_to=fingerprint_upload_to_institute,
        blank=True,
        null=True,
    )

    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="candidates",
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.symbol_number})"

    def delete(self, *args, **kwargs):
        # delete linked user first
        if self.user:
            self.user.delete()
        super().delete(*args, **kwargs)
