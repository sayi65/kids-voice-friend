"""声のモデル (.aivmx) を AivisSpeech なしで読み込み、文章を WAV にする。

voices/ に .aivmx を置くと一覧に出る。一番新しく置いたものが既定になる。
"""
import io
import wave
from io import BytesIO
from pathlib import Path

import aivmlib
import numpy as np
from style_bert_vits2.constants import Languages
from style_bert_vits2.models.hyper_parameters import HyperParameters
from style_bert_vits2.nlp import onnx_bert_models
from style_bert_vits2.tts_model import TTSModel

VOICES_DIR = Path(__file__).parent / "voices"
# AivisSpeech Engine と同じ BERT モデル・リビジョン。変えると声のモデルの学習時と抑揚がずれる
BERT_REPO = "tsukumijima/deberta-v2-large-japanese-char-wwm-onnx"
BERT_REVISION = "5e5cc2b628d083d0a815c4d4a4c3fe84a414f8ed"
# GPU は返事を作る LLM が使うので、声は CPU で作る
PROVIDERS = ["CPUExecutionProvider"]

_bert_loaded = False
_info_cache = {}


def _read_metadata(path):
    with path.open("rb") as f:
        return aivmlib.read_aivmx_metadata(f)


def list_voices():
    """voices/ の声を新しい順に返す。[{"file", "name", "styles"}]"""
    voices = []
    for path in sorted(VOICES_DIR.glob("*.aivmx"), key=lambda p: p.stat().st_mtime, reverse=True):
        key = (path.name, path.stat().st_mtime)
        if key not in _info_cache:
            meta = _read_metadata(path)
            speaker = meta.manifest.speakers[0]
            _info_cache[key] = {"file": path.name, "name": speaker.name, "styles": [s.name for s in speaker.styles]}
        voices.append(_info_cache[key])
    return voices


class Voice:
    def __init__(self, file):
        global _bert_loaded
        if not _bert_loaded:
            onnx_bert_models.load_model(language=Languages.JP, pretrained_model_name_or_path=BERT_REPO,
                                        onnx_providers=PROVIDERS, revision=BERT_REVISION)
            onnx_bert_models.load_tokenizer(language=Languages.JP, pretrained_model_name_or_path=BERT_REPO,
                                            revision=BERT_REVISION)
            _bert_loaded = True
        path = VOICES_DIR / file
        meta = _read_metadata(path)
        hp = HyperParameters.model_validate(meta.hyper_parameters.model_dump())
        self.styles = list(hp.data.style2id)
        self.model = TTSModel(model_path=path, config_path=hp,
                              style_vec_path=np.load(BytesIO(meta.style_vectors)), onnx_providers=PROVIDERS)
        self.model.load()

    def synthesize(self, text, style):
        rate, audio = self.model.infer(text=text, language=Languages.JP, speaker_id=0, style=style)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(audio.astype(np.int16).tobytes())
        return buf.getvalue()
