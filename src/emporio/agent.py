"""Loop do agente: mensagem do cliente -> (modelo <-> ferramentas)* -> resposta final."""
from __future__ import annotations

import json
import uuid
from typing import Callable

from . import config, storage, tools
from .data import Loja, carregar_loja
from .prompts import SYSTEM_PROMPT, contexto_temporal

MSG_ERRO = ("Não consegui concluir a consulta. Tente novamente em instantes. "
            "Se preferir, fale com a equipe no WhatsApp (67) 3341-4444.")
MSG_LIMITE = ("Não consegui concluir essa consulta. Fale com a equipe pelo WhatsApp "
              "(67) 3341-4444 em horário comercial.")

OnTool = Callable[[str, dict, dict], None]


def _migrar_historico(messages: list[dict]) -> list[dict]:
    """Converte sessões salvas antes da troca de provedor."""
    resultado = []
    for mensagem in messages:
        conteudo = mensagem.get("content")
        if not isinstance(conteudo, list) or not any(
            bloco.get("type") in ("tool_use", "tool_result") for bloco in conteudo
        ):
            resultado.append(mensagem)
            continue
        if mensagem["role"] == "assistant":
            resultado.append({
                "role": "assistant",
                "content": "\n".join(b["text"] for b in conteudo if b["type"] == "text") or None,
                "tool_calls": [
                    {"id": b["id"], "type": "function", "function": {
                        "name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                    for b in conteudo if b["type"] == "tool_use"
                ],
            })
        else:
            resultado.extend({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
                             for b in conteudo if b["type"] == "tool_result")
    return resultado


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
        self.messages: list[dict] = _migrar_historico(estado["messages"])
        self.ctx = tools.Contexto(loja=self.loja, falhas_verificacao=estado.get("falhas_verificacao", 0))
        self._schemas = tools.schemas(sorted({p.categoria for p in self.loja.produtos.values()}))

    def responder(self, texto: str) -> str:
        inicio = len(self.messages)
        self.messages.append({"role": "user", "content": texto})
        try:
            resposta = self._rodar()
        except Exception:  # noqa: BLE001 - qualquer falha de API/rede vira mensagem amigável
            # desfaz o turno incompleto: não deixar chamadas sem resultado no histórico
            del self.messages[inicio:]
            return MSG_ERRO
        self._salvar()
        return resposta

    def _janela(self) -> list[dict]:
        msgs = self.messages
        if len(msgs) <= config.MAX_HISTORY_MESSAGES:
            return msgs
        corte = len(msgs) - config.MAX_HISTORY_MESSAGES
        # começa sempre em uma mensagem de texto do usuário (nunca no meio de um par de chamada e resultado)
        while corte < len(msgs) and not _eh_texto_do_usuario(msgs[corte]):
            corte += 1
        return msgs[corte:]

    def _sistema(self) -> str:
        return f"{SYSTEM_PROMPT}\n\n{contexto_temporal()}"

    def _rodar(self) -> str:
        for _ in range(config.MAX_TOOL_STEPS):
            resp = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=config.MAX_TOKENS,
                messages=[{"role": "system", "content": self._sistema()}, *self._janela()],
                tools=self._schemas,
                parallel_tool_calls=False,
            )
            mensagem = resp.choices[0].message
            usos = mensagem.tool_calls or []
            registro = {"role": "assistant", "content": mensagem.content}
            if usos:
                registro["tool_calls"] = [
                    {"id": u.id, "type": "function", "function": {
                        "name": u.function.name, "arguments": u.function.arguments}}
                    for u in usos
                ]
            self.messages.append(registro)
            if not usos:
                resposta = (mensagem.content or "").strip()
                if not resposta:
                    raise ValueError("O modelo retornou uma resposta vazia")
                return resposta
            for uso in usos:
                entrada = json.loads(uso.function.arguments)
                if not isinstance(entrada, dict):
                    raise ValueError("Os argumentos da ferramenta devem ser um objeto")
                saida = tools.executar(self.ctx, uso.function.name, entrada)
                if self.on_tool:
                    self.on_tool(uso.function.name, entrada, saida)
                self.messages.append({"role": "tool", "tool_call_id": uso.id,
                                      "content": json.dumps(saida, ensure_ascii=False)})
        self.messages.append({"role": "assistant", "content": MSG_LIMITE})
        return MSG_LIMITE

    def _salvar(self) -> None:
        if self.persistir:
            storage.salvar(self.session_id, {"messages": self.messages,
                                             "falhas_verificacao": self.ctx.falhas_verificacao})
