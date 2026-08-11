import React, {useState} from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {SceneProps} from './types';

const fontFamily = '"Hiragino Sans", "Noto Sans JP", system-ui, sans-serif';

export const SceneLayout: React.FC<SceneProps> = ({scene}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const [assetFailed, setAssetFailed] = useState(false);
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 110}});
  const opacity = interpolate(frame, [0, fps * 0.5], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: '#0B0E14', color: '#F5F7FA'}}>
      <div
        style={{
          position: 'absolute',
          left: 96,
          right: 96,
          top: 96,
          fontFamily,
          opacity,
          transform: `translateY(${interpolate(entrance, [0, 1], [28, 0])}px)`,
          textAlign: 'center',
        }}
      >
        <div style={{fontSize: 72, fontWeight: 700, lineHeight: 1.25}}>
          {scene.onScreenText.headline}
        </div>
        <div
          style={{
            color: '#8891A5',
            fontSize: 36,
            lineHeight: 1.4,
            marginTop: 20,
          }}
        >
          {scene.onScreenText.sub}
        </div>
      </div>

      <div
        style={{
          alignItems: 'center',
          display: 'flex',
          justifyContent: 'center',
          left: 240,
          opacity,
          position: 'absolute',
          right: 240,
          top: 300,
          bottom: 250,
          transform: `scale(${interpolate(entrance, [0, 1], [0.94, 1])})`,
        }}
      >
        {!assetFailed ? (
          <Img
            src={staticFile(scene.asset)}
            onError={() => setAssetFailed(true)}
            style={{height: '100%', maxWidth: '100%', objectFit: 'contain'}}
          />
        ) : (
          <div
            aria-label={`${scene.id} asset placeholder`}
            style={{
              backgroundColor: '#151A24',
              border: '4px solid #2A3242',
              borderRadius: 24,
              height: '80%',
              width: '70%',
            }}
          />
        )}
      </div>

      <div
        style={{
          backgroundColor: '#151A24',
          border: '2px solid #2A3242',
          borderRadius: 20,
          bottom: 96,
          boxSizing: 'border-box',
          fontFamily,
          fontSize: 36,
          left: 96,
          lineHeight: 1.4,
          opacity,
          padding: '22px 32px',
          position: 'absolute',
          right: 96,
          textAlign: 'center',
        }}
      >
        {scene.narration}
      </div>
    </AbsoluteFill>
  );
};
