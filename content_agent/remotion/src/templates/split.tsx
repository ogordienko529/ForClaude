/**
 * "Погано / добре": two stacked panels, the weak prompt or wrong result on top and the strong one below.
 * The ❌ stamp slams onto the top panel (cue 0) with a small shake, the bottom panel arrives (cue 1) and
 * its ✅ stamp follows (cue 2). A panel can show its text as a mini chat message (bubble: prompt | answer).
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {rise} from '../anim';
import {EMOJI_FONT, PREROLL, Sfx, shake, slam, uiZone, useFontsFor} from '../motion';
import {Ripple, wrapStarts} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, Avatar, chatFamily, clamp, colours, mix, onColor, skin} from './chat';

type Side = {text: string; label: string; bubble: 'prompt' | 'answer' | null};
const RED = '#ef4f55';
const GREEN = '#2fbf71';

export const splitTiming = (duration: number, speech: number, cues: (number | null)[]) => {
  const d = Math.max(duration, 40);
  const cueAt = (i: number) => (typeof cues[i] === 'number' ? clamp((cues[i] as number) - 4, 0, d - 12) : null);
  const badStamp = cueAt(0) ?? clamp(Math.max(speech + 16, d * 0.2), 10, d * 0.4);
  const goodIn = Math.max(cueAt(1) ?? Math.max(badStamp + 22, d * 0.45), badStamp + 8);
  const goodStamp = Math.max(cueAt(2) ?? goodIn + 14, goodIn + 6);
  return {badIn: -PREROLL, badStamp, goodIn, goodStamp};
};

export const Split: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const side = (x: any, fallback: string): Side => ({
    text: String(x?.text ?? ''),
    label: typeof x?.label === 'string' && x.label.trim() ? x.label : fallback,
    bubble: x?.bubble === 'prompt' || x?.bubble === 'answer' ? x.bubble : null,
  });
  const title = props.title ? String(props.title) : '';
  const cyr = /[Ѐ-ӿ]/.test([title, props.bad?.text ?? '', props.good?.text ?? ''].join(' '));
  const bad = side(props.bad, cyr ? 'Погано' : 'Bad');
  const good = side(props.good, cyr ? 'Добре' : 'Good');
  const all = [title, bad.text, bad.label, good.text, good.label].join(' ');
  const family = chatFamily(st.fonts.body, all);
  const ready = useFontsFor([`700 40px ${family}`, `800 40px ${family}`, `400 40px ${EMOJI_FONT}`], all + '❌✅');

  const c = colours(p);
  const sk = skin(st, p, c.dark, u);

  // ---- geometry: the two panels share the UI band
  const zone = uiZone(width, height);
  const zoneH = zone.bottom - zone.top;
  const panelW = vertical ? width - 130 * u : width * 0.6;
  const left = (width - panelW) / 2;
  const titleH = title ? 74 * u : 0;
  const gap = 34 * u;
  const panelH = Math.min((zoneH - titleH - gap - 20 * u) / 2, 470 * u);
  const blockH = titleH + 2 * panelH + gap;
  const top0 = zone.top + (zoneH - blockH) / 2 + titleH;
  const pad = 34 * u;
  const labelH = 50 * u;
  const stampSpace = 180 * u; // room for the stamp, so it never covers the text

  // one text size for both panels: the largest that fits
  const fs = useMemo(() => {
    const fits = (f: number) =>
      [bad, good].every((s) => {
        const bubblePad = s.bubble ? 2 * 22 * u : 0;
        const avatar = s.bubble === 'answer' ? 70 * u : 0;
        const w = (panelW - 2 * pad - stampSpace - bubblePad - avatar) * (s.bubble ? 0.98 : 1);
        const h = wrapStarts(s.text, 700, f, family, w / 1.02).length * f * 1.3 + (s.bubble ? 2 * 18 * u : 0);
        return h <= panelH - labelH - 2 * pad - 14 * u;
      });
    let f = (vertical ? 46 : 40) * u;
    while (f > 24 * u && !fits(f)) f -= 1 * u;
    return f;
  }, [ready, family, bad.text, good.text, bad.bubble, good.bubble, panelW, panelH]);

  const t = splitTiming(duration, speech, cues);

  const panel = (s: Side, i: 0 | 1) => {
    const isBad = i === 0;
    const col = isBad ? RED : GREEN;
    const inAt = isBad ? t.badIn : t.goodIn;
    const stampAt = isBad ? t.badStamp : t.goodStamp;
    const k = rise(frame, fps, inAt, 15);
    const stamp = slam(frame, fps, stampAt);
    const jolt = shake(frame, stampAt + 2, 12 * u, 14);
    const loser = isBad ? interpolate(frame, [t.goodIn, t.goodIn + 12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 0;
    const tint = mix(c.win, col, c.dark ? 0.13 : 0.09);
    const y = top0 + i * (panelH + gap);
    const textCol = onColor(tint, [p.text]);
    const content = s.bubble ? (
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 14 * u, justifyContent: s.bubble === 'prompt' ? 'flex-end' : 'flex-start', width: '100%'}}>
        {s.bubble === 'answer' ? <Avatar size={56 * u} bg={c.avatar} fg={c.avatarFace} square={st.radius === 0} /> : null}
        <div
          style={{
            ...sk.bubble,
            ...(st.label === 'neon' ? {boxShadow: undefined} : {}),
            maxWidth: '96%',
            padding: `${18 * u}px ${22 * u}px`,
            borderRadius: s.bubble === 'prompt' ? `${26 * u}px ${26 * u}px ${8 * u}px ${26 * u}px` : `${26 * u}px ${26 * u}px ${26 * u}px ${8 * u}px`,
            background: s.bubble === 'prompt' ? c.user : c.bot,
            color: s.bubble === 'prompt' ? c.userText : c.botText,
            fontFamily: family,
            fontWeight: 700,
            fontSize: fs,
            lineHeight: 1.3,
            overflowWrap: 'anywhere',
          }}
        >
          {s.text}
        </div>
      </div>
    ) : (
      <div style={{fontFamily: family, fontWeight: 700, fontSize: fs, lineHeight: 1.3, color: textCol, overflowWrap: 'anywhere'}}>{s.text}</div>
    );
    if (frame < inAt - 1) return null;
    return (
      <React.Fragment key={i}>
        <div
          style={{
            position: 'absolute',
            left,
            top: y,
            width: panelW,
            height: panelH,
            opacity: Math.min(k * 1.5, 1) * (1 - 0.3 * loser),
            filter: loser ? `saturate(${1 - 0.5 * loser})` : undefined,
            transform: `translate(${jolt + (1 - Math.min(k, 1)) * (isBad ? -1 : 1) * 120 * u}px, 0) scale(${1 - 0.03 * loser})`,
          }}
        >
          <div
            style={{
              ...sk.win,
              position: 'absolute',
              inset: 0,
              borderRadius: Math.max(st.radius, 4) * 1.6 * u,
              background: tint,
              borderLeft: `${10 * u}px solid ${col}`,
              boxSizing: 'border-box',
              padding: `${pad}px ${pad + stampSpace}px ${pad}px ${pad}px`,
              display: 'flex',
              flexDirection: 'column',
              gap: 14 * u,
            }}
          >
            <div
              style={{
                alignSelf: 'flex-start',
                height: labelH,
                display: 'flex',
                alignItems: 'center',
                padding: `0 ${20 * u}px`,
                borderRadius: st.radius === 0 ? 0 : labelH / 2,
                background: col,
                color: '#ffffff',
                fontFamily: family,
                fontWeight: 800,
                fontSize: 26 * u,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                flexShrink: 0,
              }}
            >
              {s.label}
            </div>
            <div style={{flex: 1, display: 'flex', alignItems: 'center', minHeight: 0}}>{content}</div>
          </div>
          {/* the stamp */}
          {frame >= stampAt ? (
            <>
              <Ripple frame={frame} at={stampAt + 2} x={panelW - 92 * u} y={panelH / 2} r={130 * u} color={alpha(col, 0.8)} width={7 * u} />
              <div
                style={{
                  position: 'absolute',
                  right: 30 * u,
                  top: panelH / 2 - 75 * u,
                  width: 150 * u,
                  height: 150 * u,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontFamily: EMOJI_FONT,
                  fontSize: 124 * u,
                  lineHeight: 1,
                  opacity: Math.min(stamp * 2, 1),
                  transform: `scale(${2.3 - 1.3 * stamp}) rotate(${-14 + 8 * Math.min(stamp, 1)}deg)`,
                  filter: `drop-shadow(0 ${8 * u}px ${12 * u}px rgba(0,0,0,0.35))`,
                }}
              >
                {isBad ? '❌' : '✅'}
              </div>
            </>
          ) : null}
        </div>
        <Sfx name="pop" at={stampAt} gain={1.3} />
      </React.Fragment>
    );
  };

  return (
    <AbsoluteFill>
      {title ? (
        <div
          style={{
            position: 'absolute',
            left,
            width: panelW,
            top: top0 - titleH,
            height: titleH - 16 * u,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: family,
            fontWeight: 800,
            fontSize: 44 * u,
            color: p.text,
            opacity: rise(frame, fps, -PREROLL, 16),
          }}
        >
          {title}
        </div>
      ) : null}
      {panel(bad, 0)}
      {panel(good, 1)}
    </AbsoluteFill>
  );
};
