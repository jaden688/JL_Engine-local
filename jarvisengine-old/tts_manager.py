"""
TTS Manager (scaffold)

Provides basic voice selection using a cached voices file. Designed to be wired to
Google Cloud Text-to-Speech when credentials and network are available. In this
environment we avoid live API calls and rely on a local cache (JSON).
"""
from __future__ import annotations

import json
import os
from typing import List, Dict, Optional


class TTSManager:
    def __init__(self, cache_path: str = "voices_cache.json", config_path: str = "tts_config.json"):
        self.cache_path = cache_path
        self.config_path = config_path
        self._voices: List[Dict[str, str]] = []
        self._selected_voice: Optional[str] = None
        self.provider: str = "google"
        self.api_keys: Dict[str, str] = {}
        self.google_sdk_enabled: bool = True
        self.google_service_account: Optional[str] = None
        self.load_config()
        self.load_cached_voices()

    def load_cached_voices(self) -> None:
        """Load voices from a local cache file; safe if missing."""
        self._voices = []
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._voices = [
                    v for v in data if isinstance(v, dict) and v.get("name")
                ]
        except Exception as exc:
            print(f"[TTS] WARN: Failed to load cache '{self.cache_path}': {exc}")

    def load_config(self) -> None:
        """Load provider/api settings from a local config file; safe if missing."""
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.provider = data.get("provider", self.provider)
                self.api_keys = data.get("api_keys", {}) if isinstance(data.get("api_keys"), dict) else {}
                self._selected_voice = data.get("selected_voice", self._selected_voice)
                self.google_sdk_enabled = data.get("google_sdk_enabled", self.google_sdk_enabled)
                self.google_service_account = data.get("google_service_account", self.google_service_account)
        except Exception as exc:
            print(f"[TTS] WARN: Failed to load config '{self.config_path}': {exc}")

    def save_config(self) -> None:
        """Persist provider/api settings locally."""
        payload = {
            "provider": self.provider,
            "api_keys": self.api_keys,
            "selected_voice": self._selected_voice,
            "google_sdk_enabled": self.google_sdk_enabled,
            "google_service_account": self.google_service_account,
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            print(f"[TTS] WARN: Failed to save config '{self.config_path}': {exc}")

    def set_provider(self, provider: str) -> None:
        self.provider = provider
        self.save_config()

    def get_provider(self) -> str:
        return self.provider

    def set_api_key(self, provider: str, key: str) -> None:
        if not provider:
            return
        if key is None:
            key = ""
        self.api_keys[provider] = key
        self.save_config()

    def get_api_key(self, provider: str) -> str:
        return self.api_keys.get(provider, "")

    def set_google_service_account(self, path: str) -> None:
        self.google_service_account = path
        self.save_config()

    def set_google_sdk_enabled(self, enabled: bool) -> None:
        self.google_sdk_enabled = enabled
        self.save_config()

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        Attempt to synthesize speech using the configured provider.
        Returns audio bytes or None on failure. This requires the relevant SDK and network.
        """
        if not text:
            return None
        provider = self.provider.lower()
        voice_name = self._selected_voice or ""
        if provider == "google":
            if self.google_sdk_enabled:
                try:
                    from google_tts_live import GoogleTTSLive  # type: ignore
                    cred = self.google_service_account
                    gtts = GoogleTTSLive(cred_path=cred) if cred else GoogleTTSLive()
                    return gtts.synthesize(text, voice_name or "en-US-Neural2-F")
                except Exception as exc:
                    print(f"[TTS] WARN: Google SDK synth failed, falling back to cache/placeholder: {exc}")
            # Placeholder: no REST fallback implemented here
            return None
        elif provider == "elevenlabs":
            # Placeholder: implement ElevenLabs API call when wired with requests and API key
            print("[TTS] INFO: ElevenLabs provider selected; network call not implemented in this environment.")
            return None
        return None

    def fetch_live_google_voices(self) -> bool:
        """Attempt to fetch live voices via Google SDK; returns True on success."""
        try:
            from google_tts_live import GoogleTTSLive  # type: ignore
            cred = self.google_service_account
            gtts = GoogleTTSLive(cred_path=cred) if cred else GoogleTTSLive()
            voices = gtts.fetch_voices()
            if voices:
                # normalize for cache
                normalized = []
                for v in voices:
                    normalized.append({
                        "name": v.get("name"),
                        "languageCode": (v.get("language_codes") or [""])[0],
                        "ssmlGender": v.get("gender"),
                        "sample_rate_hz": v.get("sample_rate_hz"),
                    })
                self._voices = normalized
                # save cache
                try:
                    with open(self.cache_path, "w", encoding="utf-8") as f:
                        json.dump(normalized, f, indent=2)
                except Exception as exc:
                    print(f"[TTS] WARN: Failed to save voices cache: {exc}")
                return True
        except Exception as exc:
            print(f"[TTS] WARN: Live Google voices fetch failed: {exc}")
        return False

    def reload_voices(self, fetch_live: bool = False) -> None:
        """Reload voices, optionally fetching live for Google when enabled."""
        if fetch_live and self.provider.lower() == "google" and self.google_sdk_enabled:
            ok = self.fetch_live_google_voices()
            if ok:
                return
            # fall back if live failed
        self.load_cached_voices()

    def list_voices(self) -> List[Dict[str, str]]:
        """Return cached voices; each entry should have name/lang/gender if available."""
        return list(self._voices)

    def set_voice(self, voice_name: str) -> None:
        self._selected_voice = voice_name
        print(f"[TTS] Selected voice: {voice_name}")

    def get_selected_voice(self) -> Optional[str]:
        return self._selected_voice

    def synthesize_placeholder(self, text: str) -> str:
        """Placeholder synthesis; replace with real TTS integration later."""
        voice = self._selected_voice or "default"
        return f"[TTS:{voice}] {text}"
