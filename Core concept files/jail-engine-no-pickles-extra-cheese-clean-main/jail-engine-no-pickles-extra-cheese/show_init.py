import pathlib
text = pathlib.Path('main_app.py').read_text(encoding='utf-8').splitlines()
for idx in range(420, 470):
    print(f"{idx+1}: {text[idx]}")
