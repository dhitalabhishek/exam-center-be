from django.contrib import admin

from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import Hall
from .models import HallAllocation
from .models import Question
from .models import QuestionSet
from .models import StudentExamEnrollment


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "location")
    search_fields = ("name",)
    list_per_page = 10


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("id", "program", "subject", "duration_minutes", "total_marks")
    list_filter = ("program",)
    search_fields = ("program__name", "subject__name")
    list_per_page = 10
    fields = ("program", "subject", "duration_minutes", "total_marks", "description")


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "exam",
        "start_time",
        "end_time",
        "status",
        "roll_number_range",
    )
    list_filter = ("status", "exam__program")
    date_hierarchy = "start_time"
    list_per_page = 10
    fields = (
        "exam",
        "start_time",
        "status",
        "roll_number_start",
        "roll_number_end",
    )

    def roll_number_range(self, obj):
        return f"{obj.roll_number_start} - {obj.roll_number_end}"

    roll_number_range.short_description = "Roll Number Range"

    def end_time(self, obj):
        return obj.end_time

    end_time.short_description = "End Time"


# Inline for HallAllocation
class HallAllocationInline(admin.TabularInline):
    model = HallAllocation
    extra = 1
    fields = ("hall", "program", "subject")
    # readonly_fields = ("program", "subject")
    show_change_link = True


@admin.register(HallAllocation)
class HallAllocationAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "hall", "program", "subject")
    list_filter = ("session__status", "program")
    search_fields = ("hall__name", "program__name")
    list_per_page = 10
    fields = ("session", "hall", "program", "subject")
    # readonly_fields = ("program", "subject")

    # def get_readonly_fields(self, request, obj=None):
    #     if obj:  # Editing an existing object
    #         return (*self.readonly_fields, "session", "hall")
    #     return self.readonly_fields


# Inline for QuestionSet
class QuestionSetInline(admin.TabularInline):
    model = QuestionSet
    extra = 1
    fields = ("name", "program", "subject")
    show_change_link = True


# Inline for Question
class QuestionInline(admin.TabularInline):
    model = Question
    extra = 3
    fields = ("text",)
    show_change_link = True


# Inline for Answer
class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 4
    fields = ("text", "is_correct")
    show_change_link = True


@admin.register(QuestionSet)
class QuestionSetAdmin(admin.ModelAdmin):
    list_display = ("name", "program", "subject")
    list_filter = ("program", "subject")
    search_fields = ("name", "program__name")
    list_per_page = 10
    fields = ("name", "program", "subject", "hall_allocation")
    inlines = [QuestionInline]  # Fixed inline declaration


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "text_preview", "question_set")
    search_fields = ("text",)
    list_filter = ("question_set__program",)
    list_per_page = 10
    fields = ("text", "question_set")
    inlines = [AnswerInline]  # Fixed inline declaration

    def text_preview(self, obj):
        return obj.text[:50] + "..." if len(obj.text) > 50 else obj.text

    text_preview.short_description = "Question Preview"


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("id", "text_preview", "question", "is_correct")
    list_filter = ("is_correct", "question__question_set")
    search_fields = ("text",)
    list_per_page = 10
    fields = ("text", "is_correct", "question")

    def text_preview(self, obj):
        return obj.text[:30] + "..." if len(obj.text) > 30 else obj.text

    text_preview.short_description = "Answer Preview"


@admin.register(StudentExamEnrollment)
class StudentExamEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "candidate",
        "session",
        "hall_allocation",
        "exam_status",
        "verification_status",
    )
    list_filter = ("session__status", "hall_allocation__hall")
    search_fields = ("candidate__symbol_number",)
    list_per_page = 10
    fields = (
        "candidate",
        "session",
        "hall_allocation",
        "exam_started_at",
        "exam_ended_at",
    )
    # readonly_fields = ("session", "hall_allocation", "exam_started_at", "exam_ended_at")

    def exam_status(self, obj):
        if obj.exam_started_at and obj.exam_ended_at:
            return "Completed"
        if obj.exam_started_at:
            return "In Progress"
        return "Not Started"

    exam_status.short_description = "Status"

    def verification_status(self, obj):
        return "Verified"  # Placeholder for actual verification logic

    verification_status.short_description = "Verification"
