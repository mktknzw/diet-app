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
# 🔑 APIキー設定
# ==========================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = "" # ローカルテスト用

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
# 🧠 AI解析ロジック（総当たり対応版）
# ==========================================
def analyze_food(text_or_image):
    if not API_KEY:
        st.error("SecretsにAPIキーを設定してください")
        return None
    
    # 試行するモデルのリスト（優先順位順）
    # 最新のFlash -> 最新のPro -> 旧Pro の順に試す
    candidate_models = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-pro",
        "gemini-1.0-pro"
    ]

    prompt = """
    Analyze food items. Estimate Calories, Protein(P), Fat(F), Carbs(C).
    If specific values are given (e.g. "Protein 20g"), use them.
    Output ONLY a JSON list:
    [{"food_name": "Item Name", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
    """

    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            
            # 画像かテキストかで処理を分ける
            if isinstance(text_or_image, str):
                res = model.generate_content(f"Input: {text_or_image}. {prompt}")
            else:
                # gemini-pro (旧) は画像非対応なのでスキップして次のモデルへ
                if "gemini-pro" == model_name or "gemini-1.0-pro" == model_name:
                    continue 
                res = model.generate_content([prompt, text_or_image])
            
            # 成功したらJSONを抽出して返す
            match = re.search(r'\[.*\]', res.text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            match_single = re.search(r'\{.*\}', res.text, re.DOTALL)
            if match_single:
                return [json.loads(match_single.group(0))]
            
        except Exception:
            # 失敗したら次のモデルを試すので何もしない
            continue

    # 全モデルがダメだった場合
    st.error("全てのAIモデルで接続に失敗しました。時間をおいて再試行してください。")
    return None

# ==========================================
# 📱 アプリメイン処理
# ==========================================
def main():
    init_db()
    if 'draft_data' not in st.session_state: st.session_state['draft_data'] = None

    st.title("🥗 BodyLog AI")

    with st.sidebar:
        st.header("⚙️ Config")
        current_weight = st.number_input("Weight (kg)", 30.0, 150.0, 65.0)
        
        with st.expander("Details", expanded=False):
            gender = st.radio("Gender", ["Male", "Female"], horizontal=True)
            age = st.number_input("Age", 10, 100, 30)
            height = st.number_input("Height (cm)", 100.0, 250.0, 170.0)
            act_idx = st.selectbox("Activity", [0,1,2,3], format_func=lambda x: ["x1.2", "x1.375", "x1.55", "x1.725"][x])
            act_val = [1.2, 1.375, 1.55, 1.725][act_idx]
            goal_idx = st.selectbox("Goal", [0,1,2], format_func=lambda x: ["Maintain", "Lose(-500)", "Gain(+300)"][x])
            goal_val = [0, -500, 300][goal_idx]
        
        p_ratio = st.slider("Protein Target (x Weight)", 1.0, 3.0, 1.6)

        st.divider()
        df_all = get_db("SELECT * FROM meals")
        if not df_all.empty:
            csv = df_all.to_csv(index=False).encode('utf-8')
            st.download_button("💾 Download CSV", csv, "diet_log.csv", "text/csv")

    # Calculation
    if gender == 'Male':
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) - 161
    
    target_kcal = int(bmr * act_val + goal_val)
    target_p = int(current_weight * p_ratio)

    # Today's Data
    today_str = datetime.now().strftime('%Y-%m-%d')
    df_m = get_db("SELECT * FROM meals WHERE date = ?", (today_str,))
    
    sum_cal = df_m['kcal'].sum() if not df_m.empty else 0
    sum_p = df_m['p'].sum() if not df_m.empty else 0
    sum_f = df_m['f'].sum() if not df_m.empty else 0
    sum_c = df_m['c'].sum() if not df_m.empty else 0

    c1, c2 = st.columns(2)
    with c1:
        rem_cal = target_kcal - sum_cal
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">Remaining Cal (Goal: {target_kcal})</div>
            <div class="metric-value">{int(rem_cal)}</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(sum_cal / target_kcal, 1.0) if target_kcal > 0 else 0)
    
    with c2:
        rem_p = target_p - sum_p
        p_color = "green" if rem_p <= 0 else "#d9534f"
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">Remaining Protein (Goal: {target_p}g)</div>
            <div class="metric-value" style="color: {p_color};">{max(0, int(rem_p))} g</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(sum_p / target_p, 1.0) if target_p > 0 else 0)

    tab1, tab2, tab3, tab4 = st.tabs(["📝 Record", "⭐️ Menu", "📊 Analysis", "🗑️ History"])

    # Tab 1
    with tab1:
        if st.session_state['draft_data'] is None:
            in_mode = st.radio("Mode", ["Text", "Photo"], horizontal=True)
            
            if in_mode == "Text":
                txt_in = st.text_input("Food", placeholder="ex: Beef bowl")
                if st.button("Analyze", type="primary") and txt_in:
                    with st.spinner("Thinking..."):
                        res = analyze_food(txt_in)
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
            else:
                img_in = st.file_uploader("Photo", type=["jpg", "png", "jpeg"])
                if img_in and st.button("Analyze", type="primary"):
                    with st.spinner("Processing..."):
                        image = Image.open(img_in)
                        res = analyze_food(image)
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
        else:
            st.info("Check & Save")
            with st.form("edit_form"):
                edited_items = []
                for i, item in enumerate(st.session_state['draft_data']):
                    st.markdown(f"**Item {i+1}**")
                    cols = st.columns([3, 1, 1, 1, 1])
                    n = cols[0].text_input("Name", item['food_name'], key=f"n{i}")
                    k = cols[1].number_input("kcal", 0, 9999, int(item['calories']), key=f"k{i}")
                    p = cols[2].number_input("P", 0, 999, int(item['protein']), key=f"p{i}")
                    f = cols[3].number_input("F", 0, 999, int(item['fat']), key=f"f{i}")
                    c = cols[4].number_input("C", 0, 999, int(item['carbs']), key=f"c{i}")
                    edited_items.append({"name":n, "kcal":k, "p":p, "f":f, "c":c})
                
                b1, b2 = st.columns(2)
                if b1.form_submit_button("✅ Save", type="primary"):
                    today = datetime.now().strftime('%Y-%m-%d')
                    for item in edited_items:
                        execute_db("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)",
                                   (today, item['name'], item['kcal'], item['p'], item['f'], item['c']))
                    st.session_state['draft_data'] = None
                    st.success("Saved!")
                    st.rerun()
                
                if b2.form_submit_button("❌ Cancel"):
                    st.session_state['draft_data'] = None
                    st.rerun()

    # Tab 2
    with tab2:
        favs = get_db("SELECT * FROM favorites")
        if not favs.empty:
            sel_fav = st.selectbox("My Menu", favs['name'])
            target = favs[favs['name'] == sel_fav].iloc[0]
            st.success(f"{target['name']} : {int(target['kcal'])}kcal")
            if st.button("Add to Today"):
                today = datetime.now().strftime('%Y-%m-%d')
                execute_db("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)",
                           (today, target['name'], target['kcal'], target['p'], target['f'], target['c']))
                st.success("Added!")
                time.sleep(1)
                st.rerun()
        else:
            st.info("Save favorites from History tab.")

    # Tab 3
    with tab3:
        st.subheader("Balance")
        if sum_cal > 0:
            fig, ax = plt.subplots(figsize=(4, 4))
            ax.pie([sum_p, sum_f, sum_c], labels=['Protein', 'Fat', 'Carbs'], 
                   colors=['#ff9999', '#66b3ff', '#99ff99'], autopct='%1.1f%%', startangle=90)
            st.pyplot(fig)
        else:
            st.write("No data")
        st.divider()
        st.subheader("Weekly")
        dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)][::-1]
        weekly_data = []
        for d in dates:
            row = get_db("SELECT SUM(kcal) as k, SUM(p) as p FROM meals WHERE date = ?", (d,))
            k_val = row.iloc[0]['k'] if row.iloc[0]['k'] else 0
            p_val = row.iloc[0]['p'] if row.iloc[0]['p'] else 0
            weekly_data.append({"date": d, "Calories": k_val, "Protein": p_val})
        df_week = pd.DataFrame(weekly_data).set_index("date")
        
        st.caption("Calories")
        st.bar_chart(df_week["Calories"])
        
        st.caption("Protein")
        fig2, ax2 = plt.subplots(figsize=(6, 3))
        ax2.plot(df_week.index, df_week["Protein"], marker='o', label='Intake')
        ax2.axhline(target_p, color='red', linestyle='--', label='Target')
        plt.xticks(rotation=45)
        ax2.legend()
        st.pyplot(fig2)

    # Tab 4
    with tab4:
        if not df_m.empty:
            for i, r in df_m.iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{r['name']}**")
                    c1.caption(f"🔥{int(r['kcal'])} | P:{int(r['p'])} | F:{int(r['f'])} | C:{int(r['c'])}")
                    bc1, bc2 = c2.columns(2)
                    if bc1.button("⭐️", key=f"fav_{r['id']}"):
                        execute_db("INSERT INTO favorites (name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?)",
                                   (r['name'], r['kcal'], r['p'], r['f'], r['c']))
                        st.success("Saved!")
                    if bc2.button("🗑️", key=f"del_{r['id']}"):
                        execute_db("DELETE FROM meals WHERE id=?", (r['id'],))
                        st.rerun()
                    st.divider()
        else:
            st.info("No records today")

if __name__ == "__main__":
    main()
