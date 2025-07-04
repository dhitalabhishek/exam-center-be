from io import BytesIO

from django.http import FileResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer
from reportlab.platypus import Table
from reportlab.platypus import TableStyle

from appExam.models import ExamSession
from appExam.models import SeatAssignment
from appExam.models import StudentExamEnrollment


def download_exam_pdf_view(request, session_id):
    session = ExamSession.objects.get(pk=session_id)
    enrollments = StudentExamEnrollment.objects.filter(session=session).select_related(
        "candidate",
    )

    # Create a list of enrollments with their seat info for sorting
    enrollment_data = []
    for enrollment in enrollments:
        seat = (
            SeatAssignment.objects.filter(enrollment=enrollment)
            .select_related("hall")
            .first()
        )
        enrollment_data.append((enrollment, seat))

    # Sort by hall name then seat number
    def seat_sort_key(item):
        enrollment, seat = item
        if not seat or not seat.seat_number:
            return ("ZZZ", 999999, "")

        hall_name = seat.hall.name if seat.hall else "ZZZ"
        if isinstance(seat.seat_number, int):
            return (hall_name, seat.seat_number, "")
        number_part = "".join([c for c in str(seat.seat_number) if c.isdigit()])
        prefix = "".join([c for c in str(seat.seat_number) if c.isalpha()])
        return (hall_name, int(number_part) if number_part else 999999, prefix)

    enrollment_data.sort(key=seat_sort_key)

    buffer = BytesIO()
    page_width, page_height = A4
    left_margin = right_margin = 40
    usable_width = page_width - left_margin - right_margin

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=20,
        bottomMargin=20,
    )

    elements = []
    styles = getSampleStyleSheet()

    # No header needed for PDF

    for enrollment, seat in enrollment_data:
        candidate = enrollment.candidate

        if seat and seat.seat_number:
            hall_name = seat.hall.name if seat.hall else "No Hall"
            if isinstance(seat.seat_number, int):
                formatted_seat_number = f"{hall_name}-C{seat.seat_number:03d}"
            else:
                prefix = "".join([c for c in seat.seat_number if c.isalpha()])
                number_part = "".join([c for c in seat.seat_number if c.isdigit()])
                formatted_seat_number = (
                    f"{hall_name} - {prefix}{int(number_part):03d}"
                    if number_part
                    else f"{hall_name} - {seat.seat_number}"
                )
        else:
            formatted_seat_number = "Not Assigned"

        password = getattr(candidate, "generated_password", "N/A")

        # Prepare table data (without QR)
        data = [
            ["Symbol No", "Password", "Seat Number"],
            [candidate.symbol_number, password, formatted_seat_number],
        ]
        col_widths = [usable_width * 0.33, usable_width * 0.33, usable_width * 0.34]

        table = Table(data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Courier"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ],
            ),
        )

        elements.append(table)
        elements.append(PageBreak())

    if elements and isinstance(elements[-1], PageBreak):
        elements.pop()

    doc.build(elements)
    buffer.seek(0)

    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"Exam_Session_{session.exam.program.name}_{session.base_start.strftime('%Y-%m-%d')}_Enrollments.pdf",
    )


def download_exam_excel_view(request, session_id):
    """
    Generates a PDF (styled like Excel table) listing all enrollments with:
    - Symbol number
    - Full name
    - Seat number
    Includes exam session date/time header with local timezone.
    """
    session = ExamSession.objects.get(pk=session_id)
    enrollments = StudentExamEnrollment.objects.filter(session=session).select_related(
        "candidate",
    )

    # Prepare data for table
    data = [["Symbol No", "Name", "Seat Number"]]

    # Sort enrollments by symbol number
    enrollments = enrollments.order_by("candidate__symbol_number")

    for enrollment in enrollments:
        candidate = enrollment.candidate
        seat = (
            SeatAssignment.objects.filter(enrollment=enrollment)
            .select_related("hall")
            .first()
        )

        hall_name = seat.hall.name if seat and seat.hall else "No Hall"
        seat_number = seat.seat_number if seat else "Not Assigned"

        full_name = f"{candidate.first_name} {candidate.middle_name or ''} {candidate.last_name}".strip()  # noqa: E501

        data.append(
            [
                candidate.symbol_number,
                full_name,
                f"{hall_name} - {seat_number}",
            ],
        )

    # Generate PDF with table
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Convert to local timezone for display
    local_datetime = timezone.localtime(session.base_start)

    # Add session info header with local timezone
    session_info = (
        f"{session.exam.program.name} - {local_datetime.strftime('%Y-%m-%d %H:%M')}"
    )
    elements.append(Paragraph(session_info, styles["Title"]))
    elements.append(Spacer(1, 12))

    # Table setup
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ],
        ),
    )
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    # Filename with local timezone
    filename = f"Exam_Session_{session.exam.program.name}_{local_datetime.strftime('%Y-%m-%d_%H-%M')}_Enrollments.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename)
