import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, revealAt, rise, stagger} from '../anim';
import {FONTS, usePalette} from '../theme';
import type {SceneProps} from '../types';
import {Kicker} from '../ui';

const useUnit = () => {
  const {width, height} = useVideoConfig();
  return Math.min(width, height) / 1080;
};

export const TitleCard: React.FC<SceneProps> = ({props, speech}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const words = String(props.title || '').split(' ');
  const start = Math.max(speech - 6, 4);
  const line = progress(frame, start + 10, start + 40);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: 120 * u}}>
      {props.kicker && (
        <Kicker style={{opacity: rise(frame, fps, start - 4), marginBottom: 28 * u, fontSize: 30 * u}}>
          {props.kicker}
        </Kicker>
      )}
      <div style={{textAlign: 'center', maxWidth: 1500 * u, textWrap: 'balance'}}>
        {words.map((w, i) => {
          const r = rise(frame, fps, start + i * 3);
          return (
            <span
              key={i}
              style={{
                display: 'inline-block',
                marginRight: '0.28em',
                opacity: r,
                transform: `translateY(${(1 - r) * 40 * u}px)`,
                fontFamily: FONTS.serif,
                fontWeight: 700,
                fontSize: (words.length > 6 ? 96 : 116) * u,
                lineHeight: 1.08,
                color: p.text,
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
      <div style={{width: 260 * u * line, height: 5 * u, background: p.accent, marginTop: 34 * u, borderRadius: 3}} />
      {props.subtitle && (
        <div
          style={{
            marginTop: 30 * u,
            opacity: rise(frame, fps, start + 14),
            fontFamily: FONTS.sans,
            fontSize: 42 * u,
            color: p.muted,
            textAlign: 'center',
            maxWidth: 1300 * u,
            textWrap: 'balance',
          }}
        >
          {props.subtitle}
        </div>
      )}
    </AbsoluteFill>
  );
};

export const Kinetic: React.FC<SceneProps> = ({props, speech, duration, cues}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const lines: string[] = props.lines || [];
  const emph = new Set((props.emphasis || []).map((w: string) => w.toLowerCase().replace(/[^a-z0-9]/g, '')));
  const all = lines.flatMap((l, li) => l.split(' ').map((w) => ({w, li})));
  const size = (lines.length >= 3 ? 74 : lines.length === 2 ? 88 : 104) * u;
  let k = 0;
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: 120 * u}}>
      {lines.map((l, li) => (
        <div key={li} style={{textAlign: 'center', marginBottom: 18 * u}}>
          {l.split(' ').map((w, wi) => {
            const idx = k++;
            // a line with a narration cue appears when its words are spoken (the first line no later than
            // the narration itself, so the screen is never empty); otherwise words spread out
            const c = cues[li];
            const lineStart = typeof c === 'number' ? Math.max(c - 4, 0) : null;
            const start = lineStart === null
              ? stagger(idx, all.length, speech, duration, 0.5)
              : (li === 0 ? Math.min(lineStart, speech) : lineStart) + wi * 3;
            const r = rise(frame, fps, start);
            const isEm = emph.has(w.toLowerCase().replace(/[^a-z0-9]/g, ''));
            return (
              <span
                key={wi}
                style={{
                  display: 'inline-block',
                  marginRight: '0.26em',
                  opacity: r,
                  transform: `translateY(${(1 - r) * 30 * u}px) scale(${isEm ? 1 + 0.06 * r : 1})`,
                  fontFamily: FONTS.sans,
                  fontWeight: 800,
                  fontSize: size,
                  color: isEm ? p.accent : p.text,
                  letterSpacing: '-0.01em',
                }}
              >
                {w}
              </span>
            );
          })}
        </div>
      ))}
    </AbsoluteFill>
  );
};

export const FactCard: React.FC<SceneProps> = ({props, speech, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const words = String(props.text || '').split(' ');
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: 160 * u}}>
      <div
        style={{
          position: 'relative',
          maxWidth: 1400 * u,
          padding: `${70 * u}px ${90 * u}px`,
          borderRadius: 26 * u,
          background: p.panel,
          borderLeft: `${8 * u}px solid ${p.accent}`,
          opacity: rise(frame, fps, speech - 8),
        }}
      >
        {props.kicker && <Kicker style={{fontSize: 26 * u, marginBottom: 22 * u}}>{props.kicker}</Kicker>}
        <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 60 * u, lineHeight: 1.3, color: p.text, textWrap: 'pretty'}}>
          {words.map((w, i) => (
            <span
              key={i}
              style={{opacity: interpolate(frame, [stagger(i, words.length, speech, duration, 0.6), stagger(i, words.length, speech, duration, 0.6) + 8], [0.15, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}
            >
              {w}{' '}
            </span>
          ))}
        </div>
        {props.source && (
          <div style={{marginTop: 30 * u, fontFamily: FONTS.sans, fontSize: 30 * u, color: p.muted, opacity: rise(frame, fps, speech + 20)}}>
            — {props.source}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

export const ListCard: React.FC<SceneProps> = ({props, speech, duration, cues}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const items: string[] = props.items || [];
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `0 ${160 * u}px`}}>
      <div style={{maxWidth: 1500 * u}}>
      {props.title && (
        <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 76 * u, color: p.text, marginBottom: 46 * u, opacity: rise(frame, fps, speech - 8)}}>
          {props.title}
        </div>
      )}
      {items.map((it, i) => {
        const r = rise(frame, fps, revealAt(i, items.length, speech + 6, duration, cues, 0.7));
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', marginBottom: 30 * u, opacity: r, transform: `translateX(${(1 - r) * -50 * u}px)`}}>
            <div style={{width: 54 * u, height: 54 * u, borderRadius: 27 * u, background: p.accent, color: p.bg1, fontFamily: FONTS.sans, fontWeight: 800, fontSize: 30 * u, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 30 * u, flexShrink: 0}}>
              {i + 1}
            </div>
            <div style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 50 * u, color: p.text}}>{it}</div>
          </div>
        );
      })}
      </div>
    </AbsoluteFill>
  );
};
