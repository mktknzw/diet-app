import streamlit as st
import google.generativeai as genai

API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)

st.title("Gemini モデル確認")

try:
    models = genai.list_models()
    st.success(f"取得モデル数: {len(models)}")

    for m in models:
        st.write({
            "name": m.name,
            "supported_generation_methods": m.supported_generation_methods
        })

except Exception as e:
    st.error("モデル一覧取得失敗")
    st.error(repr(e))



