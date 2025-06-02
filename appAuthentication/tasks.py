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


@shared_task(bind=True)
def process_candidates_csv(self, file_path, institute_id):
    """
    Process CSV file and create candidate records in batches
    """
    try:
        institute = Institute.objects.get(id=institute_id)

        with default_storage.open(file_path, "r") as csvfile:
            content = csvfile.read()

        csv_reader = csv.DictReader(content.splitlines())

        batch_size = 100
        processed_rows = 0
        errors = []
        users_batch = []
        candidates_batch = []

        rows = list(csv_reader)
        total_rows = len(rows)

        logger.info(
            f"Starting to process {total_rows} candidates for institute {institute.name}",
        )

        for index, row in enumerate(rows):
            try:
                data = clean_csv_row(row)

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
                logger.exception(error_msg)
                errors.append(error_msg)

        if candidates_batch:
            processed_rows += process_batch(users_batch, candidates_batch)

        default_storage.delete(file_path)

        logger.info(
            f"Completed processing. {processed_rows}/{total_rows} candidates created successfully",
        )

        return {
            "total_rows": total_rows,
            "processed_rows": processed_rows,
            "errors": errors,
            "institute_name": institute.name,
        }

    except Exception as e:
        logger.error(f"Task failed: {e!s}")
        raise self.retry(countdown=60, max_retries=3, exc=e)


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
    try:
        created_users = [User.objects.create_user(**u) for u in users_batch]

        for user, candidate_data in zip(created_users, candidates_batch, strict=False):
            Candidate.objects.create(**candidate_data, user=user)

        return len(created_users)

    except Exception as e:
        logger.error(f"Batch processing failed: {e!s}")
        raise
