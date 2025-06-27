from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
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
            range_string = form.cleaned_data["range_string"].strip()
            hall = form.cleaned_data["hall"]

            if range_string == "*":
                # Create dummy hall assignment with first hall, used only for task linkage
                from appInstitutions.models import Hall

                first_hall = hall or Hall.objects.first()

                if not first_hall:
                    messages.error(request, "No halls available to proceed.")
                    return redirect("admin:appExam_examsession_change", session.id)

                hall_assignment, _ = HallAndStudentAssignment.objects.get_or_create(
                    session=session,
                    hall=first_hall,
                    defaults={"roll_number_range": "*"},
                )
            else:
                hall_assignment, created = (
                    HallAndStudentAssignment.objects.get_or_create(
                        session=session,
                        hall=hall,
                        defaults={"roll_number_range": range_string},
                    )
                )
                if not created:
                    hall_assignment.roll_number_range = range_string
                    hall_assignment.save()

            task = enroll_students_by_symbol_range.delay(
                session_id=session.id,
                hall_assignment_id=hall_assignment.id,
                range_string=range_string,
            )

            messages.success(
                request,
                f"Enrollment task started for range '{range_string}'. "
                f"Task ID: {task.id}. Check the results in a few seconds.",
            )

    return redirect("admin:appExam_examsession_change", session.id)
