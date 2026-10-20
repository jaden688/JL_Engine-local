from __future__ import annotations

import html
import hashlib
import json
import math
import struct
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SplashSource:
    token: str
    module: str
    x: int
    y: int
    radius: int
    period: int
    phase: int
    strength: float
    r_bias: float
    g_bias: float
    b_bias: float
    delay_bias: float


@dataclass(frozen=True)
class SplashGardenConfig:
    prompt: str
    width: int = 96
    height: int = 96
    steps: int = 72
    out_path: str = "data/splash_garden.png"
    delay_out_path: str = "data/splash_garden_delay.png"
    meta_out_path: str = "data/splash_garden.json"
    energy: float = 1.0
    delay_gain: float = 1.0
    structure_gain: float = 1.0
    spectral_tilt: float = 0.0
    ring_scale: float = 1.0
    guide_label: str | None = None
    guide_luma: list[list[float]] | None = None
    guide_edges: list[list[float]] | None = None


@dataclass(frozen=True)
class SplashBenchCase:
    slug: str
    title: str
    description: str
    energy: float = 1.0
    delay_gain: float = 1.0
    structure_gain: float = 1.0
    spectral_tilt: float = 0.0
    ring_scale: float = 1.0
    extra_steps: int = 0


@dataclass(frozen=True)
class SplashBenchConfig:
    prompt: str
    out_dir: str = "data/splash_garden_bench"
    width: int = 96
    height: int = 96
    steps: int = 72
    guide_label: str | None = None
    guide_luma: list[list[float]] | None = None
    guide_edges: list[list[float]] | None = None


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _zero_field(width: int, height: int) -> list[list[float]]:
    return [[0.0 for _ in range(width)] for _ in range(height)]


def _hash_bytes(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def _hash_unit(text: str, offset: int) -> float:
    payload = _hash_bytes(text)
    return payload[offset % len(payload)] / 255.0


def _tokenize(prompt: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in prompt)
    tokens = [part for part in cleaned.split() if part]
    return tokens or ["splash", "garden", "ripple"]


def _slugify(text: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    parts = [part for part in slug.split("-") if part]
    return "-".join(parts) or "splash-garden"


def _tilt_channels(red: float, green: float, blue: float, spectral_tilt: float) -> tuple[float, float, float]:
    red += spectral_tilt * 0.22
    blue -= spectral_tilt * 0.22
    green -= abs(spectral_tilt) * 0.08
    return (
        _clamp(red, 0.05, 1.35),
        _clamp(green, 0.05, 1.35),
        _clamp(blue, 0.05, 1.35),
    )


def _disk_points(cx: int, cy: int, radius: int, width: int, height: int):
    radius_sq = radius * radius
    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        dy = y - cy
        for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
            dx = x - cx
            dist_sq = dx * dx + dy * dy
            if dist_sq <= radius_sq:
                yield x, y, 1.0 - (dist_sq / max(radius_sq, 1))


def _build_sources(
    prompt: str,
    width: int,
    height: int,
    energy: float,
    spectral_tilt: float,
    ring_scale: float,
) -> list[SplashSource]:
    tokens = _tokenize(prompt)[:12]
    modules = ["core", "style", "detail", "lighting"]
    cx = width // 2
    cy = height // 2
    base_radius = max(3, min(width, height) // 14)
    ring_base = max(8.0, min(width, height) * 0.22) * ring_scale
    sources: list[SplashSource] = []

    root = prompt.strip() or "splash garden"
    root_r, root_g, root_b = _tilt_channels(0.92, 0.88, 1.0, spectral_tilt * 0.5)
    sources.append(
        SplashSource(
            token=root,
            module="core",
            x=cx,
            y=cy,
            radius=max(base_radius + 3, min(width, height) // 9),
            period=9,
            phase=0,
            strength=1.4 * energy,
            r_bias=root_r,
            g_bias=root_g,
            b_bias=root_b,
            delay_bias=1.1,
        )
    )

    count = len(tokens)
    for index, token in enumerate(tokens):
        key = f"{prompt}:{token}:{index}"
        angle = (2.0 * math.pi * index) / max(count, 1)
        band = index % 3
        ring_radius = ring_base + band * max(4.0, min(width, height) * 0.06)
        x = int(round(cx + math.cos(angle) * ring_radius))
        y = int(round(cy + math.sin(angle) * ring_radius))
        token_r, token_g, token_b = _tilt_channels(
            0.2 + _hash_unit(key, 13) * 0.8,
            0.2 + _hash_unit(key, 17) * 0.8,
            0.2 + _hash_unit(key, 19) * 0.8,
            spectral_tilt,
        )
        sources.append(
            SplashSource(
                token=token,
                module=modules[(index + 1) % len(modules)],
                x=int(_clamp(x, 2, width - 3)),
                y=int(_clamp(y, 2, height - 3)),
                radius=base_radius + int(_hash_unit(key, 3) * 5),
                period=6 + int(_hash_unit(key, 5) * 11),
                phase=int(_hash_unit(key, 7) * 5),
                strength=(0.45 + _hash_unit(key, 11) * 1.15) * energy,
                r_bias=token_r,
                g_bias=token_g,
                b_bias=token_b,
                delay_bias=0.45 + _hash_unit(key, 23) * 0.9,
            )
        )
    return sources


def _paint_lenses(
    sources: list[SplashSource], width: int, height: int, structure_gain: float, delay_gain: float
) -> tuple[list[list[float]], list[list[float]], list[list[float]], list[list[float]]]:
    r_lens = _zero_field(width, height)
    g_lens = _zero_field(width, height)
    b_lens = _zero_field(width, height)
    d_lens = _zero_field(width, height)
    for source in sources:
        influence_radius = max(2, source.radius * 2)
        for x, y, weight in _disk_points(source.x, source.y, influence_radius, width, height):
            scale = weight * 0.065 * structure_gain
            r_lens[y][x] += scale * source.r_bias
            g_lens[y][x] += scale * source.g_bias
            b_lens[y][x] += scale * source.b_bias
            d_lens[y][x] += scale * source.delay_bias * delay_gain
    return r_lens, g_lens, b_lens, d_lens


def _inject_source(
    rgb_fields: list[list[list[float]]],
    delay_field: list[list[float]],
    source: SplashSource,
    step: int,
    width: int,
    height: int,
    delay_gain: float,
) -> None:
    frequency = (2.0 * math.pi) / max(source.period, 1)
    pulse = math.sin((step + source.phase + 1) * frequency)
    for x, y, weight in _disk_points(source.x, source.y, source.radius, width, height):
        amplitude = weight * source.strength * pulse
        rgb_fields[0][y][x] += amplitude * source.r_bias
        rgb_fields[1][y][x] += amplitude * source.g_bias
        rgb_fields[2][y][x] += amplitude * source.b_bias
        delay_field[y][x] += abs(amplitude) * source.delay_bias * 0.55 * delay_gain


def _step_field(
    current: list[list[float]],
    previous: list[list[float]],
    lens: list[list[float]],
    delay_field: list[list[float]],
    base_speed: float,
    delay_coupling: float,
    attenuation: float,
) -> list[list[float]]:
    height = len(current)
    width = len(current[0])
    next_field = _zero_field(width, height)
    for y in range(1, height - 1):
        row = current[y]
        prev_row = previous[y]
        next_row = next_field[y]
        lens_row = lens[y]
        delay_row = delay_field[y]
        row_above = current[y - 1]
        row_below = current[y + 1]
        for x in range(1, width - 1):
            value = row[x]
            laplacian = row[x - 1] + row[x + 1] + row_above[x] + row_below[x] - (4.0 * value)
            speed = _clamp(
                base_speed + lens_row[x] + math.tanh(delay_row[x] * 0.12) * delay_coupling,
                0.02,
                0.24,
            )
            next_row[x] = ((1.94 * value) - (0.965 * prev_row[x]) + (speed * laplacian)) * attenuation
    return next_field


def _max_abs(field: list[list[float]]) -> float:
    largest = 0.0
    for row in field:
        for value in row:
            magnitude = abs(value)
            if magnitude > largest:
                largest = magnitude
    return largest or 1.0


def _coerce_guide_map(
    payload: list[list[float]] | None, width: int, height: int
) -> list[list[float]] | None:
    if not payload or not isinstance(payload, list):
        return None
    rows = payload[:height]
    if not rows:
        return None
    field = _zero_field(width, height)
    for y, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        for x, value in enumerate(row[:width]):
            try:
                field[y][x] = _clamp(float(value), 0.0, 1.0)
            except (TypeError, ValueError):
                field[y][x] = 0.0
    return field


def _mean_field(field: list[list[float]] | None) -> float:
    if not field:
        return 0.0
    total = 0.0
    count = 0
    for row in field:
        for value in row:
            total += value
            count += 1
    return total / max(count, 1)


def _apply_guide_fields(
    guide_luma: list[list[float]] | None,
    guide_edges: list[list[float]] | None,
    r_lens: list[list[float]],
    g_lens: list[list[float]],
    b_lens: list[list[float]],
    d_lens: list[list[float]],
    rgb_current: list[list[list[float]]],
    delay_current: list[list[float]],
    structure_gain: float,
    delay_gain: float,
) -> dict[str, float]:
    if not guide_luma and not guide_edges:
        return {"enabled": 0.0, "luma_mean": 0.0, "edge_mean": 0.0, "edge_peak": 0.0}

    height = len(delay_current)
    width = len(delay_current[0])
    edge_peak = 0.0
    for y in range(height):
        for x in range(width):
            luma = guide_luma[y][x] if guide_luma else 0.0
            edge = guide_edges[y][x] if guide_edges else 0.0
            edge_peak = edge if edge > edge_peak else edge_peak

            structure_push = (luma * 0.045) + (edge * 0.16 * structure_gain)
            delay_push = (edge * 0.26 * delay_gain) + (luma * 0.035)

            r_lens[y][x] += structure_push * (0.72 + (luma * 0.35))
            g_lens[y][x] += structure_push * (0.62 + (edge * 0.42))
            b_lens[y][x] += structure_push * (0.54 + ((1.0 - luma) * 0.24))
            d_lens[y][x] += delay_push

            rgb_current[0][y][x] += ((luma - 0.5) * 0.22) + (edge * 0.05)
            rgb_current[1][y][x] += ((edge - 0.35) * 0.16)
            rgb_current[2][y][x] += (((1.0 - luma) - 0.5) * 0.16) + (edge * 0.07)
            delay_current[y][x] += (edge * 0.38) + (luma * 0.11)

    return {
        "enabled": 1.0,
        "luma_mean": _mean_field(guide_luma),
        "edge_mean": _mean_field(guide_edges),
        "edge_peak": edge_peak,
    }


def _write_ppm(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        for row in pixels:
            for red, green, blue in row:
                handle.write(bytes((red, green, blue)))


def _write_pgm(path: Path, pixels: list[list[int]]) -> None:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        for row in pixels:
            handle.write(bytes(row))


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _write_png_rgb(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    raw_rows = bytearray()
    for row in pixels:
        raw_rows.append(0)
        for red, green, blue in row:
            raw_rows.extend((red, green, blue))
    compressed = zlib.compress(bytes(raw_rows), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(_png_chunk(b"IHDR", ihdr))
        handle.write(_png_chunk(b"IDAT", compressed))
        handle.write(_png_chunk(b"IEND", b""))


def _write_png_gray(path: Path, pixels: list[list[int]]) -> None:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    raw_rows = bytearray()
    for row in pixels:
        raw_rows.append(0)
        raw_rows.extend(row)
    compressed = zlib.compress(bytes(raw_rows), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(_png_chunk(b"IHDR", ihdr))
        handle.write(_png_chunk(b"IDAT", compressed))
        handle.write(_png_chunk(b"IEND", b""))


def _write_rgb_image(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".png":
        _write_png_rgb(path, pixels)
        return
    _write_ppm(path, pixels)


def _write_delay_image(path: Path, pixels: list[list[int]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".png":
        _write_png_gray(path, pixels)
        return
    _write_pgm(path, pixels)


def _module_color(module: str) -> tuple[int, int, int]:
    palette = {
        "core": (255, 104, 68),
        "style": (255, 208, 76),
        "detail": (54, 197, 240),
        "lighting": (214, 130, 255),
    }
    return palette.get(module, (255, 255, 255))


def _build_source_map(
    sources: list[SplashSource], width: int, height: int
) -> list[list[tuple[int, int, int]]]:
    pixels = [[(8, 12, 18) for _ in range(width)] for _ in range(height)]
    for source in sources:
        red, green, blue = _module_color(source.module)
        marker_radius = max(2, source.radius // 2)
        for x, y, weight in _disk_points(source.x, source.y, marker_radius, width, height):
            glow = 0.2 + (weight * 0.8)
            pixels[y][x] = (
                int(_clamp(red * glow, 0, 255)),
                int(_clamp(green * glow, 0, 255)),
                int(_clamp(blue * glow, 0, 255)),
            )
    return pixels


def _auxiliary_output_paths(out_path: Path) -> dict[str, Path]:
    return {
        "red": out_path.with_name(f"{out_path.stem}-red{out_path.suffix}"),
        "green": out_path.with_name(f"{out_path.stem}-green{out_path.suffix}"),
        "blue": out_path.with_name(f"{out_path.stem}-blue{out_path.suffix}"),
        "source_map": out_path.with_name(f"{out_path.stem}-sources{out_path.suffix}"),
    }


def _asset_name(path_text: str) -> str:
    return Path(path_text).name


def _write_bench_report(out_dir: Path, manifest: dict[str, object]) -> Path:
    prompt = html.escape(str(manifest["prompt"]))
    highlights = manifest["highlights"]
    cases = manifest["cases"]
    cards: list[str] = []
    for case in cases:
        pixel_stats = case["pixel_stats"]
        tuning = case["tuning"]
        cards.append(
            f"""
            <article class="case-card">
              <header>
                <h2>{html.escape(str(case["title"]))}</h2>
                <p>{html.escape(str(case["description"]))}</p>
              </header>
              <div class="hero-grid">
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["rgb"]))}" alt="{html.escape(str(case["title"]))} RGB render">
                  <figcaption>RGB field</figcaption>
                </figure>
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["delay"]))}" alt="{html.escape(str(case["title"]))} delay map">
                  <figcaption>Delay field</figcaption>
                </figure>
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["source_map"]))}" alt="{html.escape(str(case["title"]))} source map">
                  <figcaption>Source map</figcaption>
                </figure>
              </div>
              <div class="channel-grid">
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["red"]))}" alt="{html.escape(str(case["title"]))} red channel">
                  <figcaption>Red</figcaption>
                </figure>
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["green"]))}" alt="{html.escape(str(case["title"]))} green channel">
                  <figcaption>Green</figcaption>
                </figure>
                <figure>
                  <img src="{html.escape(_asset_name(case["files"]["blue"]))}" alt="{html.escape(str(case["title"]))} blue channel">
                  <figcaption>Blue</figcaption>
                </figure>
              </div>
              <dl class="stat-grid">
                <div><dt>Delay mean</dt><dd>{pixel_stats["delay_mean"]:.3f}</dd></div>
                <div><dt>Brightness</dt><dd>{pixel_stats["brightness_mean"]:.3f}</dd></div>
                <div><dt>Spectral split</dt><dd>{pixel_stats["spectral_split"]:.3f}</dd></div>
                <div><dt>Structure gain</dt><dd>{tuning["structure_gain"]:.2f}</dd></div>
                <div><dt>Delay gain</dt><dd>{tuning["delay_gain"]:.2f}</dd></div>
                <div><dt>Spectral tilt</dt><dd>{tuning["spectral_tilt"]:.2f}</dd></div>
              </dl>
            </article>
            """
        )

    report_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Splash Garden Bench</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #08111a;
      --panel: rgba(11, 24, 37, 0.88);
      --line: rgba(133, 197, 255, 0.18);
      --text: #eff7ff;
      --muted: #9bb7c9;
      --hot: #ffb44c;
      --aqua: #67e8f9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at top, rgba(63, 116, 165, 0.35), transparent 42%),
        linear-gradient(180deg, #071019 0%, #0d1721 48%, #091019 100%);
      color: var(--text);
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px;
      margin-bottom: 24px;
      backdrop-filter: blur(18px);
    }}
    h1, h2 {{ margin: 0 0 8px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .highlight-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .pill {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
    }}
    .pill strong {{
      display: block;
      color: var(--hot);
      margin-bottom: 4px;
    }}
    .case-stack {{
      display: grid;
      gap: 20px;
    }}
    .case-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 22px;
    }}
    .hero-grid, .channel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}
    figure {{
      margin: 0;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 18px;
      overflow: hidden;
    }}
    img {{
      display: block;
      width: 100%;
      image-rendering: pixelated;
      background: #05080d;
      aspect-ratio: 1 / 1;
      object-fit: cover;
    }}
    figcaption {{
      padding: 10px 12px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 12px;
      margin: 18px 0 0;
    }}
    .stat-grid div {{
      padding: 10px 12px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
    dt {{
      color: var(--muted);
      font-size: 0.84rem;
    }}
    dd {{
      margin: 6px 0 0;
      font-size: 1.05rem;
      color: var(--aqua);
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Splash Garden Bench</h1>
      <p>Prompt: <strong>{prompt}</strong></p>
      <div class="highlight-row">
        <div class="pill"><strong>Most Delay-Driven</strong>{html.escape(str(highlights["most_delay_driven"]))}</div>
        <div class="pill"><strong>Most Structural</strong>{html.escape(str(highlights["most_structural"]))}</div>
        <div class="pill"><strong>Most Spectral</strong>{html.escape(str(highlights["most_spectral"]))}</div>
      </div>
    </section>
    <section class="case-stack">
      {''.join(cards)}
    </section>
  </main>
</body>
</html>
"""
    report_path = out_dir / "index.html"
    report_path.write_text(report_html, encoding="utf-8")
    return report_path


def _case_library() -> list[SplashBenchCase]:
    return [
        SplashBenchCase(
            slug="balanced-field",
            title="Balanced Field",
            description="Baseline unseen-vision render with the hub and ring held in balance.",
        ),
        SplashBenchCase(
            slug="delay-oracle",
            title="Delay Oracle",
            description="Pushes the hidden delay layer harder so arrival-order starts steering the scene.",
            energy=0.94,
            delay_gain=1.8,
            structure_gain=0.92,
            spectral_tilt=0.18,
            ring_scale=0.96,
            extra_steps=10,
        ),
        SplashBenchCase(
            slug="structure-lock",
            title="Structure Lock",
            description="Leans into lensing and composition to see whether the form stabilizes first.",
            energy=1.05,
            delay_gain=0.82,
            structure_gain=1.65,
            spectral_tilt=-0.12,
            ring_scale=0.84,
            extra_steps=6,
        ),
        SplashBenchCase(
            slug="spectral-echo",
            title="Spectral Echo",
            description="Separates channel agentlities so the field reveals color-phase drift.",
            energy=1.12,
            delay_gain=1.08,
            structure_gain=1.0,
            spectral_tilt=0.78,
            ring_scale=1.14,
            extra_steps=14,
        ),
    ]


def render_splash_garden(config: SplashGardenConfig) -> dict[str, object]:
    width = int(_clamp(config.width, 24, 192))
    height = int(_clamp(config.height, 24, 192))
    steps = int(_clamp(config.steps, 8, 200))
    prompt = config.prompt.strip() or "splash garden"
    energy = _clamp(config.energy, 0.35, 2.4)
    delay_gain = _clamp(config.delay_gain, 0.35, 2.6)
    structure_gain = _clamp(config.structure_gain, 0.45, 2.6)
    spectral_tilt = _clamp(config.spectral_tilt, -1.0, 1.0)
    ring_scale = _clamp(config.ring_scale, 0.6, 1.45)
    guide_luma = _coerce_guide_map(config.guide_luma, width, height)
    guide_edges = _coerce_guide_map(config.guide_edges, width, height)
    seed_material = (
        f"{prompt}|{width}|{height}|{steps}|{energy:.3f}|{delay_gain:.3f}|"
        f"{structure_gain:.3f}|{spectral_tilt:.3f}|{ring_scale:.3f}|"
        f"{_mean_field(guide_luma):.4f}|{_mean_field(guide_edges):.4f}"
    )
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)

    sources = _build_sources(prompt, width, height, energy, spectral_tilt, ring_scale)
    r_lens, g_lens, b_lens, d_lens = _paint_lenses(
        sources, width, height, structure_gain, delay_gain
    )

    rgb_current = [_zero_field(width, height) for _ in range(3)]
    rgb_previous = [_zero_field(width, height) for _ in range(3)]
    delay_current = _zero_field(width, height)
    delay_previous = _zero_field(width, height)
    guide_stats = _apply_guide_fields(
        guide_luma,
        guide_edges,
        r_lens,
        g_lens,
        b_lens,
        d_lens,
        rgb_current,
        delay_current,
        structure_gain,
        delay_gain,
    )

    for step in range(steps):
        for source in sources:
            _inject_source(rgb_current, delay_current, source, step, width, height, delay_gain)

        next_delay = _step_field(
            delay_current,
            delay_previous,
            d_lens,
            delay_current,
            base_speed=0.052 + ((structure_gain - 1.0) * 0.008),
            delay_coupling=0.015 * delay_gain,
            attenuation=_clamp(0.992 - ((energy - 1.0) * 0.003), 0.982, 0.997),
        )

        next_rgb = [
            _step_field(
                rgb_current[0],
                rgb_previous[0],
                r_lens,
                delay_current,
                base_speed=0.068 + ((structure_gain - 1.0) * 0.009),
                delay_coupling=0.022 * delay_gain,
                attenuation=_clamp(0.996 - ((energy - 1.0) * 0.002), 0.988, 0.998),
            ),
            _step_field(
                rgb_current[1],
                rgb_previous[1],
                g_lens,
                delay_current,
                base_speed=0.074 + ((structure_gain - 1.0) * 0.008),
                delay_coupling=0.018 * delay_gain,
                attenuation=_clamp(0.996 - ((energy - 1.0) * 0.002), 0.988, 0.998),
            ),
            _step_field(
                rgb_current[2],
                rgb_previous[2],
                b_lens,
                delay_current,
                base_speed=0.081 + ((structure_gain - 1.0) * 0.007),
                delay_coupling=0.026 * delay_gain,
                attenuation=_clamp(0.996 - ((energy - 1.0) * 0.002), 0.988, 0.998),
            ),
        ]

        rgb_previous = rgb_current
        rgb_current = next_rgb
        delay_previous = delay_current
        delay_current = next_delay

    r_max = _max_abs(rgb_current[0])
    g_max = _max_abs(rgb_current[1])
    b_max = _max_abs(rgb_current[2])
    d_max = _max_abs(delay_current)

    rgb_pixels: list[list[tuple[int, int, int]]] = []
    delay_pixels: list[list[int]] = []
    red_pixels: list[list[int]] = []
    green_pixels: list[list[int]] = []
    blue_pixels: list[list[int]] = []
    channel_totals = [0.0, 0.0, 0.0]
    delay_total = 0.0
    brightness_total = 0.0
    spectral_split_total = 0.0
    for y in range(height):
        rgb_row: list[tuple[int, int, int]] = []
        delay_row: list[int] = []
        red_row: list[int] = []
        green_row: list[int] = []
        blue_row: list[int] = []
        for x in range(width):
            delay_norm = delay_current[y][x] / d_max
            red = rgb_current[0][y][x] / r_max
            green = rgb_current[1][y][x] / g_max
            blue = rgb_current[2][y][x] / b_max
            red_channel = int(round(255.0 * (0.5 + 0.5 * math.tanh(red * 2.8))))
            green_channel = int(round(255.0 * (0.5 + 0.5 * math.tanh(green * 2.8))))
            blue_channel = int(round(255.0 * (0.5 + 0.5 * math.tanh(blue * 2.8))))

            red_byte = int(
                round(255.0 * (0.5 + 0.5 * math.tanh((red * 2.7) + (delay_norm * 0.34))))
            )
            green_byte = int(
                round(255.0 * (0.5 + 0.5 * math.tanh((green * 2.5) + (delay_norm * 0.16))))
            )
            blue_byte = int(
                round(
                    255.0
                    * (
                        0.5
                        + 0.5
                        * math.tanh((blue * 2.9) - (delay_norm * 0.24) - (spectral_tilt * 0.22))
                    )
                )
            )
            red_byte = int(round(red_byte + (spectral_tilt * 12.0)))
            green_byte = int(round(green_byte - (abs(spectral_tilt) * 6.0)))
            blue_byte = int(round(blue_byte - (spectral_tilt * 12.0)))
            delay_byte = int(
                round(255.0 * (0.5 + 0.5 * math.tanh(delay_norm * 3.2 * delay_gain)))
            )

            rgb_row.append(
                (
                    int(_clamp(red_byte, 0, 255)),
                    int(_clamp(green_byte, 0, 255)),
                    int(_clamp(blue_byte, 0, 255)),
                )
            )
            delay_row.append(int(_clamp(delay_byte, 0, 255)))
            red_row.append(int(_clamp(red_channel, 0, 255)))
            green_row.append(int(_clamp(green_channel, 0, 255)))
            blue_row.append(int(_clamp(blue_channel, 0, 255)))
            channel_totals[0] += rgb_row[-1][0]
            channel_totals[1] += rgb_row[-1][1]
            channel_totals[2] += rgb_row[-1][2]
            delay_total += delay_row[-1]
            brightness_total += sum(rgb_row[-1]) / 3.0
            spectral_split_total += abs(rgb_row[-1][0] - rgb_row[-1][2])
        rgb_pixels.append(rgb_row)
        delay_pixels.append(delay_row)
        red_pixels.append(red_row)
        green_pixels.append(green_row)
        blue_pixels.append(blue_row)

    out_path = Path(config.out_path)
    delay_out_path = Path(config.delay_out_path)
    meta_out_path = Path(config.meta_out_path)
    aux_paths = _auxiliary_output_paths(out_path)
    source_map_pixels = _build_source_map(sources, width, height)

    _write_rgb_image(out_path, rgb_pixels)
    _write_delay_image(delay_out_path, delay_pixels)
    _write_delay_image(aux_paths["red"], red_pixels)
    _write_delay_image(aux_paths["green"], green_pixels)
    _write_delay_image(aux_paths["blue"], blue_pixels)
    _write_rgb_image(aux_paths["source_map"], source_map_pixels)

    metadata = {
        "prompt": prompt,
        "seed": seed,
        "width": width,
        "height": height,
        "steps": steps,
        "tuning": {
            "energy": energy,
            "delay_gain": delay_gain,
            "structure_gain": structure_gain,
            "spectral_tilt": spectral_tilt,
            "ring_scale": ring_scale,
        },
        "layers": ["R", "G", "B", "D"],
        "delay_role": "arrival-order, damping, and phase modulation",
        "layout": "hub-and-ring splash garden",
        "modules": ["core", "style", "detail", "lighting"],
        "guide": {
            "enabled": bool(guide_stats["enabled"]),
            "label": config.guide_label,
            "luma_mean": guide_stats["luma_mean"],
            "edge_mean": guide_stats["edge_mean"],
            "edge_peak": guide_stats["edge_peak"],
        },
        "sources": [asdict(source) for source in sources],
        "output_files": {
            "rgb": str(out_path),
            "delay": str(delay_out_path),
            "red": str(aux_paths["red"]),
            "green": str(aux_paths["green"]),
            "blue": str(aux_paths["blue"]),
            "source_map": str(aux_paths["source_map"]),
        },
        "amplitude_stats": {
            "r_max_abs": r_max,
            "g_max_abs": g_max,
            "b_max_abs": b_max,
            "d_max_abs": d_max,
        },
        "pixel_stats": {
            "brightness_mean": brightness_total / (width * height * 255.0),
            "delay_mean": delay_total / (width * height * 255.0),
            "red_mean": channel_totals[0] / (width * height * 255.0),
            "green_mean": channel_totals[1] / (width * height * 255.0),
            "blue_mean": channel_totals[2] / (width * height * 255.0),
            "spectral_split": spectral_split_total / (width * height * 255.0),
        },
        "source_count": len(sources),
    }

    meta_out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_out_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["meta_path"] = str(meta_out_path)
    return metadata


def run_splash_garden_bench(config: SplashBenchConfig) -> dict[str, object]:
    prompt = config.prompt.strip() or "unseen vision"
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_slug = _slugify(prompt)
    cases = _case_library()
    runs: list[dict[str, object]] = []

    for case in cases:
        base_name = f"{prompt_slug}-{case.slug}"
        result = render_splash_garden(
            SplashGardenConfig(
                prompt=prompt,
                width=config.width,
                height=config.height,
                steps=config.steps + case.extra_steps,
                out_path=str(out_dir / f"{base_name}.png"),
                delay_out_path=str(out_dir / f"{base_name}-delay.png"),
                meta_out_path=str(out_dir / f"{base_name}.json"),
                energy=case.energy,
                delay_gain=case.delay_gain,
                structure_gain=case.structure_gain,
                spectral_tilt=case.spectral_tilt,
                ring_scale=case.ring_scale,
                guide_label=config.guide_label,
                guide_luma=config.guide_luma,
                guide_edges=config.guide_edges,
            )
        )
        runs.append(
            {
                "case": case.slug,
                "title": case.title,
                "description": case.description,
                "files": result["output_files"],
                "meta_path": result["meta_path"],
                "pixel_stats": result["pixel_stats"],
                "tuning": result["tuning"],
            }
        )

    manifest = {
        "prompt": prompt,
        "width": config.width,
        "height": config.height,
        "base_steps": config.steps,
        "out_dir": str(out_dir),
        "cases": runs,
        "highlights": {
            "most_delay_driven": max(runs, key=lambda run: run["pixel_stats"]["delay_mean"])["case"],
            "most_structural": max(
                runs, key=lambda run: run["tuning"]["structure_gain"]
            )["case"],
            "most_spectral": max(
                runs, key=lambda run: run["pixel_stats"]["spectral_split"]
            )["case"],
        },
    }

    manifest_path = out_dir / f"{prompt_slug}-bench.json"
    report_path = _write_bench_report(out_dir, manifest)
    manifest["manifest_path"] = str(manifest_path)
    manifest["report_path"] = str(report_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
