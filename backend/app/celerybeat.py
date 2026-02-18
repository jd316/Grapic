"""Celery Beat schedule for periodic tasks."""

from celery.schedules import crontab
from app.celery_app import celery_app

# Configure periodic tasks
celery_app.conf.beat_schedule = {
    # Run auto-retry for failed photos every 5 minutes
    "scan-and-retry-failed-photos": {
        "task": "app.tasks.scan_and_retry_all_events",
        "schedule": 300.0,  # 5 minutes
    },

    # Run expired event cleanup every hour
    "cleanup-expired-events": {
        "task": "app.tasks.cleanup_expired_events_task",
        "schedule": crontab(minute=0),  # Every hour at :00
    },

    # Optional: Daily backup reminder (does not actually backup, just logs)
    "daily-backup-reminder": {
        "task": "app.tasks.backup_reminder",
        "schedule": crontab(hour=2, minute=0),  # 2 AM daily
    },
}

celery_app.conf.timezone = "UTC"
