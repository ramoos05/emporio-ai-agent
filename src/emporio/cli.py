"""Interface de linha de comando: `python -m emporio`."""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from . import config


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="emporio", description="Atendimento virtual da Empório da Música")
    ap.add_argument("--session", help="ID da conversa; reutilize para retomar o histórico")
    ap.add_argument("--verbose", "-v", action="store_true", help="mostra as ferramentas chamadas e seus resultados")
    ap.add_argument("--model", help=f"modelo OpenAI (padrão: {config.MODEL})")
    args = ap.parse_args(argv)

    if not os.getenv("OPENAI_API_KEY"):
        print("Defina OPENAI_API_KEY (veja .env.example).", file=sys.stderr)
        return 1

    from openai import OpenAI

    from .agent import Agente

    def on_tool(nome, entrada, saida):
        if args.verbose:
            print(f"  [ferramenta] {nome}({json.dumps(entrada, ensure_ascii=False)})")
            print(f"  [resultado] {json.dumps(saida, ensure_ascii=False)[:400]}")

    agente = Agente(OpenAI(timeout=30.0), session_id=args.session, on_tool=on_tool, model=args.model)
    print(f"Empório da Música | sessão: {agente.session_id} | /sair para encerrar, /novo para nova conversa\n")
    if agente.messages:
        print("(histórico anterior carregado)\n")
    while True:
        try:
            texto = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not texto:
            continue
        if texto == "/sair":
            return 0
        if texto == "/novo":
            agente = Agente(OpenAI(timeout=30.0), on_tool=on_tool, model=args.model)
            print(f"\nNova conversa (sessão: {agente.session_id})\n")
            continue
        print(f"\nBia: {agente.responder(texto)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
