"""Carga e tratamento dos CSVs da loja.

Decisões de limpeza (detalhadas no README):
- `specs` é JSON em texto: convertido para dict.
- Um produto só é *vendável* se status == "active" E estoque > 0.
  Há casos inconsistentes no dado (ex.: descontinuado com estoque, "coming_soon" com estoque);
  nesses casos o status manda, nunca o estoque.
- Promoção vale somente com is_active == 1 (o CSV não tem datas de vigência).
- Telefones e e-mails dos clientes são normalizados só para comparação na verificação de identidade.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from . import config

STATUS_PEDIDO_PT = {
    "pending": "pendente (aguardando confirmação do pagamento)",
    "confirmed": "confirmado (pagamento aprovado, em preparação)",
    "shipped": "enviado (em transporte)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}


def normalize(text: str) -> str:
    """minúsculas, sem acentos, só alfanumérico e espaço."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def forma_pagamento_legivel(code: str) -> str:
    if code == "pix":
        return "PIX"
    if code == "debit":
        return "cartão de débito"
    if code == "boleto":
        return "boleto"
    m = re.fullmatch(r"credit_(\d+)x", code)
    if m:
        return f"cartão de crédito em {m.group(1)}x"
    return code


@dataclass
class Produto:
    id: int
    nome: str
    preco: float
    categoria_id: int
    categoria: str
    descricao: str
    estoque: int
    status: str
    specs: dict
    criado_em: date | None

    @property
    def vendavel(self) -> bool:
        return self.status == "active" and self.estoque > 0

    @property
    def situacao(self) -> str:
        if self.status == "discontinued":
            return "descontinuado"
        if self.status == "coming_soon":
            return "em_breve"
        if self.estoque <= 0:
            return "sem_estoque"
        return "disponivel"

    @property
    def texto_busca(self) -> str:
        specs = " ".join(str(v) for v in self.specs.values())
        return normalize(f"{self.nome} {self.categoria} {self.descricao} {specs}")


@dataclass
class Promocao:
    id: int
    produto_id: int
    percentual: float
    descricao: str
    ativa: bool


@dataclass
class Cliente:
    id: int
    nome: str
    telefone: str
    email: str
    cidade: str


@dataclass
class Pedido:
    id: int
    cliente_id: int
    data: date
    status: str
    total: float
    pagamento: str
    rastreio: str
    previsao_entrega: date | None
    observacao: str
    itens: list[tuple[int, int]] = field(default_factory=list)  # (produto_id, quantidade)


def _date(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


class Loja:
    def __init__(self, data_dir: Path | None = None):
        d = Path(data_dir or config.DATA_DIR)
        categorias = {int(r["category_id"]): r["name"] for r in _read(d / "categories.csv")}
        self.categorias = categorias

        self.produtos: dict[int, Produto] = {}
        for r in _read(d / "products.csv"):
            try:
                specs = json.loads(r["specs"]) if r["specs"] else {}
            except json.JSONDecodeError:
                specs = {}
            p = Produto(
                id=int(r["product_id"]), nome=r["name"], preco=float(r["price_brl"]),
                categoria_id=int(r["category_id"]), categoria=categorias[int(r["category_id"])],
                descricao=r["description"], estoque=int(r["stock_quantity"]), status=r["status"],
                specs=specs, criado_em=_date(r["created_at"]),
            )
            self.produtos[p.id] = p

        self.promocoes = [
            Promocao(int(r["promotion_id"]), int(r["product_id"]), float(r["discount_percent"]),
                     r["description"], r["is_active"] == "1")
            for r in _read(d / "promotions.csv")
        ]
        self.clientes = {
            int(r["customer_id"]): Cliente(int(r["customer_id"]), r["name"], r["phone"],
                                           r["email"].lower(), r["city"])
            for r in _read(d / "customers.csv")
        }
        self.pedidos: dict[int, Pedido] = {}
        for r in _read(d / "orders.csv"):
            o = Pedido(int(r["order_id"]), int(r["customer_id"]), date.fromisoformat(r["order_date"]),
                       r["status"], float(r["total_brl"]), r["payment_method"], r["tracking_code"],
                       _date(r["estimated_delivery"]), r["notes"])
            self.pedidos[o.id] = o
        for r in _read(d / "order_items.csv"):
            self.pedidos[int(r["order_id"])].itens.append((int(r["product_id"]), int(r["quantity"])))

    # --- promoções -------------------------------------------------------------------
    def promocao_ativa(self, produto_id: int) -> Promocao | None:
        ativas = [p for p in self.promocoes if p.produto_id == produto_id and p.ativa]
        return max(ativas, key=lambda p: p.percentual) if ativas else None

    def preco_atual(self, produto: Produto) -> float:
        promo = self.promocao_ativa(produto.id)
        return round(produto.preco * (1 - promo.percentual / 100), 2) if promo else produto.preco

    # --- clientes --------------------------------------------------------------------
    def verifica_cliente(self, pedido: Pedido, informado: str) -> bool:
        """Confere se o e-mail ou telefone informado pertence ao dono do pedido."""
        c = self.clientes.get(pedido.cliente_id)
        if not c or not informado.strip():
            return False
        informado = informado.strip().lower()
        if "@" in informado:
            return informado == c.email
        d = digits(informado)
        tel = digits(c.telefone)
        # aceita com ou sem DDD (mínimo 8 dígitos para evitar "casar" por acidente)
        return len(d) >= 8 and tel.endswith(d)


@lru_cache(maxsize=1)
def carregar_loja() -> Loja:
    return Loja()
