import streamlit as st
import google.generativeai as genai
import json
import re
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image
import time

# ==========================================
# 🔑 APIキー（secrets.toml 必須）
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)

MODEL_NAME = "models/gemini-1.5-flash"

# ==========================================
# 🎨 デザイン
# ==========================================
st.set_page_config(page_title="BodyLog AI Ultimate", layout="centered")
st.markdown("""
<style>
.stProgress > div > div > div > div { background-color: #4CAF50; }
.metric-card {
    background-color: #f8f9fa;
    padding: 15px;
    border-radius: 10px;
    text-align: center;
    border: 1px solid #eee;
}
.big-font { font-size: 20px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 💾 DB
# ==========================================
DB_NAME = "diet_app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS meals (id INTEGER PRIMARY KEY, date TEXT, name TEXT, kcal REAL, p REAL, f REAL, c REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY, name TEXT, kcal REAL, p REAL, f REAL, c REAL)')
    conn.commit()
    conn.close()

def add_meal(name, kcal, p, f, c):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime('%Y-%m-%d'), name, kcal, p, f, c)
    )
    conn.commit()
    conn.close()

def add_favorite(name, kcal, p, f, c):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO favorites (name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?)",
        (name, kcal, p, f, c)
    )
    conn.commit()
    conn.close()

def get_daily_meals(date):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM meals WHERE date = ?", conn, params=(date,))
    conn.close()
    return df

def get_favorites():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM favorites", conn)
    conn.close()
    return df

# ==========================================
# 🧠 AI解析（完全安定版）
# ==========================================
def analyze_food(text_or_image):
    from google.generativeai.types import content_types

    model = genai.GenerativeModel(MODEL_NAME)

    SYSTEM_PROMPT = """
あなたは管理栄養士AIです。

【厳守】
・出力はJSON配列のみ
・説明文、Markdown禁止
・以下の形式のみ

[
  {
    "food_name": "string",
    "calories": number,
    "protein": number,
    "fat": number,
    "carbs": number
  }
]

【計算】
・明示された数値は最優先
・kcal = protein*4 + fat*9 + carbs*4
・日本の一般的な食品基準
"""

    def call_gemini(payload):
        for _ in range(2):
            try:
                res = model.generate_content(payload)
                return res.text
            except:
                time.sleep(1)
        return None

    if isinstance(text_or_image, str):
        raw = call_gemini(SYSTEM_PROMPT + "\n食事内容: " + text_or_image)
    else:
        raw = call_gemini([
            SYSTEM_PROMPT,
            content_types.Image.from_pil_image(text_or_image)
        ])

    if not raw:
        return None

    match = re.search(r'\[\s*{.*?}\s*\]', raw, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except:
        return None

    cleaned = []
    for item in data:
        try:
            p = float(item["protein"])
            f = float(item["fat"])
            c = float(item["carbs"])
            kcal = int(round(p*4 + f*9 + c*4))

            cleaned.append({
                "food_name": str(item["food_name"]),
                "calories": kcal,
                "protein": int(round(p)),
                "fat": int(round(f)),
                "carbs": int(round(c))
            })
        except:
            continue

    return cleaned if cleaned else None

# ==========================================
# 📱 メイン
# ==========================================
def main():
    init_db()

    if "draft" not in st.session_state:
        st.session_state.draft = None

    st.title("🥗 BodyLog AI Ultimate")

    today = datetime.now().strftime('%Y-%m-%d')
    df = get_daily_meals(today)

    cur_kcal = df["kcal"].sum() if not df.empty else 0
    cur_p = df["p"].sum() if not df.empty else 0
    cur_f = df["f"].sum() if not df.empty else 0
    cur_c = df["c"].sum() if not df.empty else 0

    st.caption(f"今日の合計: {int(cur_kcal)}kcal / P:{int(cur_p)} F:{int(cur_f)} C:{int(cur_c)}")

    tab1, tab2, tab3 = st.tabs(["📝 記録", "⭐ マイメニュー", "📊 分析"])

    # --- 記録 ---
    with tab1:
        if st.session_state.draft is None:
            mode = st.radio("入力方法", ["文字", "写真"], horizontal=True)

            if mode == "文字":
                txt = st.text_input("食事内容")
                if st.button("解析する") and txt:
                    with st.spinner("解析中..."):
                        res = analyze_food(txt)
                        if res:
                            st.session_state.draft = res
                            st.rerun()
                        else:
                            st.error("解析失敗")
            else:
                img = st.file_uploader("画像", type=["jpg", "png"])
                if img and st.button("解析する"):
                    with st.spinner("解析中..."):
                        res = analyze_food(Image.open(img))
                        if res:
                            st.session_state.draft = res
                            st.rerun()
                        else:
                            st.error("解析失敗")

        else:
            with st.form("confirm"):
                edited = []
                for i, item in enumerate(st.session_state.draft):
                    st.subheader(item["food_name"])
                    kcal = st.number_input("kcal", value=item["calories"], key=f"k{i}")
                    p = st.number_input("P", value=item["protein"], key=f"p{i}")
                    f = st.number_input("F", value=item["fat"], key=f"f{i}")
                    c = st.number_input("C", value=item["carbs"], key=f"c{i}")
                    edited.append((item["food_name"], kcal, p, f, c))

                if st.form_submit_button("保存"):
                    for e in edited:
                        add_meal(*e)
                    st.session_state.draft = None
                    st.success("保存完了")
                    st.rerun()

    # --- マイメニュー ---
    with tab2:
        favs = get_favorites()
        if not favs.empty:
            sel = st.selectbox("選択", favs["name"])
            r = favs[favs["name"] == sel].iloc[0]
            if st.button("これ食べた"):
                add_meal(r["name"], r["kcal"], r["p"], r["f"], r["c"])
                st.success("記録しました")
                st.rerun()

    # --- 分析 ---
    with tab3:
        if cur_kcal > 0:
            fig, ax = plt.subplots()
            ax.pie([cur_p, cur_f, cur_c], labels=["P", "F", "C"], autopct="%1.1f%%")
            st.pyplot(fig)
        else:
            st.info("データなし")

if __name__ == "__main__":
    main()
