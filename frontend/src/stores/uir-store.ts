import { create } from "zustand";

import type { UIRSnapshotRead } from "@/types/api";
import type { UIRProject } from "@/types/uir";

interface UIRState {
  projectId: string | null;
  snapshot: Omit<UIRSnapshotRead, "uir"> | null;
  uir: UIRProject | null;
  selectedTagId: string | null;
  setSnapshot: (projectId: string, snapshot: UIRSnapshotRead | null) => void;
  selectTag: (tagId: string | null) => void;
  reset: () => void;
}

const initialState = { projectId: null, snapshot: null, uir: null, selectedTagId: null };

export const useUIRStore = create<UIRState>()((set) => ({
  ...initialState,
  setSnapshot: (projectId, snapshot) => {
    if (!snapshot) {
      set({ ...initialState, projectId });
      return;
    }
    const { uir, ...meta } = snapshot;
    set((state) => ({
      projectId,
      snapshot: meta,
      uir,
      selectedTagId:
        state.projectId === projectId && uir.tags.some((t) => t.id === state.selectedTagId)
          ? state.selectedTagId
          : null,
    }));
  },
  selectTag: (tagId) => set({ selectedTagId: tagId }),
  reset: () => set(initialState),
}));
