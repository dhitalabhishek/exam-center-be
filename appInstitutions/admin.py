from django.contrib import admin

from .models import Institute
from .models import Program
from .models import Subject


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "created_at")
    search_fields = ("name", "email")


class SubjectInline(admin.TabularInline):
    model = Program.subjects.through
    extra = 1


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "created_at")
    list_filter = ("institute",)
    search_fields = ("name",)
    inlines = [SubjectInline]
    exclude = ("subjects",)  # Subjects managed via inline


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "institute", "credits")
    list_filter = ("institute",)
    search_fields = ("name", "code")
