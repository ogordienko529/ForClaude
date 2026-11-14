/**
 * Scenes that explain how AI works, drawn instead of told (9:16 first):
 * - connect: a hub (the AI) and the services it plugs into, one cable per narration cue (MCP, connectors);
 * - loop: steps on a ring with a light running round it, failing checks and a final ✅ (an agent's loop);
 * - tokens: a word or a sentence that falls apart into coloured chips (how a model reads text);
 * - context: a chat that keeps growing while a frame marks what still fits in the model's working memory;
 * - webpage: a page with white-on-white text that a select-all reveals and an agent's scan reads.
 * Each event lands on its cue (cue i = the i-th phrase in the beat's `cues`) with its own sound.
 */
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise} from '../anim';
import {LOGOS} from '../logos';
import {EMOJI_FONT, PREROLL, Sfx, pop, shake, uiZone, useFontsFor} from '../motion';
import {Ripple, textWidth, WindowDots} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, chatFamily, clamp, lum, mix} from './chat';

const RED = '#ef3b4f';
const GREEN = '#2fbf71';
const CLAMP = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** Frame of event i: its narration cue (a little early, so the picture leads the word), else the fallback. */
export const cueAt = (cues: (number | null)[], i: number, fallback: number) =>
  typeof cues[i] === 'number' ? Math.max((cues[i] as number) - 4, 0) : fallback;

const useScene = () => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const zone = uiZone(width, height);
  const dark = lum(p.bg1) < 0.4;
  return {frame, width, height, fps, p, st, u, zone, dark};
};

const Emoji: React.FC<{e: string; size: number; style?: React.CSSProperties}> = ({e, size, style}) => (
  <span style={{fontFamily: EMOJI_FONT, fontSize: size, lineHeight: 1, ...style}}>{e}</span>
);

const LogoMark: React.FC<{name: string; size: number; color?: string}> = ({name, size, color}) => {
  const logo = LOGOS[name];
  if (!logo) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24">
      <path d={logo.path} fill={color || logo.color} />
    </svg>
  );
};

// ------------------------------------------------------------------ connect
type Node = {label: string; icon?: string};

export const Connect: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone, dark} = useScene();
  const nodes: Node[] = (props.nodes || []).slice(0, 6).map((n: any) => (typeof n === 'string' ? {label: n} : n));
  const n = Math.max(nodes.length, 1);
  const unplugged = !!props.unplugged;
  const center = props.center || {};
  const title = props.title ? String(props.title) : '';
  const all = [title, center.label || '', ...nodes.map((x) => x.label)].join(' ');
  const family = chatFamily(st.fonts.body, all);
  useFontsFor([`800 40px ${family}`, `800 80px ${st.fonts.display}`, `400 40px ${EMOJI_FONT}`], all + nodes.map((x) => x.icon || '').join(''));

  const titleH = title ? 120 * u : 0;
  const cx = width / 2;
  const cy = (zone.top + titleH + zone.bottom) / 2;
  const rx = width * 0.3;
  const ry = (zone.bottom - zone.top - titleH) * 0.4;
  const R = 140 * u; // the hub
  const nfs = 48 * u; // node label size
  const fast = !!props.fast;
  const start = fast ? 3 : Math.max(Math.min(speech, 12), 0);
  const gap = fast ? 7 : clamp(((duration - start) * 0.62) / n, 7, 26);
  const at = nodes.map((_, i) => cueAt(cues, i, start + i * gap));
  const widths = nodes.map((node) => textWidth(node.label, 800, nfs, family) + (node.icon ? 80 * u : 0) + 72 * u);
  const maxW = Math.max(...widths, 0);
  // four go to the corners, spread so the two in a row keep a gap; other counts start at the top
  const corners = n === 4;
  const rxN = corners ? clamp(maxW / 2 + 18 * u, rx, width / 2 - maxW / 2 - 14 * u) : rx;
  const pos = nodes.map((_, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n + (corners ? Math.PI / 4 : 0);
    const x = clamp(cx + rxN * Math.cos(a), widths[i] / 2 + 14 * u, width - widths[i] / 2 - 14 * u);
    return {x, y: cy + ry * Math.sin(a), a};
  });
  const live = nodes.filter((_, i) => !unplugged && frame >= at[i] + 6).length;
  const hubGlow = unplugged ? 0 : Math.min(live / n, 1);
  const hubIn = pop(frame, fps, -PREROLL);
  const wobble = unplugged ? Math.sin(frame / 5) * 3 * u : 0;
  const nodeBg = dark ? mix(p.bg2, p.text, 0.08) : '#ffffff';

  return (
    <AbsoluteFill>
      {title ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: zone.top + 10 * u, textAlign: 'center', fontFamily: st.fonts.display, fontWeight: 800,
          fontSize: 96 * u, color: p.accent, letterSpacing: '0.04em', opacity: rise(frame, fps, -PREROLL, 14),
          textShadow: dark ? `0 0 ${30 * u}px ${alpha(p.accent, 0.7)}` : undefined}}>
          {title}
        </div>
      ) : null}
      <svg width={width} height={zone.bottom + 200 * u} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}}>
        {pos.map((q, i) => {
          const dx = q.x - cx;
          const dy = q.y - cy;
          const d = Math.hypot(dx, dy) || 1;
          const x0 = cx + (dx / d) * R;
          const y0 = cy + (dy / d) * R;
          const x1 = q.x - (dx / d) * 70 * u;
          const y1 = q.y - (dy / d) * 50 * u;
          const len = Math.hypot(x1 - x0, y1 - y0);
          if (unplugged) {
            const mx = (x0 + x1) / 2;
            const my = (y0 + y1) / 2;
            const k = pop(frame, fps, at[i]);
            return (
              <g key={i} opacity={rise(frame, fps, -PREROLL + i * 2, 16)}>
                <line x1={x0} y1={y0} x2={mx - (dx / d) * 26 * u} y2={my - (dy / d) * 26 * u} stroke={p.muted} strokeWidth={5 * u} strokeDasharray={`${12 * u} ${12 * u}`} opacity={0.5} />
                <line x1={mx + (dx / d) * 26 * u} y1={my + (dy / d) * 26 * u} x2={x1} y2={y1} stroke={p.muted} strokeWidth={5 * u} strokeDasharray={`${12 * u} ${12 * u}`} opacity={0.5} />
                {frame >= at[i] ? (
                  <g transform={`translate(${mx} ${my}) scale(${k})`}>
                    <circle r={24 * u} fill={RED} />
                    <path d={`M${-9 * u} ${-9 * u} L${9 * u} ${9 * u} M${9 * u} ${-9 * u} L${-9 * u} ${9 * u}`} stroke="#fff" strokeWidth={5 * u} strokeLinecap="round" />
                  </g>
                ) : null}
              </g>
            );
          }
          const k = progress(frame, at[i], at[i] + 8);
          const on = frame >= at[i] + 8;
          const dots = on
            ? [0, 1, 2].map((j) => {
                const t = (((frame - at[i]) / 26 + j / 3) % 1 + 1) % 1;
                const back = j === 1;
                const tt = back ? 1 - t : t;
                return <circle key={j} cx={x1 + (x0 - x1) * tt} cy={y1 + (y0 - y1) * tt} r={7 * u} fill={back ? p.accent2 : p.accent}
                  style={{filter: `drop-shadow(0 0 ${8 * u}px ${back ? p.accent2 : p.accent})`}} />;
              })
            : null;
          return (
            <g key={i}>
              <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={p.muted} strokeOpacity={0.25} strokeWidth={4 * u} strokeDasharray={`${10 * u} ${12 * u}`} />
              <line x1={x1} y1={y1} x2={x1 + (x0 - x1) * k} y2={y1 + (y0 - y1) * k} stroke={p.accent} strokeWidth={7 * u} strokeLinecap="round"
                style={{filter: dark ? `drop-shadow(0 0 ${10 * u}px ${p.accent})` : undefined}} />
              {dots}
              {len > 0 && frame >= at[i] + 8 ? <Ripple frame={frame} at={at[i] + 8} x={x0} y={y0} r={60 * u} color={alpha(p.accent, 0.8)} width={5 * u} /> : null}
            </g>
          );
        })}
      </svg>
      {/* the hub */}
      <div style={{position: 'absolute', left: cx - R, top: cy - R + wobble, width: 2 * R, height: 2 * R, borderRadius: R,
        background: dark ? `radial-gradient(circle at 35% 30%, ${mix(p.bg2, p.text, 0.16)} 0%, ${p.bg1} 100%)` : '#ffffff',
        border: `${5 * u}px solid ${unplugged ? p.muted : mix(p.muted, p.accent, hubGlow)}`,
        boxShadow: `0 0 ${(20 + 50 * hubGlow) * u}px ${alpha(p.accent, 0.25 + 0.5 * hubGlow)}, 0 ${10 * u}px ${30 * u}px rgba(0,0,0,0.3)`,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', transform: `scale(${hubIn})`}}>
        {center.logo && LOGOS[center.logo] ? <LogoMark name={center.logo} size={R * 1.05} /> : (
          <div style={{fontFamily: st.fonts.display, fontWeight: 800, fontSize: 64 * u, color: p.text}}>{center.label || 'ШІ'}</div>
        )}
        {unplugged ? (
          <div style={{position: 'absolute', top: -34 * u, right: -14 * u, opacity: Math.min(pop(frame, fps, at[0] ?? 10) * 2, 1)}}>
            <Emoji e="🤷" size={70 * u} />
          </div>
        ) : null}
      </div>
      {center.logo && center.label ? (
        <div style={{position: 'absolute', left: cx - 200 * u, width: 400 * u, top: cy + R + 14 * u, textAlign: 'center', fontFamily: family, fontWeight: 800,
          fontSize: 34 * u, color: p.text, opacity: hubIn}}>
          {center.label}
        </div>
      ) : null}
      {/* the services */}
      {nodes.map((node, i) => {
        const q = pos[i];
        const on = !unplugged && frame >= at[i] + 6;
        const bump = on ? spring({frame: frame - at[i] - 6, fps, config: {damping: 8, stiffness: 260, mass: 0.5}}) : 0;
        const inK = rise(frame, fps, -PREROLL + i * 2, 16);
        const scale = (0.7 + 0.3 * inK) * (1 + 0.14 * Math.sin(Math.min(bump, 1) * Math.PI));
        return (
          <div key={i} style={{position: 'absolute', left: q.x, top: q.y, transform: `translate(-50%, -50%) scale(${scale})`, opacity: Math.min(inK * 1.4, 1),
            display: 'flex', alignItems: 'center', gap: 16 * u, padding: `${22 * u}px ${32 * u}px`, borderRadius: Math.max(st.radius, 8) * 1.4 * u,
            background: on ? (dark ? mix(nodeBg, p.accent, 0.16) : mix('#ffffff', p.accent, 0.08)) : nodeBg,
            border: `${4 * u}px solid ${on ? p.accent : alpha(p.muted, 0.5)}`, whiteSpace: 'nowrap',
            boxShadow: on ? `0 0 ${30 * u}px ${alpha(p.accent, 0.55)}` : `0 ${8 * u}px ${20 * u}px rgba(0,0,0,0.25)`,
            filter: unplugged ? 'grayscale(0.7)' : undefined}}>
            {node.icon ? <Emoji e={node.icon} size={62 * u} /> : null}
            <span style={{fontFamily: family, fontWeight: 800, fontSize: nfs, color: on ? p.text : alpha(p.text, unplugged ? 0.55 : 0.85)}}>{node.label}</span>
            {!unplugged ? <Sfx name="click" at={at[i] + 6} gain={1.2} /> : <Sfx name="pop" at={at[i]} gain={0.8} />}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ loop
type Step = {label: string; icon?: string};

export const Loop: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone, dark} = useScene();
  const steps: Step[] = (props.steps || []).slice(0, 5).map((x: any) => (typeof x === 'string' ? {label: x} : x));
  const m = Math.max(steps.length, 1);
  const rounds = clamp(Math.round(Number(props.rounds) || 1), 1, 4);
  const center = String(props.center || '');
  const done = props.done ? String(props.done) : '';
  const all = [center, done, ...steps.map((x) => x.label)].join(' ');
  const family = chatFamily(st.fonts.body, all);
  useFontsFor([`800 40px ${family}`, `400 40px ${EMOJI_FONT}`], all + steps.map((x) => x.icon || '').join('') + '✅❌');

  const cx = width / 2;
  const cy = (zone.top + zone.bottom) / 2 + 10 * u;
  const r = Math.min(width * 0.31, (zone.bottom - zone.top) * 0.36);
  const angle = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / m;
  // when the light passes step i in round k
  const t0 = Math.max(Math.min(speech, 10), 0);
  const t1 = Math.max(duration - (done ? 26 : 10), t0 + 20);
  const hits: number[][] = [];
  for (let k = 0; k < rounds; k++) {
    hits.push(steps.map((_, i) => {
      const uniform = t0 + ((t1 - t0) * (k + i / m)) / rounds;
      return rounds === 1 ? cueAt(cues, i, uniform) : uniform;
    }));
  }
  const last = hits[rounds - 1][m - 1];
  // the light's angle: through the hit frames, then on to the top of the ring
  const keys = hits.flat();
  const angs = hits.flatMap((row, k) => row.map((_, i) => angle(i) + 2 * Math.PI * k));
  const endAt = last + 14;
  const theta = frame <= keys[0]
    ? interpolate(frame, [keys[0] - 14, keys[0]], [angs[0] - 0.6, angs[0]], CLAMP)
    : frame >= last
      ? interpolate(frame, [last, endAt], [angs[angs.length - 1], angle(0) + 2 * Math.PI * rounds], CLAMP)
      : interpolate(frame, keys, angs, CLAMP);
  const ox = cx + r * Math.cos(theta);
  const oy = cy + r * Math.sin(theta);
  const finished = frame >= last + 4;
  const roundNow = Math.min(rounds, Math.max(1, hits.filter((row) => frame >= row[0]).length));
  const fin = pop(frame, fps, last + 4);
  const trail = 0.9; // radians of glowing trail behind the light
  const arc = (a0: number, a1: number) => {
    const s = {x: cx + r * Math.cos(a0), y: cy + r * Math.sin(a0)};
    const e = {x: cx + r * Math.cos(a1), y: cy + r * Math.sin(a1)};
    return `M ${s.x} ${s.y} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${e.x} ${e.y}`;
  };
  const cardBg = dark ? mix(p.bg2, p.text, 0.08) : '#ffffff';

  return (
    <AbsoluteFill>
      <svg width={width} height={zone.bottom + 100 * u} style={{position: 'absolute', left: 0, top: 0}}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={alpha(p.muted, 0.35)} strokeWidth={8 * u} opacity={rise(frame, fps, -PREROLL, 16)} />
        {steps.map((_, i) => {
          const a = (angle(i) + angle(i + 1)) / 2;
          const x = cx + r * Math.cos(a);
          const y = cy + r * Math.sin(a);
          const deg = (a * 180) / Math.PI + 90;
          return <path key={i} d={`M ${-12 * u} ${-12 * u} L ${12 * u} 0 L ${-12 * u} ${12 * u}`} fill="none" stroke={alpha(p.muted, 0.7)} strokeWidth={5 * u}
            strokeLinecap="round" strokeLinejoin="round" transform={`translate(${x} ${y}) rotate(${deg})`} />;
        })}
        {frame > keys[0] - 14 ? <path d={arc(theta - trail, theta)} fill="none" stroke={finished ? GREEN : p.accent} strokeWidth={10 * u} strokeLinecap="round"
          opacity={0.85} style={{filter: dark ? `drop-shadow(0 0 ${10 * u}px ${finished ? GREEN : p.accent})` : undefined}} /> : null}
        {frame > keys[0] - 14 ? <circle cx={ox} cy={oy} r={20 * u} fill={finished ? GREEN : p.accent}
          style={{filter: `drop-shadow(0 0 ${16 * u}px ${finished ? GREEN : p.accent})`}} /> : null}
      </svg>
      {/* the centre: what loops, the round counter, the result */}
      <div style={{position: 'absolute', left: cx - r * 0.7, width: r * 1.4, top: cy - 90 * u, height: 180 * u, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 8 * u, textAlign: 'center'}}>
        {finished && done ? (
          <div style={{transform: `scale(${fin})`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 * u}}>
            <Emoji e="✅" size={96 * u} />
            <div style={{fontFamily: family, fontWeight: 800, fontSize: 44 * u, color: GREEN}}>{done}</div>
          </div>
        ) : (
          <>
            {center ? <div style={{fontFamily: st.fonts.display, fontWeight: 800, fontSize: 56 * u, color: p.text, lineHeight: 1.05}}>{center}</div> : null}
            {rounds > 1 ? (
              <div style={{fontFamily: family, fontWeight: 800, fontSize: 34 * u, color: p.accent, letterSpacing: '0.08em', textTransform: 'uppercase'}}>
                коло {roundNow}
              </div>
            ) : null}
          </>
        )}
      </div>
      {steps.map((s, i) => {
        const a = angle(i);
        const x = cx + r * Math.cos(a);
        const y = cy + r * Math.sin(a);
        const passed = hits.map((row) => row[i]).filter((h) => frame >= h);
        const lastHit = passed.length ? passed[passed.length - 1] : null;
        const k = lastHit === null ? 0 : spring({frame: frame - lastHit, fps, config: {damping: 9, stiffness: 240, mass: 0.5}});
        const lit = lastHit !== null;
        const isCheck = i === m - 1 && rounds > 1;
        const failed = isCheck && lastHit !== null && passed.length < rounds;
        const ok = isCheck && passed.length === rounds;
        const edge = failed ? RED : ok ? GREEN : lit ? p.accent : alpha(p.muted, 0.5);
        const inK = rise(frame, fps, -PREROLL + i * 2, 16);
        return (
          <React.Fragment key={i}>
            <div style={{position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) scale(${(0.75 + 0.25 * inK) * (1 + 0.16 * Math.sin(Math.min(k, 1) * Math.PI))})`,
              opacity: Math.min(inK * 1.4, 1), display: 'flex', alignItems: 'center', gap: 12 * u, padding: `${16 * u}px ${24 * u}px`, whiteSpace: 'nowrap',
              borderRadius: Math.max(st.radius, 8) * 1.4 * u, background: lit ? mix(cardBg, edge, dark ? 0.18 : 0.1) : cardBg,
              border: `${4 * u}px solid ${edge}`, boxShadow: lit ? `0 0 ${28 * u}px ${alpha(edge, 0.5)}` : `0 ${8 * u}px ${20 * u}px rgba(0,0,0,0.25)`}}>
              {s.icon ? <Emoji e={s.icon} size={44 * u} /> : null}
              <span style={{fontFamily: family, fontWeight: 800, fontSize: 38 * u, color: p.text}}>{s.label}</span>
              {failed ? <Emoji e="❌" size={40 * u} style={{transform: `scale(${Math.min(k, 1.2)})`}} /> : null}
              {ok ? <Emoji e="✅" size={40 * u} style={{transform: `scale(${Math.min(k, 1.2)})`}} /> : null}
            </div>
            {hits.map((row, kk) => {
              const h = row[i];
              const bad = isCheck && kk < rounds - 1;
              const good = isCheck && kk === rounds - 1;
              return <Sfx key={kk} name={bad ? 'buzz' : good ? 'ding' : 'click'} at={h} gain={bad ? 0.9 : 1.1} />;
            })}
          </React.Fragment>
        );
      })}
      {done ? <Sfx name="pop" at={last + 4} /> : null}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ tokens
type Row = {text: string; pieces: string[]; label?: string};
// light chip colours that keep dark text readable on any background
const TOKEN_COLORS = ['#ffb4a2', '#b9f18c', '#a9c8ff', '#ffd98a', '#d7b8f5', '#9ff0e6', '#ffc2e2'];

export const Tokens: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone} = useScene();
  const rows: Row[] = (props.rows || []).slice(0, 3).map((r: any) => ({
    text: String(r.text ?? (r.pieces || []).join('')),
    pieces: (r.pieces || [String(r.text ?? '')]).map(String),
    label: r.label ? String(r.label) : '',
  }));
  const count = props.count !== false;
  const note = props.note ? String(props.note) : '';
  const all = rows.map((r) => r.text + ' ' + r.label).join(' ') + ' ' + note + ' токенів 0123456789';
  const family = chatFamily(st.fonts.display, all);
  const ready = useFontsFor([`800 80px ${family}`, `700 40px ${family}`], all);

  const fast = !!props.fast;
  const n = Math.max(rows.length, 1);
  const start = fast ? 6 : Math.max(Math.min(speech + 6, 30), 6);
  const gap = clamp(((duration - start) * 0.6) / n, 10, 40);
  const at = rows.map((_, i) => cueAt(cues, i, start + i * gap));
  const maxW = width * 0.82;
  const sizes = rows.map((r) => {
    if (!ready) return 90 * u;
    const w = textWidth(r.text, 800, 100, family) + r.pieces.length * 46; // chips' padding and gaps at size 100
    return Math.min((n === 1 ? 150 : 110) * u, (100 * maxW) / Math.max(w, 1));
  });
  const rowH = rows.map((_, i) => sizes[i] * 1.5 + (rows[i].label ? 74 * u : 0) + (count ? 70 * u : 0));
  const total = rowH.reduce((a, b) => a + b, 0) + (n - 1) * 46 * u + (note ? 90 * u : 0);
  let y = (zone.top + zone.bottom) / 2 - total / 2;

  return (
    <AbsoluteFill>
      {rows.map((r, i) => {
        const top = y;
        y += rowH[i] + 46 * u;
        const fs = sizes[i];
        const k = spring({frame: frame - at[i], fps, config: {damping: 12, stiffness: 170, mass: 0.6}});
        const split = frame >= at[i] ? Math.min(k, 1.15) : 0;
        const inK = rise(frame, fps, -PREROLL + i * 4, 16);
        const shown = frame >= at[i] ? Math.min(r.pieces.length, Math.floor((frame - at[i]) / 2) + 1) : 0;
        return (
          <div key={i} style={{position: 'absolute', left: 0, right: 0, top, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 * u,
            opacity: Math.min(inK * 1.5, 1), transform: `translateY(${(1 - Math.min(inK, 1)) * 40 * u}px)`}}>
            {r.label ? <div style={{fontFamily: family, fontWeight: 800, fontSize: 54 * u, color: p.text}}>{r.label}</div> : null}
            <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18 * u * split, flexWrap: 'nowrap'}}>
              {r.pieces.map((piece, j) => {
                const c = frame >= at[i] + j * 2 ? spring({frame: frame - at[i] - j * 2, fps, config: {damping: 9, stiffness: 260, mass: 0.5}}) : 0;
                const col = TOKEN_COLORS[(j + i * 3) % TOKEN_COLORS.length];
                const lift = Math.sin(Math.min(c, 1) * Math.PI) * -26 * u;
                return (
                  <div key={j} style={{position: 'relative', fontFamily: family, fontWeight: 800, fontSize: fs, lineHeight: 1.25, whiteSpace: 'pre',
                    padding: `${4 * u * split}px ${14 * u * split}px`, borderRadius: 18 * u, color: split > 0.4 ? '#1b1b2a' : p.text,
                    background: alpha(col, Math.min(c, 1)), transform: `translateY(${lift}px) rotate(${(j % 2 ? 3 : -3) * Math.min(c, 1)}deg)`,
                    boxShadow: c > 0.2 ? `0 ${6 * u}px 0 ${alpha('#000000', 0.15)}` : undefined}}>
                    {piece.replace(/ /g, ' ')}
                    <Sfx name="click" at={at[i] + j * 2} gain={0.9} />
                  </div>
                );
              })}
            </div>
            {count ? (
              <div style={{fontFamily: family, fontWeight: 800, fontSize: 52 * u, color: p.accent, opacity: frame >= at[i] ? 1 : 0}}>
                {shown} {tokenWord(shown)}
              </div>
            ) : null}
            <Sfx name="pop" at={at[i]} gain={1.1} />
          </div>
        );
      })}
      {note ? (
        <div style={{position: 'absolute', left: width * 0.1, right: width * 0.1, top: y - 20 * u, textAlign: 'center', fontFamily: family, fontWeight: 700,
          fontSize: 40 * u, color: p.muted, opacity: rise(frame, fps, at[at.length - 1] + 10, 16)}}>
          {note}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** «1 токен», «2 токени», «5 токенів». */
export const tokenWord = (k: number) => {
  const a = k % 10;
  const b = k % 100;
  if (a === 1 && b !== 11) return 'токен';
  if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return 'токени';
  return 'токенів';
};

// ------------------------------------------------------------------ context
export const Context: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone, dark} = useScene();
  const messages: string[] = (props.messages || []).slice(0, 12).map(String);
  const n = Math.max(messages.length, 1);
  const win = clamp(Math.round(Number(props.window) || 4), 1, 8);
  const label = String(props.label || 'контекстне вікно');
  const all = messages.join(' ') + ' ' + label;
  const family = chatFamily(st.fonts.body, all);
  useFontsFor([`600 40px ${family}`, `800 40px ${family}`], all);

  const fast = !!props.fast;
  const step = fast ? 6 : clamp((Math.max(duration - 20, 30) * 0.8) / n, 6, 34);
  const at = messages.map((_, i) => cueAt(cues, i, -PREROLL + i * step));
  const h = 96 * u;
  const gap = 18 * u;
  const colW = width * 0.84;
  const left = (width - colW) / 2;
  const bottom = zone.bottom - 30 * u;
  const winTop = bottom - win * (h + gap) + gap - 26 * u;
  const winH = bottom - winTop + 26 * u;
  // how many messages are on screen, smoothly: each new one pushes the stack up by one slot
  const pushed = (i: number) => messages.reduce((acc, _, j) => (j > i && frame >= at[j]
    ? acc + Math.min(spring({frame: frame - at[j], fps, config: {damping: 14, stiffness: 180}}), 1) : acc), 0);
  const shown = messages.filter((_, i) => frame >= at[i]).length;
  const full = Math.min(shown / win, 1);
  const over = shown > win;
  const userBg = p.accent;
  const botBg = dark ? mix(p.bg2, p.text, 0.12) : '#ffffff';

  return (
    <AbsoluteFill>
      {messages.map((m, i) => {
        if (frame < at[i]) return null;
        const k = spring({frame: frame - at[i], fps, config: {damping: 12, stiffness: 220, mass: 0.6}});
        const slot = pushed(i); // 0 = the newest, at the bottom
        const yy = bottom - h - slot * (h + gap) + (1 - Math.min(k, 1)) * 60 * u;
        const outside = clamp(slot - (win - 1), 0, 1);
        const user = i % 2 === 0;
        if (yy + h < zone.top - 40 * u) return null;
        return (
          <div key={i} style={{position: 'absolute', top: yy, height: h, left: user ? left + colW * 0.18 : left, width: colW * 0.82, display: 'flex',
            justifyContent: user ? 'flex-end' : 'flex-start', opacity: Math.min(k * 1.5, 1) * (1 - 0.65 * outside) * interpolate(yy, [zone.top - 40 * u, zone.top + 80 * u], [0, 1], CLAMP),
            filter: outside > 0 ? `blur(${3 * outside * u}px) grayscale(${outside})` : undefined}}>
            <div style={{maxWidth: '100%', height: h, boxSizing: 'border-box', display: 'flex', alignItems: 'center', padding: `0 ${26 * u}px`,
              borderRadius: `${26 * u}px ${26 * u}px ${user ? 8 * u : 26 * u}px ${user ? 26 * u : 8 * u}px`, background: user ? userBg : botBg,
              color: user ? '#ffffff' : p.text, fontFamily: family, fontWeight: 600, fontSize: 37 * u, whiteSpace: 'nowrap', overflow: 'hidden',
              textOverflow: 'ellipsis', boxShadow: `0 ${6 * u}px ${16 * u}px rgba(0,0,0,${dark ? 0.35 : 0.12})`}}>
              {m}
            </div>
            <Sfx name={user ? 'click' : 'pop'} at={at[i]} gain={0.7} />
          </div>
        );
      })}
      {/* the window: what the model still holds */}
      <div style={{position: 'absolute', left: left - 26 * u, width: colW + 52 * u, top: winTop, height: winH, borderRadius: 30 * u,
        border: `${5 * u}px dashed ${over ? RED : p.accent}`, boxShadow: `0 0 ${24 * u}px ${alpha(over ? RED : p.accent, 0.3)}`,
        opacity: rise(frame, fps, -PREROLL, 16), transform: `translateX(${shake(frame, at[win] ?? 1e9, 8 * u, 14)}px)`}}>
        <div style={{position: 'absolute', left: 30 * u, top: -30 * u, padding: `${8 * u}px ${18 * u}px`, borderRadius: 14 * u, background: over ? RED : p.accent,
          color: '#ffffff', fontFamily: family, fontWeight: 800, fontSize: 28 * u, letterSpacing: '0.06em', textTransform: 'uppercase'}}>
          {label}
        </div>
        <div style={{position: 'absolute', right: 30 * u, top: -24 * u, width: 180 * u, height: 18 * u, borderRadius: 9 * u, background: alpha(p.muted, 0.3), overflow: 'hidden'}}>
          <div style={{width: `${full * 100}%`, height: '100%', background: over ? RED : p.accent}} />
        </div>
      </div>
      {over && at[win] !== undefined ? <Sfx name="buzz" at={at[win]} gain={0.6} /> : null}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ webpage
export const Webpage: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone} = useScene();
  const url = String(props.url || 'example.com');
  const title = String(props.title || '');
  const lines: string[] = (props.lines || []).slice(0, 4).map(String);
  const hidden = String(props.hidden || '');
  const badge = props.badge ? String(props.badge) : '';
  const revealed = !!props.revealed;
  const all = [url, title, hidden, badge, ...lines].join(' ');
  const family = chatFamily(st.fonts.body, all);
  useFontsFor([`600 40px ${family}`, `800 40px ${family}`, `400 40px ${EMOJI_FONT}`], all + '⚠️🤖');

  const reveal = revealed ? -PREROLL - 20 : cueAt(cues, 0, Math.max(speech, 0) + Math.max(duration - speech, 30) * 0.4);
  const scanAt = props.scan ? cueAt(cues, 1, reveal + 16) : null;
  const zoomAt = props.zoom ? (revealed ? -PREROLL : reveal + 12) : null;
  const sel = progress(frame, reveal, reveal + 10);
  const red = progress(frame, reveal + 6, reveal + 16);

  const winW = width - 110 * u;
  const winX = (width - winW) / 2;
  const winY = zone.top + 10 * u;
  const winH = zone.bottom - zone.top - 20 * u;
  const barH = 86 * u;
  const pagePad = 46 * u;
  // where the hidden line sits in the page: after the first visible line
  const fs = 34 * u;
  const lh = fs * 1.45;
  const titleH = title ? 64 * u + 30 * u : 0;
  const hiddenY = winY + barH + pagePad + titleH + (lines.length ? 2 * lh + 26 * u : 0);
  const zk = zoomAt === null ? 0 : spring({frame: frame - zoomAt, fps, config: {damping: 14, stiffness: 150}});
  const scanY = scanAt === null ? null : interpolate(frame, [scanAt, scanAt + 30], [winY + barH, winY + winH], CLAMP);
  const hit = scanAt !== null && frame >= scanAt + 30 * ((hiddenY - winY - barH) / (winH - barH));
  const bk = badge && scanAt !== null ? pop(frame, fps, scanAt + 30 * ((hiddenY - winY - barH) / (winH - barH))) : 0;

  const para = (text: string, key: string | number) => (
    <div key={key} style={{position: 'relative', fontFamily: family, fontWeight: 600, fontSize: fs, lineHeight: 1.45, color: '#3b3f46', marginBottom: 26 * u}}>
      <span style={{background: sel > 0 ? `linear-gradient(90deg, #b4d5fe ${sel * 100}%, transparent ${sel * 100}%)` : undefined}}>{text}</span>
    </div>
  );

  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: winX, top: winY, width: winW, height: winH, borderRadius: 26 * u, overflow: 'hidden', background: '#ffffff',
        boxShadow: `0 ${20 * u}px ${60 * u}px rgba(0,0,0,0.45)`, opacity: rise(frame, fps, -PREROLL, 16),
        filter: zk > 0 ? `blur(${4 * Math.min(zk, 1) * u}px) brightness(${1 - 0.35 * Math.min(zk, 1)})` : undefined}}>
        <div style={{height: barH, background: '#eceef1', display: 'flex', alignItems: 'center', gap: 22 * u, padding: `0 ${26 * u}px`, borderBottom: '1px solid #d9dce1'}}>
          <WindowDots size={18 * u} gap={12 * u} />
          <div style={{flex: 1, height: 52 * u, borderRadius: 26 * u, background: '#ffffff', display: 'flex', alignItems: 'center', padding: `0 ${24 * u}px`,
            fontFamily: family, fontWeight: 600, fontSize: 28 * u, color: '#4a4f57'}}>
            🔒&nbsp;{url}
          </div>
        </div>
        <div style={{padding: pagePad}}>
          {title ? <div style={{fontFamily: family, fontWeight: 800, fontSize: 52 * u, color: '#111318', marginBottom: 30 * u, lineHeight: 1.15}}>{title}</div> : null}
          {lines.slice(0, 2).map((l, i) => para(l, i))}
          {hidden ? (
            <div style={{position: 'relative', fontFamily: family, fontWeight: 800, fontSize: fs, lineHeight: 1.45, marginBottom: 26 * u,
              transform: `translateX(${hit ? shake(frame, scanAt! + 30 * ((hiddenY - winY - barH) / (winH - barH)), 8 * u, 16) : 0}px)`}}>
              <span style={{color: mix('#ffffff', RED, red), background: sel > 0 ? `linear-gradient(90deg, #b4d5fe ${sel * 100}%, transparent ${sel * 100}%)` : undefined,
                outline: red > 0.5 ? `${4 * u}px solid ${alpha(RED, red)}` : undefined, outlineOffset: 6 * u, borderRadius: 4 * u}}>
                {hidden}
              </span>
            </div>
          ) : null}
          {lines.slice(2).map((l, i) => para(l, i + 2))}
        </div>
        {scanY !== null && frame >= scanAt! && frame <= scanAt! + 34 ? (
          <div style={{position: 'absolute', left: 0, right: 0, top: scanY - winY, height: 6 * u, background: p.accent,
            boxShadow: `0 0 ${30 * u}px ${12 * u}px ${alpha(p.accent, 0.45)}`}} />
        ) : null}
      </div>
      {zk > 0 ? (
        <div style={{position: 'absolute', left: winX + 30 * u, width: winW - 60 * u, top: hiddenY - 60 * u, padding: `${34 * u}px ${38 * u}px`, boxSizing: 'border-box',
          borderRadius: 24 * u, background: RED, color: '#ffffff', fontFamily: family, fontWeight: 800, fontSize: 52 * u, lineHeight: 1.25,
          transform: `scale(${0.6 + 0.4 * Math.min(zk, 1.1)}) rotate(${-2 * Math.min(zk, 1)}deg) translateX(${shake(frame, (zoomAt ?? 0) + 10, 10 * u, 16)}px)`,
          opacity: Math.min(zk * 2, 1), boxShadow: `0 ${24 * u}px ${60 * u}px rgba(0,0,0,0.55)`}}>
          «{hidden}»
        </div>
      ) : null}
      {zoomAt !== null ? <Sfx name="impact" at={zoomAt} gain={0.8} /> : null}
      {badge && bk > 0 ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: winY + winH - 150 * u, display: 'flex', justifyContent: 'center'}}>
          <div style={{transform: `scale(${bk}) rotate(-3deg)`, padding: `${16 * u}px ${30 * u}px`, borderRadius: 18 * u, background: RED, color: '#ffffff',
            fontFamily: family, fontWeight: 800, fontSize: 40 * u, boxShadow: `0 ${10 * u}px ${24 * u}px rgba(0,0,0,0.4)`, display: 'flex', alignItems: 'center', gap: 14 * u}}>
            <span style={{fontFamily: EMOJI_FONT}}>🤖</span>{badge}
          </div>
        </div>
      ) : null}
      {!revealed ? <Sfx name="click" at={reveal} gain={1.2} /> : null}
      {!revealed ? <Sfx name="buzz" at={reveal + 10} gain={0.7} /> : null}
      {scanAt !== null ? <Sfx name="riser" at={scanAt + 30 * ((hiddenY - winY - barH) / (winH - barH))} gain={0.8} /> : null}
      {badge && scanAt !== null ? <Sfx name="pop" at={scanAt + 30 * ((hiddenY - winY - barH) / (winH - barH))} /> : null}
    </AbsoluteFill>
  );
};


// ------------------------------------------------------------------ flashcards
type Card = {front: string; back: string};

/**
 * A little flashcard app, the kind Claude builds in a chat (an artifact): a window with a title, a card that
 * flips from the word to its translation, a fingertip on «✅ Знаю», the score going up, the next card sliding in.
 * Card i flips on cue i (else the cards share the scene evenly).
 */
export const Flashcards: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const {frame, width, fps, p, st, u, zone, dark} = useScene();
  const cards: Card[] = (props.cards || []).slice(0, 6).map((c: any) => ({front: String(c.front ?? ''), back: String(c.back ?? '')}));
  const n = Math.max(cards.length, 1);
  const title = String(props.title || 'Тренажер слів');
  const tag = props.tag ? String(props.tag) : '';
  const all = [title, tag, ...cards.flatMap((c) => [c.front, c.back]), 'Знаю Ще раз 0123456789'].join(' ');
  const family = chatFamily(st.fonts.body, all);
  useFontsFor([`800 40px ${family}`, `600 40px ${family}`, `400 40px ${EMOJI_FONT}`], all + '✅🔁⚡👆');

  const start = Math.max(Math.min(speech, 8), 0);
  const per = Math.max((duration - start - 6) / n, 22);
  const flipAt = cards.map((_, i) => cueAt(cues, i, start + i * per + per * 0.25));
  const tapAt = flipAt.map((f, i) => Math.min(f + Math.max(per * 0.38, 10), (flipAt[i + 1] ?? duration) - 8));
  const outAt = tapAt.map((t) => t + 6);
  const cur = Math.max(0, cards.findIndex((_, i) => frame < (outAt[i] ?? 1e9) + 8));
  const known = tapAt.filter((t) => frame >= t).length;

  const winW = width - 120 * u;
  const winX = (width - winW) / 2;
  const winY = zone.top + 10 * u;
  const barH = 92 * u;
  const cardW = winW - 120 * u;
  const cardH = (zone.bottom - zone.top) * 0.42;
  const winH = barH + 70 * u + cardH + 54 * u + 104 * u + 56 * u; // fits the card and the buttons
  const cardX = winX + (winW - cardW) / 2;
  const cardY = winY + barH + 70 * u;
  const btnY = cardY + cardH + 54 * u;
  const btnW = (cardW - 30 * u) / 2;
  const btnH = 104 * u;
  const winBg = dark ? mix(p.bg2, p.text, 0.06) : '#ffffff';
  const inK = rise(frame, fps, -PREROLL, 16);

  const c = cards[cur] || {front: '', back: ''};
  const flip = progress(frame, flipAt[cur] ?? 1e9, (flipAt[cur] ?? 1e9) + 9);
  const away = progress(frame, outAt[cur] ?? 1e9, (outAt[cur] ?? 1e9) + 8);
  const enter = cur > 0 ? progress(frame, outAt[cur - 1] + 4, outAt[cur - 1] + 14) : 1;
  const faceBack = flip > 0.5;
  const tapK = tapAt[cur] !== undefined ? interpolate(frame, [tapAt[cur] - 10, tapAt[cur], tapAt[cur] + 6], [0, 1, 0.6], CLAMP) : 0;
  const pressed = tapAt[cur] !== undefined && frame >= tapAt[cur] && frame < tapAt[cur] + 6;
  const scorePop = known && tapAt[known - 1] !== undefined ? pop(frame, fps, tapAt[known - 1]) : 1;

  return (
    <AbsoluteFill>
      <div style={{position: 'absolute', left: winX, top: winY, width: winW, height: winH, borderRadius: 30 * u, background: winBg, overflow: 'hidden',
        boxShadow: `0 ${20 * u}px ${60 * u}px rgba(0,0,0,${dark ? 0.5 : 0.18})`, opacity: Math.min(inK * 1.4, 1),
        transform: `translateY(${(1 - Math.min(inK, 1)) * 60 * u}px)`}}>
        <div style={{height: barH, display: 'flex', alignItems: 'center', gap: 16 * u, padding: `0 ${30 * u}px`, borderBottom: `1px solid ${alpha(p.text, 0.1)}`}}>
          <span style={{fontFamily: EMOJI_FONT, fontSize: 40 * u}}>⚡</span>
          <span style={{fontFamily: family, fontWeight: 800, fontSize: 38 * u, color: p.text, flex: 1}}>{title}</span>
          {tag ? <span style={{fontFamily: family, fontWeight: 800, fontSize: 24 * u, color: p.accent, padding: `${6 * u}px ${14 * u}px`, borderRadius: 12 * u,
            background: alpha(p.accent, 0.14), letterSpacing: '0.06em', textTransform: 'uppercase'}}>{tag}</span> : null}
          <span style={{fontFamily: family, fontWeight: 800, fontSize: 34 * u, color: GREEN, transform: `scale(${scorePop})`, display: 'inline-block'}}>
            ✅ {known}/{n}
          </span>
        </div>
      </div>
      {/* the card: front (the word) flips to the back (the translation) */}
      <div style={{position: 'absolute', left: cardX, top: cardY, width: cardW, height: cardH, perspective: 1600 * u,
        transform: `translateX(${(-away * 1.2 + (1 - enter) * 1.2) * width}px) rotate(${-away * 8}deg)`, opacity: Math.min(inK * 1.4, 1)}}>
        <div style={{position: 'absolute', inset: 0, borderRadius: 28 * u, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18 * u,
          background: faceBack ? mix(winBg, GREEN, dark ? 0.22 : 0.12) : mix(winBg, p.accent, dark ? 0.2 : 0.1),
          border: `${5 * u}px solid ${faceBack ? GREEN : p.accent}`, transform: `rotateY(${flip * 180 - (faceBack ? 180 : 0)}deg)`,
          boxShadow: `0 ${14 * u}px ${30 * u}px rgba(0,0,0,0.18)`}}>
          <div style={{fontFamily: family, fontWeight: 800, fontSize: 30 * u, color: p.muted, letterSpacing: '0.1em', textTransform: 'uppercase'}}>
            {faceBack ? 'переклад' : 'слово'}
          </div>
          <div style={{fontFamily: st.fonts.display, fontWeight: 800, fontSize: 104 * u, color: p.text, textAlign: 'center', lineHeight: 1.05, padding: `0 ${30 * u}px`}}>
            {faceBack ? c.back : c.front}
          </div>
        </div>
      </div>
      {/* the two answer buttons */}
      {[0, 1].map((b) => {
        const good = b === 1;
        const x = cardX + b * (btnW + 30 * u);
        return (
          <div key={b} style={{position: 'absolute', left: x, top: btnY, width: btnW, height: btnH, borderRadius: 24 * u, display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: 12 * u, background: good ? (pressed ? mix(GREEN, '#000000', 0.15) : GREEN) : alpha(p.text, 0.08),
            color: good ? '#ffffff' : p.text, fontFamily: family, fontWeight: 800, fontSize: 40 * u, opacity: Math.min(inK * 1.4, 1),
            transform: `scale(${good && pressed ? 0.95 : 1})`}}>
            <span style={{fontFamily: EMOJI_FONT}}>{good ? '✅' : '🔁'}</span>{good ? 'Знаю' : 'Ще раз'}
          </div>
        );
      })}
      {/* the fingertip that taps «Знаю» */}
      {tapK > 0 ? (
        <div style={{position: 'absolute', left: cardX + btnW * 1.5 + 30 * u - 36 * u, top: btnY + btnH * 0.55 + (1 - tapK) * 140 * u, fontFamily: EMOJI_FONT,
          fontSize: 92 * u, opacity: Math.min(tapK * 2, 1), filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.35))'}}>👆</div>
      ) : null}
      {flipAt.map((f, i) => <Sfx key={`f${i}`} name="pop" at={f} gain={0.9} />)}
      {tapAt.map((t, i) => <Sfx key={`t${i}`} name="click" at={t} gain={1.2} />)}
      {tapAt.map((t, i) => <Sfx key={`d${i}`} name="ding" at={t + 2} gain={0.6} />)}
      {outAt.map((o, i) => (i < n - 1 ? <Sfx key={`w${i}`} name="whoosh" at={o} gain={0.6} /> : null))}
    </AbsoluteFill>
  );
};
