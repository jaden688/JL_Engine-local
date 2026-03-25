"""Gemini Live audio output bridge for JL Engine replies.

This keeps JL Engine as the text/agent orchestrator and uses Gemini Live only
as a voice transport for already-generated assistant replies.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional


DEFAULT_LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
DEFAULT_LIVE_VOICE = "Zephyr"


class GeminiLiveAudioBridge:
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None) -> None:
        self._status_callback = status_callback
        self.api_key = ""
        self.model = DEFAULT_LIVE_MODEL
        self.voice = DEFAULT_LIVE_VOICE
        self.enabled = False
        self._speak_lock = threading.Lock()

    def configure(
        self,
        *,
        enabled: bool,
        api_key: str,
        model: str | None = None,
        voice: str | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip() or DEFAULT_LIVE_MODEL
        self.voice = str(voice or "").strip() or DEFAULT_LIVE_VOICE

    def available(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        if not self.api_key:
            return False, "missing_gemini_api_key"
        try:
            import pyaudio  # noqa: F401
            from google import genai  # noqa: F401
            from google.genai import types  # noqa: F401
        except Exception as exc:
            return False, f"missing_live_audio_dependencies:{exc}"
        return True, "ok"

    def speak_text(self, text: str) -> bool:
        message = str(text or "").strip()
        ok, reason = self.available()
        if not message or not ok:
            self._emit_status(f"Live voice unavailable: {reason}")
            return False
        asyncio.run(self._speak_once(message))
        return True

    async def _speak_once(self, text: str) -> None:
        import pyaudio
        from google import genai
        from google.genai import types

        client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=self.api_key,
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                )
            ),
            system_instruction=types.Content(
                role="system",
                parts=[
                    types.Part.from_text(
                        text=(
                            "You are a text-to-speech engine. "
                            "Repeat the following text exactly as written. "
                            "Do not paraphrase, do not add any greeting or closing, and do not respond to the content. "
                            "Speak ONLY the provided text."
                        )
                    )
                ],
            ),
        )

        pya = pyaudio.PyAudio()
        stream = None
        try:
            with self._speak_lock:
                stream = await asyncio.to_thread(
                    pya.open,
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=24000,
                    output=True,
                )
                self._emit_status(f"Speaking via Gemini Live ({self.voice})...")
                async with client.aio.live.connect(model=self.model, config=config) as session:
                    await session.send(input=text, end_of_turn=True)
                    turn = session.receive()
                    async for response in turn:
                        if response.data:
                            await asyncio.to_thread(stream.write, response.data)
                self._emit_status("Live voice playback complete.")
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                pya.terminate()
            except Exception:
                pass

    def _emit_status(self, message: str) -> None:
        if self._status_callback:
            try:
                self._status_callback(str(message))
            except Exception:
                pass
