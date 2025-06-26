import csv
import logging
import os
import random
import string

import pandas as pd
from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage

from appAuthentication.models import Candidate
from appCore.models import CeleryTask
from appCore.utils.track_task import track_task
from appInstitutions.models import Institute

User = get_user_model()
logger = logging.getLogger(__name__)


def process_batch(users_batch, candidates_batch):
    """
    BEST APPROACH: Process batch using get_or_create for robust duplicate handling
    Returns (created_count, errors_list)
    """
    created_count = 0
    errors = []

    for user_data, candidate_data in zip(users_batch, candidates_batch, strict=False):
        try:
            # Check for existing candidate first (most restrictive check)
            if Candidate.objects.filter(
                symbol_number=candidate_data["symbol_number"],
            ).exists():
                errors.append(
                    f"Candidate with symbol number {candidate_data['symbol_number']} already exists",
                )
                continue

            # Use get_or_create for user - handles race conditions automatically
            user, user_created = User.objects.get_or_create(
                email=user_data["email"],
                defaults={"is_candidate": user_data.get("is_candidate", True)},
            )

            if not user_created:
                errors.append(f"User with email {user_data['email']} already exists")
                continue

            # Set password properly since get_or_create doesn't hash it
            user.set_password(user_data["password"])
            user.save()

            # Create candidate - this is safe now since we checked for duplicates
            Candidate.objects.create(**candidate_data, user=user)
            created_count += 1

        except Exception as e:
            error_msg = f"Failed to create user {user_data['email']}: {e!s}"
            logger.error(error_msg)
            errors.append(error_msg)
            continue

    return created_count, errors


@shared_task(bind=True)
def process_candidates_file(self, file_path, institute_id, file_format="format1"):
    """
    IMPROVED: Process CSV or Excel file with robust error handling
    """
    with track_task(self.request.id, "process_candidates_file") as task:
        try:
            task.message = f"Starting candidate import process (Format: {file_format})"
            task.progress = 5
            task.save()

            institute = Institute.objects.get(id=institute_id)
            file_extension = os.path.splitext(file_path)[1].lower()

            # Read file based on extension
            if file_extension == ".csv":
                task.message = "Reading CSV file"
                task.save()
                rows = read_csv_file(file_path)
            elif file_extension in [".xlsx", ".xls"]:
                task.message = "Reading Excel file"
                task.save()
                rows = read_excel_file(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")

            total_rows = len(rows)
            if total_rows == 0:
                task.message = "File is empty - no candidates to process"
                task.status = CeleryTask.get_status_value("FAILURE")
                task.save()
                return {"status": "error", "message": "File is empty"}

            # Process in smaller batches for better memory management
            batch_size = 50  # Reduced batch size for better error isolation
            processed_rows = 0
            all_errors = []
            users_batch = []
            candidates_batch = []

            logger.info(
                f"Starting to process {total_rows} candidates from {file_extension} file for institute {institute.name} using {file_format}",
            )

            task.message = f"Processing {total_rows} candidates ({file_format})"
            task.progress = 10
            task.save()

            for index, row in enumerate(rows):
                try:
                    # Clean data based on format
                    if file_format == "format2":
                        data = clean_row_data_format2(row)
                    else:
                        data = clean_row_data(row)

                    # Validate required fields
                    if not data.get("symbol_number") or not data.get("email"):
                        all_errors.append(
                            f"Row {index + 1}: Missing required fields (symbol_number or email)",
                        )
                        continue

                    # Process initial_image path
                    initial_image = data.get("initial_image", "").strip()
                    if initial_image:
                        data["initial_image"] = (
                            f"{institute.name}/candidatePhotos/{initial_image}"
                        )
                    else:
                        data["initial_image"] = None

                    symbol = data["symbol_number"]
                    email = data["email"].lower().strip()

                    # Basic validation
                    if not email or "@" not in email:
                        all_errors.append(f"Row {index + 1}: Invalid email format")
                        continue

                    random_password = "".join(
                        random.choices(string.ascii_letters + string.digits, k=8),
                    )

                    users_batch.append(
                        {
                            "email": email,
                            "password": random_password,
                            "is_candidate": True,
                        },
                    )

                    candidates_batch.append(
                        {
                            **data,
                            "institute": institute,
                            "generated_password": random_password,
                        },
                    )

                    # Process batch when it reaches batch_size
                    if len(candidates_batch) >= batch_size:
                        batch_created, batch_errors = process_batch(
                            users_batch,
                            candidates_batch,
                        )
                        processed_rows += batch_created
                        all_errors.extend(batch_errors)

                        users_batch.clear()
                        candidates_batch.clear()

                        # Update progress
                        progress = min(90, int(10 + 80 * (index + 1) / total_rows))
                        task.message = f"Processed {index + 1}/{total_rows} candidates"
                        task.progress = progress
                        task.save()

                except Exception as e:
                    error_msg = f"Row {index + 1}: {e!s}"
                    logger.exception(error_msg)
                    all_errors.append(error_msg)

            # Process remaining candidates in final batch
            if candidates_batch:
                batch_created, batch_errors = process_batch(
                    users_batch,
                    candidates_batch,
                )
                processed_rows += batch_created
                all_errors.extend(batch_errors)

            # Clean up uploaded file
            try:
                default_storage.delete(file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file {file_path}: {e!s}")

            logger.info(
                f"Completed processing. {processed_rows}/{total_rows} candidates created successfully",
            )

            # Set final task status - ALWAYS SUCCESS to prevent retry loops
            if processed_rows == 0:
                task.message = (
                    f"No candidates created. {len(all_errors)} errors occurred."
                )
                task.status = CeleryTask.get_status_value("FAILURE")
            elif all_errors:
                task.message = f"Completed with {len(all_errors)} errors. {processed_rows} candidates created."
                task.status = CeleryTask.get_status_value(
                    "SUCCESS",
                )  # Still success if some were created
            else:
                task.message = "Successfully processed all candidates"
                task.status = CeleryTask.get_status_value("SUCCESS")

            result_data = {
                "total_rows": total_rows,
                "processed_rows": processed_rows,
                "errors": all_errors[:50],  # Limit errors to prevent huge responses
                "total_errors": len(all_errors),
                "institute_name": institute.name,
                "file_type": file_extension,
                "format_used": file_format,
                "success_rate": f"{(processed_rows / total_rows * 100):.1f}%"
                if total_rows > 0
                else "0%",
            }

            task.result = str(result_data)
            task.progress = 100
            task.save()

            return result_data

        except Exception as e:
            logger.exception(f"Task failed: {e!s}")
            task.message = f"Task failed: {e!s}"
            task.status = CeleryTask.get_status_value("FAILURE")
            task.save()

            # CRITICAL: Never retry on database constraint errors
            error_str = str(e).lower()
            if any(
                phrase in error_str
                for phrase in ["duplicate key", "unique constraint", "already exists"]
            ):
                logger.error(
                    "Database constraint error - not retrying to prevent infinite loop",
                )
                return {
                    "status": "error",
                    "message": f"Database constraint error: {e!s}",
                }

            # Only retry for genuine system errors (max 2 retries)
            raise self.retry(countdown=30, max_retries=2, exc=e)


# Keep existing helper functions unchanged
def read_csv_file(file_path):
    """Read CSV file and return list of dictionaries"""
    with default_storage.open(file_path, "r") as csvfile:
        content = csvfile.read()
    csv_reader = csv.DictReader(content.splitlines())
    return list(csv_reader)


def read_excel_file(file_path):
    """Read Excel file and return list of dictionaries"""
    with default_storage.open(file_path, "rb") as excel_file:
        df = pd.read_excel(excel_file, engine="openpyxl")
        df = df.fillna("")
        df.columns = df.columns.astype(str).str.strip()
        return df.to_dict("records")


def clean_row_data(row):
    """Clean and validate row data - Format 1 (Original)"""

    def safe_int(value, default=0):
        if pd.isna(value) or value == "":
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default

    def safe_str(value):
        if pd.isna(value):
            return ""
        return str(value).strip()

    return {
        "admit_card_id": safe_int(row.get("Admit Card ID")),
        "profile_id": safe_int(row.get("Profile ID")),
        "symbol_number": safe_str(row.get("Symbol Number")),
        "exam_processing_id": safe_int(row.get("Exam Processing Id")),
        "gender": safe_str(row.get("Gender")).lower(),
        "citizenship_no": safe_str(row.get("Citizenship No.")),
        "first_name": safe_str(row.get("Firstname")),
        "middle_name": safe_str(row.get("Middlename")) or None,
        "last_name": safe_str(row.get("Lastname")),
        "dob_nep": safe_str(row.get("DOB (nep)")),
        "email": safe_str(row.get("email")).lower(),
        "phone": safe_str(row.get("phone")),
        "level_id": safe_int(row.get("Level ID")),
        "level": safe_str(row.get("Level")),
        "program_id": safe_int(row.get("Program ID")),
        "program": safe_str(row.get("Program")),
        "initial_image": safe_str(row.get("Profile Picture")),
    }


def clean_row_data_format2(row):
    """Clean and validate row data - Format 2 (New simplified format)"""

    def safe_str(value):
        if pd.isna(value):
            return ""
        return str(value).strip()

    # Parse full name
    full_name = safe_str(row.get("Name", ""))
    name_parts = full_name.split()

    if len(name_parts) == 1:
        first_name, middle_name, last_name = name_parts[0], None, ""
    elif len(name_parts) == 2:
        first_name, middle_name, last_name = name_parts[0], None, name_parts[1]
    elif len(name_parts) >= 3:
        first_name = name_parts[0]
        middle_name = " ".join(name_parts[1:-1])
        last_name = name_parts[-1]
    else:
        first_name, middle_name, last_name = "", None, ""

    level = safe_str(row.get("Level", ""))
    program = safe_str(row.get("Program", "")) or level

    return {
        "admit_card_id": 0,
        "profile_id": 0,
        "symbol_number": safe_str(row.get("Symbol Number")),
        "exam_processing_id": 0,
        "gender": "",
        "citizenship_no": "",
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "dob_nep": "",
        "email": safe_str(row.get("Email")).lower(),
        "phone": safe_str(row.get("Mobile")),
        "level_id": 0,
        "level": level,
        "program_id": 1,
        "program": program,
        "initial_image": "",
    }


def validate_file_format(file_path, expected_format=None):
    """
    Validate if the uploaded file has the correct format and required columns
    If expected_format is None, auto-detect the format
    """
    file_extension = os.path.splitext(file_path)[1].lower()

    try:
        if file_extension == ".csv":
            rows = read_csv_file(file_path)
        elif file_extension in [".xlsx", ".xls"]:
            rows = read_excel_file(file_path)
        else:
            return {
                "is_valid": False,
                "error": f"Unsupported file format: {file_extension}. Please upload CSV or Excel files.",
            }

        if not rows:
            return {
                "is_valid": False,
                "error": "File is empty or has no data rows.",
            }

        available_columns = set(rows[0].keys())

        # Auto-detect format if not specified
        if expected_format is None:
            detected_format = detect_file_format(rows)
            if detected_format == "unknown":
                return {
                    "is_valid": False,
                    "error": "Unable to detect file format. Please ensure your file matches one of the supported formats.",
                    "available_columns": list(available_columns),
                }
            expected_format = detected_format

        # Define required columns based on format
        if expected_format == "format2":
            required_columns = ["Name", "Mobile", "Email", "Symbol Number", "Level"]
        else:  # format1
            required_columns = [
                "Admit Card ID",
                "Profile ID",
                "Symbol Number",
                "Exam Processing Id",
                "Gender",
                "Citizenship No.",
                "Firstname",
                "Lastname",
                "DOB (nep)",
                "email",
                "phone",
                "Level ID",
                "Level",
                "Program ID",
                "Program",
                "Profile Picture",
            ]

        # Check if required columns exist
        missing_columns = [
            col for col in required_columns if col not in available_columns
        ]

        if missing_columns:
            return {
                "is_valid": False,
                "error": f"Missing required columns for {expected_format}: {', '.join(missing_columns)}",
                "available_columns": list(available_columns),
                "detected_format": expected_format,
            }

        return {
            "is_valid": True,
            "total_rows": len(rows),
            "columns": list(available_columns),
            "file_type": file_extension,
            "detected_format": expected_format,
        }

    except Exception as e:
        return {
            "is_valid": False,
            "error": f"Error reading file: {e!s}",
        }


def detect_file_format(rows):
    """
    Auto-detect the file format based on available columns
    """
    if not rows:
        return "unknown"

    available_columns = set(rows[0].keys())

    # Check for format2 columns (simplified format)
    format2_columns = {"Name", "Mobile", "Email", "Symbol Number", "Level"}
    format2_match = len(format2_columns.intersection(available_columns))

    # Check for format1 columns (detailed format)
    format1_columns = {
        "Admit Card ID",
        "Profile ID",
        "Symbol Number",
        "Exam Processing Id",
        "Gender",
        "Citizenship No.",
        "Firstname",
        "Lastname",
        "DOB (nep)",
        "email",
        "phone",
        "Level ID",
        "Level",
        "Program ID",
        "Program",
        "Profile Picture",
    }
    format1_match = len(format1_columns.intersection(available_columns))

    # Determine which format has better match
    if format2_match >= 4:  # At least 4 out of 5 format2 columns
        return "format2"
    if format1_match >= 12:  # At least 12 out of 16 format1 columns
        return "format1"
    return "unknown"
