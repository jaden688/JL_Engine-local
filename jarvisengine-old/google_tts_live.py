import os
from google.cloud import texttospeech

SERVICE_ACCOUNT_PATH = os.path.join(
    os.path.dirname(__file__),
    "myprojectyo-471407-47eb080ef502.json"
)


class GoogleTTSLive:
    def __init__(self, cred_path: str | None = None):
        cred_path = cred_path or SERVICE_ACCOUNT_PATH
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        self.client = texttospeech.TextToSpeechClient()

    def fetch_voices(self):
        """Return a simple list of dicts describing available voices."""
        response = self.client.list_voices()
        voices = []
        for voice in response.voices:
            voices.append({
                "name": voice.name,
                "language_codes": list(voice.language_codes),
                "gender": texttospeech.SsmlVoiceGender(voice.ssml_gender).name,
                "sample_rate_hz": voice.natural_sample_rate_hertz,
            })
        return voices

    def synthesize(self, text: str, voice_name: str, audio_encoding: str = "MP3") -> bytes:
        synthesis_input = texttospeech.SynthesisInput(text=text)

        # Derive languageCode from name like "en-US-Neural2-F"
        parts = voice_name.split("-")
        if len(parts) >= 2:
            language_code = f"{parts[0]}-{parts[1]}"
        else:
            language_code = "en-US"

        voice = texttospeech.VoiceSelectionParams(
            name=voice_name,
            language_code=language_code,
        )

        encoding_map = {
            "MP3": texttospeech.AudioEncoding.MP3,
            "OGG_OPUS": texttospeech.AudioEncoding.OGG_OPUS,
            "LINEAR16": texttospeech.AudioEncoding.LINEAR16,
        }
        audio_config = texttospeech.AudioConfig(
            audio_encoding=encoding_map.get(audio_encoding.upper(), texttospeech.AudioEncoding.MP3)
        )

        response = self.client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        return response.audio_content
