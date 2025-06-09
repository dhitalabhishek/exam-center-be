
import logging
import re

from celery import shared_task
from django.db import transaction

from appAuthentication.models import Candidate
from appCore.models import CeleryTask
from appCore.utils.track_task import track_task
from appExam.models import ExamSession
from appExam.models import HallAndStudentAssignment
from appExam.models import StudentExamEnrollment

logger = logging.getLogger(__name__)
BATCH_LOG_INTERVAL = 100

def parse_symbol_number(symbol):
    """Parse symbol number with detailed error handling."""
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
        # Include original symbol in error message
        raise ValueError(f"Error parsing symbol '{symbol}': {e!s}") from e

def extract_numeric_from_section(section):
    match = re.search(r"(\d+)", section)
    return int(match.group(1)) if match else 0

def extract_letter_from_section(section):
    match = re.search(r"^([A-Z]+)", section)
    return match.group(1) if match else ""

def is_symbol_in_range(symbol, start_symbol, end_symbol):
    try:
        year, section, code = parse_symbol_number(symbol)
        start_year, start_section, start_code = parse_symbol_number(start_symbol)
        end_year, end_section, end_code = parse_symbol_number(end_symbol)

        # If years are different
        if year < start_year or year > end_year:
            return False

        # Same year range
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
                # Handle code range
                if start_code == end_code:
                    return code == start_code
                return start_code <= code <= end_code

        # Cross-year handling
        if year == start_year:
            if section < start_section or (section == start_section and code < start_code):
                return False

        if year == end_year:
            if section > end_section or (section == end_section and code > end_code):
                return False

        return True

    except ValueError as e:
        logger.error(f"Range check error: {e}")
        return False

def parse_range_string(range_string):
    """Parse complex range strings with commas and dashes."""
    ranges = []
    tokens = [token.strip() for token in range_string.split(",") if token.strip()]

    for token in tokens:
        if " - " in token:
            parts = token.split(" - ")
            if len(parts) != 2:
                raise ValueError(f"Invalid range format: {token}")
            ranges.append((parts[0].strip(), parts[1].strip()))
        else:
            ranges.append((token, token))

    return ranges

@shared_task(bind=True)
def enroll_students_by_symbol_range(self, session_id, hall_assignment_id, range_string):
    with track_task(self.request.id, "enroll_students_by_symbol_range") as task:
        try:
            # Initial setup
            task.message = "Starting enrollment"
            task.progress = 5
            task.save()

            session = ExamSession.objects.get(id=session_id)
            hall_assignment = HallAndStudentAssignment.objects.get(id=hall_assignment_id)
            program = session.exam.program
            candidates = Candidate.objects.filter(program_id=program.program_id)
            total_candidates = candidates.count()

            # Parse ranges with detailed error handling
            try:
                ranges = parse_range_string(range_string)
            except ValueError as e:
                raise ValueError(f"Invalid range format: {e!s}") from e

            if not ranges:
                raise ValueError("No valid ranges provided")

            # Processing setup
            enrolled_count = 0
            skipped_count = 0
            error_count = 0
            errors = []
            candidates_in_range = []

            with transaction.atomic():
                for idx, candidate in enumerate(candidates, start=1):
                    try:
                        in_range = any(
                            is_symbol_in_range(candidate.symbol_number, start, end)
                            for start, end in ranges
                        )

                        if in_range:
                            candidates_in_range.append(candidate.symbol_number)
                            if not StudentExamEnrollment.objects.filter(
                                candidate=candidate, session=session,
                            ).exists():
                                StudentExamEnrollment.objects.create(
                                    candidate=candidate,
                                    session=session,
                                    time_remaining=session.duration,
                                    hall_assignment=hall_assignment,
                                )
                                enrolled_count += 1
                            else:
                                skipped_count += 1

                        # Progress updates
                        if idx % BATCH_LOG_INTERVAL == 0 or idx == total_candidates:
                            progress = 30 + int(60 * (idx / total_candidates))
                            task.message = (
                                f"Processed {idx}/{total_candidates}: "
                                f"{enrolled_count} enrolled, {skipped_count} skipped"
                            )
                            task.progress = min(90, progress)
                            task.save()

                    except Exception as e:
                        error_count += 1
                        error_msg = f"{candidate.symbol_number}: {e!s}"
                        errors.append(error_msg)
                        logger.error(error_msg)

            # Final updates
            hall_assignment.roll_number_range = range_string
            hall_assignment.save()

            result = {
                "success": True,
                "session_id": session_id,
                "hall_assignment_id": hall_assignment_id,
                "range_processed": range_string,
                "enrolled_count": enrolled_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "errors": errors[:10],  # Limit to first 10 errors
                "total_candidates_checked": total_candidates,
                "candidates_in_range": candidates_in_range,
                "parsed_ranges": ranges,  # For debugging
            }

            task.message = (
                f"Complete: {enrolled_count} enrolled, "
                f"{skipped_count} skipped, {error_count} errors"
            )
            task.status = CeleryTask.get_status_value("SUCCESS")

            task.result = str(result)
            task.progress = 100
            task.save()

            return result

        except Exception as e:
            # Detailed error reporting
            import traceback
            tb = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {e!s}\n\nTraceback:\n{tb}"
            logger.error(f"Fatal error in enrollment task: {error_msg}")

            task.message = f"Task failed: {e!s}"
            task.status = CeleryTask.get_status_value("FAILURE")

            task.result = str({"error": error_msg})
            task.save()
            raise
