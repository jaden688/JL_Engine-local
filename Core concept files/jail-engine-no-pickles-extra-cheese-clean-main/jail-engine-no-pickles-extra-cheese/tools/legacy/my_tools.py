
def summarize_code(code: str) -> str:
    """Summarize simple code snippets."""
    if "def" in code and "return" in code:
        return "This function returns a computed result."
    return "No clear function definition found."

def get_current_time() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()
