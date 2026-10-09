import axios, { type AxiosInstance } from "axios";

import { env } from "@/lib/env";
import type { HealthResponse } from "@/types/api";

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${env.apiUrl}/api/v1`,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>("/health");
  return data;
}
