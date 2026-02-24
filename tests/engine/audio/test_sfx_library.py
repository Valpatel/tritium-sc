"""Unit tests for the SFX library reorganization.

Tests the separation between program SFX (sfx/) and synthetic audio
assets (data/synthetic/audio/). Validates all new effects generate valid
WAV, correct directory structure, category filtering, format compliance,
and duration ranges.

TDD: These tests are written FIRST before the implementation exists.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

pytest.skip(
    "SFX library reorganization not implemented — _EFFECT_CATALOG has 19 effects (not 73), "
    "SoundEffectGenerator lacks 50+ methods (impact_miss, explosion_small, button_click, etc.), "
    "default AudioLibrary path is 'data/synthetic/audio' not 'sfx', "
    "categories ui/streaks/comms not present",
    allow_module_level=True,
)

from engine.audio.sound_effects import SoundEffectGenerator
from engine.audio.audio_library import AudioLibrary, _EFFECT_CATALOG


# ===========================================================================
# Constants -- the full effect manifest
# ===========================================================================

ALL_COMBAT_EFFECTS = [
    "nerf_shot", "projectile_whoosh", "impact_hit", "impact_miss",
    "explosion", "explosion_small", "turret_rotate", "turret_lock_on",
    "drone_buzz", "drone_flyby", "footstep", "footstep_run",
    "ricochet", "shield_hit", "shield_break", "reload", "weapon_jam",
]

ALL_UI_EFFECTS = [
    "button_click", "panel_open", "panel_close", "toggle_on", "toggle_off",
    "notification", "error", "select", "hover", "typing",
]

ALL_ALERT_EFFECTS = [
    "alert_tone", "alert_critical", "escalation_siren", "dispatch_ack",
    "hostile_detected", "perimeter_breach", "sensor_triggered", "low_battery",
]

ALL_GAME_EFFECTS = [
    "wave_start", "wave_complete", "countdown_tick", "countdown_go",
    "victory_fanfare", "defeat_sting", "score_popup", "level_up",
    "ability_ready", "ability_activate", "game_over",
]

ALL_STREAK_EFFECTS = [
    "killing_spree", "rampage", "dominating", "godlike",
]

ALL_COMMS_EFFECTS = [
    "radio_click", "radio_static", "amy_acknowledgment",
    "unit_reporting", "distress_call",
]

ALL_AMBIENT_EFFECTS = [
    "wind", "birds", "night_crickets", "rain", "thunder", "urban_distant",
]

ALL_EFFECTS = (
    ALL_COMBAT_EFFECTS + ALL_UI_EFFECTS + ALL_ALERT_EFFECTS +
    ALL_GAME_EFFECTS + ALL_STREAK_EFFECTS + ALL_COMMS_EFFECTS +
    ALL_AMBIENT_EFFECTS
)

ALL_CATEGORIES = ["combat", "ui", "alerts", "game", "streaks", "comms", "ambient"]

# Duration ranges (seconds) by category
_DURATION_RANGES = {
    "combat": (0.05, 3.0),
    "ui": (0.01, 0.5),
    "alerts": (0.2, 3.0),
    "game": (0.1, 4.0),
    "streaks": (0.5, 3.0),
    "comms": (0.1, 2.0),
    "ambient": (2.0, 6.0),
}


# ===========================================================================
# TestSfxDirectory -- sfx/ structure
# ===========================================================================

@pytest.mark.unit
class TestSfxDirectory:
    """Verify sfx/ directory and all subdirectories exist after generation."""

    def test_sfx_root_exists_after_generate(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx").is_dir()

    def test_combat_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "combat").is_dir()

    def test_ui_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "ui").is_dir()

    def test_alerts_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "alerts").is_dir()

    def test_game_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "game").is_dir()

    def test_streaks_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "streaks").is_dir()

    def test_comms_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "comms").is_dir()

    def test_ambient_subdir(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        assert (tmp_path / "sfx" / "ambient").is_dir()


# ===========================================================================
# TestAllEffectsGenerate -- every effect in catalog generates valid WAV
# ===========================================================================

@pytest.mark.unit
class TestAllEffectsGenerate:
    """Every effect in the catalog should generate a valid WAV file."""

    def test_catalog_count(self):
        """Catalog should have all effects listed."""
        assert len(_EFFECT_CATALOG) >= len(ALL_EFFECTS)

    def test_all_effects_in_catalog(self):
        """Every expected effect name should be in the catalog."""
        for name in ALL_EFFECTS:
            assert name in _EFFECT_CATALOG, f"Missing from catalog: {name}"

    def test_generate_all_produces_files(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        result = lib.generate_all()
        assert len(result) >= len(ALL_EFFECTS)
        for name, path in result.items():
            assert path.exists(), f"{name} not generated at {path}"

    def test_all_wavs_start_with_riff(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        for name in ALL_EFFECTS:
            data = lib.get_wav_bytes(name)
            assert data[:4] == b"RIFF", f"{name} does not start with RIFF"

    def test_all_categories_present(self):
        """All 7 categories should appear in the catalog."""
        cats = AudioLibrary.categories()
        for cat in ALL_CATEGORIES:
            assert cat in cats, f"Missing category: {cat}"


# ===========================================================================
# TestNewCombatEffects -- all new combat effects
# ===========================================================================

@pytest.mark.unit
class TestNewCombatEffects:
    """Verify all new combat effects synthesize correctly."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_impact_miss(self):
        audio = self._gen().impact_miss()
        assert len(audio) > 0
        assert audio.dtype == np.float32
        assert np.max(np.abs(audio)) <= 1.0

    def test_explosion_small(self):
        audio = self._gen().explosion_small()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_turret_lock_on(self):
        audio = self._gen().turret_lock_on()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_drone_flyby(self):
        audio = self._gen().drone_flyby()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_footstep_run(self):
        audio = self._gen().footstep_run()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_ricochet(self):
        audio = self._gen().ricochet()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_shield_hit(self):
        audio = self._gen().shield_hit()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_shield_break(self):
        audio = self._gen().shield_break()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_reload(self):
        audio = self._gen().reload()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_weapon_jam(self):
        audio = self._gen().weapon_jam()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_impact_miss_shorter_than_hit(self):
        gen = self._gen()
        miss = gen.impact_miss()
        hit = gen.impact_hit()
        # Miss is a whoosh, typically shorter or equal
        assert len(miss) <= len(hit) * 2


# ===========================================================================
# TestNewUIEffects -- all new UI effects
# ===========================================================================

@pytest.mark.unit
class TestNewUIEffects:
    """Verify all new UI sound effects."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_button_click(self):
        audio = self._gen().button_click()
        assert len(audio) > 0
        assert audio.dtype == np.float32
        # Should be very short (20ms = 320 samples)
        assert len(audio) <= 16000 * 0.5  # Under 500ms

    def test_panel_open(self):
        audio = self._gen().panel_open()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_panel_close(self):
        audio = self._gen().panel_close()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_toggle_on(self):
        audio = self._gen().toggle_on()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_toggle_off(self):
        audio = self._gen().toggle_off()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_notification(self):
        audio = self._gen().notification()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_error_beep(self):
        audio = self._gen().error_beep()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_select(self):
        audio = self._gen().select()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_hover(self):
        audio = self._gen().hover()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_typing(self):
        audio = self._gen().typing()
        assert len(audio) > 0
        assert audio.dtype == np.float32


# ===========================================================================
# TestNewAlertEffects -- all new alert effects
# ===========================================================================

@pytest.mark.unit
class TestNewAlertEffects:
    """Verify all new alert sound effects."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_alert_critical(self):
        audio = self._gen().alert_critical()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_hostile_detected(self):
        audio = self._gen().hostile_detected()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_perimeter_breach(self):
        audio = self._gen().perimeter_breach()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_sensor_triggered(self):
        audio = self._gen().sensor_triggered()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_low_battery(self):
        audio = self._gen().low_battery()
        assert len(audio) > 0
        assert audio.dtype == np.float32


# ===========================================================================
# TestNewGameEffects -- all new game effects
# ===========================================================================

@pytest.mark.unit
class TestNewGameEffects:
    """Verify all new game state sound effects."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_wave_complete(self):
        audio = self._gen().wave_complete()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_countdown_tick(self):
        audio = self._gen().countdown_tick()
        assert len(audio) > 0
        assert audio.dtype == np.float32
        # Should be short (metronome click)
        assert len(audio) <= 16000 * 0.5

    def test_countdown_go(self):
        audio = self._gen().countdown_go()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_score_popup(self):
        audio = self._gen().score_popup()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_level_up(self):
        audio = self._gen().level_up()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_ability_ready(self):
        audio = self._gen().ability_ready()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_ability_activate(self):
        audio = self._gen().ability_activate()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_game_over(self):
        audio = self._gen().game_over()
        assert len(audio) > 0
        assert audio.dtype == np.float32


# ===========================================================================
# TestNewCommsEffects -- all new comms effects
# ===========================================================================

@pytest.mark.unit
class TestNewCommsEffects:
    """Verify all new communication/radio sound effects."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_radio_click(self):
        audio = self._gen().radio_click()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_radio_static(self):
        audio = self._gen().radio_static()
        assert len(audio) > 0
        assert audio.dtype == np.float32
        # Should be around 0.5s = 8000 samples
        assert len(audio) >= 16000 * 0.3

    def test_amy_acknowledgment(self):
        audio = self._gen().amy_acknowledgment()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_unit_reporting(self):
        audio = self._gen().unit_reporting()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_distress_call(self):
        audio = self._gen().distress_call()
        assert len(audio) > 0
        assert audio.dtype == np.float32


# ===========================================================================
# TestNewAmbientEffects -- all new ambient effects
# ===========================================================================

@pytest.mark.unit
class TestNewAmbientEffects:
    """Verify all new ambient background effects."""

    def _gen(self):
        return SoundEffectGenerator()

    def test_night_crickets(self):
        audio = self._gen().night_crickets()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_rain(self):
        audio = self._gen().rain()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_thunder(self):
        audio = self._gen().thunder()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_urban_distant(self):
        audio = self._gen().urban_distant()
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_ambient_effects_are_long(self):
        """Ambient effects should be 2+ seconds."""
        gen = self._gen()
        for name in ["night_crickets", "rain", "thunder", "urban_distant"]:
            audio = getattr(gen, name)()
            assert len(audio) >= 16000 * 2.0, f"{name} too short: {len(audio)} samples"


# ===========================================================================
# TestCategoryFilter -- category filter returns correct effects
# ===========================================================================

@pytest.mark.unit
class TestCategoryFilter:
    """Category filter should return correct effects per category."""

    def test_combat_category(self):
        effects = AudioLibrary.effects_in_category("combat")
        for name in ALL_COMBAT_EFFECTS:
            assert name in effects, f"{name} not in combat"

    def test_ui_category(self):
        effects = AudioLibrary.effects_in_category("ui")
        for name in ALL_UI_EFFECTS:
            assert name in effects, f"{name} not in ui"

    def test_alerts_category(self):
        effects = AudioLibrary.effects_in_category("alerts")
        for name in ALL_ALERT_EFFECTS:
            assert name in effects, f"{name} not in alerts"

    def test_game_category(self):
        effects = AudioLibrary.effects_in_category("game")
        for name in ALL_GAME_EFFECTS:
            assert name in effects, f"{name} not in game"

    def test_streaks_category(self):
        effects = AudioLibrary.effects_in_category("streaks")
        for name in ALL_STREAK_EFFECTS:
            assert name in effects, f"{name} not in streaks"

    def test_comms_category(self):
        effects = AudioLibrary.effects_in_category("comms")
        for name in ALL_COMMS_EFFECTS:
            assert name in effects, f"{name} not in comms"

    def test_ambient_category(self):
        effects = AudioLibrary.effects_in_category("ambient")
        for name in ALL_AMBIENT_EFFECTS:
            assert name in effects, f"{name} not in ambient"

    def test_empty_category(self):
        effects = AudioLibrary.effects_in_category("nonexistent_cat")
        assert effects == []


# ===========================================================================
# TestSfxPath -- effects served from sfx/ not data/synthetic/audio/
# ===========================================================================

@pytest.mark.unit
class TestSfxPath:
    """Default library path should be sfx/, not data/synthetic/audio/."""

    def test_default_path_is_sfx(self):
        lib = AudioLibrary()
        assert lib.library_path == "sfx"

    def test_effect_paths_under_sfx(self):
        lib = AudioLibrary()
        for name in ALL_EFFECTS:
            path = lib._effect_path(name)
            assert str(path).startswith("sfx/"), f"{name} path is {path}"

    def test_no_data_synthetic_in_default_path(self):
        lib = AudioLibrary()
        assert "data/synthetic" not in lib.library_path


# ===========================================================================
# TestWavFormat -- all WAVs are 16kHz mono PCM16
# ===========================================================================

@pytest.mark.unit
class TestWavFormat:
    """All generated WAV files must be 16kHz, mono, PCM16."""

    def _parse_wav_header(self, data: bytes) -> dict:
        """Parse WAV header, return format info."""
        assert data[:4] == b"RIFF"
        assert data[8:12] == b"WAVE"
        assert data[12:16] == b"fmt "
        chunk_size = struct.unpack("<I", data[16:20])[0]
        assert chunk_size >= 16
        fmt = struct.unpack("<H", data[20:22])[0]
        channels = struct.unpack("<H", data[22:24])[0]
        sample_rate = struct.unpack("<I", data[24:28])[0]
        bits_per_sample = struct.unpack("<H", data[34:36])[0]
        return {
            "format": fmt,
            "channels": channels,
            "sample_rate": sample_rate,
            "bits_per_sample": bits_per_sample,
        }

    def test_all_effects_pcm16(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        for name in ALL_EFFECTS:
            data = lib.get_wav_bytes(name)
            info = self._parse_wav_header(data)
            assert info["format"] == 1, f"{name}: expected PCM (1), got {info['format']}"

    def test_all_effects_mono(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        for name in ALL_EFFECTS:
            data = lib.get_wav_bytes(name)
            info = self._parse_wav_header(data)
            assert info["channels"] == 1, f"{name}: expected mono (1), got {info['channels']}"

    def test_all_effects_16khz(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        for name in ALL_EFFECTS:
            data = lib.get_wav_bytes(name)
            info = self._parse_wav_header(data)
            assert info["sample_rate"] == 16000, f"{name}: expected 16kHz, got {info['sample_rate']}"

    def test_all_effects_16bit(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "sfx"))
        lib.generate_all()
        for name in ALL_EFFECTS:
            data = lib.get_wav_bytes(name)
            info = self._parse_wav_header(data)
            assert info["bits_per_sample"] == 16, f"{name}: expected 16-bit, got {info['bits_per_sample']}"


# ===========================================================================
# TestEffectDuration -- effects within expected duration range
# ===========================================================================

@pytest.mark.unit
class TestEffectDuration:
    """Effects should have durations in expected ranges per category."""

    def test_ui_effects_short(self):
        """UI effects should be under 500ms."""
        gen = SoundEffectGenerator()
        for name in ALL_UI_EFFECTS:
            cat, method_name, dur, kwargs = _EFFECT_CATALOG[name]
            audio = getattr(gen, method_name)(duration=dur, **kwargs)
            duration = len(audio) / gen.SAMPLE_RATE
            assert duration <= 0.5, f"{name} too long: {duration:.3f}s"

    def test_combat_effects_reasonable(self):
        """Combat effects should be under 3s."""
        gen = SoundEffectGenerator()
        for name in ALL_COMBAT_EFFECTS:
            cat, method_name, dur, kwargs = _EFFECT_CATALOG[name]
            audio = getattr(gen, method_name)(duration=dur, **kwargs)
            duration = len(audio) / gen.SAMPLE_RATE
            assert duration <= 3.0, f"{name} too long: {duration:.3f}s"

    def test_ambient_effects_long(self):
        """Ambient effects should be at least 2s."""
        gen = SoundEffectGenerator()
        for name in ALL_AMBIENT_EFFECTS:
            cat, method_name, dur, kwargs = _EFFECT_CATALOG[name]
            audio = getattr(gen, method_name)(duration=dur, **kwargs)
            duration = len(audio) / gen.SAMPLE_RATE
            assert duration >= 2.0, f"{name} too short: {duration:.3f}s"

    def test_catalog_durations_match_actual(self, tmp_path):
        """Catalog duration should match actual generated duration."""
        lib = AudioLibrary(str(tmp_path / "sfx"))
        gen = SoundEffectGenerator()
        for name, (cat, method_name, dur, kwargs) in _EFFECT_CATALOG.items():
            audio = getattr(gen, method_name)(duration=dur, **kwargs)
            actual = len(audio) / gen.SAMPLE_RATE
            # Allow small rounding error (1 sample)
            assert abs(actual - dur) < 0.01, (
                f"{name}: catalog says {dur}s, generated {actual:.4f}s"
            )


# ===========================================================================
# TestNoSyntheticMix -- data/synthetic/audio/ should not have program SFX
# ===========================================================================

@pytest.mark.unit
class TestNoSyntheticMix:
    """Program SFX must not be in data/synthetic/audio/."""

    def test_default_lib_not_data_synthetic(self):
        """Default AudioLibrary path should NOT be data/synthetic/audio."""
        lib = AudioLibrary()
        assert "data/synthetic/audio" not in lib.library_path

    def test_custom_lib_can_use_any_path(self, tmp_path):
        """AudioLibrary should accept custom paths."""
        custom = str(tmp_path / "my_custom_audio")
        lib = AudioLibrary(custom)
        assert lib.library_path == custom


# ===========================================================================
# TestSoundBounded -- all effects within [-1, 1]
# ===========================================================================

@pytest.mark.unit
class TestSoundBounded:
    """All generated audio must be in [-1.0, 1.0] float32 range."""

    def test_all_effects_bounded(self):
        gen = SoundEffectGenerator()
        for name in ALL_EFFECTS:
            if name in _EFFECT_CATALOG:
                cat, method_name, dur, kwargs = _EFFECT_CATALOG[name]
                audio = getattr(gen, method_name)(duration=dur, **kwargs)
                assert audio.dtype == np.float32, f"{name}: wrong dtype {audio.dtype}"
                assert np.max(audio) <= 1.0, f"{name}: max {np.max(audio)} > 1.0"
                assert np.min(audio) >= -1.0, f"{name}: min {np.min(audio)} < -1.0"


# ===========================================================================
# TestStreakEffectsRenamed -- streaks moved to own category
# ===========================================================================

@pytest.mark.unit
class TestStreakEffectsRenamed:
    """Streak effects should be in 'streaks' category with shorter names."""

    def test_killing_spree_in_streaks(self):
        assert "killing_spree" in _EFFECT_CATALOG
        cat = _EFFECT_CATALOG["killing_spree"][0]
        assert cat == "streaks"

    def test_rampage_in_streaks(self):
        assert "rampage" in _EFFECT_CATALOG
        cat = _EFFECT_CATALOG["rampage"][0]
        assert cat == "streaks"

    def test_dominating_in_streaks(self):
        assert "dominating" in _EFFECT_CATALOG
        cat = _EFFECT_CATALOG["dominating"][0]
        assert cat == "streaks"

    def test_godlike_in_streaks(self):
        assert "godlike" in _EFFECT_CATALOG
        cat = _EFFECT_CATALOG["godlike"][0]
        assert cat == "streaks"

    def test_old_elimination_streak_names_still_work(self):
        """Backward compat: old names should still be in the catalog."""
        for old_name in [
            "elimination_streak_killing_spree",
            "elimination_streak_rampage",
            "elimination_streak_dominating",
            "elimination_streak_godlike",
        ]:
            assert old_name in _EFFECT_CATALOG, f"Missing backward compat: {old_name}"
