from django.contrib import admin

from .models import Institute
from .models import Program
from .models import Subject

# Register your models here.
admin.site.register(Institute)
admin.site.register(Program)
admin.site.register(Subject)
