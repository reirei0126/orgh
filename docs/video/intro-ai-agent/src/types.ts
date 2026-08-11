import scenesData from '../scenes.json';

export type Scene = (typeof scenesData.scenes)[number];

export type SceneProps = {
  scene: Scene;
};
