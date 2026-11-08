const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const target = path.join(root, 'demo-public');
if (!fs.existsSync(path.join(target, 'demo/snapshot.json'))) {
  throw new Error('Missing public demo snapshot. See scripts/export-demo.py or the repository demo data.');
}
fs.mkdirSync(target, { recursive: true });
for (const name of ['land-50m.json', 'weather-mark.svg']) {
  fs.copyFileSync(path.join(root, 'weather-public', name), path.join(target, name));
}
fs.mkdirSync(path.join(target, 'geography'), { recursive: true });
for (const name of ['east-asia-relief.webp', 'east-asia-water.json', 'sources.json']) {
  fs.copyFileSync(path.join(root, 'weather-public/geography', name), path.join(target, 'geography', name));
}
