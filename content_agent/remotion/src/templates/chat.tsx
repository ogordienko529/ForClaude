/**
 * A generic messenger-style AI chat (no brand look): the prompt types into a user bubble on the right,
 * three "typing" dots answer on the left, then the answer lines arrive one by one (line i on cue i).
 * Colours come from the palette, corners and borders from the style, so the window fits every style.
 */
import React, {useEffect, useMemo, useState} from 'react';
import {LOGOS} from '../logos';
import {AbsoluteFill, continueRender, delayRender, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise} from '../anim';
import {PREROLL, Sfx, uiZone} from '../motion';
import type {StyleDef} from '../styles';
import {useStyle} from '../styles';
import type {Palette} from '../theme';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

// ------------------------------------------------------------------ timing
/** Frames (from the scene start) of every step; everything is on screen by ~75 % of the beat. */
export const chatTiming = (duration: number, speech: number, cues: (number | null)[], chars: number, n: number) => {
  const d = Math.max(duration, 24);
  const end = d * 0.75;
  const cueAt = (i: number) => (typeof cues[i] === 'number' ? clamp((cues[i] as number) - 4, 0, d * 0.9) : null);
  let typeStart = clamp(speech, 8, d * 0.12);
  const room0 = Math.max(end - 12 - typeStart, 24);
  const nominal = Math.max(chars / 1.6, Math.min(chars, 6)); // ~48 characters a second
  let first = typeStart + clamp(nominal, 6, room0 * 0.45) + 4 + clamp(room0 * 0.14, 10, 26);
  const c0 = cueAt(0);
  if (c0 !== null) {
    first = c0;
  } else {
    const j = cues.findIndex((c, i) => i < n && typeof c === 'number');
    if (j > 0) first = Math.min(first, (cueAt(j) as number) - 6 * j); // the first line comes before a cued later one
  }
  first = Math.max(first, 2);
  typeStart = Math.min(typeStart, Math.max(first - 24, 0)); // an early first cue: start typing sooner
  const room = first - typeStart;
  const dots = clamp(room * 0.22, 4, 30);
  const typeEnd = typeStart + clamp(room - dots - 4, 1, nominal * 1.5);
  const reveals: number[] = [];
  for (let i = 0; i < n; i++) {
    if (i === 0) {
      reveals.push(first);
      continue;
    }
    const prev = reveals[i - 1];
    const c = cueAt(i);
    if (c !== null) {
      reveals.push(Math.max(c, prev + 3));
      continue;
    }
    // no cue: spread evenly up to the next cued line, or up to ~75 % of the beat
    let j = i + 1;
    while (j < n && cueAt(j) === null) j++;
    const target = j < n ? (cueAt(j) as number) : Math.max(end - 12, prev + 3 * (n - i));
    const steps = j < n ? j - i + 1 : n - i;
    reveals.push(Math.max(prev + (target - prev) / steps, prev + 3));
  }
  return {appear: Math.max(typeStart - 10, 0), typeStart, typeEnd, dotsStart: typeEnd + 4, reveals};
};

// ------------------------------------------------------------------ colours
export const rgb = (c: string): number[] => {
  const h = c.trim().match(/^#([0-9a-f]{6})/i);
  if (h) {
    const v = parseInt(h[1], 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }
  const r = c.match(/rgba?\(([^)]+)\)/i);
  return r ? r[1].split(',').slice(0, 3).map((x) => parseFloat(x)) : [128, 128, 128];
};
export const hex = (c: number[]) => '#' + c.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');
export const mix = (a: string, b: string, t: number) => {
  const x = rgb(a);
  const y = rgb(b);
  return hex(x.map((v, i) => v + (y[i] - v) * t));
};
export const alpha = (c: string, a: number) => `rgba(${rgb(c).join(',')},${a})`;
export const lum = (c: string) => {
  const [r, g, b] = rgb(c).map((v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((m, k) => k - m);
  return (x + 0.05) / (y + 0.05);
};
/** A palette colour that reads on `bg`, else whichever of black and white reads better. */
export const onColor = (bg: string, prefer: string[]) =>
  prefer.find((c) => contrast(c, bg) >= 4.5) ||
  [...prefer, '#ffffff', '#111111'].reduce((a, b) => (contrast(b, bg) > contrast(a, bg) ? b : a));

export const colours = (p: Palette) => {
  const dark = lum(p.bg1) < 0.25;
  const opaquePanel = /^#[0-9a-f]{6}$/i.test(p.panel.trim()); // comic: a white panel
  const win = opaquePanel ? p.panel : dark ? mix(p.bg1, p.bg2, 0.55) : mix(p.bg1, '#ffffff', 0.65);
  const bot = mix(win, p.text, dark ? 0.1 : 0.07);
  return {
    dark,
    win,
    header: mix(win, p.text, dark ? 0.05 : 0.035),
    divider: mix(win, p.text, 0.12),
    user: p.accent,
    userText: onColor(p.accent, [p.bg1, p.text]),
    bot,
    botText: onColor(bot, [p.text]),
    hiText: contrast(p.accent, bot) >= 3.2 ? p.accent : p.text,
    avatar: p.accent2,
    avatarFace: onColor(p.accent2, [p.bg1, p.text]),
  };
};

/** Borders and shadows that match the style's labels (comic outlines, blocky bevels, neon glow). */
export const skin = (st: StyleDef, p: Palette, dark: boolean, u: number) => {
  switch (st.label) {
    case 'bubble':
      return {
        win: {border: `${5 * u}px solid #111`, boxShadow: `${10 * u}px ${10 * u}px 0 #111`},
        bubble: {border: `${4 * u}px solid #111`, boxShadow: `${5 * u}px ${5 * u}px 0 #111`},
        border: 4 * u,
      };
    case 'toast':
      return {
        win: {border: `${5 * u}px solid #000`, outline: `${4 * u}px solid #555`, outlineOffset: -9 * u, boxShadow: `0 ${14 * u}px 0 rgba(0,0,0,0.35)`},
        bubble: {boxShadow: `inset -${6 * u}px -${6 * u}px 0 rgba(0,0,0,0.28), inset ${6 * u}px ${6 * u}px 0 rgba(255,255,255,0.16)`},
        border: 0,
      };
    case 'neon':
      return {
        win: {border: `${3 * u}px solid ${p.accent2}`, boxShadow: `0 0 ${30 * u}px ${alpha(p.accent2, 0.5)}, inset 0 0 ${24 * u}px ${alpha(p.accent2, 0.16)}`},
        bubble: {boxShadow: `0 0 ${18 * u}px ${alpha(p.accent, 0.45)}`},
        border: 0,
      };
    default:
      return {
        win: {boxShadow: dark ? `0 ${30 * u}px ${80 * u}px rgba(0,0,0,0.5)` : `0 ${24 * u}px ${64 * u}px rgba(40,30,10,0.16)`},
        bubble: {},
        border: 0,
      };
  }
};

// ------------------------------------------------------------------ text
export type Seg = {text: string; hi: boolean};

/** Split text into plain and highlighted runs (case-insensitive, every occurrence). */
export const marks = (text: string, highlight: string[]): Seg[] => {
  const cs = Array.from(text);
  const low = cs.map((c) => c.toLowerCase());
  const on = cs.map(() => false);
  for (const h of highlight) {
    const nd = Array.from(String(h).trim()).map((c) => c.toLowerCase());
    if (!nd.length) continue;
    for (let i = 0; i + nd.length <= low.length; i++) {
      let k = 0;
      while (k < nd.length && low[i + k] === nd[k]) k++;
      if (k === nd.length) {
        for (let j = i; j < i + k; j++) on[j] = true;
        i += k - 1;
      }
    }
  }
  const segs: Seg[] = [];
  cs.forEach((c, i) => {
    const last = segs[segs.length - 1];
    if (last && last.hi === on[i]) last.text += c;
    else segs.push({text: c, hi: on[i]});
  });
  return segs;
};

/** The first n characters of the runs (what has been typed so far). */
export const take = (segs: Seg[], n: number): Seg[] => {
  const out: Seg[] = [];
  let left = n;
  for (const s of segs) {
    if (left <= 0) break;
    const cs = Array.from(s.text);
    out.push({text: cs.slice(0, left).join(''), hi: s.hi});
    left -= cs.length;
  }
  return out;
};

export const Rich: React.FC<{segs: Seg[]; hi: React.CSSProperties}> = ({segs, hi}) => (
  <>
    {segs.map((s, i) =>
      s.hi ? (
        <span key={i} style={hi}>
          {s.text}
        </span>
      ) : (
        <React.Fragment key={i}>{s.text}</React.Fragment>
      ),
    )}
  </>
);

// the bundled fonts with Cyrillic letters; other body fonts (Space Grotesk) fall back to Inter for Cyrillic text
export const CYRILLIC_FONTS = /Inter|Pixelify|Playfair|Montserrat/;
export const chatFamily = (body: string, text: string) =>
  /[Ѐ-ӿ]/.test(text) && !CYRILLIC_FONTS.test(body) ? 'Inter, Arial, sans-serif' : body;

/** Waits until the faces for exactly these characters are loaded (Cyrillic subsets load on demand). */
export const useChatFonts = (family: string, text: string) => {
  const [handle] = useState(() => delayRender('Loading chat fonts'));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const sample = text || 'Aa';
    Promise.all([600, 800].map((w) => document.fonts.load(`${w} 40px ${family}`, sample)))
      .catch(() => undefined)
      .then(() => setReady(true));
  }, [family, text]);
  useEffect(() => {
    if (ready) continueRender(handle);
  }, [ready, handle]);
  return ready;
};

let canvasCtx: CanvasRenderingContext2D | null | undefined;
/** Lines the text takes at this font and width (greedy word wrap, as the browser does). */
export const lineCount = (text: string, weight: number, size: number, family: string, max: number) => {
  if (canvasCtx === undefined) canvasCtx = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
  if (!canvasCtx) return Math.max(1, Math.ceil((Array.from(text).length * size * 0.58) / max));
  canvasCtx.font = `${weight} ${size}px ${family}`;
  const space = canvasCtx.measureText(' ').width;
  let lines = 1;
  let cur = 0;
  for (const w of text.split(/\s+/).filter(Boolean)) {
    let ww = canvasCtx.measureText(w).width;
    if (cur > 0 && cur + space + ww <= max) {
      cur += space + ww;
      continue;
    }
    if (cur > 0) lines++;
    while (ww > max) {
      lines++; // a word longer than the line breaks anywhere
      ww -= max;
    }
    cur = ww;
  }
  return lines;
};

export const Avatar: React.FC<{size: number; bg: string; fg: string; square: boolean; logo?: string}> = ({size, bg, fg, square, logo}) => {
  const mark = logo ? LOGOS[logo] : undefined;
  if (mark) {
    // the tool's own mark on a white disc, so the viewer sees which assistant this is
    return (
      <svg width={size} height={size} viewBox="0 0 100 100" style={{flexShrink: 0}}>
        {square ? <rect width={100} height={100} fill="#ffffff" /> : <circle cx={50} cy={50} r={50} fill="#ffffff" />}
        <g transform="translate(20 20) scale(2.5)">
          <path d={mark.path} fill={mark.color} />
        </g>
      </svg>
    );
  }
  return <BotFace size={size} bg={bg} fg={fg} square={square} />;
};

const BotFace: React.FC<{size: number; bg: string; fg: string; square: boolean}> = ({size, bg, fg, square}) => (
  <svg width={size} height={size} viewBox="0 0 100 100" style={{flexShrink: 0}}>
    {square ? <rect width={100} height={100} fill={bg} /> : <circle cx={50} cy={50} r={50} fill={bg} />}
    <line x1={50} y1={20} x2={50} y2={32} stroke={fg} strokeWidth={5} strokeLinecap="round" />
    <circle cx={50} cy={18} r={5.5} fill={fg} />
    <rect x={24} y={31} width={52} height={42} rx={square ? 0 : 14} fill={fg} />
    <circle cx={39.5} cy={50} r={6} fill={bg} />
    <circle cx={60.5} cy={50} r={6} fill={bg} />
    <rect x={40} y={61} width={20} height={4.5} rx={2.2} fill={bg} />
  </svg>
);

// ------------------------------------------------------------------ the scene
export const Chat: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const prompt = String(props.prompt ?? '');
  const answer: string[] = (Array.isArray(props.answer) ? props.answer : []).map((a: unknown) => String(a));
  const highlight: string[] = (Array.isArray(props.highlight) ? props.highlight : []).map((h: unknown) => String(h));
  const title = props.title ? String(props.title) : '';
  const all = [title, prompt, ...answer].join(' ');
  const family = chatFamily(st.fonts.body, all);
  const fontsReady = useChatFonts(family, all);

  const c = colours(p);
  const sk = skin(st, p, c.dark, u);
  const bw = sk.border;

  // geometry: the UI band keeps clear of the platform's top bar, and the captions sit below it
  const padX = (vertical ? 30 : 34) * u;
  const bubbleMaxFor = (cardW: number) => (vertical ? Math.min(width * 0.85, cardW - 2 * padX) : (cardW - 2 * padX) * 0.85);
  const zone = uiZone(width, height);
  const safeTop = zone.top;
  const safeBottom = height - zone.bottom;
  const avatar = (vertical ? 76 : 60) * u;
  const headerPadV = (vertical ? 22 : 18) * u;
  const headerH = avatar + 2 * headerPadV + 2 * u;
  const base = vertical ? {prompt: 52, answer: 48} : {prompt: 42, answer: 38};
  const LH = 1.28;

  // one text scale for the whole chat: the largest at which the finished chat fits the safe area;
  // 16:9 widens the window for a long chat rather than shrinking the text far
  const {s, cardW} = useMemo(() => {
    const avail = (height - safeTop - safeBottom) * 0.97 - headerH - 10 * u; // 10: the window's border
    const fits = (k: number, max: number) => {
      const pv = 24 * k * u;
      const textW = (max - 2 * 32 * k * u - 2 * bw) / 1.03; // a little room for bold highlights
      const bubble = (t: string, size: number) => lineCount(t, 600, size, family, textW) * size * LH + 2 * pv + 2 * bw;
      let h = (34 + 38) * k * u + bubble(prompt, base.prompt * k * u) + 34 * k * u;
      answer.forEach((a, i) => (h += bubble(a, base.answer * k * u) + (i ? 14 * k * u : 0)));
      if (!answer.length) h += 2 * pv + 20 * k * u;
      return h <= avail;
    };
    const widths = vertical ? [width - 80 * u] : [0.64, 0.74, 0.84].map((f) => width * f);
    let best = {s: 0, cardW: widths[0]};
    for (const w of widths) {
      let k = 1;
      while (k > 0.5 && !fits(k, bubbleMaxFor(w))) k -= 0.02;
      if (k > best.s + 0.04) best = {s: k, cardW: w};
      if (k >= 0.9) break;
    }
    return best;
  }, [fontsReady, family, prompt, answer.join('\n'), width, height, bw]); // fontsReady: measure again with the real fonts
  const bubbleMax = bubbleMaxFor(cardW);

  const fp = base.prompt * s * u;
  const fa = base.answer * s * u;
  const padV = 24 * s * u;
  const padH = 32 * s * u;
  const R = st.radius === 0 ? 0 : clamp(st.radius * 2.6, 14, 46) * u * Math.max(s, 0.7);
  const r = Math.min(R, 8 * u);

  const t = chatTiming(duration, speech, cues, Array.from(prompt).length, answer.length);
  const promptSegs = marks(prompt, highlight);
  const typedK = clamp((frame - t.typeStart) / Math.max(t.typeEnd - t.typeStart, 1), 0, 1);
  const typed = take(promptSegs, Math.round(Array.from(prompt).length * typedK));
  const typing = frame >= t.typeStart && frame < t.typeEnd;
  const caretOn = frame < t.dotsStart && (typing || Math.floor(frame / 8) % 2 === 0);

  const appear = rise(frame, fps, t.appear - PREROLL); // already moving on the first frame
  const dotsIn = rise(frame, fps, t.dotsStart, 14);
  // the dots give way to the first answer line (with no answer they keep going)
  const dotsOut = answer.length
    ? interpolate(frame, [t.reveals[0] - 2, t.reveals[0] + 4], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const showDots = frame >= t.dotsStart && dotsOut > 0;

  const text: React.CSSProperties = {fontFamily: family, fontWeight: 600, lineHeight: LH, overflowWrap: 'anywhere', whiteSpace: 'pre-wrap'};
  const marker = (col: string, k = 1): React.CSSProperties => ({
    fontWeight: 800,
    backgroundImage: `linear-gradient(${col}, ${col})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${k * 100}% 100%`,
    borderRadius: '0.18em',
    padding: '0 0.08em',
    margin: '0 -0.08em', // the marker bleeds out without changing the line breaks
    boxDecorationBreak: 'clone',
    WebkitBoxDecorationBreak: 'clone',
  });
  const userBubble: React.CSSProperties = {
    ...text,
    ...sk.bubble,
    fontSize: fp,
    color: c.userText,
    background: c.user,
    padding: `${padV}px ${padH}px`,
    borderRadius: `${R}px ${R}px ${r}px ${R}px`,
    minHeight: fp * LH + 2 * padV,
    boxSizing: 'border-box',
  };
  const botBubble = (i: number): React.CSSProperties => ({
    ...text,
    ...sk.bubble,
    ...(st.label === 'neon' ? {boxShadow: undefined, border: `${2 * u}px solid ${alpha(p.accent2, 0.55)}`} : {}),
    fontSize: fa,
    color: c.botText,
    background: c.bot,
    padding: `${padV}px ${padH}px`,
    borderRadius: `${i === 0 ? R : r}px ${R}px ${R}px ${r}px`,
    maxWidth: bubbleMax,
    boxSizing: 'border-box',
  });

  const caret = (
    <span
      style={{
        display: 'inline-block',
        width: Math.max(4 * u, fp * 0.08),
        height: fp * 1.05,
        marginLeft: fp * 0.04,
        marginRight: -(Math.max(4 * u, fp * 0.08) + fp * 0.04), // takes no room, so the lines break as in the final text
        verticalAlign: '-0.18em',
        background: c.userText,
        borderRadius: 2 * u,
        opacity: caretOn ? 1 : 0,
      }}
    />
  );

  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingTop: safeTop, paddingBottom: safeBottom}}>
      <div
        style={{
          ...sk.win,
          width: cardW,
          boxSizing: 'border-box',
          background: c.win,
          borderRadius: st.radius * 2 * u,
          overflow: 'hidden',
          opacity: Math.min(appear, 1),
          transform: `translateY(${(1 - appear) * 50 * u}px) scale(${0.97 + 0.03 * appear})`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 22 * u,
            padding: `${headerPadV}px ${padX}px`,
            background: c.header,
            borderBottom: `${2 * u}px solid ${c.divider}`,
            borderRadius: `${st.radius * 2 * u}px ${st.radius * 2 * u}px 0 0`,
          }}
        >
          <Avatar size={avatar} bg={c.avatar} fg={c.avatarFace} square={st.radius === 0} logo={props.app_logo} />
          {title ? (
            <div style={{fontFamily: family, fontWeight: 800, fontSize: (vertical ? 38 : 32) * u, color: p.text, lineHeight: 1.1}}>{title}</div>
          ) : null}
        </div>

        <div style={{display: 'flex', flexDirection: 'column', padding: `${34 * s * u}px ${padX}px ${38 * s * u}px`}}>
          {/* the finished prompt (hidden) holds the room; the visible bubble grows inside it as the text types */}
          <div style={{alignSelf: 'flex-end', position: 'relative', maxWidth: bubbleMax}}>
            <div style={{...userBubble, visibility: 'hidden'}}>
              <Rich segs={promptSegs} hi={marker(alpha(c.userText, 0.16))} />
            </div>
            <div style={{position: 'absolute', top: 0, right: 0, maxWidth: '100%'}}>
              <div style={userBubble}>
                <Rich segs={typed} hi={marker(alpha(c.userText, 0.16))} />
                {caret}
              </div>
            </div>
          </div>

          <div
            style={{
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              gap: 14 * s * u,
              marginTop: 34 * s * u,
              minHeight: fa * 0.4 + 2 * padV + 2 * bw,
            }}
          >
            {showDots ? (
              <div
                style={{
                  ...botBubble(0),
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  display: 'flex',
                  gap: 14 * s * u,
                  alignItems: 'center',
                  paddingTop: padV + 6 * s * u, // the dots bounce up: centre the bounce, not the resting dots
                  height: fa * LH + 2 * padV + 2 * bw,
                  opacity: Math.min(dotsIn, 1) * dotsOut,
                  transform: `scale(${0.7 + 0.3 * Math.min(dotsIn, 1)})`,
                  transformOrigin: 'left center',
                }}
              >
                {[0, 1, 2].map((i) => {
                  const w = Math.max(0, Math.sin((frame - t.dotsStart) / 4.2 - i * 0.9));
                  return (
                    <div
                      key={i}
                      style={{
                        width: 22 * s * u,
                        height: 22 * s * u,
                        borderRadius: st.radius === 0 ? 0 : '50%',
                        background: p.muted,
                        opacity: 0.45 + 0.55 * w,
                        transform: `translateY(${-w * 12 * s * u}px)`,
                      }}
                    />
                  );
                })}
              </div>
            ) : null}
            {answer.map((line, i) => {
              const at = t.reveals[i];
              const k = rise(frame, fps, at, 16);
              return (
                <div
                  key={i}
                  style={{...botBubble(i), opacity: Math.min(k, 1), transform: `translateY(${(1 - k) * 36 * s * u}px)`}}
                >
                  <Rich
                    segs={marks(line, highlight)}
                    hi={{...marker(alpha(p.accent, c.dark ? 0.22 : 0.28), progress(frame, at + 8, at + 22)), color: c.hiText}}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <Sfx name="keys" at={t.typeStart} dur={t.typeEnd - t.typeStart} />
    </AbsoluteFill>
  );
};
