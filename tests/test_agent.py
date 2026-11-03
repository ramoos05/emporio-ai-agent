"""Testa o loop do agente com um cliente OpenAI falso (sem rede, sem chave)."""
import copy
from types import SimpleNamespace as NS

import pytest

from emporio import config, prompts, storage
from emporio.agent import MSG_ERRO, MSG_LIMITE, Agente


def texto(t):
    return NS(type="text", text=t)


def uso(id_, nome, **inp):
    return NS(type="function", id=id_, function=NS(name=nome, arguments=__import__("json").dumps(inp)))


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.chamadas.append(copy.deepcopy(kw))  # snapshot: o agente muta a lista depois
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def resp(*blocos, stop="end_turn"):
    return NS(choices=[NS(message=NS(
        content="\n".join(b.text for b in blocos if b.type == "text") or None,
        tool_calls=[b for b in blocos if b.type == "function"] or None,
    ))])


def test_fluxo_com_ferramenta():
    c = ClienteFalso([resp(uso("t1", "buscar_produtos", consulta="Takamine GD20"), stop="tool_use"),
                      resp(texto("O Takamine GD20 sai por R$ 2.199,00."))])
    eventos = []
    a = Agente(c, session_id="s1", on_tool=lambda n, i, o: eventos.append((n, o)))
    assert "2.199" in a.responder("Quanto custa o Takamine GD20?")
    assert eventos[0][0] == "buscar_produtos" and eventos[0][1]["produtos"][0]["preco_tabela"] == 2199
    # o 2º envio ao modelo contém o tool_result com o dado real
    ultimo = c.chamadas[1]["messages"][-1]
    assert ultimo["role"] == "tool" and ultimo["tool_call_id"] == "t1"
    assert "2199" in ultimo["content"]


def test_prompt_do_sistema_tem_regras_e_hora():
    c = ClienteFalso([resp(texto("oi"))])
    Agente(c, persistir=False).responder("oi")
    sistema = c.chamadas[0]["messages"][0]
    assert sistema["role"] == "system"
    assert prompts.SYSTEM_PROMPT in sistema["content"]
    assert "ABERTA" in sistema["content"] and "sexta-feira" in sistema["content"]
    assert all(t["type"] == "function" and "parameters" in t["function"]
               for t in c.chamadas[0]["tools"])


def test_persistencia_e_retomada():
    a = Agente(ClienteFalso([resp(texto("Oi! Como posso ajudar?"))]), session_id="s2")
    a.responder("oi")
    b = Agente(ClienteFalso([resp(texto("Claro!"))]), session_id="s2")
    assert len(b.messages) == 2
    b.responder("tudo bem?")
    assert [m["role"] for m in storage.carregar("s2")["messages"]] == ["user", "assistant"] * 2


def test_falha_de_api_nao_corrompe_historico():
    c = ClienteFalso([resp(uso("t1", "listar_promocoes"), stop="tool_use"), RuntimeError("API fora")])
    a = Agente(c, persistir=False)
    assert a.responder("promoções?") == MSG_ERRO
    assert a.messages == []  # turno incompleto removido


def test_limite_de_rodadas_de_ferramenta():
    c = ClienteFalso([resp(uso(f"t{i}", "listar_promocoes"), stop="tool_use") for i in range(config.MAX_TOOL_STEPS)])
    a = Agente(c, persistir=False)
    assert a.responder("promoções?") == MSG_LIMITE
    assert a.messages[-1]["role"] == "assistant"


def test_janela_nao_comeca_no_meio_de_par_tool(monkeypatch):
    monkeypatch.setattr(config, "MAX_HISTORY_MESSAGES", 4)
    a = Agente(ClienteFalso([]), persistir=False)
    a.messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok2"}]},
    ]
    j = a._janela()
    assert j[0] == {"role": "user", "content": "b"}


def test_falhas_de_verificacao_persistem_entre_sessoes():
    c = ClienteFalso([resp(uso("t1", "consultar_pedido", numero_pedido=8, email_ou_telefone="x@y.com"), stop="tool_use"),
                      resp(texto("Não consegui confirmar."))])
    Agente(c, session_id="s3").responder("pedido 8")
    assert Agente(ClienteFalso([]), session_id="s3").ctx.falhas_verificacao == 1


@pytest.mark.parametrize("quando,esperado", [
    ("2026-02-20T10:00:00", "ABERTA"),             # sexta 10h
    ("2026-02-20T18:00:00", "FECHADA"),            # sexta 18h em ponto
    ("2026-02-21T12:59:00", "ABERTA"),             # sábado
    ("2026-02-21T13:00:00", "FECHADA"),
    ("2026-02-22T10:00:00", "FECHADA"),            # domingo
])
def test_loja_aberta_ou_fechada(quando, esperado):
    from datetime import datetime
    assert esperado in prompts.contexto_temporal(datetime.fromisoformat(quando).replace(tzinfo=config.TZ))


def test_proxima_abertura_domingo_e_segunda():
    from datetime import datetime
    t = prompts.contexto_temporal(datetime(2026, 2, 22, 10, tzinfo=config.TZ))
    assert "segunda-feira, 23/02 às 09h" in t
    t = prompts.contexto_temporal(datetime(2026, 2, 20, 19, tzinfo=config.TZ))
    assert "sábado, 21/02 às 09h" in t


def test_migracao_de_sessao_antiga():
    storage.salvar("antiga", {"messages": [
        {"role": "user", "content": "promoções?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "listar_promocoes", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Confira as opções."}]},
    ], "falhas_verificacao": 2})
    c = ClienteFalso([resp(texto("Certo."))])
    agente = Agente(c, session_id="antiga")
    assert agente.ctx.falhas_verificacao == 2
    assert agente.responder("obrigado") == "Certo."
    mensagens = c.chamadas[0]["messages"]
    assert mensagens[2]["tool_calls"][0]["function"]["name"] == "listar_promocoes"
    assert mensagens[3]["role"] == "tool"


def test_argumentos_invalidos_desfazem_turno():
    chamada = uso("t1", "listar_promocoes")
    chamada.function.arguments = "{invalido"
    agente = Agente(ClienteFalso([resp(chamada)]), persistir=False)
    assert agente.responder("promoções?") == MSG_ERRO
    assert agente.messages == []


def test_resposta_vazia_desfaz_turno():
    agente = Agente(ClienteFalso([resp()]), persistir=False)
    assert agente.responder("oi") == MSG_ERRO
    assert agente.messages == []
