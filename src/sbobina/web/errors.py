class AppError(Exception):
    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(AppError):
    def __init__(self, entity: str, id: str) -> None:
        super().__init__(message=f"{entity} {id} non trovato", code="NOT_FOUND")


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="VALIDATION_ERROR")


class ConflictError(AppError):
    """The request clashes with the current state of the resource (HTTP 409)."""


class ServiceUnavailableError(AppError):
    """A dependency the request needs is unreachable (HTTP 503)."""


class GatewayTimeoutError(AppError):
    """An external call exceeded its time budget (HTTP 504)."""


class JobNotCancellableError(ConflictError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            message=f"Job {job_id} non annullabile", code="JOB_NOT_CANCELLABLE"
        )
