from enum import StrEnum


class Role(StrEnum):
    REVIEWER = 'reviewer'
    ANALYST = 'analyst'
    VIEWER = 'viewer'


class Sequence(StrEnum):
    AB = 'AB'
    BA = 'BA'


class RunState(StrEnum):
    QUEUED = 'queued'
    READY = 'ready'
    FAILED = 'failed'
    PUBLISHED = 'published'


class Decision(StrEnum):
    RETEST = 'retest'
    RETAIN = 'retain'
    PILOT = 'pilot'


class EntryKind(StrEnum):
    REGISTER = 'register'
    SUPPLEMENT = 'supplement'
    MODIFY = 'modify'
    REUPLOAD = 'reupload'


class EntryStatus(StrEnum):
    PASSED = 'passed'
    MISSING = 'missing'
    DUPLICATE = 'duplicate'
    SEQUENCE_CONFLICT = 'sequence_conflict'
    CONFLICT = 'conflict'


class BatchChoice(StrEnum):
    ORIGINAL = 'original'
    LATEST_COMPLETE = 'latest_complete'
