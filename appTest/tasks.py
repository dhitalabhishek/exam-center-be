import time

from celery import shared_task


@shared_task
def fake_task(duration=5):
    print(f"Fake task started, sleeping for {duration} seconds...")
    time.sleep(duration)
    print("Fake task done!")
    return f"Slept for {duration} seconds"
