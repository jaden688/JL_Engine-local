from huggingface_hub import snapshot_download
import os

def download_model():
    # Model: Phi-3-mini-4k-instruct-onnx-directml
    # This is the optimized version for Windows NPU/GPU via DirectML
    repo_id = "microsoft/Phi-3-mini-4k-instruct-onnx"
    
    # We specifically want the 'directml-int4-awq-block-128' folder 
    # (or similar variant) which contains the .onnx files.
    # Microsoft packages multiple variants in the same repo.
    # Let's target the 'directml-int4-awq-block-128' subfolder.
    subfolder = "directml/directml-int4-awq-block-128"
    
    target_dir = os.path.join(os.getcwd(), "models", "onnx-adapters", "phi3-mini-directml")
    
    print(f"Downloading {repo_id} ({subfolder}) to {target_dir}...")
    print("This may take a while depending on your internet connection...")
    
    try:
        snapshot_download(
            repo_id=repo_id,
            allow_patterns=[f"{subfolder}/*"],
            local_dir=target_dir,
            local_dir_use_symlinks=False
        )
        print("Download complete!")
        print(f"Model path: {os.path.join(target_dir, subfolder)}")
        
        # Update the backend config in backends.py if needed, or user can do it via UI
        # The default in backends.py was 'models/onnx-adapters', we should probably point specifically to the subfolder.
        print("\nNOTE: In backends.py, update 'model_path' to:")
        print(os.path.join(target_dir, subfolder).replace("\\\\", "/"))
        
    except Exception as e:
        print(f"Failed to download: {e}")

if __name__ == "__main__":
    download_model()
