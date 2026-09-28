from enum import Enum


class ArtifactType(str, Enum):
    IMAGE = "image"
    MASK = "mask"
    VIDEO = "video"
    THREE_D_MESH = "3d_mesh"
    MESH = "mesh"
    GLB = "glb"
    TEXTURE = "texture"
    POINT_CLOUD = "point_cloud"
    PHYSICS_ASSET = "physics_asset"
    PHYSICS_SCENE = "physics_scene"
    TRAJECTORY = "trajectory"
    REPORT = "report"
    LOG_FILE = "log_file"
    UNKNOWN = "unknown"


class ArtifactRetention(str, Enum):
    TEMPORARY = "temporary"
    RESULT = "result"


class ArtifactVisibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    TEMPORARY = "temporary"


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_ALREADY_FINISHED = "JOB_ALREADY_FINISHED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    SERVICE_BUSY = "SERVICE_BUSY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class JobStatus(str, Enum):
    CREATED = "created"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SUBMIT_FAILED = "submit_failed"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    STDOUT = "stdout"
    STDERR = "stderr"


class LogSource(str, Enum):
    SERVICE = "service"
    ORCHESTRATOR = "orchestrator"


class ParameterValueType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    JSON = "json"


class ServiceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    BUSY = "busy"
    UNKNOWN = "unknown"
