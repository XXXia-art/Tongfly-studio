const initialDroneState = {
  connected: true,
  altitude: 1,
  distance: 0,
  lateral: 0,
  yaw: 0,
  battery: 82,
  target: '起降垫',
  frameId: 0,
  flash: 0
};

const directionToType = {
  '向前': 'forward',
  '向后': 'backward',
  '向左': 'left',
  '向右': 'right',
  '向上': 'up',
  '向下': 'down'
};

class DroneBridgeMock {
  constructor() {
    this.state = {...initialDroneState};
    this.listeners = new Set();
    this.lastMissionFile = null;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    listener(this.getState());
    return () => this.listeners.delete(listener);
  }

  notify() {
    const snapshot = this.getState();
    this.listeners.forEach(listener => listener(snapshot));
  }

  getState() {
    return {...this.state, ...this.getFrameMeta()};
  }

  async connect() {
    this.state.connected = true;
    this.notify();
    return {ok: true, mode: 'mock'};
  }

  async sendMissionFile(missionFile) {
    this.lastMissionFile = {
      ...missionFile,
      receivedAt: new Date().toISOString(),
      route: 'web-editor -> onboard-chip -> flight-controller'
    };
    this.state.flash = 1;
    this.notify();
    return {
      ok: true,
      missionId: missionFile.id,
      bytes: new TextEncoder().encode(JSON.stringify(missionFile)).length,
      route: this.lastMissionFile.route
    };
  }

  disconnect() {
    this.state.connected = false;
    this.notify();
  }

  reset() {
    this.state = {...initialDroneState};
    this.notify();
  }

  getFrameMeta() {
    const target = this.state.altitude > 2.8
      ? '操场跑道'
      : this.state.distance > 5
        ? '蓝色圆环'
        : '起降垫';
    return {
      frameId: this.state.frameId,
      altitude: this.state.altitude,
      distance: this.state.distance,
      lateral: this.state.lateral,
      yaw: this.state.yaw,
      battery: this.state.battery,
      target,
      scene: target === '起降垫'
        ? '近处有起降垫和草地'
        : '前方有跑道标记和安全圆环',
      lighting: '晴天散射光'
    };
  }

  async runCommand(command) {
    const type = directionToType[command.direction] || command.type;
    const speed = Number(command.speed ?? command.params?.speed ?? 0);
    const seconds = Number(command.seconds ?? command.params?.seconds ?? 0);
    const distance = speed * seconds;

    switch (type) {
      case 'forward':
        this.state.distance += distance;
        this.state.battery -= Math.max(0.3, distance * 0.6);
        break;
      case 'backward':
        this.state.distance = Math.max(0, this.state.distance - distance);
        this.state.battery -= Math.max(0.3, distance * 0.6);
        break;
      case 'left':
        this.state.lateral -= distance;
        this.state.battery -= Math.max(0.2, distance * 0.45);
        break;
      case 'right':
        this.state.lateral += distance;
        this.state.battery -= Math.max(0.2, distance * 0.45);
        break;
      case 'up':
        this.state.altitude += distance;
        this.state.battery -= Math.max(0.3, distance * 0.7);
        break;
      case 'down':
        this.state.altitude = Math.max(0.2, this.state.altitude - distance);
        this.state.battery -= Math.max(0.2, distance * 0.5);
        break;
      case 'turn':
        this.state.yaw = ((this.state.yaw + distance) % 360 + 360) % 360;
        this.state.battery -= Math.max(0.2, Math.abs(distance) / 120);
        break;
      case 'wait':
        this.state.battery -= 0.2;
        break;
      default:
        break;
    }

    this.state.battery = Math.max(0, Math.min(100, this.state.battery));
    this.state.target = this.getFrameMeta().target;
    this.notify();
    return this.getFrameMeta();
  }

  tickFrame() {
    this.state.frameId += 1;
    this.state.flash = Math.max(0, this.state.flash - 0.08);
    this.notify();
  }
}

export const droneBridge = new DroneBridgeMock();
export {DroneBridgeMock};
