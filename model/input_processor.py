import subprocess
import sys
import tempfile
from pathlib import Path


def convert_audio_to_midi(input_path: str) -> Path:
    input_path = Path(input_path)
    artifact_dir = Path(__file__).parent.parent / "artifact"
    artifact_dir.mkdir(exist_ok=True)

    output_midi = artifact_dir / input_path.with_suffix(".mid").name

    with tempfile.TemporaryDirectory() as tmp_dir:
        mono_wav = Path(tmp_dir) / "mono.wav"

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-ac", "1",
            "-ar", "44100",
            "-sample_fmt", "s16",
            str(mono_wav),
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)

        transkun_cmd = ["transkun", str(mono_wav), str(output_midi)]
        subprocess.run(transkun_cmd, check=True, capture_output=True)

    return output_midi


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python input_processor.py <audio_file>")
        sys.exit(1)

    result = convert_audio_to_midi(sys.argv[1])
    print(f"MIDI saved to: {result}")
