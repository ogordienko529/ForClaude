/**
 * Motion shared by every scene: a slow camera drift (no frame is ever static), a pop with a small
 * bounce for stickers and stamps, the optional top progress bar, optional sound effects, and the
 * screen band that on-screen UI keeps to in 9:16 (captions sit below it).
 */
import React, {createContext, useContext, useEffect, useState} from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  random,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {usePalette} from './theme';

// the system's colour emoji (Windows, macOS, Linux); a bundled emoji webfont renders blank in headless Chrome
export const EMOJI_FONT = '"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif';
export const MONO_FONT = '"JetBrains Mono", "DejaVu Sans Mono", Consolas, monospace';

/**
 * Where on-screen UI goes. 9:16: below the platform's top bar (12 %) and above the captions, which sit
 * just above the title and buttons at the bottom (see CAPTION_LIFT); 16:9: clear of the captions.
 */
export const uiZone = (width: number, height: number) =>
  height > width ? {top: height * 0.12, bottom: height * 0.63} : {top: height * 0.065, bottom: height * 0.81};
/** Captions' bottom edge above the frame's bottom (fraction of the height): reviews clear the game's hotbar. */
export const CAPTION_LIFT: Record<string, number> = {review: 0.13};
/** 9:16: the captions' top edge, just under the UI band, so they sit between the UI and the platform's title. */
export const CAPTION_TOP: Record<string, number> = {shorts: 0.645};

/** Frames the scene content is already into its entrance on frame 0: the first frame is in motion. */
export const PREROLL = 6;

/** 0 -> 1 with a small overshoot (about 8 %): stickers, chips and bubbles that pop. */
export const pop = (frame: number, fps: number, start: number) =>
  spring({frame: frame - start, fps, config: {damping: 9, stiffness: 210, mass: 0.6}});

/** 0 -> 1 with a hard landing and a little recoil: stamps that slam onto a card. */
export const slam = (frame: number, fps: number, start: number) =>
  spring({frame: frame - start, fps, config: {damping: 13, stiffness: 420, mass: 0.7}});

/** A decaying shake (pixels) after `start`: a wrong answer, a 404, a stamp landing. */
export const shake = (frame: number, start: number, amp: number, frames = 16) => {
  const f = frame - start;
  if (f < 0 || f > frames) return 0;
  return Math.sin(f * 1.9) * amp * Math.exp(-f / (frames / 3.2));
};

/** A slow seeded camera drift: a few pixels of travel, a hair of rotation and a 1.5 % push-in. */
export const Drift: React.FC<{seed: string; duration: number; children: React.ReactNode}> = ({seed, duration, children}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const u = Math.min(width, height) / 1080;
  const a = random(`drift-a-${seed}`) * Math.PI * 2;
  const b = random(`drift-b-${seed}`) * Math.PI * 2;
  const t = frame / 30;
  const x = Math.sin(t * 0.55 + a) * 7 * u;
  const y = Math.cos(t * 0.43 + b) * 6 * u;
  const r = Math.sin(t * 0.31 + a + b) * 0.2;
  const z = 1 + 0.015 * Math.min(frame / Math.max(duration, 1), 1);
  return <AbsoluteFill style={{transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${z})`}}>{children}</AbsoluteFill>;
};

/** A thin accent bar along the top edge that fills over the whole video. */
export const ProgressBar: React.FC<{total: number}> = ({total}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  const h = 8 * u;
  const k = Math.min(Math.max(frame / Math.max(total - 1, 1), 0), 1);
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: '100%', height: h, background: 'rgba(0,0,0,0.28)'}}>
      <div
        style={{
          width: `${k * 100}%`,
          height: '100%',
          background: p.accent,
          borderRadius: `0 ${h / 2}px ${h / 2}px 0`,
          boxShadow: `0 0 ${12 * u}px ${p.accent}`,
        }}
      />
    </div>
  );
};

/**
 * «⏱ 0:29»: the seconds left, in a pill in the top-left corner under the progress bar. It pops in big on the
 * first frames (the promise «за 30 секунд»), settles small, and pulses in the last three seconds.
 */
export const Countdown: React.FC<{total: number}> = ({total}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  useFontsFor([`700 40px ${MONO_FONT}`, `400 40px ${EMOJI_FONT}`], '⏱0123456789:');
  const left = Math.max(Math.ceil((total - frame) / fps), 0);
  const label = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
  const k = spring({frame: frame - 2, fps, config: {damping: 12, stiffness: 180, mass: 0.6}});
  const settle = spring({frame: frame - 40, fps, config: {damping: 16, stiffness: 120}});
  const scale = (0.6 + 0.4 * Math.min(k, 1.1)) * (1.5 - 0.5 * Math.min(settle, 1));
  const tick = (total - frame) / fps < 3.2 ? 1 + 0.08 * Math.max(Math.sin(((frame % fps) / fps) * Math.PI), 0) : 1;
  const urgent = (total - frame) / fps < 3.2;
  return (
    <div style={{position: 'absolute', left: 40 * u, top: height * 0.045, transformOrigin: 'left top', transform: `scale(${scale * tick})`,
      opacity: Math.min(k * 2, 1), display: 'flex', alignItems: 'center', gap: 10 * u, padding: `${10 * u}px ${20 * u}px`, borderRadius: 40 * u,
      background: 'rgba(0,0,0,0.55)', border: `${3 * u}px solid ${urgent ? '#ef3b4f' : p.accent}`, boxShadow: `0 ${6 * u}px ${18 * u}px rgba(0,0,0,0.35)`}}>
      <span style={{fontFamily: EMOJI_FONT, fontSize: 34 * u, lineHeight: 1}}>⏱</span>
      <span style={{fontFamily: MONO_FONT, fontWeight: 700, fontSize: 36 * u, color: '#ffffff', letterSpacing: '0.02em'}}>{label}</span>
    </div>
  );
};

// ------------------------------------------------------------------ sound effects
export type SfxName = 'whoosh' | 'pop' | 'click' | 'keys' | 'impact' | 'ding' | 'buzz' | 'riser';
// linear gains: quiet under the voice (the voice mix keeps 3 dB of headroom for them, see `mix`)
// recorded CC0 sounds (content_agent/assets/sfx): loudness-matched, so the gains only set their place in the mix
const SFX_GAIN: Record<SfxName, number> = {whoosh: 0.32, pop: 0.38, click: 0.42, keys: 0.16, impact: 0.45, ding: 0.3, buzz: 0.26, riser: 0.22};
const SFX_FRAMES: Record<SfxName, number> = {whoosh: 18, pop: 4, click: 3, keys: 90, impact: 24, ding: 16, buzz: 17, riser: 66};
// the files of each sound (content_agent/assets/sfx and variants/) with the seconds from the start of the file to
// its sync point (the soft whoosh peaks 0.23 s in): each starts that much earlier. Events rotate through the
// variants so a Short does not repeat one whoosh at every cut.
const SFX_FILES: Record<SfxName, Array<[string, number]>> = {
  whoosh: [['whoosh', 0.229], ['whoosh_2', 0.096], ['whoosh_4', 0.233]],
  pop: [['pop', 0.011]],
  click: [['click', 0.009], ['click_2', 0.01], ['click_3', 0.002]],
  keys: [['keys', 0], ['keys_2', 0], ['keys_3', 0]],
  impact: [['impact', 0.018]],
  ding: [['ding', 0.003]],
  buzz: [['buzz', 0.003]],
  riser: [['riser', 1.98]], // peaks at its end: it lands on the action
};

/** The project folder with the sound files (timeline "sfx"), or null when sound effects are off. */
export const SfxContext = createContext<string | null>(null);

/** One sound effect `at` frames into the current sequence; `keys` loops for `dur` frames (typing). */
export const Sfx: React.FC<{name: SfxName; at: number; dur?: number; gain?: number}> = ({name, at, dur, gain = 1}) => {
  const dir = useContext(SfxContext);
  const {fps} = useVideoConfig();
  if (!dir || !Number.isFinite(at)) return null;
  const len = Math.max(Math.round(dur ?? SFX_FRAMES[name]), 1);
  const files = SFX_FILES[name];
  const [file, lead] = files[Math.abs(Math.round(at)) % files.length];
  return (
    <Sequence from={Math.max(Math.round(at - lead * fps), 0)} durationInFrames={len} layout="none" name={`sfx ${file}`}>
      <Audio src={staticFile(`${dir}/${file}.wav`)} volume={SFX_GAIN[name] * gain} loop={name === 'keys'} />
    </Sequence>
  );
};

// ------------------------------------------------------------------ fonts
/** Waits until these fonts are loaded for exactly these characters (Cyrillic and emoji subsets load on demand). */
export const useFontsFor = (loads: string[], text: string) => {
  const [handle] = useState(() => delayRender('Loading fonts for the scene'));
  const [ready, setReady] = useState(false);
  const key = loads.join('|');
  useEffect(() => {
    const sample = text || 'Aa';
    Promise.all(loads.map((f) => document.fonts.load(f, sample)))
      .catch(() => undefined)
      .then(() => setReady(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, text]);
  useEffect(() => {
    if (ready) continueRender(handle);
  }, [ready, handle]);
  return ready;
};

// ------------------------------------------------------------------ stickers
/**
 * An emoji sticker that pops in once with a small bounce (and a pop sound), then sways gently.
 * Positioned absolutely by `style` inside the caller's relative box.
 */
export const Sticker: React.FC<{emoji: string; at: number; size: number; tilt?: number; style?: React.CSSProperties}> = ({
  emoji,
  at,
  size,
  tilt = 10,
  style,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  useFontsFor([`400 ${Math.round(size)}px ${EMOJI_FONT}`], emoji);
  const k = pop(frame, fps, at);
  const sway = frame > at ? Math.sin((frame - at) / 11) * 4 * Math.min(k, 1) : 0;
  return (
    <>
      <div
        style={{
          position: 'absolute',
          fontFamily: EMOJI_FONT,
          fontSize: size,
          lineHeight: 1,
          opacity: frame < at ? 0 : Math.min(k * 2, 1),
          transform: `scale(${k}) rotate(${tilt + (1 - k) * -30 + sway}deg)`,
          filter: `drop-shadow(0 ${size * 0.06}px ${size * 0.1}px rgba(0,0,0,0.35))`,
          pointerEvents: 'none',
          ...style,
        }}
      >
        {emoji}
      </div>
      <Sfx name="pop" at={at} />
    </>
  );
};
