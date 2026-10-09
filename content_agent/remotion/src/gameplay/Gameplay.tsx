import '@fontsource/archivo-black/400.css';
import '@fontsource/bangers/400.css';
import '@fontsource/montserrat/800.css';
import '@fontsource/montserrat/900.css';
import '@fontsource/orbitron/800.css';
import '@fontsource/pixelify-sans/700.css';
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
  random,
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
  transition?: string | null; // cut | zoomblur | pixel | flash | glitch | whip (default: the style's)
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
  style?: string; // meme | boxed | pixel | comic | neon | clean
  clips: Clip[];
  texts: Txt[];
  badges: Badge[];
};

type ShortStyle = {font: string; weight: number; accent: string; accent2: string; cut: string; loads: string[]};

/** Text and cut styles for Shorts. One per video keeps it consistent; vary between videos or series. */
export const SHORT_STYLES: Record<string, ShortStyle> = {
  meme: {font: '"Montserrat", sans-serif', weight: 900, accent: '#ffd21f', accent2: '#ffffff', cut: 'cut', loads: ['900 80px Montserrat']},
  boxed: {font: '"Archivo Black", sans-serif', weight: 400, accent: '#ffd21f', accent2: '#ff4d6d', cut: 'zoomblur', loads: ['400 80px "Archivo Black"']},
  pixel: {font: '"Pixelify Sans", monospace', weight: 700, accent: '#ffff55', accent2: '#55ff55', cut: 'pixel', loads: ['700 80px "Pixelify Sans"']},
  comic: {font: 'Bangers, Impact, sans-serif', weight: 400, accent: '#e8242b', accent2: '#ffd84a', cut: 'flash', loads: ['400 80px Bangers']},
  neon: {font: 'Orbitron, sans-serif', weight: 800, accent: '#ff3dbb', accent2: '#2de2e6', cut: 'glitch', loads: ['800 80px Orbitron']},
  clean: {font: '"Archivo Black", sans-serif', weight: 400, accent: '#ff5a1f', accent2: '#111111', cut: 'whip', loads: ['400 80px "Archivo Black"']},
};
const ShortStyleCtx = React.createContext<ShortStyle>(SHORT_STYLES.meme);
const useShortStyle = () => React.useContext(ShortStyleCtx);
// Shorts UI covers the bottom ~20% and a column of buttons on the right: keep text inside this box.
const SAFE = {left: 0.09, right: 0.88, top: 0.1, bottom: 0.72};
const ease = Easing.bezier(0.33, 0, 0.2, 1);

const useFont = (loads: string[]) => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  useEffect(() => {
    Promise.all(loads.map((f) => document.fonts.load(f)))
      .catch(() => undefined)
      .then(() => continueRender(handle));
  }, [handle, loads]);
};

/** The first frames after a cut, in the style of the video. */
const cutEffect = (kind: string, frame: number) => {
  const k = Math.max(0, 1 - frame / 6); // 1 at the cut -> 0 after 6 frames
  if (k <= 0 || kind === 'cut') return {transform: '', filter: '', flash: 0, blocks: 0};
  switch (kind) {
    case 'zoomblur': return {transform: `scale(${1 + 0.18 * k})`, filter: `blur(${10 * k}px)`, flash: 0, blocks: 0};
    case 'flash': return {transform: '', filter: '', flash: 0.85 * k, blocks: 0};
    case 'glitch': return {transform: `translateX(${(random(`g${frame}`) - 0.5) * 60 * k}px)`,
      filter: `drop-shadow(${10 * k}px 0 rgba(255,40,140,0.9)) drop-shadow(${-10 * k}px 0 rgba(40,230,255,0.9))`, flash: 0, blocks: 0};
    case 'whip': return {transform: `translateX(${35 * k}%)`, filter: `blur(${12 * k}px)`, flash: 0, blocks: 0};
    case 'pixel': return {transform: '', filter: '', flash: 0, blocks: k};
    default: return {transform: '', filter: '', flash: 0, blocks: 0};
  }
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
  const ss = useShortStyle();
  const cut = cutEffect(clip.from === 0 || clip.kind === 'still' ? 'cut' : clip.transition || ss.cut, frame);
  const flash = Math.max(clip.fx.includes('flash')
    ? interpolate(frame, [0, 2, 10], [0.95, 0.8, 0], {extrapolateRight: 'clamp'})
    : 0, cut.flash);
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden', transform: cut.transform || undefined, filter: cut.filter || undefined}}>
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
      {cut.blocks > 0
        ? Array.from({length: 12 * 21}, (_, i) =>
            random(`b${i}`) < cut.blocks ? (
              <div key={i} style={{position: 'absolute', left: `${(i % 12) * (100 / 12)}%`, top: `${Math.floor(i / 12) * (100 / 21)}%`,
                width: `${100 / 12 + 0.2}%`, height: `${100 / 21 + 0.2}%`, background: '#000'}} />
            ) : null,
          )
        : null}
    </AbsoluteFill>
  );
};

/** "*word*" -> highlighted word. */
const Words: React.FC<{text: string; color: string}> = ({text, color}) => (
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

const parts = (text: string) => {
  const words = text.split(/(\*[^*]+\*)/).filter(Boolean).flatMap((part) =>
    part.startsWith('*') ? part.slice(1, -1).split(' ').map((w) => ({w, hi: true})) : part.trim().split(/\s+/).filter(Boolean).map((w) => ({w, hi: false})),
  );
  // punctuation stays with the word before it ("TNT?" not "TNT" + "?")
  return words.reduce<{w: string; hi: boolean}[]>((acc, x) => {
    if (acc.length && /^[^\p{L}\p{N}]+$/u.test(x.w)) acc[acc.length - 1] = {...acc[acc.length - 1], w: acc[acc.length - 1].w + x.w};
    else acc.push(x);
    return acc;
  }, []);
};

const TextView: React.FC<{txt: Txt; kind: string}> = ({txt, kind}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const ss = useShortStyle();
  const st = STYLE[txt.style] || STYLE.caption;
  const pop = spring({frame, fps, config: {damping: 9, stiffness: 240, mass: 0.6}});
  const scale = interpolate(pop, [0, 1], [0.55, 1]);
  const jitter = txt.style === 'big' ? 6 * Math.exp(-frame / 6) * Math.sin(frame * 3.1) : 0;
  const boxW = (SAFE.right - SAFE.left) * W;
  let y = st.y * H;
  let arrow: React.ReactNode = null;
  const arrowColor = kind === 'clean' ? ss.accent : kind === 'neon' ? ss.accent2 : ss.accent;
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
    const head = (a: number) => `${ex + 34 * Math.cos(ang + Math.PI - a)},${ey + 34 * Math.sin(ang + Math.PI - a)}`;
    const pixelCap = kind === 'pixel' ? 'butt' : 'round';
    arrow = (
      <svg width={W} height={H} style={{position: 'absolute', left: 0, top: 0}}>
        <g stroke="#000" strokeWidth={22} strokeLinecap={pixelCap} fill="none">
          <line x1={x0} y1={y0} x2={ex} y2={ey} />
          {grow > 0.9 ? <polyline points={`${head(0.5)} ${ex},${ey} ${head(-0.5)}`} strokeLinejoin="round" /> : null}
        </g>
        <g stroke={arrowColor} strokeWidth={11} strokeLinecap={pixelCap} fill="none">
          <line x1={x0} y1={y0} x2={ex} y2={ey} />
          {grow > 0.9 ? <polyline points={`${head(0.5)} ${ex},${ey} ${head(-0.5)}`} strokeLinejoin="round" /> : null}
        </g>
      </svg>
    );
  }
  const big = txt.style === 'big';
  const size = st.size * (({comic: 1.12, neon: 0.86, boxed: 0.82, clean: 0.92, pixel: 1.12} as Record<string, number>)[kind] ?? 1);
  const box: React.CSSProperties = {
    position: 'absolute', left: SAFE.left * W, width: boxW, top: y, textAlign: 'center', lineHeight: 1.08,
    transform: `translate(${jitter}px, -50%) rotate(${st.tilt}deg) scale(${scale})`, fontFamily: ss.font, fontWeight: ss.weight,
    fontSize: size, textTransform: 'uppercase', textWrap: 'balance',
  };
  let body: React.ReactNode;
  switch (kind) {
    case 'boxed':
      // every word on its own box, popping in one after another
      body = (
        <div style={box}>
          {parts(txt.text).map((x, i) => {
            const pw = spring({frame: frame - i * 2, fps, config: {damping: 10, stiffness: 260, mass: 0.5}});
            return (
              <span key={i} style={{display: 'inline-block', margin: '0.06em 0.08em', padding: '0.06em 0.22em', borderRadius: '0.12em',
                background: x.hi ? ss.accent : big ? ss.accent2 : '#fff', color: '#111', transform: `scale(${pw}) rotate(${i % 2 ? 2 : -2}deg)`,
                boxShadow: '0 0.08em 0 rgba(0,0,0,0.4)'}}>
                {x.w}
              </span>
            );
          })}
        </div>
      );
      break;
    case 'pixel': {
      const inner = (
        <span style={{color: big ? ss.accent2 : '#fff', textShadow: '0.09em 0.09em 0 #3f3f3f', textTransform: 'none'}}>
          <Words text={txt.text} color={ss.accent} />
        </span>
      );
      body = (
        <div style={box}>
          {txt.style === 'caption' || txt.style === 'label' ? (
            <span style={{display: 'inline-block', padding: '0.18em 0.4em', background: 'rgba(16,0,16,0.92)', border: '0.06em solid #100010',
              boxShadow: 'inset 0 0 0 0.05em #2d0a6b'}}>{inner}</span>
          ) : inner}
        </div>
      );
      break;
    }
    case 'comic':
      body = big ? (
        <div style={{...box, color: ss.accent2, WebkitTextStroke: `${Math.round(size * 0.07)}px #111`, paintOrder: 'stroke fill',
          textShadow: `0.06em 0.06em 0 ${ss.accent}`, letterSpacing: '0.03em', transform: `${box.transform} rotate(-4deg)`}}>
          <Words text={txt.text} color={ss.accent} />
        </div>
      ) : (
        <div style={box}>
          <span style={{display: 'inline-block', position: 'relative', background: '#fff', color: '#111', border: '0.06em solid #111',
            borderRadius: '0.35em', padding: '0.12em 0.4em', boxShadow: '0.09em 0.09em 0 #111', letterSpacing: '0.03em'}}>
            <Words text={txt.text} color={ss.accent} />
          </span>
        </div>
      );
      break;
    case 'neon':
      body = (
        <div style={{...box, color: '#fff', textShadow: `0 0 0.12em ${ss.accent}, 0 0 0.35em ${ss.accent}, 0 0.05em 0.1em #000`, letterSpacing: '0.04em'}}>
          <span style={{color: '#fff'}}>
            {parts(txt.text).map((x, i) => (
              <span key={i} style={x.hi ? {color: ss.accent2, textShadow: `0 0 0.12em ${ss.accent2}, 0 0 0.35em ${ss.accent2}`} : undefined}>{x.w} </span>
            ))}
          </span>
        </div>
      );
      break;
    case 'clean':
      body = (
        <div style={box}>
          <span style={{display: 'inline-block', background: big ? ss.accent : '#fff', color: big ? '#fff' : '#111', borderRadius: '0.28em',
            padding: '0.14em 0.45em', boxShadow: '0 0.1em 0.3em rgba(0,0,0,0.25)', textTransform: 'none'}}>
            <Words text={txt.text} color={big ? '#111' : ss.accent} />
          </span>
        </div>
      );
      break;
    default:
      body = (
        <div style={{...box, color: '#fff', WebkitTextStroke: `${Math.round(size * 0.16)}px #000`, paintOrder: 'stroke fill',
          textShadow: '0 8px 0 rgba(0,0,0,0.55)', letterSpacing: '-0.01em', lineHeight: 1.05}}>
          <Words text={txt.text} color={ss.accent} />
        </div>
      );
  }
  return (
    <AbsoluteFill>
      {arrow}
      {body}
    </AbsoluteFill>
  );
};

const BadgeView: React.FC<{badge: Badge}> = ({badge}) => {
  const frame = useCurrentFrame();
  const ss = useShortStyle();
  const YELLOW = ss.accent;
  const FONT = ss.font;
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
        fontWeight: ss.weight,
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
  const kind = t.style && SHORT_STYLES[t.style] ? t.style : 'meme';
  const ss = SHORT_STYLES[kind];
  useFont(ss.loads);
  const frame = useCurrentFrame();
  return (
    <ShortStyleCtx.Provider value={ss}>
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
          <TextView txt={x} kind={kind} />
        </Sequence>
      ))}
      {t.progressBar ? (
        <div style={{position: 'absolute', left: 0, top: 0, height: 12, width: `${(100 * frame) / t.durationInFrames}%`, background: ss.accent}} />
      ) : null}
      {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
    </AbsoluteFill>
    </ShortStyleCtx.Provider>
  );
};
