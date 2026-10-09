import { cn } from "@/lib/utils";
import type { FileParseStatus, ProjectStatus } from "@/types/api";

const STYLES: Record<ProjectStatus | FileParseStatus, string> = {
  DRAFT: "border-muted-foreground/40 text-muted-foreground",
  PENDING: "border-muted-foreground/40 text-muted-foreground",
  PARSING: "border-status-warn/50 text-status-warn",
  READY: "border-status-ok/50 text-status-ok",
  SUCCESS: "border-status-ok/50 text-status-ok",
  FAILED: "border-status-fault/50 text-status-fault",
  ARCHIVED: "border-border text-muted-foreground/70",
};

export function StatusBadge({ status }: { status: ProjectStatus | FileParseStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        STYLES[status],
      )}
    >
      {status}
    </span>
  );
}
