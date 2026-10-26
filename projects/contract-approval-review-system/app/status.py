"""任务、回写、阶段、解析和错误码常量。"""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    DONE = "done"


class WriteStatus(str, Enum):
    NOT_WRITTEN = "not_written"
    WRITING = "writing"
    SUCCESS = "success"
    FAILED = "failed"


class Stage(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    DOWNLOAD = "download"
    PARSE = "parse"
    REVIEW = "review"
    SAVE = "save"
    WRITE = "write"
    DONE = "done"


class ParseStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    SUCCESS = "success"
    FAILED = "failed"
    MISSING = "missing"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ErrorCode(str, Enum):
    MISSING_ATTACHMENT = "MISSING_ATTACHMENT"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    OCR_FAILED = "OCR_FAILED"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    PARSE_FAILED = "PARSE_FAILED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    SAVE_FAILED = "SAVE_FAILED"
    COMMENT_WRITE_FAILED = "COMMENT_WRITE_FAILED"
    SERVICE_INTERRUPTED = "SERVICE_INTERRUPTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


TASK_STATUS_VALUES = {item.value for item in TaskStatus}
WRITE_STATUS_VALUES = {item.value for item in WriteStatus}
STAGE_VALUES = {item.value for item in Stage}
PARSE_STATUS_VALUES = {item.value for item in ParseStatus}
DOWNLOAD_STATUS_VALUES = {item.value for item in DownloadStatus}
RISK_LEVEL_VALUES = {item.value for item in RiskLevel}

RISK_ORDER = {RiskLevel.HIGH.value: 3, RiskLevel.MEDIUM.value: 2, RiskLevel.LOW.value: 1}
TASK_STATUS_LABELS = {
    TaskStatus.PENDING.value: "待处理",
    TaskStatus.PARSING.value: "解析中",
    TaskStatus.REVIEWING.value: "审查中",
    TaskStatus.BLOCKED.value: "已阻塞",
    TaskStatus.DONE.value: "已完成",
}
