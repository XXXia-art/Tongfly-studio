import DroneScratchExtension from '../extensions/droneScratchExtension.js';

export function registerDroneExtension(vm, Scratch, services) {
  const extension = new DroneScratchExtension(Scratch, services);

  if (vm?.extensionManager?._registerInternalExtension) {
    return vm.extensionManager._registerInternalExtension(extension);
  }

  if (Scratch?.extensions?.register) {
    return Scratch.extensions.register(extension);
  }

  throw new Error('Cannot register drone extension: Scratch VM or Scratch extension host was not found.');
}
