# Julian MetaMorph

`Julian MetaMorph` is a standalone GitHub scout, quarry, and skill-forging project.

It is built to do four things well:

1. Crawl GitHub repositories with a real API client.
2. Index approved code fragments into a local SQLite FTS quarry.
3. Scout the quarry for task-relevant solutions.
4. Forge reusable Python skill modules with provenance manifests.

## Julian

Julian is a first-class profile in this project. He is not implied and he is not a stub.
The profile gives the forge and CLI a concrete operating voice and mission.

## Quick start

```powershell
cd C:\Users\J_lin\JulianMetaMorph
$env:PYTHONPATH = "src"
python -m julian_metamorph.cli julian-prompt --task "find auth middleware patterns"
python -m julian_metamorph.cli search-repos "oauth token python"
python -m julian_metamorph.cli ingest-repo psf/requests --max-files 20
python -m julian_metamorph.cli scout-task "session cookie auth flow"
python -m julian_metamorph.cli forge-skill auth_capsule "session cookie auth flow"
python -m julian_metamorph.cli splash-garden "unseen vision radar" --out data/splash_garden.png --delay-out data/splash_garden_delay.png
python -m julian_metamorph.cli splash-garden-bench "unseen vision radar" --out-dir data/splash_garden_bench
python -m julian_metamorph.cli serve
```

The bench now emits an `index.html` report with RGB, delay, source-map, and channel plates for each case.
The live viewer is available at `http://127.0.0.1:8765/ripple-scope` while the service is running.

## Click launcher

Double-click [Launch_Julian_MetaMorph.bat](/C:/Users/J_lin/JulianMetaMorph/Launch_Julian_MetaMorph.bat) to start the standalone service and open the local FastAPI docs.

## GitHub token

Set `GITHUB_TOKEN` to increase rate limits:

```powershell
$env:GITHUB_TOKEN = "ghp_..."
```

## Output

- SQLite quarry: `data/quarry.db`
- Forged skill modules: `skills/`
- Provenance manifests: `skills/*.json`
- Splash Garden renders: `data/splash_garden*.png`
- Splash Garden benches: `data/splash_garden_bench/`
- Splash Garden report: `data/splash_garden_bench/index.html`
- Ripple Scope live outputs: `data/live/`
