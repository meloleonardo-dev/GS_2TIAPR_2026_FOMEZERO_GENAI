"""N6: prompts (versionados em prompts/) e montador de contexto (C7, C8).

Configurações comparadas na avaliação (§2.7.4), mesmo modelo, temperatura e semente:
- S: só um prompt simples ("Responda à pergunta do doador de alimentos."), sem regras, sem recuperação, sem controle;
- P: prompt de sistema com as regras 3 a 6 e controle de saída, sem recuperação;
- R: solução completa: recuperação + prompt de sistema completo + controle de resposta.
A pergunta vai entre <pergunta> e </pergunta>; as marcas são retiradas do texto do usuário para que ele não
"feche" o delimitador (defesa contra injeção, regra 6).
"""
from __future__ import annotations

import hashlib
import re

from . import config


def sha16(nome: str) -> str:
    return hashlib.sha256(config.ler_prompt(nome).encode("utf-8")).hexdigest()[:16]


def limpar_delimitadores(texto: str) -> str:
    return re.sub(r"</?\s*pergunta\s*>", " ", texto, flags=re.I).strip()


def montar_contexto(trechos: list[dict]) -> str:
    """[T-NNN] (documento, localização) + texto, um bloco por trecho, na ordem da recuperação."""
    blocos = []
    for t in trechos:
        nome = config.NOME_CURTO.get(t["doc_id"], t["fonte"])
        blocos.append(f"[{t['id']}] ({nome}, {t['localizacao']})\n{t['texto']}")
    return "\n\n".join(blocos)


def instrucao_rota(rota: str, orgao_texto: str | None) -> str:
    if rota == "ENCAMINHAMENTO":
        return "\n" + config.ler_prompt("instrucao_encaminhamento.txt").replace("<<ORGAO>>", orgao_texto or "") + "\n"
    return ""


def mensagens_R(pergunta: str, trechos: list[dict], rota: str, orgao_texto: str | None = None) -> list[dict]:
    usuario = (config.ler_prompt("usuario_R.txt").replace("<<CONTEXTO>>", montar_contexto(trechos))
               .replace("<<INSTRUCAO_ROTA>>", instrucao_rota(rota, orgao_texto))
               .replace("<<PERGUNTA>>", limpar_delimitadores(pergunta)))
    return [{"role": "system", "content": config.ler_prompt("sistema.txt")}, {"role": "user", "content": usuario}]


def mensagens_P(pergunta: str, rota: str, orgao_texto: str | None = None) -> list[dict]:
    usuario = (config.ler_prompt("usuario_P.txt").replace("<<INSTRUCAO_ROTA>>", instrucao_rota(rota, orgao_texto))
               .replace("<<PERGUNTA>>", limpar_delimitadores(pergunta)))
    return [{"role": "system", "content": config.ler_prompt("regras_P.txt")}, {"role": "user", "content": usuario}]


def mensagens_S(pergunta: str) -> list[dict]:
    return [{"role": "system", "content": config.ler_prompt("baseline_S.txt")},
            {"role": "user", "content": pergunta}]


def versoes_prompts() -> dict:
    nomes = ["sistema.txt", "usuario_R.txt", "instrucao_encaminhamento.txt", "regras_P.txt", "usuario_P.txt",
             "baseline_S.txt", "frases_proibidas.txt", "palavras_chave_rotas.txt", "textos_fixos.json"]
    return {n: sha16(n) for n in nomes}
