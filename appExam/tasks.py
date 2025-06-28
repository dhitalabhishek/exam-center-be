import logging
import re

from celery import shared_task
from django.db import IntegrityError
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


def extract_symbol_components(symbol):
    """
    Extract prefix and numeric parts from a symbol number.
    Handles complex formats like 'MG12XX10', 'b10001', etc.
    Examples: 
    - 'MG12XX10' -> {'prefix': 'mg12xx', 'number': 10}
    - 'b10001' -> {'prefix': 'b', 'number': 10001}
    - 'CSE2023001' -> {'prefix': 'cse2023', 'number': 1}
    """
    if not symbol:
        return None
    
    symbol = symbol.strip()
    
    # Find the last continuous sequence of digits
    match = re.search(r'(\d+)$', symbol)
    if not match:
        return None
    
    number_part = match.group(1)
    prefix_part = symbol[:match.start()]
    
    return {
        'prefix': prefix_part.lower(),
        'number': int(number_part)
    }


def parse_flexible_range_string(range_string):
    """
    Parse range string with prefix awareness.
    Examples:
    - 'b10001|b10101' -> [{'prefix': 'b', 'start': 10001, 'end': 10101}]
    - 'p10001|p10101' -> [{'prefix': 'p', 'start': 10001, 'end': 10101}]
    - '*' -> '*'
    """
    range_string = range_string.strip()
    if range_string == "*":
        return "*"

    ranges = []
    tokens = [token.strip() for token in range_string.split(",") if token.strip()]
    
    for token in tokens:
        if "|" in token:
            parts = token.split("|")
            if len(parts) >= 2:
                start_comp = extract_symbol_components(parts[0])
                end_comp = extract_symbol_components(parts[-1])
                
                if (start_comp and end_comp and 
                    start_comp['prefix'] == end_comp['prefix']):
                    ranges.append({
                        'prefix': start_comp['prefix'],
                        'start': min(start_comp['number'], end_comp['number']),
                        'end': max(start_comp['number'], end_comp['number'])
                    })
                else:
                    logger.warning(f"Invalid range token: {token} - prefixes must match")
        else:
            comp = extract_symbol_components(token)
            if comp:
                ranges.append({
                    'prefix': comp['prefix'],
                    'start': comp['number'],
                    'end': comp['number']
                })
            else:
                logger.warning(f"Invalid symbol format: {token}")
    
    return ranges


def is_symbol_in_range(symbol, ranges):
    """
    Check if a symbol falls within any of the given ranges.
    Now prefix-aware: 'b10001' will only match ranges with prefix 'b'.
    """
    if ranges == "*":
        return True
    
    comp = extract_symbol_components(symbol)
    if not comp:
        return False
    
    return any(
        range_item['prefix'] == comp['prefix'] and
        range_item['start'] <= comp['number'] <= range_item['end']
        for range_item in ranges
    )


def is_seat_available(hall, seat_number, session):
    """
    Check if a seat is available by looking for existing assignments
    with the same hall, seat_number, and session_base_start
    """
    return not SeatAssignment.objects.filter(
        hall=hall,
        seat_number=seat_number,
        session_base_start=session.base_start,
    ).exists()


def assign_seat_to_enrollment(enrollment, session, halls):
    """
    Try to assign a seat to an enrollment.
    Returns True if successful, False otherwise.
    """
    for hall in halls:
        # Get all currently occupied seats for this hall and time slot
        occupied_seats = set(
            SeatAssignment.objects.filter(
                hall=hall,
                session_base_start=session.base_start,
            ).values_list("seat_number", flat=True)
        )

        # Try to find an available seat
        for seat_number in range(1, hall.capacity + 1):
            if seat_number not in occupied_seats:
                try:
                    # Each seat assignment attempt gets its own atomic block
                    with transaction.atomic():
                        SeatAssignment.objects.create(
                            enrollment=enrollment,
                            session=session,
                            hall=hall,
                            seat_number=seat_number,
                        )
                    return True  # Successfully assigned
                except IntegrityError as seat_error:
                    # This atomic block failed, but we can continue with the next seat
                    logger.warning(
                        f"Seat conflict for enrollment {enrollment.id} at seat {seat_number}: {seat_error}"
                    )
                    # Add this seat to occupied_seats to avoid trying it again
                    occupied_seats.add(seat_number)
                    continue
    return False  # No seat could be assigned


@shared_task(bind=True)
def enroll_students_by_symbol_range(self, session_id, hall_assignment_id, range_string):
    with track_task(self.request.id, "enroll_students_by_symbol_range") as task:
        try:
            task.message = "Starting enrollment"
            task.progress = 5
            task.save()

            session = ExamSession.objects.get(id=session_id)
            program = session.exam.program

            # Filter candidates by both institute and program
            candidates = Candidate.objects.filter(
                institute=program.institute, program_id=program.program_id,
            )
            total_candidates = candidates.count()

            try:
                ranges = parse_flexible_range_string(range_string)
                logger.info(f"Parsed ranges: {ranges}")
            except ValueError as e:
                msg = f"Invalid range format: {e!s}"
                raise ValueError(msg) from e

            enrolled_count = 0
            skipped_count = 0
            error_count = 0
            not_in_program_count = 0
            errors = []
            candidates_in_range = []
            unassigned_candidates = []
            halls = Hall.objects.all()

            for idx, candidate in enumerate(candidates, start=1):
                try:
                    if ranges == "*":
                        in_range = True
                    else:
                        in_range = is_symbol_in_range(candidate.symbol_number, ranges)

                    if not in_range:
                        continue

                    candidates_in_range.append(candidate.symbol_number)

                    # No need to check program since we already filtered by it
                    if StudentExamEnrollment.objects.filter(
                        candidate=candidate,
                        session=session,
                    ).exists():
                        skipped_count += 1
                        continue

                    # Create enrollment in its own transaction
                    try:
                        with transaction.atomic():
                            enrollment = StudentExamEnrollment.objects.create(
                                candidate=candidate,
                                session=session,
                                status="inactive",
                                individual_duration=session.base_duration,
                            )
                    except IntegrityError as e:
                        error_count += 1
                        error_msg = f"{candidate.symbol_number}: Failed to create enrollment - {e!s}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                        continue

                    # Try to assign a seat
                    seat_assigned = assign_seat_to_enrollment(
                        enrollment, session, halls
                    )

                    if not seat_assigned:
                        # Clean up the enrollment if no seat could be assigned
                        try:
                            with transaction.atomic():
                                enrollment.delete()
                        except Exception as delete_error:
                            logger.warning(
                                f"Could not delete enrollment for {candidate.symbol_number}: {delete_error}",
                            )
                        unassigned_candidates.append(candidate.symbol_number)
                        continue

                    enrolled_count += 1

                except Exception as e:
                    error_count += 1
                    error_msg = f"{candidate.symbol_number}: {e!s}"
                    errors.append(error_msg)
                    logger.error(error_msg)

                if idx % BATCH_LOG_INTERVAL == 0 or idx == total_candidates:
                    progress = 30 + int(60 * (idx / total_candidates))
                    task.message = (
                        f"Processed {idx}/{total_candidates}: "
                        f"{enrolled_count} enrolled, {skipped_count} skipped, "
                        f"{not_in_program_count} not in program"
                    )
                    task.progress = min(90, progress)
                    task.save()

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