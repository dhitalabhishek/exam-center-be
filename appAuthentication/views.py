from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Candidate
from .serializers import AdminLoginSerializer
from .serializers import AdminRegistrationSerializer
from .serializers import CandidateLoginSerializer
from .serializers import CandidateRegistrationSerializer

User = get_user_model()

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }

# ------------------------- Admin Registration -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def admin_register_view(request):
    serializer = AdminRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        tokens = get_tokens_for_user(user)
        return Response({
            "message": "Admin registered successfully.",
            "tokens": tokens,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ------------------------- Admin Login -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def admin_login_view(request):
    serializer = AdminLoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data["user"]
        tokens = get_tokens_for_user(user)
        return Response({
            "message": "Admin logged in successfully.",
            "tokens": tokens,
        }, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ------------------------- Candidate Registration -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_register_view(request):
    serializer = CandidateRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        candidate = serializer.save()
        tokens = get_tokens_for_user(candidate.user)
        return Response({
            "message": "Candidate registered successfully.",
            "symbol_number": candidate.symbol_number,
            "generated_password": candidate.generated_password,
            "tokens": tokens,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ------------------------- Candidate Login -------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def candidate_login_view(request):
    serializer = CandidateLoginSerializer(data=request.data)
    if serializer.is_valid():
        symbol_number = serializer.validated_data["symbol_number"]
        password = serializer.validated_data["password"]

        try:
            candidate = Candidate.objects.get(symbol_number=symbol_number)
        except Candidate.DoesNotExist:
            return Response({"error": "Invalid symbol number."}, status=status.HTTP_404_NOT_FOUND)

        user = candidate.user
        if user.check_password(password):
            tokens = get_tokens_for_user(user)
            return Response({
                "message": "Candidate logged in successfully.",
                "tokens": tokens,
            }, status=status.HTTP_200_OK)
        return Response({"error": "Invalid password."}, status=status.HTTP_401_UNAUTHORIZED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

