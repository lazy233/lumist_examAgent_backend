"""Pre-download embedding model via ModelScope (works in China without HF)."""
import os
import sys

for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(key, None)

# ModelScope 镜像，ModelScope 上的 all-MiniLM-L6-v2
MS_MODEL = "AI-ModelScope/all-MiniLM-L6-v2"
HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_dir = os.path.join(base, "models", "all-MiniLM-L6-v2")
    os.makedirs(local_dir, exist_ok=True)

    print("Trying ModelScope (China mirror)...")
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        path = snapshot_download(MS_MODEL, cache_dir=os.path.join(base, "models"))
        print(f"ModelScope OK: {path}")
        return 0
    except Exception as e1:
        print(f"ModelScope failed: {e1}")

    print("Trying ModelScope alternative model id...")
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        path = snapshot_download("iic/nlp_gte_sentence-embedding_english-small", cache_dir=os.path.join(base, "models"))
        print(f"ModelScope OK: {path}")
        return 0
    except Exception as e2:
        print(f"ModelScope alt failed: {e2}")

    print("Trying HuggingFace mirror...")
    try:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from sentence_transformers import SentenceTransformer
        SentenceTransformer(HF_MODEL)
        print("HuggingFace OK.")
        return 0
    except Exception as e3:
        print(f"HuggingFace failed: {e3}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
