export type Scene = {
  id: string;
  template: string;
  props: Record<string, any>;
  from: number;
  durationInFrames: number;
  speechOffset: number;
  cues?: (number | null)[];
};

export type Caption = {from: number; to: number; text: string};

export type Timeline = {
  title: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  palette: string;
  format: string;
  audio: string;
  showCaptions: boolean;
  scenes: Scene[];
  captions: Caption[];
};

export type SceneProps = {
  props: Record<string, any>;
  duration: number;
  speech: number; // frame (relative to scene) where narration starts
  cues: (number | null)[]; // frames (relative to scene) where the storyboard's cue phrases are spoken
};
