import itertools


def dump_lines(path: str, start: int, end: int) -> None:
    """Print a 1-based line range from the given file."""
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()

    for idx in range(start - 1, end):
        print(f"{idx + 1}: {lines[idx].rstrip()}")


if __name__ == "__main__":
    dump_lines("main_app.py", 1540, 1670)
