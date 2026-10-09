"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, FolderOpen, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProject, listProjects } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

const VENDORS = ["", "SIEMENS", "ROCKWELL", "OTHER"] as const;

function CreateProjectForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [vendor, setVendor] = useState<(typeof VENDORS)[number]>("");

  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects, exact: true });
      router.push(`/projects/${project.id}`);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    mutation.mutate({ name: name.trim(), original_vendor: vendor || null });
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 rounded-lg border bg-card/60 p-4">
      <label className="flex min-w-60 flex-1 flex-col gap-1 text-xs text-muted-foreground">
        Project name
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Packaging Line 3"
          maxLength={255}
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Original vendor
        <select
          value={vendor}
          onChange={(event) => setVendor(event.target.value as (typeof VENDORS)[number])}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
        >
          {VENDORS.map((v) => (
            <option key={v} value={v}>
              {v || "Unknown"}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={mutation.isPending || !name.trim()}>
        {mutation.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
        Create project
      </Button>
      {mutation.isError ? (
        <p role="alert" className="w-full text-xs text-status-fault">
          {mutation.error.message}
        </p>
      ) : null}
    </form>
  );
}

export default function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
  });

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <header className="flex items-center gap-3">
        <Cpu className="h-7 w-7 text-primary" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            {"// zAutomation dashboard"}
          </p>
        </div>
      </header>

      <CreateProjectForm />

      {isLoading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading projects…
        </p>
      ) : isError ? (
        <p role="alert" className="text-sm text-status-fault">
          Failed to load projects: {error.message}
        </p>
      ) : data && data.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="project-grid">
          {data.map((project) => (
            <li key={project.id}>
              <Link
                href={`/projects/${project.id}`}
                className="block rounded-lg border bg-card/60 p-4 transition-colors hover:border-primary/60 hover:bg-card"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h2 className="truncate font-medium">{project.name}</h2>
                  <StatusBadge status={project.status} />
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {project.original_vendor ?? "Unknown vendor"} · updated{" "}
                  {new Date(project.updated_at).toLocaleString()}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-10 text-center text-muted-foreground">
          <FolderOpen className="h-8 w-8" />
          <p className="text-sm">No projects yet. Create one above to get started.</p>
        </div>
      )}
    </main>
  );
}
