import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise, stagger} from '../anim';
import {FONTS, usePalette} from '../theme';
import type {SceneProps} from '../types';

const useUnit = () => {
  const {width, height} = useVideoConfig();
  return Math.min(width, height) / 1080;
};

const fmt = (v: number, decimals = 0) =>
  v.toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

export const Stat: React.FC<SceneProps> = ({props, speech}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const value = Number(props.value || 0);
  const decimals = props.decimals ?? (Number.isInteger(value) ? 0 : 2);
  const k = progress(frame, speech, speech + 42);
  const ring = rise(frame, fps, speech - 6, 24);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
      <div
        style={{
          position: 'absolute',
          width: 760 * u * ring,
          height: 760 * u * ring,
          borderRadius: '50%',
          border: `2px solid ${p.accent}`,
          opacity: 0.25,
        }}
      />
      <div style={{display: 'flex', alignItems: 'baseline', opacity: rise(frame, fps, speech - 4)}}>
        {props.prefix && (
          <span style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 80 * u, color: p.muted, marginRight: 20 * u}}>
            {props.prefix}
          </span>
        )}
        <span style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 230 * u, color: p.accent, lineHeight: 1}}>
          {fmt(value * k, decimals)}
        </span>
        {props.suffix && (
          <span style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 80 * u, color: p.muted, marginLeft: 20 * u}}>
            {props.suffix}
          </span>
        )}
      </div>
      <div
        style={{
          marginTop: 30 * u,
          fontFamily: FONTS.sans,
          fontWeight: 600,
          fontSize: 50 * u,
          color: p.text,
          textAlign: 'center',
          maxWidth: 1300 * u,
          opacity: rise(frame, fps, speech + 10),
        }}
      >
        {props.label}
      </div>
      {props.note && (
        <div style={{marginTop: 16 * u, fontFamily: FONTS.sans, fontSize: 32 * u, color: p.muted, opacity: rise(frame, fps, speech + 22)}}>
          {props.note}
        </div>
      )}
    </AbsoluteFill>
  );
};

export const Comparison: React.FC<SceneProps> = ({props, speech}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const sides = [props.left || {}, props.right || {}];
  const max = Math.max(...sides.map((s) => Number(s.value) || 0), 1);
  const colors = [p.accent2, p.accent];
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
      {props.title && (
        <div style={{position: 'absolute', top: 110 * u, fontFamily: FONTS.serif, fontWeight: 700, fontSize: 70 * u, color: p.text, opacity: rise(frame, fps, speech - 8)}}>
          {props.title}
        </div>
      )}
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 220 * u, height: 560 * u, marginTop: 120 * u}}>
        {sides.map((s, i) => {
          const g = progress(frame, speech + i * 14, speech + i * 14 + 36);
          const h = (480 * u * (Number(s.value) || 0)) / max;
          return (
            <div key={i} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: 300 * u}}>
              <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 64 * u, color: colors[i], marginBottom: 14 * u, opacity: g}}>
                {fmt((Number(s.value) || 0) * g, Number.isInteger(s.value) ? 0 : 1)}
                {props.unit ? <span style={{fontSize: 34 * u, color: p.muted}}> {props.unit}</span> : null}
              </div>
              <div style={{width: 200 * u, height: Math.max(h * g, 2), background: colors[i], borderRadius: `${12 * u}px ${12 * u}px 0 0`}} />
              <div style={{marginTop: 20 * u, fontFamily: FONTS.sans, fontWeight: 600, fontSize: 40 * u, color: p.text, textAlign: 'center'}}>
                {s.label}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const Bars: React.FC<SceneProps> = ({props, speech, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const items: {label: string; value: number}[] = props.items || [];
  const max = Math.max(...items.map((it) => it.value), 1);
  return (
    <AbsoluteFill style={{justifyContent: 'center', padding: `0 ${200 * u}px`}}>
      {props.title && (
        <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 70 * u, color: p.text, marginBottom: 50 * u, opacity: rise(frame, fps, speech - 8)}}>
          {props.title}
        </div>
      )}
      {items.map((it, i) => {
        const s = stagger(i, items.length, speech, duration, 0.5);
        const g = progress(frame, s, s + 30);
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', marginBottom: 26 * u}}>
            <div style={{width: 330 * u, fontFamily: FONTS.sans, fontWeight: 600, fontSize: 38 * u, color: p.text, opacity: rise(frame, fps, s - 6)}}>
              {it.label}
            </div>
            <div style={{height: 52 * u, width: (1000 * u * it.value * g) / max, background: i === 0 ? p.accent : p.accent2, borderRadius: 8 * u}} />
            <div style={{marginLeft: 20 * u, fontFamily: FONTS.sans, fontWeight: 800, fontSize: 38 * u, color: p.muted, opacity: g}}>
              {fmt(it.value * g, Number.isInteger(it.value) ? 0 : 1)}
              {props.unit ? ` ${props.unit}` : ''}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

export const Timeline: React.FC<SceneProps> = ({props, speech, duration}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const events: {year: string; label: string}[] = props.events || [];
  const n = events.length;
  const margin = 200 * u;
  const usable = width - 2 * margin;
  const axis = progress(frame, speech - 6, speech + 30);
  return (
    <AbsoluteFill style={{justifyContent: 'center'}}>
      {props.title && (
        <div style={{position: 'absolute', top: 150 * u, width: '100%', textAlign: 'center', fontFamily: FONTS.serif, fontWeight: 700, fontSize: 70 * u, color: p.text, opacity: rise(frame, fps, speech - 8)}}>
          {props.title}
        </div>
      )}
      <div style={{position: 'absolute', left: margin, top: '52%', height: 4 * u, width: usable * axis, background: p.muted, opacity: 0.5}} />
      {events.map((e, i) => {
        const x = margin + (n === 1 ? usable / 2 : (usable * i) / (n - 1));
        const s = stagger(i, n, speech + 8, duration, 0.6);
        const r = rise(frame, fps, s);
        const hi = props.highlight === i;
        const pulse = hi ? 1 + 0.12 * Math.sin((frame - s) / 6) * r : 1;
        return (
          <div key={i} style={{position: 'absolute', left: x, top: '52%', width: 0, height: 0, opacity: r}}>
            <div style={{position: 'absolute', left: 0, top: 0, transform: 'translate(-50%, -50%)', width: (hi ? 40 : 28) * u * pulse, height: (hi ? 40 : 28) * u * pulse, borderRadius: '50%', background: hi ? p.accent : p.accent2, border: `${5 * u}px solid ${p.bg1}`}} />
            <div style={{position: 'absolute', bottom: 40 * u, left: 0, transform: `translateX(-50%) translateY(${(1 - r) * 20 * u}px)`, fontFamily: FONTS.serif, fontWeight: 700, fontSize: (hi ? 64 : 52) * u, color: hi ? p.accent : p.text, whiteSpace: 'nowrap', lineHeight: 1}}>
              {e.year}
            </div>
            <div style={{position: 'absolute', top: 44 * u, left: 0, transform: `translateX(-50%) translateY(${(1 - r) * -20 * u}px)`, width: Math.min(320 * u, usable / Math.max(n, 1) - 20 * u), fontFamily: FONTS.sans, fontWeight: 600, fontSize: 30 * u, color: hi ? p.text : p.muted, textAlign: 'center', lineHeight: 1.25}}>
              {e.label}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

