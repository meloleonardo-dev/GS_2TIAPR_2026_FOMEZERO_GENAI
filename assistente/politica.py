"""N7: entrada (C1), classificador de política (C2) e pós-processamento (C9).

- C1: valida o tamanho (1 a 500 caracteres), normaliza (NFC) e mascara CPF, e-mail e telefone ANTES de qualquer
  registro ou chamada ao modelo (DL-GENAI-12; mesmas expressões regulares do M5 da PLN).
- C2: decide a rota por regras e palavras-chave revisáveis (prompts/palavras_chave_rotas.txt). O LLM não decide a rota.
  Rotas: DENTRO_DO_TEMA, ENCAMINHAMENTO, FORA_DO_TEMA, INJECAO (mesma política de recusa da PLN + injeção).
- C9: confere o JSON, as citações (só trechos recuperados), a lista de frases proibidas da PLN ("nunca seguro"),
  números de pontos/CO₂, o aviso da Lei 14.016 e o encaminhamento obrigatório.
- Calibração do limiar de abstenção τ com dados do conjunto de desenvolvimento (§2.7.3).
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache

from . import config

# ---------------------------------------------------------------- C1 entrada (regras do M5 da PLN)
RE_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w-])")
RE_CPF = re.compile(r"(?<![\d.])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d])")
RE_TELEFONE = re.compile(
    r"(?<![\w/.-])(?:"
    r"(?:\+?55[\s.-]?)?(?:\(\d{2}\)|\d{2})[\s.-]?9?\s?\d{4}[\s.-]\d{4}"
    r"|\d{4,5}-\d{4}"
    r"|0800[\s.-]?\d{2,3}[\s.-]?\d{4}"
    r")(?![\w/-])")
RE_CONTEXTO_NORMA = re.compile(r"(Lei|Decreto|Portaria|RDC|Resolução|Instrução|art\.|arts\.|nº|n°|n\.º|Processo|SEI|"
                               r"ISO|NBR|CNPJ|CEP|ABNT|Guia)\s*[^\s]*\s*$", re.I)
RE_INTERVALO_ANOS = re.compile(r"^(19|20)\d{2}-(19|20)\d{2}$")


def _e_telefone(texto: str, m) -> bool:
    return (not RE_CONTEXTO_NORMA.search(texto[max(0, m.start() - 25):m.start()])
            and not RE_INTERVALO_ANOS.match(m.group(0)))


def mascarar_dados_pessoais(texto: str) -> tuple[str, dict]:
    """E-mail -> CPF -> telefone (mesma ordem da PLN). Devolve o texto mascarado e a contagem por tipo."""
    cont = {"EMAIL": 0, "CPF": 0, "TELEFONE": 0}

    def sub(rx, tipo, t, filtro=None):
        partes, pos = [], 0
        for m in rx.finditer(t):
            if filtro and not filtro(t, m):
                continue
            partes += [t[pos:m.start()], f"[{tipo}]"]
            cont[tipo] += 1
            pos = m.end()
        return "".join(partes + [t[pos:]])

    texto = sub(RE_EMAIL, "EMAIL", texto)
    texto = sub(RE_CPF, "CPF", texto)
    texto = sub(RE_TELEFONE, "TELEFONE", texto, _e_telefone)
    return texto, cont


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(texto or ""))).strip()


def validar_entrada(pergunta) -> str | None:
    """Devolve o código de erro do CT-02 ou None."""
    p = normalizar(pergunta)
    if not p:
        return "ENTRADA_VAZIA"
    if len(p) > config.MAX_CARACTERES:
        return "ENTRADA_LONGA"
    return None


# ---------------------------------------------------------------- C2 classificador de política
def sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


@lru_cache(maxsize=1)
def regras_rotas() -> dict:
    secoes, atual = {}, None
    for linha in config.ler_prompt("palavras_chave_rotas.txt").splitlines():
        l = linha.strip()
        if not l or l.startswith("#"):
            continue
        m = re.fullmatch(r"\[([A-Z_:a-z]+)\]", l)
        if m:
            atual = m.group(1)
            secoes[atual] = []
            continue
        secoes[atual].append(re.compile(l, re.I))
    return secoes


def _primeira(secao: str, t: str):
    for rx in regras_rotas().get(secao, []):
        m = rx.search(t)
        if m:
            return rx.pattern, m.group(0)
    return None


def classificar_rota(pergunta: str) -> dict:
    """Rota da política (C2). Devolve {"rota", "subtipo", "regra", "trecho_casado"}."""
    t = sem_acento(normalizar(pergunta))
    if (r := _primeira("INJECAO", t)):
        return {"rota": "INJECAO", "subtipo": None, "regra": r[0], "trecho_casado": r[1]}
    for sub in ("fomezero", "geral"):
        if (r := _primeira(f"FORA_DO_TEMA:{sub}", t)):
            return {"rota": "FORA_DO_TEMA", "subtipo": sub, "regra": r[0], "trecho_casado": r[1]}
    for sub in ("juridico", "saude", "profissional", "autorizacao", "decisao"):   # jurídico antes: R10 da PLN
        if (r := _primeira(f"ENCAMINHAMENTO:{sub}", t)):
            return {"rota": "ENCAMINHAMENTO", "subtipo": sub, "regra": r[0], "trecho_casado": r[1]}
    c, v = _primeira("CONDICAO", t), _primeira("DECISAO_VERBO", t)
    if c and v:
        return {"rota": "ENCAMINHAMENTO", "subtipo": "decisao", "regra": f"CONDICAO {c[0]} + DECISAO_VERBO {v[0]}",
                "trecho_casado": f"{c[1]} + {v[1]}"}
    return {"rota": "DENTRO_DO_TEMA", "subtipo": None, "regra": None, "trecho_casado": None}


@lru_cache(maxsize=1)
def textos_fixos() -> dict:
    return json.loads(config.ler_prompt("textos_fixos.json"))


def orgao(subtipo: str | None) -> dict:
    return textos_fixos()["orgaos"].get(subtipo or "decisao")


# ---------------------------------------------------------------- C9 pós-processamento
@lru_cache(maxsize=1)
def frases_proibidas() -> list[re.Pattern]:
    return [re.compile(l.strip(), re.I) for l in config.ler_prompt("frases_proibidas.txt").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def detectar_frases_proibidas(texto: str) -> list[str]:
    return [m.group(0) for rx in frases_proibidas() for m in [rx.search(texto or "")] if m]


RE_NUMERO_FOMEZERO = re.compile(
    r"\d[\d.,]*\s*(pontos?\b|kg\s*(de\s*)?co\s*[2₂]|co\s*[2₂])|\b(pontos?|co\s*[2₂](eq)?)\s*(:|=|de)?\s*\d"
    r"|selo\s+verde[^.]{0,40}\b(bronze|prata|ouro)\b|\b(bronze|prata|ouro)\b[^.]{0,40}selo\s+verde", re.I)


def detectar_numeros_fomezero(texto: str) -> list[str]:
    return [m.group(0) for m in RE_NUMERO_FOMEZERO.finditer(texto or "")]


RE_CITACAO = re.compile(r"\[(T-\d{3})\]")


def citacoes_no_texto(texto: str) -> list[str]:
    return RE_CITACAO.findall(texto or "")


def verificar_citacoes(citacoes: list[str], recuperados: list[str]) -> tuple[list[str], list[str]]:
    validas, invalidas = [], []
    for c in citacoes:
        (validas if c in recuperados else invalidas).append(c)
    return list(dict.fromkeys(validas)), list(dict.fromkeys(invalidas))


def remover_citacoes_invalidas(texto: str, invalidas: list[str]) -> str:
    for c in invalidas:
        texto = texto.replace(f"[{c}]", "")
    return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", texto)).strip()


def menciona_encaminhamento(texto: str) -> bool:
    t = sem_acento(texto or "")
    return bool(re.search(r"vigilancia\s+sanitaria|profissional\s+(legalmente\s+)?habilitad|servico\s+de\s+saude|"
                          r"\bmedic|advogad|defensoria", t))


def validar_json_resposta(obj, exige_citacoes: bool) -> list[str]:
    falhas = []
    if not isinstance(obj, dict):
        return ["JSON inválido ou ausente"]
    if not isinstance(obj.get("resposta"), str) or not obj["resposta"].strip():
        falhas.append("campo 'resposta' vazio ou ausente")
    if not isinstance(obj.get("suficiente"), bool):
        falhas.append("campo 'suficiente' não é true/false")
    if exige_citacoes and not isinstance(obj.get("citacoes", []), list):
        falhas.append("campo 'citacoes' não é lista")
    return falhas


def pos_processar(obj, recuperados: list[str] | None, rota: str, exige_citacoes: bool) -> dict:
    """Aplica as verificações do C9 a uma saída do LLM já convertida em objeto.
    Devolve {"ok", "falhas", "resposta", "citacoes_brutas", "citacoes_validas", "citacoes_invalidas",
    "frases_proibidas", "numeros_fomezero", "suficiente"}."""
    falhas = validar_json_resposta(obj, exige_citacoes)
    if falhas:
        return {"ok": False, "falhas": falhas, "resposta": None, "citacoes_brutas": [], "citacoes_validas": [],
                "citacoes_invalidas": [], "frases_proibidas": [], "numeros_fomezero": [], "suficiente": None}
    texto = obj["resposta"].strip()
    brutas = list(dict.fromkeys([c for c in (obj.get("citacoes") or []) if isinstance(c, str)] + citacoes_no_texto(texto)))
    validas, invalidas = verificar_citacoes(brutas, recuperados or []) if exige_citacoes else ([], brutas)
    texto = remover_citacoes_invalidas(texto, invalidas)
    proib = detectar_frases_proibidas(texto)
    nums = detectar_numeros_fomezero(texto)
    if proib:
        falhas.append(f"frase proibida: {proib}")
    if nums:
        falhas.append(f"número de pontos/CO2/Selo Verde ESG: {nums}")
    if exige_citacoes and obj["suficiente"] and rota == "DENTRO_DO_TEMA" and not validas:
        falhas.append("rota respondida sem nenhuma citação válida")
    return {"ok": not falhas, "falhas": falhas, "resposta": texto, "citacoes_brutas": brutas,
            "citacoes_validas": validas, "citacoes_invalidas": invalidas, "frases_proibidas": proib,
            "numeros_fomezero": nums, "suficiente": obj["suficiente"]}


# ---------------------------------------------------------------- calibração de τ (§2.7.3)
def calibrar_tau(scores_positivos: list[float], scores_negativos: list[float],
                 peso_falso_respondida: float = config.PESO_FALSO_RESPONDIDA) -> dict:
    """τ que minimiza custo = peso × (negativos com score ≥ τ) + (positivos com score < τ).
    Positivos: perguntas que devem ser respondidas (T1/T2 de desenvolvimento). Negativos: as que não devem (T4/T5).
    Empate: fica o maior τ (mais conservador: prefere abster-se a responder sem evidência)."""
    if not scores_positivos or not scores_negativos:
        raise ValueError("Calibração de τ precisa de perguntas positivas e negativas no conjunto de desenvolvimento.")
    todos = sorted(set(scores_positivos) | set(scores_negativos))
    candidatos = [todos[0] - 1e-6] + [(a + b) / 2 for a, b in zip(todos, todos[1:])] + [todos[-1] + 1e-6]
    tabela = []
    for tau in candidatos:
        fp = sum(s >= tau for s in scores_negativos)
        fn = sum(s < tau for s in scores_positivos)
        tabela.append({"tau": round(tau, 6), "falso_respondida": fp, "abstencao_indevida": fn,
                       "custo": peso_falso_respondida * fp + fn})
    melhor = min(tabela, key=lambda r: (r["custo"], -r["tau"]))
    return {"tau": melhor["tau"], "custo": melhor["custo"], "falso_respondida": melhor["falso_respondida"],
            "abstencao_indevida": melhor["abstencao_indevida"], "n_positivos": len(scores_positivos),
            "n_negativos": len(scores_negativos), "peso_falso_respondida": peso_falso_respondida, "tabela": tabela}
