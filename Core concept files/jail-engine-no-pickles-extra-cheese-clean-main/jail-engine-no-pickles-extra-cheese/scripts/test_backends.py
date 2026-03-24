"""Lightweight backend sanity checks.

Run with: python scripts/test_backends.py
This will attempt an Ollama call if a local instance is running.
"""

from __future__ import annotations

import os

from backends import LlamaCppHTTPBackend, OllamaBackend, BackendConfig, create_backend, BackendError


def _build_messages():
    return [
        {"role": "system", "content": "You are JL Engine test backend."},
        {"role": "user", "content": "Say hello in one short sentence."},
    ]


def try_ollama():
    print("[test] Ollama backend...")
    config = {
        "id": "ollama-local-test",
        "provider": "ollama",
        "model": os.getenv("JL_MODEL", "llama3"),
        "modelName": os.getenv("JL_MODEL", "llama3"),
        "baseUrl": os.getenv("JL_BACKEND_URL", "http://127.0.0.1:11434"),
    }
    backend = OllamaBackend(config)
    try:
        reply = backend.generate(_build_messages())
        print(f"[ollama ok] {reply[:200]}\n")
    except BackendError as exc:
        print(f"[ollama skipped] {exc}\n")


def try_llama_cpp():
    print("[test] llama.cpp HTTP backend (placeholder)...")
    cfg = BackendConfig(
        id="llama-cpp-test",
        provider="llama_cpp_http",
        model=os.getenv("LLAMA_CPP_MODEL", "local-llama-gguf"),
        api_url=os.getenv("LLAMA_CPP_API_URL", "http://127.0.0.1:8000"),
        api_type=os.getenv("LLAMA_CPP_API_TYPE", "openai_compatible"),
    )
    backend = create_backend(cfg)
    try:
        backend.generate(_build_messages())
        print("[llama.cpp ok] request built successfully\n")
    except BackendError as exc:
        print(f"[llama.cpp unavailable] {exc}\n")
    except Exception as exc:
        print(f"[llama.cpp error] {exc}\n")


if __name__ == "__main__":
    try_ollama()
    try_llama_cpp()
