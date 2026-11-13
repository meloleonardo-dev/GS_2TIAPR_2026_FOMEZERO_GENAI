"""N5: LLM Qwen2.5-7B-Instruct em 4 bits (NF4) no Colab com GPU T4; reserva Qwen2.5-1.5B-Instruct.

Lições da PLN aplicadas:
- DEC-019: no transformers 5 o apply_chat_template devolve BatchEncoding; pedimos return_dict=True e passamos
  input_ids e attention_mask ao generate (funciona no 4.x e no 5.x).
- DEC-021: o extrator de JSON decodifica a partir de cada '{' / '[' com json.raw_decode (respeita o aninhamento,
  ignora lixo depois do JSON) e só repara sintaxe (vírgula sobrando, fechamentos faltando no fim).
- Temperatura e semente fixas (config). Nova tentativa com geração gulosa (temperatura 0).
O LLMStub NÃO é um modelo: devolve texto fixo rotulado SIMULADO, só para testar o pipeline sem GPU.
"""
from __future__ import annotations

import json
import re
import time

from . import config


# ---------------------------------------------------------------- JSON devolvido pelo modelo (DEC-021)
_FECHAMENTOS = ("", "}", "]}", "}]", "}}", "]]", '"}', '"]}', '"}}')


def extrair_json(texto: str, tipo: type | None = None):
    """Primeiro JSON válido do texto (objeto ou lista; `tipo` restringe). Tolera cercas ```json, texto antes
    (inclusive com colchetes como "[T-012]"), lixo depois, vírgula sobrando e até 2 fechamentos faltando."""
    if not isinstance(texto, str):
        return None
    t = re.sub(r"```(?:json)?", "", texto).strip()
    dec = json.JSONDecoder()
    for k, ch in enumerate(t):
        if ch not in "[{":
            continue
        if (tipo is dict and ch != "{") or (tipo is list and ch != "["):
            continue
        resto = t[k:]
        for base in (resto, re.sub(r",\s*([}\]])", r"\1", resto)):
            for fim in _FECHAMENTOS:
                try:
                    valor = dec.raw_decode(base + fim)[0]
                except json.JSONDecodeError:
                    continue
                if tipo is None or isinstance(valor, tipo):
                    return valor
                break
    return None


# ---------------------------------------------------------------- modelo real (Colab, GPU)
class SemGPU(RuntimeError):
    pass


class LLMQwen:
    simulado = False

    def __init__(self, modelo, tok, nome: str, revisao: str | None, motivo_reserva: str | None = None):
        self.modelo, self.tok, self.nome, self.revisao = modelo, tok, nome, revisao
        self.motivo_reserva = motivo_reserva
        self.rotulo = f"{nome} (4 bits NF4)"

    def gerar(self, mensagens: list[dict], semente: int = config.SEMENTE, temperatura: float = config.TEMPERATURA,
              max_novos: int = config.MAX_NOVOS_TOKENS, gulosa: bool = False) -> dict:
        import torch
        from transformers import set_seed

        set_seed(semente)
        enc = self.tok.apply_chat_template(mensagens, add_generation_prompt=True, return_tensors="pt",
                                           return_dict=True)
        ids = enc["input_ids"].to(self.modelo.device)
        mascara = enc["attention_mask"].to(self.modelo.device) if "attention_mask" in enc else None
        args = dict(input_ids=ids, attention_mask=mascara, max_new_tokens=max_novos, pad_token_id=self.tok.eos_token_id,
                    max_time=config.TEMPO_LIMITE_S)
        if gulosa:   # temperatura 0 = geração gulosa (o transformers só avisa que top_p/top_k não são usados)
            args.update(do_sample=False)
        else:
            args.update(do_sample=True, temperature=temperatura)
        t0 = time.perf_counter()
        with torch.no_grad():
            saida = self.modelo.generate(**args)
        dt = time.perf_counter() - t0
        novos = saida[0][ids.shape[1]:]
        return {"texto": self.tok.decode(novos, skip_special_tokens=True), "tempo_s": round(dt, 3),
                "tokens_entrada": int(ids.shape[1]), "tokens_saida": int(novos.shape[0]),
                "tempo_limite_atingido": dt >= config.TEMPO_LIMITE_S - 0.5, "semente": semente,
                "gulosa": gulosa, "temperatura": None if gulosa else temperatura}


def _carregar(nome: str, revisao: str | None):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                           bnb_4bit_compute_dtype=torch.float16)
    tok = AutoTokenizer.from_pretrained(nome, revision=revisao)
    modelo = AutoModelForCausalLM.from_pretrained(nome, revision=revisao, quantization_config=q, device_map="auto")
    modelo.eval()
    return modelo, tok


def carregar_llm(usar_reserva: bool = False, log=print) -> LLMQwen:
    """7B em 4 bits; se faltar memória (ou usar_reserva=True), cai para o 1.5B e registra o motivo."""
    import torch

    if not torch.cuda.is_available():
        raise SemGPU("Sem GPU. No Colab: Ambiente de execução > Alterar o tipo de ambiente > GPU T4.")
    if not usar_reserva:
        try:
            m, t = _carregar(config.MODELO_LLM, config.REVISAO_LLM)
            log(f"[N5] {config.MODELO_LLM} carregado (revisão {config.REVISAO_LLM})")
            return LLMQwen(m, t, config.MODELO_LLM, config.REVISAO_LLM)
        except (torch.cuda.OutOfMemoryError, RuntimeError, ValueError) as e:   # noqa: PERF203
            motivo = f"{type(e).__name__}: {str(e)[:200]}"
            log(f"[N5] falhou ao carregar o 7B ({motivo}); usando a reserva {config.MODELO_RESERVA}")
            torch.cuda.empty_cache()
    else:
        motivo = "usar_reserva=True"
    m, t = _carregar(config.MODELO_RESERVA, config.REVISAO_RESERVA)
    rev = getattr(m.config, "_commit_hash", None)
    return LLMQwen(m, t, config.MODELO_RESERVA, rev, motivo_reserva=motivo)


def info_ambiente(llm=None) -> dict:
    info = {"modelo": getattr(llm, "nome", None), "revisao": getattr(llm, "revisao", None),
            "simulado": getattr(llm, "simulado", None), "motivo_reserva": getattr(llm, "motivo_reserva", None),
            "quantizacao": "4 bits NF4, double quant, compute float16 (bitsandbytes)",
            "temperatura": config.TEMPERATURA, "semente": config.SEMENTE, "max_new_tokens": config.MAX_NOVOS_TOKENS,
            "embedding": config.MODELO_EMBEDDING, "revisao_embedding": config.REVISAO_EMBEDDING}
    try:
        import torch
        import transformers
        info.update({"torch": torch.__version__, "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None})
        if llm is not None and not getattr(llm, "simulado", True):
            gc = llm.modelo.generation_config
            info["generation_config"] = {k: getattr(gc, k, None) for k in ("top_p", "top_k", "repetition_penalty")}
        import bitsandbytes
        info["bitsandbytes"] = bitsandbytes.__version__
    except Exception as e:  # noqa: BLE001
        info["aviso"] = f"{type(e).__name__}: {e}"
    return info


# ---------------------------------------------------------------- stub rotulado SIMULADO (só para testes sem GPU)
class LLMStub:
    """NÃO é um modelo de linguagem. Devolve texto fixo, rotulado SIMULADO, para testar o pipeline sem GPU.
    modo: "ok" | "json_quebrado" | "citacao_invalida" | "frase_proibida" | "insuficiente" | "sem_chave_final"."""
    simulado = True
    nome = "STUB_SIMULADO"
    revisao = None
    motivo_reserva = None
    rotulo = "STUB SIMULADO (não é o Qwen; texto fixo de teste)"

    def __init__(self, modo: str = "ok", modos_por_tentativa: list[str] | None = None):
        self.modo, self.modos_por_tentativa, self.chamadas = modo, modos_por_tentativa, 0

    def gerar(self, mensagens, semente=config.SEMENTE, temperatura=config.TEMPERATURA,
              max_novos=config.MAX_NOVOS_TOKENS, gulosa=False) -> dict:
        modo = (self.modos_por_tentativa[min(self.chamadas, len(self.modos_por_tentativa) - 1)]
                if self.modos_por_tentativa else self.modo)
        self.chamadas += 1
        usuario = mensagens[-1]["content"]
        sistema = mensagens[0]["content"] if mensagens[0]["role"] == "system" else ""
        ids = re.findall(r"\[(T-\d{3})\]", usuario)
        cit = ids[0] if ids else None
        if "Devolva apenas JSON" not in sistema:         # configuração S: texto livre
            texto = "[SIMULADO] Resposta de teste sem modelo de linguagem (configuração S)."
        else:
            resp = "[SIMULADO] Resposta de teste sem modelo de linguagem."
            if cit:
                resp += f" Ver o trecho [{cit}]."
            obj = {"resposta": resp, "citacoes": [cit] if cit else [], "suficiente": True}
            if modo == "citacao_invalida":
                obj["citacoes"], obj["resposta"] = ["T-999"], "[SIMULADO] Texto com citação inexistente [T-999]."
            elif modo == "frase_proibida":
                obj["resposta"] = "[SIMULADO] Este alimento é seguro para consumo." + (f" [{cit}]" if cit else "")
            elif modo == "insuficiente":
                obj["suficiente"], obj["citacoes"] = False, []
                obj["resposta"] = "[SIMULADO] Não encontrei a resposta nos trechos."
            texto = json.dumps(obj, ensure_ascii=False)
            if modo == "json_quebrado":
                texto = "[SIMULADO] sem JSON nenhum aqui"
            elif modo == "sem_chave_final":
                texto = texto[:-1]
        return {"texto": texto, "tempo_s": 0.0, "tokens_entrada": None, "tokens_saida": None,
                "tempo_limite_atingido": False, "semente": semente, "gulosa": gulosa,
                "temperatura": None if gulosa else temperatura}
