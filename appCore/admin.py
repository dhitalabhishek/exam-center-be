from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html

from .models import AdminNotification
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


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ("text", "level", "created_at", "is_read")
    list_filter = ("level", "is_read", "created_at")
    search_fields = ("text",)
    ordering = ("-created_at",)
    actions = ["mark_selected_as_read"]

    # Admin action to mark selected as read
    @admin.action(description="Mark selected notifications as read")
    def mark_selected_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(
            request,
            f"{updated} notification(s) marked as read.",
            messages.SUCCESS,
        )

    # Add custom admin button to mark all as read
    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}

        extra_context["mark_all_as_read_url"] = "mark-all-read/"
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "mark-all-read/",
                self.admin_site.admin_view(self.mark_all_as_read),
                name="mark_all_notifications_as_read",
            ),
        ]
        return custom_urls + urls

    def mark_all_as_read(self, request):
        count = AdminNotification.objects.filter(is_read=False).update(is_read=True)
        self.message_user(
            request,
            f"{count} unread notification(s) marked as read.",
            messages.SUCCESS,
        )
        return redirect("..")
