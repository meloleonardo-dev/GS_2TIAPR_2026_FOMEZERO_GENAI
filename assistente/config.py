"""Configuração única do Assistente de consulta FOMEZERO (GENAI).

Todos os parâmetros do Design aprovado (02_MATERIAS/GENAI/DESENVOLVIMENTO.md, DL-GENAI-01 a 12, DEC-014)
ficam aqui, para o notebook, os testes locais e a interface Gradio usarem os MESMOS valores.
Valores do grupo ainda pendentes ficam parametrizados e marcados [PENDENTE].
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- pastas
EM_COLAB = "google.colab" in sys.modules
PASTA_GENAI = Path(os.environ.get("GENAI_PASTA", Path(__file__).resolve().parents[1]))

# CT-01: ÚNICO lugar com o caminho da PLN. O corpus NÃO é copiado para a GENAI: é lido da pasta da PLN.
#   local: 05_ENTREGAVEIS/PLN (irmã de 05_ENTREGAVEIS/GENAI)
#   Colab: /content/drive/MyDrive/GS_FOMEZERO/PLN (as duas pastas copiadas para MyDrive/GS_FOMEZERO/)
# A variável de ambiente GENAI_PASTA_PLN troca o caminho, se a pasta estiver em outro lugar.
PASTA_PLN = Path(os.environ.get(
    "GENAI_PASTA_PLN",
    "/content/drive/MyDrive/GS_FOMEZERO/PLN" if EM_COLAB else PASTA_GENAI.parent / "PLN"))
PASTA_CORPUS_PLN = PASTA_PLN / "corpus"
ARQ_MAPA_TRECHOS = PASTA_PLN / "saidas" / "mapa_trechos.jsonl"        # página por trecho (aprovado na DEC-015)
ARQ_QA_CANDIDATOS = PASTA_PLN / "revisao" / "qa_candidatos.jsonl"     # indice_linha do trecho-ouro (T8)
ARQ_RECUSAS_PLN = PASTA_PLN / "revisao" / "prompts" / "perguntas_recusa.json"  # política de recusa da PLN
ARQ_LINKS_PLN = PASTA_PLN / "documentos" / "LINKS.md"                  # título e URL oficial de cada fonte
ARQ_M7_PLN = PASTA_PLN / "fabrica" / "m7_ia.py"                        # só leitura: lista de frases proibidas

PASTA_PROMPTS = PASTA_GENAI / "prompts"
PASTA_AVALIACAO = PASTA_GENAI / "avaliacao"
PASTA_CONTRATO = PASTA_GENAI / "contrato"
PASTA_EVIDENCIAS = PASTA_GENAI / "evidencias"
PASTA_INDICE = PASTA_GENAI / "indice"          # índice FAISS salvo (o .faiss fica fora do git)

# ---------------------------------------------------------------- CT-01 (DEC-024/025): conferência obrigatória
ARQ_TEXTO, ARQ_QA, ARQ_CHAT = "corpus_texto.jsonl", "corpus_qa.jsonl", "corpus_chat.jsonl"
SHA256_CT01 = {   # calculados uma vez em 2026-11-09 sobre os arquivos finais da PLN; o N1 falha se não baterem
    ARQ_TEXTO: "547B287EE59CF8602FC78B4C4F5E62D5570CE2E3EACE0C7CFFDAF142329ABC86",
    ARQ_QA: "B0A2C66999196AC43114E9A27A6B0C0DC820B7DB10E5AE8DF45965A54AE697C9",
    ARQ_CHAT: "0963DD7DB8E1D50F1112387F6137C00D9333B56B99C6259C69353EB987D6D61F",
}
# Atualizado em 2026-11-11 (DEC-038). corpus_texto: 2 sobrenomes de autores mascarados (T-052 e T-110), segmentação
# igual. corpus_chat: 2 diálogos corrigidos na revisão humana (linhas 33 e 52; falas do usuário iguais). Hashes usados
# na execução do Colab de 2026-11-10: texto F714BD8DDCAE736FDCC018A586F5ADEA13C0E07D2CB6F3CD99BC7C61D674C8D1,
# chat 0E00C564C60159550D122CE28BC32FE44E04E091700B017C7FCD6864E6C86A0E
SHA256_AUXILIARES = {   # anexos da PLN usados pela GENAI (também conferidos)
    "mapa_trechos.jsonl": "8216FE7A4574C7FAF57668E6DD59736BEE663ECCF49222998464A0EE0909E87E",
    "qa_candidatos.jsonl": "15DE6DBDC01E9DA046B9CA0F7590DAF933DC00ECB8FCDA66D7CF4498669A7719",
    "perguntas_recusa.json": "CE4299C2A97B5673EDC653A6E649285623C7600363E9260E62C284285E3D6E20",
}
CHAVES_CT01 = {ARQ_TEXTO: ["fonte", "text"], ARQ_QA: ["fonte", "input", "instruction", "output"],
               ARQ_CHAT: ["fonte", "messages"]}
CONTAGENS_CT01 = {ARQ_TEXTO: 149, ARQ_QA: 143, ARQ_CHAT: 52}
INDICES_RECUSAS_CHAT = list(range(40, 52))     # 12 recusas do corpus_chat (estatisticas_geracao.json da PLN)
FONTE_RECUSA_FORA_DO_TEMA = "recusa_fora_do_tema"
FONTES_DOCUMENTOS = ["D1_Lei_15224_2025.htm", "D2_RDC_ANVISA_216_2004.html",
                     "D3_Guia_ANVISA_57_2022_Doacao_Alimentos_v1.pdf",
                     "D4_Guia_ANVISA_Boas_Praticas_Bancos_Alimentos.pdf"]
NOME_CURTO = {"D1": "Lei nº 15.224/2025", "D2": "RDC ANVISA nº 216/2004", "D3": "Guia ANVISA nº 57/2022",
              "D4": "Guia ANVISA de Boas Práticas para Bancos de Alimentos"}

# ---------------------------------------------------------------- embeddings e índice (DL-GENAI-03)
MODELO_EMBEDDING = "intfloat/multilingual-e5-small"            # MIT (F-008)
REVISAO_EMBEDDING = "614241f622f53c4eeff9890bdc4f31cfecc418b3"  # commit baixado em 2026-11-09
PREFIXO_CONSULTA, PREFIXO_PASSAGEM = "query: ", "passage: "     # exigidos pelo e5
MAX_TOKENS_E5 = 512           # o e5 trunca em 512 tokens: trechos maiores são divididos (C3b)
# trechos entregues ao LLM. Era 4 no Design ([HIPÓTESE], "ajustar no desenvolvimento"). Escolhido 6 em 2026-11-10
# (TAR-008, DEC-028; confirmado na TAR-009) SÓ com o desenvolvimento (33 perguntas T1/T2): hit@4 0,667; hit@6 0,758; hit@8 0,788; regra
# "menor k a no máximo 1 pergunta do melhor". Evidência: evidencias/selecao_k_tau_2026-11-10.md (CPU, e5 614241f6).
K = 6
K_BUSCA_SUBTRECHOS = 24       # subtrechos buscados antes de agrupar por trecho
VERSAO_INDICE = "e5small-flatip-v1"

# ---------------------------------------------------------------- LLM (DL-GENAI-04), mesmo modelo e revisão da PLN
MODELO_LLM = "Qwen/Qwen2.5-7B-Instruct"                        # Apache-2.0 (F-009)
REVISAO_LLM = "a09a35458c702b33eeacc393d103063234e8bc28"
MODELO_RESERVA = "Qwen/Qwen2.5-1.5B-Instruct"                  # Apache-2.0 (F-011); o 3B NÃO (licença qwen-research)
REVISAO_RESERVA = None        # [PENDENTE] o commit usado fica registrado no log (config._commit_hash) na execução
TEMPERATURA = 0.1
MAX_NOVOS_TOKENS = 400
SEMENTE = 42
TEMPO_LIMITE_S = 60           # [HIPÓTESE] tempo limite do CT-02 (PEN-014); vira max_time da geração

# ---------------------------------------------------------------- entrada e política (DL-GENAI-05, 06, 11, 12)
MAX_CARACTERES = 500
# Limiar de abstenção τ: nunca fixado à mão. Valor calibrado em 2026-11-10 (TAR-008) no desenvolvimento ampliado
# e recalibrado na TAR-009 (sem a T4-07; 33 que devem responder x 18 que não devem, peso 2; mesmo valor), em CPU: evidencias/selecao_k_tau_2026-11-10.md e
# avaliacao/calibracao_tau.json. O notebook (N7) recalcula no Colab e mostra a diferença para este valor.
TAU = 0.860939
PESO_FALSO_RESPONDIDA = 2.0   # [HIPÓTESE] na calibração, responder sem evidência pesa 2x uma abstenção a mais
FRACAO_DESENVOLVIMENTO = 1 / 3
REVISOR = "Leonardo Melo, RM 567097"   # DEC-015 (PEN-023)
CT02_VERSAO = "ct02-v0"                # proposta; decisão final do Erick (PEN-014)
CONFIGURACOES = ("S", "P", "R")

AVISO_VALIDACAO_HUMANA = ("Resposta informativa, baseada nos documentos citados. Ela não substitui a avaliação da "
                          "vigilância sanitária do seu município nem de um profissional habilitado. O FOMEZERO não "
                          "declara se um alimento é seguro para consumo.")
AVISO_LEI_14016 = ("Atenção: um trecho usado cita a Lei nº 14.016/2020, que foi revogada pela Lei nº 15.224/2025 "
                   "(art. 19). Confira a regra atual na Lei nº 15.224/2025.")

# contexto_lote (CT-02): [PENDENTE PEN-001]. Só estes campos, em texto livre, e só para enriquecer a busca.
CAMPOS_CONTEXTO_LOTE = ("alimento", "condicao")
# Valores do grupo que o assistente NÃO usa (não informa): limite de temperatura próprio (PEN-002),
# fator de CO2 (PEN-003, sem fonte), pontos e Selo Verde ESG. Município sem nome (PEN-017).
ORGAO_PADRAO = "a vigilância sanitária do seu município"


def ler_texto(caminho: Path) -> str:
    return Path(caminho).read_text(encoding="utf-8")


def ler_prompt(nome: str) -> str:
    """Prompts versionados em prompts/ (vão inteiros para a documentação)."""
    return ler_texto(PASTA_PROMPTS / nome).strip()
