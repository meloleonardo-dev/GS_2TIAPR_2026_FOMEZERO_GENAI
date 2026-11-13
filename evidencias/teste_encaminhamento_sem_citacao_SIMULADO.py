import json, sys
sys.path.insert(0, sys.argv[1])
from assistente import base as kb, consulta as cs, llm as m_llm, config
class Indice:
    def buscar(self, consulta, k=config.K): return [{"id": "T-072", "score": 0.95, "posicao": 1}]
class StubVeredito(m_llm.LLMStub):
    """SIMULADO: imita a resposta real do Qwen na pergunta da lasanha (texto sem citação)."""
    def __init__(self, citar): super().__init__(); self.citar = citar
    def gerar(self, mensagens, **kw):
        obj = {"resposta": "Não é seguro doar a lasanha que ficou no buffet a tarde toda." + (" Ver [T-072]." if self.citar else ""),
               "citacoes": ["T-072"] if self.citar else [], "suficiente": True}
        return {"texto": json.dumps(obj, ensure_ascii=False), "tempo_s": 0.0, "tokens_entrada": None, "tokens_saida": None,
                "tempo_limite_atingido": False, "semente": 42, "gulosa": False, "temperatura": 0.1}
base = kb.construir_base()
p = "É seguro doar a lasanha que ficou no buffet a tarde toda?"
for citar in (False, True):
    r = cs.Assistente(base, Indice(), StubVeredito(citar), tau=0.5).consultar(p)
    print("com citação" if citar else "sem citação", "|", r["status"], r["meta"].get("modo_resposta"), "|", r["resposta"][:140])
r = cs.Assistente(base, Indice(), m_llm.LLMStub(), tau=0.5).consultar("Como devo transportar comida pronta para doar?")
print("pergunta comum |", r["status"], r["meta"].get("modo_resposta"), [f["id_trecho"] for f in r["fontes"]])
