/**
 * tgpost: the channel's own post in a Telegram-like channel view, for the call-to-action beat («готовий промпт — у
 * телеграм-каналі»). The viewer sees what is waiting there: the channel header (round «Ш І» avatar, name, «канал»),
 * a post with a bold title and the prompt in a monospace tap-to-copy block. Everything is already moving on the
 * first frame: the post slides up, the prompt types in, a fingertip taps the block (ripple, click) and the toast
 * «Скопійовано в буфер обміну» comes up; then the tag pulses. Colours come from the palette, corners and borders
 * from the style (like the chat scene), so it fits every style; no product logo, only the channel's own look.
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {rise} from '../anim';
import {EMOJI_FONT, MONO_FONT, PREROLL, Sfx, uiZone, useFontsFor} from '../motion';
import {Ripple} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, chatFamily, clamp, colours, contrast, lineCount, mix, onColor, skin, useChatFonts} from './chat';

const CLAMP = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const LH = {title: 1.2, code: 1.36, tag: 1.25, meta: 1.2};

/** Frames (from the scene start) of every step; the tap lands on cue 0 when the storyboard gives one. */
export const tgpostTiming = (duration: number, speech: number, cues: (number | null)[], chars: number, fps: number) => {
  const d = Math.max(duration, 36);
  const typeStart = clamp(speech, 6, d * 0.12);
  const typeEnd = typeStart + clamp(chars / 2.4, 10, d * 0.32); // ~70 characters a second, a reveal more than typing
  const cue = typeof cues[0] === 'number' ? (cues[0] as number) - 3 : d * 0.55;
  const tap = Math.round(clamp(cue, typeEnd + 6, d - 18));
  const toastIn = tap + 3;
  const toastOut = Math.min(toastIn + Math.round(1.1 * fps), d - 4);
  const tagAt = Math.min(tap + 26, d - 10);
  return {typeStart, typeEnd, tap, toastIn, toastOut, tagAt};
};

const CopyIcon: React.FC<{size: number; color: string}> = ({size, color}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{display: 'block'}}>
    <rect x={8} y={8} width={12} height={13} rx={2.5} fill="none" stroke={color} strokeWidth={2.2} />
    <path d="M5 16V5.5A2.5 2.5 0 0 1 7.5 3H15" fill="none" stroke={color} strokeWidth={2.2} strokeLinecap="round" />
  </svg>
);

export const TgPost: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const title = String(props.title ?? '');
  const prompt = String(props.prompt ?? '');
  const channel = String(props.channel ?? 'ШІ на старті');
  const tag = props.tag ? String(props.tag) : '';
  const all = [title, channel, tag, 'канал Скопійовано в буфер обміну Залишити коментар 09:30'].join(' ');
  const family = chatFamily(st.fonts.body, all);
  const fontsReady = useChatFonts(family, all);
  useFontsFor([`400 40px ${MONO_FONT}`, `700 40px ${MONO_FONT}`, `400 40px ${EMOJI_FONT}`], prompt + '👆💬');

  const c = colours(p);
  const sk = skin(st, p, c.dark, u);
  const zone = uiZone(width, height);
  const cardW = vertical ? width - 80 * u : Math.min(width * 0.62, 1100 * u);
  const winPad = 24 * u;
  const bubbleW = cardW - 2 * winPad;
  const headerH = (84 + 2 * 20) * u;
  const slotH = 96 * u; // under the post: «Залишити коментар», where the copy toast comes up

  // one scale for the whole post: the largest at which it fits the UI band
  const k = useMemo(() => {
    const avail = (height - zone.top - (height - zone.bottom)) * 0.96 - headerH - 2 * winPad - slotH;
    const fits = (s: number) => {
      const pad = 28 * s * u;
      const textW = bubbleW - 2 * pad - 2 * sk.border;
      const codeW = textW - 2 * 24 * s * u - 6 * u;
      let h = 2 * pad;
      h += lineCount(title, 800, 50 * s * u, family, textW) * 50 * s * u * LH.title + 18 * s * u;
      h += lineCount(prompt, 400, 37 * s * u, MONO_FONT, codeW * 0.97) * 37 * s * u * LH.code + 2 * 22 * s * u;
      if (tag) h += 14 * s * u + 36 * s * u * LH.tag;
      h += 10 * s * u + 28 * s * u * LH.meta;
      return h <= avail;
    };
    let s = 1.45;
    while (s > 0.6 && !fits(s)) s -= 0.02;
    return s;
  }, [fontsReady, family, title, prompt, tag, bubbleW, height, sk.border]); // fontsReady: measure again with the real fonts

  const pad = 28 * k * u;
  const fTitle = 50 * k * u;
  const fCode = 37 * k * u;
  const fTag = 36 * k * u;
  const fMeta = 28 * k * u;
  const R = st.radius === 0 ? 0 : clamp(st.radius * 1.6, 10, 30) * u;

  const t = tgpostTiming(duration, speech, cues, Array.from(prompt).length, fps);
  const appear = rise(frame, fps, -PREROLL);
  const post = rise(frame, fps, 3 - PREROLL, 16);
  const chars = Array.from(prompt);
  const typed = Math.round(chars.length * clamp((frame - t.typeStart) / Math.max(t.typeEnd - t.typeStart, 1), 0, 1));
  const typing = frame >= t.typeStart && frame < t.typeEnd;

  // the fingertip comes up, presses on the tap, lifts off
  const fingerIn = interpolate(frame, [t.tap - 14, t.tap], [0, 1], CLAMP);
  const fingerOut = interpolate(frame, [t.tap + 8, t.tap + 20], [0, 1], CLAMP);
  const pressed = frame >= t.tap && frame < t.tap + 6;
  const flash = interpolate(frame, [t.tap, t.tap + 3, t.tap + 16], [0, 1, 0], CLAMP);
  const toast = spring({frame: frame - t.toastIn, fps, config: {damping: 15, stiffness: 180, mass: 0.6}}) *
    interpolate(frame, [t.toastOut - 6, t.toastOut], [1, 0], CLAMP);
  const tagK = tag ? spring({frame: frame - t.tagAt, fps, config: {damping: 9, stiffness: 200, mass: 0.6}}) : 0;
  const tagPulse = 1 + 0.1 * Math.sin(Math.min(tagK, 1) * Math.PI);

  const codeBg = c.dark ? mix(c.bot, '#000000', 0.28) : mix(c.bot, p.text, 0.07);
  const codeText = onColor(codeBg, [p.text, '#ffffff', '#111111']);
  const link = [p.accent2, p.accent].find((x) => contrast(x, c.bot) >= 3) || c.botText;
  const avatarText = onColor(p.accent, ['#ffffff', '#141414']);
  const muted = mix(c.botText, c.bot, 0.42);

  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingTop: zone.top, paddingBottom: height - zone.bottom}}>
      <div style={{...sk.win, position: 'relative', width: cardW, boxSizing: 'border-box', background: c.win, borderRadius: st.radius * 2 * u,
        opacity: Math.min(appear * 1.5, 1), transform: `translateY(${(1 - appear) * 70 * u}px) scale(${0.96 + 0.04 * appear})`}}>
        {/* the channel header */}
        <div style={{display: 'flex', alignItems: 'center', gap: 22 * u, height: headerH, boxSizing: 'border-box', padding: `0 ${28 * u}px`,
          background: c.header, borderBottom: `${2 * u}px solid ${c.divider}`, borderRadius: `${st.radius * 2 * u}px ${st.radius * 2 * u}px 0 0`}}>
          <div style={{fontFamily: family, fontWeight: 600, fontSize: 52 * u, lineHeight: 1, color: muted, marginTop: -6 * u}}>‹</div>
          <div style={{width: 84 * u, height: 84 * u, borderRadius: '50%', background: p.accent, display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: 5 * u, fontFamily: 'Inter, Arial, sans-serif', fontWeight: 800, fontSize: 36 * u, color: avatarText,
            flexShrink: 0}}>
            <span>Ш</span>
            <span>І</span>
          </div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 4 * u, minWidth: 0}}>
            <div style={{fontFamily: family, fontWeight: 800, fontSize: 42 * u, lineHeight: 1.1, color: c.botText, whiteSpace: 'nowrap'}}>{channel}</div>
            <div style={{fontFamily: family, fontWeight: 600, fontSize: 30 * u, lineHeight: 1.1, color: muted}}>канал</div>
          </div>
        </div>

        {/* the post */}
        <div style={{padding: winPad, paddingBottom: 0}}>
          <div style={{...sk.bubble, position: 'relative', background: c.bot, borderRadius: `${R}px ${R}px ${R}px ${Math.min(R, 8 * u)}px`,
            padding: pad, boxSizing: 'border-box', opacity: Math.min(post * 1.6, 1), transform: `translateY(${(1 - post) * 90 * u}px)`}}>
            <div style={{fontFamily: family, fontWeight: 800, fontSize: fTitle, lineHeight: LH.title, color: c.botText, marginBottom: 18 * k * u}}>
              {title}
            </div>
            <div style={{position: 'relative', background: mix(codeBg, '#ffffff', c.dark ? 0.12 * flash : 0.5 * flash), borderRadius: 14 * u,
              borderLeft: `${6 * u}px solid ${p.accent}`, padding: `${22 * k * u}px ${24 * k * u}px`,
              transform: `scale(${pressed ? 0.985 : 1})`, transformOrigin: 'center'}}>
              <div style={{position: 'absolute', right: 14 * u, top: 12 * u, opacity: 0.75}}>
                <CopyIcon size={34 * u} color={codeText} />
              </div>
              <div style={{fontFamily: MONO_FONT, fontWeight: 400, fontSize: fCode, lineHeight: LH.code, color: codeText, whiteSpace: 'pre-wrap',
                overflowWrap: 'anywhere', paddingRight: 30 * u}}>
                <span>{chars.slice(0, typed).join('')}</span>
                <span style={{display: 'inline-block', width: 4 * u, height: fCode * 1.05, marginRight: -4 * u, verticalAlign: '-0.2em',
                  background: p.accent, opacity: typing || (frame < t.tap && Math.floor(frame / 8) % 2 === 0) ? 1 : 0}} />
                <span style={{opacity: 0}}>{chars.slice(typed).join('')}</span>
              </div>
              {/* the tap */}
              <div style={{position: 'absolute', left: '70%', top: '50%', width: 0, height: 0}}>
                <Ripple frame={frame} at={t.tap} x={0} y={0} r={120 * u} color={alpha(p.accent, 0.9)} width={10 * u} />
                {fingerIn > 0 && fingerOut < 1 ? (
                  <div style={{position: 'absolute', left: -40 * u, top: -8 * u + (1 - fingerIn) * 150 * u + fingerOut * 60 * u,
                    fontFamily: EMOJI_FONT, fontSize: 96 * u, lineHeight: 1, opacity: Math.min(fingerIn * 2, 1) * (1 - fingerOut),
                    transform: `scale(${pressed ? 0.92 : 1})`, filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.35))'}}>👆</div>
                ) : null}
              </div>
            </div>
            {tag ? (
              <div style={{marginTop: 14 * k * u, fontFamily: family, fontWeight: 700, fontSize: fTag, lineHeight: LH.tag, color: link,
                display: 'inline-block', transform: `scale(${tagPulse})`, transformOrigin: 'left center'}}>
                {tag}
              </div>
            ) : null}
            <div style={{marginTop: 10 * k * u, fontFamily: family, fontWeight: 600, fontSize: fMeta, lineHeight: LH.meta, color: muted,
              textAlign: 'right'}}>
              09:30
            </div>
          </div>
        </div>

        {/* under the post: the comments bar, and Telegram's copy toast over it */}
        <div style={{position: 'relative', height: slotH, margin: `0 ${winPad}px`, display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 12 * u, color: link, fontFamily: family, fontWeight: 700, fontSize: 32 * u, opacity: Math.min(post * 1.6, 1)}}>
          <span style={{fontFamily: EMOJI_FONT, fontWeight: 400}}>💬</span> Залишити коментар
          {toast > 0.01 ? (
            <div style={{position: 'absolute', left: '50%', top: '50%', transform: `translate(-50%, ${-50 + (1 - toast) * 60}%)`,
              opacity: Math.min(toast * 1.5, 1), display: 'flex', alignItems: 'center', gap: 14 * u, padding: `${18 * u}px ${30 * u}px`,
              borderRadius: 22 * u, background: 'rgba(28,30,34,0.94)', color: '#ffffff', fontFamily: family, fontWeight: 700, fontSize: 34 * u,
              lineHeight: 1.1, whiteSpace: 'nowrap', boxShadow: `0 ${10 * u}px ${30 * u}px rgba(0,0,0,0.35)`}}>
              <CopyIcon size={36 * u} color="#ffffff" />
              Скопійовано в буфер обміну
            </div>
          ) : null}
        </div>
      </div>
      <Sfx name="keys" at={Math.round(t.typeStart)} dur={Math.round(t.typeEnd - t.typeStart)} />
      <Sfx name="click" at={t.tap} gain={1.2} />
      <Sfx name="ding" at={t.toastIn + 2} gain={0.5} />
      {tag ? <Sfx name="pop" at={t.tagAt} gain={0.7} /> : null}
    </AbsoluteFill>
  );
};
