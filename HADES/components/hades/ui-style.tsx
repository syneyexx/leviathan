"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { AppSettings, hadesApi } from "@/lib/hades-api";
import { HADES_SETTINGS_UPDATED_EVENT } from "@/components/hades/features/settings/settings-events";

/** Product shells: Lux (default) and FINALBETA (Phase 1 visual variant). Legacy DB values coerce to Lux. */
export type UiStyle = "lux" | "finalbeta";
export type MotionLevel = AppSettings["motion_level"];

const LOCAL_UI_STYLE_KEY = "hades-ui-style";

type UiStyleContextValue = {
  uiStyle: UiStyle;
  motionLevel: MotionLevel;
  setUiStyle: (style: UiStyle) => void;
  setMotionLevel: (level: MotionLevel) => void;
};

const UiStyleContext = createContext<UiStyleContextValue | null>(null);

export function coerceUiStyle(value: unknown): UiStyle {
  if (value === "finalbeta") return "finalbeta";
  return "lux";
}

function readLocalUiStyle(): UiStyle | null {
  if (typeof window === "undefined") return null;
  try {
    return coerceUiStyle(window.localStorage.getItem(LOCAL_UI_STYLE_KEY));
  } catch {
    return null;
  }
}

function writeLocalUiStyle(style: UiStyle) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LOCAL_UI_STYLE_KEY, style);
  } catch {
    /* ignore */
  }
}

function applyUiStyle(uiStyle: UiStyle, motionLevel: MotionLevel) {
  document.documentElement.dataset.hadesStyle = uiStyle;
  document.documentElement.dataset.motion = motionLevel;
}

export function UiStyleProvider({ children }: { children: React.ReactNode }) {
  const [uiStyle, setUiStyleState] = useState<UiStyle>(() => readLocalUiStyle() ?? "lux");
  const [motionLevel, setMotionLevel] = useState<MotionLevel>("standard");
  const [systemReducedMotion, setSystemReducedMotion] = useState(false);

  const setUiStyle = (style: UiStyle) => {
    setUiStyleState(style);
    writeLocalUiStyle(style);
    document.documentElement.dataset.hadesStyle = style;
  };

  useEffect(() => {
    hadesApi
      .settings()
      .then(({ values }) => {
        const nextStyle = coerceUiStyle(values.ui_style);
        const nextMotion = values.motion_level ?? "standard";
        setUiStyleState(nextStyle);
        writeLocalUiStyle(nextStyle);
        setMotionLevel(nextMotion);
        applyUiStyle(nextStyle, nextMotion);
      })
      .catch(() => {
        const local = readLocalUiStyle() ?? "lux";
        applyUiStyle(local, "standard");
      });

    const receive = (event: Event) => {
      const values = (event as CustomEvent<Partial<AppSettings>>).detail ?? {};
      if (values.ui_style != null) {
        const next = coerceUiStyle(values.ui_style);
        setUiStyleState(next);
        writeLocalUiStyle(next);
        document.documentElement.dataset.hadesStyle = next;
      }
      if (values.motion_level != null) {
        setMotionLevel(values.motion_level);
        document.documentElement.dataset.motion = values.motion_level;
      }
    };
    window.addEventListener(HADES_SETTINGS_UPDATED_EVENT, receive);
    return () => window.removeEventListener(HADES_SETTINGS_UPDATED_EVENT, receive);
  }, []);

  useEffect(() => applyUiStyle(uiStyle, systemReducedMotion ? "reduced" : motionLevel), [uiStyle, motionLevel, systemReducedMotion]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setSystemReducedMotion(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const value = useMemo(
    () => ({ uiStyle, motionLevel: systemReducedMotion ? "reduced" : motionLevel, setUiStyle, setMotionLevel }),
    [uiStyle, motionLevel, systemReducedMotion],
  );
  return <UiStyleContext.Provider value={value}>{children}</UiStyleContext.Provider>;
}

export function useUiStyle(): UiStyleContextValue {
  const context = useContext(UiStyleContext);
  if (!context) throw new Error("useUiStyle must be used inside UiStyleProvider.");
  return context;
}
