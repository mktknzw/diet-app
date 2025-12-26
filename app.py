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
# 👇 APIキー
# ==========================================
API_KEY = "AIzaSyDFtXBreE4btuCc-sugDCiDKXNbv_biSu8"
# ==========================================

# 🟢 モデル名を安定版の 1.5-flash に修正
MODEL_NAME = "models/gemini-1.5-flash"
genai.configure(api_key=API_KEY)

# ==========================================
# 🎨 デザイン (CSS)
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
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    .big-font { font-size: 20px; font-weight: bold; }
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

def add_meal(name, kcal, p, f, c):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)", 
                   (datetime.now().strftime('%Y-%m-%d'), name, kcal, p, f, c))
    conn.commit(); conn.close()

def add_favorite(name, kcal, p, f, c):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("INSERT INTO favorites (name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?)", (name, kcal, p, f, c))
    conn.commit(); conn.close()

def get_favorites():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM favorites", conn)
    conn.close()
    return df

def get_daily_data(date_str):
    conn = sqlite3.connect(DB_NAME)
    df_m = pd.read_sql_query(f"SELECT * FROM meals WHERE date = '{date_str}'", conn)
    df_e = pd.read_sql_query(f"SELECT * FROM exercises WHERE date = '{date_str}'", conn)
    conn.close()
    return df_m, df_e

def get_weekly_summary():
    conn = sqlite3.connect(DB_NAME)
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(14)][::-1]
    summary = []
    cursor = conn.cursor()
    for d in dates:
        cursor.execute("SELECT SUM(kcal), SUM(p) FROM meals WHERE date = ?", (d,))
        res = cursor.fetchone()
        intake, prot = (res[0] or 0), (res[1] or 0)
        cursor.execute("SELECT kg FROM weights WHERE date = ?", (d,))
        r_w = cursor.fetchone()
        summary.append({"date": d, "intake": intake, "protein": prot, "weight": r_w[0] if r_w else None})
    conn.close()
    return pd.DataFrame(summary)

def analyze_food(text_or_image):
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = """
        Analyze food items and estimate Calories, P, F, C.
        If specific numbers are provided (e.g., Protein 20g), prioritize them.
        Output ONLY a JSON list: [{"food_name": "name", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
        """
        if isinstance(text_or_image, str):
            res = model.generate_content(f"Input: {text_or_image}. {prompt}")
        else:
            res = model.generate_content([prompt, text_or_image])
        match = re.search(r'\[.*\]', res.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"AI Error: {e}") # 🆕 エラーがあれば画面に出すようにしました
        return None

def main():
    init_db()
    if 'draft_data' not in st.session_state: st.session_state['draft_data'] = None

    st.title("🥗 BodyLog AI Ultimate")

    with st.sidebar:
        st.header("⚙️ 設定")
        current_weight = st.number_input("体重 (kg)", 30.0, 150.0, 65.0)
        with st.expander("📏 詳細設定", expanded=True):
            gender = st.radio("性別", ["男性", "女性"], horizontal=True)
            age = st.number_input("年齢", 18, 100, 30)
            height = st.number_input("身長 (cm)", 100.0, 250.0, 170.0)
            act_opts = [("1.2", 1.2), ("1.375", 1.375), ("1.55", 1.55), ("1.725", 1.725)]
            act_val = st.selectbox("活動レベル", act_opts, format_func=lambda x: x[0])
            goal_opts = [("0", 0), ("-500", -500), ("+300", 300)]
            goal_val = st.selectbox("目標kcal調整", goal_opts, format_func=lambda x: x[0])
        p_target_ratio = st.slider("タンパク質目標 (体重 x ?)", 1.0, 2.5, 1.6)

    # 目標計算
    if gender == '男性':
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) - 161
    target_kcal = int(bmr * act_val[1] + goal_val[1])
    target_p = int(current_weight * p_target_ratio)

    today_str = datetime.now().strftime('%Y-%m-%d')
    df_m, df_e = get_daily_data(today_str)
    cur_cal, cur_p, cur_f, cur_c = (df_m['kcal'].sum() or 0), (df_m['p'].sum() or 0), (df_m['f'].sum() or 0), (df_m['c'].sum() or 0)

    st.caption(f"Goal: {target_kcal}kcal / P: {target_p}g")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div class="metric-card">Remaining Cal<br><span class="big-font">{int(target_kcal - cur_cal)}</span></div>', unsafe_allow_html=True)
    with c2:
        rem_p = target_p - cur_p
        st.markdown(f'<div class="metric-card">Remaining P<br><span class="big-font" style="color:{"green" if rem_p<=0 else "red"}">{max(0, int(rem_p))}g</span></div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["📝 Input", "⭐️ MyMenu", "📊 Analysis", "🗑️ History"])

    with tab1:
        if st.session_state['draft_data'] is None:
            in_type = st.radio("Type", ["Text", "Photo"], horizontal=True)
            if in_type == "Text":
                txt = st.text_input("What did you eat?")
                if st.button("Analyze", type="primary") and txt:
                    with st.spinner("Analyzing..."):
                        res = analyze_food(txt)
                        if res: st.session_state['draft_data'] = res; st.rerun()
            else:
                img = st.file_uploader("Photo", type=["jpg","png","jpeg"])
                if img and st.button("Analyze Photo", type="primary"):
                    with st.spinner("Analyzing Image..."):
                        res = analyze_food(Image.open(img))
                        if res: st.session_state['draft_data'] = res; st.rerun()
        else:
            with st.form("edit_form"):
                edited = []
                for idx, item in enumerate(st.session_state['draft_data']):
                    st.markdown(f"**Item {idx+1}**")
                    c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1, 1, 1])
                    n = c1.text_input("Name", item['food_name'], key=f"n_{idx}")
                    k = c2.number_input("kcal", 0, 5000, int(item['calories']), key=f"k_{idx}")
                    p = c3.number_input("P", 0, 500, int(item['protein']), key=f"p_{idx}")
                    f = c4.number_input("F", 0, 500, int(item['fat']), key=f"f_{idx}")
                    c = c5.number_input("C", 0, 500, int(item['carbs']), key=f"c_{idx}")
                    edited.append({"food_name": n, "calories": k, "protein": p, "fat": f, "carbs": c})
                if st.form_submit_button("✅ Save", type="primary"):
                    for i in edited: add_meal(i['food_name'], i['calories'], i['protein'], i['fat'], i['carbs'])
                    st.session_state['draft_data'] = None; st.rerun()
                if st.form_submit_button("❌ Cancel"):
                    st.session_state['draft_data'] = None; st.rerun()

    with tab2:
        favs = get_favorites()
        if not favs.empty:
            sel = st.selectbox("Select Favorite", favs['name'])
            tgt = favs[favs['name'] == sel].iloc[0]
            if st.button("Add to Today"):
                add_meal(tgt['name'], tgt['kcal'], tgt['p'], tgt['f'], tgt['c']); st.rerun()
        else: st.info("No favorites yet.")

    with tab3:
        st.subheader("PFC Balance")
        if cur_cal > 0:
            # 🟢 グラフの日本語を排除してエラーを回避
            fig_pie, ax_pie = plt.subplots(figsize=(4, 4))
            ax_pie.pie([cur_p, cur_f, cur_c], labels=['P', 'F', 'C'], colors=['#ff9999', '#66b3ff', '#99ff99'], autopct='%1.1f%%')
            st.pyplot(fig_pie)
        
        st.divider()
        df_w = get_weekly_summary()
        st.subheader("Weekly Intake (kcal)")
        st.bar_chart(df_w.set_index("date")[["intake"]])

    with tab4:
        if not df_m.empty:
            for i, r in df_m.iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"**{r['name']}**")
                    c1.caption(f"{int(r['kcal'])}kcal | P:{int(r['p'])}g | F:{int(r['f'])}g | C:{int(r['c'])}g")
                    if c2.button("🗑️", key=f"del_{r['id']}"):
                        conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
                        cur.execute("DELETE FROM meals WHERE id=?", (r['id'],)); conn.commit(); st.rerun()
                    if c2.button("⭐️", key=f"fav_{r['id']}"):
                        add_favorite(r['name'], r['kcal'], r['p'], r['f'], r['c']); st.success("Saved!")

if __name__ == "__main__":
    main()

