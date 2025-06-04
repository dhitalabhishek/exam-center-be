# tasks.py

import csv
import logging
import os

import pandas as pd
from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import transaction

from appAuthentication.models import Candidate
from appInstitutions.models import Institute

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_candidates_file(self, file_path, institute_id):
    try:
        institute = Institute.objects.get(id=institute_id)
        file_extension = os.path.splitext(file_path)[1].lower()

        # Read file
        if file_extension == ".csv":
            rows = read_csv_file(file_path)
        elif file_extension in [".xlsx", ".xls"]:
            rows = read_excel_file(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}")

        total_rows = len(rows)
        batch_size = 100  # Process in batches of 100
        processed_rows = 0
        errors = []

        # Track duplicates within the file
        seen_symbols_in_file = set()
        seen_emails_in_file = set()

        logger.info(f"Processing {total_rows} candidates for {institute.name}")

        # Process in batches
        for batch_start in range(0, total_rows, batch_size):
            batch_end = min(batch_start + batch_size, total_rows)
            batch = rows[batch_start:batch_end]
            batch_errors = []
            valid_candidates = []

            # Collect symbols/emails for batch validation
            batch_symbols = []
            batch_emails = []
            cleaned_data = []

            # Clean data and collect identifiers
            for idx, row in enumerate(batch):
                abs_idx = batch_start + idx
                try:
                    data = clean_row_data(row)
                    symbol = data["symbol_number"]
                    email = data["email"]

                    # Skip duplicate within file
                    if symbol in seen_symbols_in_file:
                        batch_errors.append(
                            f"Row {abs_idx + 1}: Duplicate symbol {symbol} in file",
                        )
                        continue
                    if email in seen_emails_in_file:
                        batch_errors.append(
                            f"Row {abs_idx + 1}: Duplicate email {email} in file",
                        )
                        continue

                    batch_symbols.append(symbol)
                    batch_emails.append(email)
                    cleaned_data.append(data)

                except Exception as e:
                    batch_errors.append(f"Row {abs_idx + 1}: {e!s}")

            # Batch database checks (2 queries per batch)
            existing_symbols = set(
                Candidate.objects.filter(symbol_number__in=batch_symbols).values_list(
                    "symbol_number", flat=True,
                ),
            )
            existing_emails = set(
                User.objects.filter(email__in=batch_emails).values_list(
                    "email", flat=True,
                ),
            )

            # Validate against DB
            for data in cleaned_data:
                abs_idx = batch_start + cleaned_data.index(data)  # Approximate index
                symbol = data["symbol_number"]
                email = data["email"]

                if symbol in existing_symbols:
                    batch_errors.append(
                        f"Row {abs_idx + 1}: Symbol {symbol} exists in DB",
                    )
                    continue
                if email in existing_emails:
                    batch_errors.append(
                        f"Row {abs_idx + 1}: Email {email} exists in DB",
                    )
                    continue

                # Add to valid candidates
                valid_candidates.append(data)
                seen_symbols_in_file.add(symbol)
                seen_emails_in_file.add(email)

            # Bulk create valid candidates
            if valid_candidates:
                users_batch = [
                    {"email": c["email"], "raw_password": c["dob_nep"]}
                    for c in valid_candidates
                ]
                candidates_batch = [
                    {**c, "institute": institute} for c in valid_candidates
                ]

                try:
                    created_count = process_batch(users_batch, candidates_batch)
                    processed_rows += created_count
                except Exception as e:
                    batch_errors.append(f"Batch create failed: {e!s}")

            errors.extend(batch_errors)

            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": batch_end,
                    "total": total_rows,
                    "processed": processed_rows,
                    "errors": len(errors),
                },
            )

        # Cleanup
        default_storage.delete(file_path)
        logger.info(f"Processed {processed_rows}/{total_rows} candidates")

        return {
            "total_rows": total_rows,
            "processed_rows": processed_rows,
            "errors": errors,
            "institute_name": institute.name,
        }

    except Exception as e:
        logger.error(f"Task failed: {e!s}")
        raise self.retry(countdown=60, max_retries=3, exc=e)


@shared_task(bind=True)
def process_candidates_csv(self, file_path, institute_id):
    """
    Legacy function—redirects to the new processor.
    """
    return process_candidates_file(self, file_path, institute_id)


def read_csv_file(file_path):
    """
    Read CSV file and return list of dictionaries.
    """
    with default_storage.open(file_path, "r") as csvfile:
        content = csvfile.read()

    csv_reader = csv.DictReader(content.splitlines())
    return list(csv_reader)


def read_excel_file(file_path):
    """
    Read Excel file (XLSX or XLS) and return list of dictionaries.
    """
    with default_storage.open(file_path, "rb") as excel_file:
        # Read the Excel file into a pandas DataFrame
        df = pd.read_excel(excel_file, engine="openpyxl")

        # Convert DataFrame to list of dicts, replacing NaN with ""
        df = df.fillna("")
        df.columns = df.columns.astype(str).str.strip()
        return df.to_dict("records")


def clean_row_data(row):
    """
    Clean and validate row data from CSV or Excel.
    Converts numeric fields safely to int, strings to stripped strings.
    """

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
    }


def clean_csv_row(row):
    """
    Legacy function—redirects to clean_row_data.
    """
    return clean_row_data(row)


@transaction.atomic
def process_batch(users_batch, candidates_batch):
    """
    Bulk-create Users and Candidates in one shot.

    users_batch:   List of dicts: { "email": ..., "raw_password": ... }
    candidates_batch: List of dicts matching Candidate model fields (minus 'user').
    """
    try:
        # 1) Build User instances (unsaved)
        user_objs = []
        for u in users_batch:
            # Create a User object (unsaved) so we can hash the password
            user = User(email=u["email"], is_candidate=True)
            user.set_password(u["raw_password"])
            user_objs.append(user)

        # 2) Bulk‐insert all users at once
        User.objects.bulk_create(user_objs)

        # At this point, user_objs have their primary key (id) populated if using Django 3.2+.

        # 3) Build Candidate instances (unsaved), linking to the just‐created users
        candidate_objs = []
        for user_obj, candidate_data in zip(user_objs, candidates_batch, strict=False):
            candidate = Candidate(user=user_obj, **candidate_data)
            candidate_objs.append(candidate)

        # 4) Bulk‐insert all candidates at once
        Candidate.objects.bulk_create(candidate_objs)

        return len(user_objs)

    except Exception as e:
        logger.error(f"Batch processing failed: {e!s}")
        raise


def validate_file_format(file_path):
    """
    Validate that the uploaded file has required columns.
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
            return {"is_valid": False, "error": "File is empty or has no data rows."}

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

    except Exception as e:
        return {"is_valid": False, "error": f"Error reading file: {e!s}"}
