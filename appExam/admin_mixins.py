from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from appCore.tasks import pause_exam_session
from appCore.tasks import resume_exam_session

MAX_DELTA_SECONDS = 60
MAX_DELTA_MIN = 3600
MAX_DELTA_HOUR = 86400


class ExamSessionActionMixin:
    """Mixin to handle action generation for ExamSession admin"""

    def get_session_actions(self, obj):
        """Get available actions for a session based on its status"""
        if not obj.pk:
            return []

        base_actions = [
            ("📝 Enroll", reverse("admin:enroll_students", args=[obj.pk]), "primary"),
            (
                "📥 Import",
                reverse("admin:appExam_question_import_document", args=[obj.pk]),
                "success",
            ),
            (
                "📄 Export PDF",
                reverse("admin:exam_session_download_pdf", args=[obj.pk]),
                "info",
            ),
            (
                "📄 Export Excel",
                reverse("admin:exam_session_download_excel", args=[obj.pk]),
                "info",
            ),
        ]

        # Add status-specific actions
        status_actions = {
            "ongoing": [
                (
                    "⏸ Pause",
                    reverse("admin:exam_session_pause", args=[obj.pk]),
                    "warning",
                ),
            ],
            "paused": [
                (
                    "▶ Resume",
                    reverse("admin:exam_session_resume", args=[obj.pk]),
                    "warning",
                ),
            ],
            "completed": [
                (
                    "📊 Show Results",
                    reverse("admin:exam_session_download_results_csv", args=[obj.pk]),
                    "secondary",
                ),
            ],
        }

        return base_actions + status_actions.get(obj.status, [])

    def render_dropdown_actions(self, actions):
        """Render actions as a dropdown menu"""
        if not actions:
            return "-"

        items_html = "".join(
            f'<a class="dropdown-item text-{cls}" href="{url}" '
            f'style="display: block; padding: 3px 20px; clear: both; '
            f'color: #333; text-decoration: none; white-space: nowrap;">{label}</a>'
            for label, url, cls in actions
        )

        return format_html(
            """
            <div style="position: relative; display: inline-block;">
                <details style="display: inline-block;">
                    <summary style="
                        display: inline-block; padding: 3px 6px; margin-bottom: 0;
                        font-size: 14px; font-weight: 400; line-height: 1.5;
                        text-align: center; white-space: nowrap; vertical-align: middle;
                        cursor: pointer; user-select: none; background-color: transparent;
                        border: 1px solid #ccc; border-radius: 4px; color: #333;
                        position: relative; padding-right: 25px;
                    ">
                        Actions
                        <span style="
                            position: absolute; right: 8px; top: 50%;
                            transform: translateY(-50%); font-size: 10px;
                        ">▼</span>
                    </summary>
                    <div style="
                        position: absolute; top: 100%; right: 0; z-index: 1000;
                        min-width: 160px; padding: 5px 0; margin: 2px 0 0;
                        font-size: 14px; color: #333; text-align: left;
                        list-style: none; background-color: #fff;
                        background-clip: padding-box; border: 1px solid rgba(0,0,0,.15);
                        border-radius: 4px; box-shadow: 0 6px 12px rgba(0,0,0,.175);
                    ">
                        {items}
                    </div>
                </details>
            </div>
            """,
            items=mark_safe(items_html),
        )


class ExamSessionDisplayMixin:
    """Mixin to handle display methods for ExamSession admin"""

    def status_colored(self, obj):
        """Display status with color coding"""
        color_map = {
            "scheduled": "gray",
            "ongoing": "green",
            "paused": "orange",
            "completed": "blue",
            "cancelled": "red",
        }
        color = color_map.get(obj.status, "black")
        return format_html(
            '<span style="color: {}; font-weight:bold">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_colored.short_description = "Status"

    def base_start_display(self, obj):
        """Simple display of base_start without pill styling"""
        if not obj.base_start:
            return "-"
        return obj.base_start.strftime("%b %d, %Y %H:%M")

    base_start_display.short_description = "Start Time"

    def _format_time_delta(self, delta):
        """Format time delta in a human-readable way"""
        total_seconds = int(delta.total_seconds())

        if total_seconds < MAX_DELTA_SECONDS:
            return f"{total_seconds}s"
        if total_seconds < MAX_DELTA_MIN:
            minutes = total_seconds // 60
            return f"{minutes}m"
        if total_seconds < MAX_DELTA_HOUR:
            hours = total_seconds // MAX_DELTA_MIN
            return f"{hours}h"
        days = total_seconds // MAX_DELTA_HOUR
        return f"{days}d"

    def pause_resume_button(self, obj):
        """Display pause/resume button based on session status"""
        if obj.status == "ongoing":
            return format_html(
                '<a class="button" href="{}">⏸ Pause</a>',
                reverse("admin:exam_session_pause", args=[obj.id]),
            )
        if obj.status == "paused":
            return format_html(
                '<a class="button" href="{}">▶ Resume</a>',
                reverse("admin:exam_session_resume", args=[obj.id]),
            )
        return format_html('<span class="button disabled">Not Active</span>')

    pause_resume_button.short_description = "Session Control"

    def get_base_start_filters(self, request):
        """Generate filter pills for unique base_start times"""
        from django.apps import apps

        ExamSession = apps.get_model("appExam", "ExamSession")

        # Get unique base_start times with counts
        base_starts = (
            ExamSession.objects.values("base_start")
            .annotate(count=Count("id"))
            .order_by("base_start")
        )

        if not base_starts:
            return ""

        now = timezone.now()
        pills_html = []

        for item in base_starts:
            base_start = item["base_start"]
            count = item["count"]

            if not base_start:
                continue

            # Determine pill color based on timing
            if base_start > now:
                # Future - blue
                color = "#007bff"
                bg_color = "#e7f3ff"
                time_diff = base_start - now
                relative_text = f"in {self._format_time_delta(time_diff)}"
            elif base_start.date() == now.date():
                # Today - green
                color = "#28a745"
                bg_color = "#e8f5e9"
                relative_text = "today"
            else:
                # Past - gray
                color = "#6c757d"
                bg_color = "#f8f9fa"
                time_diff = now - base_start
                relative_text = f"{self._format_time_delta(time_diff)} ago"

            formatted_date = base_start.strftime("%b %d, %Y")
            formatted_time = base_start.strftime("%H:%M")

            # Build filter URL
            base_url = request.path
            filter_params = {
                "base_start__date": base_start.date().strftime("%Y-%m-%d"),
                "base_start__time": base_start.time().strftime("%H:%M:%S"),
            }
            filter_url = f"{base_url}?{urlencode(filter_params)}"

            pill_html = format_html(
                """
                <a href="{}" style="text-decoration: none; color: inherit; margin-right: 10px;">
                    <div style="
                        display: inline-flex;
                        flex-direction: column;
                        align-items: center;
                        gap: 2px;
                        cursor: pointer;
                        transition: opacity 0.2s;
                        margin-bottom: 5px;
                    " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">
                        <span style="
                            background-color: {};
                            color: {};
                            padding: 6px 12px;
                            border-radius: 15px;
                            font-size: 12px;
                            font-weight: 500;
                            white-space: nowrap;
                            position: relative;
                        ">
                            {}
                            <span style="
                                position: absolute;
                                top: -5px;
                                right: -5px;
                                background-color: #dc3545;
                                color: white;
                                border-radius: 50%;
                                width: 18px;
                                height: 18px;
                                font-size: 10px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-weight: bold;
                            ">{}</span>
                        </span>
                        <small style="
                            color: #666;
                            font-size: 10px;
                            text-align: center;
                        ">{}<br>{}</small>
                    </div>
                </a>
                """,
                filter_url,
                bg_color,
                color,
                formatted_date,
                count,
                formatted_time,
                relative_text,
            )
            pills_html.append(pill_html)

        if pills_html:
            return format_html(
                """
                <div style="
                    background: #f8f9fa;
                    padding: 15px;
                    margin-bottom: 20px;
                    border-radius: 5px;
                    border: 1px solid #dee2e6;
                ">
                    <h4 style="margin: 0 0 10px 0; color: #495057; font-size: 14px;">
                        Filter by Start Time:
                    </h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                        {}
                    </div>
                </div>
                """,
                mark_safe("".join(pills_html)),
            )

        return ""


class ExamSessionBulkActionMixin:
    """Mixin to handle bulk actions for ExamSession admin"""

    def bulk_pause(self, request, queryset):
        """Bulk pause ongoing sessions"""
        count = 0
        for sess in queryset.filter(status="ongoing"):
            pause_exam_session.delay(sess.id)
            count += 1
        self.message_user(request, f"Initiated pause for {count} ongoing sessions")

    bulk_pause.short_description = "Pause selected ongoing sessions"

    def bulk_resume(self, request, queryset):
        """Bulk resume paused sessions"""
        count = 0
        for sess in queryset.filter(status="paused"):
            resume_exam_session.delay(sess.id)
            count += 1
        self.message_user(request, f"Initiated resume for {count} paused sessions")

    bulk_resume.short_description = "Resume selected paused sessions"

    def bulk_end(self, request, queryset):
        """Bulk end active sessions"""
        count = 0
        for sess in queryset.filter(status__in=["ongoing", "paused"]):
            if sess.end_session():
                count += 1
        self.message_user(request, f"Ended {count} selected sessions")

    bulk_end.short_description = "End selected sessions"

    def enroll_students_action(self, request, queryset):
        """Admin action to enroll students for selected exam sessions"""
        if queryset.count() > 1:
            self.message_user(
                request,
                "Please select only one exam session at a time for enrollment.",
                level=messages.ERROR,
            )
            return None

        session = queryset.first()
        url = reverse("admin:enroll_students", args=[session.pk])
        return HttpResponseRedirect(url)

    enroll_students_action.short_description = "📝 Enroll students by symbol range"
