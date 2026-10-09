"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, GitCompare, Loader2, Minus, Pencil, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { exportL5XUrl, getUIRDiff, listUIRVersions } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { CHANGE_TYPES, type ChangeType, type DiffEntry } from "@/types/api";

export const CHANGE_STYLES: Record<ChangeType, { row: string; badge: string; label: string }> = {
  ADDED: {
    row: "border-l-emerald-500 bg-emerald-500/10",
    badge: "border-emerald-500/50 text-emerald-400",
    label: "Added",
  },
  REMOVED: {
    row: "border-l-red-500 bg-red-500/10",
    badge: "border-red-500/50 text-red-400",
    label: "Removed",
  },
  MODIFIED: {
    row: "border-l-yellow-500 bg-yellow-500/10",
    badge: "border-yellow-500/50 text-yellow-300",
    label: "Modified",
  },
};

const ICONS: Record<ChangeType, typeof Plus> = { ADDED: Plus, REMOVED: Minus, MODIFIED: Pencil };

function formatValue(value: unknown): string {
  if (value === undefined) return "";
  const text = typeof value === "string" ? JSON.stringify(value) : JSON.stringify(value, null, 1);
  return text.length > 400 ? `${text.slice(0, 400)}…` : text;
}

function DiffRow({ entry }: { entry: DiffEntry }) {
  const style = CHANGE_STYLES[entry.change_type];
  const Icon = ICONS[entry.change_type];
  return (
    <li
      className={cn("rounded-sm border-l-4 px-3 py-2", style.row)}
      data-testid="diff-entry"
      data-change-type={entry.change_type}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className={cn("rounded border px-1 font-mono text-[10px]", style.badge)}>{entry.change_type}</span>
        <code className="truncate font-mono text-xs" title={entry.path}>
          {entry.path}
        </code>
        {entry.entity_id ? (
          <span className="ml-auto truncate font-mono text-[10px] text-muted-foreground">{entry.entity_id}</span>
        ) : null}
      </div>
      <div className="mt-1 grid gap-1 font-mono text-[11px]">
        {entry.change_type !== "ADDED" ? (
          <pre className="whitespace-pre-wrap break-all text-red-300/90">- {formatValue(entry.old_value)}</pre>
        ) : null}
        {entry.change_type !== "REMOVED" ? (
          <pre className="whitespace-pre-wrap break-all text-emerald-300/90">+ {formatValue(entry.new_value)}</pre>
        ) : null}
      </div>
    </li>
  );
}

interface VisualDiffProps {
  projectId: string;
  latestVersion: number | null;
}

export function VisualDiff({ projectId, latestVersion }: VisualDiffProps) {
  const [base, setBase] = useState<number | null>(null);
  const [filter, setFilter] = useState<Set<ChangeType>>(() => new Set(CHANGE_TYPES));

  const versions = useQuery({
    queryKey: queryKeys.uirVersions(projectId),
    queryFn: () => listUIRVersions(projectId),
    enabled: latestVersion !== null,
  });
  const effectiveBase = base !== null && latestVersion !== null && base < latestVersion ? base : null;
  const diff = useQuery({
    queryKey: queryKeys.uirDiff(projectId, effectiveBase, latestVersion),
    queryFn: () => getUIRDiff(projectId, { base: effectiveBase, target: latestVersion }),
    enabled: latestVersion !== null,
  });

  const grouped = useMemo(() => {
    const out = new Map<string, DiffEntry[]>();
    for (const entry of diff.data?.changes ?? []) {
      if (!filter.has(entry.change_type)) continue;
      const key = entry.collection ?? "project";
      out.set(key, [...(out.get(key) ?? []), entry]);
    }
    return [...out.entries()];
  }, [diff.data, filter]);

  if (latestVersion === null) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
        <GitCompare className="h-6 w-6" />
        <p className="text-sm">Upload a PLC file or ask the AI assistant to create the first UIR version.</p>
      </div>
    );
  }

  const toggle = (type: ChangeType) =>
    setFilter((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });

  const summary = diff.data?.summary;
  return (
    <div className="flex h-full flex-col" data-testid="visual-diff">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <GitCompare className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">Visual Diff</span>
        <label className="ml-2 flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
          base
          <select
            value={effectiveBase ?? ""}
            onChange={(event) => setBase(event.target.value === "" ? null : Number(event.target.value))}
            className="rounded border border-input bg-background px-1 py-0.5 text-[11px]"
            aria-label="Base version"
          >
            <option value="">{latestVersion > 1 ? `v${latestVersion - 1} (previous)` : "empty"}</option>
            {(versions.data ?? [])
              .filter((v) => v.version < latestVersion - 1)
              .map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                </option>
              ))}
          </select>
          → v{latestVersion}
        </label>
        <div className="ml-auto flex items-center gap-1">
          {CHANGE_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => toggle(type)}
              aria-pressed={filter.has(type)}
              className={cn(
                "rounded border px-1.5 py-0.5 font-mono text-[10px] transition-opacity",
                CHANGE_STYLES[type].badge,
                !filter.has(type) && "opacity-40",
              )}
              data-testid={`diff-filter-${type}`}
            >
              {CHANGE_STYLES[type].label} {summary ? summary[type.toLowerCase() as "added" | "removed" | "modified"] : 0}
            </button>
          ))}
          <Button asChild variant="outline" size="sm" className="ml-2 h-7 text-[11px]">
            <a href={exportL5XUrl(projectId)} download>
              <Download /> L5X
            </a>
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {diff.isLoading ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Computing diff…
          </p>
        ) : diff.isError ? (
          <p role="alert" className="text-xs text-status-fault">
            {diff.error.message}
          </p>
        ) : grouped.length ? (
          <div className="space-y-4">
            {grouped.map(([collection, entries]) => (
              <section key={collection}>
                <h3 className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  {collection} · {entries.length}
                </h3>
                <ul className="space-y-1">
                  {entries.map((entry) => (
                    <DiffRow key={`${entry.change_type}:${entry.path}`} entry={entry} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No changes{filter.size < 3 ? " for the selected filters" : ""}.</p>
        )}
      </div>
    </div>
  );
}
