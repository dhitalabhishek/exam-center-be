from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from .models import Candidate
import random
import string

User = get_user_model()

class AdminRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    confirm_password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    confirm_password2 = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['password1'] != data['confirm_password1']:
            raise serializers.ValidationError("Password 1 and Confirm Password 1 do not match.")
        if data['password2'] != data['confirm_password2']:
            raise serializers.ValidationError("Password 2 and Confirm Password 2 do not match.")
        if data['password1'] == data['password2']:
            raise serializers.ValidationError("Password 1 and Password 2 must be different.")
        return data

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password1'],
            is_admin=True,
            is_staff=True
        )
        user.admin_password2 = validated_data['password2']
        user.save()
        return user



class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password1 = serializers.CharField()
    password2 = serializers.CharField()

    def validate(self, data):
        email = data.get('email')
        password1 = data.get('password1')
        password2 = data.get('password2')

        user = authenticate(username=email, password=password1)
        if not user:
            raise serializers.ValidationError("Invalid email or password1.")

        if not user.is_admin:
            raise serializers.ValidationError("This user is not an admin.")

        if user.admin_password2 != password2:
            raise serializers.ValidationError("Password 2 is incorrect.")

        data['user'] = user
        return data


class CandidateRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = [
            'admit_card_id', 'profile_id', 'symbol_number', 'exam_processing_id', 'gender',
            'citizenship_no', 'first_name', 'middle_name', 'last_name', 'dob_nep',
            'email', 'phone', 'level_id', 'level', 'program_id', 'program'
        ]

    def create(self, validated_data):
        random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user = User.objects.create_user(
            email=validated_data['email'],
            password=random_password,
            is_candidate=True
        )
        candidate = Candidate.objects.create(
            user=user,
            generated_password=random_password,
            **validated_data
        )
        return candidate


class CandidateLoginSerializer(serializers.Serializer):
    symbol_number = serializers.CharField()
    password = serializers.CharField()
