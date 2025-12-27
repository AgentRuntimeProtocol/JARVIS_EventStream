class EventStreamError(Exception):
    pass


class NotFoundError(EventStreamError):
    pass


class ConflictError(EventStreamError):
    pass


class ValidationError(EventStreamError):
    pass
