import React from 'react';
import {Composition} from 'remotion';
import sample from './sample-timeline.json';
import type {Timeline} from './types';
import {Video} from './Video';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Video"
    component={Video as any}
    defaultProps={sample as unknown as Timeline}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
    calculateMetadata={({props}: {props: any}) => ({
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
    })}
  />
);
