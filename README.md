# Assistente de consulta FOMEZERO: doação segura de alimentos (GENAI)

Global Solution 2026.2 · FIAP · Tecnólogo em Inteligência Artificial · turma 2TIAPR-2026 ·
Generative AI and Advanced Nets.

O FOMEZERO liga quem tem comida sobrando (o doador) a quem precisa (o beneficiário), acompanhando cada lote de
doação. Esta parte do projeto é o **assistente de consulta para doadores**. Ele responde dúvidas sobre o que doar,
como conservar e como transportar o lote de doação, usando **RAG**: busca os trechos certos nos documentos oficiais
e gera uma resposta curta, com a fonte. Os documentos são os mesmos da matéria de PLN (contrato CT-01).

**O assistente nunca diz que um alimento é seguro para consumo e nunca decide sobre um lote.** Quando a pergunta
pede essa decisão, ele mostra o que os documentos dizem e encaminha à vigilância sanitária do município (ou a um
serviço de saúde, a um advogado ou à Defensoria Pública, ou a um profissional habilitado). Quando os documentos
não respondem, ele diz que não encontrou a informação.

## Integrantes
| Nome | RM |
|---|---|
| Erick Miguel | 564896 |
| Leonardo Melo | 567097 |
| Luna Oliveira | 564215 |

## Estrutura
```
README.md · requirements.txt · requirements-lock.txt (ambiente local completo) · .gitignore
assistente_fomezero.ipynb   notebook do Colab, seções N0 a N11
assistente/                 módulos importados pelo notebook: config, base (N1, N2), indice (N3, N4), llm (N5),
                            prompts (N6), politica (N7), consulta (N8), avaliacao (N9), interface (N10), simulado (N11)
prompts/                    prompts e listas da política (vão inteiros para a documentação)
avaliacao/                  perguntas_teste.jsonl, rubrica.md, construir_conjunto_teste.py, selecionar_k_tau.py,
                            calibracao_tau.json,
                            recuperacao.jsonl, metricas_recuperacao.csv; depois do Colab: resultados_S|P|R.jsonl,
                            log_chamadas.jsonl, metricas.csv, avaliacao_humana.csv
contrato/                   CT-02_PROPOSTA.md, exemplos_ct02.json; depois do Colab: respostas_SIMULADO.json
documentacao/               DOCUMENTACAO_TECNICA.md, .html e .pdf (com capa)
evidencias/                 EVIDENCIAS.md, testes locais, recuperação e τ medidos em CPU, teste_SIMULADO/, prints/
video/                      ROTEIRO.md, LINK.md
testes_locais.py            testes sem GPU (gera evidencias/testes_locais_AAAA-MM-DD.txt)
```
O corpus **não** é copiado para cá. Ele vem da matéria de PLN, que está em outro repositório:
**[PENDENTE: link do repositório da PLN]**. O notebook lê de `../PLN/corpus/` (o caminho fica num só lugar,
`assistente/config.py`), e a seção N1 confere o SHA-256 dos três arquivos antes de começar.

## Como executar no Google Colab
1. Copie este repositório e o da PLN para o Google Drive, lado a lado, com os nomes de pasta `GENAI` e `PLN`:
   `MyDrive/GS_FOMEZERO/GENAI` e `MyDrive/GS_FOMEZERO/PLN`. A pasta `GENAI/.venv`, `GENAI/.cache_hf` e
   `GENAI/indice` não precisam ir.
2. Abra `assistente_fomezero.ipynb` no Colab. Troque o ambiente para **GPU T4**:
   *Ambiente de execução > Alterar o tipo de ambiente de execução > T4 GPU*.
3. Rode a seção N0. Ela monta o Drive e instala `requirements.txt`.
   Se, depois da instalação, aparecer erro de importação do Pillow (`PIL`), use
   **Ambiente de execução > Reiniciar sessão** e rode de novo. A instalação troca a versão do Pillow que já estava
   carregada na memória.
4. **Executar tudo.** Com `REGERAR = False` (padrão), o notebook valida o corpus, monta o índice, carrega o
   Qwen2.5-7B, calibra o limiar τ, mostra exemplos, recalcula as métricas que já existirem e abre a interface
   Gradio com um link público temporário.
5. **Gerar a avaliação S × P × R:** mude `REGERAR = True` na seção N0 e rode a seção N9. São as 42 perguntas de
   teste de T1 a T7, nas três configurações (126 respostas). As perguntas de desenvolvimento só entram se
   `GERAR_DESENVOLVIMENTO = True` (opcional). Cada resposta é gravada assim que sai. Se a sessão cair, rode de novo: o notebook
   continua de onde parou. Na execução de 2026-11-10 (Tesla T4), a mediana por resposta foi de 15,41 s em S, 4,59 s em P e 11,21 s em R; os tempos de cada chamada ficam em `avaliacao/log_chamadas.jsonl`.
6. Rode a seção N11 para gravar `contrato/respostas_SIMULADO.json` (modo simulado do CT-02, gravado pelo pipeline real).
7. **Avaliação humana** (revisor: Leonardo Melo, RM 567097): abra `avaliacao/avaliacao_humana.csv` (separador `;`,
   UTF-8). São 74 linhas: 100% das respostas de R (42) e uma amostra pareada de S e P (16 perguntas cada, 1/3 de cada
   categoria, semente 42). Siga `avaliacao/rubrica.md`. Depois rode a seção N9 de novo: o CSV é validado e entra nas
   métricas.

**Parâmetros da busca (escolhidos só com o conjunto de desenvolvimento, em CPU, 2026-11-10):** k = 6 trechos e
limiar de abstenção τ = 0,860939. Tabela e regra em `evidencias/selecao_k_tau_2026-11-10.md`. O notebook recalcula o
τ no Colab e mostra a diferença.
8. Traga de volta para o repositório as pastas `avaliacao/`, `contrato/` e `evidencias/` (inclusive os prints da
   interface em `evidencias/prints/`) e o notebook baixado **com as saídas**.

## Como executar localmente (sem GPU)
```
python -m venv .venv
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -I testes_locais.py
```
Sem GPU, o Qwen não é carregado. As respostas "geradas" vêm de um **stub rotulado SIMULADO** (texto fixo), só para
testar o caminho todo. A busca (e5 + FAISS), o limiar τ, as rotas e os filtros rodam de verdade em CPU.

## Bibliotecas, modelos e serviços
| Item | Versão | Licença | Papel |
|---|---|---|---|
| `intfloat/multilingual-e5-small` | commit `614241f622f53c4eeff9890bdc4f31cfecc418b3` | MIT | embeddings (busca) |
| `Qwen/Qwen2.5-7B-Instruct` | commit `a09a35458c702b33eeacc393d103063234e8bc28` (o mesmo da PLN) | Apache-2.0 | geração da resposta |
| `Qwen/Qwen2.5-1.5B-Instruct` | revisão registrada no log, se usada | Apache-2.0 | reserva, se faltar memória |
| sentence-transformers | 6.2.0 | Apache-2.0 | carga do e5 e cálculo dos vetores |
| faiss-cpu | 1.15.1 | MIT | índice vetorial `IndexFlatIP` |
| transformers | 5.22.2 | Apache-2.0 | carga do Qwen e do tokenizador |
| langchain-core | 1.7.6 | MIT | cadeia LCEL do fluxo e `Document` |
| gradio | 6.31.0 | Apache-2.0 | interface e endpoint `/consultar` |
| accelerate, bitsandbytes | versão do Colab (registrada no log) | Apache-2.0, MIT | quantização em 4 bits (NF4) |
| torch | do Colab; local 2.15.0+cpu | estilo BSD | execução dos modelos |
| Google Colab (GPU T4) | serviço gratuito | termos do Google | onde o LLM roda |

Nenhuma chave de API é usada. O modelo roda dentro da sessão do Colab.

## Dados pessoais e segurança
Nenhum dado pessoal real. CPF, e-mail e telefone digitados na pergunta são mascarados antes de qualquer registro ou
chamada ao modelo. O assistente não tem login. O link público do Gradio só existe enquanto a sessão do Colab está
aberta e deve ser usado só na demonstração.

## Estado
Implementado e testado localmente (`evidencias/testes_locais_2026-11-10.txt`), executado no Colab com GPU Tesla T4
(DEC-032) e avaliado por um revisor humano (DEC-033). Resultados em `evidencias/EVIDENCIAS.md` e na documentação
técnica. Falta: prints da interface `[PENDENTE: prints, a tirar no dia da gravação]`.
Link do vídeo: `video/LINK.md` `[PENDENTE: gravação]`.
