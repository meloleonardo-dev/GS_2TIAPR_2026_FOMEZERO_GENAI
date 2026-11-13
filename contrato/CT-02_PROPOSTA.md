# CT-02 (GENAI → FEMD): proposta `ct02-v0`

**Status: PROPOSTA.** A decisão final é do Erick, responsável pela FEMD (PEN-014). Este arquivo descreve o que a
GENAI já entrega. Nada aqui obriga a FEMD a mudar o próprio desenho.

## Formas de ligar (a FEMD escolhe)
| Opção | Como | Prós | Contras |
|---|---|---|---|
| T1 | a FEMD chama o endpoint Gradio `/consultar` com `@gradio/client`: `Client.connect(URL)` e `predict("/consultar", [entrada])` | integração real, sem servidor próprio | o link do Colab é temporário e só existe com a sessão aberta |
| T2 | `iframe` com a interface Gradio dentro da tela da FEMD | mais simples | a FEMD não controla o layout nem os dados |
| T3 | modo simulado: a FEMD lê `contrato/respostas_SIMULADO.json` | funciona sem internet nem GPU | não é IA ao vivo; exige a faixa "Resposta SIMULADA" na tela |

Exemplo com o cliente JavaScript (opção T1):
```js
import { Client } from "@gradio/client";
const app = await Client.connect("https://xxxx.gradio.live");   // link mostrado na seção N10 do notebook
const r = await app.predict("/consultar", [{ versao: "ct02-v0", pergunta: "Como devo transportar comida pronta?", perfil: "doador", modo: "real" }]);
console.log(r.data[0].status, r.data[0].resposta, r.data[0].aviso_validacao_humana);
```

## Entrada
```json
{"versao": "ct02-v0", "pergunta": "Como devo transportar comida pronta para doar?", "perfil": "doador",
 "contexto_lote": null, "id_sessao": "a1b2c3", "modo": "real"}
```
- `pergunta`: texto de 1 a 500 caracteres (obrigatório). CPF, e-mail e telefone são mascarados antes de tudo.
- `perfil`: `doador`, `beneficiario` ou `outro` (opcional).
- `contexto_lote`: opcional e `[PENDENTE: PEN-001]`. Só os campos `alimento` e `condicao`, em texto livre, até 200
  caracteres cada. Servem só para melhorar a busca, **nunca** para decidir se o lote pode ser doado. Outros campos
  são ignorados e aparecem num aviso.
- `id_sessao`: gerado no navegador, sem dado pessoal (volta em `meta.id_sessao`).
- `modo`: `real` ou `simulado` (no simulado, a resposta vem de `respostas_SIMULADO.json`).

## Saída
```json
{"versao": "ct02-v0", "status": "respondida", "resposta": "Em resumo: ... [T-073]",
 "fontes": [{"id_trecho": "T-073", "documento": "D3_Guia_ANVISA_57_2022_Doacao_Alimentos_v1.pdf",
             "titulo": "Guia para Doação de Alimentos com Segurança Sanitária ...", "localizacao": "p. 45 a 46",
             "trecho": "até 300 caracteres do trecho", "url": "https://antigo.anvisa.gov.br/..."}],
 "encaminhamento": null, "avisos": [], "aviso_validacao_humana": "Resposta informativa, ...",
 "simulado": false, "meta": {"modelo": "Qwen/Qwen2.5-7B-Instruct (4 bits NF4)", "k": 4, "score_max": 0.0, "tempo_ms": 0}}
```
O exemplo mostra só o formato. Conteúdo, página e números são ilustrativos. Exemplos produzidos pelo código estão
em `exemplos_ct02.json` (as respostas "geradas" ali vêm do stub SIMULADO e estão marcadas).

| Campo | O que é |
|---|---|
| `status` | `respondida`, `abstencao`, `encaminhamento`, `recusa_fora_do_tema`, `recusa_seguranca` ou `erro` |
| `resposta` | texto curto, com as citações `[T-NNN]` |
| `fontes` | trechos citados (vazio em abstenção e nas recusas); `localizacao` = artigo ou item (D1, D2) ou página (D3, D4) |
| `encaminhamento` | `{"orgao", "motivo"}` em encaminhamento e em abstenção; `null` nos outros casos |
| `avisos` | ex.: Lei 14.016/2020 revogada; dados pessoais mascarados; resposta SIMULADA |
| `aviso_validacao_humana` | **sempre presente**; a FEMD exibe junto da resposta |
| `simulado` | `true` quando a resposta não é IA ao vivo (stub de teste ou modo simulado gravado) |
| `meta` | modelo, k, score máximo, limiar τ, rota, trechos recuperados, tempo em ms, data |

Texto do aviso fixo: "Resposta informativa, baseada nos documentos citados. Ela não substitui a avaliação da
vigilância sanitária do seu município nem de um profissional habilitado. O FOMEZERO não declara se um alimento é
seguro para consumo."

## Erros
`{"status": "erro", "erro": {"codigo": "...", "mensagem": "..."}, "aviso_validacao_humana": "..."}`
| Código | Quando |
|---|---|
| `ENTRADA_VAZIA` | pergunta vazia |
| `ENTRADA_LONGA` | mais de 500 caracteres |
| `SERVICO_INDISPONIVEL` | o assistente não está carregado (a FEMD também usa quando o link não responde) |
| `TEMPO_ESGOTADO` | lado da FEMD: sem resposta em 60 s `[HIPÓTESE]`; no assistente, a geração é cortada em 60 s |
| `ERRO_INTERNO` | falha inesperada (detalhe em `meta`) |
| `SIMULADO_NAO_ENCONTRADO` | **acréscimo desta versão:** `modo: "simulado"` com uma pergunta que não foi gravada |

Em `SERVICO_INDISPONIVEL` e `TEMPO_ESGOTADO`, a proposta é a FEMD mostrar a mensagem e oferecer as perguntas do modo
simulado.

## Limites do contrato
- O assistente não informa pontos, Selo Verde ESG nem CO₂ evitado. Essas regras são do FOMEZERO (PEN-003: o fator
  de CO₂ não tem fonte).
- O assistente não decide sobre um lote de doação. Quem decide é a vigilância sanitária do município ou um
  profissional habilitado.
- O link do Colab não é produção. Hospedagem permanente é evolução futura.
