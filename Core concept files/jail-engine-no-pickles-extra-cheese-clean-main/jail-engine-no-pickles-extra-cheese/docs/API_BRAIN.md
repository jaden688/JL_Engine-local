# Google Gemini Brain (Vertex AI Gemini 3 Pro)

This document now captures the production-ready backend that routes JL Engine prompts to Google Vertex AI’s
Gemini 3 Pro model with x-goog-api-key authentication.

## Integration intent
- Add `GoogleGeminiBackend` to `backends.py` and expose it through `BACKEND_REGISTRY`; the UI already iterates
  over that registry for backend selection.
- Return the Gemini backend from `get_backend()` whenever the registry entry’s `provider` is `google_gemini`, allowing
  `engine_core.py` to continue building the layered prompt and telemetry exactly as before.
- Submit the final joined string to Vertex via a synchronous POST, unwrap the first candidate, and return the text as
  the assistant reply.

## Implementation snippet

```python
class GoogleGeminiBackend(ModelBackend):
    def __init__(self, config: dict):
        super().__init__(config)
        self.endpoint = config.get(
            "google_gemini_endpoint",
            "https://us-central1-aiplatform.googleapis.com/v1/projects/jl-engine-6510e/locations/us-central1/publishers/google/models/gemini-3-pro:generateContent",
        )
        self.api_key = config.get("google_api_key", "YOUR_GOOGLE_API_KEY")
        self.timeout = config.get("google_gemini_timeout", 60)

    def _assemble_prompt(self, messages: list) -> str:
        pieces = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content") or msg.get("text") or ""
            if content:
                pieces.append(f"[{role}] {content}")
        return "\n".join(pieces).strip()

    def call_gemini(self, prompt: str, metadata: dict) -> str:
        """
        Call Vertex AI Gemini using x-goog-api-key authentication.
        """
        if not self.api_key:
            raise RuntimeError("google_api_key not set.")

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]
        }

        response = requests.post(
            self.endpoint,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return json.dumps(data, indent=2)

    def generate(self, messages: list, options: dict | None = None, timeout: int | float | None = None) -> tuple[str, dict]:
        prompt = self._assemble_prompt(messages)
        text = self.call_gemini(prompt, {"options": options or {}, "timeout": timeout})
        return text, {"model": "gemini-3-pro", "backend": "google_gemini"}
```

## Configuration checklist
1. Register the backend below with `BACKEND_REGISTRY` and make it the default backend so every `process_turn()`
   call hits Gemini by default:

```json
{
  "google-gemini": {
    "id": "google-gemini",
    "label": "Google Gemini 3 Pro (Vertex AI)",
    "provider": "google_gemini",
    "google_api_key": "YOUR_GOOGLE_API_KEY",
    "google_gemini_endpoint": "https://us-central1-aiplatform.googleapis.com/v1/projects/jl-engine-6510e/locations/us-central1/publishers/google/models/gemini-3-pro:generateContent"
  }
}
```

2. Avoid overriding this registry entry when the engine boots so `get_brain_backend()` keeps returning Gemini.
3. The backend only needs the final joined prompt (plus whatever metadata you log); all persona/telemetry work stays in
   `engine_core.py`.
