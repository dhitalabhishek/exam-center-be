# appInstitutions/tasks/delete_institute.py

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction

from appAuthentication.models import Candidate
from appCore.models import CeleryTask
from appCore.utils.track_task import track_task
from appInstitutions.models import Institute

logger = logging.getLogger(__name__)
BATCH_SIZE = 500


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def delete_institute_and_all_users(self, institute_id):
    """
    Single task that:
    1) Deletes all users/candidates in batches
    2) Deletes the institute record
    All progress/status/result is tracked via CeleryTask through track_task.
    """
    with track_task(self.request.id, "delete_institute_and_all_users") as task:
        try:
            User = get_user_model()
            total_deleted = 0

            task.message = f"Starting deletion for institute {institute_id}"
            task.progress = 5
            task.save()

            logger.info(
                f"[delete_institute_and_all_users] Starting deletion for institute {institute_id}",
            )

            # Step 1: Delete all users/candidates in batches
            qs = Candidate.objects.filter(institute_id=institute_id).select_related(
                "user",
            )
            while qs.exists():
                batch = qs[:BATCH_SIZE]
                user_ids = [cand.user.id for cand in batch if cand.user_id]

                if user_ids:
                    deleted_info = User.objects.filter(id__in=user_ids).delete()
                    deleted_count = deleted_info[0]
                    total_deleted += deleted_count

                    task.message = (
                        f"Deleted {len(user_ids)} users "
                        f"(cascade_deleted={deleted_count})"
                    )
                    # Rough progress: assume step 1 is up to 80%
                    task.progress = min(
                        80, int(5 + 75 * (total_deleted / max(1, len(qs)))),
                    )
                    task.save()

                    logger.info(
                        f"[delete_institute_and_all_users] Deleted {len(user_ids)} users "
                        f"(cascade_total={deleted_info}) for institute={institute_id}",
                    )

                # Refresh queryset for next batch
                qs = Candidate.objects.filter(institute_id=institute_id).select_related(
                    "user",
                )

            logger.info(
                f"[delete_institute_and_all_users] Finished deleting all users for institute {institute_id}; "
                f"total rows deleted (incl. cascades)={total_deleted}",
            )

            # Step 2: Delete the institute itself
            task.message = "Deleting institute record"
            task.progress = 90
            task.save()

            with transaction.atomic():
                try:
                    inst = Institute.objects.get(pk=institute_id)
                    inst.delete()
                    task.message = f"Institute {institute_id} deleted successfully"
                    logger.info(
                        f"[delete_institute_and_all_users] Institute {institute_id} deleted successfully.",
                    )
                except Institute.DoesNotExist:
                    task.message = f"Institute {institute_id} does not exist"
                    logger.warning(
                        f"[delete_institute_and_all_users] Institute {institute_id} does not exist.",
                    )

            task.status = CeleryTask.STATUS_CHOICES[5][0]  # SUCCESS
            result_data = {
                "institute_id": institute_id,
                "total_deleted_users": total_deleted,
            }
            task.result = str(result_data)
            task.progress = 100
            task.save()

            return result_data

        except Exception as exc:
            logger.exception(
                f"[delete_institute_and_all_users] Error while deleting institute {institute_id}",
            )

            task.message = f"Task failed: {exc!s}"
            task.status = CeleryTask.STATUS_CHOICES[4][0]  # FAILURE
            task.result = str({"institute_id": institute_id, "error": str(exc)})
            task.save()

            raise self.retry(exc=exc)
