import {Easing, interpolate, spring} from 'remotion';

/** 0 -> 1 spring starting at `start` frames. */
export const rise = (frame: number, fps: number, start: number, damping = 18) =>
  spring({frame: frame - start, fps, config: {damping, mass: 0.8, stiffness: 110}});

/** Linear-ish 0 -> 1 progress between two frames with ease in/out. */
export const progress = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, Math.max(end, start + 1)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.45, 0, 0.2, 1),
  });

/** Spread n reveals across the time the narration is speaking. */
export const stagger = (i: number, n: number, speech: number, duration: number, share = 0.55) => {
  const span = Math.max(duration - speech, 30) * share;
  return speech + (n <= 1 ? 0 : (span * i) / (n - 1));
};
