import React from 'react';
import {AbsoluteFill, Series} from 'remotion';
import scenesData from '../scenes.json';
import {S01} from './scenes/S01';
import {S02} from './scenes/S02';
import {S03} from './scenes/S03';
import {S04} from './scenes/S04';
import {S05} from './scenes/S05';
import {S06} from './scenes/S06';
import {S07} from './scenes/S07';
import type {SceneProps} from './types';

const sceneComponents: Record<string, React.ComponentType<SceneProps>> = {
  s01: S01,
  s02: S02,
  s03: S03,
  s04: S04,
  s05: S05,
  s06: S06,
  s07: S07,
};

export const Main: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: '#0B0E14'}}>
    <Series>
      {scenesData.scenes.map((scene) => {
        const SceneComponent = sceneComponents[scene.id];
        if (!SceneComponent) {
          throw new Error(`Scene component not found: ${scene.id}`);
        }

        return (
          <Series.Sequence
            key={scene.id}
            durationInFrames={Math.ceil(scene.durationSec * scenesData.fps)}
          >
            <SceneComponent scene={scene} />
          </Series.Sequence>
        );
      })}
    </Series>
  </AbsoluteFill>
);
