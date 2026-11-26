"""Import every module that defines worker tasks, so the tasks are registered."""

from app.core import jobs as core_jobs
from app.modules.identity import tasks as identity_tasks
from app.modules.notifications import tasks as notification_tasks

__all__ = ["core_jobs", "identity_tasks", "notification_tasks"]
