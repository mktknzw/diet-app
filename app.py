import streamlit as st
import google.generativeai as genai

# ==========================================
# 👇 ここにAPIキーを入れてください
# ==========================================
API_KEY = "ここにAPIキーを貼り付ける" 
# ==========================================

genai.configure(api_key=API_KEY)

st.title("🔍 モデル名 捜索ツール (修正版)")
st.write("あなたのAPIキーで使えるAIモデルを探しています...")

try:
    # 【修正ポイント】ジェネレータを強制的にリストに変換してエラーを防ぐ
    all_models = list(genai.list_models())
    
    available_models = []
    
    st.write("---")
    st.subheader("📋 取得できたリスト")
    
    for m in all_models:
        # 名前を表示
        st.text(f"・{m.name}")
        
        # 「文章生成(generateContent)」に対応しているかチェック
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)

    # 結果発表
    st.write("---")
    if available_models:
        # 最新のモデルを優先的に探すロジック
        recommended = available_models[0]
        # もし gemini-1.5-flash があればそれを優先
        for m in available_models:
            if "1.5-flash" in m:
                recommended = m
                break
        
        st.success(f"🎉 発見！この名前を使ってください 👉 {recommended}")
        
        # テスト通信
        try:
            st.info(f"「{recommended}」でテスト通信中...")
            model = genai.GenerativeModel(recommended)
            response = model.generate_content("こんにちは")
            st.write(f"AIからの返事: {response.text}")
        except Exception as e:
            st.error(f"テスト通信エラー: {e}")
            
    else:
        st.error("😱 使えるモデルが1つも見つかりませんでした。APIキーが無料枠の上限に達している可能性があります。")

except Exception as e:
    st.error(f"一覧の取得に失敗しました: {e}")

