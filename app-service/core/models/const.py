from sqlalchemy import Enum


# Helper classes
class TaskTTL(int, Enum):
    MIN_TTL = 1
    MAX_TTL = 44640  # = 1 month in minutes

class TaskStatus(int, Enum):
    READY = 0
    LOCKED = 1
    DONE = 2
    FAILED = 3