from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import EnrollmentRangeForm
from .models import ExamSession
from .models import HallAndStudentAssignment
from .tasks import enroll_students_by_symbol_range


# Custom admin view for enrolling students
@staff_member_required
@require_http_methods(["GET", "POST"])
def enroll_students_view(request, session_id):
    """Custom admin view for enrolling students by range"""
    try:
        session = ExamSession.objects.get(id=session_id)
    except ExamSession.DoesNotExist:
        messages.error(request, f"Exam session with ID {session_id} not found.")
        return redirect("admin:appExam_examsession_changelist")

    if request.method == "POST":
        form = EnrollmentRangeForm(session_id, request.POST)
        if form.is_valid():
            range_string = form.cleaned_data["range_string"]
            hall = form.cleaned_data["hall"]

            # Get or create hall assignment
            hall_assignment, created = HallAndStudentAssignment.objects.get_or_create(
                session=session,
                hall=hall,
                defaults={"roll_number_range": range_string},
            )

            # If already exists, update range
            if not created:
                hall_assignment.roll_number_range = range_string
                hall_assignment.save()

            # Trigger the Celery task
            task = enroll_students_by_symbol_range.delay(
                session_id=session.id,
                hall_assignment_id=hall_assignment.id,
                range_string=range_string,
            )

            messages.success(
                request,
                f"Enrollment task started for range '{range_string}'. "
                f"Task ID: {task.id}. Check the results in few seconds.",
            )
            return redirect("admin:appExam_examsession_change", session.id)
    else:
        form = EnrollmentRangeForm(session_id)

    context = {
        "form": form,
        "session": session,
        "title": f"Enroll Students for {session}",
        "opts": ExamSession._meta,  # noqa: SLF001
        "has_change_permission": True,
        "current_time": timezone.localtime(timezone.now()),
    }

    return render(request, "admin/enroll_students.html", context)
