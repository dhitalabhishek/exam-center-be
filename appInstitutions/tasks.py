# appInstitutions/tasks.py

import logging

from celery import chain
from celery import shared_task

logger = logging.getLogger(__name__)
BATCH_SIZE = 500  # Adjust this batch size if you want larger or smaller chunks


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def delete_users_by_institute(self, institute_id):
    """
    1) In batches of BATCH_SIZE, delete all User objects whose linked Candidate.institute == institute_id.
       Because Candidate.user has on_delete=CASCADE, deleting each User also removes that Candidate.
    2) Repeat until no Candidate remains for this institute.
    3) Return institute_id so the chained task can delete the Institute itself.
    """
    try:
        # Import inside the function to avoid a circular-import at module load time
        from django.contrib.auth import get_user_model

        from appAuthentication.models import Candidate

        User = get_user_model()
        total_deleted = 0

        # Keep looping as long as there are still Candidate rows for this institute
        qs = Candidate.objects.filter(institute_id=institute_id).select_related("user")
        while qs.exists():
            batch = qs[:BATCH_SIZE]
            user_ids = [cand.user.id for cand in batch if cand.user_id]

            if user_ids:
                # Deleting the Users in one call; each User→Candidate will cascade
                deleted_info = User.objects.filter(id__in=user_ids).delete()
                total_deleted += deleted_info[0]
                logger.info(
                    "[delete_users_by_institute] Deleted %d users (cascade_total=%s) for institute=%s",
                    len(user_ids),
                    deleted_info,
                    institute_id,
                )

            # Refresh the queryset to see if any Candidate rows remain
            qs = Candidate.objects.filter(institute_id=institute_id).select_related(
                "user",
            )

        logger.info(
            "[delete_users_by_institute] Finished deleting all users for institute %s; total rows deleted (incl. cascades)=%d",
            institute_id,
            total_deleted,
        )
        return institute_id

    except Exception as exc:
        logger.exception(
            "[delete_users_by_institute] Error while deleting users for institute %s",
            institute_id,
        )
        # Retry up to 3 times with 30s delay
        raise self.retry(exc=exc)


@shared_task(bind=True)
def delete_institute_record(self, institute_id):
    """
    Deletes the Institute record itself. Should run only after delete_users_by_institute
    has removed every Candidate/User for that institute.
    """
    try:
        from django.db import transaction

        from appInstitutions.models import Institute

        with transaction.atomic():
            inst = Institute.objects.get(pk=institute_id)
            inst.delete()  # This cascades on Subjects, Programs, etc.
            logger.info("[delete_institute_record] Institute %s deleted.", institute_id)
    except Institute.DoesNotExist:
        logger.warning(
            "[delete_institute_record] Institute %s does not exist.", institute_id,
        )
    except Exception as exc:
        logger.exception(
            "[delete_institute_record] Failed to delete Institute %s", institute_id,
        )
        raise self.retry(exc=exc)

    return f"Institute {institute_id} removed"


def delete_institute_and_all_users(institute_id):
    """
    Utility function to enqueue:
      1) delete_users_by_institute(institute_id)
      2) delete_institute_record(institute_id)
    in a chain. Returns the AsyncResult so you can monitor if desired.
    """
    # NOTE: bind institute_id only into the first task. The second task gets it
    # automatically from the first task’s return value.
    return chain(
        delete_users_by_institute.s(institute_id),
        delete_institute_record.s(),
    ).delay()
