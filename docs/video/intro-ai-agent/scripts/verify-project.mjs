import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scenesData = JSON.parse(
  await readFile(path.join(projectRoot, 'scenes.json'), 'utf8'),
);

const sceneFiles = (await readdir(path.join(projectRoot, 'src', 'scenes')))
  .filter((file) => /^S\d{2}\.tsx$/.test(file))
  .sort();
const expectedSceneFiles = scenesData.scenes
  .map(({id}) => `${id[0].toUpperCase()}${id.slice(1)}.tsx`)
  .sort();

assert.deepEqual(
  sceneFiles,
  expectedSceneFiles,
  'scene component files must match scenes.json IDs',
);

const packageJson = JSON.parse(
  await readFile(path.join(projectRoot, 'package.json'), 'utf8'),
);
assert.equal(packageJson.scripts.build, 'tsc --noEmit');
assert.equal(
  packageJson.scripts.render,
  'remotion render src/index.ts Main out/intro-ai-agent.mp4',
);
for (const dependency of [
  'remotion',
  '@remotion/cli',
  'react',
  'react-dom',
  'typescript',
]) {
  assert.ok(
    packageJson.dependencies?.[dependency],
    `package.json must include ${dependency} in dependencies`,
  );
}

for (const sourceFile of ['src/Root.tsx', 'src/Main.tsx']) {
  const source = await readFile(path.join(projectRoot, sourceFile), 'utf8');
  assert.doesNotMatch(
    source,
    /(1920|1080|:\s*30)/,
    `${sourceFile} must derive video dimensions and fps from scenes.json`,
  );
}

console.log(`Verified ${sceneFiles.length} scene components.`);
