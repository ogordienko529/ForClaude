import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, revealAt, rise, stagger} from '../anim';
import {PREROLL, Sticker, uiZone, useFontsFor} from '../motion';
import {textWidth} from '../screen';
import {useStyle} from '../styles';
import {FONTS, usePalette} from '../theme';
import type {SceneProps} from '../types';
import {Kicker} from '../ui';

const useUnit = () => {
  const {width, height} = useVideoConfig();
  return Math.min(width, height) / 1080;
};

/** 9:16: centre the card in the UI band (the captions sit below it); 16:9: in the whole frame. */
const useBand = (side: number): React.CSSProperties => {
  const {width, height} = useVideoConfig();
  if (height <= width) return {padding: side};
  const z = uiZone(width, height);
  return {paddingTop: z.top, paddingBottom: height - z.bottom, paddingLeft: side, paddingRight: side};
};

/** The scene's first appearance starts before frame 0, so the first frame is already in motion. */
const opening = (start: number) => Math.min(start, 0) - PREROLL;

export const TitleCard: React.FC<SceneProps> = ({props, speech}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const p = usePalette();
  const u = useUnit() * (height > width ? 1.2 : 1);        // 9:16: phone-sized text
  const words = String(props.title || '').split(' ');
  const start = opening(Math.min(Math.max(speech - 6, 0), 6));
  const line = progress(frame, start + 10, start + 40);
  const band = useBand(120 * u);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', ...band}}>
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

const norm = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

export const Kinetic: React.FC<SceneProps> = ({props, speech, duration, cues}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  const u = useUnit();
  const lines: string[] = props.lines || [];
  const emph = new Set((props.emphasis || []).map((w: string) => norm(w)).filter(Boolean));
  const total = lines.reduce((n, l) => n + l.split(' ').length, 0);
  const {width, height} = useVideoConfig();
  const st = useStyle();
  const portrait = height > width;
  // 9:16: phone-sized type, each line as big as fits the width (handwritten Caveat runs small, so it gets more)
  const base = (portrait ? (lines.length >= 3 ? 112 : lines.length === 2 ? 128 : 150) : lines.length >= 3 ? 74 : lines.length === 2 ? 88 : 104) * u
    * (/Caveat/.test(st.fonts.impact) ? 1.3 : 1);
  // measure with the style's own font, once it has loaded (a fallback font measures narrower)
  const ready = useFontsFor([`800 100px ${st.fonts.impact}`], lines.join(' '));
  const lineSize = lines.map((l) => {
    if (!ready) return base * 0.7;
    const w = textWidth(l, 800, 100, st.fonts.impact) + 34 * Math.max(l.split(' ').length - 1, 0);
    return portrait ? Math.max(Math.min(base, (width * 0.8 * 100) / Math.max(w, 1)), base * 0.5) : base;
  });
  const size = Math.min(...lineSize, base);
  const band = useBand(120 * u);
  // a line with a narration cue appears when its words are spoken (the first line no later than
  // the narration itself, so the screen is never empty); otherwise words spread out. The very first
  // word is already rising on frame 0.
  let idx = 0;
  const starts = lines.map((l, li) =>
    l.split(' ').map((_, wi) => {
      const c = cues[li];
      const lineStart = typeof c === 'number' ? Math.max(c - 4, 0) : null;
      // `fast`: a hook or a call to action, the whole text on screen within ~0.4 s
      const start = props.fast
        ? idx * 2
        : lineStart === null
        ? stagger(idx, total, speech, duration, 0.5)
        : (li === 0 ? Math.min(lineStart, speech) : lineStart) + wi * 3;
      return idx++ === 0 ? Math.min(start, 2 - PREROLL) : start;
    }),
  );
  const last = Math.max(0, ...starts.flat());
  const stickerAt = Math.min(last + 10, Math.max(duration - 24, 0));
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', ...band}}>
      <div style={{position: 'relative'}}>
        {lines.map((l, li) => (
          <div key={li} style={{textAlign: 'center', marginBottom: 18 * u, whiteSpace: 'nowrap'}}>
            <span style={{position: 'relative', display: 'inline-block'}}>
            {l.split(' ').map((w, wi) => {
              const r = rise(frame, fps, starts[li][wi]);
              const isEm = emph.has(norm(w));
              return (
                <span
                  key={wi}
                  style={{
                    display: 'inline-block',
                    marginRight: '0.34em',
                    opacity: r,
                    transform: `translateY(${(1 - r) * 30 * u}px) scale(${isEm ? 1 + 0.06 * r : 1})`,
                    fontFamily: FONTS.impact,
                    fontWeight: 800,
                    fontSize: lineSize[li],
                    color: isEm ? p.accent : p.text,
                    letterSpacing: '-0.01em',
                  }}
                >
                  {w}
                </span>
              );
            })}
            {/* the sticker sits on the first line's end, close to the words even when a later line wraps */}
            {li === 0 && props.sticker ? (
              <Sticker emoji={String(props.sticker)} at={stickerAt} size={size * (portrait ? 1.05 : 1.35)} tilt={12}
                style={portrait ? {right: -size * 0.55, top: -size * 1.05} : {right: -size * 1.6, top: -size * 0.8}} />
            ) : null}
            </span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

export const FactCard: React.FC<SceneProps> = ({props, speech, duration}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const p = usePalette();
  const text = String(props.text || '');
  // 9:16: phone-sized text, a little smaller for a long fact so the card stays in the UI band
  const u = useUnit() * (height > width ? 1.25 * Math.max(1 - Math.max(text.length - 90, 0) / 200, 0.72) : 1);
  const words = text.split(' ');
  const band = useBand((height > width ? 56 : 160) * u);
  const stickerAt = Math.min(stagger(Math.floor(words.length * 0.7), words.length, speech, duration, 0.6) + 4, Math.max(duration - 24, 0));
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', ...band}}>
      <div
        style={{
          position: 'relative',
          maxWidth: 1400 * u,
          padding: `${70 * u}px ${90 * u}px`,
          borderRadius: 26 * u,
          background: p.panel,
          borderLeft: `${8 * u}px solid ${p.accent}`,
          opacity: rise(frame, fps, opening(speech - 8)),
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
        {props.sticker ? (
          <Sticker emoji={String(props.sticker)} at={stickerAt} size={100 * u} tilt={12} style={{right: -24 * u, top: -62 * u}} />
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const ListCard: React.FC<SceneProps> = ({props, speech, duration, cues}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const p = usePalette();
  const u = useUnit() * (height > width ? 1.32 : 1);       // 9:16 has the room: phone-sized text
  const items: string[] = props.items || [];
  const band = useBand(70 * u);
  const at = items.map((_, i) => {
    const a = revealAt(i, items.length, speech + 6, duration, cues, 0.7);
    return i === 0 && !props.title ? Math.min(a, 2 - PREROLL) : a; // no title: the first item opens the scene
  });
  const stickerAt = Math.min(Math.max(0, ...at) + 10, Math.max(duration - 24, 0));
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', ...(height > width ? band : {padding: `0 ${160 * u}px`})}}>
      <div style={{maxWidth: 1500 * u, position: 'relative'}}>
      {props.title && (
        <div style={{fontFamily: FONTS.serif, fontWeight: 700, fontSize: 76 * u, color: p.text, marginBottom: 46 * u, opacity: rise(frame, fps, opening(speech - 8))}}>
          {props.title}
        </div>
      )}
      {items.map((it, i) => {
        const r = rise(frame, fps, at[i]);
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', marginBottom: 30 * u, opacity: r, transform: `translateX(${(1 - r) * -50 * u}px)`}}>
            <div style={{width: 54 * u, height: 54 * u, borderRadius: 27 * u, background: p.accent, color: p.bg1, fontFamily: FONTS.sans, fontWeight: 800, fontSize: 30 * u, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 30 * u, flexShrink: 0}}>
              {i + 1}
            </div>
            <div style={{fontFamily: FONTS.sans, fontWeight: 600, fontSize: 50 * u, color: p.text}}>{it}</div>
          </div>
        );
      })}
      {props.sticker ? (
        <Sticker emoji={String(props.sticker)} at={stickerAt} size={90 * u} tilt={-10} style={{right: -40 * u, top: -70 * u}} />
      ) : null}
      </div>
    </AbsoluteFill>
  );
};
