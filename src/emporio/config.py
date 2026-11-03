"""Configuração central: caminhos, modelo e relógio da loja."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("EMPORIO_DATA_DIR", ROOT / "data"))
SESSIONS_DIR = Path(os.getenv("EMPORIO_SESSIONS_DIR", ROOT / ".sessions"))
HANDOFF_FILE = Path(os.getenv("EMPORIO_HANDOFF_FILE", ROOT / ".sessions" / "encaminhamentos.jsonl"))

MODEL = os.getenv("EMPORIO_MODEL", "").strip() or "gpt-4.1-mini"
MAX_TOKENS = 1024
MAX_TOOL_STEPS = 6          # limite de rodadas de ferramenta por mensagem do cliente
MAX_HISTORY_MESSAGES = 40   # janela de histórico enviada ao modelo
MAX_FAILED_VERIFICATIONS = 3

TZ = ZoneInfo("America/Campo_Grande")


def now() -> datetime:
    """Hora atual na loja. `EMPORIO_NOW` (ISO 8601) permite fixar a data em demos e testes."""
    override = os.getenv("EMPORIO_NOW")
    if override:
        dt = datetime.fromisoformat(override)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)
