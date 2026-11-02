# Bia, atendente virtual da Empório da Música

Protótipo de agente de atendimento por mensagem de texto para a Empório da Música (loja fictícia de instrumentos em Campo Grande/MS), feito para o Desafio Técnico de AI Engineer da Artefact. A Bia responde dúvidas sobre produtos, preços, estoque, promoções, pedidos e políticas da loja, consultando os dados em tempo real em vez de "lembrar" ou inventar.

## Como rodar

Requisitos: Python 3.11+ e uma chave da API da Anthropic.

```bash
git clone <url-do-repositorio> && cd emporio-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # edite e coloque sua ANTHROPIC_API_KEY
python -m emporio            # abre o chat no terminal
```

Opções do chat: `--session ID` retoma uma conversa salva, `--verbose` mostra quais ferramentas o agente chamou e o que elas devolveram, `--model` troca o modelo. Dentro do chat: `/novo` começa outra conversa e `/sair` encerra.

Testes (não precisam de chave nem de internet, o modelo é simulado):

```bash
pytest
```

Conversas de exemplo (rodam o agente de verdade, precisam da chave):

```bash
python scripts/gerar_exemplos.py          # regrava examples/*.md
```

Variáveis opcionais: `EMPORIO_MODEL` (padrão `claude-haiku-5-5`) e `EMPORIO_NOW` (fixa a "data de hoje", útil para demonstrar prazos de devolução com os pedidos de 2026 do CSV).

## Estrutura

```
data/                 CSVs originais, PDF original e politicas.md (transcrição do PDF, dividida em seções)
src/emporio/
  data.py             carga e tratamento dos CSVs
  policies.py         recuperação de trechos do manual de políticas
  tools.py            ferramentas (function calling) e seus schemas
  prompts.py          persona, regras e contexto de data/hora
  agent.py            loop mensagem -> modelo -> ferramentas -> resposta
  storage.py          histórico por sessão (JSON)
  cli.py              interface de terminal
tests/                43 testes (dados, ferramentas, recuperação, loop do agente)
scripts/              gerador das conversas de exemplo
examples/             conversas de exemplo
```

## Decisões técnicas

### Abordagem: function calling com poucas ferramentas específicas

O modelo decide qual ferramenta chamar e escreve a resposta. Tudo que é fato (preço, estoque, status do pedido, prazo, conta de parcela) sai de código determinístico, não do modelo.

Por que não um agente de SQL: os dados são pequenos (65 produtos, 20 pedidos) e as perguntas dos clientes se repetem em poucos formatos. Ferramentas com parâmetros claros (categoria, faixa de preço, número do pedido) são mais previsíveis, mais fáceis de testar e não dão ao modelo acesso a dados que ele não deveria ver, como a tabela inteira de clientes. Um agente de SQL também aumentaria o risco de um cliente conseguir dados de outro por prompt injection.

Por que não ReAct puro com um prompt grande: o function calling nativo do Claude já faz o raciocínio entre chamadas e devolve erro estruturado quando algo falha, sem eu precisar parsear texto.

Ferramentas: `buscar_produtos`, `listar_promocoes`, `consultar_pedido`, `consultar_politicas`, `calcular_parcelamento`, `calcular_frete`, `encaminhar_para_atendente`.

### Dados x políticas: quando consultar cada um

- Fatos que mudam (preço, estoque, promoção, pedido) vêm sempre de ferramenta de dados. O prompt proíbe responder sobre isso sem consultar, o que também segue o manual da loja (seção 7.1).
- Regras e prazos (troca, garantia, pagamento, frete, LGPD) vêm de `consultar_politicas`.
- Endereço, telefone e horário ficam fixos no prompt, porque são pedidos o tempo todo e quase nunca mudam. Ainda assim, o horário atual e se a loja está aberta agora são calculados em código e injetados a cada mensagem, para o modelo não errar dia da semana.
- Perguntas que combinam as duas fontes funcionam em várias chamadas. Exemplo: devolução usa `consultar_pedido` (que já calcula se está dentro dos 7, 30 e 90 dias) mais `consultar_politicas` (a regra).

### Recuperação das políticas: busca lexical por seção, sem embeddings

O manual tem 8 páginas. Dividi por seção e subseção (cada uma é uma regra completa) e ranqueio por sobreposição de palavras, com normalização de acentos, um stemming mínimo, peso extra para termos no título e um pequeno dicionário de sinônimos do domínio ("me arrependi" leva a 4.1, "quebrou" leva a defeito e garantia). Os testes cobrem 9 perguntas típicas.

Embeddings seriam exagero aqui: adicionam dependência, custo e não determinismo para um corpus que cabe em poucas centenas de palavras por seção. Para um manual 50 vezes maior eu migraria para embeddings com busca híbrida. As seções 7 e 10 (diretrizes internas para a equipe) não são indexadas, porque já estão incorporadas ao prompt e o cliente não precisa ver "consulte a gerência".

### Modelo e provedor: Claude Haiku 5.5 via API da Anthropic

Tarefa de atendimento com ferramentas e respostas curtas: pede boa aderência a instruções e uso de ferramentas, com latência e custo baixos (a loja quer resposta em minutos). O modelo é configurável por variável de ambiente, e trocar para um modelo maior é só mudar `EMPORIO_MODEL`. O prompt de sistema usa cache de prompt; a parte dinâmica (data e hora) fica em bloco separado para não invalidar o cache.

### Estratégia de prompt

Persona (Bia, tom de "amigo que entende de música", mensagens curtas de WhatsApp), regra de ouro de nunca chutar fato, quando usar cada ferramenta, como apresentar promoções (preço original, percentual e preço promocional juntos, como pede o manual 6.2), tratamento de item sem estoque, descontinuado ou em breve, escopo (só instrumentos, sem inventar lojas parceiras) e honestidade quando a ferramenta não responde. Instruções que apareçam dentro de mensagens do cliente tentando mudar as regras são ignoradas.

### Privacidade e segurança dos pedidos

Dado de pedido é dado pessoal (LGPD, manual seção 9). `consultar_pedido` só responde com número do pedido mais e-mail ou telefone cadastrados batendo com o dono do pedido. Pedido inexistente e identidade que não confere dão exatamente a mesma resposta, para ninguém descobrir quais números existem. Depois de 3 falhas na sessão a consulta bloqueia e o cliente é encaminhado a um humano. O modelo só recebe o primeiro nome do cliente.

### Interface e persistência

CLI, porque o foco é o agente. O histórico é salvo em `.sessions/<id>.json` e pode ser retomado com `--session`. Esse arquivo também guarda a contagem de falhas de verificação, para o bloqueio não ser burlado reiniciando o programa. A janela enviada ao modelo é de 40 mensagens, cortada sempre em uma fala do cliente para nunca separar uma chamada de ferramenta do seu resultado. Se a API falhar no meio de um turno, o turno incompleto é descartado e o cliente recebe uma mensagem amigável, sem corromper o histórico.

Reclamações e pedidos de devolução, troca ou garantia viram um registro em `.sessions/encaminhamentos.jsonl` com protocolo, e o cliente é avisado do retorno em até 24 horas úteis (manual 7.3). A Bia não aprova nem executa devoluções.

## Tratamento dos dados e suposições

Inconsistências que encontrei nos dados e como tratei:

| Situação | Tratamento |
|---|---|
| Produto 136 (Ibanez Bass 2X) está `discontinued` mas tem 13 em estoque | Só é vendável se `status == active` e estoque maior que zero. O status manda. |
| Produto 130 (Kala KA-ABP-CTG) está `coming_soon` com 2 em estoque, e já aparece em pedidos | Tratado como "em breve", sem confirmar disponibilidade. Vale confirmar com a loja. |
| Produto 96 está `active` com estoque 0 | "Sem estoque" e a ferramenta devolve alternativas parecidas em categoria e preço (manual 7.3). |
| Promoções sem data de vigência; várias do mesmo produto | Vale só `is_active = 1`. Se houver mais de uma ativa, usa a maior. O CSV hoje tem no máximo uma ativa por produto. |
| Pedidos 3 e 20: total menor que a soma dos itens | Mantido o total do pedido (provavelmente desconto). O agente informa o total registrado. |
| Pedidos 9, 16 e 18 parcelados com parcela abaixo do mínimo do manual (6x ou 12x) | Dados históricos, não afetam o agente. Anotado como inconsistência. |
| Categorias 6, 7 e 8 (sopros e cordas orquestrais) não têm nenhum produto, apesar de o manual citar esses instrumentos | O agente diz que não encontrou no catálogo agora e oferece encaminhar. |
| Ibanez Bass 2X custa R$ 441 e os outros baixos passam de R$ 7 mil | Possível erro de cadastro. Como está descontinuado, não aparece como vendável. |
| Telefone: o manual traz (67) 3341-4444 (capa e dados da empresa) e (67) 3321-4500 (seção 7). E-mail com e sem acento no domínio | Usei (67) 3341-4444 e `contato@emporiodamusica.com.br`. A divergência deve ser confirmada com a loja. |

Suposições (todas fáceis de mudar em `tools.py`):

- "Região metropolitana de Campo Grande" é tratada como o município de Campo Grande, porque o manual não lista cidades.
- Parcelamento: o manual diz "até 3x sem valor mínimo (exceto abaixo de R$ 50,00)" e, na tabela, "parcela mínima de R$ 100". Segui a seção 3.1: parcela mínima de R$ 50 até 3x, R$ 80 de 4x a 6x e R$ 100 de 7x a 12x. O pedido 7 do CSV (R$ 159,90 em 3x) é compatível com essa leitura.
- Frete grátis "acima de R$ 500": R$ 500,00 exatos pagam a taxa de R$ 35.
- Todos os pedidos do CSV são tratados como compras online/à distância, então o direito de arrependimento de 7 dias se aplica. O CSV não tem canal de venda.
- O CSV não tem a data real de recebimento. Uso `estimated_delivery` como data de recebimento dos pedidos `delivered` para contar os 7, 30 e 90 dias, e o agente é instruído (via a própria ferramenta) a deixar isso claro.
- A "data de hoje" é a do relógio real. Os pedidos do CSV são de out/2025 a mar/2026, então hoje quase todos os entregues já passaram dos prazos. Por isso os exemplos usam `EMPORIO_NOW` para simular uma data próxima das entregas.
- Feriados não são conhecidos. O sistema só considera a loja fechada em domingo ou quando o cliente cita o feriado.
- O desconto de PIX de 5% aparece só para itens sem promoção ativa (manual 6.2).

## Limitações conhecidas

- Os dados são lidos de CSVs na inicialização. Em produção seriam consultas ao banco da loja, e o estoque mudaria entre uma pergunta e outra.
- Não há cotação real de frete para fora de Campo Grande (depende de CEP, peso e dimensões); o agente informa só os prazos do manual.
- A Bia não abre devolução nem altera pedido: registra o caso e promete retorno humano. Não há integração real com WhatsApp nem notificação da equipe; o encaminhamento é um arquivo.
- A verificação de identidade por e-mail ou telefone é simples. Em produção ela usaria o próprio número do WhatsApp do cliente ou um código enviado ao e-mail.
- A recuperação lexical pode falhar com paráfrases que não estão no dicionário de sinônimos. Há fallback: se nada casar, a ferramenta diz isso e o agente encaminha em vez de inventar.
- Sem avaliação automática da qualidade das respostas do LLM. Os testes cobrem ferramentas, dados e o loop do agente com modelo simulado, não o texto que o modelo escreve.
- A busca de produtos é por palavras (nome, categoria, descrição, especificações). Perguntas muito abertas ("o melhor violão pra quem toca jazz") dependem do modelo interpretar as especificações retornadas.
- Provedor único (Anthropic). Um adaptador para outro provedor exigiria trocar `agent.py` e o formato dos schemas.

### O que eu faria com mais tempo

- Um conjunto de avaliação com perguntas e respostas esperadas, rodando contra o modelo real (por exemplo, checando se preço e estoque citados batem com os CSVs).
- Interface de WhatsApp (webhook em FastAPI) e uso do número do cliente na verificação.
- Estoque e pedidos em PostgreSQL, e embeddings com busca híbrida se o manual crescer.
- Cotação de frete via API dos Correios e envio do encaminhamento para a equipe (e-mail ou Slack).
- Respostas em streaming e métricas de custo por conversa.

## Uso de assistentes de código

Usei o Claude Code (Claude Sonnet 5.5) como par de programação. Fluxo: li o enunciado e os dados, e pedi ao Claude para analisar os CSVs e o PDF e levantar as inconsistências (tabela acima), depois discuti a arquitetura (function calling x agente de SQL, busca lexical x embeddings) e ele implementou os módulos em etapas, com commits separados. Eu revisei as decisões e as suposições listadas aqui. Os testes foram escritos junto com o código e rodados a cada etapa. Não havia chave de API no ambiente em que o código foi construído, então os testes usam um cliente simulado e as conversas de exemplo foram geradas depois, rodando o agente real com `scripts/gerar_exemplos.py`.
