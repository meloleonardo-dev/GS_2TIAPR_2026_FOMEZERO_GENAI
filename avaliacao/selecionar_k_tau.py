"""Escolha de k e calibração de τ SÓ com o conjunto de DESENVOLVIMENTO (TAR-008, DEC-028), e medição única no teste.

Regra fixada ANTES de medir (TAR-008, 2026-11-10):
- k candidatos: 4, 6 e 8. Medida no desenvolvimento: hit@k e MRR@k das perguntas T1/T2 de desenvolvimento.
- Escolhe-se o MENOR k cujo hit@k fica a no máximo 1 pergunta do melhor hit@k entre os candidatos
  (menos trechos = contexto menor para o modelo de 7B e resposta mais rápida).
- τ: calibrar_tau (§2.7.3) com T1/T2 de desenvolvimento (devem responder) contra T4/T5 de desenvolvimento (não devem),
  peso 2 para responder sem evidência. τ usa o score máximo (1º trecho), então não depende de k.
- O conjunto de TESTE (T1 a T6 de teste e T8) não entra em nenhuma escolha.
Uso:
  <python da venv> -I avaliacao/selecionar_k_tau.py desenvolvimento   -> grava evidencias/selecao_k_tau_<data>.json/.md
  (copiar k e τ para assistente/config.py)
  <python da venv> -I avaliacao/selecionar_k_tau.py teste             -> mede UMA vez no teste com o k e o τ do config
"""
from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

PASTA_GENAI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA_GENAI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HOME", str(PASTA_GENAI / ".cache_hf"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from assistente import avaliacao as av  # noqa: E402
from assistente import base as kb  # noqa: E402
from assistente import config  # noqa: E402
from assistente import indice as ix  # noqa: E402

KS = (4, 6, 8)
HOJE = datetime.now().strftime("%Y-%m-%d")


def ambiente() -> dict:
    import faiss
    import torch
    return {"momento": datetime.now().isoformat(timespec="seconds"), "maquina": platform.platform(),
            "processador": platform.processor(), "python": sys.version.split()[0], "torch": torch.__version__,
            "faiss": faiss.__version__, "modelo_embedding": config.MODELO_EMBEDDING,
            "revisao_embedding": config.REVISAO_EMBEDDING, "dispositivo": "cpu"}


def _tabela_k(idx, qs):
    recs = idx.buscar_lote([q["pergunta"] for q in qs], k=max(KS))
    linhas = [{"ouro": av.ouro(q), "recuperados": r} for q, r in zip(qs, recs)]
    return {k: ix.metricas_recuperacao(linhas, k) for k in KS}


def desenvolvimento():
    base = kb.construir_base()
    idx, _ = ix.construir_ou_carregar(base)
    perguntas = av.carregar_perguntas()
    dev_pos = [q for q in perguntas if q["split"] == "desenvolvimento" and q["categoria"] in ("T1", "T2") and av.ouro(q)]
    tab = _tabela_k(idx, dev_pos)
    n = len(dev_pos)
    melhor = max(tab[k][f"hit@{k}"] for k in KS)
    k_escolhido = min(k for k in KS if tab[k][f"hit@{k}"] >= melhor - 1 / n - 1e-9)
    amb = ambiente()
    cal = av.calibrar_tau_desenvolvimento(idx, perguntas, ambiente=amb)   # grava avaliacao/calibracao_tau.json
    res = {"regra_k": "menor k cujo hit@k fica a no máximo 1 pergunta do melhor (candidatos 4, 6, 8)",
           "n_positivas_com_ouro": n, "tabela_k": {str(k): v for k, v in tab.items()}, "k_escolhido": k_escolhido,
           "tau": {x: cal[x] for x in ("tau", "custo", "falso_respondida", "abstencao_indevida", "n_positivos",
                                         "n_negativos", "peso_falso_respondida")},
           "curva_tau": cal["tabela"], "scores_desenvolvimento": cal["scores"], "ambiente": amb,
           "aviso": "Resultado REAL da execução local em CPU, só com o conjunto de desenvolvimento."}
    (config.PASTA_EVIDENCIAS / f"selecao_k_tau_{HOJE}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                                        encoding="utf-8")
    md = [f"# Escolha de k e de τ (só desenvolvimento), {HOJE}", "",
          "Resultado REAL em CPU: " + f"{amb['maquina']}, Python {amb['python']}, torch {amb['torch']}, faiss {amb['faiss']}, "
          f"e5-small commit {config.REVISAO_EMBEDDING[:8]}.", "",
          f"## k ({n} perguntas T1/T2 de desenvolvimento com trecho esperado)", "",
          "Regra fixada antes de medir: o menor k cujo hit@k fica a no máximo 1 pergunta do melhor.", "",
          "| k | hit@1 | hit@k | MRR@k |", "|---|---|---|---|"]
    for k in KS:
        md.append(f"| {k} | {tab[k]['hit@1']} | {tab[k][f'hit@{k}']} | {tab[k][f'MRR@{k}']} |")
    md += ["", f"**k escolhido: {k_escolhido}.**", "",
           f"## τ ({cal['n_positivos']} que devem responder, {cal['n_negativos']} que não devem; peso 2)", "",
           f"**τ = {cal['tau']:.6f}**: {cal['falso_respondida']} respostas sem evidência e "
           f"{cal['abstencao_indevida']} abstenções indevidas no desenvolvimento (custo {cal['custo']}).", "",
           "Curva (cada linha é um valor candidato de τ):", "", "| τ | responde sem evidência | abstenção indevida | custo |",
           "|---|---|---|---|"]
    for r in cal["tabela"]:
        md.append(f"| {r['tau']:.4f} | {r['falso_respondida']} | {r['abstencao_indevida']} | {r['custo']} |")
    md += ["", "Scores do desenvolvimento (+ deve responder, - não deve):", "", "```", av.histograma_texto(cal), "```", ""]
    (config.PASTA_EVIDENCIAS / f"selecao_k_tau_{HOJE}.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"tabela_k": res["tabela_k"], "k_escolhido": k_escolhido, "tau": res["tau"]}, ensure_ascii=False, indent=1))


def teste():
    destino = config.PASTA_EVIDENCIAS / f"resultado_teste_k{config.K}_{HOJE}.json"
    if destino.exists():
        raise SystemExit(f"{destino.name} já existe: a medição no teste é feita UMA vez.")
    if config.TAU is None:
        raise SystemExit("Copie o τ escolhido para assistente/config.py antes de medir no teste.")
    base = kb.construir_base()
    idx, _ = ix.construir_ou_carregar(base)
    perguntas = av.carregar_perguntas()
    teste_q = [q for q in perguntas if q["split"] == "teste"]
    res = {"k": config.K, "tau": config.TAU, "ambiente": ambiente(),
           "aviso": "Medição única no TESTE com o k e o τ escolhidos no desenvolvimento. Resultado REAL em CPU; "
                    "só a busca (sem LLM)."}
    for nome, cats in (("T1", ("T1",)), ("T2", ("T2",)), ("T1+T2", ("T1", "T2")), ("T8", ("T8",))):
        qs = [q for q in teste_q if q["categoria"] in cats and av.ouro(q)]
        recs = idx.buscar_lote([q["pergunta"] for q in qs], k=config.K)
        res[f"busca_{nome}"] = ix.metricas_recuperacao([{"ouro": av.ouro(q), "recuperados": r} for q, r in zip(qs, recs)],
                                                        config.K)
    qs = [q for q in teste_q if q["categoria"] in ("T1", "T2", "T4", "T5")]
    sc = idx.buscar_lote([q["pergunta"] for q in qs], k=1)
    pos = [s[0]["score"] for q, s in zip(qs, sc) if q["categoria"] in ("T1", "T2")]
    neg = [s[0]["score"] for q, s in zip(qs, sc) if q["categoria"] in ("T4", "T5")]
    res["efeito_tau"] = {"T1T2_acima_de_tau": f"{sum(x >= config.TAU for x in pos)}/{len(pos)}",
                         "T4T5_abaixo_de_tau": f"{sum(x < config.TAU for x in neg)}/{len(neg)}"}
    destino.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"desenvolvimento": desenvolvimento, "teste": teste}[sys.argv[1]]()
