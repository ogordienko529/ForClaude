/**
 * Pieces shared by the screen-like templates (phone, terminal, browser, split): text measurement that
 * matches the browser's line breaks (so a camera can aim at a phrase), generic window chrome, a mouse
 * pointer and tap ripples. Nothing here copies a specific product's look.
 */
import React from 'react';
import {interpolate} from 'remotion';

const clampX = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

let ctx: CanvasRenderingContext2D | null | undefined;
const canvas = () => {
  if (ctx === undefined) ctx = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
  return ctx;
};

/** Width of a run of text at this font (falls back to an estimate outside a browser). */
export const textWidth = (text: string, weight: number, size: number, family: string) => {
  const c = canvas();
  if (!c) return Array.from(text).length * size * 0.56;
  c.font = `${weight} ${size}px ${family}`;
  return c.measureText(text).width;
};

/** Greedy word wrap as the browser does it: the code-point index at which each line starts. */
export const wrapStarts = (text: string, weight: number, size: number, family: string, max: number): number[] => {
  const cs = Array.from(text);
  const w = (a: number, b: number) => textWidth(cs.slice(a, b).join(''), weight, size, family);
  const space = textWidth(' ', weight, size, family);
  const starts = [0];
  let cur = 0;
  let i = 0;
  while (i < cs.length) {
    if (cs[i] === '\n') {
      starts.push(i + 1);
      cur = 0;
      i++;
      continue;
    }
    if (/\s/.test(cs[i])) {
      i++;
      continue;
    }
    let j = i;
    while (j < cs.length && !/\s/.test(cs[j])) j++;
    let ww = w(i, j);
    if (cur > 0 && cur + space + ww <= max) {
      cur += space + ww;
    } else {
      if (cur > 0) starts.push(i);
      let k = i;
      while (ww > max && j - k > 1) {
        // a word longer than the line breaks anywhere
        let n = 1;
        while (k + n < j && w(k, k + n + 1) <= max) n++;
        k += n;
        starts.push(k);
        ww = w(k, j);
      }
      cur = ww;
    }
    i = j;
  }
  return starts;
};

/** Code-point span of the first case-insensitive occurrence of `phrase` in `text`. */
export const findPhrase = (text: string, phrase: string): {start: number; end: number} | null => {
  const hay = Array.from(text).map((c) => c.toLowerCase());
  const nd = Array.from(phrase.trim()).map((c) => c.toLowerCase());
  if (!nd.length) return null;
  for (let i = 0; i + nd.length <= hay.length; i++) {
    let k = 0;
    while (k < nd.length && hay[i + k] === nd[k]) k++;
    if (k === nd.length) return {start: i, end: i + k};
  }
  return null;
};

/**
 * Where a phrase sits inside a wrapped text block: the centre of its (middle) line, relative to the
 * block's top-left corner, plus the block's measured width.
 */
export const phraseSpot = (text: string, phrase: string, weight: number, size: number, family: string, max: number, lh: number) => {
  const span = findPhrase(text, phrase);
  if (!span) return null;
  const cs = Array.from(text);
  const starts = wrapStarts(text, weight, size, family, max);
  const mid = Math.floor((span.start + span.end - 1) / 2);
  let line = 0;
  starts.forEach((s, i) => {
    if (s <= mid) line = i;
  });
  const lineStart = starts[line];
  const lineEnd = line + 1 < starts.length ? starts[line + 1] : cs.length;
  const a = Math.max(span.start, lineStart);
  const b = Math.min(span.end, lineEnd);
  const x0 = textWidth(cs.slice(lineStart, a).join(''), weight, size, family);
  const pw = textWidth(cs.slice(a, b).join(''), weight, size, family);
  return {x: Math.min(x0 + pw / 2, max), y: (line + 0.5) * lh, lines: starts.length, line};
};

/**
 * The point a camera should aim at so a block [left, right] stays on screen at zoom `z` when the target
 * point lands at `tx`: the phrase's own x when that fits, else as close to it as possible.
 */
export const aimX = (fx: number, left: number, right: number, z: number, tx: number, frameW: number, margin: number) => {
  if (z * (right - left) > frameW - 2 * margin) return (left + right) / 2;
  const lo = right - (frameW - margin - tx) / z;
  const hi = left + (tx - margin) / z;
  return Math.min(Math.max(fx, lo), hi);
};

// ------------------------------------------------------------------ chrome
/** Three window dots (red, amber, green, slightly muted): the generic desktop-window cue. */
export const WindowDots: React.FC<{size: number; gap: number; dim?: boolean}> = ({size, gap, dim}) => (
  <div style={{display: 'flex', gap, flexShrink: 0}}>
    {['#ec6a5e', '#f3be4f', '#62c655'].map((c) => (
      <div key={c} style={{width: size, height: size, borderRadius: size / 2, background: c, opacity: dim ? 0.45 : 1}} />
    ))}
  </div>
);

/** A mouse pointer (white arrow with a dark outline); its tip is the element's top-left corner. */
export const Pointer: React.FC<{x: number; y: number; size: number; press?: number; opacity?: number}> = ({x, y, size, press = 0, opacity = 1}) => (
  <svg
    width={size}
    height={size * 1.5}
    viewBox="0 0 20 30"
    style={{position: 'absolute', left: x - size * 0.06, top: y - size * 0.04, opacity, transform: `scale(${1 - 0.12 * press})`,
      transformOrigin: '6% 4%', filter: `drop-shadow(0 ${size * 0.08}px ${size * 0.12}px rgba(0,0,0,0.45))`, overflow: 'visible'}}
  >
    <path d="M1 1 L1 22.5 L6.4 17.6 L10.2 26.4 L13.9 24.8 L10.2 16.3 L17.6 16.3 Z" fill="#ffffff" stroke="#111111" strokeWidth={1.6} strokeLinejoin="round" />
  </svg>
);

/** An expanding ring from a tap or a click at (x, y), starting at frame `at`. */
export const Ripple: React.FC<{frame: number; at: number; x: number; y: number; r: number; color: string; width: number}> = ({
  frame,
  at,
  x,
  y,
  r,
  color,
  width,
}) => {
  const f = frame - at;
  if (f < 0 || f > 22) return null;
  const k = interpolate(f, [0, 22], [0, 1], clampX);
  const rr = r * (0.25 + 0.75 * Math.sqrt(k));
  return (
    <div
      style={{
        position: 'absolute',
        left: x - rr,
        top: y - rr,
        width: 2 * rr,
        height: 2 * rr,
        borderRadius: '50%',
        border: `${width * (1 - 0.6 * k)}px solid ${color}`,
        opacity: 1 - k,
        boxSizing: 'border-box',
        pointerEvents: 'none',
      }}
    />
  );
};

/** A fingertip touch: a soft translucent disc (as in screen recordings with touches shown). */
export const Touch: React.FC<{x: number; y: number; r: number; press: number; opacity: number}> = ({x, y, r, press, opacity}) => {
  const rr = r * (1 - 0.18 * press);
  return (
    <div
      style={{
        position: 'absolute',
        left: x - rr,
        top: y - rr,
        width: 2 * rr,
        height: 2 * rr,
        borderRadius: '50%',
        background: 'radial-gradient(circle at 40% 35%, rgba(255,255,255,0.95) 0%, rgba(235,238,245,0.85) 55%, rgba(200,205,215,0.75) 100%)',
        border: `${Math.max(r * 0.06, 2)}px solid rgba(255,255,255,0.9)`,
        boxShadow: `0 ${r * 0.25}px ${r * 0.6}px rgba(0,0,0,${0.35 - 0.15 * press})`,
        opacity,
        pointerEvents: 'none',
      }}
    />
  );
};
