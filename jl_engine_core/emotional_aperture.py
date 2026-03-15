from .logging_setup import get_logger

logger = get_logger(__name__)

from typing import Optional
from .cognitive_gears import GearType, get_gear_modifiers


class EmotionalAperture:
    """
    Implements the Emotional Aperture Module as per the JL-EMO-APERTURE-MKIV spec.
    This module calculates a single score to determine the engine's expressive mode.
    """

    def __init__(self, drive_type: GearType = "spur", agent_state: Optional[dict] = None):
        self.drive_type: GearType = drive_type
        self._current_emotion: Optional[str] = None
        self._current_emotion_meta: Optional[dict] = None
        self.agent_state: Optional[dict] = agent_state
        self.emotion_palette: list[dict] = []
        self.emotion_wheel: dict = {}
        self._recent_emotion_ids: list[str] = []
        self._focus_level: float = 0.0
        self._overload_level: float = 0.0
        self._drift_bias: float = 0.0
        self._recent_sentiment: float = 0.0
        self._last_state = self._build_state(0.25, "GUARDED", self.MODIFIERS["GUARDED"])

    MODIFIERS = {
        "CLOSED": {
            "temperature": 0.10,
            "top_p": 0.20,
            "agent_amplitude": 0.05,
            "creativity_bias": 0.05,
            "expressiveness": 0.06,
        },
        "GUARDED": {
            "temperature": 0.25,
            "top_p": 0.45,
            "agent_amplitude": 0.20,
            "creativity_bias": 0.18,
            "expressiveness": 0.22,
        },
        "BALANCED": {
            "temperature": 0.45,
            "top_p": 0.70,
            "agent_amplitude": 0.45,
            "creativity_bias": 0.45,
            "expressiveness": 0.50,
        },
        "OPEN": {
            "temperature": 0.65,
            "top_p": 0.85,
            "agent_amplitude": 0.70,
            "creativity_bias": 0.75,
            "expressiveness": 0.78,
        },
        "WIDE_OPEN": {
            "temperature": 0.85,
            "top_p": 0.95,
            "agent_amplitude": 0.95,
            "creativity_bias": 0.98,
            "expressiveness": 1.00,
        },
    }

    def _get_mode_from_score(self, score: float) -> str:
        if score <= 0.12:
            return "CLOSED"
        if score <= 0.28:
            return "GUARDED"
        if score <= 0.55:
            return "BALANCED"
        if score <= 0.78:
            return "OPEN"
        return "WIDE_OPEN"

    def set_drive_type(self, drive_type: GearType) -> None:
        if self.drive_type != drive_type:
            logger.info("[Aperture] drive_type set to %s", drive_type)
            self.drive_type = drive_type

    def set_emotion_model(self, palette: Optional[list], wheel: Optional[dict] = None) -> None:
        """
        Inject a agent-specific emotion palette. Palette entries are dicts with:
        - id (str), label (str), style (str)
        - score_range: [min, max] in 0..1
        - intensity: desired 0..1 energy
        - sentiment: 'positive' | 'negative' | 'neutral' | 'any'
        - sampling_bias: {temperature: float, top_p: float} (optional)
        """
        base_palette = [p for p in (palette or []) if isinstance(p, dict)]
        self.emotion_wheel = wheel if isinstance(wheel, dict) else {}
        self._recent_emotion_ids = []

        if self.emotion_wheel:
            expanded_palette = self._build_palette_from_wheel(base_palette, self.emotion_wheel)
        else:
            expanded_palette = base_palette

        if not expanded_palette:
            self.emotion_palette = []
            self.emotion_wheel = {}
            self._current_emotion_meta = None
            self._current_emotion = None
            self._write_agent_emotion(None, None)
            return
        self.emotion_palette = expanded_palette

    def set_emotion_palette(self, palette: Optional[list]) -> None:
        self.set_emotion_model(palette, None)

    def set_agent_state(self, agent_state: Optional[dict]) -> None:
        """Attach a canonical agent_state dict so emotion writes land in one place."""
        self.agent_state = agent_state
        if agent_state is not None and not isinstance(agent_state, dict):
            self.agent_state = None

    def get_drive_type(self) -> GearType:
        return self.drive_type

    def get_gear_modifiers(self):
        return get_gear_modifiers(self.drive_type)

    def reset(self):
        """Reset aperture state back to a safe baseline."""
        self._current_emotion = None
        self._current_emotion_meta = None
        self._recent_emotion_ids = []
        self._write_agent_emotion(None, None)
        self._focus_level = 0.0
        self._overload_level = 0.0
        self._drift_bias = 0.0
        self._recent_sentiment = 0.0
        self._last_state = self._build_state(0.25, "GUARDED", self.MODIFIERS["GUARDED"])

    def get_state(self) -> dict:
        """Return the last computed aperture state."""
        return dict(self._last_state)

    def update_from_signals(
        self, behavior_state=None, gait: str = "walk", rhythm: str = "flop", **signals
    ):
        """
        Update aperture using a simplified signal set from the main app.
        Missing signals fall back to neutral defaults to avoid crashes.
        """
        behavior_intensity = getattr(behavior_state, "expressiveness", 0.5)
        gait_range = self._map_gait_to_range(gait)
        rhythm_variability = self._map_rhythm_to_variability(rhythm)

        signal_payload = {
            "behavior_intensity": behavior_intensity,
            "agent_vividness": signals.get("agent_vividness", 0.6),
            "safety_mode": signals.get("safety_mode", True),
            "drift_pressure": signals.get("drift_pressure", 0.0),
            "drift_bias": signals.get("drift_bias", 0.0),
            "user_sentiment": signals.get("user_sentiment", 0.0),
            "conversation_pacing": signals.get("conversation_pacing", 0.5),
            "memory_density": signals.get("memory_density", 0.0),
            "gait_range": gait_range,
            "rhythm_variability": rhythm_variability,
            "aperture_bias": signals.get("aperture_bias", 0.0),
        }

        computed = self.compute(signal_payload)
        self._focus_level, self._overload_level = self._derive_focus_overload(signal_payload)
        self._last_state = self._build_state(
            computed.get("score", 0.0),
            computed.get("mode", "GUARDED"),
            computed.get("modifiers"),
        )

        selected_emotion = self._select_emotion(
            score=self._last_state.get("score", 0.0),
            signals=signal_payload,
            behavior_state=behavior_state,
        )
        self._apply_selected_emotion(selected_emotion)
        return self._last_state

    def update_from_signal(
        self, emotion: Optional[str] = None, focus_delta: float = 0.0, overload_delta: float = 0.0
    ):
        """
        Update aperture from new measurements. This method is gear-aware:
        the gear determines how fast and how stably aperture changes.
        """
        mods = self.get_gear_modifiers()

        # 1) update discrete emotion with some inertia
        if emotion is not None:
            self._current_emotion = emotion

        # 2) update continuous dimensions with gear-scaled deltas
        # reaction_speed: how strongly we apply the incoming change
        scaled_focus = focus_delta * mods.reaction_speed
        scaled_overload = overload_delta * mods.reaction_speed

        # mode_inertia reduces how fast we move away from prior state
        inertia = mods.mode_inertia
        inv_inertia = 1.0 - inertia

        # apply like a leaky integrator
        self._focus_level = self._focus_level * inertia + scaled_focus * inv_inertia
        self._overload_level = self._overload_level * inertia + scaled_overload * inv_inertia

        # clamp to 0..1
        self._focus_level = max(0.0, min(1.0, self._focus_level))
        self._overload_level = max(0.0, min(1.0, self._overload_level))
        self._last_state["focus_level"] = self._focus_level
        self._last_state["overload_level"] = self._overload_level
        # Keep emotion info exposed even when only deltas are applied.
        self._last_state["emotion"] = self._current_emotion
        self._last_state["emotion_meta"] = self._current_emotion_meta
        self._write_agent_emotion(self._current_emotion, self._current_emotion_meta)

    def apply_output_feedback(
        self, output_text: str, rhythm_state: Optional[dict] = None, gait: str | None = None
    ):
        """
        Slow-drift feedback loop driven by the assistant's own output.
        Rhythm variability and gait energy modulate the drift rate.
        """
        if not isinstance(output_text, str):
            return
        sentiment = self._quick_sentiment(output_text)
        variability = 0.0
        if isinstance(rhythm_state, dict):
            variability = float(rhythm_state.get("variability", 0.0) or 0.0)
        gait_push = 0.0
        if gait:
            gait_lower = gait.lower()
            if gait_lower in ("trot", "gallop", "sprint"):
                gait_push = 0.05
            elif gait_lower == "idle":
                gait_push = -0.05

        drift_rate = 0.015 + variability * 0.08 + abs(gait_push) * 0.5
        self._drift_bias = max(-0.25, min(0.25, self._drift_bias * 0.9 + sentiment * drift_rate))
        self._recent_sentiment = sentiment
        # Nudge focus/overload gently toward the emotional inertia
        self._focus_level = max(0.0, min(1.0, self._focus_level + max(0.0, sentiment) * 0.05))
        self._overload_level = max(
            0.0, min(1.0, self._overload_level + max(0.0, -sentiment) * 0.05)
        )
        self._last_state["drift_bias"] = self._drift_bias

    def inject_drift_bias(self, bias: float):
        """Allow the supervisor/state manager to apply a slow drift bias."""
        try:
            bias = float(bias)
        except (TypeError, ValueError):
            return
        self._drift_bias = max(-0.35, min(0.35, bias))

    def get_focus_level(self) -> float:
        return self._focus_level

    def get_overload_level(self) -> float:
        return self._overload_level

    def compute(self, signals: dict) -> dict:
        """
        Computes the aperture score and resolves the final state.
        `signals` is a dictionary containing the nine input signals.
        """
        # Use .get() to provide defaults for missing signals
        behavior_intensity = signals.get("behavior_intensity", 0.5)
        agent_vividness = signals.get("agent_vividness", 0.5)
        safety_mode = signals.get("safety_mode", True)
        drift_pressure = signals.get("drift_pressure", 0.0)
        user_sentiment = signals.get("user_sentiment", 0.0)
        conversation_pacing = signals.get("conversation_pacing", 0.5)
        memory_density = signals.get("memory_density", 0.0)
        gait_range = signals.get("gait_range", 0.3)  # Default to WALK
        rhythm_variability = signals.get("rhythm_variability", 0.5)

        # Per spec failure mode: if any signal is missing, default to GUARDED.
        # .get() with defaults handles this, but an explicit check for None is safer.
        if any(
            signals.get(k) is None
            for k in [
                "behavior_intensity",
                "agent_vividness",
                "safety_mode",
                "drift_pressure",
                "user_sentiment",
                "conversation_pacing",
                "memory_density",
                "gait_range",
                "rhythm_variability",
            ]
        ):
            return {
                "score": 0.25,
                "mode": "GUARDED",
                "modifiers": self.MODIFIERS["GUARDED"],
            }

        # Calculate weighted score
        score = (
            (behavior_intensity * 0.18)
            + (agent_vividness * 0.16)
            + (user_sentiment * 0.22)
            + (conversation_pacing * 0.08)
            + (memory_density * 0.12)
            + (gait_range * 0.06)
            + (rhythm_variability * 0.08)
            - (drift_pressure * 0.20)
        )

        # Apply bias from supervisor
        score += signals.get("aperture_bias", 0.0)
        score += signals.get("drift_bias", 0.0)
        score += self._drift_bias

        # Clamp score to be within [0, 1]
        score = max(0.0, min(1.0, score))

        # Apply safety clamp
        if safety_mode:
            # Loosen safety clamp to allow more expressiveness while still preventing max-open.
            score = min(score, 0.60)

        # Resolve mode and modifiers
        mode = self._get_mode_from_score(score)
        modifiers = self.MODIFIERS.get(mode)

        return {
            "score": score,
            "mode": mode,
            "modifiers": modifiers,
        }

    def _derive_focus_overload(self, signals: dict) -> tuple[float, float]:
        """Derive focus and overload levels from the same signals used to compute aperture."""

        def clamp(val: float) -> float:
            return max(0.0, min(1.0, val))

        # Focus rises with deliberate behavior, vivid agent, steady rhythm, and positive sentiment.
        focus = (
            signals.get("behavior_intensity", 0.5) * 0.45
            + (1.0 - signals.get("rhythm_variability", 0.5)) * 0.20
            + max(0.0, signals.get("conversation_pacing", 0.5) - 0.4) * 0.15
            + max(0.0, signals.get("agent_vividness", 0.5) - 0.3) * 0.10
            + max(0.0, signals.get("user_sentiment", 0.0)) * 0.10
            - signals.get("drift_pressure", 0.0) * 0.20
        )

        # Overload rises with drift pressure, dense memory retrieval, chaotic rhythm, and negative sentiment.
        overload = (
            signals.get("drift_pressure", 0.0) * 0.35
            + signals.get("memory_density", 0.0) * 0.25
            + signals.get("gait_range", 0.3) * 0.10
            + signals.get("rhythm_variability", 0.5) * 0.10
            + max(0.0, -signals.get("user_sentiment", 0.0)) * 0.12
            + max(0.0, 0.5 - signals.get("conversation_pacing", 0.5)) * 0.08
        )

        return clamp(focus), clamp(overload)

    def _quick_sentiment(self, text: str) -> float:
        """Tiny sentiment heuristic to avoid heavy dependencies."""
        if not text or not isinstance(text, str):
            return 0.0
        lowered = text.lower()
        positives = sum(1 for k in ("great", "glad", "yes", "sure", "love", "!") if k in lowered)
        negatives = sum(
            1 for k in ("sorry", "no", "cannot", "frustrated", "confused", "?") if k in lowered
        )
        raw = (positives - negatives) / 6.0
        return max(-1.0, min(1.0, raw))

    def _build_state(self, score: float, mode: str, modifiers: dict | None = None) -> dict:
        mods = modifiers or self.MODIFIERS.get(mode, self.MODIFIERS["BALANCED"])
        return {
            "score": score,
            "mode": mode,
            "modifiers": mods,
            "temp": mods.get("temperature", 0.45),
            "top_p": mods.get("top_p", 0.7),
            "focus_level": self._focus_level,
            "overload_level": self._overload_level,
            "emotion": self._current_emotion,
            "emotion_meta": self._current_emotion_meta,
            "emotion_root": (
                self._current_emotion_meta.get("root_label")
                if isinstance(self._current_emotion_meta, dict)
                else None
            ),
            "emotion_family": (
                self._current_emotion_meta.get("family_label")
                if isinstance(self._current_emotion_meta, dict)
                else None
            ),
            "emotion_scene": (
                self._current_emotion_meta.get("scene_label")
                if isinstance(self._current_emotion_meta, dict)
                else None
            ),
            "emotion_sensation": (
                (self._current_emotion_meta.get("sensation") or {}).get("label")
                if isinstance(self._current_emotion_meta, dict)
                and isinstance(self._current_emotion_meta.get("sensation"), dict)
                else None
            ),
            "drift_bias": self._drift_bias,
        }

    def _map_gait_to_range(self, gait: str) -> float:
        """Map gait string to a normalized range value used by the aperture compute step."""
        return {
            "idle": 0.1,
            "walk": 0.3,
            "trot": 0.55,
            "gallop": 0.75,
            "sprint": 0.9,
        }.get(gait, 0.3)

    def _map_rhythm_to_variability(self, rhythm: str) -> float:
        """Map rhythm name to a variability score."""
        return {
            "flop": 0.2,
            "flip": 0.35,
            "twitch": 0.55,
            "cascade": 0.45,
            "stutter": 0.3,
            "burst": 0.65,
        }.get(rhythm, 0.4)

    def _build_palette_from_wheel(self, palette: list[dict], wheel: dict) -> list[dict]:
        by_id = {}
        for entry in palette:
            entry_id = str(entry.get("id") or "").strip()
            if entry_id:
                by_id[entry_id] = dict(entry)

        def _float_or(default: float, value) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def _expand_refs(
            refs,
            *,
            root_meta: dict | None = None,
            family_meta: dict | None = None,
            scene_meta: dict | None = None,
        ) -> list[dict]:
            if not isinstance(refs, list):
                return []
            built: list[dict] = []
            for ref in refs:
                overrides = ref if isinstance(ref, dict) else {}
                facet_id = (
                    str(ref.get("id") or "").strip()
                    if isinstance(ref, dict)
                    else str(ref or "").strip()
                )
                base = dict(by_id.get(facet_id) or {})
                if not base and isinstance(ref, dict):
                    base = dict(ref)
                if not base:
                    continue
                entry = dict(base)
                if overrides:
                    entry.update(overrides)
                entry["facet_id"] = facet_id or str(entry.get("id") or "").strip()

                if root_meta:
                    entry["root_id"] = root_meta.get("id")
                    entry["root_label"] = root_meta.get("label")
                    entry["root_default_weight"] = _float_or(1.0, root_meta.get("default_weight", 1.0))
                if family_meta:
                    entry["family_id"] = family_meta.get("id")
                    entry["family_label"] = family_meta.get("label")
                    entry["family_default_weight"] = _float_or(
                        1.0, family_meta.get("default_weight", 1.0)
                    )
                if scene_meta:
                    entry["scene_id"] = scene_meta.get("id")
                    entry["scene_label"] = scene_meta.get("label")
                    entry["scene_default_weight"] = _float_or(
                        1.0, scene_meta.get("default_weight", 1.0)
                    )

                repeat_penalty = None
                cooldown_turns = None
                sensation = None
                for meta in (scene_meta, family_meta, root_meta):
                    if not isinstance(meta, dict):
                        continue
                    if repeat_penalty is None and meta.get("repeat_penalty") is not None:
                        repeat_penalty = meta.get("repeat_penalty")
                    if cooldown_turns is None and meta.get("cooldown_turns") is not None:
                        cooldown_turns = meta.get("cooldown_turns")
                    if sensation is None and isinstance(meta.get("sensation"), dict):
                        sensation = dict(meta.get("sensation"))
                if "repeat_penalty" not in entry and repeat_penalty is not None:
                    entry["repeat_penalty"] = repeat_penalty
                if "cooldown_turns" not in entry and cooldown_turns is not None:
                    entry["cooldown_turns"] = cooldown_turns
                if sensation and "sensation" not in entry:
                    entry["sensation"] = sensation

                built.append(entry)
            return built

        expanded: list[dict] = []
        roots = wheel.get("roots")
        if isinstance(roots, list):
            for root in roots:
                if not isinstance(root, dict):
                    continue
                root_meta = {
                    "id": str(root.get("id") or "").strip(),
                    "label": str(root.get("label") or root.get("id") or "").strip(),
                    "default_weight": root.get("default_weight", 1.0),
                    "repeat_penalty": root.get("repeat_penalty"),
                    "cooldown_turns": root.get("cooldown_turns"),
                    "sensation": root.get("sensation"),
                }
                families = root.get("families") or []
                for family in families:
                    if not isinstance(family, dict):
                        continue
                    family_meta = {
                        "id": str(family.get("id") or "").strip(),
                        "label": str(family.get("label") or family.get("id") or "").strip(),
                        "default_weight": family.get("default_weight", 1.0),
                        "repeat_penalty": family.get("repeat_penalty"),
                        "cooldown_turns": family.get("cooldown_turns"),
                        "sensation": family.get("sensation"),
                    }
                    scenes = family.get("scenes") or []
                    if isinstance(scenes, list) and scenes:
                        for scene in scenes:
                            if not isinstance(scene, dict):
                                continue
                            scene_meta = {
                                "id": str(scene.get("id") or "").strip(),
                                "label": str(scene.get("label") or scene.get("id") or "").strip(),
                                "default_weight": scene.get("default_weight", 1.0),
                                "repeat_penalty": scene.get("repeat_penalty"),
                                "cooldown_turns": scene.get("cooldown_turns"),
                                "sensation": scene.get("sensation"),
                            }
                            expanded.extend(
                                _expand_refs(
                                    scene.get("facets") or scene.get("facet_ids") or [],
                                    root_meta=root_meta,
                                    family_meta=family_meta,
                                    scene_meta=scene_meta,
                                )
                            )
                    else:
                        expanded.extend(
                            _expand_refs(
                                family.get("facets") or family.get("facet_ids") or [],
                                root_meta=root_meta,
                                family_meta=family_meta,
                            )
                        )
        else:
            families = wheel.get("families")
            if not isinstance(families, list):
                return palette
            for family in families:
                if not isinstance(family, dict):
                    continue
                family_meta = {
                    "id": str(family.get("id") or "").strip(),
                    "label": str(family.get("label") or family.get("id") or "").strip(),
                    "default_weight": family.get("default_weight", 1.0),
                    "repeat_penalty": family.get("repeat_penalty"),
                    "cooldown_turns": family.get("cooldown_turns"),
                    "sensation": family.get("sensation"),
                }
                expanded.extend(
                    _expand_refs(family.get("facets") or family.get("facet_ids") or [], family_meta=family_meta)
                )

        return expanded or palette

    def _select_emotion(self, score: float, signals: dict, behavior_state=None) -> Optional[dict]:
        """Pick the best-matching emotion entry from the palette based on score, sentiment, and intensity."""
        if not self.emotion_palette:
            return None

        sentiment = signals.get("user_sentiment", 0.0) if isinstance(signals, dict) else 0.0
        behavior_intensity = (
            signals.get("behavior_intensity") if isinstance(signals, dict) else None
        )
        if behavior_intensity is None and behavior_state is not None:
            behavior_intensity = getattr(behavior_state, "expressiveness", 0.5)
        if behavior_intensity is None:
            behavior_intensity = 0.5

        best_entry = None
        best_score = -1.0

        for entry in self.emotion_palette:
            if not isinstance(entry, dict):
                continue

            min_score, max_score = (entry.get("score_range") or [0.0, 1.0])[:2]
            try:
                min_score = float(min_score)
                max_score = float(max_score)
            except (TypeError, ValueError) as exc:
                logger.debug("[Aperture] Invalid score range in palette: %s", exc, exc_info=True)
                min_score, max_score = 0.0, 1.0
            if min_score > max_score:
                min_score, max_score = max_score, min_score
            span = max(0.1, max_score - min_score)
            center = min_score + span / 2.0
            score_fit = max(0.0, 1.0 - abs(score - center) / (span / 2.0))

            target_intensity = float(entry.get("intensity", 0.5) or 0.5)
            intensity_fit = max(0.0, 1.0 - abs(behavior_intensity - target_intensity))

            sentiment_pref = str(entry.get("sentiment", "any")).lower()
            sentiment_fit = 1.0
            if sentiment_pref != "any":
                if sentiment_pref == "positive":
                    sentiment_fit = 1.0 if sentiment >= 0.1 else 0.55
                elif sentiment_pref == "negative":
                    sentiment_fit = 1.0 if sentiment <= -0.1 else 0.55
                elif sentiment_pref == "neutral":
                    sentiment_fit = 1.0 if abs(sentiment) < 0.25 else 0.55

            combined = (score_fit * 0.5) + (intensity_fit * 0.3) + (sentiment_fit * 0.2)

            family_weight = entry.get("family_default_weight")
            try:
                if family_weight is not None:
                    combined *= max(0.5, min(1.5, float(family_weight)))
            except (TypeError, ValueError):
                pass
            root_weight = entry.get("root_default_weight")
            try:
                if root_weight is not None:
                    combined *= max(0.5, min(1.5, float(root_weight)))
            except (TypeError, ValueError):
                pass
            scene_weight = entry.get("scene_default_weight")
            try:
                if scene_weight is not None:
                    combined *= max(0.5, min(1.5, float(scene_weight)))
            except (TypeError, ValueError):
                pass

            baseline_root = str(self.emotion_wheel.get("baseline_root") or "").strip()
            if baseline_root and str(entry.get("root_id") or "").strip() == baseline_root:
                combined += 0.03
            baseline_family = str(self.emotion_wheel.get("baseline_family") or "").strip()
            if baseline_family and str(entry.get("family_id") or "").strip() == baseline_family:
                combined += 0.03

            entry_id = str(entry.get("facet_id") or entry.get("id") or "").strip()
            try:
                cooldown_turns = max(0, int(entry.get("cooldown_turns", 0) or 0))
            except (TypeError, ValueError):
                cooldown_turns = 0
            try:
                repeat_penalty = max(0.0, min(0.95, float(entry.get("repeat_penalty", 0.0) or 0.0)))
            except (TypeError, ValueError):
                repeat_penalty = 0.0
            if entry_id and cooldown_turns > 0 and entry_id in self._recent_emotion_ids[-cooldown_turns:]:
                combined *= 1.0 - (repeat_penalty or 0.35)

            if combined > best_score:
                best_score = combined
                best_entry = entry

        return best_entry

    def _apply_selected_emotion(self, entry: Optional[dict]) -> None:
        """Persist selected emotion into state for telemetry/logging."""
        if not entry:
            self._current_emotion = None
            self._current_emotion_meta = None
            self._last_state["emotion"] = None
            self._last_state["emotion_meta"] = None
            self._last_state["emotion_root"] = None
            self._last_state["emotion_family"] = None
            self._last_state["emotion_scene"] = None
            self._last_state["emotion_sensation"] = None
            self._write_agent_emotion(None, None)
            return

        label = entry.get("label") or entry.get("id")
        sensation = entry.get("sensation") if isinstance(entry.get("sensation"), dict) else None
        meta = {
            "id": entry.get("id"),
            "facet_id": entry.get("facet_id") or entry.get("id"),
            "label": label,
            "style": entry.get("style"),
            "sampling_bias": entry.get("sampling_bias"),
            "intensity": entry.get("intensity"),
            "sentiment": entry.get("sentiment"),
            "score_range": entry.get("score_range"),
            "root_id": entry.get("root_id"),
            "root_label": entry.get("root_label"),
            "family_id": entry.get("family_id"),
            "family_label": entry.get("family_label"),
            "scene_id": entry.get("scene_id"),
            "scene_label": entry.get("scene_label"),
            "sensation": sensation,
            "repeat_penalty": entry.get("repeat_penalty"),
            "cooldown_turns": entry.get("cooldown_turns"),
        }
        self._current_emotion = label
        self._current_emotion_meta = meta
        self._last_state["emotion"] = label
        self._last_state["emotion_meta"] = meta
        self._last_state["emotion_root"] = meta.get("root_label") or meta.get("root_id")
        self._last_state["emotion_family"] = meta.get("family_label") or meta.get("family_id")
        self._last_state["emotion_scene"] = meta.get("scene_label") or meta.get("scene_id")
        self._last_state["emotion_sensation"] = (
            sensation.get("label") if isinstance(sensation, dict) else None
        )
        recent_id = str(meta.get("facet_id") or meta.get("id") or "").strip()
        if recent_id:
            self._recent_emotion_ids.append(recent_id)
            self._recent_emotion_ids = self._recent_emotion_ids[-8:]
        self._write_agent_emotion(label, meta)

    def _write_agent_emotion(self, label: Optional[str], meta: Optional[dict]) -> None:
        """Commit the canonical emotion fields into the shared agent_state dict, if provided."""
        if isinstance(self.agent_state, dict):
            self.agent_state["emotion"] = label
            self.agent_state["emotion_meta"] = meta
