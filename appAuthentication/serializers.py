from rest_framework import serializers
from .models import Candidate, User
import random, string

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
