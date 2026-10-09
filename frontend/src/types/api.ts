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
  snapshot: UIRSnapshotSummary;
}
