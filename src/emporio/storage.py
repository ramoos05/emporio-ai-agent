"""Persistência do histórico: um arquivo JSON por sessão (retomável via --session)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import config


def _path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    return config.SESSIONS_DIR / f"{safe}.json"


def carregar(session_id: str) -> dict:
    p = _path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # arquivo corrompido: começa do zero em vez de quebrar o atendimento
    return {"messages": [], "falhas_verificacao": 0}


def salvar(session_id: str, estado: dict) -> None:
    p = _path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)  # escrita atômica
