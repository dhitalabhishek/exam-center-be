from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")
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
    admin_password2 = models.CharField(max_length=128, blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email


class Candidate(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='candidate_profile')
    admit_card_id = models.IntegerField()
    profile_id = models.IntegerField()
    symbol_number = models.CharField(max_length=100, unique=True)
    exam_processing_id = models.IntegerField()
    gender = models.CharField(max_length=10)
    citizenship_no = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    dob_nep = models.CharField(max_length=20)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    level_id = models.IntegerField()
    level = models.CharField(max_length=100)
    program_id = models.IntegerField()
    program = models.CharField(max_length=100)
    generated_password = models.CharField(max_length=128)
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.symbol_number})"
