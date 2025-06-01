
from django.contrib import admin

from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import Hall
from .models import HallAndStudentAssignment
from .models import Question
from .models import StudentExamEnrollment


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "location")
    list_per_page = 10


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("id", "program", "subject", "total_marks")
    list_filter = ("program",)
    list_per_page = 10


class HallAndStudentAssignmentInline(admin.TabularInline):
    model = HallAndStudentAssignment
    extra = 1
    fields = ("hall", "roll_number_range", "numeric_rolls")
    show_change_link = True

    readonly_fields = ("numeric_rolls",)

    def numeric_rolls(self, obj):
        # joins the integer list as a comma-separated string
        return ", ".join(str(n) for n in obj.get_numeric_roll_range())

    numeric_rolls.short_description = "All Rolls"


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "exam", "start_time", "end_time", "status")
    inlines = [HallAndStudentAssignmentInline]
    list_filter = ("status", "exam__program")
    date_hierarchy = "start_time"
    list_per_page = 10




@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "session")
    list_per_page = 10


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("text", "question", "is_correct")
    list_per_page = 10


@admin.register(StudentExamEnrollment)
class StudentExamEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("candidate", "session", "hall_assignment", "Time_Remaining")
    list_filter = ("session__status", "hall_assignment__hall")
    list_per_page = 10
