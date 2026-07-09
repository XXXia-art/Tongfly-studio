import DroneScratchExtension from '../src/extensions/droneScratchExtension.js';

const extension = new DroneScratchExtension();
const info = extension.getInfo();

if (info.id !== 'droneVLM') {
  throw new Error(`Unexpected extension id: ${info.id}`);
}

if (!Array.isArray(info.blocks) || info.blocks.length < 8) {
  throw new Error('Drone extension should expose the migrated block set.');
}

const requiredOpcodes = [
  'fly',
  'turn',
  'waitSeconds',
  'yoloDetect',
  'askVision',
  'chat',
  'createImage'
];

for (const opcode of requiredOpcodes) {
  if (!info.blocks.some(block => block.opcode === opcode)) {
    throw new Error(`Missing opcode: ${opcode}`);
  }
}

console.log(`drone extension ok: ${info.blocks.length} blocks`);
