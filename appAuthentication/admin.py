from django.contrib import admin

from .models import Candidate
from .models import User

# Register your models here.
admin.site.register(User)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("symbol_number", "first_name", "last_name", "institute")
    search_fields = ("symbol_number", "first_name", "last_name")

    def institute(self, obj):
        return obj.institute

    institute.short_description = "Institute"
