"""Recuperação (RAG leve) sobre o manual de políticas.

O manual tem ~8 páginas, então a estratégia é: dividir por seção/subseção (cada trecho é uma
unidade de significado completa) e ranquear por sobreposição lexical com normalização de
acentos, stemming mínimo e um pequeno dicionário de sinônimos do domínio. Sem embeddings:
para este tamanho, é determinístico, grátis, testável e não adiciona dependências.

As seções 7 (diretrizes internas de atendimento) e 10 (disposições finais) não são indexadas:
já estão incorporadas ao prompt do agente e são de uso interno da equipe.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from . import config
from .data import normalize

SECOES_INTERNAS = {"7", "10"}

STOPWORDS = set(
    "a o as os um uma de do da dos das em no na nos nas e ou que para por com se meu minha "
    "voces voce eu posso pode quero queria gostaria qual quais como quando onde tem ha ser "
    "sao foi vai ao aos ja mais muito me te ter fazer".split()
)

SINONIMOS = {
    "devolver": ["devolucao", "arrependimento", "reembolso", "troca"],
    "devolucao": ["devolver", "arrependimento", "reembolso"],
    "arrependi": ["arrependimento", "devolucao", "devolver"],
    "arrepender": ["arrependimento", "devolucao"],
    "trocar": ["troca", "defeito", "preferencia"],
    "troca": ["trocar", "defeito", "preferencia"],
    "cancelar": ["devolucao", "arrependimento"],
    "defeito": ["garantia", "troca", "fabricante"],
    "quebrou": ["defeito", "garantia"],
    "estragou": ["defeito", "garantia"],
    "horario": ["funcionamento", "expediente", "abre", "fecha"],
    "abre": ["horario", "funcionamento"],
    "fecha": ["horario", "funcionamento"],
    "aberto": ["horario", "funcionamento"],
    "funciona": ["horario", "funcionamento"],
    "domingo": ["horario", "funcionamento"],
    "sabado": ["horario", "funcionamento"],
    "feriado": ["horario", "funcionamento"],
    "pagar": ["pagamento", "pix", "cartao", "boleto"],
    "pagamento": ["pix", "cartao", "debito", "credito", "boleto", "parcelamento"],
    "parcelar": ["parcelamento", "credito", "parcela"],
    "parcela": ["parcelamento", "credito"],
    "parcelas": ["parcelamento", "credito"],
    "cartao": ["credito", "debito", "pagamento"],
    "entrega": ["frete", "prazo", "envio"],
    "entregar": ["frete", "entrega", "envio"],
    "enviar": ["frete", "envio", "correios"],
    "envio": ["frete", "entrega", "correios"],
    "frete": ["entrega", "envio", "correios", "sedex", "pac"],
    "rastrear": ["rastreamento", "codigo"],
    "rastreio": ["rastreamento", "codigo"],
    "desconto": ["promocao", "pix"],
    "promocao": ["desconto", "promocoes"],
    "black": ["promocao", "friday"],
    "endereco": ["dados", "empresa", "rua"],
    "telefone": ["dados", "empresa", "whatsapp"],
    "whatsapp": ["telefone", "contato"],
    "contato": ["telefone", "email", "whatsapp"],
    "email": ["dados", "empresa", "contato"],
    "dados": ["privacidade", "lgpd"],
    "excluir": ["privacidade", "lgpd", "exclusao"],
    "lgpd": ["privacidade", "dados"],
    "garantia": ["defeito", "fabricante", "legal"],
}


def _stem(tok: str) -> str:
    if tok.endswith("oes"):
        return tok[:-3] + "ao"
    if len(tok) > 3 and tok.endswith("s"):
        return tok[:-1]
    return tok


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in normalize(text).split() if t not in STOPWORDS and len(t) > 1]


@dataclass
class Trecho:
    secao: str       # ex.: "4.1"
    titulo: str      # ex.: "Direito de Arrependimento (Compras Online)"
    texto: str

    @property
    def rotulo(self) -> str:
        return f"{self.secao} {self.titulo}"


def _parse(md: str) -> list[Trecho]:
    trechos: list[Trecho] = []
    secao_pai = ""
    titulo_pai = ""
    atual: tuple[str, str] | None = None
    buf: list[str] = []

    def fecha():
        nonlocal buf
        texto = "\n".join(buf).strip()
        if atual and texto:
            sec, titulo = atual
            if sec.split(".")[0] not in SECOES_INTERNAS:
                # prefixa o título da seção-pai no subtrecho para dar contexto ao ranking e à resposta
                nome = titulo if sec == secao_pai else f"{titulo_pai} > {titulo}"
                trechos.append(Trecho(sec, nome, texto))
        buf = []

    for linha in md.splitlines():
        m2 = re.match(r"^## (\d+)\. (.+)$", linha)
        m3 = re.match(r"^### (\d+\.\d+) (.+)$", linha)
        if m2:
            fecha()
            secao_pai, titulo_pai = m2.group(1), m2.group(2)
            atual = (secao_pai, titulo_pai)
        elif m3:
            fecha()
            atual = (m3.group(1), m3.group(2))
        elif atual:
            buf.append(linha)
    fecha()
    return trechos


class Politicas:
    def __init__(self, md: str):
        self.trechos = _parse(md)
        self._tok = [_tokens(f"{t.rotulo} {t.texto}") for t in self.trechos]
        self._titulo_tok = [set(_tokens(t.rotulo)) for t in self.trechos]
        n = len(self.trechos)
        df: dict[str, int] = {}
        for toks in self._tok:
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1
        self._idf = {tok: math.log(1 + n / c) for tok, c in df.items()}

    def _expande(self, consulta: str) -> dict[str, float]:
        pesos: dict[str, float] = {}
        for tok in _tokens(consulta):
            pesos[tok] = max(pesos.get(tok, 0), 1.0)
            for sin in SINONIMOS.get(tok, []):
                s = _stem(sin)
                pesos[s] = max(pesos.get(s, 0), 0.5)
        return pesos

    def buscar(self, consulta: str, k: int = 3) -> list[tuple[Trecho, float]]:
        pesos = self._expande(consulta)
        resultados = []
        for t, toks, titulo in zip(self.trechos, self._tok, self._titulo_tok):
            conj = set(toks)
            score = 0.0
            for tok, peso in pesos.items():
                if tok in conj:
                    score += peso * self._idf.get(tok, 0)
                    if tok in titulo:
                        score += peso * 1.5  # termo no título da seção vale mais
            if score > 0:
                resultados.append((t, score))
        resultados.sort(key=lambda x: -x[1])
        return resultados[:k]


@lru_cache(maxsize=1)
def carregar_politicas() -> Politicas:
    return Politicas((config.DATA_DIR / "politicas.md").read_text(encoding="utf-8"))
