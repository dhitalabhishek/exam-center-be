# appAuthentication/tasks.py
import csv
import logging
import os
import random
import string

import pandas as pd
from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import transaction

from appAuthentication.models import Candidate
from appCore.models import CeleryTask

# Add these imports
from appCore.utils.track_task import track_task
from appInstitutions.models import Institute

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_candidates_file(self, file_path, institute_id):
    """
    Process CSV or Excel file and create candidate records in batches
    """
    # Wrap the entire task with track_task context manager
    with track_task(self.request.id, "process_candidates_file") as task:
        try:
            task.message = "Starting candidate import process"
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

            batch_size = 100
            processed_rows = 0
            errors = []
            users_batch = []
            candidates_batch = []

            logger.info(
                f"Starting to process {total_rows} candidates from {file_extension} file for institute {institute.name}",
            )

            task.message = f"Processing {total_rows} candidates"
            task.progress = 10
            task.save()

            for index, row in enumerate(rows):
                try:
                    data = clean_row_data(row)

                    symbol = data["symbol_number"]
                    email = data["email"]

                    if Candidate.objects.filter(symbol_number=symbol).exists():
                        errors.append(
                            f"Row {index + 1}: Candidate with symbol number {symbol} already exists",
                        )
                        continue

                    if User.objects.filter(email=email).exists():
                        errors.append(
                            f"Row {index + 1}: User with email {email} already exists",
                        )
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

                    if len(candidates_batch) >= batch_size:
                        processed_rows += process_batch(users_batch, candidates_batch)
                        users_batch.clear()
                        candidates_batch.clear()

                        # Update progress after each batch
                        progress = min(90, int(10 + 80 * (index + 1) / total_rows))
                        task.message = f"Processed {index + 1}/{total_rows} candidates"
                        task.progress = progress
                        task.save()

                except Exception as e:
                    error_msg = f"Row {index + 1}: {e!s}"
                    logger.exception(error_msg)
                    errors.append(error_msg)

            # Process remaining candidates
            if candidates_batch:
                processed_rows += process_batch(users_batch, candidates_batch)

            # Clean up the uploaded file
            default_storage.delete(file_path)

            logger.info(
                f"Completed processing. {processed_rows}/{total_rows} candidates created successfully",
            )

            # Update task status
            if errors:
                task.message = f"Completed with {len(errors)} errors"
                task.status = CeleryTask.get_status_value("RETRY")
            else:
                task.message = "Successfully processed all candidates"
                task.status = CeleryTask.get_status_value("SUCCESS")

            result_data = {
                "total_rows": total_rows,
                "processed_rows": processed_rows,
                "errors": errors,
                "institute_name": institute.name,
                "file_type": file_extension,
            }

            task.result = str(result_data)

            task.progress = 100
            task.save()

            return result_data  # noqa: TRY300

        except Exception as e:
            logger.exception(f"Task failed: {e!s}")
            task.message = f"Task failed: {e!s}"
            task.status = CeleryTask.get_status_value("FAILURE")
            task.save()
            raise self.retry(countdown=60, max_retries=3, exc=e)  # noqa: B904


# Keep the old function for backward compatibility
@shared_task(bind=True)
def process_candidates_csv(self, file_path, institute_id):
    """
    Legacy function - now redirects to the new file processor
    """
    return process_candidates_file(self, file_path, institute_id)


def read_csv_file(file_path):
    """
    Read CSV file and return list of dictionaries
    """
    with default_storage.open(file_path, "r") as csvfile:
        content = csvfile.read()

    csv_reader = csv.DictReader(content.splitlines())
    return list(csv_reader)


def read_excel_file(file_path):
    """
    Read Excel file and return list of dictionaries
    """
    with default_storage.open(file_path, "rb") as excel_file:
        # Read the Excel file into a pandas DataFrame
        df = pd.read_excel(excel_file, engine="openpyxl")

        # Convert DataFrame to list of dictionaries
        # Handle NaN values by converting them to empty strings
        df = df.fillna("")

        # Convert all column names to strings and strip whitespace
        df.columns = df.columns.astype(str).str.strip()

        return df.to_dict("records")


def clean_row_data(row):
    """
    Clean and validate row data from CSV or Excel
    Handles both string and numeric data types
    """

    def safe_int(value, default=0):
        """Safely convert value to int"""
        if pd.isna(value) or value == "":
            return default
        try:
            return int(
                float(value),
            )  # Convert through float first to handle decimal strings
        except (ValueError, TypeError):
            return default

    def safe_str(value):
        """Safely convert value to string"""
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
    }


# Keep the old function for backward compatibility
def clean_csv_row(row):
    """
    Legacy function - now redirects to the new cleaner
    """
    return clean_row_data(row)


@transaction.atomic
def process_batch(users_batch, candidates_batch):
    """
    Process a batch of users and candidates
    """
    try:
        created_users = [User.objects.create_user(**u) for u in users_batch]

        for user, candidate_data in zip(created_users, candidates_batch, strict=False):
            Candidate.objects.create(**candidate_data, user=user)

        return len(created_users)

    except Exception as e:
        logger.error(f"Batch processing failed: {e!s}")
        raise


def validate_file_format(file_path):
    """
    Validate if the uploaded file has the correct format and required columns
    """
    file_extension = os.path.splitext(file_path)[1].lower()
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
    ]

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

        # Check if required columns exist
        available_columns = set(rows[0].keys())
        missing_columns = [
            col for col in required_columns if col not in available_columns
        ]

        if missing_columns:
            return {
                "is_valid": False,
                "error": f"Missing required columns: {', '.join(missing_columns)}",
                "available_columns": list(available_columns),
            }

        return {
            "is_valid": True,
            "total_rows": len(rows),
            "columns": list(available_columns),
            "file_type": file_extension,
        }

    except Exception as e:  # noqa: BLE001
        return {
            "is_valid": False,
            "error": f"Error reading file: {e!s}",
        }
