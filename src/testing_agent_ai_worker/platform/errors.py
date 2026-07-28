"""Platform polling errors."""


class TaskSourceError(RuntimeError):
    """Raised when platform task polling cannot complete successfully."""


class SkillSourceError(RuntimeError):
    """Raised when platform project skill syncing cannot complete successfully."""
