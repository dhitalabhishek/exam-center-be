# tasks.py
import csv
import logging
import random
import string

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import transaction

from appAuthentication.models import Candidate
from appInstitutions.models import Institute

User = get_user_model()
logger = logging.getLogger(__name__)


# for importing CSV data to candidates
@shared_task(bind=True)
def process_candidates_csv(self, file_path, institute_id):
    """
    Process CSV file and create candidate records in batches
    """
    try:
        institute = Institute.objects.get(id=institute_id)

        # Read the CSV file
        with default_storage.open(file_path, "r") as csvfile:
            # Read the content and detect encoding if needed
            content = csvfile.read()

        # Parse CSV content
        csv_reader = csv.DictReader(content.splitlines())

        total_rows = 0
        processed_rows = 0
        errors = []
        batch_size = 100

        candidates_batch = []
        users_batch = []

        # Count total rows first
        rows = list(csv_reader)
        total_rows = len(rows)

        (
            logger.info(
                f"Starting to process {total_rows} candidates for institute {institute.name}",  # noqa: E501, G004
            ),
        )

        for index, row in enumerate(rows):
            try:
                # Clean and validate row data
                cleaned_data = clean_csv_row(row)

                # Check if candidate already exists
                if Candidate.objects.filter(
                    symbol_number=cleaned_data["symbol_number"],
                ).exists():
                    (
                        errors.append(
                            f"Row {index + 1}: Candidate with symbol number \
                                {cleaned_data['symbol_number']} already exists",
                        ),
                    )
                    continue

                # Check if user already exists
                if User.objects.filter(email=cleaned_data["email"]).exists():
                    errors.append(
                        f"Row {index + 1}: User with email {cleaned_data['email']} already exists",  # noqa: E501
                    )
                    continue

                # Generate random password
                random_password = "".join(
                    random.choices(string.ascii_letters + string.digits, k=8),  # noqa: S311
                )

                # Prepare user data
                user_data = {
                    "email": cleaned_data["email"],
                    "password": random_password,
                    "is_candidate": True,
                }

                # Prepare candidate data
                candidate_data = {
                    **cleaned_data,
                    "institute": institute,
                    "generated_password": random_password,
                }

                # Add to batch
                users_batch.append(user_data)
                candidates_batch.append(candidate_data)

                # Process batch when it reaches batch_size
                if len(candidates_batch) >= batch_size:
                    success_count = process_batch(users_batch, candidates_batch)
                    processed_rows += success_count
                    candidates_batch = []
                    users_batch = []

                    # Update task progress
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "current": index + 1,
                            "total": total_rows,
                            "processed": processed_rows,
                            "errors": len(errors),
                        },
                    )

            except Exception as e:
                error_msg = f"Row {index + 1}: {e!s}"
                errors.append(error_msg)
                logger.exception(error_msg)
                continue

        # Process remaining batch
        if candidates_batch:
            success_count = process_batch(users_batch, candidates_batch)
            processed_rows += success_count

        # Clean up the uploaded file
        default_storage.delete(file_path)

        # Final result
        result = {
            "total_rows": total_rows,
            "processed_rows": processed_rows,
            "errors": errors,
            "institute_name": institute.name,
        }

        logger.info(
            f"Completed processing. {processed_rows}/{total_rows} candidates created successfully",  # noqa: E501, G004
        )

        return result  # noqa: TRY300

    except Exception as e:  # noqa: BLE001
        logger.error(f"Task failed: {e!s}")  # noqa: G004, TRY400
        raise self.retry(countdown=60, max_retries=3, exc=e)  # noqa: B904


def clean_csv_row(row):
    """
    Clean and validate CSV row data
    """
    return {
        "admit_card_id": int(row.get("Admit Card ID", 0)),
        "profile_id": int(row.get("Profile ID", 0)),
        "symbol_number": row.get("Symbol Number", "").strip(),
        "exam_processing_id": int(row.get("Exam Processing Id", 0)),
        "gender": row.get("Gender", "").strip().lower(),
        "citizenship_no": row.get("Citizenship No.", "").strip(),
        "first_name": row.get("Firstname", "").strip(),
        "middle_name": row.get("Middlename", "").strip() or None,
        "last_name": row.get("Lastname", "").strip(),
        "dob_nep": row.get("DOB (nep)", "").strip(),
        "email": row.get("email", "").strip().lower(),
        "phone": row.get("phone", "").strip(),
        "level_id": int(row.get("Level ID", 0)),
        "level": row.get("Level", "").strip(),
        "program_id": int(row.get("Program ID", 0)),
        "program": row.get("Program", "").strip(),
    }


@transaction.atomic
def process_batch(users_batch, candidates_batch):
    """
    Process a batch of users and candidates
    """
    created_users = []
    created_candidates = []

    try:
        # Create users first
        for user_data in users_batch:
            user = User.objects.create_user(**user_data)
            created_users.append(user)

        # Create candidates
        for i, candidate_data in enumerate(candidates_batch):
            candidate_data["user"] = created_users[i]
            candidate = Candidate.objects.create(**candidate_data)
            created_candidates.append(candidate)

        return len(created_candidates)

    except Exception as e:
        logger.error(f"Batch processing failed: {e!s}")  # noqa: G004, TRY400
        # The transaction will be rolled back automatically
        raise e  # noqa: TRY201
