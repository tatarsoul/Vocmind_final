import tempfile
from pathlib import Path
from typing import List, Tuple, Union

import numpy as np
from faster_whisper import WhisperModel

from ..config import settings


def _ct2_cuda_devices() -> int:
    try:
        import ctranslate2
        if hasattr(ctranslate2, "get_cuda_device_count"):
            return int(ctranslate2.get_cuda_device_count() or 0)
    except Exception:
        return 0
    return 0


def _resolve_device(device: str) -> str:
    d = (device or "").lower().strip()
    if d and d != "auto":
        return d
    return "cuda" if _ct2_cuda_devices() > 0 else "cpu"


def _resolve_compute_type(ct: str, device: str) -> str:
    c = (ct or "").lower().strip()
    if c and c != "auto":
        return c
    return "float16" if device == "cuda" else "int8"


ASR_DEVICE = _resolve_device(settings.asr_device)
ASR_COMPUTE = _resolve_compute_type(settings.asr_compute_type, ASR_DEVICE)

print(f"[ASR] ctranslate2 CUDA devices: {_ct2_cuda_devices()}")
print(f"[ASR] Loading model at startup: {settings.asr_model} on {ASR_DEVICE} ({ASR_COMPUTE})")

model = WhisperModel(settings.asr_model, device=ASR_DEVICE, compute_type=ASR_COMPUTE)

print("[ASR] Model loaded.")


def _pcm16_to_wav_file(pcm16: np.ndarray, sample_rate: int) -> Path:
    import wave
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_path = Path(tmp.name)
    with wave.open(str(tmp_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.astype(np.int16).tobytes())
    return tmp_path


def transcribe_pcm16_window(
    pcm16: np.ndarray,
    sample_rate: int,
    language: str = "ru",
    return_segments: bool = False,
    initial_prompt: str = "",
) -> Union[str, Tuple[str, List[Tuple[float, float, str]]]]:
    if pcm16 is None or pcm16.size == 0:
        return ("", []) if return_segments else ""

    wav_path = _pcm16_to_wav_file(pcm16, sample_rate)
    lang = (language or "").strip().lower() or None
    if lang == "auto":
        lang = None

    try:
        segments, _info = model.transcribe(
            str(wav_path),
            language=lang,
            task="transcribe",
            beam_size=5,
            repetition_penalty=1.04,
            no_repeat_ngram_size=3,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": int(getattr(settings, "vad_min_silence_ms", 600) or 600),
                "speech_pad_ms": 200,
            },
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.0,
            log_prob_threshold=-0.8,
            word_timestamps=True,
            hallucination_silence_threshold=1.2,
            suppress_tokens=[-1],
        )

        full_text: List[str] = []
        segs: List[Tuple[float, float, str]] = []
        for seg in segments:
            txt = (seg.text or "").strip()
            if not txt:
                continue
            full_text.append(txt)
            segs.append((float(seg.start), float(seg.end), txt))

        text_joined = " ".join(full_text).strip()
        return (text_joined, segs) if return_segments else text_joined
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass
