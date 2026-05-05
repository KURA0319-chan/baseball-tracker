import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
import time
import random

# ==========================================
# 專屬設定 & 規定門檻設定 (MLB 標準)
# ==========================================
SERVICE_ACCOUNT_FILE = 'baseball.json'
SHEET_NAME = '棒球數據資料庫'
TEAMS = ["LAA", "LAD"]

QUALIFY_PA = 31   
QUALIFY_IP = 10.0 

SEASONS = [f"Season {i}" for i in range(1, 11)]
GAME_STAGES = [f"例行賽 G{i}" for i in range(1, 11)] + [f"世界大賽 G{i}" for i in range(1, 8)]

bat_keys = ['pa_b', 'ab_b', 'h_b', 'rbi_b', 'run_b', 'hr_b', 'bb_b', 'so_b', 'sb_b', 'tb2_b', 'tb3_b']
pitch_keys = ['ip_f', 'ip_o', 'bf_p', 'so_p', 'bb_p', 'r_p', 'er_p', 'hp_p', 'hrp_p', 'np_p']

if 'clear_bat' not in st.session_state: st.session_state.clear_bat = False
if 'clear_pitch' not in st.session_state: st.session_state.clear_pitch = False

if st.session_state.clear_bat:
    for key in bat_keys: st.session_state[key] = 0
    st.session_state.clear_bat = False 

if st.session_state.clear_pitch:
    for key in pitch_keys: st.session_state[key] = 0
    st.session_state.clear_pitch = False 

@st.cache_resource
def get_sheet():
    try:
        # 1. 如果在雲端 (有設定 secrets)，就從雲端保險箱讀取密鑰
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            gc = gspread.service_account_from_dict(creds_dict)
            return gc.open(SHEET_NAME)
        # 2. 如果在你自己電腦上，就照舊讀取實體檔案
        else:
            gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
            return gc.open(SHEET_NAME)
    except Exception as e:
        st.error(f"連線失敗：{e}")
        return None

@st.cache_data(ttl=15)
def get_raw_records(sheet_name):
    sh = get_sheet()
    if not sh: return []
    try: return sh.worksheet(sheet_name).get_all_values()[1:]
    except: return []

@st.cache_data(ttl=60)
def get_player_list(sheet_name):
    records = get_raw_records(sheet_name)
    players_dict = {team: set() for team in TEAMS}
    for row in records:
        if len(row) > 3 and row[2] in players_dict: players_dict[row[2]].add(row[3])
    return {k: sorted(list(v)) for k, v in players_dict.items()}

def check_duplicate(sheet_name, target_stage, team, player):
    records = get_raw_records(sheet_name)
    for row in records:
        if len(row) > 3 and row[1] == target_stage and row[2] == team and row[3] == player:
            return True
    return False

def get_career_stats():
    records_b = get_raw_records("打擊單場紀錄")
    records_p = get_raw_records("投手單場紀錄")
    df_b_agg = pd.DataFrame()
    df_p_agg = pd.DataFrame()
    error_msg = ""
    
    try:
        if records_b:
            df_b = pd.DataFrame(records_b, columns=['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘'])
            num_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            for col in num_cols: df_b[col] = pd.to_numeric(df_b[col], errors='coerce').fillna(0)
            
            total_pa = df_b['打席'].sum()
            if total_pa > 0:
                lg_obp = (df_b['安打'].sum() + df_b['四壞球'].sum()) / total_pa
                lg_slg = ((df_b['安打'].sum() - df_b['二壘安打'].sum() - df_b['三壘安打'].sum() - df_b['全壘打'].sum()) + 2*df_b['二壘安打'].sum() + 3*df_b['三壘安打'].sum() + 4*df_b['全壘打'].sum()) / df_b['打數'].sum() if df_b['打數'].sum() > 0 else 0
            else: lg_obp, lg_slg = 0, 0

            df_b_agg = df_b.groupby(['球隊', '球員姓名'])[num_cols].sum().reset_index()
            df_b_agg['AVG'] = (df_b_agg['安打'] / df_b_agg['打數'].replace(0, 1)).fillna(0)
            df_b_agg['OBP'] = ((df_b_agg['安打'] + df_b_agg['四壞球']) / df_b_agg['打席'].replace(0, 1)).fillna(0)
            df_b_agg['SLG'] = ((df_b_agg['安打'] - df_b_agg['二壘安打'] - df_b_agg['三壘安打'] - df_b_agg['全壘打']) + 2*df_b_agg['二壘安打'] + 3*df_b_agg['三壘安打'] + 4*df_b_agg['全壘打']) / df_b_agg['打數'].replace(0, 1)
            df_b_agg['ISO'] = df_b_agg['SLG'] - df_b_agg['AVG']
            df_b_agg['BABIP'] = ((df_b_agg['安打'] - df_b_agg['全壘打']) / (df_b_agg['打數'] - df_b_agg['三振'] - df_b_agg['全壘打']).replace(0, 1)).fillna(0)
            df_b_agg['BB%'] = (df_b_agg['四壞球'] / df_b_agg['打席'].replace(0, 1)) * 100
            df_b_agg['K%'] = (df_b_agg['三振'] / df_b_agg['打席'].replace(0, 1)) * 100
            def calc_ops_plus(row):
                if lg_obp > 0 and lg_slg > 0 and row['打席'] > 0: return 100 * ((row['OBP'] / lg_obp) + (row['SLG'] / lg_slg) - 1)
                return 0.0
            # ✨ 將 OPS+ 強制轉為整數 (去除小數點) ✨
            df_b_agg['OPS+'] = df_b_agg.apply(calc_ops_plus, axis=1).round(0).astype(int)
            st.session_state.df_b_raw = df_b 
            
    except Exception as e: error_msg += f"打擊計算異常: {e}\n"

    try:
        if records_p:
            df_p = pd.DataFrame(records_p, columns=['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分'])
            p_cols = ['局數(整數)', '局數(出局數)', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            for col in p_cols: df_p[col] = pd.to_numeric(df_p[col], errors='coerce').fillna(0)
                
            df_p_agg = df_p.groupby(['球隊', '投手姓名'])[p_cols].sum().reset_index()
            
            stats_counts = df_p.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
            for col in ['勝', '敗', '中繼', '救援']:
                if col not in stats_counts.columns: stats_counts[col] = 0
            df_p_agg = pd.merge(df_p_agg, stats_counts, on=['球隊', '投手姓名'], how='left')
            df_p_agg.rename(columns={'勝': '勝投', '救援': '救援成功', '中繼': '中繼成功'}, inplace=True)
            
            total_outs = (df_p_agg['局數(整數)'] * 3) + df_p_agg['局數(出局數)']
            ip_calc = total_outs / 3.0
            df_p_agg['實際局數'] = ip_calc
            df_p_agg['ERA'] = ((df_p_agg['自責分'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            df_p_agg['FIP'] = (((13 * df_p_agg['被全壘打']) + (3 * df_p_agg['四壞球']) - (2 * df_p_agg['奪三振'])) / ip_calc.replace(0, 1) + 3.10).fillna(0)
            df_p_agg['K/9'] = (df_p_agg['奪三振'] * 9) / ip_calc.replace(0, 1)
            df_p_agg['BB/9'] = (df_p_agg['四壞球'] * 9) / ip_calc.replace(0, 1)
            df_p_agg['HR/9'] = (df_p_agg['被全壘打'] * 9) / ip_calc.replace(0, 1)
            df_p_agg['K/BB'] = (df_p_agg['奪三振'] / df_p_agg['四壞球'].replace(0, 1)).fillna(df_p_agg['奪三振'])
            
            st.session_state.df_p_raw = df_p
            
    except Exception as e: error_msg += f"投球計算異常: {e}"
        
    return df_b_agg, df_p_agg, error_msg

# ==========================================
# 網頁介面設計
# ==========================================
st.set_page_config(page_title="LAA vs LAD 數據中心", page_icon="⚾", layout="wide")
st.title("⚾ 洛杉磯雙雄數據追蹤系統 V26")

tab1, tab2, tab3, tab4 = st.tabs(["⚾ 打擊單場輸入", "🥎 投球單場輸入", "🏆 累積數據總表", "📋 賽前戰情室"])

# --- 分頁 1：打擊輸入 ---
with tab1:
    st.subheader("輸入今日打擊表現")
    col_s_b, col_g_b, col_t_b, col_p_b = st.columns([1, 1.2, 1, 1.5])
    with col_s_b: selected_season_b = st.selectbox("賽季", SEASONS, key="season_b")
    with col_g_b: selected_game_b = st.selectbox("賽事階段", GAME_STAGES, key="game_b")
    with col_t_b: team_b = st.selectbox("所屬球隊", TEAMS, key="team_b")
    
    season_num_b = selected_season_b.split(" ")[1]
    full_stage_b = f"[S{season_num_b}] {selected_game_b}"
    
    records_b = get_raw_records("打擊單場紀錄")
    inputted_batters = [row[3] for row in records_b if len(row) > 3 and row[1] == full_stage_b and row[2] == team_b]
    cached_players_b = get_player_list("打擊單場紀錄")
    all_team_batters = cached_players_b.get(team_b, [])
    available_batters = [p for p in all_team_batters if p not in inputted_batters]

    with col_p_b:
        options_b = ["➕ 手動輸入新球員..."] + available_batters
        selected_p_b = st.selectbox("選擇球員", options_b, key="sel_b")
        if selected_p_b == "➕ 手動輸入新球員...": player_b = st.text_input("輸入姓名", key="txt_b")
        else: player_b = selected_p_b
    
    st.markdown("---")
    st.info("💡 提醒：【安打】欄位請填寫包含長打在內的「總安打數」。")
    c1, c2, c3, c4 = st.columns(4)
    pa = c1.number_input("打席", min_value=0, step=1, key="pa_b")
    ab = c2.number_input("打數", min_value=0, step=1, key="ab_b")
    h = c3.number_input("安打", min_value=0, step=1, key="h_b")
    rbi = c4.number_input("打點", min_value=0, step=1, key="rbi_b")
    c5, c6, c7, c8 = st.columns(4)
    run = c5.number_input("得分", min_value=0, step=1, key="run_b")
    hr = c6.number_input("全壘打", min_value=0, step=1, key="hr_b")
    bb = c7.number_input("四壞球", min_value=0, step=1, key="bb_b")
    so = c8.number_input("三振", min_value=0, step=1, key="so_b")
    c9, c10, c11, c12 = st.columns(4)
    sb = c9.number_input("盜壘", min_value=0, step=1, key="sb_b")
    tb2 = c10.number_input("二壘安打", min_value=0, step=1, key="tb2_b")
    tb3 = c11.number_input("三壘安打", min_value=0, step=1, key="tb3_b")
    c12.empty()

    if st.button("⚾ 儲存本場打擊數據", type="primary", use_container_width=True, key="btn_submit_b"):
        if player_b == "": st.warning("請填寫球員姓名！")
        elif ab > pa: st.error("⚠️ 邏輯錯誤：打數 (AB) 不可能大於 打席 (PA)！")
        elif h > ab: st.error("⚠️ 邏輯錯誤：安打數 (H) 不可能大於 打數 (AB)！")
        elif (tb2 + tb3 + hr) > h: st.error("⚠️ 邏輯錯誤：長打總和 不能大於 總安打數！")
        else:
            sh = get_sheet()
            if sh:
                try:
                    ws = sh.worksheet("打擊單場紀錄")
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ws.append_row([now, full_stage_b, team_b, player_b, pa, ab, h, tb2, tb3, hr, rbi, run, bb, so, sb])
                    st.success(f"✅ 成功儲存 {player_b} 的表現！")
                    get_raw_records.clear()
                    time.sleep(1)
                    st.session_state.clear_bat = True
                    st.rerun() 
                except Exception as e: st.error(f"寫入失敗：{e}")

# --- 分頁 2：投球輸入 ---
with tab2:
    st.subheader("輸入今日投球表現")
    col_s_p, col_g_p, col_t_p, col_p_p, col_res_p = st.columns([1, 1.2, 1, 1.5, 0.8])
    with col_s_p: selected_season_p = st.selectbox("賽季", SEASONS, key="season_p")
    with col_g_p: selected_game_p = st.selectbox("賽事階段", GAME_STAGES, key="game_p")
    with col_t_p: team_p = st.selectbox("所屬球隊", TEAMS, key="team_p")
    
    season_num_p = selected_season_p.split(" ")[1]
    full_stage_p = f"[S{season_num_p}] {selected_game_p}"

    records_p = get_raw_records("投手單場紀錄")
    
    # 找出現有紀錄中，已經被用掉的投手、以及被標記的「勝敗紀錄」
    inputted_pitchers = []
    used_statuses = []
    for row in records_p:
        if len(row) > 4 and row[1] == full_stage_p:
            if row[2] == team_p: inputted_pitchers.append(row[3])
            # 一場比賽無論哪隊，總共只會有一個勝投、一個敗投 (為了系統嚴謹，我們跨隊檢查)
            used_statuses.append(row[4])

    cached_players_p = get_player_list("投手單場紀錄")
    all_team_pitchers = cached_players_p.get(team_p, [])
    available_pitchers = [p for p in all_team_pitchers if p not in inputted_pitchers]

    # ✨ 動態勝敗選單防呆：已輸入過勝/敗/救援，該場比賽就不再顯示該選項 ✨
    p_res_options = ["無", "中繼"]
    if "勝" not in used_statuses: p_res_options.insert(1, "勝")
    if "敗" not in used_statuses: p_res_options.insert(2, "敗")
    if "救援" not in used_statuses: p_res_options.append("救援")

    with col_p_p:
        options_p = ["➕ 手動輸入新投手..."] + available_pitchers
        selected_p_p = st.selectbox("選擇投手", options_p, key="sel_p")
        if selected_p_p == "➕ 手動輸入新投手...": player_p = st.text_input("輸入姓名", key="txt_p")
        else: player_p = selected_p_p
    with col_res_p: 
        p_res = st.selectbox("勝敗紀錄", p_res_options, key="p_res", help="同場比賽的勝/敗/救援若已被其他投手登錄，選項會自動隱藏！")
        
    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    ip_full = c1.number_input("局數(整數)", min_value=0, step=1, key="ip_f")
    ip_outs = c2.number_input("局數(出局數)", min_value=0, max_value=2, step=1, key="ip_o")
    bf = c3.number_input("打者數", min_value=0, step=1, key="bf_p")
    so_p = c4.number_input("奪三振", min_value=0, step=1, key="so_p")
    c5, c6, c7, c8 = st.columns(4)
    bb_p = c5.number_input("四壞球", min_value=0, step=1, key="bb_p")
    r = c6.number_input("失分", min_value=0, step=1, key="r_p")
    er = c7.number_input("自責分", min_value=0, step=1, key="er_p")
    h_p = c8.number_input("被安打", min_value=0, step=1, key="hp_p")
    c9, c10, c11, c12 = st.columns(4)
    hr_p = c9.number_input("被全壘打", min_value=0, step=1, key="hrp_p")
    np_pitch = c10.number_input("投球數", min_value=0, step=1, key="np_p")
    c11.empty()
    c12.empty()

    if st.button("🥎 儲存本場投球數據", type="primary", use_container_width=True, key="btn_submit_p"):
        if player_p == "": st.warning("請填寫投手姓名！")
        elif so_p > bf: st.error("⚠️ 邏輯錯誤：奪三振 不可能大於 打者數！")
        elif h_p > bf: st.error("⚠️ 邏輯錯誤：被安打 不可能大於 打者數！")
        elif hr_p > h_p: st.error("⚠️ 邏輯錯誤：被全壘打 不可能大於 被安打總數！")
        elif er > r: st.error("⚠️ 邏輯錯誤：自責分 不可能大於 總失分！")
        else:
            sh = get_sheet()
            if sh:
                try:
                    ws = sh.worksheet("投手單場紀錄")
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ws.append_row([now, full_stage_p, team_p, player_p, p_res, ip_full, ip_outs, bf, np_pitch, h_p, hr_p, bb_p, so_p, r, er])
                    st.success(f"✅ 成功儲存！")
                    get_raw_records.clear()
                    time.sleep(1)
                    st.session_state.clear_pitch = True
                    st.rerun() 
                except Exception as e: st.error(f"寫入失敗：{e}")

# ==========================================
# --- 分頁 3：無刪減完全版累積總表 + 真實排序 + 數據小教室 ---
# ==========================================
with tab3:
    st.subheader("🏆 累積進階數據排行榜")
    
    # ✨ 棒球進階數據小教室 ✨
    with st.expander("💡 棒球進階數據 (Sabermetrics) 小教室 (點我展開)"):
        st.markdown("""
        * **OPS+ (標準化整體攻擊指數)：** 衡量打者整體破壞力的終極指標。**100 為全聯盟平均**。若 OPS+ 為 150，代表火力比平均高出 50%。
        * **FIP (獨立防禦率)：** 剔除隊友守備與運氣成分，只看投手「三振、保送、被全壘打」等自己能控制的能力。
          * 📉 **FIP < ERA (獨立防禦率比防禦率低)：** 投手其實投得很棒！但可能運氣極差或隊友失誤太多，真實實力被低估（俗稱問天或悲情投手）。
          * 📈 **FIP > ERA (獨立防禦率比防禦率高)：** 投手帳面成績好看，但很多出局數是靠隊友美技守備或強運，未來隨時可能「校正回歸」（強運投手）。
        * **ISO (純長打率)：** `長打率(SLG) - 打擊率(AVG)`。衡量打者的純長打能力。數值大於 **0.200** 就是貨真價實的重砲手。
        * **BABIP (場內安打率)：** 衡量把球打進場內後變成安打的機率。一般落在 0.300 左右。異常高代表近期極度強運；異常低則是地獄倒楣鬼。
        * **WHIP (每局被上壘率)：** 投手每局讓幾名打者上壘。**1.20 以下**就算是非常優秀的投手。
        """)

    st.info("💡 **小技巧：** 點擊表格的任意標題，就可以自由從大排到小喔！")
    
    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 2.5])
    with col_f1:
        if st.button("🔄 載入最新數據", type="primary"):
            get_raw_records.clear()
            st.rerun()
            
    with col_f2:
        filter_season = st.selectbox("篩選賽季", ["十年總成績"] + SEASONS, key="f_season")
    with col_f3:
        if filter_season == "十年總成績":
            filter_game = st.selectbox("篩選比賽階段", ["不限 (看全部)"], disabled=True, key="f_game")
            target_stage = "十年總成績 (全賽季累積)"
        else:
            filter_game = st.selectbox("篩選比賽階段", ["看整季", "例行賽總和", "世界大賽總和"] + GAME_STAGES, key="f_game")
            s_num = filter_season.split(" ")[1]
            if filter_game == "看整季": target_stage = f"[S{s_num}]"
            elif filter_game == "例行賽總和": target_stage = f"[S{s_num}] 例行賽"
            elif filter_game == "世界大賽總和": target_stage = f"[S{s_num}] 世界大賽"
            else: target_stage = f"[S{s_num}] {filter_game}"

    records_b = get_raw_records("打擊單場紀錄")
    records_p = get_raw_records("投手單場紀錄")
    
    st.markdown("### ⚾ 打擊成績")
    if records_b:
        df_b = pd.DataFrame(records_b, columns=['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘'])
        if target_stage != "十年總成績 (全賽季累積)" and '賽事階段' in df_b.columns:
            df_b = df_b[df_b['賽事階段'].astype(str).str.contains(target_stage, regex=False)]
        
        if df_b.empty: st.info("查無符合條件的打擊紀錄。")
        else:
            num_cols_b = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            for col in num_cols_b: df_b[col] = pd.to_numeric(df_b[col], errors='coerce').fillna(0)
            
            agg_b = df_b.groupby(['球隊', '球員姓名']).agg({
                '打席': 'sum', '打數': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', 
                '全壘打': 'sum', '打點': 'sum', '得分': 'sum', '四壞球': 'sum', '三振': 'sum', '盜壘': 'sum',
                '賽事階段': 'count' 
            }).reset_index().rename(columns={'賽事階段': '出賽數'})
            
            agg_b['一壘安打'] = agg_b['安打'] - agg_b['二壘安打'] - agg_b['三壘安打'] - agg_b['全壘打']
            agg_b['AVG'] = (agg_b['安打'] / agg_b['打數']).fillna(0)
            agg_b['OBP'] = ((agg_b['安打'] + agg_b['四壞球']) / agg_b['打席']).fillna(0)
            agg_b['SLG'] = ((agg_b['一壘安打'] + 2*agg_b['二壘安打'] + 3*agg_b['三壘安打'] + 4*agg_b['全壘打']) / agg_b['打數']).fillna(0)
            agg_b['OPS'] = agg_b['OBP'] + agg_b['SLG']
            agg_b['ISO'] = agg_b['SLG'] - agg_b['AVG']
            agg_b['BABIP'] = ((agg_b['安打'] - agg_b['全壘打']) / (agg_b['打數'] - agg_b['三振'] - agg_b['全壘打']).replace(0, 1)).fillna(0)
            agg_b['BB%'] = (agg_b['四壞球'] / agg_b['打席'] * 100).fillna(0)
            agg_b['K%'] = (agg_b['三振'] / agg_b['打席'] * 100).fillna(0)
            
            total_h = df_b['安打'].sum()
            total_bb = df_b['四壞球'].sum()
            total_pa = df_b['打席'].sum()
            total_ab = df_b['打數'].sum()
            total_tb = (total_h - df_b['二壘安打'].sum() - df_b['三壘安打'].sum() - df_b['全壘打'].sum()) + 2*df_b['二壘安打'].sum() + 3*df_b['三壘安打'].sum() + 4*df_b['全壘打'].sum()
            lg_obp = (total_h + total_bb) / total_pa if total_pa > 0 else 0.0
            lg_slg = total_tb / total_ab if total_ab > 0 else 0.0
            def calc_ops_plus(row):
                if lg_obp > 0 and lg_slg > 0 and row['打席'] > 0: return 100 * ((row['OBP'] / lg_obp) + (row['SLG'] / lg_slg) - 1)
                return 0.0
            # ✨ OPS+ 轉為整數 ✨
            agg_b['OPS+'] = agg_b.apply(calc_ops_plus, axis=1).round(0).astype(int)

            qual_b = agg_b[agg_b['打席'] >= QUALIFY_PA]
            avg_pool = qual_b if not qual_b.empty else agg_b
            
            if not agg_b.empty:
                st.markdown(f"#### 👑 聯盟打擊領先者 (規定打席: {QUALIFY_PA})")
                avg_leader = avg_pool.loc[avg_pool['AVG'].astype(float).idxmax()]
                h_leader = agg_b.loc[agg_b['安打'].idxmax()]
                hr_leader = agg_b.loc[agg_b['全壘打'].idxmax()]
                rbi_leader = agg_b.loc[agg_b['打點'].idxmax()]
                sb_leader = agg_b.loc[agg_b['盜壘'].idxmax()]
                
                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                lc1.metric(f"打擊王", f"{float(avg_leader['AVG']):.3f}", f"{avg_leader['球員姓名']}")
                lc2.metric(f"安打王", f"{int(h_leader['安打'])} H", f"{h_leader['球員姓名']}")
                lc3.metric(f"全壘打王", f"{int(hr_leader['全壘打'])} HR", f"{hr_leader['球員姓名']}")
                lc4.metric(f"打點王", f"{int(rbi_leader['打點'])} RBI", f"{rbi_leader['球員姓名']}")
                lc5.metric(f"盜壘王", f"{int(sb_leader['盜壘'])} SB", f"{sb_leader['球員姓名']}")
            
            st.markdown("---")
            lg_ops = lg_obp + lg_slg
            lg_avg = total_h / total_ab if total_ab > 0 else 0.0
            summary_b = []
            summary_b.append({'隊伍': '🌎 全聯盟平均', 'OPS+': 100, 'OPS': lg_ops, 'AVG': lg_avg, 'OBP': lg_obp, 'SLG': lg_slg})
            for team in TEAMS:
                t_df = df_b[df_b['球隊'] == team]
                if not t_df.empty:
                    t_pa = t_df['打席'].sum()
                    t_ab = t_df['打數'].sum()
                    t_h = t_df['安打'].sum()
                    t_bb = t_df['四壞球'].sum()
                    t_tb = (t_h - t_df['二壘安打'].sum() - t_df['三壘安打'].sum() - t_df['全壘打'].sum()) + 2*t_df['二壘安打'].sum() + 3*t_df['三壘安打'].sum() + 4*t_df['全壘打'].sum()
                    t_obp = (t_h + t_bb) / t_pa if t_pa > 0 else 0
                    t_slg = t_tb / t_ab if t_ab > 0 else 0
                    t_ops = t_obp + t_slg
                    t_avg = t_h / t_ab if t_ab > 0 else 0
                    t_ops_plus = 100 * ((t_obp / lg_obp) + (t_slg / lg_slg) - 1) if (lg_obp>0 and lg_slg>0 and t_pa>0) else 0
                    summary_b.append({'隊伍': f"🔴 {team}" if team == "LAA" else f"🔵 {team}", 'OPS+': int(round(t_ops_plus, 0)), 'OPS': t_ops, 'AVG': t_avg, 'OBP': t_obp, 'SLG': t_slg})
            
            st.markdown("#### ⚖️ 團隊火力對比")
            df_sum_b = pd.DataFrame(summary_b)
            st.dataframe(df_sum_b.style.format({'OPS': '{:.3f}', 'AVG': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}'}), use_container_width=True, hide_index=True)

            show_cols_b = ['球隊', '球員姓名', '出賽數', '打席', '打數', 'OPS+', 'OPS', 'AVG', 'OBP', 'SLG', 'ISO', 'BABIP', 'BB%', 'K%', '全壘打', '打點', '盜壘']
            show_df = agg_b[show_cols_b].copy()
            show_df = show_df.sort_values(by=['球隊', 'OPS+'], ascending=[True, False])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人打擊榜")
                team_df = show_df[show_df['球隊'] == team]
                if not team_df.empty: 
                    styled_df = team_df.drop(columns=['球隊']).style.format({
                        'OPS': '{:.3f}', 'AVG': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'ISO': '{:.3f}', 'BABIP': '{:.3f}',
                        'BB%': '{:.1f}%', 'K%': '{:.1f}%'
                    })
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else: st.info("目前沒有打擊紀錄可以顯示！")

    st.markdown("---")
    
    st.markdown("### 🥎 投球成績")
    if records_p:
        df_p = pd.DataFrame(records_p, columns=['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分'])
        if target_stage != "十年總成績 (全賽季累積)" and '賽事階段' in df_p.columns:
                df_p = df_p[df_p['賽事階段'].astype(str).str.contains(target_stage, regex=False)]
        
        if df_p.empty: st.info("查無符合條件的投球紀錄。")
        else:
            p_cols = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            for col in p_cols: df_p[col] = pd.to_numeric(df_p[col], errors='coerce').fillna(0)
            
            agg_p = df_p.groupby(['球隊', '投手姓名'])[p_cols].sum().reset_index()
            stats_counts = df_p.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
            for col in ['勝', '敗', '中繼', '救援']:
                if col not in stats_counts.columns: stats_counts[col] = 0
            agg_p = pd.merge(agg_p, stats_counts, on=['球隊', '投手姓名'], how='left')
            agg_p.rename(columns={'勝': '勝投', '救援': '救援成功', '中繼': '中繼成功'}, inplace=True)
            
            total_outs = (agg_p['局數(整數)'] * 3) + agg_p['局數(出局數)']
            ip_calc = total_outs / 3.0
            agg_p['實際局數'] = ip_calc
            agg_p['總局數'] = (total_outs // 3) + (total_outs % 3) / 10.0
            
            agg_p['ERA'] = ((agg_p['自責分'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['WHIP'] = ((agg_p['被安打'] + agg_p['四壞球']) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['K/9'] = ((agg_p['奪三振'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['BB/9'] = ((agg_p['四壞球'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['HR/9'] = ((agg_p['被全壘打'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['K/BB'] = (agg_p['奪三振'] / agg_p['四壞球'].replace(0, 1)).fillna(agg_p['奪三振'])
            agg_p['FIP'] = (((13 * agg_p['被全壘打']) + (3 * agg_p['四壞球']) - (2 * agg_p['奪三振'])) / ip_calc.replace(0, 1) + 3.10).fillna(0)
            
            qual_p = agg_p[agg_p['實際局數'] >= QUALIFY_IP]
            era_pool = qual_p if not qual_p.empty else agg_p
            
            if not agg_p.empty:
                st.markdown(f"#### 👑 聯盟投球領先者 (規定局數: {QUALIFY_IP})")
                era_leader = era_pool.loc[era_pool['ERA'].astype(float).idxmin()]
                w_leader = agg_p.loc[agg_p['勝投'].idxmax()]
                sv_leader = agg_p.loc[agg_p['救援成功'].idxmax()]
                hld_leader = agg_p.loc[agg_p['中繼成功'].idxmax()]
                so_leader = agg_p.loc[agg_p['奪三振'].idxmax()]
                
                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                lc1.metric(f"防禦率王", f"{float(era_leader['ERA']):.2f}", f"{era_leader['投手姓名']}")
                lc2.metric(f"勝投王", f"{int(w_leader['勝投'])} W", f"{w_leader['投手姓名']}")
                lc3.metric(f"救援王", f"{int(sv_leader['救援成功'])} SV", f"{sv_leader['投手姓名']}")
                lc4.metric(f"中繼王", f"{int(hld_leader['中繼成功'])} HLD", f"{hld_leader['投手姓名']}")
                lc5.metric(f"三振王", f"{int(so_leader['奪三振'])} K", f"{so_leader['投手姓名']}")

            st.markdown("---")
            lg_outs = (df_p['局數(整數)'].sum() * 3) + df_p['局數(出局數)'].sum()
            lg_ip = lg_outs / 3.0
            lg_er = df_p['自責分'].sum()
            lg_hr = df_p['被全壘打'].sum()
            lg_bb = df_p['四壞球'].sum()
            lg_so = df_p['奪三振'].sum()
            lg_h = df_p['被安打'].sum()
            lg_era = (lg_er * 9) / lg_ip if lg_ip > 0 else 0
            lg_whip = (lg_h + lg_bb) / lg_ip if lg_ip > 0 else 0
            lg_fip = (((13 * lg_hr) + (3 * lg_bb) - (2 * lg_so)) / lg_ip + 3.10) if lg_ip > 0 else 0

            summary_p = []
            summary_p.append({'隊伍': '🌎 全聯盟平均', 'ERA': lg_era, 'FIP': lg_fip, 'WHIP': lg_whip, 'K/9': (lg_so * 9 / lg_ip) if lg_ip > 0 else 0, 'BB/9': (lg_bb * 9 / lg_ip) if lg_ip > 0 else 0})
            for team in TEAMS:
                t_df = df_p[df_p['球隊'] == team]
                if not t_df.empty:
                    t_outs = (t_df['局數(整數)'].sum() * 3) + t_df['局數(出局數)'].sum()
                    t_ip = t_outs / 3.0
                    t_er = t_df['自責分'].sum()
                    t_hr = t_df['被全壘打'].sum()
                    t_bb = t_df['四壞球'].sum()
                    t_so = t_df['奪三振'].sum()
                    t_h = t_df['被安打'].sum()
                    t_era = (t_er * 9) / t_ip if t_ip > 0 else 0
                    t_whip = (t_h + t_bb) / t_ip if t_ip > 0 else 0
                    t_fip = (((13 * t_hr) + (3 * t_bb) - (2 * t_so)) / t_ip + 3.10) if t_ip > 0 else 0
                    summary_p.append({'隊伍': f"🔴 {team}" if team == "LAA" else f"🔵 {team}", 'ERA': t_era, 'FIP': t_fip, 'WHIP': t_whip, 'K/9': (t_so * 9 / t_ip) if t_ip > 0 else 0, 'BB/9': (t_bb * 9 / t_ip) if t_ip > 0 else 0})
                    
            st.markdown("#### ⚖️ 團隊防線對比")
            df_sum_p = pd.DataFrame(summary_p)
            st.dataframe(df_sum_p.style.format({'ERA': '{:.2f}', 'FIP': '{:.2f}', 'WHIP': '{:.2f}', 'K/9': '{:.2f}', 'BB/9': '{:.2f}'}), use_container_width=True, hide_index=True)
            
            show_cols_p = ['球隊', '投手姓名', '勝投', '中繼成功', '救援成功', 'ERA', 'FIP', 'WHIP', 'K/9', 'BB/9', 'HR/9', 'K/BB', '總局數', '奪三振']
            show_p = agg_p[show_cols_p].copy()
            show_p = show_p.sort_values(by=['球隊', 'FIP'], ascending=[True, True])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人投手榜")
                team_df = show_p[show_p['球隊'] == team]
                if not team_df.empty: 
                    styled_p = team_df.drop(columns=['球隊']).style.format({
                        'ERA': '{:.2f}', 'FIP': '{:.2f}', 'WHIP': '{:.2f}',
                        'K/9': '{:.2f}', 'BB/9': '{:.2f}', 'HR/9': '{:.2f}', 'K/BB': '{:.2f}',
                        '總局數': '{:.1f}'
                    })
                    st.dataframe(styled_p, use_container_width=True, hide_index=True)
    else: st.info("目前沒有投球紀錄可以顯示！")

# ==========================================
# --- 分頁 4：📋 賽前戰情室 (智慧標籤與過濾引擎版) ---
# ==========================================
with tab4:
    st.header("📋 賽前戰情室")
    
    cached_players_b = get_player_list("打擊單場紀錄")
    cached_players_p = get_player_list("投手單場紀錄")
    
    col_laa, col_lad = st.columns(2)
    
    with col_laa:
        st.subheader("🔴 LAA 先發陣容")
        laa_batters = []
        available_laa = cached_players_b.get("LAA", []).copy()
        for i in range(1, 10):
            current_options = ["未指定"] + available_laa
            p = st.selectbox(f"第 {i} 棒", current_options, key=f"laa_b{i}")
            if p != "未指定": laa_batters.append(p); available_laa.remove(p)
        laa_sp = st.selectbox("先發投手 (SP)", ["未指定"] + cached_players_p.get("LAA", []), key="laa_sp")
        
    with col_lad:
        st.subheader("🔵 LAD 先發陣容")
        lad_batters = []
        available_lad = cached_players_b.get("LAD", []).copy()
        for i in range(1, 10):
            current_options = ["未指定"] + available_lad
            p = st.selectbox(f"第 {i} 棒", current_options, key=f"lad_b{i}")
            if p != "未指定": lad_batters.append(p); available_lad.remove(p)
        lad_sp = st.selectbox("先發投手 (SP)", ["未指定"] + cached_players_p.get("LAD", []), key="lad_sp")

    st.markdown("---")
    
    if st.button("📊 產生今日觀戰重點", type="primary", use_container_width=True):
        with st.spinner("AI 正在分析大量數據與潛規則..."):
            df_b, df_p, err = get_career_stats()
            
            if df_b is None or df_b.empty:
                st.warning("⚠️ 數據不足！請確認試算表內至少有一筆有效的球員紀錄。")
            else:
                raw_report_pool = []
                
                # --- 團隊分析 ---
                def analyze_team_status(team_name, sp_name):
                    if not df_p.empty:
                        bp_df = df_p[(df_p['球隊'] == team_name) & (df_p['投手姓名'] != sp_name)]
                        if not bp_df.empty:
                            bp_outs = (bp_df['局數(整數)'].sum() * 3) + bp_df['局數(出局數)'].sum()
                            bp_ip = bp_outs / 3.0
                            if bp_ip > 0:
                                bp_era = (bp_df['自責分'].sum() * 9) / bp_ip
                                if bp_era > 5.50:
                                    msgs = [
                                        f"🚨 **【牛棚核爆危機】** {team_name} 後援防線宛如提款機 (牛棚 ERA {bp_era:.2f})，對方只要撐過先發投手大有可為！",
                                        f"🔥 **【漏水牛棚】** {team_name} 牛棚 ERA 高達 {bp_era:.2f}，比賽隨時可能在後半段翻盤。"
                                    ]
                                    raw_report_pool.append({"type": "error", "text": random.choice(msgs), "player": "Team_BP", "category": "TEAM_BP_BAD"})
                                elif bp_era < 2.50:
                                    msgs = [
                                        f"🏰 **【鐵壁牛棚】** {team_name} 擁有固若金湯的後援防線 (牛棚 ERA {bp_era:.2f})，陷入僵局對他們極度有利。",
                                        f"🔒 **【關門大吉】** 只要 {team_name} 取得領先，他們強悍的牛棚 (ERA {bp_era:.2f}) 幾乎不會讓勝利溜走。"
                                    ]
                                    raw_report_pool.append({"type": "success", "text": random.choice(msgs), "player": "Team_BP", "category": "TEAM_BP_GOOD"})
                    
                    if not df_b.empty:
                        team_b_df = df_b[df_b['球隊'] == team_name]
                        if not team_b_df.empty:
                            team_ab = team_b_df['打數'].sum()
                            team_pa = team_b_df['打席'].sum()
                            if team_ab > 0:
                                team_avg = team_b_df['安打'].sum() / team_ab
                                if team_avg < 0.200:
                                    msgs = [
                                        f"🥶 **【全隊急凍】** {team_name} 團隊打線陷入低潮 (打擊率僅 {team_avg:.3f})，極需有人跳出來帶動氣勢。",
                                        f"💤 **【集體沉睡】** {team_name} 的打線像是被下了安眠藥 (團隊 AVG {team_avg:.3f})，今晚能甦醒嗎？"
                                    ]
                                    raw_report_pool.append({"type": "warning", "text": random.choice(msgs), "player": "Team_Hit", "category": "TEAM_SLUMP"})
                                
                                team_tb = (team_b_df['安打'].sum() - team_b_df['二壘安打'].sum() - team_b_df['三壘安打'].sum() - team_b_df['全壘打'].sum()) + 2*team_b_df['二壘安打'].sum() + 3*team_b_df['三壘安打'].sum() + 4*team_b_df['全壘打'].sum()
                                team_iso = (team_tb / team_ab) - team_avg
                                if team_iso > 0.200:
                                    raw_report_pool.append({"type": "error", "text": f"🌋 **【團隊長打猛獸】** {team_name} 全隊充斥著怪力男 (團隊 ISO {team_iso:.3f})，稍有不慎就會被扛出大牆。", "player": "Team_Hit", "category": "TEAM_POWER"})
                            
                            if team_pa > 0:
                                team_bb_pct = (team_b_df['四壞球'].sum() / team_pa) * 100
                                if team_bb_pct > 12:
                                    raw_report_pool.append({"type": "warning", "text": f"🧘‍♂️ **【極致耐心】** {team_name} 是支選球極其刁鑽的球隊 (團隊保送率 {team_bb_pct:.1f}%)，會快速消耗對方投手的用球數。", "player": "Team_Hit", "category": "TEAM_EYE"})

                analyze_team_status("LAA", laa_sp)
                analyze_team_status("LAD", lad_sp)

                # --- 獨立分析 ---
                def analyze_player_matchup(team_name, batters, sp_same_team, opp_team, opp_sp):
                    if opp_sp != "未指定":
                        sp_stats = df_p[(df_p['球隊'] == opp_team) & (df_p['投手姓名'] == opp_sp)]
                        if not sp_stats.empty:
                            fip, era, k9, hr9 = sp_stats.iloc[0]['FIP'], sp_stats.iloc[0]['ERA'], sp_stats.iloc[0]['K/9'], sp_stats.iloc[0]['HR/9']
                            if 0 < fip < 2.50:
                                msgs = [
                                    f"🛡️ **【賽揚神獸】** {opp_team} {opp_sp} 展現史詩級壓制力 (FIP {fip:.2f})，{team_name} 今晚將面臨苦戰。",
                                    f"⛰️ **【難以翻越的高牆】** {opp_team} 推出的 {opp_sp} (FIP {fip:.2f}) 近乎無解，必須把握得點圈機會。"
                                ]
                                raw_report_pool.append({"type": "error", "text": random.choice(msgs), "player": opp_sp, "category": "SP_ACE"})
                            if era > 6.0:
                                msgs = [
                                    f"🎯 **【發球機啟動】** {opp_team} {opp_sp} 近期狂失分 (ERA {era:.2f})，{team_name} 打線請把握進補機會！",
                                    f"🎁 **【大進補時間】** {opp_team} {opp_sp} 狀況極差，這會是 {team_name} 洗數據的最佳時機。"
                                ]
                                raw_report_pool.append({"type": "success", "text": random.choice(msgs), "player": opp_sp, "category": "SP_BP"})
                            if k9 > 11.0:
                                msgs = [
                                    f"🌪️ **【三振大師】** {opp_team} {opp_sp} 狂飆三振 (K/9 {k9:.2f})，打者請縮小好球帶，想辦法破壞球數。",
                                    f"⚔️ **【揮空夢魘】** {opp_team} {opp_sp} 的球威極其噁心，今晚預計會有大量打者走回休息室。"
                                ]
                                raw_report_pool.append({"type": "warning", "text": random.choice(msgs), "player": opp_sp, "category": "SP_K"})

                    for i, batter in enumerate(batters):
                        b_stats = df_b[(df_b['球隊'] == team_name) & (df_b['球員姓名'] == batter)]
                        if not b_stats.empty:
                            ops_p, hr, sb, k_pct = b_stats.iloc[0]['OPS+'], b_stats.iloc[0]['全壘打'], b_stats.iloc[0]['盜壘'], b_stats.iloc[0]['K%']
                            bb_pct = b_stats.iloc[0]['BB%']
                            
                            if "ohtani" in batter.lower() or "大谷" in batter:
                                if batter == sp_same_team: 
                                    msgs = [
                                        f"⚔️ **【二刀流全開】** 警告！{team_name} {batter} 同場先發投打，對手準備見證歷史！",
                                        f"🦄 **【棒球界獨角獸】** 又是投球又是打擊，{team_name} {batter} 打算一個人擊敗對手全隊嗎？"
                                    ]
                                    raw_report_pool.append({"type": "error", "text": random.choice(msgs), "player": batter, "category": "TWO_WAY"})
                            
                            if ops_p > 180:
                                msgs = [
                                    f"👽 **【外星人降臨】** {team_name} {batter} 數據超脫人類極限 (OPS+ {ops_p:.0f})。直接敬遠可能比較快。",
                                    f"🛑 **【危險人物】** 看到 {team_name} {batter} 走上打擊區，防護員已經準備好冰敷袋了 (OPS+ {ops_p:.0f})。"
                                ]
                                raw_report_pool.append({"type": "error", "text": random.choice(msgs), "player": batter, "category": "OPS_HIGH"})
                            elif ops_p > 140:
                                msgs = [
                                    f"🔥 **【重砲警戒】** {team_name} {batter} 近況火熱 (OPS+ {ops_p:.0f})，投手絕對不能失投。",
                                    f"💥 **【火力全開】** {team_name} {batter} 手感燙得可以煎蛋，請投手小心對付。"
                                ]
                                raw_report_pool.append({"type": "warning", "text": random.choice(msgs), "player": batter, "category": "OPS_GOOD"})
                            
                            if hr > 2 and k_pct > 30:
                                msgs = [
                                    f"💨 **【電風扇盲砲】** {team_name} {batter} 要麼全壘打要麼揮空，變化球伺候。",
                                    f"🎲 **【吃角子老虎機】** 投資 {team_name} {batter} 風險極大，要嘛全壘打不然就三振。"
                                ]
                                raw_report_pool.append({"type": "info", "text": random.choice(msgs), "player": batter, "category": "FAN"})
                            if sb >= 5:
                                msgs = [
                                    f"🏍️ **【紅色閃電】** {team_name} {batter} 已累積 {sb} 盜壘，只要上一壘就等於在二壘。",
                                    f"🏃 **【田徑隊借來的】** 只要讓 {team_name} {batter} 上壘，捕手跟投手的噩夢就開始了。"
                                ]
                                raw_report_pool.append({"type": "warning", "text": random.choice(msgs), "player": batter, "category": "SPEED"})
                            if bb_pct > 18:
                                msgs = [
                                    f"🦅 **【鷹眼】** {team_name} {batter} 超會選球 (BB% {bb_pct:.1f}%)，請準備好投滿球數。",
                                    f"🧘‍♂️ **【打擊區的修行者】** 面對 {team_name} {batter}，想騙他揮壞球簡直比登天還難。"
                                ]
                                raw_report_pool.append({"type": "warning", "text": random.choice(msgs), "player": batter, "category": "EYE"})

                analyze_player_matchup("LAA", laa_batters, laa_sp, "LAD", lad_sp)
                analyze_player_matchup("LAD", lad_batters, lad_sp, "LAA", laa_sp)

                st.markdown("---")
                st.markdown("## 📰 今日賽前觀戰焦點 (Top 5)")
                
                if raw_report_pool:
                    team_reports = [r for r in raw_report_pool if "Team" in r['player']]
                    player_reports = [r for r in raw_report_pool if "Team" not in r['player']]
                    
                    random.shuffle(team_reports)
                    random.shuffle(player_reports)
                    
                    final_reports = []
                    selected_players = set()
                    selected_categories = set()
                    
                    for r in team_reports:
                        if len(final_reports) >= 2: break
                        if r['category'] not in selected_categories:
                            final_reports.append(r)
                            selected_categories.add(r['category'])
                            
                    for r in player_reports:
                        if len(final_reports) >= 5: break
                        if r['player'] not in selected_players and r['category'] not in selected_categories:
                            final_reports.append(r)
                            selected_players.add(r['player'])
                            selected_categories.add(r['category'])
                    
                    if len(final_reports) < 3:
                        for r in raw_report_pool:
                            if len(final_reports) >= 3: break
                            if r not in final_reports: final_reports.append(r)
                            
                    st.info(random.choice([
                        "🏟️ **【洛城內戰】** 高速公路大戰 (Freeway Series) 點燃戰火！面子之爭絕不退讓！",
                        "🔥 **【恩怨對決】** 洛杉磯的球迷已經將球場塞滿，今晚註定是個不安靜的夜晚！",
                        "🍿 **【頂尖碰撞】** 準備好爆米花，兩支火力強大的球隊即將在鑽石場上正面交鋒！"
                    ]))
                    for report in final_reports:
                        if report['type'] == 'error': st.error(report['text'])
                        elif report['type'] == 'warning': st.warning(report['text'])
                        elif report['type'] == 'success': st.success(report['text'])
                        else: st.info(report['text'])
                else:
                    st.write("目前雙方戰力均衡，敬請期待場上表現！")