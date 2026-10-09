export type Environment = "development" | "staging" | "production";

export interface HealthResponse {
  status: "ok" | "error";
  version: string;
  environment: Environment;
}
