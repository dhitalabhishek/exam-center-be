import logging
import re

from celery import shared_task
from django.db import transaction

from appAuthentication.models import Candidate
from appExam.models import ExamSession
from appExam.models import HallAndStudentAssignment
from appExam.models import StudentExamEnrollment

logger = logging.getLogger(__name__)


def parse_symbol_number(symbol):
    """
    Parse symbol number like '13-A1-PT' into components for comparison.
    Returns tuple: (year, section, code) where each is normalized for comparison.
    """
    parts = symbol.strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid symbol format: {symbol}")

    year = int(parts[0])
    section = parts[1].upper()  # Normalize to uppercase
    code = parts[2].upper()  # Normalize to uppercase

    return (year, section, code)


def extract_numeric_from_section(section):
    """
    Extract numeric part from section like 'A1' -> 1, 'B12' -> 12, 'S1' -> 1
    """
    match = re.search(r"(\d+)", section)
    return int(match.group(1)) if match else 0


def extract_letter_from_section(section):
    """
    Extract letter part from section like 'A1' -> 'A', 'B12' -> 'B'
    """
    match = re.search(r"^([A-Z]+)", section)
    return match.group(1) if match else ""


def is_symbol_in_range(symbol, start_symbol, end_symbol):
    """
    Check if a symbol number falls within the given range.
    Handles formats like '13-S1-PH' to '13-S14-PH'
    """
    try:
        year, section, code = parse_symbol_number(symbol)
        start_year, start_section, start_code = parse_symbol_number(start_symbol)
        end_year, end_section, end_code = parse_symbol_number(end_symbol)

        logger.debug(
            f"Checking symbol {symbol}: year={year}, section={section}, code={code}",
        )
        logger.debug(
            f"Range: {start_year}-{start_section}-{start_code} to {end_year}-{end_section}-{end_code}",
        )

        # If years are different, check year range
        if year < start_year or year > end_year:
            logger.debug(
                f"Symbol {symbol} rejected: year {year} not in range {start_year}-{end_year}",
            )
            return False

        # For same year ranges like 13-S1-PH to 13-S14-PH
        if start_year == end_year == year:
            # Extract letter and number parts from sections
            start_letter = extract_letter_from_section(start_section)
            start_num = extract_numeric_from_section(start_section)
            end_letter = extract_letter_from_section(end_section)
            end_num = extract_numeric_from_section(end_section)
            curr_letter = extract_letter_from_section(section)
            curr_num = extract_numeric_from_section(section)

            logger.debug(
                f"Section comparison: {curr_letter}{curr_num} between {start_letter}{start_num} and {end_letter}{end_num}",
            )

            # If same letter prefix (like 'S'), just compare numbers
            if start_letter == end_letter == curr_letter:
                in_range = start_num <= curr_num <= end_num
                logger.debug(
                    f"Same letter '{curr_letter}': {curr_num} in range {start_num}-{end_num}? {in_range}",
                )
                if in_range:
                    # Now check codes
                    if start_code == end_code == code:
                        logger.debug(f"Code match: {code}")
                        return True
                    if start_code <= code <= end_code:
                        logger.debug(
                            f"Code in range: {code} between {start_code} and {end_code}",
                        )
                        return True
                return False

        # If same year as start, check if section/code is >= start
        if year == start_year:
            if section < start_section:
                return False
            if section == start_section and code < start_code:
                return False

        # If same year as end, check if section/code is <= end
        if year == end_year:
            if section > end_section:
                return False
            if section == end_section and code > end_code:
                return False

        return True

    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing symbol {symbol}: {e}")
        return False


def parse_range_string(range_string):
    """
    Parse range string like '13-A1-PT - 14-C2-GM' or single symbol '17-A6-12'
    Returns tuple: (start_symbol, end_symbol) or (symbol, symbol) for single
    """
    range_string = range_string.strip()

    # Check if it's a range (contains ' - ')
    if " - " in range_string:
        parts = range_string.split(" - ")
        if len(parts) != 2:
            raise ValueError(f"Invalid range format: {range_string}")
        return parts[0].strip(), parts[1].strip()
    # Single symbol
    return range_string, range_string


@shared_task
def enroll_students_by_symbol_range(session_id, hall_assignment_id, range_string):
    """
    Celery task to enroll students in an exam session based on symbol number range.

    Args:
        session_id: ID of the ExamSession
        hall_assignment_id: ID of the HallAndStudentAssignment
        range_string: Symbol range like '13-S1-PH - 13-S14-PH' or single '17-A6-12'

    Returns:
        dict: Summary of enrollment results
    """
    try:
        logger.info(
            f"Starting enrollment task for session {session_id}, hall {hall_assignment_id}, range {range_string}",
        )

        # Get the session and hall assignment
        session = ExamSession.objects.get(id=session_id)
        hall_assignment = HallAndStudentAssignment.objects.get(id=hall_assignment_id)

        logger.info(f"Found session: {session}")
        logger.info(f"Found hall assignment: {hall_assignment}")

        # Parse the range
        start_symbol, end_symbol = parse_range_string(range_string)
        logger.info(f"Parsed range: {start_symbol} to {end_symbol}")

        # Get the program from the exam session
        program = session.exam.program
        logger.info(f"Program: {program} (ID: {program.id}, Name: {program.name})")

        # FIXED: Get all candidates for this program
        # The Candidate model has program_id (IntegerField) and program (CharField)
        # Based on your debug, candidates are found by program_id using program.program_id
        candidates = Candidate.objects.filter(program_id=program.program_id)

        logger.info(f"Found {candidates.count()} candidates for program")

        # Debug: Show some candidates
        for candidate in candidates[:5]:  # Show first 5
            logger.info(
                f"Candidate: {candidate.symbol_number} - {candidate.first_name} {candidate.last_name}",
            )

        enrolled_count = 0
        skipped_count = 0
        error_count = 0
        errors = []
        candidates_in_range = []

        with transaction.atomic():
            for candidate in candidates:
                try:
                    logger.debug(f"Checking candidate {candidate.symbol_number}")

                    # Check if candidate's symbol is in range
                    if is_symbol_in_range(
                        candidate.symbol_number, start_symbol, end_symbol,
                    ):
                        logger.info(f"Candidate {candidate.symbol_number} is in range")
                        candidates_in_range.append(candidate.symbol_number)

                        # Check if already enrolled
                        existing_enrollment = StudentExamEnrollment.objects.filter(
                            candidate=candidate,
                            session=session,
                        ).first()

                        if existing_enrollment:
                            logger.info(
                                f"Candidate {candidate.symbol_number} already enrolled, skipping",
                            )
                            skipped_count += 1
                            continue

                        # Create enrollment
                        StudentExamEnrollment.objects.create(
                            candidate=candidate,
                            session=session,
                            hall_assignment=hall_assignment,
                            Time_Remaining=0,  # Will be set when exam starts
                        )
                        logger.info(f"Enrolled candidate {candidate.symbol_number}")
                        enrolled_count += 1
                    else:
                        logger.debug(
                            f"Candidate {candidate.symbol_number} not in range",
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing candidate {candidate.symbol_number}: {e}",
                    )
                    error_count += 1
                    errors.append(f"Candidate {candidate.symbol_number}: {e!s}")

        # Update the hall assignment with the processed range
        hall_assignment.roll_number_range = range_string
        hall_assignment.save()

        logger.info(
            f"Enrollment complete: {enrolled_count} enrolled, {skipped_count} skipped, {error_count} errors",
        )
        logger.info(f"Candidates in range: {candidates_in_range}")

        result = {
            "success": True,
            "session_id": session_id,
            "hall_assignment_id": hall_assignment_id,
            "range_processed": range_string,
            "enrolled_count": enrolled_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "errors": errors[:10] if errors else [],  # Limit to first 10 errors
            "total_candidates_checked": candidates.count(),
            "candidates_in_range": candidates_in_range,
        }

        return result

    except Exception as e:
        logger.error(f"Fatal error in enrollment task: {e}")
        return {
            "success": False,
            "error": str(e),
            "session_id": session_id,
            "hall_assignment_id": hall_assignment_id,
            "range_processed": range_string,
        }

