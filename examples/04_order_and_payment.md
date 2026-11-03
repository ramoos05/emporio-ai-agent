# Produto sem estoque e promoção que não está mais ativa

_Data simulada no sistema: 2026-02-20 10:00:00. Trechos `ferramenta` mostram o que o agente consultou antes de responder._

**Cliente:** Quero comprar o violão Giannini GF-3D

> `ferramenta` **buscar_produtos**({"consulta": "Giannini GF-3D", "categoria": "Violões", "somente_disponiveis": true, "limite": 1})
> `resultado` {"total_encontrado": 0, "exibidos": 0, "produtos": [], "aviso": "Nenhum produto encontrado com esses filtros. Categorias do catálogo com itens: Baixos, Baterias e Percussão, Guitarras, Teclados e Pianos, Ukuleles, Violões"}…

**Bia:** Olá! Não encontrei o violão Giannini GF-3D disponível no momento em nosso catálogo. Posso ajudar a buscar outro modelo de violão Giannini ou de outra marca?

**Cliente:** Mas eu vi que tava com 40% de desconto na Semana do Músico, ainda vale?

> `ferramenta` **listar_promocoes**({})
> `resultado` {"promocoes_ativas": [{"produto_id": 127, "nome": "Kalani KAL-700T Tenor Natural", "campanha": "Oferta Especial", "percentual_desconto": 10.0, "preco_tabela": 359.0, "preco_promocional": 323.1, "situacao": "disponivel"}, {"produto_id": 121, "nome": "Ohana CK-20 Concert Natural", "campanha": "Descont…

**Bia:** Olá! A promoção da Semana do Músico para o violão Giannini GF-3D não está mais ativa no momento. Temos outras promoções em violões, como Ohana CK-20 Concert com 20% de desconto e Crafter HT-100 Folk com 18%. Quer que eu envie detalhes ou preços dessas opções?
