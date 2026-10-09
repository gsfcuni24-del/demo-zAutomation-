// Mirrors backend/app/schemas/project.py and backend/app/models enums.
import type { UIRProject } from "@/types/uir";

export type Environment = "development" | "staging" | "production";

export interface HealthResponse {
  status: "ok" | "error";
  version: string;
  environment: Environment;
}

export const PROJECT_STATUSES = ["DRAFT", "PARSING", "READY", "ARCHIVED"] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export const FILE_PARSE_STATUSES = ["PENDING", "PARSING", "SUCCESS", "FAILED"] as const;
export type FileParseStatus = (typeof FILE_PARSE_STATUSES)[number];

export interface ProjectCreate {
  name: string;
  original_vendor: string | null;
}

export interface ProjectRead {
  id: string;
  name: string;
  owner_id: string;
  original_vendor: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface FileRead {
  id: string;
  project_id: string;
  filename: string;
  file_size_bytes: number;
  parse_status: FileParseStatus;
  created_at: string;
}

export interface UIRSnapshotSummary {
  id: string;
  project_id: string;
  version: number;
  version_hash: string;
  parent_version_hash: string | null;
  created_at: string;
}

export interface UIRSnapshotRead extends UIRSnapshotSummary {
  uir: UIRProject;
}

export interface FileUploadResponse {
  file: FileRead;
  /** null for CSV/Excel/text inputs, which are converted to UIR by the AI assistant. */
  snapshot: UIRSnapshotSummary | null;
  warnings: string[];
}

// Mirrors backend/app/services/diff_engine.py
export const CHANGE_TYPES = ["ADDED", "REMOVED", "MODIFIED"] as const;
export type ChangeType = (typeof CHANGE_TYPES)[number];

export interface DiffEntry {
  change_type: ChangeType;
  /** Exact JSONPath into the snapshot, e.g. "$.tags[3].description". */
  path: string;
  collection: string | null;
  entity_id: string | null;
  field: string | null;
  old_value: unknown;
  new_value: unknown;
}

export interface DiffSummary {
  added: number;
  removed: number;
  modified: number;
}

export interface UIRDiffResponse {
  base_version: number | null;
  target_version: number;
  summary: DiffSummary;
  changes: DiffEntry[];
}

// Mirrors backend/app/services/auditor/rule_engine.py
export const VIOLATION_SEVERITIES = ["CRITICAL", "HIGH"] as const;
export type ViolationSeverity = (typeof VIOLATION_SEVERITIES)[number];

export interface Violation {
  rule_id: string;
  severity: ViolationSeverity;
  message: string;
  location: string;
  subjects: string[];
  fingerprint: string;
}

export interface AuditReport {
  passed: boolean;
  rules_checked: string[];
  violations: Violation[];
  preexisting: Violation[];
}
