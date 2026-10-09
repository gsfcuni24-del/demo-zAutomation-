import { create } from "zustand";

export type CenterPanelView = "diff" | "hmi";

interface UIState {
  centerPanelView: CenterPanelView;
  setCenterPanelView: (view: CenterPanelView) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  centerPanelView: "diff",
  setCenterPanelView: (view) => set({ centerPanelView: view }),
}));
