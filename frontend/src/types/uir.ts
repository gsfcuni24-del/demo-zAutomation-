// Mirrors backend/app/schemas/uir/ (Pydantic, extra="forbid"). Keep field names and enum values identical;
// backend/tests/test_ts_mirror.py fails if they drift.

export const TAG_DATA_TYPES = ["BOOL", "INT", "DINT", "REAL", "STRING"] as const;
export type TagDataType = (typeof TAG_DATA_TYPES)[number];

export const TAG_SCOPES = ["CONTROLLER", "PROGRAM"] as const;
export type TagScope = (typeof TAG_SCOPES)[number];

export const ROUTINE_TYPES = ["MAIN", "SUBROUTINE"] as const;
export type RoutineType = (typeof ROUTINE_TYPES)[number];

export const ROUTINE_LANGUAGES = ["RLL", "ST"] as const;
export type RoutineLanguage = (typeof ROUTINE_LANGUAGES)[number];

export const WIDGET_TYPES = ["BUTTON", "INDICATOR", "NUMERIC"] as const;
export type WidgetType = (typeof WIDGET_TYPES)[number];

export const ALARM_SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
export type AlarmSeverity = (typeof ALARM_SEVERITIES)[number];

export interface Tag {
  id: string;
  name: string;
  data_type: TagDataType;
  scope: TagScope;
  program: string | null;
  description: string | null;
  address: string | null;
  initial_value: boolean | number | string | null;
}

export interface Rung {
  number: number;
  logic: string;
  comment: string | null;
}

export interface Routine {
  id: string;
  name: string;
  program: string;
  type: RoutineType;
  language: RoutineLanguage;
  rungs: Rung[];
}

export interface Widget {
  id: string;
  type: WidgetType;
  label: string;
  tag_ref: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Screen {
  id: string;
  name: string;
  width: number;
  height: number;
  widgets: Widget[];
}

export interface Alarm {
  id: string;
  tag_ref: string;
  message: string;
  severity: AlarmSeverity;
}

export interface UIRProject {
  schema_version: "1.0";
  name: string;
  vendor: string | null;
  source_filename: string | null;
  tags: Tag[];
  routines: Routine[];
  screens: Screen[];
  alarms: Alarm[];
}
