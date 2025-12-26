import streamlit as st
import google.generativeai as genai
import json
import re
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image

# ==========================================
# 🔑 APIキー設定 (安定版)
# ==========================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = "AIzaSyDFtXBreE4btuCc-sugDCiDKXNbv_biSu8" 

# 🟢 最も安定している 1.5-flash にモデル名を変更
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

# ==========================================
# 🧠 AI解析
# ==========================================
def analyze_food(text_or_image):
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = """
        Analyze food and estimate PFC. 
        If specific values (e.g. 20g protein) given, prioritize them.
        Output ONLY JSON: [{"food_name": "name", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
        """
        if isinstance(text_or_image, str):
            res = model.generate_content(f"Input: {text_or_image}. {prompt}")
        else:
            res = model.generate_content([prompt, text_or_image])
        match = re.search(r'\[.*\]', res.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"AI Connection Error: {e}")
        return None

# ==========================================
# 📱 メイン処理
# ==========================================
def main():
    init_db()
    if 'draft_data' not in st.session_state: st.session_state['draft_data'] = None

    st.title("🥗 BodyLog AI Ultimate")

    with st.sidebar:
        st.header("Settings")
        cur_w = st.number_input("Weight (kg)", 30.0, 150.0, 65.0)
        with st.expander("Details", expanded=True):
            gender = st.radio("Gender", ["Male", "Female"], horizontal=True)
            age = st.number_input("Age", 18, 100, 30)
            height = st.number_input("Height (cm)", 100.0, 250.0, 170.0)
            act = st.selectbox("Activity", [("Low", 1.2), ("Mid", 1.55), ("High", 1.725)], format_func=lambda x:x[0])[1]
            goal = st.selectbox("Goal", [("Maintain", 0), ("Lose", -500), ("Gain", 300)], format_func=lambda x:x[0])[1]
        p_ratio = st.slider("Protein Ratio (x kg)", 1.0, 2.5, 1.6)

    # Calculation
    bmr = (10*cur_w + 6.25*height - 5*age + 5) if gender=='Male' else (10*cur_w + 6.25*height - 5*age - 161)
    target_k = int(bmr * act + goal)
    target_p = int(cur_w * p_ratio)

    # Dashboard
    today = datetime.now().strftime('%Y-%m-%d')
    df_m, _ = get_daily_data(today)
    sum_k, sum_p, sum_f, sum_c = (df_m['kcal'].sum() or 0), (df_m['p'].sum() or 0), (df_m['f'].sum() or 0), (df_m['c'].sum() or 0)

    st.caption(f"Goal: {target_k} kcal / Protein: {target_p} g")
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="metric-card">Remaining Cal<br><span class="big-font">{int(target_k - sum_k)}</span></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card">Remaining P<br><span class="big-font" style="color:{"green" if target_p-sum_p<=0 else "red"}">{max(0, int(target_p-sum_p))}g</span></div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["📝 Input", "⭐️ MyMenu", "📊 Report", "🗑️ History"])

    with tab1:
        if st.session_state['draft_data'] is None:
            txt = st.text_input("What did you eat?")
            if st.button("Analyze", type="primary") and txt:
                with st.spinner("Analyzing..."):
                    res = analyze_food(txt)
                    if res: st.session_state['draft_data'] = res; st.rerun()
            img = st.file_uploader("Or Upload Photo", type=["jpg","png","jpeg"])
            if img and st.button("Analyze Photo"):
                with st.spinner("AI Processing..."):
                    res = analyze_food(Image.open(img))
                    if res: st.session_state['draft_data'] = res; st.rerun()
        else:
            with st.form("edit"):
                edited = []
                for idx, item in enumerate(st.session_state['draft_data']):
                    st.markdown(f"**Item {idx+1}**")
                    cols = st.columns([3, 1, 1, 1, 1])
                    n = cols[0].text_input("Name", item['food_name'], key=f"n_{idx}")
                    k = cols[1].number_input("kcal", 0, 5000, int(item['calories']), key=f"k_{idx}")
                    p = cols[2].number_input("P", 0, 500, int(item['protein']), key=f"p_{idx}")
                    f = cols[3].number_input("F", 0, 500, int(item['fat']), key=f"f_{idx}")
                    c = cols[4].number_input("C", 0, 500, int(item['carbs']), key=f"c_{idx}")
                    edited.append({"food_name": n, "calories": k, "protein": p, "fat": f, "carbs": c})
                if st.form_submit_button("✅ Save"):
                    for i in edited: add_meal(i['food_name'], i['calories'], i['protein'], i['fat'], i['carbs'])
                    st.session_state['draft_data'] = None; st.rerun()
                if st.form_submit_button("❌ Cancel"):
                    st.session_state['draft_data'] = None; st.rerun()

    with tab2:
        favs = get_favorites()
        if not favs.empty:
            sel = st.selectbox("Select", favs['name'])
            if st.button("Add Today"):
                f = favs[favs['name']==sel].iloc[0]
                add_meal(f['name'], f['kcal'], f['p'], f['f'], f['c']); st.rerun()
        else: st.info("Use ⭐️ in History tab to save menu.")

    with tab3:
        if sum_k > 0:
            # 🟢 日本語フォントなしでもOKなようにラベルを英語に変更
            fig, ax = plt.subplots(figsize=(4,4))
            ax.pie([sum_p, sum_f, sum_c], labels=['P','F','C'], colors=['#ff9999','#66b3ff','#99ff99'], autopct='%1.1f%%')
            st.pyplot(fig)
        df_w = get_weekly_summary()
        st.bar_chart(df_w.set_index("date")["intake"])

    with tab4:
        if not df_m.empty:
            for _, r in df_m.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{r['name']}** {int(r['kcal'])}kcal | P:{int(r['p'])} F:{int(r['f'])} C:{int(r['c'])}")
                if c2.button("🗑️", key=f"d_{r['id']}"):
                    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
                    cursor.execute("DELETE FROM meals WHERE id=?", (r['id'],)); conn.commit(); st.rerun()
                if c2.button("⭐️", key=f"s_{r['id']}"):
                    add_favorite(r['name'], r['kcal'], r['p'], r['f'], r['c']); st.success("Saved!")

if __name__ == "__main__":
    main()
