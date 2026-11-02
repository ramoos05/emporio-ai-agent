import pytest

from emporio.policies import carregar_politicas


@pytest.mark.parametrize("pergunta,secao", [
    ("posso devolver? me arrependi", "4.1"),
    ("o violão chegou com defeito", "4.2"),
    ("vocês abrem no sábado?", "2"),
    ("quanto é o frete pra Dourados", "5.2"),
    ("dá pra parcelar em quantas vezes", "3.1"),
    ("desconto no pix junto com promoção", "6.2"),
    ("quero apagar meus dados", "9"),
    ("qual o endereço de vocês", "1.2"),
    ("qual o formato do código de rastreio", "5.3"),
])
def test_trecho_certo_no_topo(pergunta, secao):
    assert carregar_politicas().buscar(pergunta)[0][0].secao == secao


def test_secoes_internas_nao_indexadas():
    secoes = {t.secao.split(".")[0] for t in carregar_politicas().trechos}
    assert not secoes & {"7", "10"}
