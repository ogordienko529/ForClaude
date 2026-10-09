import React from 'react';
import {Composition} from 'remotion';
import {Gameplay} from './gameplay/Gameplay';
import {Thumbnail} from './Thumbnail';
import type {GameplayTimeline} from './gameplay/Gameplay';
import gameplaySample from './gameplay/sample-gameplay.json';
import sample from './sample-timeline.json';
import type {Timeline} from './types';
import {Video} from './Video';

const fromProps = ({props}: {props: any}) => ({
  durationInFrames: props.durationInFrames,
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Video"
      component={Video as any}
      defaultProps={sample as unknown as Timeline}
      durationInFrames={300}
      fps={30}
      width={1920}
      height={1080}
      calculateMetadata={fromProps}
    />
    <Composition
      id="Gameplay"
      component={Gameplay as any}
      defaultProps={gameplaySample as unknown as GameplayTimeline}
      durationInFrames={30}
      fps={30}
      width={1080}
      height={1920}
      calculateMetadata={fromProps}
    />
    <Composition
      id="Thumbnail"
      component={Thumbnail as any}
      defaultProps={{image: '', title: 'Sample *title*', tag: 'Review'}}
      durationInFrames={1}
      fps={30}
      width={1280}
      height={720}
    />
  </>
);
