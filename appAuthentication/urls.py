from django.urls import path
from . import views

urlpatterns = [
    # Admin URLs
    path('admin/register/', views.admin_register_view, name='admin_register'),
    path('admin/login/', views.admin_login_view, name='admin_login'),

    # Candidate URLs
    path('candidate/register/', views.candidate_register_view, name='candidate_register'),
    path('candidate/login/', views.candidate_login_view, name='candidate_login'),
]
