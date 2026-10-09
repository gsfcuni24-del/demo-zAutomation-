export const queryKeys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  projectFiles: (id: string) => ["projects", id, "files"] as const,
  latestUIR: (id: string) => ["projects", id, "uir", "latest"] as const,
  uirVersions: (id: string) => ["projects", id, "uir", "versions"] as const,
  uirDiff: (id: string, base: number | null, target: number | null) =>
    ["projects", id, "uir", "diff", base, target] as const,
};
