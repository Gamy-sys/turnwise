import React, { useCallback, useEffect, useRef, useState } from "react";

/**
 * Drag handle between two panes. `axis` is "x" (vertical bar, resize widths)
 * or "y" (horizontal bar, resize heights).
 */
export function ResizeHandle({ axis = "x", onDrag, onDragEnd }) {
  const dragging = useRef(false);

  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current) return;
      onDrag && onDrag(axis === "x" ? e.clientX : e.clientY, e);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.classList.remove("resizing");
      onDragEnd && onDragEnd();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [axis, onDrag, onDragEnd]);

  return (
    <div
      className={"resize-handle resize-" + axis}
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      onPointerDown={(e) => {
        e.preventDefault();
        dragging.current = true;
        document.body.classList.add("resizing");
        e.currentTarget.setPointerCapture?.(e.pointerId);
      }}
      title={axis === "x" ? "Drag to resize width" : "Drag to resize height"}
    />
  );
}

/** Persist a numeric layout value in localStorage. */
export function usePersistedNumber(key, fallback, { min = 0, max = 1e9 } = {}) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw == null) return fallback;
      const n = parseFloat(raw);
      if (Number.isNaN(n)) return fallback;
      return Math.min(max, Math.max(min, n));
    } catch (_) {
      return fallback;
    }
  });
  useEffect(() => {
    try { localStorage.setItem(key, String(value)); } catch (_) {}
  }, [key, value]);
  const setClamped = useCallback((v) => {
    const n = typeof v === "function" ? v(value) : v;
    setValue(Math.min(max, Math.max(min, n)));
  }, [value, min, max]);
  return [value, setClamped];
}

export function usePersistedBool(key, fallback = false) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw == null) return fallback;
      return raw === "1" || raw === "true";
    } catch (_) {
      return fallback;
    }
  });
  useEffect(() => {
    try { localStorage.setItem(key, value ? "1" : "0"); } catch (_) {}
  }, [key, value]);
  return [value, setValue];
}

/**
 * Collapsible section with a title bar. When collapsed, only the bar shows.
 * `hidden` fully removes it (parent can show a restore chip).
 */
export function CollapsiblePanel({
  id,
  title,
  children,
  defaultOpen = true,
  className = "",
  headerExtra = null,
  storageKey,
}) {
  const key = storageKey || `ca-panel-open-${id}`;
  const [open, setOpen] = usePersistedBool(key, defaultOpen);

  return (
    <div className={"collapsible-panel" + (open ? "" : " collapsed") + (className ? " " + className : "")}>
      <div className="panel-chrome">
        <button
          type="button"
          className="panel-toggle"
          onClick={() => setOpen((o) => !o)}
          title={open ? "Collapse" : "Expand"}
          aria-expanded={open}
        >
          <span className="chev">{open ? "▾" : "▸"}</span>
          <span className="panel-title">{title}</span>
        </button>
        <div className="panel-chrome-extra">{headerExtra}</div>
      </div>
      {open && <div className="panel-body">{children}</div>}
    </div>
  );
}
