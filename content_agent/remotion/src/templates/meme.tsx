/**
 * A meme: a real meme picture or a short video fragment (a file in the project, e.g. a template from the public
 * memegen collection) with classic meme text in its text boxes.
 * - The media sits in a white meme panel as large as the UI band allows, with a slow punch-in.
 * - Each text lands on its narration cue (else they spread over the first ~60 % of the beat) with a slam and a pop;
 *   the last one lands with a «boom» and a short shake (the punchline), or with the sound `sfx` names
 *   (sad, ding, buzz, pop).
 * - Text boxes are fractions of the media (memegen's anchor_x / anchor_y / scale_x / scale_y), so a template's
 *   own layout is reused; the text shrinks until it fits its box.
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, Img, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {stagger} from '../anim';
import {PREROLL, Sfx, shake, uiZone, useFontsFor} from '../motion';
import type {SceneProps} from '../types';
import {lineCount} from './chat';
import {textWidth} from '../screen';

const THICK = 'Oswald, Impact, "Arial Narrow", sans-serif';
const THIN = 'Inter, Arial, sans-serif';

type MemeText = {text: string; x: number; y: number; w: number; h: number; angle: number; color: string; upper: boolean; thick: boolean; cue: number | null};

const readTexts = (raw: unknown): MemeText[] =>
  (Array.isArray(raw) ? raw : []).map((r: any) => {
    const thick = (r?.font ?? 'thick') !== 'thin';
    return {
      text: String(r?.text ?? ''),
      x: Number(r?.x ?? 0),
      y: Number(r?.y ?? 0),
      w: Number(r?.w ?? 1),
      h: Number(r?.h ?? 0.2),
      angle: Number(r?.angle ?? 0),
      color: String(r?.color ?? (thick ? 'white' : '#111111')),
      upper: (r?.style ?? (thick ? 'upper' : 'none')) === 'upper',
      thick,
      cue: typeof r?.cue === 'number' ? r.cue : null,
    };
  });

/** The largest font size (px) at which the text fits its box in at most 3 lines. */
const fitSize = (text: string, boxW: number, boxH: number, thick: boolean) => {
  const family = thick ? THICK : THIN;
  const weight = thick ? 700 : 600;
  const LH = thick ? 1.02 : 1.12;
  const words = text.split(/\s+/).filter(Boolean);
  let s = Math.min(boxH * 0.9, boxW * 0.22);
  while (s > 10) {
    const n = lineCount(text, weight, s, family, boxW * 0.92);
    const widest = Math.max(...words.map((w) => textWidth(w, weight, s, family)), 0);
    // no word broken in two, at most 3 lines, and room for the outline and the glyphs' descent
    if (n <= 3 && widest <= boxW * 0.92 && n * s * LH * 1.1 <= boxH) break;
    s -= 1;
  }
  return s;
};

export const Meme: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const u = Math.min(width, height) / 1080;
  const src = String(props.src ?? '');
  const isVideo = /\.(mp4|webm|mov)$/i.test(src);
  const [mw, mh] = Array.isArray(props.size) ? [Number(props.size[0]) || 1, Number(props.size[1]) || 1] : [1, 1];
  const texts = readTexts(props.texts).map((t) => ({...t, text: t.upper ? t.text.toUpperCase() : t.text}));
  const fontsReady = useFontsFor([`700 60px Oswald`, `600 40px Inter`], texts.map((t) => t.text).join(' '));
  // the punchline's sound: boom (with a shake) unless the storyboard picks another one
  const PUNCH = ['boom', 'sad', 'ding', 'buzz', 'pop'] as const;
  type Punch = (typeof PUNCH)[number];
  const punch: Punch = PUNCH.includes(props.sfx) ? props.sfx : props.boom === false ? 'pop' : 'boom';
  const boom = punch === 'boom';
  const zoom = props.zoom !== false;

  // geometry: the panel fills the UI band (fit by width, or by height for tall memes). The meme's own text does the
  // captions' job (set "captions": false on the beat), so in 9:16 it also takes the captions' place below the band;
  // `fit: "band"` keeps it to the band, e.g. on the last scene where the comment bubble takes that place
  const band = uiZone(width, height);
  const zone = height > width && props.fit !== 'band' ? {top: band.top, bottom: height * 0.75} : band;
  const border = 10 * u;
  const availW = width - 2 * 44 * u;
  const availH = (zone.bottom - zone.top) * 0.98;
  const scale = Math.min((availW - 2 * border) / mw, (availH - 2 * border) / mh);
  const dw = mw * scale;
  const dh = mh * scale;
  const left = (width - dw) / 2;
  const top = zone.top + (zone.bottom - zone.top - dh) / 2;

  // timing: each text on its cue, else spread over the first part of the beat
  const at = texts.map((t, i) => {
    const c = t.cue !== null ? cues[t.cue] : cues[i];
    return typeof c === 'number' ? Math.max(c - 3, 0) : stagger(i, texts.length, Math.max(speech, 6), duration, 0.6);
  });
  const last = at.length ? at[at.length - 1] : duration;

  const sizes = useMemo(
    () => texts.map((t) => fitSize(t.text, t.w * dw, t.h * dh, t.thick)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fontsReady, texts.map((t) => t.text).join('|'), dw, dh],
  );

  const enter = spring({frame: frame + PREROLL, fps, config: {damping: 16, stiffness: 150, mass: 0.7}});
  const push = zoom ? interpolate(frame, [0, Math.max(duration, 1)], [1, 1.07], {extrapolateRight: 'clamp'}) : 1;
  const sx = boom && texts.length ? shake(frame, last, 14 * u, 12) : 0;
  const sy = boom && texts.length ? shake(frame + 3, last + 3, 8 * u, 12) : 0;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute', left: left - border, top: top - border, width: dw + 2 * border, height: dh + 2 * border,
          background: '#ffffff', border: `${3 * u}px solid #111111`, boxSizing: 'border-box', borderRadius: 6 * u,
          boxShadow: `0 ${18 * u}px ${44 * u}px rgba(0,0,0,0.35)`, opacity: Math.min(enter * 1.5, 1),
          transform: `translate(${sx}px, ${sy}px) scale(${0.94 + 0.06 * enter})`,
        }}
      >
        <div style={{position: 'absolute', left: border - 3 * u, top: border - 3 * u, width: dw, height: dh, overflow: 'hidden'}}>
          <div style={{position: 'absolute', inset: 0, transform: `scale(${push})`, transformOrigin: '50% 45%'}}>
            {isVideo ? (
              <OffthreadVideo src={staticFile(src)} muted style={{width: dw, height: dh, objectFit: 'cover', display: 'block'}} />
            ) : (
              <Img src={staticFile(src)} style={{width: dw, height: dh, objectFit: 'cover', display: 'block'}} />
            )}
          </div>
          {/* the texts stay put while the picture pushes in, so a bottom line never slides out of the frame */}
          <div style={{position: 'absolute', inset: 0}}>
            {texts.map((t, i) => {
              const k = spring({frame: frame - at[i], fps, config: {damping: 11, stiffness: 210, mass: 0.6}});
              if (frame < at[i]) return null;
              const s = sizes[i];
              const o = Math.max(2, s * 0.075);
              const outline = t.thick
                ? [[-1, -1], [1, -1], [-1, 1], [1, 1], [0, -1.3], [0, 1.3], [-1.3, 0], [1.3, 0]]
                    .map(([a, b]) => `${a * o}px ${b * o}px 0 #000`).join(', ')
                : undefined;
              return (
                <div
                  key={i}
                  style={{
                    position: 'absolute', left: t.x * dw, top: t.y * dh, width: t.w * dw, height: t.h * dh,
                    display: 'flex', justifyContent: 'center', textAlign: 'center', boxSizing: 'border-box', padding: `${0.012 * dh}px 0`,
                    // top text hugs the top edge and bottom text the bottom edge, as in a classic meme
                    alignItems: !t.thick ? 'center' : t.y + t.h / 2 < 0.35 ? 'flex-start' : t.y + t.h / 2 > 0.65 ? 'flex-end' : 'center',
                    transform: `rotate(${t.angle}deg) scale(${1.35 - 0.35 * Math.min(k, 1.05)})`, opacity: Math.min(k * 2, 1),
                  }}
                >
                  <span
                    style={{
                      fontFamily: t.thick ? THICK : THIN, fontWeight: t.thick ? 700 : 600, fontSize: s,
                      lineHeight: t.thick ? 1.02 : 1.12, color: t.color, textShadow: outline,
                      letterSpacing: t.thick ? '0.01em' : 0, width: '94%',
                    }}
                  >
                    {t.text}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {texts.map((_, i) => (
        <Sfx key={`s${i}`} name={i === texts.length - 1 ? punch : 'pop'} at={at[i]} />
      ))}
    </AbsoluteFill>
  );
};
