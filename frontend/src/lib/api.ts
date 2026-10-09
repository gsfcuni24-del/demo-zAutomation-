import axios, { AxiosError, type AxiosInstance } from "axios";

import { env } from "@/lib/env";
import type {
  AuditReport,
  FileRead,
  FileUploadResponse,
  HealthResponse,
  ProjectCreate,
  ProjectRead,
  UIRDiffResponse,
  UIRSnapshotRead,
  UIRSnapshotSummary,
} from "@/types/api";

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface FastAPIValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

function extractMessage(error: AxiosError): string {
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (detail as FastAPIValidationIssue[])
      .map((issue) => [issue.loc?.slice(1).join("."), issue.msg].filter(Boolean).join(": "))
      .join("; ");
  }
  if (error.code === AxiosError.ERR_NETWORK) return "Cannot reach the API server";
  if (error.code === AxiosError.ECONNABORTED) return "Request timed out";
  return error.message;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${env.apiUrl}/api/v1`,
  timeout: 15_000,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      return Promise.reject(new ApiError(extractMessage(error), error.response?.status ?? null));
    }
    return Promise.reject(error);
  },
);

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>("/health");
  return data;
}

export async function listProjects(): Promise<ProjectRead[]> {
  const { data } = await apiClient.get<ProjectRead[]>("/projects");
  return data;
}

export async function getProject(projectId: string): Promise<ProjectRead> {
  const { data } = await apiClient.get<ProjectRead>(`/projects/${projectId}`);
  return data;
}

export async function createProject(payload: ProjectCreate): Promise<ProjectRead> {
  const { data } = await apiClient.post<ProjectRead>("/projects", payload);
  return data;
}

export async function listProjectFiles(projectId: string): Promise<FileRead[]> {
  const { data } = await apiClient.get<FileRead[]>(`/projects/${projectId}/files`);
  return data;
}

export async function uploadProjectFile(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<FileUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<FileUploadResponse>(`/projects/${projectId}/files`, form, {
    timeout: 120_000,
    onUploadProgress: (event) => {
      if (onProgress && event.total) onProgress(Math.round((event.loaded / event.total) * 100));
    },
  });
  return data;
}

/** Returns null when the project has no snapshot yet (404). */
export async function getLatestUIR(projectId: string): Promise<UIRSnapshotRead | null> {
  try {
    const { data } = await apiClient.get<UIRSnapshotRead>(`/projects/${projectId}/uir/latest`);
    return data;
  } catch (error) {
    if (isNotFound(error)) return null;
    throw error;
  }
}

export async function listUIRVersions(projectId: string): Promise<UIRSnapshotSummary[]> {
  const { data } = await apiClient.get<UIRSnapshotSummary[]>(`/projects/${projectId}/uir/versions`);
  return data;
}

export async function getUIRDiff(
  projectId: string,
  params: { base?: number | null; target?: number | null } = {},
): Promise<UIRDiffResponse> {
  const query: Record<string, number> = {};
  if (params.base != null) query.base = params.base;
  if (params.target != null) query.target = params.target;
  const { data } = await apiClient.get<UIRDiffResponse>(`/projects/${projectId}/uir/diff`, {
    params: query,
  });
  return data;
}

export async function getUIRAudit(projectId: string, version?: number): Promise<AuditReport> {
  const { data } = await apiClient.get<AuditReport>(`/projects/${projectId}/uir/audit`, {
    params: version != null ? { version } : {},
  });
  return data;
}

export function exportL5XUrl(projectId: string): string {
  return `${env.apiUrl}/api/v1/projects/${projectId}/export/l5x`;
}
