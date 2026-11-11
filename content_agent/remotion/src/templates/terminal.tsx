/**
 * A dark terminal / code-editor window (generic: three window dots, a title, a monospace font with
 * Cyrillic): commands and code type in, output lines appear (line i on cue i), an error line turns red,
 * the highlighted line gets a box and an optional `explain` bubble pops in next to it.
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise} from '../anim';
import {EMOJI_FONT, MONO_FONT, PREROLL, Sfx, pop, shake, uiZone, useFontsFor} from '../motion';
import {WindowDots, wrapStarts} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, chatFamily, clamp, contrast, lum, mix, skin} from './chat';

type Kind = 'cmd' | 'code' | 'out' | 'error' | 'ok';
type Line = {text: string; kind: Kind};
const KINDS: Kind[] = ['cmd', 'code', 'out', 'error', 'ok'];
const PREFIX: Record<Kind, string> = {cmd: '$ ', code: '', out: '', error: '', ok: '✓ '};
const LH = 1.5;

/** Lighten a colour until it reads on the dark window (palette accents can be dark, e.g. clean's blue). */
const readable = (col: string, bg: string, min = 4.2) => {
  let c = col;
  for (let i = 0; i < 6 && contrast(c, bg) < min; i++) c = mix(c, '#ffffff', 0.28);
  return c;
};

// ------------------------------------------------------------------ timing
export const terminalTiming = (duration: number, speech: number, cues: (number | null)[], lines: Line[], hl: number | null) => {
  const d = Math.max(duration, 30);
  const end = d * (hl === null ? 0.8 : 0.66); // room for the box and the explanation
  const cueAt = (i: number) => (typeof cues[i] === 'number' ? clamp((cues[i] as number) - 4, 0, d * 0.9) : null);
  const typed = (l: Line) => l.kind === 'cmd' || l.kind === 'code';
  const start0 = clamp(speech - 6, 2, d * 0.1);
  const gaps: number[] = lines.map((l, i) => (i === 0 ? 0 : typed(lines[i - 1]) && !typed(l) ? 9 : typed(l) ? 6 : 4));
  const durs = lines.map((l) => (typed(l) ? clamp(Array.from(PREFIX[l.kind] + l.text).length / (l.kind === 'cmd' ? 1.25 : 2.1), 6, 70) : 0));
  const total = gaps.reduce((a, b) => a + b, 0) + durs.reduce((a, b) => a + b, 0);
  const f = Math.min(1, Math.max(end - start0, 12) / Math.max(total, 1));
  const starts: number[] = [];
  const ends: number[] = [];
  let t = start0;
  lines.forEach((_, i) => {
    t += gaps[i] * f;
    const c = cueAt(i);
    if (c !== null) t = Math.max(c, i ? ends[i - 1] + 2 : 0);
    starts.push(t);
    t += durs[i] * f;
    ends.push(t);
  });
  const hlAt = hl === null ? null : Math.min(ends[hl] + 8, Math.max(d - 30, ends[hl] + 2));
  return {appear: -PREROLL, starts, ends, hlAt, explainAt: hlAt === null ? null : hlAt + 10};
};

// ------------------------------------------------------------------ code colours (a tiny generic highlighter)
const KEYWORDS = new Set(
  ('def return import from as for in if elif else while try except finally with class lambda pass break continue ' +
    'and or not is None True False print const let var function async await new this null undefined true false ' +
    'export default switch case public static void int float str bool echo cd ls pip npm git python node').split(' '),
);
type Tok = {t: string; c: 'kw' | 'str' | 'num' | 'com' | 'fn' | 'txt'};
const tokens = (s: string): Tok[] => {
  const out: Tok[] = [];
  const re = /(#.*$|\/\/.*$)|("(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?|`[^`]*`?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_Ѐ-ӿ][\wЀ-ӿ]*)(?=\s*\()|([A-Za-z_][\w]*)/gm;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({t: s.slice(last, m.index), c: 'txt'});
    if (m[1]) out.push({t: m[1], c: 'com'});
    else if (m[2]) out.push({t: m[2], c: 'str'});
    else if (m[3]) out.push({t: m[3], c: 'num'});
    else if (m[4]) out.push({t: m[4], c: KEYWORDS.has(m[4]) ? 'kw' : 'fn'});
    else out.push({t: m[5], c: KEYWORDS.has(m[5]) ? 'kw' : 'txt'});
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push({t: s.slice(last), c: 'txt'});
  return out;
};

/** The first n characters of the tokens (what has been typed so far). */
const takeTok = (toks: Tok[], n: number) => {
  const out: Tok[] = [];
  let left = n;
  for (const k of toks) {
    if (left <= 0) break;
    const cs = Array.from(k.t);
    out.push({t: cs.slice(0, left).join(''), c: k.c});
    left -= cs.length;
  }
  return out;
};

// ------------------------------------------------------------------ the scene
export const Terminal: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const lines: Line[] = (Array.isArray(props.lines) ? props.lines : []).map((l: any) => ({
    text: String(l && typeof l === 'object' ? l.text ?? '' : l ?? ''),
    kind: (KINDS.includes(l?.kind) ? l.kind : 'out') as Kind,
  }));
  const title = props.title ? String(props.title) : '';
  const explain = props.explain ? String(props.explain) : '';
  const firstError = lines.findIndex((l) => l.kind === 'error');
  const hl: number | null =
    Number.isInteger(props.highlight_line) && props.highlight_line >= 0 && props.highlight_line < lines.length
      ? props.highlight_line
      : firstError >= 0
        ? firstError
        : null;
  const numbers = typeof props.line_numbers === 'boolean' ? props.line_numbers : lines.some((l) => l.kind === 'code');
  // a fresh prompt after the last command, unless the explanation hangs under that last line
  const idlePrompt = lines.length > 0 && lines[lines.length - 1].kind !== 'code' && !(explain && hl === lines.length - 1);
  const body = chatFamily(st.fonts.body, [title, explain].join(' '));
  const allMono = lines.map((l) => PREFIX[l.kind] + l.text).join(' ') + ' 0123456789';
  const ready = useFontsFor(['400 40px "JetBrains Mono"', '700 40px "JetBrains Mono"', `800 40px ${body}`, `400 40px ${EMOJI_FONT}`], allMono + explain + title + '💡');

  // colours: always a dark window, accents from the palette made readable on it
  const bg = lum(p.bg1) < 0.2 ? mix('#0d1016', p.bg1, 0.35) : '#12151b';
  const bar = mix(bg, '#ffffff', 0.07);
  const fg = '#e6ebf2';
  const dim = '#8a94a3';
  const red = '#ff6b6b';
  const green = '#62d68f';
  const promptCol = readable(p.accent2, bg);
  const col = {
    kw: readable(p.accent2, bg),
    str: '#a8dc7c',
    num: '#f2a65a',
    com: '#7d8796',
    fn: readable(p.accent, bg),
    txt: fg,
  };
  const sk = skin(st, p, true, u);

  // ---- geometry
  const zone = uiZone(width, height);
  const zoneH = zone.bottom - zone.top;
  const winW = vertical ? width - 130 * u : width * 0.64;
  const padX = 30 * u;
  const barH = 64 * u;
  const maxChars = Math.max(...lines.map((l) => Array.from(PREFIX[l.kind] + l.text).length), 16);
  const digits = String(lines.length).length;
  const fit = useMemo(() => {
    const layout = (fs: number) => {
      const gutter = numbers ? (digits + 1.2) * 0.6 * fs + 14 * u : 0;
      const textW = winW - 2 * padX - gutter;
      const rows = lines.map((l) => wrapStarts(PREFIX[l.kind] + l.text, 400, fs, MONO_FONT, textW).length);
      const idle = idlePrompt ? 1 : 0; // a fresh prompt at the end
      const h = barH + 28 * u + (rows.reduce((a, b) => a + b, 0) + idle) * fs * LH + 28 * u;
      return {fs, gutter, textW, rows, h};
    };
    const top = vertical ? 40 : 34;
    let fs = clamp((winW - 2 * padX - (numbers ? 70 * u : 0)) / (0.6 * maxChars), 24 * u, top * u);
    let l = layout(fs);
    while (fs > 18 * u && l.h > zoneH * (explain ? 0.7 : 0.92)) l = layout((fs -= 1 * u));
    return l;
  }, [ready, lines.map((x) => x.kind + x.text).join('\n'), winW, numbers, explain]);
  const {fs, gutter, textW, rows} = fit;
  const lh = fs * LH;
  const winH = Math.max(fit.h, zoneH * 0.4);
  const rowTop = (i: number) => barH + 28 * u + rows.slice(0, i).reduce((a, b) => a + b, 0) * lh;

  // the explanation bubble: below the line, or above it when there is no room
  const exFs = (vertical ? 33 : 30) * u;
  const exW = Math.min(winW * 0.9, 860 * u);
  const exPad = 22 * u;
  const exLines = explain ? wrapStarts(explain, 700, exFs, body, exW - 2 * exPad - exFs * 1.5).length : 0;
  const exH = explain ? exLines * exFs * 1.3 + 2 * exPad : 0;
  const hlBottom = hl === null ? 0 : rowTop(hl) + rows[hl] * lh;
  const below = explain && hl !== null ? Math.max(hlBottom + 26 * u + exH - winH, 0) : 0;
  const blockH = winH + below;
  const winTop = zone.top + Math.max((zoneH - blockH) / 2, 0);
  const exAbove = explain && hl !== null && winTop + hlBottom + 26 * u + exH > zone.bottom;
  const winLeft = (width - winW) / 2;

  const t = terminalTiming(duration, speech, cues, lines, hl);
  const appear = rise(frame, fps, t.appear, 16);
  const errAt = hl !== null && lines[hl].kind === 'error' ? t.starts[hl] : null;
  const jolt = errAt === null ? 0 : shake(frame, errAt, 9 * u, 14);
  const hlK = t.hlAt === null ? 0 : rise(frame, fps, t.hlAt, 14);
  const exK = t.explainAt === null ? 0 : pop(frame, fps, t.explainAt);
  const push = t.hlAt === null ? 0 : progress(frame, t.hlAt - 4, t.hlAt + 20);
  const focusY = winTop + (hl === null ? winH / 2 : rowTop(hl) + (rows[hl] * lh) / 2);
  const lastEnd = t.ends.length ? t.ends[t.ends.length - 1] : 0;

  const mono: React.CSSProperties = {fontFamily: MONO_FONT, fontSize: fs, lineHeight: LH, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'};
  const caret = (on: boolean) => (
    <span
      style={{
        display: 'inline-block',
        width: fs * 0.58,
        height: fs * 1.12,
        marginRight: -fs * 0.58,
        verticalAlign: '-0.22em',
        background: fg,
        opacity: on ? 0.85 : 0,
      }}
    />
  );
  const blink = Math.floor(frame / 9) % 2 === 0;

  return (
    <AbsoluteFill style={{transformOrigin: `${width / 2}px ${focusY}px`, transform: `scale(${1 + 0.035 * push})`}}>
      <div
        style={{
          position: 'absolute',
          left: winLeft,
          top: winTop,
          width: winW,
          height: winH,
          opacity: Math.min(appear * 1.5, 1),
          transform: `translate(${jolt}px, ${(1 - appear) * 70 * u}px) scale(${0.95 + 0.05 * Math.min(appear, 1)})`,
        }}
      >
        <div
          style={{
            ...sk.win,
            position: 'absolute',
            inset: 0,
            borderRadius: Math.max(st.radius, 4) * 1.3 * u,
            background: bg,
            overflow: 'hidden',
          }}
        >
          {/* title bar */}
          <div
            style={{
              height: barH,
              background: bar,
              display: 'flex',
              alignItems: 'center',
              padding: `0 ${24 * u}px`,
              borderBottom: `${2 * u}px solid ${mix(bar, '#000000', 0.3)}`,
              position: 'relative',
            }}
          >
            <WindowDots size={20 * u} gap={11 * u} />
            <div
              style={{
                position: 'absolute',
                left: 140 * u,
                right: 140 * u,
                textAlign: 'center',
                fontFamily: body,
                fontWeight: 800,
                fontSize: 26 * u,
                color: dim,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {title || (lines.some((l) => l.kind === 'code') ? 'main.py' : 'terminal')}
            </div>
          </div>

          {/* the lines */}
          {lines.map((l, i) => {
            const start = t.starts[i];
            if (frame < start) return null;
            const typed = l.kind === 'cmd' || l.kind === 'code';
            const full = PREFIX[l.kind] + l.text;
            const n = typed ? Math.round(Array.from(full).length * clamp((frame - start) / Math.max(t.ends[i] - start, 1), 0, 1)) : Array.from(full).length;
            const k = typed ? 1 : rise(frame, fps, start, 16);
            const isTyping = typed && frame < t.ends[i];
            const isLastTyped = typed && i === lines.length - 1;
            const flash = l.kind === 'error' ? interpolate(frame - start, [0, 4, 24], [0, 0.32, 0.12], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 0;
            const color = l.kind === 'error' ? red : l.kind === 'ok' ? green : l.kind === 'out' ? dim : fg;
            let content: React.ReactNode;
            if (l.kind === 'code') {
              content = takeTok(tokens(l.text), n).map((tk, j) => (
                <span key={j} style={{color: col[tk.c], fontStyle: tk.c === 'com' ? 'italic' : undefined}}>
                  {tk.t}
                </span>
              ));
            } else if (l.kind === 'cmd') {
              const cs = Array.from(full).slice(0, n);
              content = (
                <>
                  <span style={{color: promptCol, fontWeight: 700}}>{cs.slice(0, 2).join('')}</span>
                  <span style={{color: fg}}>{cs.slice(2).join('')}</span>
                </>
              );
            } else {
              content = <span style={{color, fontWeight: l.kind === 'error' ? 700 : 400}}>{full}</span>;
            }
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: 0,
                  top: rowTop(i),
                  width: winW,
                  minHeight: rows[i] * lh,
                  display: 'flex',
                  background: flash ? alpha(red, flash) : undefined,
                  opacity: Math.min(k * 1.4, 1),
                  transform: `translateY(${(1 - Math.min(k, 1)) * 14 * u}px)`,
                }}
              >
                {numbers ? (
                  <div style={{...mono, width: gutter, paddingLeft: padX, boxSizing: 'content-box', color: alpha(dim, 0.7), textAlign: 'left', flexShrink: 0}}>
                    {i + 1}
                  </div>
                ) : null}
                <div style={{...mono, width: textW, paddingLeft: numbers ? 0 : padX}}>
                  {content}
                  {isTyping || (isLastTyped && l.kind === 'code' && frame >= t.ends[i]) ? caret(isTyping || blink) : null}
                </div>
              </div>
            );
          })}

          {/* a fresh prompt once the last command has run */}
          {idlePrompt && frame >= lastEnd + 6 ? (
            <div style={{position: 'absolute', left: padX + (numbers ? gutter : 0), top: rowTop(lines.length), ...mono}}>
              <span style={{color: promptCol, fontWeight: 700}}>{'$ '}</span>
              {caret(blink)}
            </div>
          ) : null}

          {/* the highlight box */}
          {hl !== null && t.hlAt !== null && frame >= t.hlAt ? (
            <div
              style={{
                position: 'absolute',
                left: padX * 0.45,
                top: rowTop(hl) - 6 * u,
                width: winW - padX * 0.9,
                height: rows[hl] * lh + 12 * u,
                borderRadius: 10 * u,
                border: `${4 * u}px solid ${lines[hl].kind === 'error' ? red : readable(p.accent, bg)}`,
                boxShadow: `0 0 ${22 * u}px ${alpha(lines[hl].kind === 'error' ? red : p.accent, 0.55)}, inset 0 0 ${16 * u}px ${alpha(
                  lines[hl].kind === 'error' ? red : p.accent,
                  0.25,
                )}`,
                boxSizing: 'border-box',
                opacity: Math.min(hlK * 1.5, 1),
                transform: `scale(${1.08 - 0.08 * Math.min(hlK, 1)})`,
              }}
            />
          ) : null}
        </div>

        {/* the explanation, pointing at the line */}
        {explain && hl !== null && t.explainAt !== null && frame >= t.explainAt ? (
          <div
            style={{
              position: 'absolute',
              left: (winW - exW) / 2,
              top: exAbove ? rowTop(hl) - 26 * u - exH : hlBottom + 26 * u,
              width: exW,
              boxSizing: 'border-box',
              padding: exPad,
              display: 'flex',
              gap: 14 * u,
              alignItems: 'flex-start',
              borderRadius: st.radius === 0 ? 0 : 20 * u,
              background: mix('#ffffff', p.accent, 0.1),
              color: '#16181d',
              boxShadow: st.label === 'bubble' ? `${7 * u}px ${7 * u}px 0 #111` : `0 ${16 * u}px ${40 * u}px rgba(0,0,0,0.45)`,
              border: st.label === 'bubble' ? `${4 * u}px solid #111` : `${3 * u}px solid ${p.accent}`,
              opacity: Math.min(exK * 2, 1),
              transform: `scale(${exK})`,
              transformOrigin: `${90 * u}px ${exAbove ? '100%' : '0%'}`,
            }}
          >
            <div
              style={{
                position: 'absolute',
                left: 70 * u,
                [exAbove ? 'bottom' : 'top']: -16 * u,
                width: 30 * u,
                height: 30 * u,
                background: mix('#ffffff', p.accent, 0.1),
                transform: 'rotate(45deg)',
                borderLeft: exAbove ? undefined : `${3 * u}px solid ${st.label === 'bubble' ? '#111' : p.accent}`,
                borderTop: exAbove ? undefined : `${3 * u}px solid ${st.label === 'bubble' ? '#111' : p.accent}`,
                borderRight: exAbove ? `${3 * u}px solid ${st.label === 'bubble' ? '#111' : p.accent}` : undefined,
                borderBottom: exAbove ? `${3 * u}px solid ${st.label === 'bubble' ? '#111' : p.accent}` : undefined,
              }}
            />
            <div style={{fontFamily: EMOJI_FONT, fontSize: exFs * 1.15, lineHeight: 1.1, flexShrink: 0}}>💡</div>
            <div style={{fontFamily: body, fontWeight: 700, fontSize: exFs, lineHeight: 1.3, position: 'relative'}}>{explain}</div>
          </div>
        ) : null}
      </div>
      {lines.map((l, i) =>
        l.kind === 'cmd' || l.kind === 'code' ? <Sfx key={i} name="keys" at={t.starts[i]} dur={t.ends[i] - t.starts[i]} /> : null,
      )}
      {t.explainAt !== null && explain ? <Sfx name="pop" at={t.explainAt} /> : null}
    </AbsoluteFill>
  );
};
