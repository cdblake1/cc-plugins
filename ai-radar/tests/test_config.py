from __future__ import annotations

from pathlib import Path

import ai_radar.config as cfg

# The ai-radar project dir (…/ai-radar) that contains config/.
PROJECT = Path(cfg.__file__).resolve().parent.parent.parent


def test_config_resolves_from_cwd_when_package_has_no_config(tmp_path, monkeypatch):
    """Reproduces the CI case: package pip-installed elsewhere, cwd is ai-radar/."""
    monkeypatch.delenv("AI_RADAR_CONFIG_DIR", raising=False)
    # Pretend the installed package lives somewhere with no config/ alongside it.
    monkeypatch.setattr(cfg, "_PKG_ROOT", tmp_path / "site-packages" / "ai_radar")
    monkeypatch.chdir(PROJECT)

    topics = cfg.load_topics()
    assert topics["topics"], "topics.yaml should resolve via cwd/config"
    feeds = cfg.load_feeds()
    assert feeds["arxiv_categories"] and feeds["rss_feeds"], "feeds.yaml should resolve via cwd/config"


def test_config_env_override(tmp_path, monkeypatch):
    cfgdir = tmp_path / "mycfg"
    cfgdir.mkdir()
    (cfgdir / "topics.yaml").write_text("topics: [alpha, beta]\n", encoding="utf-8")
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(cfgdir))
    monkeypatch.setattr(cfg, "_PKG_ROOT", tmp_path / "nowhere" / "ai_radar")
    monkeypatch.chdir(tmp_path)  # cwd has no config/ either

    assert cfg.load_topics()["topics"] == ["alpha", "beta"]
