from django.contrib import admin
from .models import User, Candidate
from .forms import AdminRegisterForm

class CustomUserAdmin(admin.ModelAdmin):
    add_form = AdminRegisterForm
    list_display = ('email', 'is_admin', 'is_candidate')
    ordering = ('email',)
    search_fields = ('email',)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return self.add_form
        return super().get_form(request, obj, **kwargs)

admin.site.register(User, CustomUserAdmin)
admin.site.register(Candidate)
