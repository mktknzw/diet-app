import streamlit as st
import requests
import json
import re
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image
import io
import base64
import time

# ==========================================
# 🔑 APIキー設定
# ==========================================
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = ""

# ==========================================
# 🔍 自動で使える「無料」モデルを探す関数
# ==========================================
def get_available_model():
    if not API_KEY:
        return None
    
    # 🟢 【対策】無料枠で確実に動く "Flash" シリーズだけを徹底的に試すリスト
    # Pro系を入れると「Limit 0」のエラーになるため除外しました
    candidate_models = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-1.0-pro" # どうしてもFlashがだめな時の保険
    ]

    # モデルリストを取得せず、直接「生存確認」を行う方式に変更
    # (ListModelsAPI自体が不安定な場合があるため)
    
    base_url = "https://generativelanguage.googleapis.com/v1beta/models/"
    headers = {"Content-Type": "application/json"}
    dummy_payload = {
        "contents": [{"parts": [{"text": "Hello"}]}]
    }

    st.toast("🔍 最適な無料AIモデルを探索中...", icon="🤖")

    for model_name in candidate_models:
        check_url = f"{base_url}{model_name}:generateContent?key={API_KEY}"
        try:
            # テスト送信
            response = requests.post(check_url, headers=headers, data=json.dumps(dummy_payload))
            
            if response.status_code == 200:
                # 成功したらこのモデルを採用！
                return f"models/{model_name}"
            elif response.status_code == 429:
                # 429は「使いすぎ」または「無料枠なし」。これはスキップ
                continue
            
        except:
            continue

    st.error("❌ 利用可能な無料モデルが見つかりませんでした。Google AI StudioでAPIキーの設定を確認するか、1分待ってから再試行してください。")
    return None

# ==========================================
# 🧠 AI解析ロジック (REST API直接通信)
# ==========================================
def analyze_food(text_or_image):
    if not API_KEY:
        st.error("SecretsにAPIキーが設定されていません。")
        return None

    # 🟢 毎回、使えるモデルを確認してから投げる (キャッシュしても良いが安全重視)
    if 'cached_model' not in st.session_state:
        st.session_state['cached_model'] = get_available_model()
    
    model_name = st.session_state['cached_model']
    if not model_name:
        return None

    # URLの構築
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={API_KEY}"
    
    headers = {"Content-Type": "application/json"}

    # プロンプト
    system_instruction = """
    Analyze food items. Estimate Calories, Protein(P), Fat(F), Carbs(C).
    If specific values are given (e.g. "Protein 20g"), use them.
    Output ONLY a JSON list:
    [{"food_name": "Item Name", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}]
    """

    # ペイロード作成
    payload = {}
    if isinstance(text_or_image, str):
        payload = {
            "contents": [{"parts": [{"text": f"Input: {text_or_image}. {system_instruction}"}]}]
        }
    else:
        buffered = io.BytesIO()
        text_or_image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        payload = {
            "contents": [{
                "parts": [
                    {"text": system_instruction},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_str}}
                ]
            }]
        }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        # 🟢 エラーハンドリング強化
        if response.status_code == 429:
            st.warning("⚠️ Googleの無料枠制限(速度制限)にかかりました。約60秒待ってから再試行してください。")
            return None
        
        if response.status_code != 200:
            st.error(f"Google Error ({model_name}): {response.text}")
            # エラーが出たらキャッシュをクリアして次回再探索
            del st.session_state['cached_model']
            return None

        result_json = response.json()
        try:
            # 応答の検証
            if "candidates" not in result_json or not result_json["candidates"]:
                st.error("AIが回答を拒否しました（不適切なコンテンツと判定された可能性があります）。")
                return None
                
            text_response = result_json["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r'\[.*\]', text_response, re.DOTALL)
            if match: return json.loads(match.group(0))
            match_s = re.search(r'\{.*\}', text_response, re.DOTALL)
            if match_s: return [json.loads(match_s.group(0))]
            return None
        except Exception as e:
            st.error(f"解析エラー: {e}")
            return None

    except Exception as e:
        st.error(f"通信エラー: {e}")
        return None

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
# 📱 アプリメイン処理
# ==========================================
def main():
    init_db()
    if 'draft_data' not in st.session_state: st.session_state['draft_data'] = None

    st.title("🥗 BodyLog AI (Free)")

    # --- サイドバー ---
    with st.sidebar:
        st.header("⚙️ Config")
        current_weight = st.number_input("体重 (kg)", 30.0, 150.0, 65.0)
        
        with st.expander("詳細設定", expanded=False):
            gender = st.radio("性別", ["Male", "Female"], horizontal=True)
            age = st.number_input("年齢", 10, 100, 30)
            height = st.number_input("身長 (cm)", 100.0, 250.0, 170.0)
            act_idx = st.selectbox("活動レベル", [0,1,2,3], format_func=lambda x: ["x1.2 (低)", "x1.375 (中)", "x1.55 (高)", "x1.725 (激)"][x])
            act_val = [1.2, 1.375, 1.55, 1.725][act_idx]
            goal_idx = st.selectbox("目的", [0,1,2], format_func=lambda x: ["維持", "減量(-500)", "増量(+300)"][x])
            goal_val = [0, -500, 300][goal_idx]
        
        p_ratio = st.slider("タンパク質目標 (体重 x ?)", 1.0, 3.0, 1.6)

        st.divider()
        df_all = get_db("SELECT * FROM meals")
        if not df_all.empty:
            csv = df_all.to_csv(index=False).encode('utf-8')
            st.download_button("💾 CSVダウンロード", csv, "diet_log.csv", "text/csv")

    # --- 目標計算 ---
    if gender == 'Male':
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * current_weight) + (6.25 * height) - (5 * age) - 161
    
    target_kcal = int(bmr * act_val + goal_val)
    target_p = int(current_weight * p_ratio)

    # --- 今日のデータ ---
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
            <div class="metric-label">Remaining Cal (目標: {target_kcal})</div>
            <div class="metric-value">{int(rem_cal)}</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(sum_cal / target_kcal, 1.0) if target_kcal > 0 else 0)
    
    with c2:
        rem_p = target_p - sum_p
        p_color = "green" if rem_p <= 0 else "#d9534f"
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-label">Remaining Protein (目標: {target_p}g)</div>
            <div class="metric-value" style="color: {p_color};">{max(0, int(rem_p))} g</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(sum_p / target_p, 1.0) if target_p > 0 else 0)

    # --- タブ ---
    tab1, tab2, tab3, tab4 = st.tabs(["📝 記録", "⭐️ 定番", "📊 分析", "🗑️ 履歴"])

    # Tab 1: AI記録
    with tab1:
        if st.session_state['draft_data'] is None:
            in_mode = st.radio("入力モード", ["文字", "写真"], horizontal=True)
            
            if in_mode == "文字":
                txt_in = st.text_input("食事内容", placeholder="例: 牛丼と卵")
                if st.button("AI解析", type="primary") and txt_in:
                    with st.spinner("AIが考え中..."):
                        res = analyze_food(txt_in)
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
            else:
                img_in = st.file_uploader("写真をアップロード", type=["jpg", "png", "jpeg"])
                if img_in and st.button("画像解析", type="primary"):
                    with st.spinner("AIが考え中..."):
                        image = Image.open(img_in)
                        res = analyze_food(image)
                        if res:
                            st.session_state['draft_data'] = res
                            st.rerun()
        else:
            st.info("内容を確認して保存してください")
            with st.form("edit_form"):
                edited_items = []
                for i, item in enumerate(st.session_state['draft_data']):
                    st.markdown(f"**品目 {i+1}**")
                    cols = st.columns([3, 1, 1, 1, 1])
                    n = cols[0].text_input("名前", item['food_name'], key=f"n{i}")
                    k = cols[1].number_input("kcal", 0, 9999, int(item['calories']), key=f"k{i}")
                    p = cols[2].number_input("P", 0, 999, int(item['protein']), key=f"p{i}")
                    f = cols[3].number_input("F", 0, 999, int(item['fat']), key=f"f{i}")
                    c = cols[4].number_input("C", 0, 999, int(item['carbs']), key=f"c{i}")
                    edited_items.append({"name":n, "kcal":k, "p":p, "f":f, "c":c})
                
                b1, b2 = st.columns(2)
                if b1.form_submit_button("✅ 保存", type="primary"):
                    today = datetime.now().strftime('%Y-%m-%d')
                    for item in edited_items:
                        execute_db("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)",
                                   (today, item['name'], item['kcal'], item['p'], item['f'], item['c']))
                    st.session_state['draft_data'] = None
                    st.success("保存しました")
                    st.rerun()
                
                if b2.form_submit_button("❌ キャンセル"):
                    st.session_state['draft_data'] = None
                    st.rerun()

    # Tab 2: マイメニュー
    with tab2:
        favs = get_db("SELECT * FROM favorites")
        if not favs.empty:
            sel_fav = st.selectbox("My Menu", favs['name'])
            target = favs[favs['name'] == sel_fav].iloc[0]
            st.success(f"{target['name']} : {int(target['kcal'])}kcal")
            if st.button("これ食べた！ (追加)"):
                today = datetime.now().strftime('%Y-%m-%d')
                execute_db("INSERT INTO meals (date, name, kcal, p, f, c) VALUES (?, ?, ?, ?, ?, ?)",
                           (today, target['name'], target['kcal'], target['p'], target['f'], target['c']))
                st.success("追加しました")
                time.sleep(1)
                st.rerun()
        else:
            st.info("履歴タブの「⭐️」ボタンで登録できます。")

    # Tab 3: 分析
    with tab3:
        st.subheader("今日のバランス")
        if sum_cal > 0:
            fig, ax = plt.subplots(figsize=(4, 4))
            ax.pie([sum_p, sum_f, sum_c], labels=['Protein', 'Fat', 'Carbs'], 
                   colors=['#ff9999', '#66b3ff', '#99ff99'], autopct='%1.1f%%', startangle=90)
            st.pyplot(fig)
        else:
            st.write("データがありません")
        
        st.divider()
        st.subheader("週間推移")
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

    # Tab 4: 履歴
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
                        st.success("登録！")
                    
                    if bc2.button("🗑️", key=f"del_{r['id']}"):
                        execute_db("DELETE FROM meals WHERE id=?", (r['id'],))
                        st.rerun()
                    st.divider()
        else:
            st.info("今日の記録はありません")

if __name__ == "__main__":
    main()
