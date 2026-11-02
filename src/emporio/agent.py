"""Loop do agente: mensagem do cliente -> (modelo <-> ferramentas)* -> resposta final."""
from __future__ import annotations

import json
import uuid
from typing import Callable

from . import config, storage, tools
from .data import Loja, carregar_loja
from .prompts import SYSTEM_PROMPT, contexto_temporal

MSG_ERRO = ("Ops, tive um probleminha técnico aqui e não consegui concluir. Pode tentar de novo em instantes? "
            "Se preferir, fale com a equipe no WhatsApp (67) 3341-4444.")
MSG_LIMITE = ("Não consegui fechar isso sozinha agora. Vou deixar com a equipe: chame no WhatsApp "
              "(67) 3341-4444 em horário comercial, tá?")

OnTool = Callable[[str, dict, dict], None]


def _bloco_para_dict(b) -> dict:
    """Converte bloco de conteúdo do SDK em dict mínimo (evita campos extras que a API rejeita ao reenviar)."""
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    raise ValueError(f"bloco não suportado: {b.type}")


def _eh_texto_do_usuario(m: dict) -> bool:
    return m["role"] == "user" and isinstance(m["content"], str)


class Agente:
    def __init__(self, client, session_id: str | None = None, loja: Loja | None = None,
                 on_tool: OnTool | None = None, persistir: bool = True, model: str | None = None):
        self.client = client
        self.model = model or config.MODEL
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.persistir = persistir
        self.on_tool = on_tool
        self.loja = loja or carregar_loja()
        estado = storage.carregar(self.session_id) if persistir else {"messages": [], "falhas_verificacao": 0}
        self.messages: list[dict] = estado["messages"]
        self.ctx = tools.Contexto(loja=self.loja, falhas_verificacao=estado.get("falhas_verificacao", 0))
        self._schemas = tools.schemas(sorted({p.categoria for p in self.loja.produtos.values()}))

    # ---------------------------------------------------------------- público
    def responder(self, texto: str) -> str:
        inicio = len(self.messages)
        self.messages.append({"role": "user", "content": texto})
        try:
            resposta = self._rodar()
        except Exception:  # noqa: BLE001 - qualquer falha de API/rede vira mensagem amigável
            # desfaz o turno incompleto: não deixar tool_use sem tool_result no histórico
            del self.messages[inicio:]
            return MSG_ERRO
        self._salvar()
        return resposta

    # ---------------------------------------------------------------- interno
    def _janela(self) -> list[dict]:
        msgs = self.messages
        if len(msgs) <= config.MAX_HISTORY_MESSAGES:
            return msgs
        corte = len(msgs) - config.MAX_HISTORY_MESSAGES
        # começa sempre em uma mensagem de texto do usuário (nunca no meio de um par tool_use/tool_result)
        while corte < len(msgs) and not _eh_texto_do_usuario(msgs[corte]):
            corte += 1
        return msgs[corte:]

    def _sistema(self) -> list[dict]:
        return [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": contexto_temporal()},  # dinâmico: fica fora do trecho cacheado
        ]

    def _rodar(self) -> str:
        for _ in range(config.MAX_TOOL_STEPS):
            resp = self.client.messages.create(
                model=self.model, max_tokens=config.MAX_TOKENS, system=self._sistema(),
                tools=self._schemas, messages=self._janela(),
            )
            self.messages.append({"role": "assistant", "content": [_bloco_para_dict(b) for b in resp.content
                                                                    if b.type in ("text", "tool_use")]})
            usos = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not usos:
                return "\n".join(b.text for b in resp.content if b.type == "text").strip() or MSG_ERRO
            resultados = []
            for u in usos:
                saida = tools.executar(self.ctx, u.name, dict(u.input))
                if self.on_tool:
                    self.on_tool(u.name, dict(u.input), saida)
                resultados.append({"type": "tool_result", "tool_use_id": u.id,
                                   "content": json.dumps(saida, ensure_ascii=False)})
            self.messages.append({"role": "user", "content": resultados})
        # estourou o limite de rodadas: fecha o histórico de forma consistente
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": MSG_LIMITE}]})
        return MSG_LIMITE

    def _salvar(self) -> None:
        if self.persistir:
            storage.salvar(self.session_id, {"messages": self.messages,
                                             "falhas_verificacao": self.ctx.falhas_verificacao})
