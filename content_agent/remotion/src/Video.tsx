import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, continueRender, delayRender, Sequence, staticFile} from 'remotion';
import {BAND_BOTTOM, BAND_SHIFT, BandContext, CAPTION_LIFT, CAPTION_TOP, CommentSticker, Drift, ProgressBar, Sfx, SfxContext, TopBand} from './motion';
import {Browser} from './templates/browser';
import {Chat} from './templates/chat';
import {Connect, Context, Flashcards, Loop, Tokens, Webpage} from './templates/explain';
import {Bars, Comparison, Stat, Timeline} from './templates/data';
import {Footage, Verdict} from './templates/footage';
import {MapPoint, MapRoute} from './templates/maps';
import {Phone} from './templates/phone';
import {Split} from './templates/split';
import {Terminal} from './templates/terminal';
import {TgPost} from './templates/tgpost';
import {FactCard, Kinetic, ListCard, TitleCard} from './templates/text';
import {STYLES, StyleContext, StyledBackground, StyledCaptions, StyledShell, styleVars} from './styles';
import type {StyleDef} from './styles';
import {PALETTES, PaletteContext} from './theme';
import type {SceneProps, Timeline as TimelineData} from './types';

export const TEMPLATES: Record<string, React.FC<SceneProps>> = {
  title: TitleCard,
  kinetic: Kinetic,
  fact: FactCard,
  list: ListCard,
  stat: Stat,
  comparison: Comparison,
  bars: Bars,
  timeline: Timeline,
  map_route: MapRoute,
  map_point: MapPoint,
  footage: Footage,
  verdict: Verdict,
  chat: Chat,
  phone: Phone,
  terminal: Terminal,
  browser: Browser,
  split: Split,
  connect: Connect,
  loop: Loop,
  tokens: Tokens,
  context: Context,
  webpage: Webpage,
  flashcards: Flashcards,
  tgpost: TgPost,
};

const SHORTS_SAFE: React.CSSProperties = {transform: 'scale(0.9)', transformOrigin: '0% 12%'};
// with a handle line the top band has two rows: the scenes move down to clear it (and still end above the captions)
const shortsSafe = (t: TimelineData): React.CSSProperties =>
  t.handle ? {...SHORTS_SAFE, transform: `translateY(${t.height * BAND_SHIFT}px) scale(0.9)`} : SHORTS_SAFE;

const bandMask = (height: number): React.CSSProperties => {
  const edge = height * BAND_BOTTOM;
  const m = `linear-gradient(to bottom, transparent ${edge - 0.014 * height}px, #000 ${edge}px)`;
  return {maskImage: m, WebkitMaskImage: m};
};

// footage moves on its own (and a drift would show the edge of the clip)
const NO_DRIFT = new Set(['footage']);

const useFonts = (loads: string[]) => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  useEffect(() => {
    // the sample text makes unicode-range fonts (Pixel Digits) load too
    Promise.all(loads.map((f) => document.fonts.load(f, 'Aa0123456789')))
      .catch(() => undefined)
      .then(() => continueRender(handle));
  }, [handle, loads]);
};

/** The timeline's style; old timelines without one keep the cosmos look with their palette. */
const pickStyle = (t: TimelineData): StyleDef => {
  if (t.style && STYLES[t.style]) return STYLES[t.style];
  return {...STYLES.cosmos, palette: PALETTES[t.palette] || PALETTES.midnight};
};

const Missing: React.FC<SceneProps & {name: string}> = ({name}) => (
  <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', color: 'red', fontSize: 60}}>
    Unknown template: {name}
  </AbsoluteFill>
);

export const Video: React.FC<TimelineData> = (t) => {
  const st = pickStyle(t);
  const banded = t.format === 'shorts' && !!t.handle;
  useFonts(st.fontLoads);
  return (
    <StyleContext.Provider value={st}>
      <PaletteContext.Provider value={st.palette}>
        <SfxContext.Provider value={t.sfx || null}>
          <AbsoluteFill style={{fontVariantNumeric: 'lining-nums', fontFeatureSettings: '"lnum" 1', ...styleVars(st)}}>
            <StyledBackground />
            <BandContext.Provider value={banded}>
            {/* with a handle row, nothing of a scene shows under the top band: it fades out just above the band's edge */}
            <AbsoluteFill style={banded ? bandMask(t.height) : undefined}>
            {t.scenes.map((s, i) => {
              const C = TEMPLATES[s.template];
              const body = C ? (
                <C props={s.props} duration={s.durationInFrames} speech={s.speechOffset} cues={s.cues || []} marks={s.marks || {}} />
              ) : (
                <Missing props={s.props} duration={s.durationInFrames} speech={0} cues={[]} name={s.template} />
              );
              return (
                <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} name={`${s.id} ${s.template}`}>
                  {/* the first scene has no transition in: the video opens on a picture already in motion */}
                  <StyledShell duration={s.durationInFrames} transition={s.transition} intro={i > 0}>
                    {/* 9:16: the scene sits 10 % smaller and off the right edge, clear of the like/comment/share
                        column TikTok, Reels and Shorts draw on the right */}
                    <AbsoluteFill style={t.format === 'shorts' ? shortsSafe(t) : undefined}>
                      {NO_DRIFT.has(s.template) ? body : <Drift seed={s.id} duration={s.durationInFrames}>{body}</Drift>}
                    </AbsoluteFill>
                  </StyledShell>
                </Sequence>
              );
            })}
            </AbsoluteFill>
            </BandContext.Provider>
            {/* a whoosh just ahead of every cut, so it peaks on the new picture */}
            {t.scenes.slice(1).map((s) => (
              <Sfx key={`w${s.id}`} name="whoosh" at={s.from - 5} />
            ))}
            {/* a soft hit under the hook on the very first frame (Shorts only) */}
            {t.format === 'shorts' && t.scenes.length ? <Sfx name="impact" at={2} /> : null}
            {/* 9:16 keeps the captions above the platform's title and buttons; reviews lift them above the hotbar */}
            {t.showCaptions && <StyledCaptions captions={t.captions} lift={CAPTION_LIFT[t.format] ?? 0.06} top={CAPTION_TOP[t.format]} />}
            {t.progressBar ? <ProgressBar total={t.durationInFrames} /> : null}
            {/* the ending task over the last scene: «💬 Що відповів твій чат?» */}
            {t.comment && t.scenes.length ? (
              <CommentSticker text={t.comment} at={t.scenes[t.scenes.length - 1].from + Math.round(0.35 * t.fps)}
                low={!t.showCaptions || !t.captions.some((c) => c.from >= t.scenes[t.scenes.length - 1].from)} />
            ) : null}
            {t.countdown || t.series || t.handle ? (
              <TopBand total={t.durationInFrames} countdown={t.countdown} series={t.series} handle={t.handle} />
            ) : null}
            {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
          </AbsoluteFill>
        </SfxContext.Provider>
      </PaletteContext.Provider>
    </StyleContext.Provider>
  );
};
