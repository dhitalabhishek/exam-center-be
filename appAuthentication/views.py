from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .forms import AdminRegisterForm, DualPasswordAdminLoginForm
from .serializers import CandidateRegistrationSerializer, CandidateLoginSerializer
from .models import Candidate


def admin_register_view(request):
    if request.method == 'POST':
        form = AdminRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Admin registered successfully. You can now log in.')
            return redirect('customadmin:login')
    else:
        form = AdminRegisterForm()
    return render(request, 'custom_admin/register.html', {'form': form})


def custom_admin_login_view(request):
    form = DualPasswordAdminLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.cleaned_data['user']
        login(request, user)
        return redirect('admin:index')
    return render(request, 'custom_admin/login.html', {'form': form})


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


@api_view(['POST'])
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
            "tokens": tokens
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def candidate_login_view(request):
    serializer = CandidateLoginSerializer(data=request.data)
    if serializer.is_valid():
        symbol_number = serializer.validated_data['symbol_number']
        password = serializer.validated_data['password']

        try:
            candidate = Candidate.objects.get(symbol_number=symbol_number)
        except Candidate.DoesNotExist:
            return Response({"error": "Invalid symbol number."}, status=status.HTTP_404_NOT_FOUND)

        user = candidate.user
        if user.check_password(password):
            tokens = get_tokens_for_user(user)
            return Response({
                "message": "Candidate logged in successfully.",
                "tokens": tokens
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid password."}, status=status.HTTP_401_UNAUTHORIZED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

