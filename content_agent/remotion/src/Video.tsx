import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, continueRender, delayRender, Sequence, staticFile} from 'remotion';
import {Bars, Comparison, Stat, Timeline} from './templates/data';
import {Footage, Verdict} from './templates/footage';
import {MapPoint, MapRoute} from './templates/maps';
import {FactCard, Kinetic, ListCard, TitleCard} from './templates/text';
import {PALETTES, PaletteContext} from './theme';
import type {SceneProps, Timeline as TimelineData} from './types';
import {Background, Captions, SceneShell} from './ui';

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

const useFonts = () => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  useEffect(() => {
    Promise.all([
      document.fonts.load('700 80px "Playfair Display"'),
      document.fonts.load('400 40px Inter'),
      document.fonts.load('600 40px Inter'),
      document.fonts.load('800 40px Inter'),
    ])
      .catch(() => undefined)
      .then(() => continueRender(handle));
  }, [handle]);
};

const Missing: React.FC<SceneProps & {name: string}> = ({name}) => (
  <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', color: 'red', fontSize: 60}}>
    Unknown template: {name}
  </AbsoluteFill>
);

export const Video: React.FC<TimelineData> = (t) => {
  useFonts();
  const palette = PALETTES[t.palette] || PALETTES.midnight;
  return (
    <PaletteContext.Provider value={palette}>
      <AbsoluteFill style={{fontVariantNumeric: 'lining-nums', fontFeatureSettings: '"lnum" 1'}}>
        <Background />
        {t.scenes.map((s) => {
          const C = TEMPLATES[s.template];
          return (
            <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} name={`${s.id} ${s.template}`}>
              <SceneShell duration={s.durationInFrames}>
                {C ? (
                  <C props={s.props} duration={s.durationInFrames} speech={s.speechOffset} cues={s.cues || []} />
                ) : (
                  <Missing props={s.props} duration={s.durationInFrames} speech={0} cues={[]} name={s.template} />
                )}
              </SceneShell>
            </Sequence>
          );
        })}
        {/* gameplay footage has a hotbar at the bottom: reviews lift the captions above it */}
        {t.showCaptions && <Captions captions={t.captions} lift={t.format === 'review' ? 0.13 : 0.06} />}
        {t.audio ? <Audio src={staticFile(t.audio)} /> : null}
      </AbsoluteFill>
    </PaletteContext.Provider>
  );
};
