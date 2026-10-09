import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONTS, usePalette} from './theme';
import type {Caption} from './types';

/** Global background: soft gradient, slowly drifting light and dust so no frame is ever frozen. */
export const Background: React.FC = () => {
  const p = usePalette();
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const t = frame / 30;
  const lx = 50 + 18 * Math.sin(t * 0.07);
  const ly = 38 + 10 * Math.cos(t * 0.05);
  const dots = Array.from({length: 28}, (_, i) => {
    const seed = (i * 9301 + 49297) % 233280;
    const r = seed / 233280;
    const x = ((r * 1.7 + i * 0.137 + t * (0.004 + r * 0.006)) % 1) * width;
    const y = ((r * 3.1 + i * 0.071) % 1) * height + Math.sin(t * 0.3 + i) * 12;
    return {x, y, s: 1.5 + r * 2.5, o: 0.08 + r * 0.12};
  });
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at ${lx}% ${ly}%, ${p.bg2} 0%, ${p.bg1} 70%)`,
      }}
    >
      <svg width={width} height={height} style={{position: 'absolute'}}>
        {dots.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r={d.s} fill={p.text} opacity={d.o} />
        ))}
      </svg>
      <AbsoluteFill
        style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.35) 100%)'}}
      />
    </AbsoluteFill>
  );
};

/** Wraps every scene: fade in/out at the cut and a slow push-in for life. */
export const SceneShell: React.FC<{duration: number; children: React.ReactNode}> = ({duration, children}) => {
  const frame = useCurrentFrame();
  const fade = Math.min(10, Math.floor(duration / 4));
  const opacity = interpolate(frame, [0, fade, duration - fade, duration], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(frame, [0, duration], [1, 1.035]);
  return <AbsoluteFill style={{opacity, transform: `scale(${scale})`}}>{children}</AbsoluteFill>;
};

export const Captions: React.FC<{captions: Caption[]; lift?: number}> = ({captions, lift = 0.06}) => {
  const frame = useCurrentFrame();
  const p = usePalette();
  const {height} = useVideoConfig();
  const cap = captions.find((c) => frame >= c.from && frame < c.to);
  if (!cap) return null;
  const local = frame - cap.from;
  const opacity = interpolate(local, [0, 5], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: height * lift}}>
      <div
        style={{
          opacity,
          maxWidth: '78%',
          padding: '14px 28px',
          borderRadius: 14,
          background: 'rgba(0,0,0,0.55)',
          color: '#ffffff',
          fontFamily: FONTS.sans,
          fontWeight: 600,
          fontSize: height * 0.034,
          lineHeight: 1.3,
          textAlign: 'center',
          textShadow: '0 2px 6px rgba(0,0,0,0.5)',
          textWrap: 'balance',
          borderBottom: `3px solid ${p.accent}`,
        }}
      >
        {cap.text}
      </div>
    </AbsoluteFill>
  );
};

/** Small uppercase label used across templates. */
export const Kicker: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => {
  const p = usePalette();
  return (
    <div
      style={{
        fontFamily: FONTS.sans,
        fontWeight: 800,
        fontSize: 30,
        letterSpacing: '0.22em',
        textTransform: 'uppercase',
        color: p.accent,
        ...style,
      }}
    >
      {children}
    </div>
  );
};
