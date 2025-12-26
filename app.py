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
# 👇 ここにAPIキーを入れてください
# ==========================================
# Streamlitの「金庫」からキーを取り出す設定
# ※ ローカル（自分のPC）で動かすときは、ここに直接キーを入れるか、secrets.tomlというファイルを作りますが、
#    公開用はこれでOKです。
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    # 自分のPCでテストする用 (公開時は消してもOKですが、残しておくと便利)
    API_KEY = "AIzaSyDFtXBreE4btuCc-sugDCiDKXNbv_biSu8"

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
# 💾 データベース
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
        食事品目を分解し、カロリーとPFCを推定して。
        具体的数値（例:タンパク質20g）があれば絶対優先して逆算すること。
        JSONリスト形式のみ出力: [{"food_name": "品目名", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
        """
        if isinstance(text_or_image, str):
            res = model.generate_content(f"入力: {text_or_image}。{prompt}")
        else:
            res = model.generate_content([prompt, text_or_image])
        match = re.search(r'\[.*\]', res.text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except: return None

# ==========================================
# 📱 メイン処理
# ==========================================
def main():
    init_db()
    
    if 'draft_data' not in st.session_state: st.session_state['draft_data'] = None

    st.title("🥗 BodyLog AI Ultimate")

    # --- サイドバー (設定) ---
    with st.sidebar:
        st.header("⚙️ プロフィール設定")
        current_weight = st.number_input("現在の体重 (kg)", 30.0, 150.0, 65.0)
        
        with st.expander("📏 詳細設定", expanded=True):
            gender = st.radio("性別", ["男性", "女性"], horizontal=True)
            age = st.number_input("年齢", 18, 100, 30)
            height = st.number_input("身長 (cm)", 100.0, 250.0, 170.0)
            act_opts = [("運動なし(x1.2)", 1.2), ("週1-3(x1.375)", 1.375), ("週3-5(x1.55)", 1.55), ("毎日(x1.725)", 1.725)]
            act_val = st.selectbox("活動レベル", act_opts, format_func=lambda x: x[0])
            goal_opts = [("維持(±0)", 0), ("ダイエット(-500)", -500), ("増量(+300)", 300)]
            goal_val = st.selectbox("目的", goal_opts, format_func=lambda x: x[0])

        st.divider()
        p_target_ratio = st.slider("タンパク質目標 (体重 x ?)", 1.0, 2.5, 1.6)
        
        # CSV
        st.divider()
        conn = sqlite3.connect(DB_NAME)
        df_export = pd.read_sql_query("SELECT * FROM meals", conn)
        conn.close()
        csv = df_export.to_csv(index=False).encode('utf-8')
        st.download_button("💾 CSV保存", csv, "diet_log.csv", "text/csv")

    # 目標計算
    if gender == '男性':
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) - 161
    target_kcal = int(bmr * act_val[1] + goal_val[1])
    target_p = int(current_weight * p_target_ratio)

    # --- ダッシュボード ---
    today_str = datetime.now().strftime('%Y-%m-%d')
    df_m, df_e = get_daily_data(today_str)
    
    # 今日の合計値
    cur_cal = df_m['kcal'].sum() if not df_m.empty else 0
    cur_p = df_m['p'].sum() if not df_m.empty else 0
    cur_f = df_m['f'].sum() if not df_m.empty else 0
    cur_c = df_m['c'].sum() if not df_m.empty else 0

    st.caption(f"目標: {target_kcal}kcal (P目標: {target_p}g)")

    # メーター
    c1, c2 = st.columns(2)
    with c1:
        rem_cal = target_kcal - cur_cal
        st.markdown(f'<div class="metric-card">残りCal<br><span class="big-font">{int(rem_cal)}</span></div>', unsafe_allow_html=True)
        st.progress(min(cur_cal/target_kcal, 1.0) if target_kcal>0 else 0)
    with c2:
        rem_p = target_p - cur_p
        color = "green" if rem_p <= 0 else "red"
        st.markdown(f'<div class="metric-card">残りProtein<br><span class="big-font" style="color:{color}">{max(0, int(rem_p))}g</span></div>', unsafe_allow_html=True)
        st.progress(min(cur_p/target_p, 1.0) if target_p>0 else 0)

    # --- タブ ---
    tab1, tab2, tab3, tab4 = st.tabs(["📝 記録", "⭐️ マイメニュー", "📊 分析", "🗑️ 履歴"])

    # Tab 1: 記録
    with tab1:
        if st.session_state['draft_data'] is None:
            st.info("💡 AI解析後に数値を修正できます")
            in_type = st.radio("入力", ["文字", "写真"], horizontal=True)
            
            if in_type == "文字":
                txt = st.text_input("食事内容", placeholder="例: 鮭定食")
                if st.button("解析する", type="primary") and txt:
                    with st.spinner("計算中..."):
                        res = analyze_food(txt)
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
            else:
                img = st.file_uploader("画像")
                if img and st.button("解析する", type="primary"):
                    with st.spinner("計算中..."):
                        res = analyze_food(Image.open(img))
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
        else:
            st.subheader("🧐 確認・修正")
            with st.form("edit_form"):
                edited = []
                for idx, item in enumerate(st.session_state['draft_data']):
                    st.markdown(f"**品目 {idx+1}**")
                    c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1, 1, 1])
                    n = c1.text_input("名前", item['food_name'], key=f"n_{idx}")
                    k = c2.number_input("kcal", 0, 5000, int(item['calories']), key=f"k_{idx}")
                    p = c3.number_input("P(g)", 0, 500, int(item['protein']), key=f"p_{idx}")
                    f = c4.number_input("F(g)", 0, 500, int(item['fat']), key=f"f_{idx}")
                    c = c5.number_input("C(g)", 0, 500, int(item['carbs']), key=f"c_{idx}")
                    edited.append({"food_name": n, "calories": k, "protein": p, "fat": f, "carbs": c})
                    st.divider()
                
                bc1, bc2 = st.columns(2)
                if bc1.form_submit_button("✅ 保存", type="primary"):
                    for i in edited:
                        add_meal(i['food_name'], i['calories'], i['protein'], i['fat'], i['carbs'])
                    st.session_state['draft_data'] = None
                    st.success("保存完了")
                    st.rerun()
                if bc2.form_submit_button("❌ キャンセル"):
                    st.session_state['draft_data'] = None
                    st.rerun()

    # Tab 2: マイメニュー
    with tab2:
        st.subheader("⭐️ よく食べるもの")
        favs = get_favorites()
        if not favs.empty:
            sel = st.selectbox("選択", favs['name'])
            tgt = favs[favs['name'] == sel].iloc[0]
            st.info(f"{int(tgt['kcal'])}kcal (P:{int(tgt['p'])} F:{int(tgt['f'])} C:{int(tgt['c'])})")
            if st.button("これ食べた！"):
                add_meal(tgt['name'], tgt['kcal'], tgt['p'], tgt['f'], tgt['c'])
                st.success("記録しました")
                st.rerun()
        else:
            st.info("履歴タブから登録できます")

    # Tab 3: 分析 (円グラフ追加！)
    with tab3:
        # 1. 今日のPFCバランス (円グラフ)
        st.subheader("今日のPFCバランス")
        if cur_cal > 0:
            fig_pie, ax_pie = plt.subplots(figsize=(4, 4))
            labels = ['Protein (P)', 'Fat (F)', 'Carbs (C)']
            sizes = [cur_p, cur_f, cur_c]
            colors = ['#ff9999', '#66b3ff', '#99ff99']
            ax_pie.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
            ax_pie.axis('equal')
            st.pyplot(fig_pie)
            st.caption(f"合計: P {int(cur_p)}g / F {int(cur_f)}g / C {int(cur_c)}g")
        else:
            st.info("データがありません")

        st.divider()

        # 2. 週間推移
        st.subheader("週間推移")
        df_w = get_weekly_summary()
        st.bar_chart(df_w.set_index("date")[["intake"]])
        
        fig, ax = plt.subplots(figsize=(8,3))
        ax.plot(df_w['date'], df_w['protein'], marker='o', label='P摂取量')
        ax.axhline(target_p, color='red', linestyle='--', label='目標')
        ax.legend()
        st.pyplot(fig)

    # Tab 4: 履歴 (PFC全表示！)
    with tab4:
        st.caption("⭐️でマイメニュー登録、🗑️で削除")
        if not df_m.empty:
            for i, r in df_m.iterrows():
                # デザイン調整
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"**{r['name']}**")
                    # 👇 ここでPFCすべてを表示するように変更しました！
                    c1.caption(f"🔥{int(r['kcal'])}kcal | P:{int(r['p'])}g | F:{int(r['f'])}g | C:{int(r['c'])}g")
                    
                    if c2.button("⭐️", key=f"fav_{r['id']}"):
                        add_favorite(r['name'], r['kcal'], r['p'], r['f'], r['c'])
                        st.success("登録！")
                    if c2.button("🗑️", key=f"del_{r['id']}"):
                        conn = sqlite3.connect(DB_NAME); cur = conn.cursor()
                        cur.execute("DELETE FROM meals WHERE id=?", (r['id'],))
                        conn.commit(); conn.close(); st.rerun()
                    st.divider()

if __name__ == "__main__":

    main()

