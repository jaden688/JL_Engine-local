import subprocess
import time
import os
import requests
import json
from typing import Optional

class FoundryBridge:
    """
    Handles the connection to the Foundry backend, including process management
    and NPU model loading.
    """
    def __init__(self, executable_path: str, api_url: str = "http://127.0.0.1:5000", port: int = 5000):
        self.executable_path = executable_path
        self.api_url = api_url
        self.port = port
        self.process: Optional[subprocess.Popen] = None

    def is_running(self) -> bool:
        """Checks if the Foundry API is responsive."""
        try:
            # Assuming Foundry has a standard health or version endpoint
            response = requests.get(f"{self.api_url}/health", timeout=1)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def launch(self) -> bool:
        """Launches the Foundry executable if it's not already running."""
        if self.is_running():
            print("[Foundry] Service is already running.")
            return True

        if not os.path.exists(self.executable_path):
            print(f"[Foundry] Error: Executable not found at {self.executable_path}")
            return False

        print(f"[Foundry] Launching backend from: {self.executable_path}")
        
        try:
            # Launch process. Adjust flags as needed for your specific Foundry version.
            # We assume it needs to run in its own directory.
            working_dir = os.path.dirname(self.executable_path)
            self.process = subprocess.Popen(
                [self.executable_path, "--api", "--listen", "--port", str(self.port)],
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for the service to come up
            print("[Foundry] Waiting for API to initialize...")
            for _ in range(15):
                if self.is_running():
                    print("[Foundry] Backend is ready.")
                    return True
                time.sleep(1)
            
            print("[Foundry] Timed out waiting for backend to start.")
            return False
            
        except Exception as e:
            print(f"[Foundry] Failed to launch process: {e}")
            return False

    def load_npu_model(self, model_name: str) -> bool:
        """Sends a request to load a specific model on the NPU."""
        if not self.is_running():
            print("[Foundry] Cannot load model: Backend is not running.")
            return False

        print(f"[Foundry] Requesting NPU load for model: {model_name}")
        payload = {
            "model": model_name,
            "device": "NPU",  # Explicitly requesting NPU
            "precision": "int8" # Often required for NPU acceleration
        }

        try:
            # Adjust endpoint '/v1/models/load' to match Foundry's actual API
            response = requests.post(f"{self.api_url}/v1/models/load", json=payload)
            if response.status_code == 200:
                print(f"[Foundry] Successfully loaded {model_name} on NPU.")
                return True
            else:
                print(f"[Foundry] Load failed: {response.text}")
                return False
        except Exception as e:
            print(f"[Foundry] API Error during model load: {e}")
            return False

    def shutdown(self):
        """Terminates the Foundry process."""
        if self.process:
            print("[Foundry] Shutting down backend process...")
            self.process.terminate()
            self.process = None

    def list_models(self) -> list:
        """Fetches available models from the Foundry backend."""
        if not self.is_running():
            return []
        try:
            # Assuming standard OpenAI-like /v1/models
            response = requests.get(f"{self.api_url}/v1/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    return [m["id"] for m in data["data"]]
            return []
        except Exception as e:
            print(f"[Foundry] Failed to list models: {e}")
            return []

    def download_model(self, model_name: str) -> bool:
        """Requests the backend to download/pull a model."""
        if not self.is_running():
            return False
        try:
            # Hypothetical endpoint for pulling models
            payload = {"model": model_name}
            response = requests.post(f"{self.api_url}/v1/models/pull", json=payload)
            return response.status_code == 200
        except Exception as e:
            print(f"[Foundry] Failed to download model: {e}")
            return False