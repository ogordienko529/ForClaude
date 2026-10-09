import '@fontsource/montserrat/800.css';
import '@fontsource/montserrat/900.css';
import React, {useEffect, useState} from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Easing,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

export type Clip = {
  id: string;
  kind: 'video' | 'still';
  src: string;
  from: number;
  durationInFrames: number;
  startFrom?: number;
  playbackRate?: number;
  zoom: number;
  zoomTo: number;
  punch: boolean;
  focus: [number, number];
  fx: string[];
  framing?: 'crop' | 'fit';
};
export type Txt = {text: string; style: string; from: number; to: number; target?: [number, number] | null};
export type Badge = {text: string; from: number; to: number};
export type GameplayTimeline = {
  kind: 'gameplay';
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  audio: string;
  framing: 'crop' | 'fit';
  srcWidth: number;
  srcHeight: number;
  progressBar: boolean;
  clips: Clip[];
  texts: Txt[];
  badges: Badge[];
};

const FONT = '"Montserrat", sans-serif';
const YELLOW = '#ffd21f';
// Shorts UI covers the bottom ~20% and a column of buttons on the right: keep text inside this box.
const SAFE = {left: 0.09, right: 0.88, top: 0.1, bottom: 0.72};
const ease = Easing.bezier(0.33, 0, 0.2, 1);

const useFont = () => {
  const [handle] = useState(() => delayRender('Loading Montserrat'));
  useEffect(() => {
    Promise.all([document.fonts.load('900 80px Montserrat'), document.fonts.load('800 40px Montserrat')])
      .catch(() => undefined)
      .then(() => continueRender(handle));
  }, [handle]);
};

/** One clip: the source framed for 9:16, with zoom, punch-in, shake, flash and black-and-white. */
const ClipView: React.FC<{clip: Clip; t: GameplayTimeline}> = ({clip, t}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const d = clip.durationInFrames;
  const fit = (clip.framing ?? t.framing) === 'fit';
  const base = fit ? W / t.srcWidth : H / t.srcHeight;
  const sw = t.srcWidth * base;
  const sh = t.srcHeight * base;
  let left = W / 2 - clip.focus[0] * sw;
  let top = fit ? (H - sh) / 2 : H / 2 - clip.focus[1] * sh;
  if (!fit) {
    left = Math.min(0, Math.max(W - sw, left)); // never show an edge of the source
    top = Math.min(0, Math.max(H - sh, top));
  }
  let z = interpolate(frame, [0, Math.max(d - 1, 1)], [clip.zoom, clip.zoomTo], {
    easing: ease,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  if (clip.punch) {
    const p = spring({frame, fps, config: {damping: 11, stiffness: 260, mass: 0.5}});
    z *= interpolate(p, [0, 1], [0.82, 1]);
  }
  const ox = left + clip.focus[0] * sw;
  const oy = top + clip.focus[1] * sh;
  let sx = 0;
  let sy = 0;
  let rot = 0;
  if (clip.fx.includes('shake')) {
    const a = 34 * Math.exp(-frame / 8);
    sx = a * Math.sin(frame * 2.9);
    sy = a * Math.cos(frame * 3.7);
    rot = 0.9 * Math.exp(-frame / 8) * Math.sin(frame * 2.1);
  }
  const bw = clip.fx.includes('bw');
  const media: React.CSSProperties = {position: 'absolute', left, top, width: sw, height: sh, maxWidth: 'none'};
  const flash = clip.fx.includes('flash')
    ? interpolate(frame, [0, 2, 10], [0.95, 0.8, 0], {extrapolateRight: 'clamp'})
    : 0;
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      {fit && clip.kind === 'video' ? (
        <OffthreadVideo
          src={staticFile(clip.src)}
          trimBefore={clip.startFrom}
          playbackRate={clip.playbackRate}
          muted
          style={{position: 'absolute', height: H, width: H * (t.srcWidth / t.srcHeight), left: (W - H * (t.srcWidth / t.srcHeight)) / 2,
            filter: 'blur(30px) brightness(0.55)', maxWidth: 'none'}}
        />
      ) : null}
      <AbsoluteFill
        style={{
          transform: `translate(${sx}px, ${sy}px) rotate(${rot}deg) scale(${z})`,
          transformOrigin: `${ox}px ${oy}px`,
          filter: bw ? 'grayscale(1) contrast(1.3) brightness(0.92)' : undefined,
        }}
      >
        {clip.kind === 'video' ? (
          <OffthreadVideo src={staticFile(clip.src)} trimBefore={clip.startFrom} playbackRate={clip.playbackRate} muted style={media} />
        ) : (
          <Img src={staticFile(clip.src)} style={media} />
        )}
      </AbsoluteFill>
      {bw ? <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.6) 100%)'}} /> : null}
      {flash > 0 ? <AbsoluteFill style={{backgroundColor: '#fff', opacity: flash}} /> : null}
    </AbsoluteFill>
  );
};

/** "*word*" -> highlighted word. */
const Words: React.FC<{text: string; color?: string}> = ({text, color = YELLOW}) => (
  <>
    {text.split(/(\*[^*]+\*)/).filter(Boolean).map((part, i) =>
      part.startsWith('*') ? (
        <span key={i} style={{color}}>{part.slice(1, -1)}</span>
      ) : (
        <span key={i}>{part}</span>
      ),
    )}
  </>
);

const STYLE: Record<string, {size: number; y: number; tilt: number}> = {
  hook: {size: 108, y: 0.18, tilt: -2},
  caption: {size: 92, y: 0.6, tilt: 0},
  big: {size: 200, y: 0.42, tilt: -4},
  label: {size: 66, y: 0.3, tilt: 0},
};

const TextView: React.FC<{txt: Txt}> = ({txt}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const st = STYLE[txt.style] || STYLE.caption;
  const pop = spring({frame, fps, config: {damping: 9, stiffness: 240, mass: 0.6}});
  const scale = interpolate(pop, [0, 1], [0.55, 1]);
  const jitter = txt.style === 'big' ? 6 * Math.exp(-frame / 6) * Math.sin(frame * 3.1) : 0;
  const boxW = (SAFE.right - SAFE.left) * W;
  let y = st.y * H;
  let arrow: React.ReactNode = null;
  if (txt.style === 'label' && txt.target) {
    const tx = txt.target[0] * W;
    const ty = txt.target[1] * H;
    y = Math.min(Math.max(ty - 0.17 * H, SAFE.top * H + 40), SAFE.bottom * H - 120);
    const grow = interpolate(frame, [3, 12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
    const x0 = W * (SAFE.left + SAFE.right) / 2;
    const y0 = y + 70;
    const ex = x0 + (tx - x0) * grow;
    const ey = y0 + (ty - 40 - y0) * grow;
    const ang = Math.atan2(ey - y0, ex - x0);
    const head = (s: number) => `${ex + 34 * Math.cos(ang + Math.PI - s)},${ey + 34 * Math.sin(ang + Math.PI - s)}`;
    arrow = (
      <svg width={W} height={H} style={{position: 'absolute', left: 0, top: 0}}>
        <g stroke="#000" strokeWidth={22} strokeLinecap="round" fill="none">
          <line x1={x0} y1={y0} x2={ex} y2={ey} />
          {grow > 0.9 ? <polyline points={`${head(0.5)} ${ex},${ey} ${head(-0.5)}`} strokeLinejoin="round" /> : null}
        </g>
        <g stroke={YELLOW} strokeWidth={11} strokeLinecap="round" fill="none">
          <line x1={x0} y1={y0} x2={ex} y2={ey} />
          {grow > 0.9 ? <polyline points={`${head(0.5)} ${ex},${ey} ${head(-0.5)}`} strokeLinejoin="round" /> : null}
        </g>
      </svg>
    );
  }
  return (
    <AbsoluteFill>
      {arrow}
      <div
        style={{
          position: 'absolute',
          left: SAFE.left * W,
          width: boxW,
          top: y,
          transform: `translate(${jitter}px, -50%) rotate(${st.tilt}deg) scale(${scale})`,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: st.size,
          lineHeight: 1.05,
          color: '#fff',
          textTransform: 'uppercase',
          WebkitTextStroke: `${Math.round(st.size * 0.16)}px #000`,
          paintOrder: 'stroke fill',
          textShadow: '0 8px 0 rgba(0,0,0,0.55)',
          letterSpacing: '-0.01em',
          textWrap: 'balance',
        }}
      >
        <Words text={txt.text} />
      </div>
    </AbsoluteFill>
  );
};

const BadgeView: React.FC<{badge: Badge}> = ({badge}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 12, stiffness: 200}});
  const blink = 0.75 + 0.25 * Math.sin(frame / 3);
  return (
    <div
      style={{
        position: 'absolute',
        left: SAFE.left * W,
        top: 0.075 * H,
        transform: `scale(${s})`,
        transformOrigin: 'left center',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '10px 26px 10px 20px',
        borderRadius: 18,
        background: 'rgba(0,0,0,0.62)',
        border: `4px solid ${YELLOW}`,
        fontFamily: FONT,
        fontWeight: 900,
        fontSize: 54,
        color: YELLOW,
      }}
    >
      <svg width={58} height={36} viewBox="0 0 58 36" style={{opacity: blink}}>
        <polygon points="0,0 28,18 0,36" fill={YELLOW} />
        <polygon points="28,0 56,18 28,36" fill={YELLOW} />
      </svg>
      {badge.text}
    </div>
  );
};

export const Gameplay: React.FC<GameplayTimeline> = (t) => {
  useFont();
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {t.clips.map((c) => (
        <Sequence key={c.id} from={c.from} durationInFrames={c.durationInFrames} name={c.id}>
          <ClipView clip={c} t={t} />
        </Sequence>
      ))}
      {t.badges.map((b, i) => (
        <Sequence key={`b${i}`} from={b.from} durationInFrames={Math.max(b.to - b.from, 1)}>
          <BadgeView badge={b} />
        </Sequence>
      ))}
      {t.texts.map((x, i) => (
        <Sequence key={`t${i}`} from={x.from} durationInFrames={Math.max(x.to - x.from, 1)}>
          <TextView txt={x} />
        </Sequence>
      ))}
      {t.progressBar ? (
        <div style={{position: 'absolute', left: 0, top: 0, height: 12, width: `${(100 * frame) / t.durationInFrames}%`, background: YELLOW}} />
      ) : null}
      {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
    </AbsoluteFill>
  );
};
