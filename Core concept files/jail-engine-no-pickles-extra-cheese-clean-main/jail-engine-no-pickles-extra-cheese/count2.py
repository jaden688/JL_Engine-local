import pathlib
text = pathlib.Path('tts_manager.py').read_text(encoding='utf-8')
print(text.count('gemini_endpoint'))
