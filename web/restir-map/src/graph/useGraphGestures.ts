import { useEffect, useRef } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import type { Point, View } from "../data/types";
import { zoomAt } from "./layout";

type GraphGestures = {
  svg: RefObject<SVGSVGElement | null>;
  positionsRef: RefObject<Record<string, Point>>;
  view: View;
  setPositions: Dispatch<SetStateAction<Record<string, Point>>>;
  setView: Dispatch<SetStateAction<View>>;
  initiallyFitted: RefObject<boolean>;
};

export function useGraphGestures({
  svg, positionsRef, view, setPositions, setView, initiallyFitted,
}: GraphGestures) {
  const viewRef = useRef(view);
  viewRef.current = view;
  const pointers = useRef(new Map<number, Point>());
  const pinch = useRef<{ center: Point; distance: number; view: View } | null>(null);
  const gesture = useRef<{
    id: string | null;
    start: Point;
    origin: Point;
    pointer: number;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const clickResetTimer = useRef<number | undefined>(undefined);

  // Delay capture until movement so ordinary taps retain their node/edge target.
  // Window listeners cover releases outside the SVG before that capture begins.
  useEffect(() => {
    const blur = () => cancelGesture();
    window.addEventListener("pointerup", stopGesture);
    window.addEventListener("pointercancel", cancelGesture);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("pointerup", stopGesture);
      window.removeEventListener("pointercancel", cancelGesture);
      window.removeEventListener("blur", blur);
      cancelGesture();
      window.clearTimeout(clickResetTimer.current);
    };
  }, []);

  function localPoint(event: React.PointerEvent): Point {
    const box = svg.current?.getBoundingClientRect();
    return { x: event.clientX - (box?.left ?? 0), y: event.clientY - (box?.top ?? 0) };
  }
  function pinchGeometry() {
    const [first, second] = [...pointers.current.values()];
    return {
      center: { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 },
      distance: Math.max(1, Math.hypot(second.x - first.x, second.y - first.y)),
    };
  }
  function startGesture(event: React.PointerEvent, id: string | null) {
    if (event.button !== 0) return;
    event.stopPropagation();
    if (pointers.current.size >= 2) return;
    window.clearTimeout(clickResetTimer.current);
    const point = localPoint(event);
    pointers.current.set(event.pointerId, point);
    if (pointers.current.size === 2) {
      pinch.current = { ...pinchGeometry(), view: viewRef.current };
      gesture.current = null;
      suppressClick.current = true;
      initiallyFitted.current = true;
      for (const pointer of pointers.current.keys()) svg.current?.setPointerCapture?.(pointer);
      return;
    }
    suppressClick.current = false;
    gesture.current = {
      id,
      start: point,
      origin: id ? positionsRef.current[id] : { x: viewRef.current.x, y: viewRef.current.y },
      pointer: event.pointerId,
      moved: false,
    };
  }
  function moveGesture(event: React.PointerEvent) {
    if (!pointers.current.has(event.pointerId)) return;
    // A release outside the browser may not deliver pointerup to the window.
    if (event.pointerType !== "touch" && event.buttons === 0) {
      cancelGesture(event);
      return;
    }
    const point = localPoint(event);
    pointers.current.set(event.pointerId, point);
    if (pinch.current && pointers.current.size === 2) {
      const current = pinchGeometry(), initial = pinch.current;
      const zoomed = zoomAt(initial.view, current.distance / initial.distance, initial.center);
      setView({ ...zoomed, x: zoomed.x + current.center.x - initial.center.x, y: zoomed.y + current.center.y - initial.center.y });
      return;
    }
    const drag = gesture.current;
    if (!drag || drag.pointer !== event.pointerId) return;
    const dx = point.x - drag.start.x,
      dy = point.y - drag.start.y;
    if (Math.hypot(dx, dy) > 4 && !drag.moved) {
      drag.moved = true;
      initiallyFitted.current = true;
      suppressClick.current = true;
      svg.current?.setPointerCapture?.(event.pointerId);
    }
    if (!drag.moved) return;
    if (drag.id)
      setPositions((current) => ({
        ...current,
        [drag.id!]: {
          x: drag.origin.x + dx / viewRef.current.scale,
          y: drag.origin.y + dy / viewRef.current.scale,
        },
      }));
    else
      setView((current) => ({
        ...current,
        x: drag.origin.x + dx,
        y: drag.origin.y + dy,
      }));
  }
  function resetClickSuppression() {
    window.clearTimeout(clickResetTimer.current);
    clickResetTimer.current = window.setTimeout(() => {
      suppressClick.current = false;
    }, 0);
  }
  function cancelGesture(event?: { pointerId: number }) {
    if (!pointers.current.size || (event && !pointers.current.has(event.pointerId))) return;
    const captured = [...pointers.current.keys()];
    pointers.current.clear();
    pinch.current = null;
    gesture.current = null;
    suppressClick.current = true;
    for (const pointer of captured) {
      if (svg.current?.hasPointerCapture?.(pointer)) svg.current.releasePointerCapture(pointer);
    }
    resetClickSuppression();
  }
  function stopGesture(event: { pointerId: number }) {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.delete(event.pointerId);
    suppressClick.current = suppressClick.current || !!gesture.current?.moved || !!pinch.current;
    pinch.current = null;
    gesture.current = null;
    if (svg.current?.hasPointerCapture?.(event.pointerId))
      svg.current.releasePointerCapture(event.pointerId);
    if (pointers.current.size === 1) {
      const [pointer, point] = [...pointers.current.entries()][0];
      gesture.current = { id: null, pointer, start: point, origin: { x: viewRef.current.x, y: viewRef.current.y }, moved: true };
      return;
    }
    resetClickSuppression();
  }

  return { startGesture, moveGesture, stopGesture, cancelGesture, suppressClick };
}
