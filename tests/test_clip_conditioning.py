"""agent/clip_conditioning.py: the recorded "WhatsApp" clip is brought closer to the Bengali voice's spectrum and faded at its edges."""

import os

import numpy as np

from agent import clip_conditioning as cc

SR = 22050
CLIP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "whatsapp_en.wav")


def tone(hz, seconds=0.5, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def test_the_low_pass_keeps_the_voice_band_and_cuts_the_top():
    low, high = tone(1000), tone(9000)
    assert abs(rms(cc.lowpass(low, SR, 4500)) / rms(low) - 1) < 0.02
    assert rms(cc.lowpass(high, SR, 4500)) / rms(high) < 0.1  # more than 20 dB down at 9 kHz


def test_the_low_pass_adds_no_delay():
    pulse = np.zeros(2000, dtype=np.float32)
    pulse[1000] = 1.0
    assert int(np.argmax(np.abs(cc.lowpass(pulse, SR, 4500)))) == 1000


def test_zero_or_too_high_a_cutoff_is_a_no_op():
    x = tone(3000)
    assert np.array_equal(cc.lowpass(x, SR, 0), x) and np.array_equal(cc.lowpass(x, SR, SR / 2), x)
    assert np.array_equal(cc.condition(x, SR, 0.0, 0.0), x)
    assert cc.lowpass(np.zeros(0, dtype=np.float32), SR, 4500).size == 0


def test_the_fade_starts_and_ends_at_zero_and_leaves_the_middle_alone():
    x = np.ones(SR // 2, dtype=np.float32)
    y = cc.fade_edges(x, SR, 0.008)
    assert y[0] == 0.0 and y[-1] == 0.0 and np.all(y[int(0.02 * SR) : -int(0.02 * SR)] == 1.0)
    assert np.all(np.diff(y[: int(0.008 * SR)]) >= 0)  # a smooth ramp up, no overshoot
    assert np.array_equal(cc.fade_edges(x[:6], SR, 0.008), x[:6])  # too short for a fade: left alone


def test_the_real_recording_loses_its_hiss_and_keeps_its_word():
    import soundfile as sf

    clip, sr = sf.read(CLIP, dtype="float32")
    out = cc.condition(clip, sr, 4500, 0.008)

    lo, hi = int(0.30 * sr), int(0.45 * sr)  # the "ts" burst of the recording, where the hiss is (measured on the pod: 55-78% of its energy above 6 kHz)

    def burst_share_above(x, hz):
        seg = x[lo:hi] * np.hanning(hi - lo)
        spec = np.abs(np.fft.rfft(seg)) ** 2
        return float(spec[np.fft.rfftfreq(hi - lo, 1 / sr) >= hz].sum() / spec.sum())

    assert burst_share_above(clip, 6000) > 0.5 and burst_share_above(out, 6000) < 0.2
    assert 0.9 < rms(out) / rms(clip) <= 1.0  # the vowels, which carry the word, keep their level
    assert out.size == clip.size and out[0] == 0.0 and out[-1] == 0.0
