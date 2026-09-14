# -*- coding: utf-8 -*-
"""
Ponto de entrada da interface.

    streamlit run app.py

Existe para ser fino de propósito. Toda a decisão está em
`painel_san.modulos.alimento_seguro.pagina`, que é testável sem subir servidor;
aqui só se escolhe qual página servir e com que dado.

Manter este arquivo magro é o que permite ao pacote ser usado como biblioteca por
quem não quer interface nenhuma — e é o que torna o comportamento verificável em
teste, em vez de só clicável.
"""
import streamlit as st

from painel_san.modulos.alimento_seguro import pagina

st.set_page_config(page_title="Onde o dado não permite vigiar",
                   page_icon="◧", layout="wide")

pagina.app()
