/**
 * Visual styles: one switch changes the whole look of a video - fonts, colours, background, captions,
 * on-screen labels, scene transitions and motion. Templates read fonts through CSS variables
 * (see theme.ts FONTS) and colours through the palette, so every card follows the style too.
 */
import React, {createContext, useContext, useMemo} from 'react';
import {AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Palette} from './theme';
import {PALETTES} from './theme';
import type {Caption} from './types';

export type BackgroundKind = 'stars' | 'paper' | 'voxel' | 'synth' | 'clean' | 'halftone';
export type CaptionKind = 'pill' | 'typewriter' | 'tooltip' | 'karaoke' | 'bold' | 'comic';
export type LabelKind = 'bar' | 'ink' | 'toast' | 'neon' | 'tag' | 'bubble';
export type TransitionKind = 'fadePush' | 'wipe' | 'pixel' | 'glitch' | 'slide' | 'zoomBurst' | 'cut';

export type StyleDef = {
  name: string;
  palette: Palette;
  fonts: {display: string; body: string; caption: string; impact: string}; // impact: big kinetic text
  fontLoads: string[]; // CSS font shorthands to wait for before rendering
  background: BackgroundKind;
  caption: CaptionKind;
  label: LabelKind;
  transition: TransitionKind;
  radius: number;
};

const P = PALETTES;

// digits from Silkscreen (pixel-digits.css), letters from Pixelify Sans
const PIXEL = '"Pixel Digits", "Pixelify Sans", monospace';

export const STYLES: Record<string, StyleDef> = {
  cosmos: {
    name: 'cosmos', palette: P.midnight,
    fonts: {display: '"Playfair Display", Georgia, serif', body: 'Inter, Arial, sans-serif', caption: 'Inter, Arial, sans-serif', impact: 'Inter, Arial, sans-serif'},
    fontLoads: ['700 80px "Playfair Display"', '400 40px Inter', '600 40px Inter', '800 40px Inter'],
    background: 'stars', caption: 'pill', label: 'bar', transition: 'fadePush', radius: 14,
  },
  paper: {
    name: 'paper', palette: P.parchment,
    fonts: {display: '"DM Serif Display", Georgia, serif', body: 'Inter, Arial, sans-serif', caption: '"Special Elite", "Courier New", monospace', impact: '"DM Serif Display", Georgia, serif'},
    fontLoads: ['400 80px "DM Serif Display"', '400 40px "Special Elite"', '600 40px Inter', '800 40px Inter'],
    background: 'paper', caption: 'typewriter', label: 'ink', transition: 'wipe', radius: 4,
  },
  blocky: {
    name: 'blocky',
    palette: {bg1: '#1d2026', bg2: '#2c3038', text: '#f4f4f4', muted: '#b8bcc6', accent: '#62d13f', accent2: '#f2c94c',
      land: '#3a6b35', landStroke: '#284a25', grid: 'rgba(255,255,255,0.06)', panel: 'rgba(16,0,16,0.82)'},
    fonts: {display: PIXEL, body: PIXEL, caption: PIXEL, impact: PIXEL},
    fontLoads: ['400 40px "Pixelify Sans"', '600 40px "Pixelify Sans"', '700 80px "Pixelify Sans"',
      '400 40px "Pixel Digits"', '700 80px "Pixel Digits"'],
    background: 'voxel', caption: 'tooltip', label: 'toast', transition: 'pixel', radius: 0,
  },
  neon: {
    name: 'neon',
    palette: {bg1: '#0a0618', bg2: '#1d0b3a', text: '#f5f3ff', muted: '#a79fd1', accent: '#ff3dbb', accent2: '#2de2e6',
      land: '#1a1240', landStroke: '#3b2a7a', grid: 'rgba(255,255,255,0.05)', panel: 'rgba(255,255,255,0.05)'},
    fonts: {display: 'Orbitron, sans-serif', body: '"Space Grotesk", Arial, sans-serif', caption: '"Space Grotesk", Arial, sans-serif', impact: 'Orbitron, sans-serif'},
    fontLoads: ['800 80px Orbitron', '500 40px "Space Grotesk"', '700 40px "Space Grotesk"'],
    background: 'synth', caption: 'karaoke', label: 'neon', transition: 'glitch', radius: 10,
  },
  clean: {
    name: 'clean',
    palette: {bg1: '#f4f4f1', bg2: '#ffffff', text: '#111111', muted: '#6a6a6a', accent: '#ff5a1f', accent2: '#1f6bff',
      land: '#e4e4df', landStroke: '#c8c8c2', grid: 'rgba(0,0,0,0.05)', panel: 'rgba(0,0,0,0.045)'},
    fonts: {display: '"Archivo Black", Arial, sans-serif', body: 'Inter, Arial, sans-serif', caption: '"Archivo Black", Arial, sans-serif', impact: '"Archivo Black", Arial, sans-serif'},
    fontLoads: ['400 80px "Archivo Black"', '400 40px Inter', '600 40px Inter', '800 40px Inter'],
    background: 'clean', caption: 'bold', label: 'tag', transition: 'slide', radius: 22,
  },
  comic: {
    name: 'comic',
    palette: {bg1: '#ffd84a', bg2: '#ffe680', text: '#111111', muted: '#3a3a3a', accent: '#e8242b', accent2: '#1e5bd8',
      land: '#fff0a8', landStroke: '#111111', grid: 'rgba(0,0,0,0.08)', panel: '#ffffff'},
    fonts: {display: 'Bangers, Impact, sans-serif', body: 'Inter, Arial, sans-serif', caption: 'Bangers, Impact, sans-serif', impact: 'Bangers, Impact, sans-serif'},
    fontLoads: ['400 80px Bangers', '600 40px Inter', '800 40px Inter'],
    background: 'halftone', caption: 'comic', label: 'bubble', transition: 'zoomBurst', radius: 26,
  },
};

export const StyleContext = createContext<StyleDef>(STYLES.cosmos);
export const useStyle = () => useContext(StyleContext);

/** CSS variables read by FONTS in theme.ts. */
export const styleVars = (st: StyleDef): React.CSSProperties =>
  ({'--font-display': st.fonts.display, '--font-body': st.fonts.body, '--font-caption': st.fonts.caption,
    '--font-impact': st.fonts.impact} as React.CSSProperties);

const ease = Easing.bezier(0.33, 0, 0.2, 1);
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// ------------------------------------------------------------------ backgrounds
const Stars: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const t = frame / 30;
  const lx = 50 + 18 * Math.sin(t * 0.07);
  const ly = 38 + 10 * Math.cos(t * 0.05);
  const dots = Array.from({length: 28}, (_, i) => {
    const r = random(`dot${i}`);
    const x = ((r * 1.7 + i * 0.137 + t * (0.004 + r * 0.006)) % 1) * width;
    const y = ((r * 3.1 + i * 0.071) % 1) * height + Math.sin(t * 0.3 + i) * 12;
    return {x, y, s: 1.5 + r * 2.5, o: 0.08 + r * 0.12};
  });
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at ${lx}% ${ly}%, ${p.bg2} 0%, ${p.bg1} 70%)`}}>
      <svg width={width} height={height} style={{position: 'absolute'}}>
        {dots.map((d, i) => <circle key={i} cx={d.x} cy={d.y} r={d.s} fill={p.text} opacity={d.o} />)}
      </svg>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.35) 100%)'}} />
    </AbsoluteFill>
  );
};

/** A seeded grain tile, made once per render with a canvas (cheap to repeat over the frame). */
const useNoiseTile = (seed: string, alpha: number) =>
  useMemo(() => {
    if (typeof document === 'undefined') return '';
    const c = document.createElement('canvas');
    c.width = c.height = 160;
    const ctx = c.getContext('2d');
    if (!ctx) return '';
    const img = ctx.createImageData(160, 160);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.floor(random(`${seed}${i}`) * 255);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = Math.floor(alpha * 255);
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }, [seed, alpha]);

const Paper: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  const tile = useNoiseTile('paper', 0.09);
  const lx = 40 + 10 * Math.sin(frame / 300);
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at ${lx}% 35%, ${p.bg1} 0%, ${p.bg2} 95%)`}}>
      <AbsoluteFill style={{backgroundImage: `url(${tile})`, mixBlendMode: 'multiply', opacity: 0.9}} />
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 60%, rgba(70,45,20,0.28) 100%)'}} />
    </AbsoluteFill>
  );
};

const Voxel: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const cell = 80;
  const off = (frame * 0.35) % cell;
  const cols = Math.ceil(width / cell) + 2;
  const rows = Math.ceil(height / cell) + 2;
  const cells = [];
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const r = random(`v${x}_${y}`);
      const shade = r < 0.08 ? 0.09 : r < 0.3 ? 0.045 : 0.02;
      cells.push(<rect key={`${x}_${y}`} x={x * cell - off} y={y * cell - off} width={cell - 4} height={cell - 4} fill={p.text} opacity={shade} />);
    }
  }
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${p.bg2} 0%, ${p.bg1} 100%)`}}>
      <svg width={width} height={height} style={{position: 'absolute'}}>{cells}</svg>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 50%, rgba(0,0,0,0.5) 100%)'}} />
    </AbsoluteFill>
  );
};

const Synth: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const horizon = height * 0.62;
  const lines = [];
  for (let i = 0; i < 14; i++) {
    const k = ((i + (frame * 0.02) % 1) / 14) ** 2.2; // lines rush towards the viewer
    const y = horizon + k * (height - horizon);
    lines.push(<line key={`h${i}`} x1={0} y1={y} x2={width} y2={y} stroke={p.accent} strokeWidth={1 + k * 3} opacity={0.15 + k * 0.6} />);
  }
  for (let i = -12; i <= 12; i++) {
    lines.push(<line key={`v${i}`} x1={width / 2 + i * 22} y1={horizon} x2={width / 2 + i * 260} y2={height} stroke={p.accent} strokeWidth={1.5} opacity={0.45} />);
  }
  const sun = Math.min(width, height) * 0.36;
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${p.bg1} 0%, ${p.bg2} 62%, ${p.bg1} 62%)`}}>
      <div
        style={{
          // a setting sun: only the top half shows above the horizon, low behind the content
          position: 'absolute', left: width / 2 - sun / 2, top: horizon - sun * 0.5, width: sun, height: sun * 0.5,
          borderRadius: `${sun / 2}px ${sun / 2}px 0 0`,
          background: `linear-gradient(180deg, ${p.accent2} 0%, ${p.accent} 100%)`, opacity: 0.4,
          WebkitMaskImage: 'repeating-linear-gradient(180deg, #000 0px, #000 18px, transparent 18px, transparent 26px)',
          maskImage: 'repeating-linear-gradient(180deg, #000 0px, #000 18px, transparent 18px, transparent 26px)',
        }}
      />
      <svg width={width} height={height} style={{position: 'absolute'}}>{lines}</svg>
      <AbsoluteFill style={{background: `linear-gradient(180deg, rgba(0,0,0,0) 55%, ${p.bg1}aa 100%)`}} />
    </AbsoluteFill>
  );
};

const Clean: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  const a = 30 + 8 * Math.sin(frame / 140);
  const b = 70 + 8 * Math.cos(frame / 170);
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at ${a}% 20%, ${p.accent}1f 0%, rgba(0,0,0,0) 32%),
          radial-gradient(circle at ${b}% 85%, ${p.accent2}1a 0%, rgba(0,0,0,0) 35%),
          linear-gradient(180deg, ${p.bg2} 0%, ${p.bg1} 100%)`,
      }}
    />
  );
};

const Halftone: React.FC<{p: Palette}> = ({p}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: p.bg1, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          inset: '-40%',
          background: `repeating-conic-gradient(from ${frame * 0.15}deg at 50% 50%, ${p.bg2} 0deg 7deg, ${p.bg1} 7deg 18deg)`,
        }}
      />
      <AbsoluteFill style={{backgroundImage: 'radial-gradient(rgba(0,0,0,0.16) 24%, transparent 26%)', backgroundSize: '24px 24px'}} />
      <AbsoluteFill style={{boxShadow: 'inset 0 0 0 14px #111'}} />
    </AbsoluteFill>
  );
};

export const StyledBackground: React.FC = () => {
  const st = useStyle();
  const p = st.palette;
  switch (st.background) {
    case 'paper': return <Paper p={p} />;
    case 'voxel': return <Voxel p={p} />;
    case 'synth': return <Synth p={p} />;
    case 'clean': return <Clean p={p} />;
    case 'halftone': return <Halftone p={p} />;
    default: return <Stars p={p} />;
  }
};

// ------------------------------------------------------------------ captions
/** Word start frames, estimated by characters inside the caption's time span. */
export const wordTimes = (cap: Caption) => {
  const words = cap.text.split(/\s+/).filter(Boolean);
  const total = words.reduce((n, w) => n + w.length + 1, 0) || 1;
  let acc = 0;
  return words.map((w) => {
    const start = cap.from + ((cap.to - cap.from) * acc) / total;
    acc += w.length + 1;
    return {w, start};
  });
};

export const StyledCaptions: React.FC<{captions: Caption[]; lift?: number}> = ({captions, lift = 0.06}) => {
  const st = useStyle();
  const p = st.palette;
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const cap = captions.find((c) => frame >= c.from && frame < c.to);
  if (!cap) return null;
  const local = frame - cap.from;
  const u = Math.min(width, height) / 1080;
  const size = height * 0.034;
  const wrap = (child: React.ReactNode, extra: React.CSSProperties = {}) => (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: height * lift, ...extra}}>{child}</AbsoluteFill>
  );
  const fadeIn = interpolate(local, [0, 5], [0, 1], clamp);
  switch (st.caption) {
    case 'typewriter': {
      const k = interpolate(local, [0, Math.max((cap.to - cap.from) * 0.55, 6)], [0, 1], clamp);
      const n = Math.ceil(cap.text.length * k);
      const cursor = Math.floor(frame / 8) % 2 === 0 && k < 1;
      return wrap(
        <div style={{maxWidth: '76%', padding: `${10 * u}px ${22 * u}px`, background: 'rgba(250,244,228,0.92)', color: '#2a2118',
          fontFamily: st.fonts.caption, fontSize: size * 1.02, lineHeight: 1.35, textAlign: 'center', boxShadow: '0 4px 14px rgba(60,40,20,0.25)'}}>
          {cap.text.slice(0, n)}
          <span style={{opacity: cursor ? 1 : 0}}>▌</span>
        </div>,
      );
    }
    case 'tooltip': {
      // the in-game tooltip look: near-black purple box, two-tone border, pixel font with a hard shadow
      return wrap(
        <div style={{opacity: fadeIn, maxWidth: '76%', padding: `${12 * u}px ${24 * u}px`, background: 'rgba(16,0,16,0.94)',
          border: `${4 * u}px solid #100010`, boxShadow: `inset 0 0 0 ${3 * u}px #2d0a6b`, color: '#ffffff',
          fontFamily: st.fonts.caption, fontSize: size * 1.05, lineHeight: 1.3, textAlign: 'center', textShadow: `${3 * u}px ${3 * u}px 0 #3f3f3f`}}>
          {cap.text}
        </div>,
      );
    }
    case 'karaoke': {
      const ws = wordTimes(cap);
      return wrap(
        <div style={{maxWidth: '80%', textAlign: 'center', fontFamily: st.fonts.caption, fontWeight: 700, fontSize: size * 1.12, lineHeight: 1.35,
          textShadow: '0 2px 10px rgba(0,0,0,0.85)'}}>
          {ws.map((x, i) => {
            const on = frame >= x.start;
            const cur = on && (i === ws.length - 1 || frame < ws[i + 1].start);
            return (
              <span key={i} style={{display: 'inline-block', marginRight: '0.3em', color: on ? p.accent2 : 'rgba(255,255,255,0.6)',
                transform: `scale(${cur ? 1.1 : 1})`, textShadow: on ? `0 0 14px ${p.accent2}, 0 2px 10px rgba(0,0,0,0.85)` : undefined}}>
                {x.w}
              </span>
            );
          })}
        </div>,
      );
    }
    case 'bold': {
      // two or three words at a time, big, the current word highlighted
      const ws = wordTimes(cap);
      const groups: {w: string; start: number}[][] = [];
      ws.forEach((x, i) => (i % 3 === 0 ? groups.push([x]) : groups[groups.length - 1].push(x)));
      const g = [...groups].reverse().find((gr) => frame >= gr[0].start) || groups[0];
      const pop = spring({frame: frame - g[0].start, fps, config: {damping: 12, stiffness: 260, mass: 0.5}});
      return wrap(
        <div style={{transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`, textAlign: 'center', fontFamily: st.fonts.caption,
          fontSize: size * 1.6, textTransform: 'uppercase', lineHeight: 1.1, maxWidth: '82%'}}>
          {g.map((x, i) => {
            const cur = frame >= x.start && (i === g.length - 1 || frame < g[i + 1].start);
            return (
              <span key={i} style={{display: 'inline-block', margin: `0 ${8 * u}px`, padding: `0 ${10 * u}px`, borderRadius: 8 * u,
                background: cur ? p.accent : 'transparent', color: cur ? '#fff' : '#111', WebkitTextStroke: cur ? undefined : `${8 * u}px #fff`,
                paintOrder: 'stroke fill'}}>
                {x.w}
              </span>
            );
          })}
        </div>,
      );
    }
    case 'comic': {
      const pop = spring({frame: local, fps, config: {damping: 10, stiffness: 240, mass: 0.5}});
      return wrap(
        <div style={{position: 'relative', transform: `scale(${interpolate(pop, [0, 1], [0.7, 1])}) rotate(-1deg)`, maxWidth: '74%'}}>
          <div style={{background: '#fff', border: `${5 * u}px solid #111`, borderRadius: 28 * u, padding: `${12 * u}px ${28 * u}px`,
            fontFamily: st.fonts.caption, fontSize: size * 1.25, letterSpacing: '0.03em', color: '#111', textAlign: 'center', lineHeight: 1.15,
            boxShadow: `${8 * u}px ${8 * u}px 0 #111`}}>
            {cap.text.toUpperCase()}
          </div>
          <svg width={60 * u} height={40 * u} style={{position: 'absolute', left: 60 * u, bottom: -34 * u}}>
            <polygon points={`0,0 ${50 * u},0 ${8 * u},${36 * u}`} fill="#fff" stroke="#111" strokeWidth={5 * u} strokeLinejoin="round" />
            <rect x={3 * u} y={-6 * u} width={44 * u} height={9 * u} fill="#fff" />
          </svg>
        </div>,
      );
    }
    default:
      return wrap(
        <div style={{opacity: fadeIn, maxWidth: '78%', padding: '14px 28px', borderRadius: 14, background: 'rgba(0,0,0,0.55)', color: '#ffffff',
          fontFamily: st.fonts.caption, fontWeight: 600, fontSize: size, lineHeight: 1.3, textAlign: 'center',
          textShadow: '0 2px 6px rgba(0,0,0,0.5)', textWrap: 'balance', borderBottom: `3px solid ${p.accent}`}}>
          {cap.text}
        </div>,
      );
  }
};

// ------------------------------------------------------------------ labels on footage
export const StyledLabel: React.FC<{label: string; sublabel?: string; duration: number; start: number}> = ({label, sublabel, duration, start}) => {
  const st = useStyle();
  const p = st.palette;
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const u = Math.min(width, height) / 1080;
  const k = spring({frame: frame - start, fps, config: {damping: 16, stiffness: 160}});
  const out = interpolate(frame, [duration - 14, duration - 4], [1, 0], clamp);
  const bottom = 345 * u;
  switch (st.label) {
    case 'ink': {
      const line = interpolate(frame, [start + 6, start + 26], [0, 1], {...clamp, easing: ease});
      return (
        <div style={{position: 'absolute', left: 80 * u, bottom, opacity: k * out, transform: `rotate(-1.5deg) translateY(${(1 - k) * 20 * u}px)`,
          background: '#f4ecd8', padding: `${16 * u}px ${30 * u}px ${18 * u}px`, boxShadow: '0 10px 24px rgba(0,0,0,0.35)', color: '#2a2118'}}>
          <div style={{fontFamily: st.fonts.display, fontSize: 48 * u, lineHeight: 1.05}}>{label}</div>
          <div style={{height: 4 * u, width: `${line * 100}%`, background: p.accent, margin: `${8 * u}px 0`}} />
          {sublabel ? <div style={{fontFamily: st.fonts.caption, fontSize: 26 * u}}>{sublabel}</div> : null}
        </div>
      );
    }
    case 'toast': {
      // slides in from the top right in steps, like a game notification
      const step = Math.floor(Math.max(frame - start, 0) / 3) * 3;
      const slide = interpolate(step, [0, 12], [1, 0], clamp);
      return (
        <div style={{position: 'absolute', right: 70 * u, top: 70 * u, display: 'flex', alignItems: 'center', gap: 22 * u, opacity: out,
          transform: `translateX(${slide * 120}%)`, background: '#212121', border: `${4 * u}px solid #000`, boxShadow: `inset 0 0 0 ${4 * u}px #555`,
          padding: `${16 * u}px ${28 * u}px ${16 * u}px ${18 * u}px`, minWidth: 520 * u}}>
          <div style={{width: 72 * u, height: 72 * u, background: p.accent, boxShadow: `inset -${8 * u}px -${8 * u}px 0 rgba(0,0,0,0.3), inset ${8 * u}px ${8 * u}px 0 rgba(255,255,255,0.25)`}} />
          <div>
            <div style={{fontFamily: st.fonts.display, fontSize: 30 * u, color: '#ffff55', textShadow: `${3 * u}px ${3 * u}px 0 #3f3f15`}}>{sublabel || 'New!'}</div>
            <div style={{fontFamily: st.fonts.display, fontSize: 40 * u, color: '#fff', textShadow: `${3 * u}px ${3 * u}px 0 #3f3f3f`}}>{label}</div>
          </div>
        </div>
      );
    }
    case 'neon': {
      const flicker = frame - start < 10 ? (Math.floor((frame - start) / 2) % 2 === 0 ? 0.35 : 1) : 1;
      return (
        <div style={{position: 'absolute', left: 80 * u, top: 80 * u, opacity: k * out * flicker, padding: `${14 * u}px ${28 * u}px`,
          border: `${3 * u}px solid ${p.accent2}`, borderRadius: 10 * u, background: 'rgba(10,6,24,0.6)',
          boxShadow: `0 0 18px ${p.accent2}, inset 0 0 14px ${p.accent2}55`}}>
          <div style={{fontFamily: st.fonts.display, fontWeight: 800, fontSize: 40 * u, color: p.accent2, letterSpacing: '0.06em', textShadow: `0 0 12px ${p.accent2}`}}>
            {label.toUpperCase()}
          </div>
          {sublabel ? <div style={{fontFamily: st.fonts.body, fontWeight: 500, fontSize: 26 * u, color: '#e9e4ff', marginTop: 6 * u}}>{sublabel}</div> : null}
        </div>
      );
    }
    case 'tag':
      return (
        <div style={{position: 'absolute', left: 80 * u, bottom, opacity: out, transform: `scale(${k})`, transformOrigin: 'left center',
          background: '#fff', borderRadius: 22 * u, padding: `${16 * u}px ${30 * u}px`, boxShadow: '0 12px 30px rgba(0,0,0,0.25)', display: 'flex', gap: 18 * u, alignItems: 'center'}}>
          <div style={{width: 22 * u, height: 22 * u, borderRadius: 11 * u, background: p.accent, flexShrink: 0}} />
          <div>
            <div style={{fontFamily: st.fonts.display, fontSize: 40 * u, color: '#111', lineHeight: 1.05}}>{label}</div>
            {sublabel ? <div style={{fontFamily: st.fonts.body, fontWeight: 600, fontSize: 26 * u, color: '#555', marginTop: 4 * u}}>{sublabel}</div> : null}
          </div>
        </div>
      );
    case 'bubble':
      return (
        <div style={{position: 'absolute', left: 80 * u, bottom: bottom + 20 * u, opacity: out, transform: `scale(${k}) rotate(-2deg)`, transformOrigin: 'left bottom'}}>
          <div style={{background: '#fff', border: `${5 * u}px solid #111`, borderRadius: 26 * u, padding: `${14 * u}px ${28 * u}px`, boxShadow: `${8 * u}px ${8 * u}px 0 #111`}}>
            <div style={{fontFamily: st.fonts.display, fontSize: 52 * u, color: p.accent, letterSpacing: '0.03em', lineHeight: 1}}>{label.toUpperCase()}</div>
            {sublabel ? <div style={{fontFamily: st.fonts.body, fontWeight: 800, fontSize: 26 * u, color: '#111', marginTop: 6 * u}}>{sublabel}</div> : null}
          </div>
          <svg width={60 * u} height={44 * u} style={{position: 'absolute', left: 40 * u, bottom: -38 * u}}>
            <polygon points={`0,0 ${50 * u},0 ${6 * u},${40 * u}`} fill="#fff" stroke="#111" strokeWidth={5 * u} strokeLinejoin="round" />
            <rect x={3 * u} y={-7 * u} width={44 * u} height={10 * u} fill="#fff" />
          </svg>
        </div>
      );
    default:
      return (
        <div style={{position: 'absolute', left: 80 * u, bottom, display: 'flex', alignItems: 'stretch', opacity: k * out,
          transform: `translateX(${(1 - k) * -40 * u}px)`, background: 'rgba(8,10,18,0.78)', borderRadius: 12 * u, overflow: 'hidden'}}>
          <div style={{width: 9 * u, background: p.accent}} />
          <div style={{padding: `${16 * u}px ${28 * u}px`}}>
            <div style={{fontFamily: st.fonts.body, fontWeight: 800, fontSize: 44 * u, color: '#fff', lineHeight: 1.1}}>{label}</div>
            {sublabel ? <div style={{fontFamily: st.fonts.body, fontWeight: 600, fontSize: 28 * u, color: '#c9cfdb', marginTop: 6 * u}}>{sublabel}</div> : null}
          </div>
        </div>
      );
  }
};

// ------------------------------------------------------------------ scene transitions
export const StyledShell: React.FC<{duration: number; transition?: string; children: React.ReactNode}> = ({duration, transition, children}) => {
  const st = useStyle();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const kind = (transition || st.transition) as TransitionKind;
  const d = duration;
  const fadeOut = (n: number) => interpolate(frame, [d - n, d], [1, 0], clamp);
  switch (kind) {
    case 'cut':
      return <AbsoluteFill>{children}</AbsoluteFill>;
    case 'wipe': {
      const k = interpolate(frame, [0, 14], [0, 1], {...clamp, easing: ease});
      return <AbsoluteFill style={{clipPath: `inset(0 ${(1 - k) * 100}% 0 0)`, opacity: fadeOut(8)}}>{children}</AbsoluteFill>;
    }
    case 'pixel': {
      const cols = 16;
      const rows = 9;
      const inK = frame / 10;
      const outK = (frame - (d - 9)) / 9;
      const blocks = [];
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          const r = random(`px${x}_${y}`);
          if (r > inK || (outK > 0 && r < outK)) {
            blocks.push(<div key={`${x}_${y}`} style={{position: 'absolute', left: `${(x * 100) / cols}%`, top: `${(y * 100) / rows}%`,
              width: `${100 / cols + 0.1}%`, height: `${100 / rows + 0.2}%`, background: st.palette.bg1}} />);
          }
        }
      }
      const z = 1 + 0.03 * (Math.floor(frame / 6) * 6) / Math.max(d, 1); // stepped push-in
      return (
        <AbsoluteFill>
          <AbsoluteFill style={{transform: `scale(${z})`}}>{children}</AbsoluteFill>
          {blocks}
        </AbsoluteFill>
      );
    }
    case 'glitch': {
      const g = frame < 7 ? 1 - frame / 7 : frame > d - 6 ? (frame - (d - 6)) / 6 : 0;
      const jx = g * 26 * (random(`gx${frame}`) - 0.5) * 2;
      const flick = g > 0 && random(`gf${frame}`) < 0.3 ? 0.4 : 1;
      return (
        <AbsoluteFill style={{transform: `translateX(${jx}px) skewX(${g * 4 * (random(`gs${frame}`) - 0.5)}deg)`, opacity: flick * fadeOut(4),
          filter: g > 0 ? `drop-shadow(${8 * g}px 0 rgba(255,40,140,0.85)) drop-shadow(${-8 * g}px 0 rgba(40,230,255,0.85)) hue-rotate(${g * 40}deg)` : undefined}}>
          {children}
        </AbsoluteFill>
      );
    }
    case 'slide': {
      const k = interpolate(frame, [0, 13], [1, 0], {...clamp, easing: Easing.out(Easing.cubic)});
      const o = interpolate(frame, [d - 9, d], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
      return <AbsoluteFill style={{transform: `translateX(${k * 100 - o * 40}%)`, opacity: 1 - o}}>{children}</AbsoluteFill>;
    }
    case 'zoomBurst': {
      const s = spring({frame, fps, config: {damping: 12, stiffness: 200, mass: 0.6}});
      const o = interpolate(frame, [d - 7, d], [0, 1], clamp);
      return (
        <AbsoluteFill style={{transform: `scale(${interpolate(s, [0, 1], [1.35, 1]) + o * 0.15}) rotate(${interpolate(s, [0, 1], [-4, 0])}deg)`,
          opacity: interpolate(frame, [0, 3], [0, 1], clamp) * (1 - o)}}>
          {children}
        </AbsoluteFill>
      );
    }
    default: {
      const fade = Math.min(10, Math.floor(d / 4));
      const opacity = interpolate(frame, [0, fade, d - fade, d], [0, 1, 1, 0], clamp);
      return <AbsoluteFill style={{opacity, transform: `scale(${interpolate(frame, [0, d], [1, 1.035])})`}}>{children}</AbsoluteFill>;
    }
  }
};
