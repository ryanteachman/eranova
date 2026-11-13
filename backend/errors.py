"""API errors that map to an HTTP status and the {error, detail} body."""


class ApiError(Exception):
    """Base class: an error the API reports to the caller as {error, detail}."""
    status = 500
    code = "internal_error"


class BadRequest(ApiError):
    status = 400
    code = "bad_request"


class NotFound(ApiError):
    status = 404
    code = "not_found"


class Conflict(ApiError):
    status = 409
    code = "conflict"
