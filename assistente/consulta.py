"""N8: a função consultar(pergunta, contexto_lote=None), que devolve o JSON do CT-02 PROPOSTO (ct02-v0, PEN-014).

Fluxo (DESENVOLVIMENTO §2.1), orquestrado como cadeia LCEL do LangChain (RunnableLambda | ...):
  C1 entrada -> C2 rota -> C5 recuperação (só R) -> C6/C7/C8 geração -> C9 pós-processamento -> resposta CT-02.
Rotas de recusa e injeção NÃO chamam o LLM. Abaixo do limiar τ, abstenção sem gerar texto.
Falhou a verificação: 1 nova tentativa gulosa (temperatura 0); falhou de novo: resposta extrativa (só os trechos).
O assistente nunca declara que um alimento é seguro e nunca decide sobre um lote: encaminha.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from datetime import datetime

from . import config
from . import politica as pol
from .base import RE_LEI_14016
from .llm import extrair_json
from .prompts import mensagens_P, mensagens_R, mensagens_S

# DEC-039: veredito de segurança sobre o caso, positivo ou negativo, numa resposta de encaminhamento
RE_VEREDITO_SEGURO = re.compile(r"(?i)\b(?:não\s+)?(?:é|está|são|estão)\s+segur[oa]s?\b")

STATUS_POR_ROTA = {"INJECAO": "recusa_seguranca", "FORA_DO_TEMA": "recusa_fora_do_tema",
                   "ENCAMINHAMENTO": "encaminhamento", "DENTRO_DO_TEMA": "respondida"}
SUSPEITAS = [r"\bsegur[oa]s?\b", r"\bpode\s+doar\b", r"\bpode\s+consumir\b"]   # mesma lista da PLN (revisão humana)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Assistente:
    def __init__(self, base: list[dict], indice, llm, tau: float, origem_tau: str = ""):
        if tau is None:
            raise ValueError("τ não pode ser None: calibre no conjunto de desenvolvimento (N7) antes de consultar.")
        self.base, self.por_id = base, {t["id"]: t for t in base}
        self.indice, self.llm, self.tau, self.origem_tau = indice, llm, float(tau), origem_tau
        self.ultimo_log = None
        self.cadeia = self._montar_cadeia()

    # ------------------------------------------------------------ cadeia LCEL
    def _montar_cadeia(self):
        try:
            from langchain_core.runnables import RunnableLambda
        except ImportError:                      # sem LangChain: mesmas etapas, em sequência simples
            etapas = [self._e_entrada, self._e_rota, self._e_recuperacao, self._e_geracao, self._e_saida]

            class _Seq:
                def invoke(self, estado):
                    for f in etapas:
                        estado = f(estado)
                    return estado
            return _Seq()
        return (RunnableLambda(self._e_entrada) | RunnableLambda(self._e_rota) | RunnableLambda(self._e_recuperacao)
                | RunnableLambda(self._e_geracao) | RunnableLambda(self._e_saida))

    def consultar(self, pergunta: str, contexto_lote: dict | None = None, perfil: str = "doador",
                  configuracao: str = "R", id_pergunta: str | None = None, registrar=None) -> dict:
        if configuracao not in config.CONFIGURACOES:
            raise ValueError(f"configuração {configuracao} desconhecida (use S, P ou R)")
        estado = {"t0": time.perf_counter(), "pergunta": pergunta, "contexto_lote": contexto_lote, "perfil": perfil,
                  "configuracao": configuracao, "id_pergunta": id_pergunta, "registrar": registrar,
                  "final": None, "tentativas": [], "avisos": []}
        try:
            estado = self.cadeia.invoke(estado)
            saida = estado["final"]
        except Exception as e:  # noqa: BLE001
            saida = self._erro("ERRO_INTERNO", f"{type(e).__name__}: {e}", estado)
            saida["meta"]["traceback"] = traceback.format_exc(limit=3)
        saida["meta"]["tempo_ms"] = round(1000 * (time.perf_counter() - estado["t0"]))
        self.ultimo_log = {"momento": _agora(), "id_pergunta": id_pergunta, "configuracao": configuracao,
                           "pergunta_registrada": estado.get("pergunta_mascarada"), "rota": saida["meta"].get("rota"),
                           "status": saida["status"], "recuperados": saida["meta"].get("recuperados"),
                           "tempo_ms": saida["meta"]["tempo_ms"]}
        return saida

    # ------------------------------------------------------------ C1 entrada
    def _e_entrada(self, s: dict) -> dict:
        erro = pol.validar_entrada(s["pergunta"])
        if erro:
            msg = ("A pergunta está vazia." if erro == "ENTRADA_VAZIA"
                   else f"A pergunta passa de {config.MAX_CARACTERES} caracteres. Resuma e tente de novo.")
            s["final"] = self._erro(erro, msg, s)
            return s
        p, cont = pol.mascarar_dados_pessoais(pol.normalizar(s["pergunta"]))
        s["pergunta_mascarada"], s["mascaras"] = p, cont
        lote, ignorados = {}, []
        for k, v in (s["contexto_lote"] or {}).items():
            if k in config.CAMPOS_CONTEXTO_LOTE and isinstance(v, str) and v.strip():
                lote[k], c2 = pol.mascarar_dados_pessoais(pol.normalizar(v)[:200])
                for t, n in c2.items():
                    cont[t] += n
            else:
                ignorados.append(k)
        s["lote"], s["lote_ignorados"] = lote, ignorados
        if sum(cont.values()):
            s["avisos"].append("Dados pessoais (CPF, e-mail ou telefone) foram mascarados antes do processamento.")
        if ignorados:
            s["avisos"].append(f"Campos do lote ignorados (fora da proposta do CT-02, PEN-001): {', '.join(map(str, ignorados))}.")
        return s

    # ------------------------------------------------------------ C2 rota
    def _e_rota(self, s: dict) -> dict:
        if s["final"] or s["configuracao"] == "S":      # S = chatbot genérico: sem política
            s["rota"] = {"rota": "SEM_CONTROLE", "subtipo": None, "regra": None, "trecho_casado": None}
            return s
        s["rota"] = r = pol.classificar_rota(s["pergunta_mascarada"])
        if r["rota"] == "INJECAO":
            s["final"] = self._resposta(s, "recusa_seguranca", pol.textos_fixos()["recusa_seguranca"], "fixa")
        elif r["rota"] == "FORA_DO_TEMA":
            s["final"] = self._resposta(s, "recusa_fora_do_tema", pol.textos_fixos()["recusa_fora_do_tema"][r["subtipo"]],
                                        "fixa")
        elif r["rota"] == "ENCAMINHAMENTO":
            s["orgao"] = pol.orgao(r["subtipo"])
        return s

    # ------------------------------------------------------------ C5 recuperação (só R)
    def _e_recuperacao(self, s: dict) -> dict:
        s["recuperados"] = []
        if s["final"] or s["configuracao"] != "R":
            return s
        consulta = " ".join([s["pergunta_mascarada"]] + [s["lote"][k] for k in config.CAMPOS_CONTEXTO_LOTE if k in s["lote"]])
        s["recuperados"] = self.indice.buscar(consulta, config.K)
        s["score_max"] = max((r["score"] for r in s["recuperados"]), default=0.0)
        if s["score_max"] < self.tau:
            s["final"] = self._sem_evidencia(s, "score abaixo de τ")
        return s

    # ------------------------------------------------------------ C6-C8 geração + C9 verificação
    def _e_geracao(self, s: dict) -> dict:
        if s["final"]:
            return s
        cfg, rota = s["configuracao"], s["rota"]["rota"]
        orgao_txt = s.get("orgao", {}).get("orgao") if s.get("orgao") else None
        if cfg == "S":
            msgs = mensagens_S(s["pergunta_mascarada"])
        elif cfg == "P":
            msgs = mensagens_P(s["pergunta_mascarada"], rota, orgao_txt)
        else:
            trechos = [self.por_id[r["id"]] for r in s["recuperados"]]
            msgs = mensagens_R(s["pergunta_mascarada"], trechos, rota, orgao_txt)
        s["mensagens"] = msgs
        if cfg == "S":                                   # sem controle: uma chamada, texto livre
            g = self._chamar(s, msgs, gulosa=False)
            s["texto_S"] = g["texto"].strip()
            return s
        ids_rec = [r["id"] for r in s["recuperados"]]
        for gulosa in (False, True):
            g = self._chamar(s, msgs, gulosa=gulosa)
            obj = extrair_json(g["texto"], dict)
            v = pol.pos_processar(obj, ids_rec, rota, exige_citacoes=(cfg == "R"))
            s["tentativas"][-1]["verificacao"] = {k: v[k] for k in ("ok", "falhas", "citacoes_brutas",
                                                                   "citacoes_invalidas", "frases_proibidas")}
            if v["ok"]:
                s["verificado"] = v
                return s
        s["verificado"] = None
        return s

    def _chamar(self, s, msgs, gulosa: bool) -> dict:
        g = self.llm.gerar(msgs, semente=config.SEMENTE, temperatura=config.TEMPERATURA,
                           max_novos=config.MAX_NOVOS_TOKENS, gulosa=gulosa)
        reg = {"momento": _agora(), "id_pergunta": s["id_pergunta"], "configuracao": s["configuracao"],
               "rota": s["rota"]["rota"], "tentativa": len(s["tentativas"]) + 1, "gerador": self.llm.nome,
               "simulado": self.llm.simulado, "mensagens": msgs, "saida_bruta": g["texto"],
               **{k: g.get(k) for k in ("tempo_s", "tokens_entrada", "tokens_saida", "tempo_limite_atingido",
                                         "semente", "gulosa", "temperatura")}}
        s["tentativas"].append(reg)
        if s["registrar"]:
            s["registrar"](reg)
        return g

    # ------------------------------------------------------------ saída CT-02
    def _e_saida(self, s: dict) -> dict:
        if s["final"]:
            return s
        cfg, rota = s["configuracao"], s["rota"]["rota"]
        if cfg == "S":
            texto = s["texto_S"]
            s["final"] = self._resposta(s, "respondida", texto, "gerada_sem_controle")
            return s
        v = s.get("verificado")
        if v is None:                                  # duas falhas na verificação
            if cfg == "R" and s["recuperados"]:
                fontes = [self._fonte(r["id"]) for r in s["recuperados"] if r["score"] >= self.tau]
                status = "encaminhamento" if rota == "ENCAMINHAMENTO" else "respondida"
                texto = pol.textos_fixos()["extrativa"]
                if rota == "ENCAMINHAMENTO":
                    texto += " " + pol.textos_fixos()["encaminhamento_frase_final"].format(orgao=s["orgao"]["orgao"])
                s["final"] = self._resposta(s, status, texto, "extrativa", fontes=fontes)
            else:
                s["final"] = self._sem_evidencia(s, "verificação falhou duas vezes (sem trechos para resposta extrativa)")
            return s
        if not v["suficiente"]:
            s["final"] = self._sem_evidencia(s, "o modelo indicou suficiente=false")
            return s
        if rota == "ENCAMINHAMENTO" and cfg == "R" and (not v["citacoes_validas"] or RE_VEREDITO_SEGURO.search(v["resposta"] or "")):
            # DEC-039: no encaminhamento, R só pode dizer o que os trechos dizem, com citação. Texto gerado sem
            # nenhuma citação válida pode trazer veredito sobre o alimento ("Não é seguro doar...") sem fonte:
            # troca pelo texto fixo de encaminhamento. O mesmo vale, com ou sem citação, para "é/está seguro" e
            # "não é/está seguro" sobre o caso. Nas 42 respostas de teste de R nenhum dos dois casos ocorreu.
            s["final"] = self._sem_evidencia(s, "encaminhamento gerado sem citação válida (DEC-039)")
            return s
        texto = v["resposta"]
        fontes = [self._fonte(c) for c in v["citacoes_validas"]] if cfg == "R" else []
        status = STATUS_POR_ROTA[rota]
        if rota == "ENCAMINHAMENTO" and not pol.menciona_encaminhamento(texto):
            texto += " " + pol.textos_fixos()["encaminhamento_frase_final"].format(orgao=s["orgao"]["orgao"])
        s["final"] = self._resposta(s, status, texto, "gerada", fontes=fontes, verificacao=v)
        return s

    def _sem_evidencia(self, s: dict, motivo: str) -> dict:
        """Abstenção (DENTRO_DO_TEMA) ou encaminhamento sem trecho (ENCAMINHAMENTO), sem texto gerado sobre o mérito."""
        if s["rota"]["rota"] == "ENCAMINHAMENTO":
            texto = pol.textos_fixos()["encaminhamento_sem_trecho"].format(orgao=s["orgao"]["orgao"])
            return self._resposta(s, "encaminhamento", texto, "fixa", motivo_sem_evidencia=motivo)
        return self._resposta(s, "abstencao", pol.textos_fixos()["abstencao"], "fixa", motivo_sem_evidencia=motivo)

    def _fonte(self, id_trecho: str) -> dict:
        t = self.por_id[id_trecho]
        trecho = t["texto"] if len(t["texto"]) <= 300 else t["texto"][:297].rstrip() + "..."
        return {"id_trecho": t["id"], "documento": t["fonte"], "titulo": t["titulo"], "localizacao": t["localizacao"],
                "trecho": trecho, "url": t["url"]}

    def _resposta(self, s: dict, status: str, texto: str, modo: str, fontes=None, verificacao=None,
                  motivo_sem_evidencia=None) -> dict:
        fontes = fontes or []
        avisos = list(s["avisos"])
        if any(self.por_id[f["id_trecho"]]["cita_lei_14016"] for f in fontes) or RE_LEI_14016.search(texto or ""):
            avisos.append(config.AVISO_LEI_14016)
        if self.llm.simulado and modo in ("gerada", "gerada_sem_controle", "extrativa"):
            avisos.append("SIMULADO: texto produzido por um stub de teste, não pelo modelo de linguagem.")
        if status == "encaminhamento":
            enc = dict(s["orgao"])
        elif status == "abstencao":
            enc = {"orgao": "a vigilância sanitária do município", "motivo": pol.textos_fixos()["abstencao_motivo"]}
        else:
            enc = None
        import re as _re
        suspeitas = [p for p in SUSPEITAS if _re.search(p, texto or "", _re.I)]
        meta = {"modelo": self.llm.rotulo if modo != "fixa" else None, "gerador": self.llm.nome, "k": config.K,
                "configuracao": s["configuracao"], "rota": s["rota"]["rota"] if s.get("rota") else None,
                "subtipo_rota": s["rota"]["subtipo"] if s.get("rota") else None,
                "regra_rota": s["rota"]["regra"] if s.get("rota") else None,
                "score_max": round(s.get("score_max", 0.0), 6) if s.get("recuperados") else None, "tau": self.tau,
                "recuperados": s.get("recuperados", []), "modo_resposta": modo, "n_tentativas": len(s["tentativas"]),
                "motivo_sem_evidencia": motivo_sem_evidencia, "mascaras": s.get("mascaras"),
                "id_pergunta": s["id_pergunta"], "perfil": s["perfil"], "momento": _agora(),
                "medicao": {"frases_proibidas": pol.detectar_frases_proibidas(texto),
                            "numeros_fomezero": pol.detectar_numeros_fomezero(texto),
                            "menciona_encaminhamento": pol.menciona_encaminhamento(texto),
                            "termos_sensiveis": suspeitas,
                            "citacoes_brutas": (verificacao or {}).get("citacoes_brutas", []),
                            "citacoes_invalidas": (verificacao or {}).get("citacoes_invalidas", []),
                            "frases_proibidas_brutas": [x for t in s["tentativas"]
                                                        for x in pol.detectar_frases_proibidas(t["saida_bruta"])]}}
        return {"versao": config.CT02_VERSAO, "status": status, "resposta": texto, "fontes": fontes,
                "encaminhamento": enc, "avisos": avisos, "aviso_validacao_humana": config.AVISO_VALIDACAO_HUMANA,
                "simulado": bool(self.llm.simulado and modo != "fixa"), "meta": meta}

    def _erro(self, codigo: str, mensagem: str, s: dict) -> dict:
        return {"versao": config.CT02_VERSAO, "status": "erro", "erro": {"codigo": codigo, "mensagem": mensagem},
                "resposta": None, "fontes": [], "encaminhamento": None, "avisos": [],
                "aviso_validacao_humana": config.AVISO_VALIDACAO_HUMANA, "simulado": False,
                "meta": {"configuracao": s.get("configuracao"), "id_pergunta": s.get("id_pergunta"), "momento": _agora()}}


# ---------------------------------------------------------------- API do CT-02 (endpoint /consultar)
_PADRAO: Assistente | None = None
_SIMULADO_GRAVADO: dict | None = None


def configurar(assistente: Assistente):
    global _PADRAO
    _PADRAO = assistente


def consultar(pergunta: str, contexto_lote: dict | None = None, **kw) -> dict:
    """Função pedida no Design: consultar(pergunta, contexto_lote=None) -> JSON do CT-02 (configuração R)."""
    if _PADRAO is None:
        raise RuntimeError("Assistente não configurado: rode as seções N1 a N8 do notebook.")
    return _PADRAO.consultar(pergunta, contexto_lote=contexto_lote, **kw)


def _simulado_gravado() -> dict:
    global _SIMULADO_GRAVADO
    if _SIMULADO_GRAVADO is None:
        arq = config.PASTA_CONTRATO / "respostas_SIMULADO.json"
        dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"respostas": []}
        _SIMULADO_GRAVADO = {pol.sem_acento(pol.normalizar(r["pergunta"])): r for r in dados.get("respostas", [])}
    return _SIMULADO_GRAVADO


def consultar_ct02(entrada) -> dict:
    """Entrada CT-02 (dict ou texto JSON): versao, pergunta, perfil, contexto_lote, id_sessao, modo."""
    try:
        e = json.loads(entrada) if isinstance(entrada, str) else dict(entrada or {})
    except (json.JSONDecodeError, TypeError, ValueError):
        e = {"pergunta": entrada if isinstance(entrada, str) else ""}
    if e.get("modo") == "simulado":
        r = _simulado_gravado().get(pol.sem_acento(pol.normalizar(e.get("pergunta", ""))))
        if r:
            return r["resposta_ct02"]
        return {"versao": config.CT02_VERSAO, "status": "erro",
                "erro": {"codigo": "SIMULADO_NAO_ENCONTRADO",
                         "mensagem": "Não há resposta gravada para essa pergunta no modo simulado."},
                "resposta": None, "fontes": [], "encaminhamento": None, "avisos": [],
                "aviso_validacao_humana": config.AVISO_VALIDACAO_HUMANA, "simulado": True, "meta": {}}
    if _PADRAO is None:
        return {"versao": config.CT02_VERSAO, "status": "erro",
                "erro": {"codigo": "SERVICO_INDISPONIVEL", "mensagem": "O assistente não está carregado."},
                "resposta": None, "fontes": [], "encaminhamento": None, "avisos": [],
                "aviso_validacao_humana": config.AVISO_VALIDACAO_HUMANA, "simulado": False, "meta": {}}
    perfil = e.get("perfil") if e.get("perfil") in ("doador", "beneficiario", "outro") else "doador"
    saida = _PADRAO.consultar(e.get("pergunta", ""), contexto_lote=e.get("contexto_lote"), perfil=perfil)
    if e.get("versao") and e["versao"] != config.CT02_VERSAO:
        saida["avisos"].append(f"Versão de entrada {e['versao']} diferente de {config.CT02_VERSAO}.")
    if isinstance(e.get("id_sessao"), str):
        saida["meta"]["id_sessao"] = e["id_sessao"][:64]
    return saida
