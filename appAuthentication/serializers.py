from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Candidate

User = get_user_model()


class AdminRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    confirm_password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    confirm_password2 = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["password1"] != data["confirm_password1"]:
            msg = "Password 1 and Confirm Password 1 do not match."
            raise serializers.ValidationError(
                msg,
            )
        if data["password2"] != data["confirm_password2"]:
            msg = "Password 2 and Confirm Password 2 do not match."
            raise serializers.ValidationError(
                msg,
            )
        if data["password1"] == data["password2"]:
            msg = "Password 1 and Password 2 must be different."
            raise serializers.ValidationError(
                msg,
            )
        return data

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password1"],
            is_admin=True,
            is_staff=True,
        )
        user.admin_password2 = validated_data["password2"]
        user.save()
        return user


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password1 = data.get("password1")
        password2 = data.get("password2")

        user = authenticate(username=email, password=password1)
        if not user:
            msg = "Invalid email or password1."
            raise serializers.ValidationError(msg)
        if not user.is_admin:
            msg = "This user is not an admin."
            raise serializers.ValidationError(msg)
        if user.admin_password2 != password2:
            msg = "Password 2 is incorrect."
            raise serializers.ValidationError(msg)

        data["user"] = user
        return data


class CandidateRegistrationSerializer(serializers.ModelSerializer):
    """
    Now uses 'generated_password' instead of 'dob_nep' as the actual password.
    """

    class Meta:
        model = Candidate
        fields = [
            "admit_card_id",
            "profile_id",
            "symbol_number",
            "exam_processing_id",
            "gender",
            "citizenship_no",
            "first_name",
            "middle_name",
            "last_name",
            "dob_nep",
            "email",
            "phone",
            "level_id",
            "level",
            "program_id",
            "program",
            "generated_password",  # <-- new field to accept password
        ]
        extra_kwargs = {
            "generated_password": {"write_only": True},
        }

    def create(self, validated_data):
        """
        Create a User using 'generated_password', then create Candidate.
        """
        password = validated_data.pop("generated_password")

        user = User.objects.create_user(
            email=validated_data["email"],
            password=password,
            is_candidate=True,
        )

        # Create the Candidate with reference to the User and generated_password
        return Candidate.objects.create(
            user=user,
            generated_password=password,
            **validated_data,
        )


class CandidateLoginSerializer(serializers.Serializer):
    """
    Candidates now log in with their 'symbol_number' and 'generated_password'.
    """

    symbol_number = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        symbol_number = data.get("symbol_number")
        password = data.get("password")

        try:
            candidate = Candidate.objects.get(symbol_number=symbol_number)
        except Candidate.DoesNotExist:
            msg = "Invalid symbol number."
            raise serializers.ValidationError(msg)  # noqa: B904

        user = candidate.user
        if not user.check_password(password):
            msg = "Invalid password."
            raise serializers.ValidationError(msg)

        if not getattr(user, "is_candidate", False):
            msg = "This user is not a candidate."
            raise serializers.ValidationError(msg)

        data["user"] = user
        data["candidate"] = candidate
        return data


class CandidateSerializer(serializers.ModelSerializer):
    level = serializers.CharField(source="level", read_only=True)
    program = serializers.CharField(source="program", read_only=True)
    institute = serializers.CharField(source="institute.name", read_only=True)

    class Meta:
        model = Candidate
        fields = [
            "id",
            "admit_card_id",
            "profile_id",
            "symbol_number",
            "exam_processing_id",
            "gender",
            "citizenship_no",
            "first_name",
            "middle_name",
            "last_name",
            "dob_nep",
            "email",
            "phone",
            "level",
            "program",
            "institute",
            "profile_image",
            "address",
            "verification_status",
            "exam_status",
        ]
        extra_kwargs = {
            "profile_image": {"required": False},
            "address": {"required": False},
        }
