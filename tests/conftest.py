import pytest

from emporio import config, tools


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    """Data fixa, sessões e encaminhamentos em diretório temporário."""
    monkeypatch.setenv("EMPORIO_NOW", "2026-02-20T10:00:00")  # sexta-feira, loja aberta
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(config, "HANDOFF_FILE", tmp_path / "sessions" / "enc.jsonl")


@pytest.fixture
def ctx():
    return tools.Contexto()
