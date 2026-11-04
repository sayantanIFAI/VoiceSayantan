"""Conditioning for a recorded clip that is cut into the Bengali / Hindi voice's audio (the "WhatsApp" recording: agent/whatsapp_tts.py, tts_server.py).

Why: measured on the pod (2026-11-04), the English recording carries 13 to 16 dB more energy above 6 kHz than the Bengali voice does, and its "ts" burst (300-450 ms into the clip) is 55-78% energy above 6 kHz with
isolated spiky samples. Next to a voice that has almost nothing up there, that burst is heard as hiss and crackle. A smooth low-pass (zero phase, so the word keeps its timing) brings the recording's top end
down to the voice's; a few milliseconds of fade at each edge keep the splice itself from clicking. Pure numpy; no model, no GPU.
"""

from __future__ import annotations

import numpy as np


def lowpass(data: np.ndarray, sample_rate: int, cutoff_hz: float, order: int = 4) -> np.ndarray:
    """A Butterworth-shaped low-pass applied in the frequency domain (zero phase: no delay, no ringing before the sound). `cutoff_hz` <= 0 or at/above Nyquist leaves the clip as it is."""
    x = np.asarray(data, dtype=np.float32)
    if x.size == 0 or cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2:
        return x
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sample_rate)
    gain = 1.0 / np.sqrt(1.0 + (freqs / cutoff_hz) ** (2 * order))
    return np.fft.irfft(spectrum * gain, n=x.size).astype(np.float32)


def fade_edges(data: np.ndarray, sample_rate: int, fade_s: float) -> np.ndarray:
    """A raised-cosine fade in and out of `fade_s` seconds at the two ends (never more than a quarter of the clip each), so the clip starts and ends at zero."""
    x = np.array(data, dtype=np.float32, copy=True)
    n = min(int(round(fade_s * sample_rate)), x.size // 4)
    if n < 2:
        return x
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n))).astype(np.float32)
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


def condition(data: np.ndarray, sample_rate: int, lowpass_hz: float = 0.0, fade_s: float = 0.0) -> np.ndarray:
    """The clip low-passed at `lowpass_hz` and faded at both ends by `fade_s`; with both at 0 the clip comes back unchanged."""
    return (
        fade_edges(lowpass(data, sample_rate, lowpass_hz), sample_rate, fade_s)
        if fade_s > 0
        else lowpass(data, sample_rate, lowpass_hz)
    )
