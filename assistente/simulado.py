"""N11: exporta o modo simulado do CT-02 (contrato/respostas_SIMULADO.json).

As respostas são GRAVADAS PELO PIPELINE REAL (Qwen no Colab), nunca escritas à mão. Cada uma leva
"simulado": true e a data da gravação; a FEMD exibe a faixa "Resposta SIMULADA, gravada em AAAA-MM-DD".
Com o stub (sem GPU) a exportação para contrato/ é recusada: o stub não é o pipeline real.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config
from .interface import perguntas_sugeridas


def exportar_simulado(assistente, perguntas: list[str] | None = None, destino: Path | None = None, log=print) -> dict:
    destino = Path(destino or config.PASTA_CONTRATO / "respostas_SIMULADO.json")
    if assistente.llm.simulado and destino.resolve() == (config.PASTA_CONTRATO / "respostas_SIMULADO.json").resolve():
        raise RuntimeError("LLM = stub SIMULADO: o modo simulado do CT-02 precisa ser gravado pelo pipeline real "
                           "(Qwen no Colab com GPU). Nada foi gravado em contrato/.")
    data = datetime.now().strftime("%Y-%m-%d")
    saida = []
    for p in perguntas or perguntas_sugeridas():
        r = assistente.consultar(p)
        r["simulado"] = True
        r["meta"]["gravado_em"] = data
        r["meta"]["rotulo_simulado"] = (f"Resposta SIMULADA, gravada em {data} pelo pipeline real "
                                        f"({assistente.llm.rotulo}); não é IA ao vivo.")
        saida.append({"pergunta": p, "resposta_ct02": r})
        log(f"[N11] {r['status']:<20} {p}")
    doc = {"versao": config.CT02_VERSAO, "descricao": "Modo simulado do CT-02 (opção T3): respostas gravadas pelo "
           "pipeline real do assistente, para a FEMD usar quando o Colab não estiver no ar. Revisão humana antes de "
           "ir para a FEMD (DESENVOLVIMENTO §2.8, item 7).", "gravado_em": data, "gerador": assistente.llm.rotulo,
           "stub": bool(assistente.llm.simulado), "tau": assistente.tau, "respostas": saida}
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[N11] {len(saida)} respostas gravadas em {destino}")
    return doc
