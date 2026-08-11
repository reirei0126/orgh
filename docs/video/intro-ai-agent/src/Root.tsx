import React from 'react';
import {Composition} from 'remotion';
import scenesData from '../scenes.json';
import {Main} from './Main';

const durationInFrames = Math.ceil(
  scenesData.scenes.reduce((total, scene) => total + scene.durationSec, 0) *
    scenesData.fps,
);

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Main"
    component={Main}
    durationInFrames={durationInFrames}
    fps={scenesData.fps}
    width={scenesData.width}
    height={scenesData.height}
  />
);
