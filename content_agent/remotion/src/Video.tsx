import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, continueRender, delayRender, Sequence, staticFile} from 'remotion';
import {Bars, Comparison, Stat, Timeline} from './templates/data';
import {Footage, Verdict} from './templates/footage';
import {MapPoint, MapRoute} from './templates/maps';
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
};

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
        <AbsoluteFill style={{fontVariantNumeric: 'lining-nums', fontFeatureSettings: '"lnum" 1', ...styleVars(st)}}>
          <StyledBackground />
          {t.scenes.map((s) => {
            const C = TEMPLATES[s.template];
            return (
              <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} name={`${s.id} ${s.template}`}>
                <StyledShell duration={s.durationInFrames} transition={s.transition}>
                  {C ? (
                    <C props={s.props} duration={s.durationInFrames} speech={s.speechOffset} cues={s.cues || []} />
                  ) : (
                    <Missing props={s.props} duration={s.durationInFrames} speech={0} cues={[]} name={s.template} />
                  )}
                </StyledShell>
              </Sequence>
            );
          })}
          {/* gameplay footage has a hotbar at the bottom: reviews lift the captions above it */}
          {t.showCaptions && <StyledCaptions captions={t.captions} lift={t.format === 'review' ? 0.13 : 0.06} />}
          {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
        </AbsoluteFill>
      </PaletteContext.Provider>
    </StyleContext.Provider>
  );
};
