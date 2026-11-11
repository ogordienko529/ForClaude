import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, continueRender, delayRender, Sequence, staticFile} from 'remotion';
import {CAPTION_LIFT, CAPTION_TOP, Drift, ProgressBar, Sfx, SfxContext} from './motion';
import {Browser} from './templates/browser';
import {Chat} from './templates/chat';
import {Bars, Comparison, Stat, Timeline} from './templates/data';
import {Footage, Verdict} from './templates/footage';
import {MapPoint, MapRoute} from './templates/maps';
import {Phone} from './templates/phone';
import {Split} from './templates/split';
import {Terminal} from './templates/terminal';
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
  useFonts(st.fontLoads);
  return (
    <StyleContext.Provider value={st}>
      <PaletteContext.Provider value={st.palette}>
        <SfxContext.Provider value={t.sfx || null}>
          <AbsoluteFill style={{fontVariantNumeric: 'lining-nums', fontFeatureSettings: '"lnum" 1', ...styleVars(st)}}>
            <StyledBackground />
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
                    {NO_DRIFT.has(s.template) ? body : <Drift seed={s.id} duration={s.durationInFrames}>{body}</Drift>}
                  </StyledShell>
                </Sequence>
              );
            })}
            {/* a whoosh just ahead of every cut, so it peaks on the new picture */}
            {t.scenes.slice(1).map((s) => (
              <Sfx key={`w${s.id}`} name="whoosh" at={s.from - 5} />
            ))}
            {/* a soft hit under the hook on the very first frame (Shorts only) */}
            {t.format === 'shorts' && t.scenes.length ? <Sfx name="impact" at={2} /> : null}
            {/* 9:16 keeps the captions above the platform's title and buttons; reviews lift them above the hotbar */}
            {t.showCaptions && <StyledCaptions captions={t.captions} lift={CAPTION_LIFT[t.format] ?? 0.06} top={CAPTION_TOP[t.format]} />}
            {t.progressBar ? <ProgressBar total={t.durationInFrames} /> : null}
            {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
          </AbsoluteFill>
        </SfxContext.Provider>
      </PaletteContext.Provider>
    </StyleContext.Provider>
  );
};
