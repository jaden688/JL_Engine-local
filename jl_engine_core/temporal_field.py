from __future__ import annotations

import math
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any, Dict, List, Optional


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo


def apply_temporal_sampling_bias(
    temp: float, top_p: float, temporal_state: Optional[Dict[str, Any]]
) -> tuple[float, float]:
    state = temporal_state or {}
    root_id = str(state.get("root_id") or "").strip().lower()
    transition_bias = _clamp(state.get("transition_bias", 0.0), -1.0, 1.0)
    novelty_pressure = _clamp(state.get("novelty_pressure", 0.0))
    loop_pressure = _clamp(state.get("loop_pressure", 0.0))

    root_biases = {
        "playful_energy": (0.03, 0.02),
        "reassuring_bond": (-0.02, -0.02),
        "focused_drive": (-0.04, -0.03),
        "analytic_distance": (-0.05, -0.04),
        "bright_triumph": (0.05, 0.03),
        "protective_guard": (-0.03, -0.02),
    }
    root_temp_bias, root_top_p_bias = root_biases.get(root_id, (0.0, 0.0))

    biased_temp = temp + root_temp_bias + (novelty_pressure * 0.03) - (loop_pressure * 0.04)
    biased_top_p = (
        top_p
        + root_top_p_bias
        + max(0.0, transition_bias) * 0.015
        - (loop_pressure * 0.025)
    )
    return max(0.1, min(1.5, biased_temp)), max(0.1, min(1.0, biased_top_p))


class WarmLaneCPUChannel:
    """
    CPU reference scorer plus Windows warm-lane detection scaffolding.

    v1 intentionally keeps computation on CPU while surfacing whether the local
    machine appears to have a warm AMD/Windows AI lane available for a later
    backend implementation.
    """

    def __init__(self) -> None:
        self._open = False
        self._probe = self.probe_backend()

    def probe_backend(self) -> Dict[str, Any]:
        if os.name != "nt":
            return {
                "backend_name": "cpu_shim",
                "warm_lane_detected": False,
                "status": "fallback",
                "reason": "non_windows_host",
            }

        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        has_vitis = (system32 / "vitis-ai-runtime.dll").exists()
        has_radeonml = (system32 / "RadeonML_DirectML.dll").exists()
        has_directml = (system32 / "directml.dll").exists()
        has_onnxruntime = (system32 / "onnxruntime.dll").exists()
        warm_lane_detected = bool(has_vitis or has_radeonml)

        reason_parts: list[str] = []
        if warm_lane_detected:
            reason_parts.append("amd_ryzen_ai_lane_detected")
        elif has_directml or has_onnxruntime:
            reason_parts.append("generic_windows_inference_dlls_present")
        else:
            reason_parts.append("no_vendor_warm_lane_signature")

        reason_parts.append("using_cpu_reference_scorer")
        return {
            "backend_name": "cpu_shim",
            "warm_lane_detected": warm_lane_detected,
            "status": "ok" if warm_lane_detected else "fallback",
            "reason": ", ".join(reason_parts),
        }

    def open_channel(self) -> Dict[str, Any]:
        self._open = True
        return dict(self._probe)

    def close_channel(self) -> None:
        self._open = False

    def score_field(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._open:
            self.open_channel()
        return _cpu_score_field(payload)


class TemporalFieldController:
    def __init__(
        self,
        *,
        interval_seconds: float = 0.2,
        backend: Optional[WarmLaneCPUChannel] = None,
    ) -> None:
        self._interval_seconds = max(0.05, float(interval_seconds or 0.2))
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._ticks = 0
        self._last_tick_at: datetime | None = None
        self._started_monotonic: float | None = None
        self._backend = backend or WarmLaneCPUChannel()
        self._backend_status = self._backend.probe_backend()
        self._agent_name: str | None = None
        self._compiled_ontology: Dict[str, Any] = {}
        self._turn_context: Dict[str, Any] = {}
        self._state: Dict[str, Any] = {
            "root_id": None,
            "root_label": None,
            "family_id": None,
            "family_label": None,
            "scene_id": None,
            "scene_label": None,
            "facet_id": None,
            "facet_label": None,
            "sensation": None,
            "inertia": 0.25,
            "transition_bias": 0.0,
            "novelty_pressure": 0.0,
            "loop_pressure": 0.0,
            "scene_age_ticks": 0,
            "field_age_seconds": 0.0,
            "tick_count": 0,
            "sampling_ready": False,
        }

    def set_ontology(
        self,
        agent_name: str,
        wheel: Optional[Dict[str, Any]],
        palette: Optional[List[Dict[str, Any]]],
    ) -> None:
        compiled = _compile_ontology(agent_name, wheel, palette)
        with self._lock:
            changed = agent_name != self._agent_name or compiled != self._compiled_ontology
            self._agent_name = agent_name
            self._compiled_ontology = compiled
            if changed:
                self._state.update(
                    {
                        "root_id": compiled.get("baseline_root_id"),
                        "root_label": compiled.get("baseline_root_label"),
                        "family_id": compiled.get("baseline_family_id"),
                        "family_label": compiled.get("baseline_family_label"),
                        "scene_id": None,
                        "scene_label": None,
                        "facet_id": None,
                        "facet_label": None,
                        "sensation": None,
                        "inertia": 0.25,
                        "transition_bias": 0.0,
                        "novelty_pressure": 0.0,
                        "loop_pressure": 0.0,
                        "scene_age_ticks": 0,
                        "field_age_seconds": 0.0,
                        "tick_count": 0,
                        "sampling_ready": False,
                    }
                )

    def update_turn_context(
        self,
        *,
        signals: Optional[Dict[str, Any]] = None,
        aperture_state: Optional[Dict[str, Any]] = None,
        behavior_profile: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._turn_context = {
                "signals": dict(signals or {}),
                "aperture_state": dict(aperture_state or {}),
                "behavior_profile": behavior_profile or "",
            }

    def start_loop(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._backend_status = self._backend.open_channel()
            self._stop.clear()
            self._started_monotonic = monotonic()
            # Prime the field once so first-turn telemetry is available before the
            # background thread has waited a full interval.
            self._tick_once()
            self._thread = Thread(
                target=self._worker,
                daemon=True,
                name="temporal-field-loop",
            )
            self._thread.start()

    def stop_loop(self, join_timeout_seconds: float = 1.0) -> None:
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread and thread.is_alive():
            thread.join(timeout=max(0.1, float(join_timeout_seconds or 1.0)))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
                self._stop.clear()
                self._started_monotonic = None
                self._backend.close_channel()

    def sample_field(self) -> Dict[str, Any]:
        with self._lock:
            sampled = dict(self._state)
            sampled["sampling_ready"] = self._is_sampling_ready_locked()
            sampled["temporal_backend"] = dict(self._backend_status)
            return sampled

    def get_loop_status(self) -> Dict[str, Any]:
        with self._lock:
            running = bool(self._thread and self._thread.is_alive())
            return {
                "running": running,
                "interval_seconds": self._interval_seconds,
                "ticks": self._ticks,
                "sampling_ready": self._is_sampling_ready_locked(),
                "last_tick_at": self._last_tick_at.isoformat()
                if isinstance(self._last_tick_at, datetime)
                else None,
                "thread_name": self._thread.name if self._thread else None,
            }

    def get_backend_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._backend_status)

    def pulse(self) -> None:
        self._tick_once()

    def _is_sampling_ready_locked(self) -> bool:
        tick_count = int(self._state.get("tick_count", 0) or 0)
        field_age_seconds = float(self._state.get("field_age_seconds", 0.0) or 0.0)
        # Require a slightly warmer field before sampling can steer generation.
        # This keeps first-turn behavior deterministic across slower machines
        # and avoids temporal bias jumping in before the background field has
        # had a meaningful chance to stabilize.
        minimum_live_age = round(max(self._interval_seconds * 2.4, 0.12), 3)
        return tick_count >= 3 and field_age_seconds >= minimum_live_age

    def _worker(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._tick_once()
        with self._lock:
            self._thread = None

    def _tick_once(self) -> None:
        with self._lock:
            payload = {
                "ontology": deepcopy(self._compiled_ontology),
                "state": deepcopy(self._state),
                "turn_context": deepcopy(self._turn_context),
                "tick_count": self._ticks + 1,
                "interval_seconds": self._interval_seconds,
            }
        scored = self._backend.score_field(payload)
        with self._lock:
            self._state.update(scored)
            self._ticks += 1
            self._state["tick_count"] = self._ticks
            if self._started_monotonic is None:
                self._started_monotonic = monotonic()
            self._state["field_age_seconds"] = round(
                max(0.0, monotonic() - self._started_monotonic),
                3,
            )
            self._state["sampling_ready"] = self._is_sampling_ready_locked()
            self._last_tick_at = datetime.now(UTC)


def _compile_ontology(
    agent_name: str,
    wheel: Optional[Dict[str, Any]],
    palette: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    palette_map = {
        str(entry.get("id") or "").strip(): dict(entry)
        for entry in (palette or [])
        if isinstance(entry, dict) and str(entry.get("id") or "").strip()
    }
    compiled: Dict[str, Any] = {
        "agent_name": agent_name,
        "baseline_root_id": None,
        "baseline_root_label": None,
        "baseline_family_id": None,
        "baseline_family_label": None,
        "candidates": [],
    }
    if isinstance(wheel, dict) and isinstance(wheel.get("roots"), list):
        compiled["baseline_root_id"] = str(wheel.get("baseline_root") or "").strip() or None
        compiled["baseline_family_id"] = str(wheel.get("baseline_family") or "").strip() or None
        for root_index, root in enumerate(wheel.get("roots") or []):
            if not isinstance(root, dict):
                continue
            root_id = str(root.get("id") or "").strip() or f"root_{root_index}"
            root_label = str(root.get("label") or root_id).strip()
            root_weight = float(root.get("default_weight", 0.5) or 0.5)
            if compiled["baseline_root_id"] == root_id and not compiled["baseline_root_label"]:
                compiled["baseline_root_label"] = root_label
            for family_index, family in enumerate(root.get("families") or []):
                if not isinstance(family, dict):
                    continue
                family_id = str(family.get("id") or "").strip() or f"family_{family_index}"
                family_label = str(family.get("label") or family_id).strip()
                family_weight = float(family.get("default_weight", 0.5) or 0.5)
                repeat_penalty = float(family.get("repeat_penalty", 0.2) or 0.2)
                cooldown_turns = int(family.get("cooldown_turns", 1) or 1)
                if compiled["baseline_family_id"] == family_id and not compiled["baseline_family_label"]:
                    compiled["baseline_family_label"] = family_label
                sensation = family.get("sensation") if isinstance(family.get("sensation"), dict) else {}
                for scene_index, scene in enumerate(family.get("scenes") or []):
                    if not isinstance(scene, dict):
                        continue
                    scene_id = str(scene.get("id") or "").strip() or f"scene_{scene_index}"
                    scene_label = str(scene.get("label") or scene_id).strip()
                    scene_weight = float(scene.get("default_weight", 0.5) or 0.5)
                    facet_ids = [
                        str(fid).strip()
                        for fid in (scene.get("facet_ids") or [])
                        if str(fid).strip()
                    ]
                    for facet_index, facet_id in enumerate(facet_ids):
                        facet = palette_map.get(facet_id) or {}
                        compiled["candidates"].append(
                            {
                                "candidate_id": f"{scene_id}:{facet_id or facet_index}",
                                "root_id": root_id,
                                "root_label": root_label,
                                "family_id": family_id,
                                "family_label": family_label,
                                "scene_id": scene_id,
                                "scene_label": scene_label,
                                "facet_id": facet_id,
                                "facet_label": str(facet.get("label") or facet_id).strip(),
                                "sensation": deepcopy(sensation),
                                "weight": root_weight * family_weight * scene_weight,
                                "repeat_penalty": repeat_penalty,
                                "cooldown_turns": cooldown_turns,
                                "sampling_bias": deepcopy(facet.get("sampling_bias") or {}),
                            }
                        )
    if compiled["candidates"]:
        if not compiled["baseline_root_label"] and compiled["baseline_root_id"]:
            for candidate in compiled["candidates"]:
                if candidate["root_id"] == compiled["baseline_root_id"]:
                    compiled["baseline_root_label"] = candidate["root_label"]
                    break
        if not compiled["baseline_family_label"] and compiled["baseline_family_id"]:
            for candidate in compiled["candidates"]:
                if candidate["family_id"] == compiled["baseline_family_id"]:
                    compiled["baseline_family_label"] = candidate["family_label"]
                    break
        return compiled

    for index, facet in enumerate(palette_map.values()):
        facet_id = str(facet.get("id") or "").strip() or f"facet_{index}"
        compiled["candidates"].append(
            {
                "candidate_id": facet_id,
                "root_id": "default_temporal_root",
                "root_label": agent_name,
                "family_id": "default_temporal_family",
                "family_label": "Default temporal family",
                "scene_id": f"{facet_id}_scene",
                "scene_label": str(facet.get("label") or facet_id).strip(),
                "facet_id": facet_id,
                "facet_label": str(facet.get("label") or facet_id).strip(),
                "sensation": {},
                "weight": 0.5,
                "repeat_penalty": 0.2,
                "cooldown_turns": 1,
                "sampling_bias": deepcopy(facet.get("sampling_bias") or {}),
            }
        )
    compiled["baseline_root_id"] = "default_temporal_root"
    compiled["baseline_root_label"] = agent_name
    compiled["baseline_family_id"] = "default_temporal_family"
    compiled["baseline_family_label"] = "Default temporal family"
    return compiled


def _cpu_score_field(payload: Dict[str, Any]) -> Dict[str, Any]:
    ontology = payload.get("ontology") if isinstance(payload.get("ontology"), dict) else {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    turn_context = (
        payload.get("turn_context") if isinstance(payload.get("turn_context"), dict) else {}
    )
    signals = turn_context.get("signals") if isinstance(turn_context.get("signals"), dict) else {}
    behavior_profile = str(turn_context.get("behavior_profile") or "").strip().lower()
    tick_count = int(payload.get("tick_count", 0) or 0)
    interval_seconds = float(payload.get("interval_seconds", 0.2) or 0.2)
    candidates = ontology.get("candidates") if isinstance(ontology.get("candidates"), list) else []

    if not candidates:
        return {
            "root_id": ontology.get("baseline_root_id"),
            "root_label": ontology.get("baseline_root_label"),
            "family_id": ontology.get("baseline_family_id"),
            "family_label": ontology.get("baseline_family_label"),
            "scene_id": None,
            "scene_label": None,
            "facet_id": None,
            "facet_label": None,
            "sensation": None,
            "inertia": _clamp(state.get("inertia", 0.2)),
            "transition_bias": 0.0,
            "novelty_pressure": 0.0,
            "loop_pressure": 0.0,
            "scene_age_ticks": int(state.get("scene_age_ticks", 0) or 0),
        }

    current_candidate_id = str(state.get("candidate_id") or "").strip()
    current = next((c for c in candidates if c.get("candidate_id") == current_candidate_id), None)
    if current is None:
        current = next(
            (
                c
                for c in candidates
                if c.get("root_id") == ontology.get("baseline_root_id")
                and c.get("family_id") == ontology.get("baseline_family_id")
            ),
            candidates[0],
        )
        current_candidate_id = str(current.get("candidate_id") or "")

    previous_scene_age = int(state.get("scene_age_ticks", 0) or 0)
    previous_inertia = _clamp(state.get("inertia", 0.25))
    loop_pressure = _clamp(previous_scene_age / 10.0)
    novelty_pressure = _clamp(max(0, previous_scene_age - 2) / 8.0)

    sentiment = float(signals.get("sentiment", 0.0) or 0.0)
    arousal = _clamp(signals.get("arousal", 0.0))
    confusion = _clamp(signals.get("confusion", 0.0))
    directive = bool(signals.get("directive"))

    def candidate_bias(candidate: Dict[str, Any], idx: int) -> float:
        root_id = str(candidate.get("root_id") or "").lower()
        family_id = str(candidate.get("family_id") or "").lower()
        scene_id = str(candidate.get("scene_id") or "").lower()
        bias = float(candidate.get("weight", 0.5) or 0.5)
        ambient = math.sin((tick_count * interval_seconds * 0.85) + (idx * 1.17)) * 0.035
        ambient += math.cos((tick_count * interval_seconds * 0.45) + idx) * 0.02
        bias += ambient

        if "playful" in root_id or "playful" in family_id:
            bias += max(0.0, sentiment) * 0.09 + arousal * 0.04
        if "bright" in root_id or "celebrat" in family_id:
            bias += max(0.0, sentiment) * 0.08 + max(0.0, arousal - 0.4) * 0.08
        if "focus" in root_id or "focus" in family_id or "guidance" in scene_id:
            bias += confusion * 0.10 + (0.08 if directive else 0.0)
        if "execution" in scene_id:
            bias += confusion * 0.06 + (0.10 if directive else 0.0)
        if "analytic" in root_id or "analytic" in family_id:
            bias += (1.0 - _clamp(abs(sentiment))) * 0.04 + (1.0 - arousal) * 0.04
        if "reassur" in root_id or "reassur" in family_id:
            bias += max(0.0, -sentiment) * 0.07 + confusion * 0.05
        if "protect" in root_id or "protect" in family_id:
            bias += max(0.0, -sentiment) * 0.05 + confusion * 0.08

        if behavior_profile == "expressive" and (
            "playful" in root_id or "bright" in root_id or "celebrat" in family_id
        ):
            bias += 0.03

        if candidate.get("candidate_id") == current_candidate_id:
            bias += previous_inertia * 0.08
            bias -= loop_pressure * float(candidate.get("repeat_penalty", 0.2) or 0.2)
        else:
            bias += novelty_pressure * 0.07
        return bias

    scored = [(candidate_bias(candidate, idx), candidate) for idx, candidate in enumerate(candidates)]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate = scored[0]

    current_score = next(
        (score for score, candidate in scored if candidate.get("candidate_id") == current_candidate_id),
        best_score,
    )
    threshold = 0.05 + max(0.0, previous_inertia - novelty_pressure) * 0.08
    should_switch = (
        best_candidate.get("candidate_id") != current_candidate_id and best_score > (current_score + threshold)
    )

    if should_switch:
        active = best_candidate
        scene_age_ticks = 0
        inertia = 0.18
        loop_pressure = max(0.0, loop_pressure * 0.5)
        novelty_pressure = max(0.05, novelty_pressure * 0.3)
    else:
        active = current
        scene_age_ticks = previous_scene_age + 1
        inertia = _clamp((previous_inertia * 0.82) + 0.12)
        loop_pressure = _clamp(scene_age_ticks / 10.0)
        novelty_pressure = _clamp(max(0, scene_age_ticks - 2) / 8.0)

    best_alt_score = next(
        (
            score
            for score, candidate in scored
            if candidate.get("candidate_id") != active.get("candidate_id")
        ),
        best_score,
    )
    active_score = next(
        (
            score
            for score, candidate in scored
            if candidate.get("candidate_id") == active.get("candidate_id")
        ),
        best_score,
    )
    transition_bias = max(
        -1.0,
        min(1.0, (best_alt_score - active_score) + novelty_pressure - (inertia * 0.25)),
    )
    sensation = active.get("sensation") if isinstance(active.get("sensation"), dict) else {}

    return {
        "candidate_id": active.get("candidate_id"),
        "root_id": active.get("root_id"),
        "root_label": active.get("root_label"),
        "family_id": active.get("family_id"),
        "family_label": active.get("family_label"),
        "scene_id": active.get("scene_id"),
        "scene_label": active.get("scene_label"),
        "facet_id": active.get("facet_id"),
        "facet_label": active.get("facet_label"),
        "sensation": deepcopy(sensation),
        "inertia": inertia,
        "transition_bias": round(transition_bias, 3),
        "novelty_pressure": round(novelty_pressure, 3),
        "loop_pressure": round(loop_pressure, 3),
        "scene_age_ticks": scene_age_ticks,
        "sampling_bias": deepcopy(active.get("sampling_bias") or {}),
    }
