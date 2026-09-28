from typing import Optional

from fastapi import status

from app.domain.enums import ErrorCode


class AppError(Exception):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, code: ErrorCode, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    @classmethod
    def from_code(cls, code: str, message: str, details: Optional[dict] = None):
        error = cls(ErrorCode(code), message, details)
        status_by_code = {
            ErrorCode.JOB_NOT_FOUND: status.HTTP_404_NOT_FOUND,
            ErrorCode.INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
            ErrorCode.SERVICE_BUSY: status.HTTP_409_CONFLICT,
        }
        if error.code == ErrorCode.INVALID_REQUEST:
            error.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        else:
            error.status_code = status_by_code.get(error.code, cls.status_code)
        return error


class ArtifactNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, artifact_id: str):
        super().__init__(
            ErrorCode.JOB_NOT_FOUND,
            "artifact not found",
            {"artifact_id": artifact_id},
        )


class JobNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, job_id: str):
        super().__init__(
            ErrorCode.JOB_NOT_FOUND,
            "job not found",
            {"job_id": job_id},
        )


class JobAlreadyFinishedError(AppError):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, job_id: str):
        super().__init__(
            ErrorCode.JOB_ALREADY_FINISHED,
            "job already finished",
            {"job_id": job_id},
        )
