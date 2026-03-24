with open("main_app.py", encoding="utf-8") as f:
    for i in range(60):
        print(f"{i+1}: {f.readline().rstrip()}" )
