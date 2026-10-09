from enum import StrEnum


class TagDataType(StrEnum):
    BOOL = "BOOL"
    INT = "INT"
    DINT = "DINT"
    REAL = "REAL"
    STRING = "STRING"


class TagScope(StrEnum):
    CONTROLLER = "CONTROLLER"
    PROGRAM = "PROGRAM"


class RoutineType(StrEnum):
    MAIN = "MAIN"
    SUBROUTINE = "SUBROUTINE"


class WidgetType(StrEnum):
    BUTTON = "BUTTON"
    INDICATOR = "INDICATOR"
    NUMERIC = "NUMERIC"


class AlarmSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
