import streamlit as st
import requests
import json
import re
import io
import base64
from PIL import Image
import pandas as pd
import sqlite3
from datetime import datetime

# ==========================================
# 🔑 APIキー設定
# ==========================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"].strip()
except:
    API_KEY = ""

# ==========================================
# 🛠 診断機能: あなたのキーで使えるモデルを探す
# ==========================================
def find_working_model():
    if not API_KEY:
        return None, "APIキーが設定されていません"

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "error" in data:
            return None, f"APIキーエラー: {data['error']['message']}"
            
        # 使えるモデルのリストを作成
        available_models = []
        if "models" in data:
            for m in data["models"]:
                # 「文章生成」に対応しているモデルだけを抽出
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    # モデル名 (models/gemini-1.5-flash 等) をそのまま保存
                    available_models.append(m["name"])
        
        if not available_models:
            return None, "このAPIキーで使えるモデルが1つも見つかりませんでした。"
            
        # 優先順位: Flash -> Pro -> その他
        best_model = available_models[0] # デフォルトは先頭
        for m in available_models:
            if "flash" in m and "1.5" in m:
                best_model = m
                break
        
        return best_model, None # 成功！使えるモデル名を返す

    except Exception as e:
        return None, f"通信エラー: {e}"

# ==========================================
# 🧠 AI解析ロジック
# ==========================================
def analyze_food(text_or_image):
    # 🟢 ここで「使えるモデル」を動的に取得する
    model_name, error = find_working_model()
    
    if error:
        st.error(f"❌ 診断結果: {error}")
        st.info("💡 ヒント: Google AI Studioで「新しいプロジェクト」を作成し、キーを作り直してください。")
        return None

    # URLの構築
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={API_KEY}"
    headers = {"Content-Type": "application/json"}

    system_instruction = """
    Analyze food items. Estimate Calories, Protein(P), Fat(F), Carbs(C).
    Output ONLY a JSON list: [{"food_name": "Item", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
    """

    payload = {}
    if isinstance(text_or_image, str):
        payload = {"contents": [{"parts": [{"text": f"Input: {text_or_image}. {system_instruction}"}]}]}
    else:
        buffered = io.BytesIO()
        text_or_image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        payload = {"contents": [{"parts": [{"text": system_instruction}, {"inline_data": {"mime_type": "image/jpeg", "data": img_str}}]}]}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            st.error(f"Google Error ({model_name}): {response.text}")
            return None
            
        result = response.json()
        try:
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r'\[.*\]', text, re.DOTALL)
            return json.loads(match.group(0)) if match else None
        except:
            st.error("解析失敗")
            return None
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# ==========================================
# 🎨 UI & DB (簡略化)
# ==========================================
st.set_page_config(page_title="BodyLog AI (Diag)", layout="centered")
DB_NAME = "diet_app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS meals (id INTEGER PRIMARY KEY, date TEXT, name TEXT, kcal REAL, p REAL, f REAL, c REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY, name TEXT, kcal REAL, p REAL, f REAL, c REAL)') # Favoritesテーブルを追加
    conn.commit()
    conn.close()

def execute_db(query, args=()):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute(query, args); conn.commit(); conn.close()

def get_db(query, args=()):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(query, conn, params=args)
    conn.close()
    return df

def main():
    init_db()
    st.title("🥗 BodyLog AI (診断モード)")
    
    # 診断情報の表示
    if st.sidebar.button("🔑 APIキー診断を実行"):
        model, err = find_working_model()
        if model:
            st.sidebar.success(f"✅ 成功！あなたのキーで使えるモデル: {model}")
        else:
            st.sidebar.error(f"❌ 失敗: {err}")

    if 'draft' not in st.session_state: st.session_state['draft'] = None

    tab1, tab2 = st.tabs(["📝 Record", "📊 History"])

    with tab1:
        txt = st.text_input("食事内容")
        if st.button("解析開始") and txt:
            with st.spinner("AIに接続中..."):
                res = analyze_food(txt)
                if res:
                    today = datetime.now().strftime('%Y-%m-%d')
                    for i in res:
                        execute_db("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)", 
                                   (today, i['food_name'], i['calories'], i['protein'], i['fat'], i['carbs']))
                    st.success("保存しました！")
                    st.rerun()

    with tab2:
        df = get_db("SELECT * FROM meals")
        st.dataframe(df)

if __name__ == "__main__":
    main()

