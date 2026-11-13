"""N3 e N4: embeddings multilingual-e5-small e índice FAISS IndexFlatIP (busca exata por cosseno).

- Prefixos obrigatórios do e5: "query: " na consulta e "passage: " no trecho (F-008).
- Vetores normalizados (norma 1): o produto interno do IndexFlatIP é o cosseno.
- O índice é salvo em disco (indice/indice_e5.faiss + indice_meta.json + subtrechos.jsonl) e reaproveitado
  enquanto o corpus, o modelo e a divisão C3b forem os mesmos (conferido pelo meta).
- A busca procura subtrechos e agrupa por trecho T-NNN (maior score), devolvendo os k melhores trechos.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import config
from .base import dividir_para_embedding, gravar_jsonl, ler_jsonl, sha256


def dispositivo() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def carregar_embedder(device: str | None = None):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(config.MODELO_EMBEDDING, revision=config.REVISAO_EMBEDDING, device=device or dispositivo())
    m.max_seq_length = config.MAX_TOKENS_E5
    return m


def embed(embedder, textos: list[str], prefixo: str, lote: int = 32) -> np.ndarray:
    v = embedder.encode([prefixo + t for t in textos], batch_size=lote, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(v, dtype="float32")


class Indice:
    def __init__(self, faiss_index, subtrechos: list[dict], meta: dict, embedder):
        self.faiss, self.subtrechos, self.meta, self.embedder = faiss_index, subtrechos, meta, embedder

    def buscar_vetores(self, vetores: np.ndarray, k: int = config.K, k_sub: int = config.K_BUSCA_SUBTRECHOS):
        scores, idx = self.faiss.search(vetores, min(k_sub, self.faiss.ntotal))
        saida = []
        for s_lin, i_lin in zip(scores, idx):
            melhor = {}
            for s, i in zip(s_lin, i_lin):
                if i < 0:
                    continue
                tid = self.subtrechos[i]["id_trecho"]
                if tid not in melhor or s > melhor[tid]:
                    melhor[tid] = float(s)
            ordem = sorted(melhor.items(), key=lambda x: -x[1])[:k]
            saida.append([{"id": t, "score": round(s, 6), "posicao": n + 1} for n, (t, s) in enumerate(ordem)])
        return saida

    def buscar(self, consulta: str, k: int = config.K) -> list[dict]:
        return self.buscar_vetores(embed(self.embedder, [consulta], config.PREFIXO_CONSULTA), k)[0]

    def buscar_lote(self, consultas: list[str], k: int = config.K) -> list[list[dict]]:
        return self.buscar_vetores(embed(self.embedder, consultas, config.PREFIXO_CONSULTA), k)

    def como_retriever_langchain(self, base_por_id: dict, k: int = config.K):
        """Mesmo recuperador exposto como Runnable do LangChain (LCEL): consulta -> lista de Documents."""
        from langchain_core.documents import Document
        from langchain_core.runnables import RunnableLambda

        def _rec(consulta: str):
            return [Document(page_content=base_por_id[r["id"]]["texto"],
                             metadata={"id": r["id"], "score": r["score"], "posicao": r["posicao"],
                                       "localizacao": base_por_id[r["id"]]["localizacao"],
                                       "fonte": base_por_id[r["id"]]["fonte"]})
                    for r in self.buscar(consulta, k)]
        return RunnableLambda(_rec)


def _meta_esperado(base: list[dict]) -> dict:
    return {"versao": config.VERSAO_INDICE, "modelo": config.MODELO_EMBEDDING, "revisao": config.REVISAO_EMBEDDING,
            "max_tokens": config.MAX_TOKENS_E5, "prefixo_passagem": config.PREFIXO_PASSAGEM,
            "sha256_corpus_texto": sha256(config.PASTA_CORPUS_PLN / config.ARQ_TEXTO), "trechos": len(base)}


def construir_ou_carregar(base: list[dict], embedder=None, pasta: Path | None = None, forcar: bool = False,
                          log=print) -> tuple[Indice, dict]:
    import faiss

    pasta = Path(pasta or config.PASTA_INDICE)
    arq_idx, arq_meta, arq_sub = pasta / "indice_e5.faiss", pasta / "indice_meta.json", pasta / "subtrechos.jsonl"
    embedder = embedder or carregar_embedder()
    esperado = _meta_esperado(base)
    if not forcar and arq_idx.exists() and arq_meta.exists() and arq_sub.exists():
        meta = json.loads(arq_meta.read_text(encoding="utf-8"))
        if all(meta.get(k) == v for k, v in esperado.items()):
            idx = faiss.read_index(str(arq_idx))
            sub = ler_jsonl(arq_sub)
            if idx.ntotal == len(sub):
                log(f"[N3] índice reaproveitado de {pasta} ({idx.ntotal} vetores)")
                return Indice(idx, sub, meta, embedder), {"reaproveitado": True, **meta}
        log("[N3] índice salvo não confere com o corpus/modelo atuais: reconstruindo")
    sub, estat = dividir_para_embedding(base, embedder.tokenizer)
    vet = embed(embedder, [s["texto"] for s in sub], config.PREFIXO_PASSAGEM)
    idx = faiss.IndexFlatIP(vet.shape[1])
    idx.add(vet)
    pasta.mkdir(parents=True, exist_ok=True)
    faiss.write_index(idx, str(arq_idx))
    gravar_jsonl(arq_sub, sub)
    meta = {**esperado, "dimensao": int(vet.shape[1]), "vetores": int(idx.ntotal), "c3b": estat,
            "normas_min_max": [float(np.linalg.norm(vet, axis=1).min()), float(np.linalg.norm(vet, axis=1).max())]}
    arq_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[N3] índice construído: {idx.ntotal} vetores (dim {vet.shape[1]}); C3b dividiu {estat['divididos']} trechos")
    return Indice(idx, sub, meta, embedder), {"reaproveitado": False, **meta}


# ---------------------------------------------------------------- métricas de recuperação (§2.7.2)
def posicao_ouro(recuperados: list[dict], ouro: list[str]) -> int | None:
    for r in recuperados:
        if r["id"] in ouro:
            return r["posicao"]
    return None


def metricas_recuperacao(linhas: list[dict], k: int = config.K) -> dict:
    """linhas: {"ouro": [ids], "recuperados": [{"id","posicao"}...]} -> hit@1, hit@k, MRR@k."""
    n = len(linhas)
    if not n:
        return {"n": 0}
    pos = [posicao_ouro(l["recuperados"][:k], l["ouro"]) for l in linhas]
    return {"n": n, "hit@1": round(sum(p == 1 for p in pos) / n, 4),
            f"hit@{k}": round(sum(p is not None for p in pos) / n, 4),
            f"MRR@{k}": round(sum(1 / p for p in pos if p) / n, 4)}
