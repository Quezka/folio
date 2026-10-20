"""Errors the use cases raise. Their messages are shown to the user (translated)."""


class ApplicationError(Exception):
    """Something the user can understand and act on."""


class NotFound(ApplicationError):
    pass


class NotOpenError(ApplicationError):
    """No database is open."""


class FileFormatError(ApplicationError):
    """The file isn't a database Folio can open."""


class FileAccessError(ApplicationError):
    """The file couldn't be read or written (missing, no permission, disk full…)."""


class ConstraintError(ApplicationError):
    """The change breaks a rule of the table (required, unique, relationship…)."""


class IncompleteRowError(ApplicationError):
    """A new row is still missing values it needs."""


class DesignError(ApplicationError):
    """A table, query, form or report design that can't be saved."""


class UpdateError(ApplicationError):
    """Checking for, downloading or installing a new version didn't work."""
