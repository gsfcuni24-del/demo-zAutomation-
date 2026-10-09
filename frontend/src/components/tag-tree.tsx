"use client";

import { ChevronRight, Cpu, Folder, Tag as TagIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { TAG_DATA_TYPES, type Tag, type TagDataType } from "@/types/uir";

export const DATA_TYPE_STYLES: Record<TagDataType, { dot: string; badge: string }> = {
  BOOL: { dot: "bg-emerald-400", badge: "border-emerald-400/40 text-emerald-300" },
  INT: { dot: "bg-sky-400", badge: "border-sky-400/40 text-sky-300" },
  DINT: { dot: "bg-indigo-400", badge: "border-indigo-400/40 text-indigo-300" },
  REAL: { dot: "bg-amber-400", badge: "border-amber-400/40 text-amber-300" },
  STRING: { dot: "bg-fuchsia-400", badge: "border-fuchsia-400/40 text-fuchsia-300" },
};

interface TreeNode {
  id: string;
  label: string;
  kind: "scope" | "program" | "tag";
  tag?: Tag;
  children?: TreeNode[];
}

export function buildTagTree(tags: Tag[]): TreeNode[] {
  const controller = tags.filter((t) => t.scope === "CONTROLLER");
  const programs = new Map<string, Tag[]>();
  for (const tag of tags) {
    if (tag.scope !== "PROGRAM") continue;
    const key = tag.program ?? "(unassigned)";
    programs.set(key, [...(programs.get(key) ?? []), tag]);
  }
  const toLeaf = (tag: Tag): TreeNode => ({ id: tag.id, label: tag.name, kind: "tag", tag });
  return [
    {
      id: "scope:CONTROLLER",
      label: "Controller Tags",
      kind: "scope",
      children: controller.map(toLeaf),
    },
    {
      id: "scope:PROGRAM",
      label: "Program Tags",
      kind: "scope",
      children: [...programs.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([program, programTags]) => ({
          id: `program:${program}`,
          label: program,
          kind: "program",
          children: programTags.map(toLeaf),
        })),
    },
  ];
}

function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  if (!query) return nodes;
  const q = query.toLowerCase();
  return nodes.flatMap((node) => {
    if (node.kind === "tag") {
      const haystack = `${node.label} ${node.tag?.description ?? ""}`.toLowerCase();
      return haystack.includes(q) ? [node] : [];
    }
    const children = filterTree(node.children ?? [], query);
    return children.length ? [{ ...node, children }] : [];
  });
}

function countLeaves(node: TreeNode): number {
  return node.kind === "tag" ? 1 : (node.children ?? []).reduce((n, c) => n + countLeaves(c), 0);
}

interface TreeItemProps {
  node: TreeNode;
  depth: number;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  selectedTagId: string | null;
  onSelectTag: (id: string) => void;
}

function TreeItem({ node, depth, collapsed, onToggle, selectedTagId, onSelectTag }: TreeItemProps) {
  const padding = { paddingLeft: `${depth * 14 + 8}px` };

  if (node.kind === "tag" && node.tag) {
    const tag = node.tag;
    const style = DATA_TYPE_STYLES[tag.data_type];
    const selected = selectedTagId === tag.id;
    return (
      <li role="treeitem" aria-selected={selected} aria-level={depth + 1}>
        <button
          type="button"
          onClick={() => onSelectTag(tag.id)}
          title={[tag.description, tag.address].filter(Boolean).join(" · ") || undefined}
          className={cn(
            "flex w-full items-center gap-2 rounded-sm py-1 pr-2 text-left font-mono text-xs hover:bg-accent",
            selected && "bg-accent text-accent-foreground",
          )}
          style={padding}
          data-testid={`tag-${tag.id}`}
        >
          <span className={cn("h-2 w-2 shrink-0 rounded-full", style.dot)} aria-hidden />
          <span className="truncate">{tag.name}</span>
          <span
            className={cn(
              "ml-auto shrink-0 rounded border px-1 text-[10px] leading-4",
              style.badge,
            )}
          >
            {tag.data_type}
          </span>
        </button>
      </li>
    );
  }

  const isCollapsed = collapsed.has(node.id);
  const Icon = node.kind === "scope" ? Cpu : Folder;
  return (
    <li role="treeitem" aria-expanded={!isCollapsed} aria-selected={false} aria-level={depth + 1}>
      <button
        type="button"
        onClick={() => onToggle(node.id)}
        className="flex w-full items-center gap-1.5 rounded-sm py-1 pr-2 text-left text-xs font-medium hover:bg-accent"
        style={padding}
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 shrink-0 transition-transform", !isCollapsed && "rotate-90")}
        />
        <Icon className="h-3.5 w-3.5 shrink-0 text-primary" />
        <span className="truncate">{node.label}</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {countLeaves(node)}
        </span>
      </button>
      {!isCollapsed && node.children?.length ? (
        <ul role="group">
          {node.children.map((child) => (
            <TreeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              collapsed={collapsed}
              onToggle={onToggle}
              selectedTagId={selectedTagId}
              onSelectTag={onSelectTag}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

interface TagTreeProps {
  tags: Tag[];
  selectedTagId: string | null;
  onSelectTag: (id: string) => void;
}

export function TagTree({ tags, selectedTagId, onSelectTag }: TagTreeProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const tree = useMemo(() => filterTree(buildTagTree(tags), query.trim()), [tags, query]);

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 border-b px-3 py-2">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter tags…"
          className="h-8 text-xs"
          aria-label="Filter tags"
        />
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {TAG_DATA_TYPES.map((dt) => (
            <span key={dt} className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
              <span className={cn("h-2 w-2 rounded-full", DATA_TYPE_STYLES[dt].dot)} />
              {dt}
            </span>
          ))}
        </div>
      </div>
      {tree.length ? (
        <ul role="tree" aria-label="UIR tags" className="min-h-0 flex-1 overflow-auto p-1" data-testid="tag-tree">
          {tree.map((node) => (
            <TreeItem
              key={node.id}
              node={node}
              depth={0}
              collapsed={collapsed}
              onToggle={toggle}
              selectedTagId={selectedTagId}
              onSelectTag={onSelectTag}
            />
          ))}
        </ul>
      ) : (
        <p className="flex flex-1 items-center justify-center gap-2 p-6 text-xs text-muted-foreground">
          <TagIcon className="h-4 w-4" /> No tags match “{query}”
        </p>
      )}
    </div>
  );
}
