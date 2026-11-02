from emporio.data import Loja, forma_pagamento_legivel, normalize


def test_contagens_e_integridade():
    l = Loja()
    assert len(l.produtos) == 65 and len(l.pedidos) == 20 and len(l.clientes) == 50
    assert all(pid in l.produtos for o in l.pedidos.values() for pid, _ in o.itens)
    assert l.produtos[96].estoque == 0 and not l.produtos[96].vendavel
    assert l.produtos[136].status == "discontinued" and l.produtos[136].estoque > 0 and not l.produtos[136].vendavel


def test_preco_com_promocao():
    l = Loja()
    assert l.preco_atual(l.produtos[121]) == 439.2   # 20% sobre 549
    assert l.preco_atual(l.produtos[95]) == 2199     # sem promoção ativa


def test_helpers():
    assert normalize("Violões Ação!") == "violoes acao"
    assert forma_pagamento_legivel("credit_6x") == "cartão de crédito em 6x"
    assert forma_pagamento_legivel("pix") == "PIX"
