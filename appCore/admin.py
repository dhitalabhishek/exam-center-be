from django.contrib import admin
from django.urls import path
from django.utils.html import format_html

from .models import CeleryTask
from .views import task_last_updated


@admin.register(CeleryTask)
class CeleryTaskAdmin(admin.ModelAdmin):
    list_display = (
        "task_id",
        "name",
        "status",
        "progress_bar",
        "message_preview",
        "created",
        "updated",
    )
    list_filter = ("status", "name")
    readonly_fields = (
        "task_id",
        "name",
        "status",
        "progress",
        "message",
        "created",
        "updated",
    )
    search_fields = ("task_id", "name", "message")
    ordering = ("-created",)

    change_list_template = "admin/appcore/celerytask/change_list.html"

    # Progress bar display
    def progress_bar(self, obj):
        color = "#4CAF50" if obj.progress == 100 else "#2196F3"  # noqa: PLR2004
        return format_html(
            '<div style="width:100%; background:#ddd;\
              border-radius:5px; position:relative;">'
            '<div style="width:{}%; background:{}; \
                height:24px; border-radius:5px;"></div>'
            '<div style="position:absolute; top:0; left:0; width:100%; \
                text-align:center; line-height:24px; color:{}; font-weight:bold;">'
            "{}%"
            "</div>"
            "</div>",
            obj.progress,
            color,
            "white" if obj.progress > 50 else "black",  # noqa: PLR2004
            obj.progress,
        )

    progress_bar.short_description = "Progress"

    # Message preview
    def message_preview(self, obj):
        return obj.message[:100] + "..." if len(obj.message) > 100 else obj.message  # noqa: PLR2004

    message_preview.short_description = "Message"

    # Prevent adding tasks manually
    def has_add_permission(self, request):
        return False

    # Add custom URLs
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "task-status/last-updated/",
                self.admin_site.admin_view(task_last_updated),
                name="task_last_updated",
            ),
        ]
        return custom_urls + urls

    # Pass timestamp to template
