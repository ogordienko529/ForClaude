/**
 * A floating smartphone with a generic AI chat app inside (no brand look): the prompt types into the
 * composer at the bottom, a fingertip taps send, the message flies up into the thread, typing dots, then
 * the answer lines one by one (line i on cue i). `focus` gets a smooth camera punch-in (1.6x) that lands
 * ~0.2 s before the narration says the phrase; the phone straightens while the camera is close.
 * Colours come from the palette and borders from the style (shared with chat.tsx).
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise} from '../anim';
import {PREROLL, Sfx, pop, uiZone} from '../motion';
import {aimX, findPhrase, phraseSpot, Ripple, textWidth, Touch, wrapStarts} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, Avatar, chatFamily, clamp, colours, marks, mix, onColor, Rich, skin, take, useChatFonts} from './chat';

const ZOOM = 1.6;
const LH = 1.3;

type Focus = {where: 'prompt' | 'answer' | null; line: number; typedBy: number};

// ------------------------------------------------------------------ timing
/** Frames (from the scene start) of every step: typing, the tap on send, the dots, the answer lines, the zoom. */
export const phoneTiming = (
  duration: number,
  speech: number,
  cues: (number | null)[],
  chars: number,
  n: number,
  focus: Focus,
  mark: number | null,
) => {
  const d = Math.max(duration, 36);
  const end = d * 0.8;
  const cueAt = (i: number) => (typeof cues[i] === 'number' ? clamp((cues[i] as number) - 4, 0, d * 0.92) : null);
  const SEND = 8; // the last key -> the tap on send
  const FLY = 4; // the tap -> the message lands in the thread
  const DOTS = 10; // landed -> typing dots
  const wait = focus.where === 'prompt' && mark === null ? 44 : 16; // dots (and the punch-in on the sent message)
  const fixed = SEND + FLY + DOTS;
  let typeStart = clamp(speech - 4, 4, d * 0.1);
  const nominal = Math.max(chars / 1.7, 10); // ~50 characters a second
  let first: number;
  const c0 = cueAt(0);
  if (c0 !== null) {
    first = c0;
  } else {
    const room = Math.max(end - Math.max(n - 1, 0) * 12 - typeStart, 30);
    first = typeStart + clamp(nominal, 10, room - fixed - wait) + fixed + wait;
    const j = cues.findIndex((c, i) => i < n && typeof c === 'number');
    if (j > 0) first = Math.min(first, (cueAt(j) as number) - 8 * j);
  }
  first = Math.max(first, 24);
  let typing = Math.min(nominal * 1.3, first - typeStart - fixed - wait);
  if (typing < 8) {
    // not enough room before the first answer: wait less, then start typing sooner
    typing = Math.min(nominal * 1.3, first - typeStart - fixed - 12);
    if (typing < 8) {
      typeStart = Math.max(0, first - fixed - 12 - 8);
      typing = Math.max(first - typeStart - fixed - 12, 4);
    }
  }
  let typeEnd = typeStart + typing;
  let tap = typeEnd + SEND;

  // the camera punch-in: lands ~0.2 s before the narration says the phrase (else on the phrase's own moment)
  let zoom: {start: number; land: number; hold: number; out: number; onComposer: boolean} | null = null;
  let land = 0;
  if (focus.where) {
    if (mark !== null) land = mark - 6;
    else if (focus.where === 'prompt') land = tap + FLY + 12;
    else land = -1; // set after the reveals
    if (focus.where === 'prompt' && land < tap) {
      // the phrase must be typed before the camera arrives: type faster (up to 3x), else arrive later
      const need = (land - 12 - typeStart) / Math.max(focus.typedBy, 0.05);
      if (typeStart + (typeEnd - typeStart) * focus.typedBy > land - 12) {
        if (need >= Math.max(nominal / 3, 4)) typeEnd = typeStart + need;
        else land = typeStart + (typeEnd - typeStart) * focus.typedBy + 12;
      }
      tap = Math.max(tap, typeEnd + SEND);
    }
  }
  let sent = tap + FLY;
  let dotsStart = sent + DOTS;
  if (focus.where === 'prompt' && land < tap) {
    // the camera stays on the composer while the phrase is read, then pulls back for the send
    const hold = Math.max(land + 14, Math.min(land + 36, tap - 12));
    const out = hold + 12;
    if (out > tap - 2) {
      const shift = out - (tap - 2);
      tap += shift;
      sent += shift;
      dotsStart += shift;
    }
    zoom = {start: land - 12, land, hold, out, onComposer: true};
  }
  first = Math.max(first, dotsStart + 6);

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
    let j = i + 1;
    while (j < n && cueAt(j) === null) j++;
    const target = j < n ? (cueAt(j) as number) : Math.max(end - 8, prev + 3 * (n - i));
    const steps = j < n ? j - i + 1 : n - i;
    reveals.push(Math.max(prev + (target - prev) / steps, prev + 3));
  }
  if (focus.where && !zoom) {
    if (focus.where === 'answer') land = Math.max(land, (reveals[focus.line] ?? first) + 10);
    land = clamp(Math.max(land, sent + 8), 14, d - 8);
    const hold = Math.min(land + 38, Math.max(d - 4, land + 1));
    zoom = {start: land - 12, land, hold, out: hold + 13, onComposer: false};
  }
  return {appear: -PREROLL, typeStart, typeEnd, tap, sent, dotsStart, reveals, zoom};
};

// ------------------------------------------------------------------ small drawings
const StatusIcons: React.FC<{color: string; q: number}> = ({color, q}) => (
  <div style={{display: 'flex', alignItems: 'flex-end', gap: 8 * q}}>
    <svg width={30 * q} height={20 * q} viewBox="0 0 30 20">
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={i * 8} y={16 - i * 5} width={5.5} height={4 + i * 5} rx={1.2} fill={color} />
      ))}
    </svg>
    <svg width={26 * q} height={20 * q} viewBox="0 0 26 20">
      <path d="M13 18 L16.5 13.6 A5.6 5.6 0 0 0 9.5 13.6 Z" fill={color} />
      <path d="M5.2 10.2 A11.5 11.5 0 0 1 20.8 10.2" stroke={color} strokeWidth={2.6} fill="none" strokeLinecap="round" />
      <path d="M1.4 6.2 A17 17 0 0 1 24.6 6.2" stroke={color} strokeWidth={2.6} fill="none" strokeLinecap="round" />
    </svg>
    <svg width={40 * q} height={20 * q} viewBox="0 0 40 20">
      <rect x={1} y={2} width={33} height={16} rx={4.5} stroke={color} strokeWidth={2} fill="none" opacity={0.6} />
      <rect x={4} y={5} width={24} height={10} rx={2.5} fill={color} />
      <rect x={35.5} y={7} width={3} height={6} rx={1.5} fill={color} opacity={0.6} />
    </svg>
  </div>
);

const SendIcon: React.FC<{size: number; color: string}> = ({size, color}) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <path d="M12 19 L12 6 M6 11.5 L12 5.5 L18 11.5" stroke={color} strokeWidth={2.8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// ------------------------------------------------------------------ the scene
export const Phone: React.FC<SceneProps> = ({props, duration, speech, cues, marks: sceneMarks}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const prompt = String(props.prompt ?? '');
  const answer: string[] = (Array.isArray(props.answer) ? props.answer : []).map((a: unknown) => String(a));
  const chips: string[] = (Array.isArray(props.tool_chips) ? props.tool_chips : []).map((c: unknown) => String(c)).slice(0, 4);
  const focusText = typeof props.focus === 'string' ? props.focus.trim() : '';
  const highlight: string[] = [
    ...(Array.isArray(props.highlight) ? props.highlight : []).map((h: unknown) => String(h)),
    ...(focusText ? [focusText] : []),
  ];
  const cyr = /[Ѐ-ӿ]/.test([prompt, ...answer, props.app_name ?? ''].join(' '));
  const appName = props.app_name ? String(props.app_name) : cyr ? 'ШІ-чат' : 'AI chat';
  const placeholder = cyr ? 'Повідомлення…' : 'Message…';
  const greeting = cyr ? 'Чим допомогти?' : 'How can I help?';
  const online = cyr ? 'онлайн' : 'online';
  const all = [appName, prompt, ...answer, ...chips, placeholder, greeting, online, '12:30'].join(' ');
  const family = chatFamily(st.fonts.body, all);
  const fontsReady = useChatFonts(family, all);

  const c = colours(p);
  const sk = skin(st, p, c.dark, u);
  const bw = sk.border;
  const ink = onColor(c.win, [p.text]);

  // ---- geometry: the phone fills the UI band; its status bar may reach into the top margin (decoration)
  const zone = uiZone(width, height);
  const zoneH = zone.bottom - zone.top;
  const PH = zoneH * (vertical ? 1.07 : 1);
  const PW = PH / 1.9;
  const q = PW / 540; // the phone is designed 540 px wide
  const pLeft = width / 2 - PW / 2;
  const pTop = zone.bottom - (vertical ? 4 * u : 0) - PH;
  const bezel = 13 * q;
  const sw = PW - 2 * bezel;
  const sh = PH - 2 * bezel;
  const R = st.radius === 0 ? 18 * q : 72 * q;
  const statusH = 46 * q;
  const headerH = 78 * q;
  const threadTop = statusH + headerH;
  const homeH = 26 * q;
  const cmpMargin = 12 * q;
  const cmpPad = 14 * q;
  const sendD = 50 * q;
  const cmpW = sw - 2 * cmpMargin;
  const cmpTextW = cmpW - 2 * cmpPad - sendD - 10 * q;
  const cmpBottom = sh - homeH;
  const bubbleMax = sw * 0.8;
  const side = 14 * q;

  // one text scale: the largest at which the typed prompt and the finished thread both fit
  const fit = useMemo(() => {
    const sizes = (k: number) => {
      const fs = 29 * q * k;
      const fa = 27 * q * k;
      const padV = 14 * q * k;
      const padH = 18 * q * k;
      const textW = (bubbleMax - 2 * padH - 2 * bw) / 1.03;
      return {fs, fa, padV, padH, textW};
    };
    const measure = (k: number) => {
      const z = sizes(k);
      const lines = (t: string, size: number, w: number) => wrapStarts(t, 600, size, family, w).length;
      const cmpLines = Math.max(lines(prompt, z.fs, cmpTextW / 1.03), 1);
      const cmpFull = Math.max(cmpLines * z.fs * LH, sendD) + 2 * cmpPad;
      const cmpMin = Math.max(z.fs * LH, sendD) + 2 * cmpPad;
      const userH = lines(prompt, z.fs, z.textW) * z.fs * LH + 2 * z.padV + 2 * bw;
      const ansH = answer.map((a) => lines(a, z.fa, z.textW) * z.fa * LH + 2 * z.padV + 2 * bw);
      const gapA = 10 * q * k;
      const thread = 16 * q + userH + 16 * q * k + ansH.reduce((s, h) => s + h, 0) + gapA * Math.max(ansH.length - 1, 0) + 14 * q
        + (answer.length ? 0 : z.fa * LH + 2 * z.padV);
      const area = cmpBottom - cmpMin - threadTop;
      const ok = cmpFull <= (cmpBottom - threadTop) * 0.6 && thread <= area;
      return {...z, k, cmpFull, cmpMin, userH, ansH, gapA, thread, area, ok};
    };
    let k = 1.15;
    while (k > 0.62 && !measure(k).ok) k -= 0.02;
    return measure(k);
  }, [fontsReady, family, prompt, answer.join('\n'), q, bw]); // fontsReady: measure again with the real fonts
  const {fs, fa, padV, padH, textW, cmpFull, cmpMin, userH, ansH, gapA} = fit;
  const overflow = Math.max(fit.thread - fit.area, 0);

  // where the focus phrase is: the prompt (composer, then the sent message) or an answer line
  const focusIn: Focus = useMemo(() => {
    if (!focusText) return {where: null, line: 0, typedBy: 1};
    const sp = findPhrase(prompt, focusText);
    if (sp) return {where: 'prompt', line: 0, typedBy: sp.end / Math.max(Array.from(prompt).length, 1)};
    const j = answer.findIndex((a) => findPhrase(a, focusText));
    return j >= 0 ? {where: 'answer', line: j, typedBy: 1} : {where: null, line: 0, typedBy: 1};
  }, [focusText, prompt, answer.join('\n')]);
  const mark = typeof sceneMarks?.focus === 'number' ? sceneMarks.focus : null;
  const t = phoneTiming(duration, speech, cues, Array.from(prompt).length, answer.length, focusIn, mark);

  // ---- state at this frame
  const promptSegs = marks(prompt, highlight);
  const typedK = clamp((frame - t.typeStart) / Math.max(t.typeEnd - t.typeStart, 1), 0, 1);
  const nTyped = Math.round(Array.from(prompt).length * typedK);
  const isSent = frame >= t.tap + 1;
  const typing = frame >= t.typeStart && frame < t.typeEnd;
  const caretOn = !isSent && frame >= t.typeStart - 8 && (typing || Math.floor(frame / 8) % 2 === 0);
  const entrance = rise(frame, fps, t.appear, 16);
  const scroll = overflow * rise(frame, fps, t.reveals[t.reveals.length - 1] ?? t.sent, 20);
  const cmpH = isSent ? interpolate(frame, [t.tap, t.tap + 8], [cmpFull, cmpMin], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : cmpFull;
  const cmpTop = cmpBottom - cmpH;
  const userTop = threadTop + 16 * q - scroll;
  const ansTop = (i: number) => userTop + userH + 16 * q * fit.k + ansH.slice(0, i).reduce((s, h) => s + h + gapA, 0);
  const userW = Math.min(
    wrapStarts(prompt, 600, fs, family, textW).length > 1 ? bubbleMax : textWidth(prompt, 600, fs, family) * 1.03 + 2 * padH + 2 * bw,
    bubbleMax,
  );
  const userLeft = sw - side - userW;

  // ---- the camera
  const z = t.zoom;
  const zk = z ? progress(frame, z.start, z.land) * (1 - progress(frame, z.hold, z.out)) : 0;
  const target = useMemo(() => {
    if (!z || !focusIn.where) return null;
    const ox = pLeft + bezel;
    const oy = pTop + bezel;
    const scrollAt = overflow * rise(z.land, fps, t.reveals[t.reveals.length - 1] ?? t.sent, 20);
    let block: [number, number];
    let spot: {x: number; y: number} | null;
    if (focusIn.where === 'prompt' && z.onComposer) {
      const s = phraseSpot(prompt, focusText, 600, fs, family, cmpTextW / 1.03, fs * LH);
      spot = s && {x: cmpMargin + cmpPad + s.x, y: cmpBottom - cmpFull + cmpPad + s.y};
      block = [cmpMargin, cmpMargin + cmpW];
    } else if (focusIn.where === 'prompt') {
      const s = phraseSpot(prompt, focusText, 600, fs, family, textW, fs * LH);
      spot = s && {x: userLeft + padH + bw + s.x, y: threadTop + 16 * q - scrollAt + padV + bw + s.y};
      block = [userLeft, userLeft + userW];
    } else {
      const j = focusIn.line;
      const s = phraseSpot(answer[j], focusText, 600, fa, family, textW, fa * LH);
      const top = threadTop + 16 * q - scrollAt + userH + 16 * q * fit.k + ansH.slice(0, j).reduce((a, h) => a + h + gapA, 0);
      spot = s && {x: side + padH + bw + s.x, y: top + padV + bw + s.y};
      const w = Math.min(textWidth(answer[j], 600, fa, family) * 1.03 + 2 * padH + 2 * bw, bubbleMax);
      block = [side, side + w];
    }
    if (!spot) return null;
    const tx = width / 2;
    const ty = zone.top + zoneH * 0.45;
    const fx = aimX(ox + spot.x, ox + block[0], ox + block[1], ZOOM, tx, width, 36 * u);
    // the zoomed phone still fills the band: no empty strip under it (or above it)
    let dy = ty - ZOOM * (oy + spot.y);
    const bottom = ZOOM * (pTop + PH) + dy;
    if (bottom < zone.bottom) dy += zone.bottom - bottom;
    const top = ZOOM * pTop + dy;
    if (top > zone.top) dy -= top - zone.top;
    return {tx: tx - ZOOM * fx, ty: dy};
  }, [z?.land, z?.onComposer, focusIn.where, focusIn.line, fs, fa, family, prompt, userLeft, userW, overflow]);
  const camZ = 1 + (ZOOM - 1) * (target ? zk : 0);
  const camX = target ? zk * target.tx : 0;
  const camY = target ? zk * target.ty : 0;

  // the phone floats and leans a little, and straightens while the camera is close
  const calm = 1 - (target ? zk : 0);
  const tilt = (-2.4 + Math.sin(frame / 38) * 0.5) * calm;
  const bob = Math.sin(frame / 24) * 7 * u * calm + (1 - entrance) * 110 * u;
  const pScale = 0.93 + 0.07 * Math.min(entrance, 1.02);

  // ---- styles
  const text: React.CSSProperties = {fontFamily: family, fontWeight: 600, lineHeight: LH, overflowWrap: 'anywhere', whiteSpace: 'pre-wrap'};
  const marker = (col: string, k = 1): React.CSSProperties => ({
    fontWeight: 800,
    backgroundImage: `linear-gradient(${col}, ${col})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${k * 100}% 100%`,
    borderRadius: '0.18em',
    padding: '0 0.08em',
    margin: '0 -0.08em',
    boxDecorationBreak: 'clone',
    WebkitBoxDecorationBreak: 'clone',
  });
  const Rb = clamp(st.radius * 1.7, 10, 30) * q * Math.max(fit.k, 0.75);
  const rb = Math.min(Rb, 6 * q);
  const bubbleBase: React.CSSProperties = {...text, ...sk.bubble, padding: `${padV}px ${padH}px`, boxSizing: 'border-box', maxWidth: bubbleMax};
  const botStyle = (i: number): React.CSSProperties => ({
    ...bubbleBase,
    ...(st.label === 'neon' ? {boxShadow: undefined, border: `${2 * u}px solid ${alpha(p.accent2, 0.55)}`} : {}),
    fontSize: fa,
    color: c.botText,
    background: c.bot,
    borderRadius: `${i === 0 ? Rb : rb}px ${Rb}px ${Rb}px ${rb}px`,
  });
  const focusSweep = t.zoom ? progress(frame, t.zoom.start + 4, t.zoom.land + 6) : 1;
  // the sent message's marks sweep in with the punch-in when the camera aims at it
  const bubbleSweep = t.zoom && !t.zoom.onComposer && focusIn.where === 'prompt' ? focusSweep : 1;

  // the fingertip: comes in from the lower right, presses send, a ripple, then leaves
  const sendX = bezel + cmpMargin + cmpW - cmpPad - sendD / 2;
  const sendY = bezel + cmpBottom - cmpPad - sendD / 2;
  const approach = progress(frame, t.tap - 16, t.tap - 1);
  const touchOp = interpolate(frame, [t.tap - 16, t.tap - 10, t.tap + 7, t.tap + 14], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const press = Math.max(0, 1 - Math.abs(frame - t.tap) / 4);
  const sendScale = 1 - 0.14 * press;
  const hasText = nTyped > 0 && !isSent;

  const dotsIn = rise(frame, fps, t.dotsStart, 14);
  const dotsOut = answer.length
    ? interpolate(frame, [t.reveals[0] - 2, t.reveals[0] + 4], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const showDots = frame >= t.dotsStart && dotsOut > 0;
  const fly = rise(frame, fps, t.tap, 15);
  const emptyOut = progress(frame, t.tap - 2, t.tap + 8);


  return (
    <AbsoluteFill>
      <AbsoluteFill style={{transformOrigin: '0 0', transform: `translate(${camX}px, ${camY}px) scale(${camZ})`}}>
        {/* soft light behind the phone, slowly moving */}
        <div
          style={{
            position: 'absolute',
            left: width / 2 - PW * 1.1 + Math.sin(frame / 50) * 30 * u,
            top: pTop + PH * 0.12,
            width: PW * 2.2,
            height: PH * 0.9,
            background: `radial-gradient(closest-side, ${alpha(p.accent, 0.22)}, ${alpha(p.accent, 0)})`,
            opacity: Math.min(entrance, 1),
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: width / 2 - PW * 0.2 + Math.cos(frame / 60) * 40 * u,
            top: pTop + PH * 0.45,
            width: PW * 1.4,
            height: PH * 0.6,
            background: `radial-gradient(closest-side, ${alpha(p.accent2, 0.16)}, ${alpha(p.accent2, 0)})`,
            opacity: Math.min(entrance, 1),
          }}
        />

        {/* the phone */}
        <div
          style={{
            position: 'absolute',
            left: pLeft,
            top: pTop,
            width: PW,
            height: PH,
            opacity: Math.min(entrance * 1.6, 1),
            transform: `translateY(${bob}px) rotate(${tilt}deg) scale(${pScale})`,
          }}
        >
          {/* side buttons */}
          <div style={{position: 'absolute', right: -4 * q, top: 230 * q, width: 6 * q, height: 96 * q, borderRadius: 3 * q, background: '#2a2c33'}} />
          <div style={{position: 'absolute', left: -4 * q, top: 200 * q, width: 6 * q, height: 64 * q, borderRadius: 3 * q, background: '#2a2c33'}} />
          <div style={{position: 'absolute', left: -4 * q, top: 280 * q, width: 6 * q, height: 64 * q, borderRadius: 3 * q, background: '#2a2c33'}} />
          <div
            style={{
              ...sk.win,
              position: 'absolute',
              inset: 0,
              borderRadius: R,
              background: 'linear-gradient(145deg, #3a3d45 0%, #16171c 35%, #101115 70%, #2c2f36 100%)',
              boxSizing: 'border-box',
            }}
          />
          {/* the screen */}
          <div
            style={{
              position: 'absolute',
              left: bezel,
              top: bezel,
              width: sw,
              height: sh,
              borderRadius: Math.max(R - bezel, 0),
              overflow: 'hidden',
              background: c.win,
            }}
          >
            {/* status bar */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width: sw,
                height: statusH,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: `${6 * q}px ${30 * q}px 0`,
                boxSizing: 'border-box',
                background: c.header,
              }}
            >
              <div style={{fontFamily: family, fontWeight: 800, fontSize: 21 * q, color: ink}}>12:30</div>
              <StatusIcons color={ink} q={q} />
            </div>
            {/* header */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: statusH,
                width: sw,
                height: headerH,
                display: 'flex',
                alignItems: 'center',
                gap: 14 * q,
                padding: `0 ${20 * q}px`,
                boxSizing: 'border-box',
                background: c.header,
                borderBottom: `${2 * q}px solid ${c.divider}`,
              }}
            >
              <svg width={16 * q} height={28 * q} viewBox="0 0 16 28">
                <path d="M12 3 L3 14 L12 25" stroke={ink} strokeWidth={3.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <Avatar size={46 * q} bg={c.avatar} fg={c.avatarFace} square={st.radius === 0} />
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontFamily: family, fontWeight: 800, fontSize: 25 * q, color: ink, lineHeight: 1.1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                  {appName}
                </div>
                <div style={{display: 'flex', alignItems: 'center', gap: 6 * q, fontFamily: family, fontWeight: 600, fontSize: 17 * q, color: p.muted, marginTop: 3 * q}}>
                  <div style={{width: 9 * q, height: 9 * q, borderRadius: 5 * q, background: '#3ecf6e'}} />
                  {online}
                </div>
              </div>
              <svg width={8 * q} height={30 * q} viewBox="0 0 8 30">
                {[5, 15, 25].map((y) => (
                  <circle key={y} cx={4} cy={y} r={2.8} fill={ink} />
                ))}
              </svg>
            </div>

            {/* the empty chat: a greeting until the message is sent */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                width: sw,
                top: threadTop,
                height: cmpBottom - cmpFull - threadTop,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 16 * q,
                opacity: 1 - emptyOut,
                transform: `translateY(${-emptyOut * 40 * q}px)`,
              }}
            >
              <Avatar size={92 * q} bg={c.avatar} fg={c.avatarFace} square={st.radius === 0} />
              <div style={{fontFamily: family, fontWeight: 800, fontSize: 32 * q, color: ink}}>{greeting}</div>
            </div>

            {/* the thread */}
            <div style={{position: 'absolute', left: 0, top: 0, width: sw, height: cmpTop, overflow: 'hidden'}}>
              {isSent ? (
                <div
                  style={{
                    ...bubbleBase,
                    position: 'absolute',
                    right: side,
                    top: userTop,
                    fontSize: fs,
                    color: c.userText,
                    background: c.user,
                    borderRadius: `${Rb}px ${Rb}px ${rb}px ${Rb}px`,
                    opacity: Math.min(fly * 2, 1),
                    transform: `translateY(${(1 - fly) * (cmpBottom - cmpFull - userTop)}px) scale(${0.92 + 0.08 * Math.min(fly, 1)})`,
                    transformOrigin: 'right bottom',
                  }}
                >
                  <Rich segs={promptSegs} hi={marker(alpha(c.userText, 0.22), bubbleSweep)} />
                </div>
              ) : null}
              {showDots ? (
                <div
                  style={{
                    ...botStyle(0),
                    position: 'absolute',
                    left: side,
                    top: ansTop(0),
                    display: 'flex',
                    gap: 10 * q,
                    alignItems: 'center',
                    paddingTop: padV + 5 * q,
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
                          width: 15 * q * fit.k,
                          height: 15 * q * fit.k,
                          borderRadius: st.radius === 0 ? 0 : '50%',
                          background: p.muted,
                          opacity: 0.45 + 0.55 * w,
                          transform: `translateY(${-w * 8 * q}px)`,
                        }}
                      />
                    );
                  })}
                </div>
              ) : null}
              {answer.map((line, i) => {
                const at = t.reveals[i];
                const k = rise(frame, fps, at, 16);
                if (frame < at - 1) return null;
                return (
                  <div
                    key={i}
                    style={{
                      ...botStyle(i),
                      position: 'absolute',
                      left: side,
                      top: ansTop(i),
                      opacity: Math.min(k, 1),
                      transform: `translateY(${(1 - k) * 26 * q}px)`,
                    }}
                  >
                    <Rich
                      segs={marks(line, highlight)}
                      hi={{...marker(alpha(p.accent, c.dark ? 0.24 : 0.3), progress(frame, at + 8, at + 22)), color: c.hiText}}
                    />
                  </div>
                );
              })}
            </div>

            {/* the composer: where the prompt is typed */}
            <div
              style={{
                position: 'absolute',
                left: cmpMargin,
                top: cmpTop,
                width: cmpW,
                height: cmpH,
                boxSizing: 'border-box',
                borderRadius: Math.min(30 * q, cmpMin / 2),
                background: c.bot,
                border: `${2 * q}px solid ${frame >= t.typeStart - 8 && !isSent ? alpha(p.accent, 0.7) : c.divider}`,
                padding: cmpPad,
              }}
            >
              <div style={{...text, fontSize: fs, color: nTyped > 0 && !isSent ? c.botText : p.muted, width: cmpTextW, overflow: 'hidden', maxHeight: '100%'}}>
                {nTyped > 0 && !isSent ? (
                  <Rich segs={take(promptSegs, nTyped)} hi={{...marker(alpha(p.accent, c.dark ? 0.3 : 0.32), focusSweep), color: c.hiText}} />
                ) : (
                  <span style={{fontWeight: 600, whiteSpace: 'nowrap'}}>{frame < t.typeStart - 8 || isSent ? placeholder : ''}</span>
                )}
                <span
                  style={{
                    display: 'inline-block',
                    width: Math.max(3 * q, fs * 0.08),
                    height: fs * 1.05,
                    marginLeft: fs * 0.04,
                    marginRight: -(Math.max(3 * q, fs * 0.08) + fs * 0.04),
                    verticalAlign: '-0.18em',
                    background: p.accent,
                    borderRadius: 2 * q,
                    opacity: caretOn ? 1 : 0,
                  }}
                />
              </div>
              <div
                style={{
                  position: 'absolute',
                  right: cmpPad,
                  bottom: cmpPad,
                  width: sendD,
                  height: sendD,
                  borderRadius: st.radius === 0 ? 4 * q : sendD / 2,
                  background: hasText || (frame >= t.tap - 1 && frame < t.tap + 6) ? p.accent : mix(c.bot, p.text, 0.18),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transform: `scale(${sendScale})`,
                }}
              >
                <SendIcon size={sendD * 0.6} color={hasText ? c.userText : c.bot} />
              </div>
            </div>

            {/* home indicator */}
            <div
              style={{
                position: 'absolute',
                left: sw / 2 - 70 * q,
                bottom: 9 * q,
                width: 140 * q,
                height: 6 * q,
                borderRadius: 3 * q,
                background: alpha(ink, 0.55),
              }}
            />
          </div>
          {/* the camera cut-out */}
          <div style={{position: 'absolute', left: PW / 2 - 46 * q, top: bezel + 9 * q, width: 92 * q, height: 27 * q, borderRadius: 14 * q, background: '#050506'}} />

          {/* the fingertip and the tap */}
          <Ripple frame={frame} at={t.tap} x={sendX} y={sendY} r={70 * q} color={alpha(p.accent, 0.9)} width={6 * q} />
          <Ripple frame={frame} at={t.tap + 4} x={sendX} y={sendY} r={100 * q} color={alpha(p.accent, 0.5)} width={4 * q} />
          {touchOp > 0 ? (
            <Touch
              x={sendX + (1 - approach) * 90 * q}
              y={sendY + (1 - approach) * 150 * q}
              r={30 * q}
              press={press}
              opacity={touchOp * 0.92}
            />
          ) : null}
        </div>

        {/* tool chips float beside the phone, clear of the platform buttons on the right */}
        {chips.map((chip, i) => {
          const right = i % 2 === 0;
          const fsC = 26 * u;
          const w = textWidth(chip, 800, fsC, family) + 2 * 22 * u + 18 * u;
          const x = right ? Math.min(pLeft + PW - 46 * u, width - 22 * u - w) : Math.max(pLeft + 46 * u - w, 22 * u);
          const y = zone.top + zoneH * (0.08 + 0.16 * i);
          const at = 4 + i * 6 - PREROLL;
          const k = pop(frame, fps, at);
          const dots = [p.accent, p.accent2, '#3ecf6e', p.muted];
          return (
            <React.Fragment key={i}>
              <div
                style={{
                  position: 'absolute',
                  left: x,
                  top: y + Math.sin(frame / 20 + i * 1.7) * 5 * u,
                  height: fsC * 1.9,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 9 * u,
                  padding: `0 ${22 * u}px`,
                  borderRadius: st.radius === 0 ? 0 : fsC,
                  background: c.dark ? '#f6f4ee' : '#ffffff',
                  color: '#15171c',
                  fontFamily: family,
                  fontWeight: 800,
                  fontSize: fsC,
                  whiteSpace: 'nowrap',
                  boxShadow: st.label === 'bubble' ? `${5 * u}px ${5 * u}px 0 #111` : `0 ${10 * u}px ${24 * u}px rgba(0,0,0,0.3)`,
                  border: st.label === 'bubble' ? `${4 * u}px solid #111` : st.label === 'neon' ? `${2 * u}px solid ${p.accent2}` : undefined,
                  opacity: frame < at ? 0 : Math.min(k * 2, 1),
                  transform: `scale(${k}) rotate(${right ? 4 : -4}deg)`,
                }}
              >
                <div style={{width: 12 * u, height: 12 * u, borderRadius: 6 * u, background: dots[i % dots.length], flexShrink: 0}} />
                {chip}
              </div>
              <Sfx name="pop" at={at} gain={0.5} />
            </React.Fragment>
          );
        })}
      </AbsoluteFill>
      <Sfx name="keys" at={t.typeStart} dur={t.typeEnd - t.typeStart} />
      <Sfx name="click" at={t.tap} />
    </AbsoluteFill>
  );
};
