"""Ferramentas (function calling) expostas ao modelo.

Princípio: tudo que é fato (preço, estoque, status, prazo, conta) é calculado aqui, em código
determinístico; o modelo só decide *qual* ferramenta chamar e redige a resposta.
Cada função recebe os argumentos do modelo e devolve um dict serializável em JSON.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from . import config
from .data import (STATUS_PEDIDO_PT, Loja, Produto, carregar_loja, forma_pagamento_legivel,
                   normalize)
from .policies import _tokens, carregar_politicas

DESCONTO_PIX = 0.05
FRETE_FIXO_METRO = 35.0
FRETE_GRATIS_ACIMA = 500.0
# Assumimos "região metropolitana de Campo Grande" = município de Campo Grande (o manual não lista cidades).
CIDADES_METRO = {"campo grande"}


@dataclass
class Contexto:
    """Estado mutável de uma conversa que as ferramentas precisam enxergar."""
    loja: Loja = field(default_factory=carregar_loja)
    falhas_verificacao: int = 0


# --------------------------------------------------------------------------- produtos
def _ficha(loja: Loja, p: Produto) -> dict:
    promo = loja.promocao_ativa(p.id)
    ficha = {
        "produto_id": p.id,
        "nome": p.nome,
        "categoria": p.categoria,
        "situacao": p.situacao,  # disponivel | sem_estoque | descontinuado | em_breve
        "preco_tabela": p.preco,
        "descricao": p.descricao,
        "especificacoes": p.specs,
    }
    if p.vendavel:
        ficha["unidades_em_estoque"] = p.estoque
    if promo:
        ficha["promocao"] = {
            "nome": promo.descricao,
            "percentual_desconto": promo.percentual,
            "preco_promocional": loja.preco_atual(p),
        }
        ficha["preco_pix"] = None  # desconto de PIX não é cumulativo com promoção (manual 6.2)
    else:
        ficha["promocao"] = None
        ficha["preco_pix"] = round(p.preco * (1 - DESCONTO_PIX), 2)
    return ficha


def _similares(loja: Loja, p: Produto, n: int = 3) -> list[dict]:
    alvo = loja.preco_atual(p)
    cand = [q for q in loja.produtos.values()
            if q.categoria_id == p.categoria_id and q.id != p.id and q.vendavel]
    cand.sort(key=lambda q: abs(loja.preco_atual(q) - alvo))
    return [{"produto_id": q.id, "nome": q.nome, "preco_atual": loja.preco_atual(q)} for q in cand[:n]]


def buscar_produtos(ctx: Contexto, consulta: str = "", categoria: str = "", preco_min: float | None = None,
                    preco_max: float | None = None, somente_disponiveis: bool = False,
                    limite: int = 6) -> dict:
    loja = ctx.loja
    limite = max(1, min(int(limite or 6), 10))
    itens = list(loja.produtos.values())

    if categoria:
        cat = normalize(categoria)
        itens = [p for p in itens if cat in normalize(p.categoria) or normalize(p.categoria) in cat]
    if preco_min is not None:
        itens = [p for p in itens if loja.preco_atual(p) >= preco_min]
    if preco_max is not None:
        itens = [p for p in itens if loja.preco_atual(p) <= preco_max]

    parcial = False
    toks = _tokens(consulta)
    if toks:
        pontuados = []
        for p in itens:
            nome = set(_tokens(p.nome))
            resto = set(p.texto_busca.split()) | {t for t in _tokens(p.texto_busca)}
            achou = [t for t in toks if t in nome or t in resto]
            pontuados.append((p, len(achou), sum(3 for t in toks if t in nome) + len(achou)))
        todos = [x for x in pontuados if x[1] == len(toks)]
        if todos:
            itens = [p for p, _, _ in sorted(todos, key=lambda x: -x[2])]
        else:
            alguns = [x for x in pontuados if x[1] > 0]
            parcial = bool(alguns)
            itens = [p for p, _, _ in sorted(alguns, key=lambda x: -x[2])]

    if somente_disponiveis:
        itens = [p for p in itens if p.vendavel]
    else:
        # vendáveis primeiro, depois o resto, mantendo a ordem de relevância/preço
        itens.sort(key=lambda p: (not p.vendavel,))
    if not toks:
        itens.sort(key=lambda p: (not p.vendavel, loja.preco_atual(p)))

    total = len(itens)
    resultado = []
    for p in itens[:limite]:
        f = _ficha(loja, p)
        if not p.vendavel:
            f["alternativas_disponiveis"] = _similares(loja, p)
        resultado.append(f)

    out = {"total_encontrado": total, "exibidos": len(resultado), "produtos": resultado}
    if parcial:
        out["aviso"] = "Nenhum produto casou com todos os termos; mostrando correspondências parciais."
    if total == 0:
        out["aviso"] = ("Nenhum produto encontrado com esses filtros. Categorias do catálogo com itens: "
                        + ", ".join(sorted({p.categoria for p in loja.produtos.values()})))
    return out


def listar_promocoes(ctx: Contexto) -> dict:
    loja = ctx.loja
    itens = []
    for pr in loja.promocoes:
        if not pr.ativa:
            continue
        p = loja.produtos.get(pr.produto_id)
        if p:
            itens.append({"produto_id": p.id, "nome": p.nome, "campanha": pr.descricao,
                          "percentual_desconto": pr.percentual, "preco_tabela": p.preco,
                          "preco_promocional": loja.preco_atual(p), "situacao": p.situacao})
    return {"promocoes_ativas": itens,
            "observacao": "Promoções não são cumulativas e o desconto de PIX não vale sobre preço promocional."}


# --------------------------------------------------------------------------- pedidos
def _janelas(pedido, hoje) -> dict | None:
    """Prazos de devolução/garantia calculados em código (LLMs erram conta de data)."""
    if pedido.status != "delivered":
        return None
    dias_compra = (hoje - pedido.data).days
    return {
        "dias_desde_compra": dias_compra,
        "dentro_prazo_troca_defeito_30_dias": 0 <= dias_compra <= 30,
        "dentro_prazo_arrependimento_7_dias": None,
        "dentro_garantia_legal_90_dias": None,
        "dados_faltantes": ["canal da compra", "data real de recebimento"],
        "orientacao": "Pergunte ao cliente esses dados. Previsão de entrega não comprova recebimento. Não aprove nem negue devolução com base na previsão."
    }


def consultar_pedido(ctx: Contexto, numero_pedido: int, email_ou_telefone: str = "") -> dict:
    loja = ctx.loja
    if ctx.falhas_verificacao >= config.MAX_FAILED_VERIFICATIONS:
        return {"erro": "verificacao_bloqueada",
                "mensagem": "Muitas tentativas sem confirmação de identidade. Encaminhe o cliente a um atendente humano."}
    try:
        pedido = loja.pedidos.get(int(numero_pedido))
    except (TypeError, ValueError):
        pedido = None
    # Mesma resposta para "pedido inexistente" e "identidade não confere": não vaza quais pedidos existem.
    if pedido is None or not loja.verifica_cliente(pedido, email_ou_telefone or ""):
        ctx.falhas_verificacao += 1
        return {"erro": "nao_verificado",
                "mensagem": ("Não foi possível confirmar este pedido com os dados informados. Peça o número do "
                             "pedido e o e-mail ou telefone cadastrados na compra. Não revele se o pedido existe.")}
    ctx.falhas_verificacao = 0
    cliente = loja.clientes[pedido.cliente_id]
    itens = [{"produto": loja.produtos[pid].nome, "quantidade": q} for pid, q in pedido.itens]
    out = {
        "numero_pedido": pedido.id,
        "cliente_primeiro_nome": cliente.nome.split()[0],
        "data_pedido": pedido.data.isoformat(),
        "status": pedido.status,
        "status_legivel": STATUS_PEDIDO_PT[pedido.status],
        "itens": itens,
        "total": pedido.total,
        "forma_pagamento": forma_pagamento_legivel(pedido.pagamento),
        "codigo_rastreio": pedido.rastreio or None,
        "previsao_entrega": pedido.previsao_entrega.isoformat() if pedido.previsao_entrega else None,
        "observacao": pedido.observacao or None,
    }
    j = _janelas(pedido, config.now().date())
    if j:
        out["prazos_pos_venda"] = j
    if pedido.status == "shipped":
        out["dica"] = "Rastreamento pode ser consultado no site dos Correios ou da Jadlog com o código."
    if pedido.status in {"pending", "confirmed"}:
        out["dica"] = "Ainda sem código de rastreio: ele é enviado por e-mail e WhatsApp quando o pedido for despachado."
    return out


# --------------------------------------------------------------------------- políticas
def consultar_politicas(ctx: Contexto, pergunta: str) -> dict:
    achados = carregar_politicas().buscar(pergunta, k=3)
    if not achados:
        return {"encontrado": False,
                "mensagem": "Nada no manual de políticas responde isso. Não invente: encaminhe a um atendente."}
    return {"encontrado": True,
            "trechos": [{"secao": t.rotulo, "texto": t.texto} for t, _ in achados]}


# --------------------------------------------------------------------------- cálculos
def calcular_parcelamento(ctx: Contexto, valor: float, preco_ja_promocional: bool = False) -> dict:
    valor = float(valor)
    if valor <= 0:
        return {"erro": "valor_invalido"}
    opcoes = []
    for n in range(1, 13):
        parcela = round(valor / n, 2)
        # Manual 3.1: até 3x sem mínimo "exceto abaixo de R$ 50" (lido como parcela >= R$ 50);
        # 4x-6x mínimo R$ 80; 7x-12x mínimo R$ 100. À vista (1x) sempre permitido.
        minimo = 0 if n == 1 else 50 if n <= 3 else 80 if n <= 6 else 100
        if parcela >= minimo:
            opcoes.append({"parcelas": n, "valor_parcela": parcela, "juros": "sem juros"})
    out = {"valor": valor, "credito_opcoes": opcoes, "maximo_parcelas": opcoes[-1]["parcelas"]}
    if preco_ja_promocional:
        out["pix"] = {"valor": valor, "observacao": "Sem desconto extra de PIX: o preço já é promocional (manual 6.2)."}
    else:
        out["pix"] = {"valor": round(valor * (1 - DESCONTO_PIX), 2), "observacao": "5% de desconto à vista no PIX."}
    out["debito_ou_boleto"] = {"valor": valor, "observacao": "À vista, sem desconto."}
    if valor > 2000:
        out["combinacao_de_formas"] = "Permitida (ex.: PIX + cartão), pois a compra é acima de R$ 2.000,00."
    return out


def calcular_frete(ctx: Contexto, cidade: str, valor_pedido: float, contem_item_grande_porte: bool = False) -> dict:
    cidade_n = normalize(cidade or "")
    if cidade_n in CIDADES_METRO:
        gratis = float(valor_pedido) > FRETE_GRATIS_ACIMA
        out = {"modalidade": "motoboy próprio (Campo Grande)", "prazo": "1 a 3 dias úteis",
               "frete": 0.0 if gratis else FRETE_FIXO_METRO,
               "observacao": "Frete grátis acima de R$ 500,00." if gratis else
               "Taxa fixa de R$ 35,00 para pedidos até R$ 500,00. O cliente é contactado por telefone antes da entrega."}
    else:
        out = {"modalidade": "Correios (PAC/SEDEX) ou Jadlog", "frete": None,
               "prazos": {"PAC": "5 a 12 dias úteis", "SEDEX": "2 a 5 dias úteis", "Jadlog (.package)": "3 a 8 dias úteis"},
               "observacao": "O valor exato é calculado pelo CEP, peso e dimensões no fechamento do pedido; "
                             "o agente não consegue cotar. Seguro e rastreamento incluídos."}
    if contem_item_grande_porte:
        out["aviso"] = "Instrumentos de grande porte (bateria acústica, piano digital, contrabaixo) podem ter frete especial com cotação individual."
    return out


# --------------------------------------------------------------------------- humano
def encaminhar_para_atendente(ctx: Contexto, motivo: str, resumo: str, nome: str = "", contato: str = "") -> dict:
    protocolo = uuid.uuid4().hex[:8].upper()
    registro = {"protocolo": protocolo, "quando": config.now().isoformat(timespec="seconds"),
                "motivo": motivo, "resumo": resumo, "nome": nome, "contato": contato}
    config.HANDOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.HANDOFF_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {"protocolo": protocolo, "simulacao": True,
            "mensagem": "Registro local de demonstração criado. Não houve envio à equipe. Informe isso e oriente contato direto com a loja, sem prometer retorno."}


# --------------------------------------------------------------------------- registro
FUNCOES = {
    "buscar_produtos": buscar_produtos,
    "listar_promocoes": listar_promocoes,
    "consultar_pedido": consultar_pedido,
    "consultar_politicas": consultar_politicas,
    "calcular_parcelamento": calcular_parcelamento,
    "calcular_frete": calcular_frete,
    "encaminhar_para_atendente": encaminhar_para_atendente,
}


def executar(ctx: Contexto, nome: str, argumentos: dict) -> dict:
    fn = FUNCOES.get(nome)
    if fn is None:
        return {"erro": f"ferramenta desconhecida: {nome}"}
    try:
        return fn(ctx, **(argumentos or {}))
    except (TypeError, ValueError, OverflowError) as e:
        return {"erro": f"argumentos inválidos: {e}"}


def schemas(categorias: list[str]) -> list[dict]:
    definicoes = [
        {
            "name": "buscar_produtos",
            "description": (
                "Consulta o snapshot local do catálogo: preço, estoque, situação (disponível, sem estoque, descontinuado, "
                "em breve), promoção ativa e especificações. Use SEMPRE antes de falar de preço, disponibilidade ou "
                "características de qualquer instrumento. Para itens indisponíveis já retorna alternativas. "
                "Use `categoria` para tipo de instrumento e `consulta` para marca/modelo/características (ex.: 'Takamine GD20', 'nylon')."),
            "parameters": {"type": "object", "properties": {
                "consulta": {"type": "string", "description": "Marca, modelo ou palavras-chave. Vazio para listar por filtros."},
                "categoria": {"type": "string", "enum": categorias, "description": "Categoria do catálogo."},
                "preco_min": {"type": "number", "description": "Preço mínimo em R$ (considera o preço atual, com promoção)."},
                "preco_max": {"type": "number", "description": "Preço máximo em R$ (considera o preço atual, com promoção)."},
                "somente_disponiveis": {"type": "boolean", "description": "True para listar só o que dá para comprar agora (use ao recomendar opções)."},
                "limite": {"type": "integer", "description": "Máximo de itens (1-10, padrão 6)."}}},
        },
        {
            "name": "listar_promocoes",
            "description": "Lista as promoções ATIVAS agora, com preço original, percentual e preço promocional.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "consultar_pedido",
            "description": (
                "Consulta status, itens, rastreio e prazos de um pedido. Exige o número do pedido E o e-mail ou telefone "
                "cadastrados na compra (verificação de identidade, LGPD). Nunca chame sem os dois dados: peça ao cliente. "
                "Para pedidos entregues, retorna a janela de troca por defeito desde a compra e identifica dados faltantes para arrependimento e garantia."),
            "parameters": {"type": "object", "properties": {
                "numero_pedido": {"type": "integer"},
                "email_ou_telefone": {"type": "string", "description": "E-mail ou telefone do cadastro, informado pelo cliente."}},
                "required": ["numero_pedido", "email_ou_telefone"]},
        },
        {
            "name": "consultar_politicas",
            "description": (
                "Busca no manual de políticas da loja: trocas e devoluções, garantia, formas de pagamento e parcelamento, "
                "frete e prazos, rastreamento, regras de promoção, LGPD, dados da empresa. Use para qualquer regra, prazo "
                "ou condição. Passe a dúvida do cliente em linguagem natural."),
            "parameters": {"type": "object", "properties": {"pergunta": {"type": "string"}}, "required": ["pergunta"]},
        },
        {
            "name": "calcular_parcelamento",
            "description": "Calcula as opções de parcelamento no crédito (respeitando parcela mínima) e o valor no PIX para um valor total.",
            "parameters": {"type": "object", "properties": {
                "valor": {"type": "number", "description": "Valor total em R$ (use o preço atual do produto)."},
                "preco_ja_promocional": {"type": "boolean", "description": "True se o valor já é preço promocional (PIX sem desconto extra)."}},
                "required": ["valor"]},
        },
        {
            "name": "calcular_frete",
            "description": "Frete e prazo de entrega conforme a cidade e o valor do pedido.",
            "parameters": {"type": "object", "properties": {
                "cidade": {"type": "string"},
                "valor_pedido": {"type": "number"},
                "contem_item_grande_porte": {"type": "boolean"}},
                "required": ["cidade", "valor_pedido"]},
        },
        {
            "name": "encaminhar_para_atendente",
            "description": (
                "Registra o caso localmente como simulação; não envia à equipe nem garante retorno. Use em reclamações, "
                "pedidos de devolução/troca/garantia a abrir, problemas que você não resolve, ou quando o cliente pedir "
                "um humano. Resuma o caso para a equipe não precisar perguntar de novo."),
            "parameters": {"type": "object", "properties": {
                "motivo": {"type": "string", "description": "Ex.: reclamação, devolução, troca por defeito, outro."},
                "resumo": {"type": "string", "description": "Resumo objetivo do caso, incluindo nº do pedido se houver."},
                "nome": {"type": "string"},
                "contato": {"type": "string", "description": "E-mail ou telefone para retorno, se o cliente informou."}},
                "required": ["motivo", "resumo"]},
        },
    ]

    return [{"type": "function", "function": {**d, "strict": False}} for d in definicoes]
