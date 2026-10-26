"""Original BUGG notification tones, synthesized here without third-party audio."""
import math
from pathlib import Path
import struct
import wave


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    rate = 24000
    melodies = {
        'friend-request.wav': [(659.25, 0.12), (880.0, 0.20)],
        'social-invite.wav': [(783.99, 0.11), (987.77, 0.11), (1174.66, 0.26)],
    }
    for name, notes in melodies.items():
        samples = []
        for pitch, duration in notes:
            count = int(rate * duration)
            for i in range(count):
                t = i / rate
                envelope = min(1, t / 0.012) * max(0, 1 - i / count) ** 1.8
                tone = (math.sin(2 * math.pi * pitch * t) + 0.18 * math.sin(4 * math.pi * pitch * t)) / 1.18
                samples.append(int(32767 * 0.22 * envelope * tone))
            samples.extend([0] * int(rate * 0.025))
        with wave.open(str(directory / name), 'wb') as output:
            output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            output.writeframes(struct.pack('<' + 'h' * len(samples), *samples))


if __name__ == '__main__':
    generate(Path(__file__).resolve().parents[1] / 'resources/sounds')
