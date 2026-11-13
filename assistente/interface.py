"""N10: interface Gradio (abas Consulta, Comparação S×P×R e Avaliação) e endpoint api_name="consultar" para a FEMD.

O endpoint recebe a entrada do CT-02 (JSON) e devolve a saída do CT-02 (JSON). A FEMD chama com @gradio/client:
Client.connect(URL) e predict("/consultar", [entrada]). share=True (link público temporário) só no Colab.
Acessibilidade: linguagem simples, resumo primeiro, perguntas sugeridas em botões, rótulos em todos os campos,
status sempre em texto (nunca só por cor), fonte maior.
"""
from __future__ import annotations

import json

from . import config
from .consulta import consultar_ct02

ROTULO_STATUS = {"respondida": "Respondida com base nos documentos", "abstencao": "Não encontrei nos documentos",
                 "encaminhamento": "Encaminhamento: a decisão não cabe ao assistente",
                 "recusa_fora_do_tema": "Fora do tema do assistente", "recusa_seguranca": "Pedido recusado (segurança)",
                 "erro": "Erro"}
ROTULO_RESPONDIDA_SEM_DOCUMENTOS = "Respondida sem consultar documentos"
# Na tela aparece "beneficiário"; o valor enviado ao CT-02 continua "beneficiario" (sem acento, como no contrato)
PERFIS = [("doador", "doador"), ("beneficiário", "beneficiario"), ("outro", "outro")]
CSS = ".gradio-container {font-size: 17px !important} .aviso {font-size: 15px}"


def perguntas_sugeridas() -> list[str]:
    return json.loads(config.ler_prompt("perguntas_sugeridas.json"))["perguntas"]


def formatar(r: dict, configuracao: str = "R") -> tuple[str, str, str]:
    """(resposta, fontes, avisos) em Markdown para a tela. S e P não consultam documentos: rótulo próprio."""
    status = ROTULO_STATUS.get(r["status"], r["status"])
    if configuracao in ("S", "P") and r["status"] == "respondida":
        status = ROTULO_RESPONDIDA_SEM_DOCUMENTOS
    faixa = "**[RESPOSTA SIMULADA]** " if r.get("simulado") else ""
    if r["status"] == "erro":
        return f"{faixa}**Status:** {status}\n\n{r['erro']['mensagem']}", "", r["aviso_validacao_humana"]
    corpo = f"{faixa}**Status:** {status}\n\n{r['resposta']}"
    if r.get("encaminhamento"):
        corpo += f"\n\n**Procure:** {r['encaminhamento']['orgao']}."
    fontes = "\n\n".join(f"**[{f['id_trecho']}] {f['titulo']}**, {f['localizacao']}\n\n> {f['trecho']}\n\n{f['url']}"
                         for f in r.get("fontes", [])) or "Nenhuma fonte (resposta sem trecho citado)."
    avisos = "\n\n".join([f"- {a}" for a in r.get("avisos", [])] + [f"**{r['aviso_validacao_humana']}**"])
    return corpo, fontes, avisos


def criar_interface(assistente, pasta_avaliacao=None):
    import gradio as gr
    import pandas as pd

    from . import avaliacao as av

    def _consulta(pergunta, perfil, alimento, condicao):
        lote = {k: v for k, v in (("alimento", alimento), ("condicao", condicao)) if v and v.strip()} or None
        r = assistente.consultar(pergunta, contexto_lote=lote, perfil=perfil)
        return (*formatar(r), r)

    def _comparar(pergunta):
        saidas = []
        for cfg in config.CONFIGURACOES:
            r = assistente.consultar(pergunta, configuracao=cfg)
            corpo, fontes, _ = formatar(r, configuracao=cfg)
            saidas.append(f"{corpo}\n\n---\n**Fontes:**\n\n{fontes}\n\n*tempo: {r['meta'].get('tempo_ms')} ms*")
        return tuple(saidas)

    def _avaliacao():
        res = av.calcular_metricas(pasta_avaliacao, log=lambda *_: None)
        if not res:
            vazio = pd.DataFrame([{"aviso": "sem resultados: rode a seção N9 com REGERAR = True (GPU no Colab)"}])
            return vazio, vazio, vazio
        rec = res["recuperacao"] if res["recuperacao"] is not None else pd.DataFrame()
        return res["geral"].T.reset_index(), res["por_categoria"], rec

    def _api(entrada):
        return consultar_ct02(entrada)

    with gr.Blocks(title="Assistente de consulta FOMEZERO") as demo:
        gr.Markdown("# Assistente de consulta FOMEZERO\nTire dúvidas sobre doação segura de alimentos. As respostas "
                    "vêm de documentos oficiais e mostram a fonte. O assistente **não** diz se um alimento é seguro "
                    "para consumo: nesses casos ele orienta a procurar a vigilância sanitária do município."
                    + ("\n\n**Atenção: modo de teste com STUB SIMULADO (sem modelo de linguagem).**"
                       if assistente.llm.simulado else ""))
        with gr.Tab("Consulta"):
            pergunta = gr.Textbox(label="Sua pergunta (até 500 caracteres)", lines=3, max_length=config.MAX_CARACTERES)
            with gr.Row():
                perfil = gr.Dropdown(PERFIS, value="doador", label="Você é")
                botao = gr.Button("Consultar", variant="primary")
            with gr.Accordion("Contexto do lote de doação (opcional)", open=False):
                alimento = gr.Textbox(label="Alimento (texto livre)")
                condicao = gr.Textbox(label="Condição (texto livre)")
            gr.Examples(perguntas_sugeridas(), inputs=pergunta, label="Perguntas sugeridas")
            resposta = gr.Markdown(label="Resposta")
            with gr.Accordion("Fontes", open=True):
                fontes = gr.Markdown()
            avisos = gr.Markdown(elem_classes="aviso")
            with gr.Accordion("Resposta completa no formato CT-02 (JSON)", open=False):
                bruto = gr.JSON(label="CT-02")
            botao.click(_consulta, [pergunta, perfil, alimento, condicao], [resposta, fontes, avisos, bruto],
                        api_name=False)
        with gr.Tab("Comparação S × P × R"):
            gr.Markdown("A mesma pergunta em três configurações, com o mesmo modelo, temperatura e semente: "
                        "**S** só prompt simples (chatbot genérico), **P** prompt com regras e controle de saída, "
                        "sem documentos, **R** solução completa (RAG + regras + controle).")
            p2 = gr.Textbox(label="Pergunta")
            b2 = gr.Button("Comparar")
            with gr.Row():
                s_out, p_out, r_out = (gr.Markdown(label="S"), gr.Markdown(label="P"), gr.Markdown(label="R"))
            b2.click(_comparar, p2, [s_out, p_out, r_out], api_name=False)
        with gr.Tab("Avaliação"):
            gr.Markdown(f"Métricas recalculadas a partir dos arquivos de resultado (conjunto de teste). "
                        f"Limiar de abstenção τ = {assistente.tau:.4f} ({assistente.origem_tau}).")
            b3 = gr.Button("Recalcular métricas")
            t_geral = gr.Dataframe(label="Métricas por configuração")
            t_cat = gr.Dataframe(label="Por categoria")
            t_rec = gr.Dataframe(label="Recuperação (hit@k e MRR)")
            b3.click(_avaliacao, None, [t_geral, t_cat, t_rec], api_name=False)
        # endpoint do CT-02 para a FEMD (invisível na tela)
        api_in, api_out, api_bt = gr.JSON(visible=False), gr.JSON(visible=False), gr.Button(visible=False)
        api_bt.click(_api, api_in, api_out, api_name="consultar")
    return demo


def lancar(demo, share: bool | None = None, **kw):
    import gradio as gr
    share = config.EM_COLAB if share is None else share
    return demo.launch(share=share, theme=gr.themes.Default(text_size="lg"), css=CSS, **kw)
