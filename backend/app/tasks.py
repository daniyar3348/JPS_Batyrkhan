"""Import every module that defines worker tasks, so the tasks are registered."""

from app.core import jobs as core_jobs
from app.modules.files import tasks as file_tasks
from app.modules.identity import tasks as identity_tasks
from app.modules.notifications import tasks as notification_tasks
from app.modules.similarity import tasks as similarity_tasks

__all__ = ["core_jobs", "file_tasks", "identity_tasks", "notification_tasks", "similarity_tasks"]
