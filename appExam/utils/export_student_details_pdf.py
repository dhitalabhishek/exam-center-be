from io import BytesIO

from django.http import FileResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from appExam.models import ExamSession
from appExam.models import SeatAssignment
from appExam.models import StudentExamEnrollment


def download_exam_pdf_view(request, session_id):
    session = ExamSession.objects.get(pk=session_id)
    enrollments = StudentExamEnrollment.objects.filter(session=session).select_related(
        "candidate",
    )
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    for enrollment in enrollments:
        candidate = enrollment.candidate
        seat = (
            SeatAssignment.objects.filter(enrollment=enrollment)
            .select_related("hall")
            .first()
        )

        hall_name = seat.hall.name if seat and seat.hall else "No Hall Assigned"

        if seat and seat.seat_number:
            if isinstance(seat.seat_number, int):
                # If seat_number is an integer (e.g. 1, 45, 200)
                formatted_seat_number = f"C{seat.seat_number:03d}"
            else:
                # If seat_number is string (e.g. 'c1', 'c045')
                prefix = "".join([c for c in seat.seat_number if c.isalpha()])
                number_part = "".join([c for c in seat.seat_number if c.isdigit()])
                formatted_seat_number = (
                    f"{prefix}{int(number_part):03d}"
                    if number_part
                    else seat.seat_number
                )
        else:
            formatted_seat_number = "Not Assigned"

        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(100, 800, f"Symbol Number: {candidate.symbol_number}")
        pdf.setFont("Helvetica", 12)
        pdf.drawString(
            100, 770, f"Password: {getattr(candidate, 'generated_password', 'N/A')}",
        )
        pdf.drawString(100, 740, f"Seat: {hall_name} - {formatted_seat_number}")
        pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"Exam_Session_{session.exam.program.name}_{session.base_start}_Enrollments.pdf",
    )
