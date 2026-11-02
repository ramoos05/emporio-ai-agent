# Bia — Empório da Música

Agente Python para o desafio AI Engineer da Artefact. Atende por texto no terminal, com persona informal/profissional, ferramentas para dados estruturados e busca de políticas por seção.

## Estado da entrega

Código e testes locais incluídos. As cinco conversas em `examples/` são **ilustrativas**, não transcrições do LLM. A execução com API real e a publicação no GitHub ainda precisam ser feitas pelo candidato. O script `scripts/gerar_exemplos.py` grava cinco conversas reais; não grava um cenário que termina em falha técnica. Revise as respostas antes da entrega.

## Instalação no Windows (PowerShell)

Extraia o ZIP, abra a pasta `emporio-final` no VS Code e abra o terminal nessa pasta. Requer Python 3.11+ e Git para publicar.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Abra `.env` no editor e preencha:

```dotenv
ANTHROPIC_API_KEY=sua_chave_da_api
EMPORIO_MODEL=id_exato_do_modelo_disponivel_na_sua_conta
```

Use um modelo Anthropic que aceite ferramentas. O ID é obrigatório e não possui fallback silencioso. A disponibilidade deve ser conferida na sua conta; é necessário acesso e saldo/limite da API. Não envie a chave ao GitHub nem a inclua em capturas de tela.

```powershell
# Testar sem chamar o modelo
.venv\Scripts\python.exe -m pytest -q
# Conversar
.venv\Scripts\python.exe -m emporio
# Ver as chamadas de ferramentas durante uma demonstração
.venv\Scripts\python.exe -m emporio --verbose
# Retomar uma sessão específica
.venv\Scripts\python.exe -m emporio --session minha-demo
# Gerar as cinco conversas REAIS exigidas para entregar
.venv\Scripts\python.exe scripts/gerar_exemplos.py
```

`/sair` encerra; `/novo` inicia outra sessão. CLI foi escolhida porque o desafio aceita terminal e prioriza a lógica do agente. Não há necessidade de abrir navegador.

Linux/macOS: use `.venv/bin/python` nos comandos e `cp .env.example .env`.

## Como funciona

1. A CLI recebe a mensagem e carrega o histórico da sessão.
2. O modelo recebe persona, regras, ferramentas e contexto temporal.
3. O modelo solicita uma ou mais ferramentas; Python consulta os dados ou calcula valores.
4. O resultado volta ao modelo para redigir a resposta.
5. O histórico é salvo localmente. O loop tem limite de seis rodadas e desfaz o turno incompleto em falha de API.

Arquivos principais:

| Arquivo | Responsabilidade |
|---|---|
| `src/emporio/agent.py` | Loop de chamadas ao modelo e ferramentas |
| `src/emporio/tools.py` | Produtos, pedidos, promoções, políticas, cálculos e registro local |
| `src/emporio/data.py` | Carga dos CSVs e tratamento dos campos |
| `src/emporio/policies.py` | Busca lexical nas seções do manual |
| `src/emporio/prompts.py` | Persona, escopo e regras de comportamento |
| `src/emporio/storage.py` | Persistência JSON por sessão |
| `src/emporio/config.py` | Configuração carregada após o `.env` |

## Decisões técnicas

**Function calling:** ferramentas específicas limitam o acesso aos dados e simplificam testes. Não executamos SQL ou código escrito pelo modelo. Não foi necessário LangChain ou um framework de agentes para este loop.

**Provedor:** API Anthropic por SDK. O modelo é escolhido explicitamente por `EMPORIO_MODEL`; a escolha final e a qualidade precisam ser validadas com as conversas reais. Não houve benchmark de custo/latência. O prompt estático usa cache e o relógio fica em bloco separado.

**Retrieval:** o PDF original acompanha `data/politicas.md`, uma transcrição dividida em seções. Ranking lexical com normalização, stemming simples, sinônimos e peso de título. Para oito páginas, evita embeddings e infraestrutura adicional. Não é busca semântica; paráfrases podem falhar. Seções internas 7 e 10 são excluídas da busca e suas diretrizes relevantes estão no prompt.

**Dados:** CSVs carregados em memória. São um snapshot do desafio, não estoque conectado em tempo real. `specs` é convertido de JSON. Produto vendável exige status ativo e estoque positivo. Promoção usa `is_active`; se houver várias ativas, escolhe a maior sem acumular. PIX não acumula com promoção. Preço máximo filtra o preço atual antes do PIX.

**Pedidos:** consulta exige número e e-mail/telefone compatível. Retorna primeiro nome e campos do pedido, sem expor cadastro completo. Falhas de verificação têm resposta genérica e bloqueio após três tentativas na mesma sessão. Isso é validação demonstrativa, não autenticação segura; nova sessão pode contornar o limite.

**Pós-venda:** a previsão de entrega nunca é usada como recebimento efetivo. Canal da compra e data real precisam ser perguntados. A ferramenta calcula a janela interna de troca por defeito desde a compra; não conclui automaticamente arrependimento nem garantia. O agente não aprova reembolso ou devolução.

**Histórico:** JSON local por sessão, com escrita atômica e janela de contexto de 40 mensagens sem cortar pares de ferramentas. Persistência contém o texto informado pelo cliente e resultados; usar somente dados fictícios na demonstração e apagar sessões quando não forem mais necessárias.

## Ambiguidades e suposições

- Promoções não têm datas: somente `is_active` determina vigência.
- Produto descontinuado ou em breve pode ter estoque positivo: o status prevalece.
- Total de pedido é preservado mesmo quando diverge da soma dos itens.
- Parcelamento segue seção 3.1: mínimo de R$50 até 3x, R$80 de 4x a 6x e R$100 de 7x a 12x. Essa é uma interpretação documentada da ambiguidade com a tabela geral.
- Frete regional considera Campo Grande, pois o manual não lista municípios. Exatamente R$500 foi interpretado como frete de R$35; acima disso, grátis. Confirmar essas suposições com o negócio em produção.
- Contatos divergentes no manual: adotados telefone (67) 3341-4444 e e-mail sem acento. A divergência deve ser confirmada com a loja.
- Feriados não estão cadastrados; horário calculado é o regular, sujeito a feriados e exceções.
- Encaminhamento gera protocolo em arquivo local, sem notificação à equipe. A resposta deve identificar a simulação e não prometer retorno efetivo.

## Exemplos e validação

Os cinco cenários cobrem catálogo, informações/preço, arrependimento, falta de estoque/promoção inativa e assuntos fora do escopo. O script usa datas simuladas explícitas para os pedidos históricos. Com a API configurada, ele substitui os exemplos ilustrativos por resultados reais do agente.

Antes de enviar: confira preços contra os CSVs, referências das políticas, ausência de desconto acumulado, solicitação dos fatos faltantes na devolução, recusas fora do escopo e comportamento em pedidos inválidos. Uma resposta fluente não comprova correção.

Testes automatizados cobrem dados, ferramentas, políticas, loop simulado, persistência, falhas e regressões de configuração e datas. Não comprovam qualidade do modelo real nem resistência absoluta a prompt injection.

## Limitações e evolução

Sem integração real de WhatsApp, estoque, transportadora, pagamentos ou equipe humana. Sem login/OTP, criptografia de histórico, métricas de custo ou avaliação automatizada do texto do LLM. Preços usam floats arredondados; em produção migrar para Decimal e conciliação de parcelas. Busca lexical pode devolver correspondências parciais. As mensagens seguem para o provedor do modelo; dados de produção exigiriam revisão de privacidade e minimização.

Próximos passos: validação do modelo com casos reais, autenticação fora do LLM, cálculo determinístico de pós-venda usando datas confirmadas, feriados, notificações reais, telemetria sem dados pessoais e testes adversariais.

## Uso de IA

A versão recebida declara uso de Claude Code na implementação inicial. Esta revisão foi feita com ChatGPT/Codex: revisão do enunciado/código, reprodução de erros, ajustes de configuração e pós-venda, testes e documentação. Não houve credencial de API disponível para executar o modelo real. Os exemplos ilustrativos estão identificados como tal. O candidato deve compreender o código, revisar esta descrição de autoria e acrescentar as validações que efetivamente realizar.

## Publicação e entrega

O ZIP inclui o histórico Git recebido e um commit adicional de revisão, sem reescrever os anteriores. Crie um repositório público vazio no GitHub, sem README automático. Dentro desta pasta:

```powershell
git status
git log --oneline
git remote -v
```

Se não houver `origin`:

```powershell
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
```

Se já houver `origin`, use `git remote set-url origin URL_DO_SEU_REPOSITORIO`. Depois de gerar e revisar as conversas reais:

```powershell
git add examples README.md
git commit -m "Valida agente com modelo real e registra conversas"
git push -u origin main
```

Não publique `.env` ou `.sessions`. Confira no GitHub se há 3–5 conversas reais, instruções completas e histórico. Responda ao e-mail do processo com o link público antes do prazo indicado nele; não altere o repositório após a entrega. O ZIP é o pacote de trabalho, não substitui o repositório solicitado.
