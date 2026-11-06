"""Custom-color tests — colors come from ~/.flow/color.json only.

`config.json` carries just the `custom_color` switch; `color.json` carries
`primary_color`/`secondary_color`/`tertiary_color` (rich styles incl. #hex /
rgb()). Invalid values degrade to the theme fallback, writes merge with any
existing color.json content, and `maybe_reload` applies on-disk edits live.
"""

import json

import pytest

from backend import config


@pytest.fixture(autouse=True)
def restore_colors():
    """Snapshot every color-related global; earlier tests leak via _load_config."""
    before = (
        config.CustomColor,
        dict(config._CUSTOM),
        dict(config._STYLE),
        config._custom_mtime,
        config._color_mtime,
        list(config._LIVE_NAMESPACES),
        config.Primary,
        config.Secondary,
        config.Tertiary,
    )
    yield
    (
        config.CustomColor,
        config._custom_mtime,
        config._color_mtime,
    ) = (before[0], before[3], before[4])
    config._LIVE_NAMESPACES[:] = before[5]
    config._CUSTOM = before[1]
    config._STYLE = before[2]
    (config.Primary, config.Secondary, config.Tertiary) = (before[6], before[7], before[8])


@pytest.fixture
def theme_pair():
    yield


def _conf(tmp_path, custom, colors=None, theme=None):
    conf = tmp_path / "config.json"
    data = {"custom_color": custom}
    if theme:
        data.update(theme)
    conf.write_text(json.dumps(data))
    colf = tmp_path / "color.json"
    if colors is not None:
        colf.write_text(json.dumps(colors))
    return conf, colf


def _patch_files(monkeypatch, conf, colf):
    monkeypatch.setattr(config, "CONFIG_FILE", conf)
    monkeypatch.setattr(config, "COLOR_FILE", colf)
    monkeypatch.setattr(config, "_custom_mtime", None)
    monkeypatch.setattr(config, "_color_mtime", None)


def test_off_uses_theme(theme_pair):
    config.CustomColor = False
    config._render()
    assert config.Primary == (config._sgr(config._STYLE["primary"]) or config.CYAN)


def test_hex_override(theme_pair):
    config.CustomColor = True
    config._CUSTOM["primary"] = "#7f4dff"
    config._render()
    assert "\x1b[38;2;127;77;255m" in config.Primary


def test_rgb_override(theme_pair):
    config.CustomColor = True
    config._CUSTOM["secondary"] = "rgb(254,184,255)"
    config._render()
    assert "\x1b[38;2;254;184;255m" in config.Secondary


def test_rgb_with_spaces(theme_pair):
    """User-typed 'rgb(160, 208, 202)' must parse, not silently fall back."""
    config.CustomColor = True
    config._CUSTOM["primary"] = "rgb(160, 208, 202)"
    config._render()
    assert "\x1b[38;2;160;208;202m" in config.Primary


def test_unset_slot_falls_back_to_theme(theme_pair):
    config.CustomColor = True
    config._CUSTOM["primary"] = None
    config._render()
    assert config.Primary == (config._sgr(config._STYLE["primary"]) or config.CYAN)


def test_roundtrip_custom_flag_config_colors_from_color_json(
    theme_pair, tmp_path, monkeypatch
):
    conf, colf = _conf(
        tmp_path,
        custom=True,
        colors={"primary_color": "#ff005f", "secondary_color": "bold #39c5bb"},
        theme={"primary": "cyan"},
    )
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    assert config.CustomColor is True
    config._render()
    assert "\x1b[38;2;255;0;95m" in config.Primary
    assert "\x1b[1;38;2;57;197;187m" in config.Secondary  # bold #39c5bb


def test_invalid_color_in_color_json_ignored(theme_pair, tmp_path, monkeypatch):
    conf, colf = _conf(
        tmp_path,
        custom=True,
        colors={"primary_color": "not-a-color", "_comment": "keep me"},
    )
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    assert config.CustomColor is True
    assert config._CUSTOM["primary"] is None
    assert "\x1b[38;2;255;0;95m" not in config.Primary


def test_custom_color_off_ignores_color_json_values(theme_pair, tmp_path, monkeypatch):
    conf, colf = _conf(tmp_path, custom=False, colors={"primary_color": "#ff005f"})
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    assert config.CustomColor is False
    # stored but inert
    assert config._CUSTOM["primary"] == "#ff005f"
    assert "\x1b[38;2;255;0;95m" not in config.Primary


def test_maybe_reload_applies_color_json_edit(theme_pair, tmp_path, monkeypatch):
    conf, colf = _conf(tmp_path, custom=True, colors={"primary_color": "#ff005f"})
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    config.maybe_reload()  # baseline over both files
    before = config.Primary
    colf.write_text(json.dumps({"custom_color": True, "primary_color": "#00ff9f"}))
    config.maybe_reload()
    assert config.Primary != before
    assert "\x1b[38;2;0;255;159m" in config.Primary


def test_maybe_reload_applies_config_flag_flip(theme_pair, tmp_path, monkeypatch):
    conf, colf = _conf(tmp_path, custom=True, colors={"primary_color": "#ff005f"})
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    conf.write_text(json.dumps({"custom_color": False}))
    config.maybe_reload()
    assert config.CustomColor is False
    assert "\x1b[38;2;255;0;95m" not in config.Primary


def test_save_colors_merges_keeps_unrelated_keys(tmp_path, monkeypatch):
    colf = tmp_path / "color.json"
    colf.write_text(json.dumps({"_note": "hex is fine", "extra": 1}))
    monkeypatch.setattr(config, "COLOR_FILE", colf)
    monkeypatch.setattr(config, "_color_mtime", None)
    config._CUSTOM["primary"] = "#7f4dff"
    config._save_colors()
    data = json.loads(colf.read_text())
    assert data["_note"] == "hex is fine"
    assert data["extra"] == 1
    assert data["primary_color"] == "#7f4dff"


def test_setter_validation(theme_pair):
    out = config._apply_custom_color_slot("primary", "definitely-not-a-style")
    assert "Unknown color" in out
    assert config._CUSTOM["primary"] != "definitely-not-a-style"


def test_setter_writes_color_json(theme_pair, tmp_path, monkeypatch):
    colf = tmp_path / "color.json"
    monkeypatch.setattr(config, "COLOR_FILE", colf)
    monkeypatch.setattr(config, "_color_mtime", None)
    out = config._apply_custom_color_slot("primary", "#00ff9f")
    assert "primary_color set to #00ff9f" in out
    assert json.loads(colf.read_text())["primary_color"] == "#00ff9f"


def test_keep_live_rebinds_aliases(theme_pair):
    """Snapshot aliases (P, S, …) must follow _render() — the stale-color fix."""
    ns = {"P": config.Primary, "S": config.Secondary, "R": config.Reset}
    config.keep_live(ns)
    config.CustomColor = True
    config._CUSTOM["primary"] = "#00ff9f"
    config._CUSTOM["secondary"] = "#ff005f"
    config._render()
    assert ns["P"] == config.Primary == "\x1b[38;2;0;255;159m"
    assert ns["S"] == config.Secondary == "\x1b[38;2;255;0;95m"
    assert ns["R"] == config.Reset


def test_module_alias_snapshots_follow_render(theme_pair):
    """A real module's import-time alias no longer freezes its startup color."""
    from backend import summary  # registers itself via keep_live at import

    config.CustomColor = True
    config._CUSTOM["primary"] = "#00ff9f"
    config._render()
    assert summary.P == config.Primary == "\x1b[38;2;0;255;159m"
    config._CUSTOM["primary"] = None
    config._render()  # falls back to theme alias again
    assert summary.P == config.Primary


def test_eff_style_resolution(theme_pair):
    """_eff_style = custom override when on+set, else theme."""
    config._STYLE["primary"] = "cyan"
    config.CustomColor = True
    config._CUSTOM["primary"] = "#00ff9f"
    assert config._eff_style("primary") == "#00ff9f"
    config._CUSTOM["primary"] = None  # empty slot keeps the theme
    assert config._eff_style("primary") == "cyan"
    config.CustomColor = False
    assert config._eff_style("primary") == "cyan"


def test_cname_resolves_custom_ansi(theme_pair):
    """_cname's ANSI→rich mapping must also know the custom overrides."""
    config.CustomColor = True
    config._CUSTOM["primary"] = "#00ff9f"
    config._render()
    assert config._cname(config.Primary) == "#00ff9f"


def test_questionary_style_uses_custom_colors(theme_pair):
    """The questionary palettes (config picker + ui.pick) pick up color.json."""
    from backend import ui

    config.CustomColor = True
    config._CUSTOM["primary"] = "#00ff9f"
    config._CUSTOM["tertiary"] = "#ff005f"
    assert config._cname(config._eff_style("primary")) == "#00ff9f"
    assert config._cname(config._eff_style("tertiary")) == "#ff005f"
    # the pickers build their style from these without ValueError
    assert ui.questionary_style("online") is not None
    assert ui.questionary_style("offline") is not None


def test_maybe_reload_first_sighting_applies_late_created_file(
    theme_pair, tmp_path, monkeypatch
):
    """color.json appearing after startup must apply on the first poll."""
    conf, colf = _conf(tmp_path, custom=True)  # no color.json yet
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    colf.write_text(json.dumps({"primary_color": "#00ff9f"}))
    config.maybe_reload()
    assert "\x1b[38;2;0;255;159m" in config.Primary


def test_reload_command_forces_reapply(tmp_path, monkeypatch):
    # disk says blue but module state says pink — reload snaps back to disk
    conf, colf = _conf(tmp_path, custom=True, colors={"primary_color": "#0000ff"})
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    config._CUSTOM["primary"] = "#ff00ff"  # simulate a desynced in-memory value
    config._render()
    out = config._apply_reload()
    assert "reloaded" in out
    assert "\x1b[38;2;0;0;255m" in config.Primary


def test_interactive_rows_hide_theme_rows_while_custom_on(theme_pair):
    config.CustomColor = False
    keys_off = {r[0] for r in config._interactive_rows()}
    assert {"primary", "secondary", "tertiary", "theme"} <= keys_off
    assert {"custom_color", "primary_color", "secondary_color", "tertiary_color"} <= keys_off
    config.CustomColor = True
    keys_on = {r[0] for r in config._interactive_rows()}
    assert not ({"primary", "secondary", "tertiary", "theme"} & keys_on)
    assert {"custom_color", "primary_color", "secondary_color", "tertiary_color"} <= keys_on


def test_clear_colors_resets_everything(theme_pair, tmp_path, monkeypatch):
    conf, colf = _conf(
        tmp_path, custom=True,
        colors={"primary_color": "#ff005f", "secondary_color": "#00ff9f",
                "_note": "keep"},
    )
    _patch_files(monkeypatch, conf, colf)
    config._load_config()
    out = config._apply_clear_colors()
    assert "cleared" in out
    assert config._CUSTOM["primary"] is None
    assert "\x1b[38;2;255;0;95m" not in config.Primary
    data = json.loads((tmp_path / "color.json").read_text())
    assert data["primary_color"] == ""  # written back empty
    assert data["_note"] == "keep"  # merge preserved
