import json

from emporio import config, tools


def nomes(r):
    return [p["nome"] for p in r["produtos"]]


# ------------------------------------------------------------------ produtos
def test_violoes_ate_1000_somente_disponiveis(ctx):
    r = tools.buscar_produtos(ctx, categoria="Violões", preco_max=1000, somente_disponiveis=True, limite=10)
    assert r["total_encontrado"] > 0
    for p in r["produtos"]:
        assert p["categoria"] == "Violões" and p["situacao"] == "disponivel"
        atual = p["promocao"]["preco_promocional"] if p["promocao"] else p["preco_tabela"]
        assert atual <= 1000


def test_preco_takamine(ctx):
    p = tools.buscar_produtos(ctx, consulta="Takamine GD20")["produtos"][0]
    assert p["produto_id"] == 95 and p["preco_tabela"] == 2199 and p["situacao"] == "disponivel"
    assert p["promocao"] is None and p["preco_pix"] == 2089.05


def test_sem_estoque_traz_alternativas(ctx):
    p = tools.buscar_produtos(ctx, consulta="Giannini GF-3D")["produtos"][0]
    assert p["situacao"] == "sem_estoque" and "unidades_em_estoque" not in p
    assert p["alternativas_disponiveis"] and all(a["produto_id"] != 96 for a in p["alternativas_disponiveis"])


def test_descontinuado_e_em_breve_nao_sao_vendaveis(ctx):
    desc = tools.buscar_produtos(ctx, consulta="Ibanez Bass 2X")["produtos"][0]  # descontinuado mas com estoque no CSV
    assert desc["situacao"] == "descontinuado" and "unidades_em_estoque" not in desc
    breve = tools.buscar_produtos(ctx, consulta="Kala KA-ABP-CTG")["produtos"][0]
    assert breve["situacao"] == "em_breve"


def test_promocao_ativa_vs_expirada(ctx):
    ativa = tools.buscar_produtos(ctx, consulta="Ohana CK-20")["produtos"][0]
    assert ativa["promocao"]["percentual_desconto"] == 20 and ativa["promocao"]["preco_promocional"] == 439.2
    assert ativa["preco_pix"] is None  # PIX não acumula com promoção
    expirada = tools.buscar_produtos(ctx, consulta="Martin D-28 Dreadnought")["produtos"][0]
    assert expirada["promocao"] is None  # promo 6/23 existe no CSV mas is_active=0


def test_categoria_sem_itens_e_produto_inexistente(ctx):
    r = tools.buscar_produtos(ctx, consulta="saxofone")
    assert r["total_encontrado"] == 0 and "Categorias" in r["aviso"]
    assert tools.buscar_produtos(ctx, categoria="Instrumentos de Sopro (Madeiras)")["total_encontrado"] == 0


def test_listar_promocoes_so_ativas(ctx):
    ids = {p["produto_id"] for p in tools.listar_promocoes(ctx)["promocoes_ativas"]}
    assert ids == {127, 121, 90, 94}


# ------------------------------------------------------------------ pedidos
def test_pedido_verificado_por_email_ou_telefone(ctx):
    r = tools.consultar_pedido(ctx, 8, "ana carol")  # inválido
    assert r["erro"] == "nao_verificado"
    r = tools.consultar_pedido(ctx, 8, "ANACAROL.ferreira@coldmail.com")
    assert r["status"] == "shipped" and r["codigo_rastreio"] == "BRJL5544332BR"
    assert tools.consultar_pedido(ctx, 8, "(67) 99654-7821")["numero_pedido"] == 8


def test_pedido_de_outro_cliente_nao_vaza(ctx):
    a = tools.consultar_pedido(ctx, 8, "lucas.mendes@jmail.com")      # existe, mas é de outra pessoa
    b = tools.consultar_pedido(ctx, 9999, "lucas.mendes@jmail.com")   # não existe
    assert a == b and "Ana" not in json.dumps(a)


def test_bloqueio_apos_falhas(ctx):
    for _ in range(config.MAX_FAILED_VERIFICATIONS):
        tools.consultar_pedido(ctx, 8, "x@y.com")
    assert tools.consultar_pedido(ctx, 8, "anacarol.ferreira@coldmail.com")["erro"] == "verificacao_bloqueada"


def test_prazos_pos_venda_calculados_em_codigo(ctx):
    j = tools.consultar_pedido(ctx, 7, "leticia.rocha@jmail.com")["prazos_pos_venda"]
    assert j["dentro_prazo_arrependimento_7_dias"] is None
    assert j["dentro_garantia_legal_90_dias"] is None
    assert "data real de recebimento" in j["dados_faltantes"]
    assert "dias_desde_recebimento" not in j


def test_pedido_cancelado_e_pendente(ctx):
    c = tools.consultar_pedido(ctx, 18, "gustavo.nunes@inlook.com")
    assert c["status"] == "cancelled" and "estoque" in c["observacao"]
    p = tools.consultar_pedido(ctx, 13, "fernanda.ribeiro@coldmail.com")
    assert p["status"] == "pending" and p["codigo_rastreio"] is None and "prazos_pos_venda" not in p


# ------------------------------------------------------------------ cálculos
def test_parcelamento_respeita_minimos(ctx):
    r = tools.calcular_parcelamento(ctx, 349.9)
    assert r["maximo_parcelas"] == 4      # 5x = 69,98 < R$ 80 (faixa 4x-6x)
    r = tools.calcular_parcelamento(ctx, 1200)
    assert r["maximo_parcelas"] == 12 and r["pix"]["valor"] == 1140
    assert tools.calcular_parcelamento(ctx, 1200, preco_ja_promocional=True)["pix"]["valor"] == 1200
    assert "combinacao_de_formas" in tools.calcular_parcelamento(ctx, 2500)


def test_frete(ctx):
    assert tools.calcular_frete(ctx, "Campo Grande", 500)["frete"] == 35.0   # "acima de" 500 => 500 não é grátis
    assert tools.calcular_frete(ctx, "campo grande", 500.01)["frete"] == 0.0
    assert tools.calcular_frete(ctx, "Dourados", 900)["frete"] is None


# ------------------------------------------------------------------ políticas e humano
def test_politicas(ctx):
    r = tools.consultar_politicas(ctx, "me arrependi da compra, posso devolver?")
    assert r["trechos"][0]["secao"].startswith("4.1") and "7 (sete) dias" in r["trechos"][0]["texto"]
    assert tools.consultar_politicas(ctx, "tom de voz do atendente")["encontrado"] is False  # seção 7 é interna
    assert tools.consultar_politicas(ctx, "resultado do jogo de futebol de ontem")["encontrado"] is False


def test_encaminhamento_gera_protocolo_e_registro(ctx):
    r = tools.encaminhar_para_atendente(ctx, "reclamação", "Cliente reclama do pedido 8", contato="a@b.com")
    linhas = config.HANDOFF_FILE.read_text(encoding="utf-8").splitlines()
    assert json.loads(linhas[0])["protocolo"] == r["protocolo"]


def test_executar_ferramenta_invalida(ctx):
    assert "erro" in tools.executar(ctx, "inexistente", {})
    assert "erro" in tools.executar(ctx, "calcular_frete", {"cidade": "x", "foo": 1})
