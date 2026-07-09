from pathlib import Path
import urllib.request


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
TARGET = Path(__file__).resolve().parents[1] / "models" / "hand_landmarker.task"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists() and TARGET.stat().st_size > 1_000_000:
        print(f"Model already exists: {TARGET}")
        return
    print(f"Downloading MediaPipe hand model to {TARGET} ...")
    urllib.request.urlretrieve(MODEL_URL, TARGET)
    print(f"Done ({TARGET.stat().st_size / 1_000_000:.1f} MB).")


if __name__ == "__main__":
    main()
