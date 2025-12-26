import streamlit as st
import google.generativeai as genai
import json
import re
import sqlite3
from datetime import datetime
import pandas as pd

# ===============================
# 🔑 API KEY
# ===============================
API_KEY = st.secrets.get("GEMINI_API_KEY", None)
st.write("API KEY exists:", bool(API_KEY))

if not API_KEY:
    st.stop()

genai.configure(api_key=API_KEY)

MODEL_NAME = "models/gemini-1.0-pro"

# ===============================
# 💾 DB
# ===============================
DB_NAME = "diet_app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY,
            date TEXT,
            name TEXT,
            kcal REAL,
            p REAL,
            f REAL,
            c REAL
        )
    """)
    conn.commit()
    conn.close()

def add_meal(name, kcal, p, f, c):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO meals VALUES (NULL, ?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d"), name, kcal, p, f, c)
    )
    conn.commit()
    conn.close()

# ===============================
# 🧠 Geminiテスト & 食事解析
# ===============================
def analyze_food(text):
    try:
        model = genai.GenerativeModel(MODEL_NAME)

        prompt = f"""
以下の食事を解析してください。
JSON配列のみで返してください。

[{{"food_name":"", "calories":0, "protein":0, "fat":0, "carbs":0}}]

食事: {text}
"""
        res = model.generate_content(prompt)

        st.write("🔍 Gemini raw response:")
        st.code(res.text)

        match = re.search(r"\[.*\]", res.text, re.DOTALL)
        if not match:
            raise ValueError("JSONが見つかりません")

        return json.loads(match.group())

    except Exception as e:
        st.error("❌ Gemini解析エラー")
        st.error(repr(e))
        raise e   # ← Cloudログに必ず出す

# ===============================
# 🚀 UI
# ===============================
def main():
    st.set_page_config(page_title="BodyLog AI Test", layout="centered")
    st.title("🥗 BodyLog AI（動作確認版）")

    init_db()

    st.subheader("🧪 Gemini Health Check")
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content("日本語でこんにちはと言って")
        st.success("✅ Gemini 接続OK")
        st.write(res.text)
    except Exception as e:
        st.error("❌ Gemini 接続失敗")
        st.error(repr(e))
        st.stop()

    st.divider()

    st.subheader("🍱 食事入力テスト")
    text = st.text_input("食事内容", placeholder="例: 鶏むね肉とご飯")

    if st.button("解析する"):
        result = analyze_food(text)
        st.success("解析成功")
        st.write(result)

        for item in result:
            add_meal(
                item["food_name"],
                item["calories"],
                item["protein"],
                item["fat"],
                item["carbs"]
            )

    st.divider()

    st.subheader("📜 記録一覧")
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM meals", conn)
    conn.close()
    st.dataframe(df)

if __name__ == "__main__":
    main()


