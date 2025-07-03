import os

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import path
from django.urls import reverse

from appCore.models import CeleryTask
from appCore.utils.export_task import export_candidates_by_sessions_task
from appExam.models import ExamSession


class SessionWiseCandidateExportAdmin:
    """
    Admin interface for session-wise candidate export using Celery
    """

    def get_urls(self):
        """Define custom URLs for export functionality"""
        return [
            path(
                "session-export/",
                self.export_view,
                name="session_export_view",
            ),
            path(
                "session-export/start/",
                self.start_export,
                name="session_export_start",
            ),
            path(
                "session-export/status/<str:task_id>/",
                self.export_status,
                name="session_export_status",
            ),
            path(
                "session-export/download/<str:filename>/",
                self.download_file,
                name="session_export_download",
            ),
        ]

    def export_view(self, request):
        """Display export options and statistics"""
        # Get session statistics
        sessions_with_enrollments = (
            ExamSession.objects.filter(enrollments__isnull=False)
            .distinct()
            .select_related("exam__program", "exam__subject")
        )

        total_sessions = sessions_with_enrollments.count()

        # Get recent export tasks
        recent_tasks = CeleryTask.objects.filter(
            name="Export Candidates by Sessions",
        ).order_by("-created")[:10]

        context = {
            "title": "Export Candidates by Sessions",
            "total_sessions": total_sessions,
            "sessions": sessions_with_enrollments.order_by("base_start")[
                :20
            ],  # Show first 20 for preview
            "recent_tasks": recent_tasks,
            "start_export_url": reverse("admin:session_export_start"),
        }
        return render(request, "admin/session_export.html", context)

    def start_export(self, request):
        """Start the export task"""
        if request.method == "POST":
            try:
                # Start the Celery task
                task = export_candidates_by_sessions_task.delay()

                messages.success(
                    request,
                    f"Export task started successfully. Task ID: {task.id}",
                )

                return JsonResponse(
                    {
                        "status": "success",
                        "task_id": task.id,
                        "message": "Export task started successfully",
                    },
                )

            except Exception as e:
                messages.error(request, f"Failed to start export task: {e!s}")
                return JsonResponse(
                    {
                        "status": "error",
                        "message": f"Failed to start export task: {e!s}",
                    },
                    status=500,
                )

        return JsonResponse(
            {"status": "error", "message": "Invalid request method"},
            status=405,
        )

    def export_status(self, request, task_id):
        """Check the status of an export task"""
        try:
            task = CeleryTask.objects.get(task_id=task_id)

            response_data = {
                "task_id": task_id,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "created_at": task.created.isoformat(),
                "updated_at": task.updated.isoformat(),
            }

            # If task is completed successfully, add download link
            if task.status == "SUCCESS" and task.message:
                # Extract file path from message
                if "ZIP file saved at:" in task.message:
                    file_path = task.message.split("ZIP file saved at: ")[-1]
                    filename = os.path.basename(file_path)
                    response_data["download_url"] = reverse(
                        "admin:session_export_download",
                        kwargs={"filename": filename},
                    )

            return JsonResponse(response_data)

        except CeleryTask.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Task not found"},
                status=404,
            )

    def download_file(self, request, filename):
        """Download the exported ZIP file"""
        file_path = os.path.join(settings.MEDIA_ROOT, "exports", filename)

        if not os.path.exists(file_path):
            raise Http404("File not found")

        # Security check - ensure filename is safe
        if not filename.endswith(".zip") or ".." in filename:
            raise Http404("Invalid file")

        with open(file_path, "rb") as f:
            response = HttpResponse(f.read(), content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
