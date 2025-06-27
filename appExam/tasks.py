import logging
import re

from celery import shared_task
from django.db import transaction

from appAuthentication.models import Candidate
from appCore.models import CeleryTask
from appCore.utils.track_task import track_task
from appExam.models import ExamSession
from appExam.models import Hall
from appExam.models import SeatAssignment
from appExam.models import StudentExamEnrollment

logger = logging.getLogger(__name__)
BATCH_LOG_INTERVAL = 100


def parse_symbol_number(symbol):
    try:
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("Empty symbol number")
        parts = symbol.split("-")
        if len(parts) != 3:
            raise ValueError(f"Invalid format: expected 3 parts, got {len(parts)}")
        year = int(parts[0])
        section = parts[1].upper()
        code = parts[2].upper()
        return (year, section, code)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Error parsing symbol '{symbol}': {e!s}") from e


def extract_numeric_from_section(section):
    match = re.search(r"(\\d+)", section)
    return int(match.group(1)) if match else 0


def extract_letter_from_section(section):
    match = re.search(r"^([A-Z]+)", section)
    return match.group(1) if match else ""


def is_symbol_in_range(symbol, start_symbol, end_symbol):
    try:
        year, section, code = parse_symbol_number(symbol)
        start_year, start_section, start_code = parse_symbol_number(start_symbol)
        end_year, end_section, end_code = parse_symbol_number(end_symbol)

        if year < start_year or year > end_year:
            return False

        if start_year == end_year == year:
            start_letter = extract_letter_from_section(start_section)
            start_num = extract_numeric_from_section(start_section)
            end_letter = extract_letter_from_section(end_section)
            end_num = extract_numeric_from_section(end_section)
            curr_letter = extract_letter_from_section(section)
            curr_num = extract_numeric_from_section(section)

            if start_letter == end_letter == curr_letter:
                if not (start_num <= curr_num <= end_num):
                    return False
                if start_code == end_code:
                    return code == start_code
                return start_code <= code <= end_code

        if year == start_year:
            if section < start_section or (
                section == start_section and code < start_code
            ):
                return False

        if year == end_year:
            if section > end_section or (section == end_section and code > end_code):
                return False

        return True
    except ValueError as e:
        logger.error(f"Range check error: {e}")
        return False


def parse_flexible_range_string(range_string):
    range_string = range_string.strip()
    if range_string == "*":
        return "*"

    ranges = []
    tokens = [token.strip() for token in range_string.split(",") if token.strip()]
    for token in tokens:
        match = re.match(r"^([A-Z]+\\d+)\\s*-\\s*([A-Z]+\\d+)$", token)
        if match:
            start, end = match.groups()
            ranges.append((start, end))
        else:
            match_single = re.match(r"^([A-Z]+\\d+)$", token)
            if match_single:
                val = match_single.group(1)
                ranges.append((val, val))
            else:
                raise ValueError(f"Invalid range format: '{token}'")
    return ranges


def is_seat_available(hall, seat_number, session):
    return (
        not SeatAssignment.objects.filter(
            hall=hall,
            seat_number=seat_number,
            session__base_start__lt=session.expected_end,
            session__expected_end__gt=session.base_start,
        )
        .exclude(session=session)
        .exists()
    )


@shared_task(bind=True)
def enroll_students_by_symbol_range(self, session_id, hall_assignment_id, range_string):
    with track_task(self.request.id, "enroll_students_by_symbol_range") as task:
        try:
            task.message = "Starting enrollment"
            task.progress = 5
            task.save()

            session = ExamSession.objects.get(id=session_id)
            program = session.exam.program
            candidates = Candidate.objects.all()
            total_candidates = candidates.count()

            try:
                ranges = parse_flexible_range_string(range_string)
            except ValueError as e:
                raise ValueError(f"Invalid range format: {e!s}") from e

            enrolled_count = 0
            skipped_count = 0
            error_count = 0
            not_in_program_count = 0
            errors = []
            candidates_in_range = []
            unassigned_candidates = []
            halls = Hall.objects.all()

            with transaction.atomic():
                for idx, candidate in enumerate(candidates, start=1):
                    try:
                        if ranges == "*":
                            in_range = True
                        else:
                            in_range = any(
                                is_symbol_in_range(candidate.symbol_number, start, end)
                                for start, end in ranges
                            )

                        if not in_range:
                            continue

                        candidates_in_range.append(candidate.symbol_number)

                        if int(candidate.program_id) != int(program.program_id):
                            not_in_program_count += 1
                            errors.append(
                                f"Candidate {candidate.symbol_number} skipped: Not in program '{program.name}'",
                            )
                            continue

                        if StudentExamEnrollment.objects.filter(
                            candidate=candidate, session=session,
                        ).exists():
                            skipped_count += 1
                            continue

                        enrollment = StudentExamEnrollment.objects.create(
                            candidate=candidate,
                            session=session,
                            status="inactive",
                            individual_duration=session.base_duration,
                        )

                        seat_assigned = False
                        for hall in halls:
                            for seat_number in range(1, hall.capacity + 1):
                                if is_seat_available(hall, seat_number, session):
                                    SeatAssignment.objects.create(
                                        enrollment=enrollment,
                                        session=session,
                                        hall=hall,
                                        seat_number=seat_number,
                                    )
                                    seat_assigned = True
                                    break
                            if seat_assigned:
                                break

                        if not seat_assigned:
                            unassigned_candidates.append(candidate.symbol_number)
                            enrollment.delete()
                            continue

                        enrolled_count += 1

                        if idx % BATCH_LOG_INTERVAL == 0 or idx == total_candidates:
                            progress = 30 + int(60 * (idx / total_candidates))
                            task.message = (
                                f"Processed {idx}/{total_candidates}: "
                                f"{enrolled_count} enrolled, {skipped_count} skipped, "
                                f"{not_in_program_count} not in program"
                            )
                            task.progress = min(90, progress)
                            task.save()

                    except Exception as e:
                        error_count += 1
                        error_msg = f"{candidate.symbol_number}: {e!s}"
                        errors.append(error_msg)
                        logger.error(error_msg)

            result = {
                "success": True,
                "session_id": session_id,
                "range_processed": range_string,
                "enrolled_count": enrolled_count,
                "skipped_count": skipped_count,
                "not_in_program_count": not_in_program_count,
                "error_count": error_count,
                "errors": errors,
                "total_candidates_checked": total_candidates,
                "candidates_in_range": candidates_in_range,
                "unassigned_candidates": unassigned_candidates,
                "parsed_ranges": ranges,
            }

            task.message = (
                f"Complete: {enrolled_count} enrolled, "
                f"{skipped_count} skipped, {error_count} errors, "
                f"{not_in_program_count} not in program"
            )
            task.status = CeleryTask.get_status_value("SUCCESS")
            task.result = str(result)
            task.progress = 100
            task.save()

            return result

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {e!s}\n\nTraceback:\n{tb}"
            logger.error(f"Fatal error in enrollment task: {error_msg}")

            task.message = f"Task failed: {e!s}"
            task.status = CeleryTask.get_status_value("FAILURE")
            task.result = str({"error": error_msg})
            task.save()

            return {
                "success": False,
                "session_id": session_id,
                "range_processed": range_string,
                "error": error_msg,
            }
