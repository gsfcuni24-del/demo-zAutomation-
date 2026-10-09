"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Layers, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";

import { FileUpload } from "@/components/file-upload";
import { StatusBadge } from "@/components/status-badge";
import { TagTree } from "@/components/tag-tree";
import { PanelPlaceholder, WorkspaceLayout } from "@/components/workspace-layout";
import { getLatestUIR, getProject } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { useProjectStore } from "@/stores/project-store";
import { useUIRStore } from "@/stores/uir-store";

export default function ProjectWorkspacePage() {
  const { id: projectId } = useParams<{ id: string }>();
  const setActiveProject = useProjectStore((s) => s.setActiveProject);
  const activeProject = useProjectStore((s) => s.activeProject);
  const { uir, snapshot, selectedTagId, setSnapshot, selectTag, reset } = useUIRStore();

  const projectQuery = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => getProject(projectId),
  });
  const uirQuery = useQuery({
    queryKey: queryKeys.latestUIR(projectId),
    queryFn: () => getLatestUIR(projectId),
  });

  useEffect(() => {
    if (projectQuery.data) setActiveProject(projectQuery.data);
  }, [projectQuery.data, setActiveProject]);

  useEffect(() => {
    if (uirQuery.data !== undefined) setSnapshot(projectId, uirQuery.data);
  }, [projectId, uirQuery.data, setSnapshot]);

  useEffect(
    () => () => {
      setActiveProject(null);
      reset();
    },
    [setActiveProject, reset],
  );

  if (projectQuery.isError) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3 text-sm">
        <p role="alert" className="text-status-fault">
          {projectQuery.error.message}
        </p>
        <Link href="/dashboard" className="text-primary underline-offset-4 hover:underline">
          Back to dashboard
        </Link>
      </main>
    );
  }

  const project = activeProject?.id === projectId ? activeProject : projectQuery.data;
  const selectedTag = uir?.tags.find((t) => t.id === selectedTagId) ?? null;

  const header = (
    <div className="flex items-center gap-3">
      <Link href="/dashboard" aria-label="Back to dashboard" className="text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" />
      </Link>
      <h1 className="truncate text-sm font-semibold" data-testid="project-name">
        {project?.name ?? "Loading…"}
      </h1>
      {project ? <StatusBadge status={project.status} /> : null}
      {snapshot ? (
        <span className="ml-auto font-mono text-[11px] text-muted-foreground" title={snapshot.version_hash}>
          UIR v{snapshot.version} · {snapshot.version_hash.slice(0, 12)}
        </span>
      ) : null}
    </div>
  );

  const left = (
    <>
      <div className="border-b p-3">
        <FileUpload projectId={projectId} />
      </div>
      {uirQuery.isLoading ? (
        <p className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading UIR…
        </p>
      ) : uirQuery.isError ? (
        <p role="alert" className="p-4 text-xs text-status-fault">
          Failed to load UIR: {uirQuery.error.message}
        </p>
      ) : uir ? (
        <>
          <TagTree tags={uir.tags} selectedTagId={selectedTagId} onSelectTag={selectTag} />
          {selectedTag ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t p-3 font-mono text-[11px]">
              <dt className="text-muted-foreground">name</dt>
              <dd>{selectedTag.name}</dd>
              <dt className="text-muted-foreground">type</dt>
              <dd>{selectedTag.data_type}</dd>
              <dt className="text-muted-foreground">scope</dt>
              <dd>{selectedTag.program ?? selectedTag.scope}</dd>
              {selectedTag.address ? (
                <>
                  <dt className="text-muted-foreground">address</dt>
                  <dd>{selectedTag.address}</dd>
                </>
              ) : null}
              {selectedTag.description ? (
                <>
                  <dt className="text-muted-foreground">desc</dt>
                  <dd className="font-sans">{selectedTag.description}</dd>
                </>
              ) : null}
            </dl>
          ) : null}
        </>
      ) : (
        <p className="p-4 text-xs text-muted-foreground" data-testid="uir-empty">
          No UIR yet. Upload a file to generate the first snapshot.
        </p>
      )}
    </>
  );

  return (
    <WorkspaceLayout
      header={header}
      left={left}
      center={
        <PanelPlaceholder
          icon={<Layers className="h-6 w-6" />}
          title="Visual Diff / HMI Canvas"
          subtitle="Coming in Phase 3"
        />
      }
      right={
        <PanelPlaceholder
          icon={<Bot className="h-6 w-6" />}
          title="AI Chat Prompt"
          subtitle="Coming in Phase 3"
        />
      }
    />
  );
}
