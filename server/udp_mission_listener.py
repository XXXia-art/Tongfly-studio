import json
import os
import socket
from datetime import datetime
from pathlib import Path


HOST = os.environ.get("TONGFLY_MISSION_LISTEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("TONGFLY_MISSION_UDP_PORT", "9000"))
MISSION_DIR = Path(os.environ.get("TONGFLY_MISSION_DIR", Path(__file__).parent / "missions"))
MISSION_DIR.mkdir(parents=True, exist_ok=True)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"mission UDP listener on {HOST}:{PORT}", flush=True)

    while True:
        data, addr = sock.recvfrom(1024 * 1024)
        try:
            mission = json.loads(data.decode("utf-8"))
            mission_id = mission.get("id") or datetime.now().strftime("%Y%m%d_%H%M%S")
            path = MISSION_DIR / f"{mission_id}.json"
            path.write_text(
                json.dumps(mission, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            actions = len(mission.get("flightActions", []))
            print(f"received mission {mission_id} from {addr}: {actions} actions -> {path}", flush=True)
        except Exception as exc:
            print(f"failed to receive mission from {addr}: {exc}", flush=True)


if __name__ == "__main__":
    main()
