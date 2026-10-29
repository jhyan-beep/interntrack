import logging
import time

from app.database import get_settings
from app.email_delivery import process_outbox_batch
from app.observability import configure_logging
from app.reminders import enqueue_due_deadline_reminders


configure_logging(get_settings())
logger = logging.getLogger("interntrack.email_worker")


def run_worker() -> None:
    settings = get_settings()
    poll_seconds = settings.email_worker_poll_seconds
    next_reminder_scan = 0.0
    logger.info("InternTrack email worker started")
    while True:
        now = time.monotonic()
        if now >= next_reminder_scan:
            queued = enqueue_due_deadline_reminders()
            if queued:
                logger.info("Queued %s deadline reminder(s)", queued)
            next_reminder_scan = now + settings.reminder_scan_interval_seconds
        processed = process_outbox_batch()
        if processed == 0:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
