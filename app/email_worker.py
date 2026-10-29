import logging
import time

from app.database import get_settings
from app.email_delivery import process_outbox_batch


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interntrack.email_worker")


def run_worker() -> None:
    poll_seconds = get_settings().email_worker_poll_seconds
    logger.info("InternTrack email worker started")
    while True:
        processed = process_outbox_batch()
        if processed == 0:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()

