interface TouchPoint {
  identifier: number;
  clientX: number;
  clientY: number;
}

interface BackdropTouchEvent {
  target: EventTarget | { id?: string } | null;
  currentTarget: EventTarget | { id?: string } | null;
  touches: ArrayLike<TouchPoint>;
  changedTouches: ArrayLike<TouchPoint>;
}

/** Mini-program touch targets retain the press origin, so also hit-test the release point. */
export function createBackdropTapHandlers(
  elementId: string,
  isBackdropPoint: (point: TouchPoint) => Promise<boolean>,
  onDismiss: () => void,
) {
  let pressedId: number | null = null;
  let completed: TouchPoint | null = null;
  let generation = 0;

  function reset(): void {
    pressedId = null;
    completed = null;
    generation += 1;
  }

  function touchstart(event: BackdropTouchEvent): void {
    reset();
    const targetId = (event.target as { id?: string } | null)?.id;
    const currentTargetId = (event.currentTarget as { id?: string } | null)?.id;
    if (targetId !== elementId || currentTargetId !== elementId || event.touches.length !== 1) return;
    pressedId = event.touches[0]!.identifier;
  }

  function touchend(event: BackdropTouchEvent): void {
    const start = pressedId;
    reset();
    const point = event.changedTouches[0];
    if (start === null || event.touches.length || !point || event.changedTouches.length !== 1 || point.identifier !== start) return;
    completed = point;
  }

  async function tap(): Promise<void> {
    const point = completed;
    reset();
    const tapGeneration = generation;
    if (point && await isBackdropPoint(point) && generation === tapGeneration) onDismiss();
  }

  return { touchstart, touchend, tap, reset };
}
