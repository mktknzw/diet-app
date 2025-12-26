import streamlit as st
import google.generativeai as genai
import json
import re
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image
import io

# ==========================================
# 🔑 APIキー設定 (Streamlit Cloud対応)
# ==========================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    # PCでのテスト用（GitHubに上げるときは空にする）
    API_KEY = ""

if API_KEY:
    genai.configure(api_key=API_KEY)

# ==========================================
# 🎨 UIデザイン
# ==========================================
st.set_page_config(page_title="BodyLog AI", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""
    <style>
    .stProgress > div > div > div > div { background-color: #4CAF50; }
    .metric-container {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: #333; }
    .metric-label { font-size: 14px; color: #666; margin-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 💾 データベース管理
# ==========================================
DB_NAME = "diet_app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS meals (id INTEGER PRIMARY KEY, date TEXT, name TEXT, kcal REAL, p REAL, f REAL, c REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS exercises (id INTEGER PRIMARY KEY, date TEXT, name TEXT, burned REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS weights (id INTEGER PRIMARY KEY, date TEXT, kg REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY, name TEXT, kcal REAL, p REAL, f REAL, c REAL)')
    conn.commit()
    conn.close()

def execute_db(query, args=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, args)
    conn.commit()
    conn.close()

def get_db(query, args=()):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(query, conn, params=args)
    conn.close()
    return df

# ==========================================
# 🧠 AI解析ロジック
# ==========================================
def analyze_food(text_or_image):
    if not API_KEY:
        st.error("⚠️ APIキーが設定されていません。Streamlit CloudのSecretsを設定してください。")
        return None
    try:
        # 🟢 【修正】安定版の gemini-pro を使用 (テキスト専用)
        # 画像入力の場合は gemini-1.5-flash を試すが、エラー時はメッセージを出す
        
        prompt = """
        Analyze food items. Estimate Calories, Protein(P), Fat(F), Carbs(C).
        If specific values are given (e.g. "Protein 20g"), use them.
        Output ONLY a JSON list:
        [{"food_name": "Item Name", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
        """

        if isinstance(text_or_image, str):
            # テキスト入力：gemini-pro (最も安定)
            model = genai.GenerativeModel("gemini-pro")
            res = model.generate_content(f"Input: {text_or_image}. {prompt}")
        else:
            # 画像入力：gemini-1.5-flash (対応している場合のみ)
            model = genai.GenerativeModel("gemini-1.5-flash")
            res = model.generate_content([prompt, text_or_image])
            
        match = re.search(r'\[.*\]', res.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        match_single = re.search(r'\{.*\}', res.text, re.DOTALL)
        if match_single:
            return [json.loads(match_single.group(0))]
        return None

    except Exception as e:
        # エラー詳細
