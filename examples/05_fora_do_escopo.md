# Conversa ilustrativa

Exemplo redigido a partir das fontes; não é transcrição de execução do LLM.

**Cliente:** Vocês vendem cabo de guitarra?

**Consulta prevista:** search_policies(query="instrumentos acessórios cabos escopo loja").

**Bia:** Trabalhamos exclusivamente com instrumentos musicais e não vendemos cabos. Posso ajudar a encontrar uma guitarra, se você quiser. [Políticas, p. 2]

**Cliente:** Então consulta o meu pedido 1.

**Bia:** Para consultar, qual e-mail foi usado na compra?

**Cliente:** errado@example.com

**Consulta prevista:** lookup_order(order_id=1, customer_email="errado@example.com").

**Bia:** Não localizei um pedido com essa combinação de número e e-mail. Pode conferir os dois dados? [Pedidos]
