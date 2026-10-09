"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, Loader2, XCircle } from "lucide-react";
import { useCallback, useId, useRef, useState, type DragEvent } from "react";

import { uploadProjectFile } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { FileUploadResponse } from "@/types/api";

const ACCEPT = [".xml", ".l5x", ".txt", ".csv", ".xlsx", ".xls", ".json"];

interface FileUploadProps {
  projectId: string;
  onUploaded?: (response: FileUploadResponse) => void;
}

export function FileUpload({ projectId, onUploaded }: FileUploadProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (file: File) => uploadProjectFile(projectId, file, setProgress),
    onMutate: () => setProgress(0),
    onSuccess: async (response) => {
      onUploaded?.(response);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects, exact: true }),
      ]);
    },
  });

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file && !mutation.isPending) mutation.mutate(file);
    },
    [mutation],
  );

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setIsDragging(false);
    handleFiles(event.dataTransfer.files);
  };

  return (
    <div className="space-y-2">
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed px-3 py-4 text-center text-xs transition-colors",
          isDragging ? "border-primary bg-primary/10" : "hover:border-primary/60 hover:bg-accent/40",
          mutation.isPending && "pointer-events-none opacity-70",
        )}
      >
        {mutation.isPending ? (
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
        ) : (
          <FileUp className="h-5 w-5 text-primary" />
        )}
        <span className="font-medium">
          {mutation.isPending ? "Uploading…" : "Drop PLC/HMI export or click to browse"}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {ACCEPT.join(" ")}
        </span>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept={ACCEPT.join(",")}
          className="sr-only"
          data-testid="file-upload-input"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </label>

      {mutation.isPending ? (
        <div
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1.5 overflow-hidden rounded bg-muted"
        >
          <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
        </div>
      ) : null}
      {mutation.isSuccess ? (
        <div className="space-y-1" data-testid="upload-result">
          <p className="flex items-center gap-1.5 text-xs text-status-ok">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {mutation.data.snapshot
              ? `${mutation.data.file.filename} → UIR v${mutation.data.snapshot.version}`
              : `${mutation.data.file.filename} stored — import it via the AI assistant`}
          </p>
          {mutation.data.warnings.map((warning) => (
            <p key={warning} className="flex items-center gap-1.5 text-[11px] text-status-warn">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              {warning}
            </p>
          ))}
        </div>
      ) : null}
      {mutation.isError ? (
        <p role="alert" className="flex items-center gap-1.5 text-xs text-status-fault">
          <XCircle className="h-3.5 w-3.5" />
          {mutation.error.message}
        </p>
      ) : null}
    </div>
  );
}
