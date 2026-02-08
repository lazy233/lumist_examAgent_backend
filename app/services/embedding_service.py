import os

from app.core.config import settings

from sentence_transformers import SentenceTransformer

_model = None


def _get_model():
    global _model
    if _model is None:
        # 绕过代理，避免 Clash 等导致 SSL/httpx 错误
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(key, None)
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()