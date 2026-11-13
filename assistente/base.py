"""N1 e N2: carga e validação do CT-01 (corpus da PLN) e montagem da base de conhecimento.

A GENAI NÃO refaz a Fábrica de Corpus (APR-011): não extrai, não limpa, não anonimiza nem segmenta documentos.
Ela lê o corpus_texto.jsonl da PLN, confere o contrato (hash, chaves, contagens) e monta a base de conhecimento:
cada linha vira um trecho T-NNN (NNN = indice_linha do CT-01, o mesmo número usado pela PLN em mapa_trechos e
qa_candidatos), com documento, título, URL, localização (artigo, item ou página) e aviso da Lei 14.016.
C3b: um trecho que passe de 512 tokens do tokenizador do e5 é dividido só para o embedding; os subtrechos
apontam para o mesmo T-NNN.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import config


class ErroCT01(RuntimeError):
    """O corpus da PLN não está como o contrato CT-01 manda. A mensagem diz o que corrigir."""


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest().upper()


def ler_jsonl(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def gravar_jsonl(caminho: Path, registros, modo: str = "w"):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, modo, encoding="utf-8", newline="\n") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- N1: validação do CT-01
def validar_ct01(pasta_corpus: Path | None = None, conferir_hash: bool = True) -> dict:
    """Confere os três JSONL do CT-01 e os anexos usados. Falha com ErroCT01 e mensagem clara."""
    pasta = Path(pasta_corpus or config.PASTA_CORPUS_PLN)
    if not pasta.exists():
        raise ErroCT01(f"Pasta do corpus da PLN não encontrada: {pasta}. No Colab, copie 05_ENTREGAVEIS/PLN para "
                       f"MyDrive/GS_FOMEZERO/PLN (ou ajuste GENAI_PASTA_PLN). Localmente, a PLN fica em ../PLN.")
    relatorio = {"pasta": str(pasta), "arquivos": {}}
    for nome, esperado in config.SHA256_CT01.items():
        arq = pasta / nome
        if not arq.exists():
            raise ErroCT01(f"CT-01: falta {nome} em {pasta}.")
        obtido = sha256(arq)
        if conferir_hash and obtido != esperado:
            raise ErroCT01(f"CT-01: SHA-256 de {nome} não confere.\n  esperado {esperado}\n  obtido   {obtido}\n"
                           "O corpus mudou depois da validação da PLN (DEC-024/025). Não siga: avise o ORQUESTRADOR.")
        linhas = []
        with open(arq, encoding="utf-8") as f:
            for n, l in enumerate(f, 1):
                if not l.strip():
                    continue
                try:
                    linhas.append(json.loads(l))
                except json.JSONDecodeError as e:
                    raise ErroCT01(f"CT-01: {nome}, linha {n} não é JSON válido ({e}).") from e
        fora = [i for i, r in enumerate(linhas) if sorted(r) != config.CHAVES_CT01[nome]]
        if fora:
            raise ErroCT01(f"CT-01: {nome} tem {len(fora)} linhas com chaves diferentes de "
                           f"{config.CHAVES_CT01[nome]} (primeiras: {fora[:5]}).")
        if len(linhas) != config.CONTAGENS_CT01[nome]:
            raise ErroCT01(f"CT-01: {nome} tem {len(linhas)} linhas; o contrato diz {config.CONTAGENS_CT01[nome]}.")
        if any(not str(r.get("fonte", "")).strip() for r in linhas):
            raise ErroCT01(f"CT-01: {nome} tem linha sem 'fonte'.")
        relatorio["arquivos"][nome] = {"linhas": len(linhas), "sha256": obtido, "hash_confere": obtido == esperado}
    texto = ler_jsonl(pasta / config.ARQ_TEXTO)
    fontes = sorted({r["fonte"] for r in texto})
    if fontes != sorted(config.FONTES_DOCUMENTOS):
        raise ErroCT01(f"CT-01: fontes do corpus_texto {fontes} diferentes de D1 a D4 {config.FONTES_DOCUMENTOS}.")
    relatorio["trechos_por_fonte"] = {f: sum(r["fonte"] == f for r in texto) for f in fontes}
    # recusas do corpus_chat (T7): as 12 linhas 40 a 51 começam com as 12 perguntas da política de recusa da PLN
    chat = ler_jsonl(pasta / config.ARQ_CHAT)
    perguntas_pln = {p["pergunta"]: p for p in carregar_recusas_pln()}
    for i in config.INDICES_RECUSAS_CHAT:
        msgs = chat[i]["messages"]
        if msgs[0]["role"] != "system" or msgs[1]["role"] != "user" or msgs[1]["content"].strip() not in perguntas_pln:
            raise ErroCT01(f"CT-01: corpus_chat linha {i} não é uma das 12 recusas da PLN.")
    n_fora = sum(chat[i]["fonte"] == config.FONTE_RECUSA_FORA_DO_TEMA for i in config.INDICES_RECUSAS_CHAT)
    relatorio["recusas"] = {"indices": config.INDICES_RECUSAS_CHAT, "fora_do_tema": n_fora,
                            "encaminhamento": len(config.INDICES_RECUSAS_CHAT) - n_fora}
    # anexos
    for nome, caminho in (("mapa_trechos.jsonl", config.ARQ_MAPA_TRECHOS),
                          ("qa_candidatos.jsonl", config.ARQ_QA_CANDIDATOS),
                          ("perguntas_recusa.json", config.ARQ_RECUSAS_PLN)):
        if not caminho.exists():
            raise ErroCT01(f"CT-01 (anexo): falta {caminho}.")
        obtido = sha256(caminho)
        if conferir_hash and obtido != config.SHA256_AUXILIARES[nome]:
            raise ErroCT01(f"CT-01 (anexo): SHA-256 de {nome} não confere ({obtido}).")
        relatorio["arquivos"][nome] = {"sha256": obtido, "hash_confere": obtido == config.SHA256_AUXILIARES[nome]}
    mapa = ler_jsonl(config.ARQ_MAPA_TRECHOS)
    if [m["indice_linha"] for m in mapa] != list(range(len(texto))) or any(
            m["fonte"] != texto[m["indice_linha"]]["fonte"] for m in mapa):
        raise ErroCT01("CT-01 (anexo): mapa_trechos.jsonl não corresponde linha a linha ao corpus_texto.jsonl.")
    relatorio["ok"] = True
    return relatorio


def carregar_recusas_pln() -> list[dict]:
    return json.loads(config.ler_texto(config.ARQ_RECUSAS_PLN))["perguntas"]


def carregar_links() -> dict:
    """Lê documentos/LINKS.md da PLN: fonte -> id, título, órgão e URL oficial (uma única fonte da verdade)."""
    links = {}
    for linha in config.ler_texto(config.ARQ_LINKS_PLN).splitlines():
        cel = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(cel) >= 5 and re.fullmatch(r"D\d", cel[0]):
            fonte = cel[1].strip("`")
            links[fonte] = {"id": cel[0], "titulo": cel[2], "orgao": cel[3], "url": cel[4]}
    faltam = [f for f in config.FONTES_DOCUMENTOS if f not in links]
    if faltam:
        raise ErroCT01(f"LINKS.md da PLN sem as fontes {faltam}.")
    return links


# ---------------------------------------------------------------- N2: base de conhecimento
RE_ARTIGO = re.compile(r"\bArt\.\s*(\d+)")
RE_ITEM = re.compile(r"(?m)^(\d+(?:\.\d+)+)\.?\s")
# O D3 chama a Lei 14.016/2020 de "Lei de Doação de Alimentos" (trecho T-034), por isso a expressão pega os dois.
RE_LEI_14016 = re.compile(r"14\.?016|Lei de Doação")


def localizacao(texto: str, doc_id: str, pag_ini, pag_fim) -> str:
    """D1/D2 (HTML): artigos ou itens que aparecem no trecho. D3/D4 (PDF): páginas do mapa_trechos (DEC-015)."""
    if doc_id in ("D3", "D4"):
        if pag_ini is None:
            return "documento"
        return f"p. {pag_ini}" if pag_ini == pag_fim or pag_fim is None else f"p. {pag_ini} a {pag_fim}"
    itens = RE_ITEM.findall(texto) if doc_id == "D2" else []
    if itens:
        return f"item {itens[0]}" if len(set(itens)) == 1 else f"itens {itens[0]} a {itens[-1]}"
    arts = RE_ARTIGO.findall(texto)
    if arts:
        return f"art. {arts[0]}" if len(set(arts)) == 1 else f"arts. {arts[0]} a {arts[-1]}"
    return "documento"


def id_trecho(indice_linha: int) -> str:
    return f"T-{indice_linha:03d}"


def construir_base(pasta_corpus: Path | None = None) -> list[dict]:
    pasta = Path(pasta_corpus or config.PASTA_CORPUS_PLN)
    texto = ler_jsonl(pasta / config.ARQ_TEXTO)
    mapa = {m["indice_linha"]: m for m in ler_jsonl(config.ARQ_MAPA_TRECHOS)}
    links = carregar_links()
    base = []
    for i, r in enumerate(texto):
        info = links[r["fonte"]]
        m = mapa.get(i, {})
        cita_14016 = bool(RE_LEI_14016.search(r["text"])) and info["id"] != "D1"   # o D1 é a lei que revoga
        base.append({
            "id": id_trecho(i), "indice_linha": i, "fonte": r["fonte"], "doc_id": info["id"],
            "titulo": info["titulo"], "orgao": info["orgao"], "url": info["url"],
            "localizacao": localizacao(r["text"], info["id"], m.get("pagina_inicial"), m.get("pagina_final")),
            "pagina_inicial": m.get("pagina_inicial"), "pagina_final": m.get("pagina_final"),
            "cita_lei_14016": cita_14016, "texto": r["text"],
        })
    return base


def documentos_langchain(base: list[dict]):
    """A mesma base como Documents do LangChain (metadados de fonte e localização), para quem quiser usar
    os componentes do LangChain sobre ela."""
    from langchain_core.documents import Document
    return [Document(page_content=t["texto"], metadata={k: v for k, v in t.items() if k != "texto"}) for t in base]


# ---------------------------------------------------------------- C3b: divisão só para o embedding
RE_FRASE = re.compile(r"(?<=[.!?;:])\s+")


def _n_tokens(tok, texto: str) -> int:
    return len(tok(config.PREFIXO_PASSAGEM + texto, add_special_tokens=True)["input_ids"])


def dividir_para_embedding(base: list[dict], tok, max_tokens: int = config.MAX_TOKENS_E5) -> tuple[list[dict], dict]:
    """Não refaz a segmentação da PLN: só divide o trecho que passa de `max_tokens` do tokenizador do e5
    (contando o prefixo "passage: " e os tokens especiais), por parágrafo e, se preciso, por frase."""
    subtrechos, estat = [], {"trechos": len(base), "divididos": 0, "tokens_e5_max_original": 0,
                             "tokens_e5_max_subtrecho": 0, "acima_de_512_original": []}
    for t in base:
        n = _n_tokens(tok, t["texto"])
        estat["tokens_e5_max_original"] = max(estat["tokens_e5_max_original"], n)
        if n <= max_tokens:
            partes = [t["texto"]]
        else:
            estat["divididos"] += 1
            estat["acima_de_512_original"].append({"id": t["id"], "tokens_e5": n})
            unidades = []
            for par in t["texto"].split("\n\n"):
                if _n_tokens(tok, par) <= max_tokens:
                    unidades.append(par)
                else:
                    unidades.extend(RE_FRASE.split(par))
            partes, atual = [], ""
            for u in unidades:
                cand = (atual + "\n\n" + u) if atual else u
                if _n_tokens(tok, cand) <= max_tokens:
                    atual = cand
                else:
                    if atual:
                        partes.append(atual)
                    atual = u
            if atual:
                partes.append(atual)
        for k, p in enumerate(partes):
            nt = _n_tokens(tok, p)
            estat["tokens_e5_max_subtrecho"] = max(estat["tokens_e5_max_subtrecho"], nt)
            subtrechos.append({"id_trecho": t["id"], "parte": k, "texto": p, "tokens_e5": nt})
    estat["subtrechos"] = len(subtrechos)
    estat["subtrechos_acima_do_limite"] = sum(s["tokens_e5"] > max_tokens for s in subtrechos)
    return subtrechos, estat
