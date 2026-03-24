import onnxruntime_genai as og
import inspect

def test_api():
    print(f"ONNX Runtime GenAI Version: {og.__version__ if hasattr(og, '__version__') else 'Unknown'}")
    
    # Mock model loading (we can't really load without a path, but we can inspect classes)
    print("\n--- GeneratorParams Attributes ---")
    try:
        # We need a model to instantiate params usually, which is annoying.
        # Let's check the docstrings/signatures if possible.
        print(dir(og.GeneratorParams))
    except Exception as e:
        print(f"Could not inspect class: {e}")

    print("\n--- Testing Dummy Instantiation ---")
    try:
        # This will fail without a real model path
        model = og.Model("models/onnx-adapters/phi3-mini-directml/directml/directml-int4-awq-block-128")
        params = og.GeneratorParams(model)
        print("Params instantiated.")
        print("params dir:", dir(params))
        
        # Check for input_ids
        if hasattr(params, "input_ids"):
            print("HAS input_ids")
        else:
            print("MISSING input_ids")
            
    except Exception as e:
        print(f"Instantiation failed (expected if path invalid): {e}")

if __name__ == "__main__":
    test_api()
