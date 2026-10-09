import React from 'react';
import {AbsoluteFill, Easing, interpolate, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {firstCue, revealAt, rise} from '../anim';
import {StyledLabel} from '../styles';
import {FONTS, usePalette} from '../theme';
import type {SceneProps} from '../types';

const ease = Easing.bezier(0.33, 0, 0.2, 1);

/** A clip of the user's recording, filling the frame, with a slow push-in and an optional lower third. */
export const Footage: React.FC<SceneProps> = ({props, duration, speech}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  const focus: [number, number] = props.focus || [0.5, 0.5];
  const z = interpolate(frame, [0, Math.max(duration - 1, 1)], [props.zoom ?? 1.0, props.zoom_to ?? (props.zoom ?? 1.0) * 1.06], {
    easing: ease,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          transform: `scale(${z})`,
          transformOrigin: `${focus[0] * 100}% ${focus[1] * 100}%`,
          // dark recordings (caves, night) can be lifted: brightness 1.5 = +50%
          filter: props.brightness ? `brightness(${props.brightness}) contrast(1.05)` : undefined,
        }}
      >
        <OffthreadVideo
          src={staticFile(props.src)}
          trimBefore={Math.round((props.in ?? 0) * fps)}
          playbackRate={props.speed ?? 1}
          muted
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </AbsoluteFill>
      {props.label ? <StyledLabel label={props.label} sublabel={props.sublabel} duration={duration} start={Math.max(speech, 6)} /> : null}
      {props.badge ? (
        <div
          style={{
            position: 'absolute',
            left: 80 * u,
            top: 70 * u,
            padding: `${8 * u}px ${20 * u}px`,
            borderRadius: 10 * u,
            background: 'rgba(8,10,18,0.78)',
            border: `${3 * u}px solid ${p.accent}`,
            fontFamily: FONTS.sans,
            fontWeight: 800,
            fontSize: 34 * u,
            color: p.accent,
          }}
        >
          {props.badge}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** Review verdict: score ring on the left, pros and cons revealed on the narration cues. */
export const Verdict: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  const outOf = props.out_of ?? 10;
  const score = Number(props.score || 0);
  const start = firstCue(speech, cues);
  const k = interpolate(frame, [start, start + 40], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const pros: string[] = props.pros || [];
  const cons: string[] = props.cons || [];
  const items = [...pros.map((t) => ({t, good: true})), ...cons.map((t) => ({t, good: false}))];
  const r = 240 * u;
  const circ = 2 * Math.PI * r;
  const good = '#5fd38d';
  const bad = '#ff6b6b';
  const Item: React.FC<{t: string; good: boolean; i: number}> = ({t, good: g, i}) => {
    const a = rise(frame, fps, revealAt(i + 1, items.length + 1, speech + 10, duration, cues, 0.75));
    return (
      <div style={{display: 'flex', alignItems: 'center', marginBottom: 22 * u, opacity: a, transform: `translateX(${(1 - a) * 30 * u}px)`}}>
        <div
          style={{
            width: 54 * u, height: 54 * u, borderRadius: 27 * u, marginRight: 22 * u, flexShrink: 0,
            background: g ? good : bad, color: '#0b1020', fontFamily: FONTS.sans, fontWeight: 800, fontSize: 30 * u,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {g ? '+' : '–'}
        </div>
        <div style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 48 * u, color: p.text}}>{t}</div>
      </div>
    );
  };
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
      {props.title ? (
        <div style={{position: 'absolute', top: 100 * u, fontFamily: FONTS.serif, fontWeight: 700, fontSize: 66 * u, color: p.text, opacity: rise(frame, fps, speech - 8)}}>
          {props.title}
        </div>
      ) : null}
      <div style={{display: 'flex', alignItems: 'center', gap: 110 * u, marginTop: 60 * u}}>
        <div style={{position: 'relative', width: 2 * r + 40 * u, height: 2 * r + 40 * u}}>
          <svg width={2 * r + 40 * u} height={2 * r + 40 * u}>
            <circle cx={r + 20 * u} cy={r + 20 * u} r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth={22 * u} />
            <circle
              cx={r + 20 * u} cy={r + 20 * u} r={r} fill="none" stroke={p.accent} strokeWidth={22 * u} strokeLinecap="round"
              strokeDasharray={`${circ * (score / outOf) * k} ${circ}`} transform={`rotate(-90 ${r + 20 * u} ${r + 20 * u})`}
            />
          </svg>
          <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
            <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 170 * u, color: p.accent, lineHeight: 1}}>
              {(score * k).toFixed(Number.isInteger(score) ? 0 : 1)}
            </div>
            <div style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 40 * u, color: p.muted}}>out of {outOf}</div>
          </div>
        </div>
        <div style={{maxWidth: 820 * u}}>
          {items.map((it, i) => (
            <Item key={i} t={it.t} good={it.good} i={i} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
