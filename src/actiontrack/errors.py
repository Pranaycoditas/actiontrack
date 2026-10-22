class ActiontrackError(Exception):
    """Base for all expected errors."""


class UsageError(ActiontrackError):
    """Bad argument, unknown ID or owner. Exit 2."""


class StoreError(ActiontrackError):
    """Database failure. Exit 1."""


class DraftError(ActiontrackError):
    """Gmail rejected or failed the draft. Exit 1."""


class SinkUnavailable(DraftError):
    """Connector missing or unauthorized. Exit 1."""
