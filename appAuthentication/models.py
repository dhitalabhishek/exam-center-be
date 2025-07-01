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
    token_version = models.IntegerField(default=0)
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

    verification_notes = models.CharField(  # noqa: DJ001
        max_length=100,
        blank=True,  # Changed from blank="" to blank=True
        default="",
        null=True,
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

    # Fields that can be null/empty
    admit_card_id = models.IntegerField(null=True, blank=True)
    profile_id = models.IntegerField(null=True, blank=True)
    exam_processing_id = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)  # noqa: DJ001
    citizenship_no = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    last_name = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001

    # REQUIRED FIELDS - Only symbol_number is truly required
    symbol_number = models.CharField(max_length=100, unique=True)

    # Fields with defaults to avoid empty string issues
    first_name = models.CharField(max_length=100, default="", blank=True)
    dob_nep = models.CharField(max_length=20, default="", blank=True)
    email = models.EmailField(default="", blank=True)
    phone = models.CharField(max_length=20, default="", blank=True)
    level_id = models.IntegerField(default=0, blank=True)
    level = models.CharField(max_length=100, default="", blank=True)
    program_id = models.IntegerField(default=0, blank=True)
    program = models.CharField(max_length=100, default="", blank=True)
    generated_password = models.CharField(max_length=128, default="", blank=True)

    # Nullable field as intended
    middle_name = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001

    # Image fields (already correct)
    initial_image = models.ImageField(
        upload_to=image_upload_to_institute,
        blank=True,
        null=True,
    )

    # This is image to be verified
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

    class Meta:
        indexes = [
            models.Index(fields=["symbol_number"]),
            models.Index(fields=["institute", "symbol_number"]),
            models.Index(fields=["verification_status"]),
            models.Index(fields=["exam_status"]),
        ]
        verbose_name = "Candidate"
        verbose_name_plural = "Candidates"

    def __str__(self):
        # Handle cases where names might be empty
        first = self.first_name or "Unknown"
        last = self.last_name or ""
        return f"{first} {last} ({self.symbol_number})".strip()

    def save(self, *args, **kwargs):
        # Clean and validate data before saving
        self.symbol_number = self.symbol_number.strip() if self.symbol_number else ""
        self.email = self.email.strip().lower() if self.email else ""
        self.first_name = self.first_name.strip() if self.first_name else ""

        # Check if generated_password has changed
        password_changed = False
        if self.pk:  # If this is an update (not a new record)
            try:
                old_instance = Candidate.objects.get(pk=self.pk)
                if old_instance.generated_password != self.generated_password:
                    password_changed = True
            except Candidate.DoesNotExist:
                # This shouldn't happen, but handle gracefully
                password_changed = True
        else:  # This is a new record
            password_changed = True

        # Save the candidate first
        super().save(*args, **kwargs)

        # Update the user's password if generated_password changed
        if password_changed and self.generated_password and self.user:
            self.user.set_password(self.generated_password)
            self.user.save()

    def delete(self, *args, **kwargs):
        # Delete linked user first
        if self.user:
            self.user.delete()
        super().delete(*args, **kwargs)
