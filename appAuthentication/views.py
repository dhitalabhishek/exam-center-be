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

