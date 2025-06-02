import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)
BATCH_SIZE = 500

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def delete_institute_and_all_users(self, institute_id):
    """
    Single task that:
    1) Deletes all users/candidates in batches
    2) Deletes the institute record
    No chaining needed - everything happens in one task to avoid loops.
    """
    try:
        # Import inside the function to avoid circular imports
        from django.contrib.auth import get_user_model

        from appAuthentication.models import Candidate
        from appInstitutions.models import Institute

        User = get_user_model()
        total_deleted = 0

        logger.info(f"[delete_institute_and_all_users] Starting deletion for institute {institute_id}")

        # Step 1: Delete all users/candidates in batches
        qs = Candidate.objects.filter(institute_id=institute_id).select_related("user")
        while qs.exists():
            batch = qs[:BATCH_SIZE]
            user_ids = [cand.user.id for cand in batch if cand.user_id]

            if user_ids:
                # Delete users in batch - cascade will remove candidates
                deleted_info = User.objects.filter(id__in=user_ids).delete()
                total_deleted += deleted_info[0]
                logger.info(
                    f"[delete_institute_and_all_users] Deleted {len(user_ids)} users "
                    f"(cascade_total={deleted_info}) for institute={institute_id}",
                )

            # Refresh queryset
            qs = Candidate.objects.filter(institute_id=institute_id).select_related("user")

        logger.info(
            f"[delete_institute_and_all_users] Finished deleting all users for institute {institute_id}; "
            f"total rows deleted (incl. cascades)={total_deleted}",
        )

        # Step 2: Delete the institute itself
        with transaction.atomic():
            try:
                inst = Institute.objects.get(pk=institute_id)
                # Use Django's ORM delete() - this will cascade to Subject, Program, etc.
                inst.delete()
                logger.info(f"[delete_institute_and_all_users] Institute {institute_id} deleted successfully.")
            except Institute.DoesNotExist:
                logger.warning(f"[delete_institute_and_all_users] Institute {institute_id} does not exist.")

        return f"Institute {institute_id} and all related data removed successfully"

    except Exception as exc:
        logger.exception(
            f"[delete_institute_and_all_users] Error while deleting institute {institute_id}",
        )
        # Retry up to 3 times with 30s delay
        raise self.retry(exc=exc)








