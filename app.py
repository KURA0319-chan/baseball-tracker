import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
import time
import random
import json  
import os    
import math

# ==========================================
# 專屬設定 & 守位價值矩陣
# ==========================================
SERVICE_ACCOUNT_FILE = 'baseball.json'
SHEET_NAME = '棒球數據資料庫'
TEAMS = ["LAA", "LAD"]

# 打者守位 & 投手角色
POSITIONS = ["DH", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "PH", "PR"]
ROLES_P = ["SP", "RP", "CP"]

# 守位調整值矩陣 (針對 3 局制縮放後的每場紅利值)
POS_ADJ = {
    "C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, 
    "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12,
    "PH": -0.12, "PR": -0.12
}

SEASONS = [f"Season {i}" for i in range(1, 11)]
GAME_STAGES = [f"例行賽 G{i}" for i in range(1, 11)] + [f"世界大賽 G{i}" for i in range(1, 8)]

# 初始化狀態記憶
if 'clear_bat' not in st.session_state: st.session_state.clear_bat = False
if 'clear_pitch' not in st.session_state: st.session_state.clear_pitch = False
if 'prev_player_b' not in st.session_state: st.session_state.prev_player_b = ""
if 'prev_player_p' not in st.session_state: st.session_state.prev_player_p = ""

if st.session_state.get('clear_bat'):
    for k in ['pa_b', 'ab_b', 'h_b', 'rbi_b', 'run_b', 'hr_b', 'bb_b', 'so_b', 'sb_b', 'tb2_b', 'tb3_b']:
        st.session_state[k] = 0
    st.session_state.clear_bat = False

if st.session_state.get('clear_pitch'):
    for k in ['ip_f', 'ip_o', 'bf_p', 'so_p', 'bb_p', 'r_p', 'er_p', 'hp_p', 'hrp_p', 'np_p']:
        st.session_state[k] = 0
    st.session_state.clear_pitch = False

# ==========================================
# 雙引擎連線模式
# ==========================================
@st.cache_resource
def get_sheet():
    try:
        if os.path.exists('baseball.json'):
            gc = gspread.service_account(filename='baseball.json')
        else:
            creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
            gc = gspread.service_account_from_dict(creds_dict)
        return gc.open(SHEET_NAME)
    except Exception as e:
        st.error(f"連線失敗：{e}")
        return None

SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_settings():
    data = {
        "lineups": st.session_state.get("lineups", {'LAA': ["" for _ in range(9)], 'LAD': ["" for _ in range(9)]}),
        "lineup_pos": st.session_state.get("lineup_pos", {'LAA': ["DH" for _ in range(9)], 'LAD': ["DH" for _ in range(9)]}),
        "pitchers": st.session_state.get("pitchers", {'LAA': "", 'LAD': ""}),
        "default_season": st.session_state.get("f_season", "十年總成績"),
        "f_game_pref": st.session_state.get("f_game_pref", "看整季")
    }
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

saved_data = load_settings()

if 'lineups' not in st.session_state: st.session_state.lineups = saved_data.get("lineups", {'LAA': ["" for _ in range(9)], 'LAD': ["" for _ in range(9)]})
if 'lineup_pos' not in st.session_state: st.session_state.lineup_pos = saved_data.get("lineup_pos", {'LAA': ["DH" for _ in range(9)], 'LAD': ["DH" for _ in range(9)]})
if 'pitchers' not in st.session_state: st.session_state.pitchers = saved_data.get("pitchers", {'LAA': "", 'LAD': ""})
if 'default_season' not in st.session_state: st.session_state.default_season = saved_data.get("default_season", "十年總成績")
if 'f_game_pref' not in st.session_state: st.session_state.f_game_pref = saved_data.get("f_game_pref", "看整季")
    
@st.cache_data(ttl=15)
def get_raw_records(sheet_name):
    sh = get_sheet()
    if not sh: return []
    try: return sh.worksheet(sheet_name).get_all_values()[1:]
    except: return []

def get_career_stats():
    records_b = get_raw_records("打擊單場紀錄")
    records_p = get_raw_records("投手單場紀錄")
    
    b_cols = ['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘', '守位']
    try:
        if records_b:
            df_b = pd.DataFrame(records_b, columns=b_cols)
            num_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            for col in num_cols: df_b[col] = pd.to_numeric(df_b[col], errors='coerce').fillna(0)
            st.session_state.df_b_raw = df_b 
        else:
            st.session_state.df_b_raw = pd.DataFrame(columns=b_cols)
    except Exception as e:
        st.session_state.df_b_raw = pd.DataFrame(columns=b_cols)

    p_cols = ['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分', '角色']
    try:
        if records_p:
            df_p = pd.DataFrame(records_p, columns=p_cols)
            num_p = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            for col in num_p: df_p[col] = pd.to_numeric(df_p[col], errors='coerce').fillna(0)
            st.session_state.df_p_raw = df_p
        else:
            st.session_state.df_p_raw = pd.DataFrame(columns=p_cols)
    except Exception as e:
        st.session_state.df_p_raw = pd.DataFrame(columns=p_cols)

@st.cache_data(ttl=60)
def get_player_list(sheet_name):
    records = get_raw_records(sheet_name)
    players_dict = {team: set() for team in TEAMS}
    for row in records:
        if len(row) > 3 and row[2] in players_dict: players_dict[row[2]].add(row[3])
    return {k: sorted(list(v)) for k, v in players_dict.items()}

# ==========================================
# 網頁介面設計
# ==========================================
st.set_page_config(page_title="LAA vs LAD 數據中心", page_icon="⚾", layout="wide")
st.title("⚾ 洛杉磯雙雄數據追蹤系統 V48 (完美連動修正版)")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 打擊單場輸入", 
    "⚾ 投球單場輸入", 
    "📊 數據總表", 
    "📡 賽前戰報", 
    "🏛️ 歷史與榮耀殿堂"
])

# --- 分頁 1：打擊輸入 ---
with tab1:
    st.subheader("輸入今日打擊表現")
    get_career_stats()
    df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
    
    col_s_b, col_g_b, col_t_b, col_p_b, col_pos_b = st.columns([1, 1, 1, 1.2, 0.8])
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
    
    # ✨ 核心修正：只自動切換「守位」，絕對不碰「打席與打數」！讓它們自然繼承您的最後輸入
    if player_b != st.session_state.get('prev_player_b', ''):
        st.session_state.prev_player_b = player_b
        if not df_b_raw.empty and player_b in df_b_raw['球員姓名'].values:
            p_history = df_b_raw[df_b_raw['球員姓名'] == player_b].sort_values('時間戳記', ascending=False)
            last_recorded_pos = p_history.iloc[0]['守位']
            if last_recorded_pos in POSITIONS:
                st.session_state['pos_b'] = last_recorded_pos 

    with col_pos_b:
        cur_pos_b = st.selectbox("守備位置", POSITIONS, key="pos_b")

    st.markdown("---")
    st.info("💡 提醒：【安打】欄位請填寫包含長打在內的「總安打數」。(送出後會保留打席與打數以便連續登錄，其他數據自動歸零)")
    
    # ✨ 在畫面畫出之前清空其他安打數據，避開報錯
    if st.session_state.get('clear_bat_partial'):
        for k in ['h_b', 'rbi_b', 'run_b', 'hr_b', 'bb_b', 'so_b', 'sb_b', 'tb2_b', 'tb3_b']:
            if k in st.session_state: st.session_state[k] = 0
        st.session_state.clear_bat_partial = False

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

    if st.button("⚾ 儲存本場打擊數據", type="primary", use_container_width=True, key="btn_submit_b"):
        error_msg = []
        if player_b == "": error_msg.append("❌ 請填寫球員姓名！")
        if h > ab: error_msg.append(f"❌ 安打數 ({h}) 不能大於打數 ({ab})")
        if so > ab: error_msg.append(f"❌ 三振數 ({so}) 不能大於打數 ({ab})")
        if (tb2 + tb3 + hr) > h: error_msg.append("❌ 長打總和不能大於安打數")
        if ab > pa: error_msg.append(f"❌ 打數 ({ab}) 不能大於打席 ({pa})")
        if (ab + bb) > pa: error_msg.append(f"❌ 打數+四壞 ({ab+bb}) 超過總打席 ({pa})")

        if error_msg:
            for msg in error_msg: st.error(msg)
        else:
            sh = get_sheet()
            if sh:
                try:
                    ws = sh.worksheet("打擊單場紀錄")
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ws.append_row([now, full_stage_b, team_b, player_b, pa, ab, h, tb2, tb3, hr, rbi, run, bb, so, sb, cur_pos_b])
                    st.success(f"✅ 成功儲存 {player_b} 的表現！")
                    get_raw_records.clear()
                    
                    st.session_state.clear_bat_partial = True
                    time.sleep(1)
                    st.rerun() 
                except Exception as e: st.error(f"寫入失敗：{e}")
# --- 分頁 2：投球輸入 ---
with tab2:
    st.subheader("輸入今日投球表現")
    df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())
    
    col_s_p, col_g_p, col_t_p, col_p_p, col_res_p, col_role_p = st.columns([1, 1, 1, 1.2, 0.6, 0.6])
    with col_s_p: selected_season_p = st.selectbox("賽季", SEASONS, key="season_p")
    with col_g_p: selected_game_p = st.selectbox("賽事階段", GAME_STAGES, key="game_p")
    with col_t_p: team_p = st.selectbox("所屬球隊", TEAMS, key="team_p")
    
    season_num_p = selected_season_p.split(" ")[1]
    full_stage_p = f"[S{season_num_p}] {selected_game_p}"

    records_p = get_raw_records("投手單場紀錄")
    inputted_pitchers = []
    used_statuses = []
    for row in records_p:
        if len(row) > 4 and row[1] == full_stage_p:
            if row[2] == team_p: inputted_pitchers.append(row[3])
            used_statuses.append(row[4])

    cached_players_p = get_player_list("投手單場紀錄")
    all_team_pitchers = cached_players_p.get(team_p, [])
    available_pitchers = [p for p in all_team_pitchers if p not in inputted_pitchers]

    p_res_options = ["無", "中繼"]
    if "勝" not in used_statuses: p_res_options.insert(1, "勝")
    if "敗" not in used_statuses: p_res_options.insert(2, "敗")
    if "救援" not in used_statuses: p_res_options.append("救援")

    with col_p_p:
        selected_p_p = st.selectbox("選擇投手", ["➕ 手動輸入新投手..."] + available_pitchers, key="sel_p")
        player_p = st.text_input("輸入姓名", key="txt_p") if selected_p_p == "➕ 手動輸入新投手..." else selected_p_p
        
    with col_res_p: 
        p_res = st.selectbox("勝敗紀錄", p_res_options, key="p_res", help="同場比賽的勝/敗/救援若已被登錄，選項會自動隱藏！")

    # ✨ 核心修正：強制覆寫角色狀態
    if player_p != st.session_state.prev_player_p:
        st.session_state.prev_player_p = player_p
        if not df_p_raw.empty and player_p in df_p_raw['投手姓名'].values:
            p_history = df_p_raw[df_p_raw['投手姓名'] == player_p].sort_values('時間戳記', ascending=False)
            last_recorded_role = p_history.iloc[0]['角色']
            if last_recorded_role in ROLES_P:
                st.session_state['role_p'] = last_recorded_role # 強制覆寫 UI 狀態

    with col_role_p:
        cur_role_p = st.selectbox("角色", ROLES_P, key="role_p")

    st.markdown("---")
    st.info("💡 提醒：送出後局數與失分等數據會自動歸零，方便您登錄下一位牛棚投手。")
    
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
                    ws.append_row([now, full_stage_p, team_p, player_p, p_res, ip_full, ip_outs, bf, np_pitch, h_p, hr_p, bb_p, so_p, r, er, cur_role_p])
                    st.success(f"✅ 成功儲存！")
                    get_raw_records.clear()
                    st.session_state.clear_pitch = True
                    time.sleep(1)
                    st.rerun() 
                except Exception as e: st.error(f"寫入失敗：{e}")
# ==========================================
# --- 分頁 3：數據總表 + 球隊戰績表 ---
# ==========================================
with tab3:
    st.subheader("🏆 累積數據與聯盟戰績")
    
    with st.expander("💡 棒球進階數據 (Sabermetrics) 小教室 (點我展開)"):
        st.markdown("""
        * **WAR (勝場貢獻值)：** 衡量一名球員「比替補多替球隊拿幾勝」。本系統特製 **eWAR** 透過 wRC+、FIP 以及 **守位紅利** 精算而成。
        * **wRC+ (加權創造得分)：** ✨ **100 為全聯盟平均**。150 代表火力比聯盟平均高出 50%，是現代棒球最精準的打擊指標 (無負數)。
        * **wOBA (加權上壘率)：** 依照安打與保送的實際得分價值給予不同權重。
        * **ISO (純長打率)：** 評估打者真正的長打火力，> 0.200 即為重砲手。
        * **BABIP (場內安打率)：** 剔除全壘打與三振後的安打率。異常高代表強運，異常低代表被守備針對或運氣極差。
        * **FIP (獨立防禦率)：** 剔除守備與運氣成分，純看投手硬實力。
        * **HR/9 (每九局被全壘打)：** 投手飛球控制力的指標。
        * **P/IP (每局用球數)：** 投手效率指標。**14球以下**為極致省球，**18球以上**代表常陷入纏鬥。
        * **WHIP (每局被上壘率)：** < **1.20** 就算是非常優秀的投手。
        """)

    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 2.5])
    with col_f1:
        if st.button("🔄 刷新數據", type="primary", key="btn_refresh_tab3_v48_final"): 
            get_raw_records.clear()
            st.rerun()
            
    with col_f2:
        season_options = ["十年總成績"] + SEASONS
        s_idx = season_options.index(st.session_state.default_season) if st.session_state.default_season in season_options else 0
        def update_season():
            st.session_state.default_season = st.session_state.tab3_f_season_v48
            if 'save_settings' in globals(): save_settings()
        filter_season = st.selectbox("篩選賽季", season_options, index=s_idx, key="tab3_f_season_v48", on_change=update_season)

    with col_f3:
        if filter_season == "十年總成績":
            filter_game = st.selectbox("比賽階段", ["不限 (看全部)"], disabled=True, key="tab3_f_game_disabled_v48")
            target_prefix = ""
            is_exact_match = False
        else:
            game_options = ["看整季", "例行賽總和", "世界大賽總和"] + GAME_STAGES
            saved_game = st.session_state.get("f_game_pref", "看整季")
            g_idx = game_options.index(saved_game) if saved_game in game_options else 0
            def update_game():
                st.session_state.f_game_pref = st.session_state.tab3_f_game_sel_v48
                if 'save_settings' in globals(): save_settings()
            filter_game = st.selectbox("比賽階段", game_options, index=g_idx, key="tab3_f_game_sel_v48", on_change=update_game)
            s_num = filter_season.split(" ")[1]
            if filter_game == "看整季": 
                target_prefix = f"[S{s_num}]"
                is_exact_match = False
            elif filter_game == "例行賽總和": 
                target_prefix = f"[S{s_num}] 例行賽"
                is_exact_match = False
            elif filter_game == "世界大賽總和": 
                target_prefix = f"[S{s_num}] 世界大賽"
                is_exact_match = False
            else: 
                target_prefix = f"[S{s_num}] {filter_game}"
                is_exact_match = True # ✨ 單場賽事啟動「完全相等」模式

    get_career_stats()
    df_b = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p = st.session_state.get('df_p_raw', pd.DataFrame())

    # ✨ 核心修復：防止「第1場」抓到「第10場」的精準過濾器
    def apply_filter(df, prefix, exact):
        if df.empty or not prefix: return df
        if exact: return df[df['賽事階段'].astype(str) == prefix]
        else: return df[df['賽事階段'].astype(str).str.contains(prefix, regex=False)]

    b_filter_df = apply_filter(df_b, target_prefix, is_exact_match)
    p_filter_df = apply_filter(df_p, target_prefix, is_exact_match)

    team_games_played = b_filter_df['賽事階段'].nunique() if not b_filter_df.empty else 1
    
    dyn_pa_limit = max(1.0, team_games_played * 1.0)
    dyn_ip_limit = max(0.1, team_games_played * 0.33)

    st.markdown("### 📊 球隊戰績排名 (Team Standings)")
    if not df_p.empty:
        stand_b = b_filter_df
        stand_p = p_filter_df
    
        
        team_data = []
        for team in TEAMS:
            t_p = stand_p[stand_p['球隊'] == team].sort_values('時間戳記')
            t_b = stand_b[stand_b['球隊'] == team] if not stand_b.empty else pd.DataFrame()
            
            wins, losses, draws = 0, 0, 0
            starters = []
            
            for stage, group in t_p.groupby('賽事階段', sort=False):
                group = group.sort_values('時間戳記')
                res = group['勝敗'].astype(str).values
                if any('勝' in x for x in res): wins += 1
                elif any('敗' in x for x in res): losses += 1
                else: draws += 1 
                if not group.empty: starters.append(group.iloc[0]['投手姓名'])
            
            rs = pd.to_numeric(t_b['得分'], errors='coerce').sum() if not t_b.empty else 0
            ra = pd.to_numeric(t_p['失分'], errors='coerce').sum()
            
            last_sp = starters[-1] if starters else "無"
            next_sp = "輪值待定"
            is_ws_view = "世界大賽" in str(target_prefix)
            
            if is_ws_view:
                s_num_str = target_prefix.split(" ")[0] if target_prefix else ""
                reg_p = df_p[(df_p['球隊'] == team) & (df_p['賽事階段'].astype(str).str.contains(f"{s_num_str} 例行賽", regex=False))]
                reg_starters = []
                for stage, group in reg_p.groupby('賽事階段', sort=False):
                    g_sorted = group.sort_values('時間戳記')
                    if not g_sorted.empty: reg_starters.append(g_sorted.iloc[0]['投手姓名'])
                
                unique_sps = list(set(reg_starters))
                sp_stats = []
                for sp in unique_sps:
                    sp_df = reg_p[reg_p['投手姓名'] == sp]
                    outs = (pd.to_numeric(sp_df['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(sp_df['局數(出局數)'], errors='coerce').fillna(0)).sum()
                    er = pd.to_numeric(sp_df['自責分'], errors='coerce').fillna(0).sum()
                    ip = outs / 3.0
                    era = (er * 9) / ip if ip > 0 else float('inf')
                    sp_stats.append({'name': sp, 'era': era})
                
                top_ws_rotation = [x['name'] for x in sorted(sp_stats, key=lambda x: x['era'])][:5]
                if top_ws_rotation:
                    if not starters: next_sp = top_ws_rotation[0] 
                    else:
                        last_app_idx = {}
                        for sp in top_ws_rotation: last_app_idx[sp] = len(starters) - 1 - starters[::-1].index(sp) if sp in starters else -1
                        next_sp = min(top_ws_rotation, key=lambda x: (last_app_idx[x], top_ws_rotation.index(x)))
                        if next_sp == last_sp and len(top_ws_rotation) > 1:
                            next_sp = min([x for x in top_ws_rotation if x != last_sp], key=lambda x: (last_app_idx[x], top_ws_rotation.index(x)))
            else:
                if target_prefix:
                    s_num_str = target_prefix.split(" ")[0] 
                    t_p_season = df_p[(df_p['球隊'] == team) & (df_p['賽事階段'].astype(str).str.contains(s_num_str, regex=False))].sort_values('時間戳記')
                else:
                    t_p_season = df_p[df_p['球隊'] == team].sort_values('時間戳記')
                    
                season_starters = []
                for stage, group in t_p_season.groupby('賽事階段', sort=False):
                    g_sorted = group.sort_values('時間戳記')
                    if not g_sorted.empty: season_starters.append(g_sorted.iloc[0]['投手姓名'])
                
                if season_starters:
                    last_sp = season_starters[-1]
                    counts = {}
                    for sp in season_starters: counts[sp] = counts.get(sp, 0) + 1
                    top_sps = sorted(counts.keys(), key=lambda x: counts[x], reverse=True)[:5]
                    last_app_idx = {sp: len(season_starters) - 1 - season_starters[::-1].index(sp) for sp in top_sps}
                    next_sp = min(top_sps, key=lambda x: last_app_idx[x])
                    if next_sp == last_sp and len(top_sps) > 1:
                        next_sp = min([x for x in top_sps if x != last_sp], key=lambda x: last_app_idx[x])
                else:
                    next_sp = "輪值待定"

            team_data.append({
                "球隊": f"🔴 {team}" if team == "LAA" else f"🔵 {team}",
                "已賽": wins + losses + draws,
                "勝": wins, "敗": losses, "和": draws,
                "勝率": wins / (wins + losses) if (wins + losses) > 0 else 0,
                "總得分": int(rs), "總失分": int(ra), "得失分差": int(rs - ra),
                "前場先發": last_sp, "預計下場": next_sp
            })
        
        df_standings = pd.DataFrame(team_data).sort_values("勝率", ascending=False)
        st.dataframe(df_standings.style.format({"勝率": "{:.3f}"}), use_container_width=True, hide_index=True)
    else: st.info("尚無數據可計算戰績。")

    st.markdown("---")
    
    st.markdown("### ⚾ 打擊成績")
    if not df_b.empty:
        curr_b = b_filter_df
        if curr_b.empty: st.info("查無符合條件的打擊紀錄。")
        else:
            agg_b = curr_b.groupby(['球隊', '球員姓名']).agg({
                '打席': 'sum', '打數': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', 
                '全壘打': 'sum', '打點': 'sum', '得分': 'sum', '四壞球': 'sum', '三振': 'sum', '盜壘': 'sum',
                '賽事階段': 'count',
                '守位': lambda x: x.value_counts().index[0] if '守位' in curr_b.columns else 'DH'
            }).reset_index().rename(columns={'賽事階段': '出賽數'})
            
            agg_b['一壘安打'] = agg_b['安打'] - agg_b['二壘安打'] - agg_b['三壘安打'] - agg_b['全壘打']
            agg_b['AVG'] = (agg_b['安打'] / agg_b['打數'].replace(0, 1)).fillna(0)
            agg_b['OBP'] = ((agg_b['安打'] + agg_b['四壞球']) / agg_b['打席'].replace(0, 1)).fillna(0)
            agg_b['SLG'] = ((agg_b['一壘安打'] + 2*agg_b['二壘安打'] + 3*agg_b['三壘安打'] + 4*agg_b['全壘打']) / agg_b['打數'].replace(0, 1)).fillna(0)
            agg_b['OPS'] = agg_b['OBP'] + agg_b['SLG']
            agg_b['ISO'] = agg_b['SLG'] - agg_b['AVG']
            agg_b['BABIP'] = ((agg_b['安打'] - agg_b['全壘打']) / (agg_b['打數'] - agg_b['三振'] - agg_b['全壘打']).replace(0, 1)).fillna(0)
            agg_b['BB%'] = (agg_b['四壞球'] / agg_b['打席'].replace(0, 1) * 100).fillna(0)
            agg_b['K%'] = (agg_b['三振'] / agg_b['打席'].replace(0, 1) * 100).fillna(0)
            
            total_h = curr_b['安打'].sum()
            total_bb = curr_b['四壞球'].sum()
            total_pa = curr_b['打席'].sum()
            total_ab = curr_b['打數'].sum()
            
            lg_1b = total_h - curr_b['二壘安打'].sum() - curr_b['三壘安打'].sum() - curr_b['全壘打'].sum()
            lg_woba_num = 0.69 * total_bb + 0.88 * lg_1b + 1.25 * curr_b['二壘安打'].sum() + 1.59 * curr_b['三壘安打'].sum() + 2.06 * curr_b['全壘打'].sum()
            lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.320
            
            agg_b['wOBA'] = (0.69 * agg_b['四壞球'] + 0.88 * agg_b['一壘安打'] + 1.25 * agg_b['二壘安打'] + 1.59 * agg_b['三壘安打'] + 2.06 * agg_b['全壘打']) / agg_b['打席'].replace(0, 1)
            agg_b['wRC+'] = (agg_b['wOBA'] / lg_woba * 100).fillna(0).astype(int)
            
            agg_b['eWAR'] = agg_b.apply(lambda r: (((r['wRC+'] - 70) / 80) + POS_ADJ.get(r['守位'], 0)) * (r['打席'] / 15), axis=1)
            agg_b['eWAR'] = agg_b['eWAR'].apply(lambda x: 0.0 if round(x, 1) == 0 else x)

            qual_b = agg_b[agg_b['打席'] >= dyn_pa_limit]
            
            if not agg_b.empty:
                st.markdown(f"#### 👑 聯盟打擊領先者 (規定打席: {dyn_pa_limit:.1f})")
                
                # ✨ MLB Tie-breaker 同步系統 (AVG需達標，計數數據看全體)
                avg_df = qual_b[qual_b['AVG'] > 0]
                h_df = agg_b[agg_b['安打'] > 0]
                hr_df = agg_b[agg_b['全壘打'] > 0]
                rbi_df = agg_b[agg_b['打點'] > 0]
                sb_df = agg_b[agg_b['盜壘'] > 0] if '盜壘' in agg_b.columns else pd.DataFrame()

                name_avg = f"[{avg_df.sort_values(by=['AVG', '安打', '打席'], ascending=[False, False, False]).iloc[0]['球隊']}] {avg_df.sort_values(by=['AVG', '安打', '打席'], ascending=[False, False, False]).iloc[0]['球員姓名']}" if not avg_df.empty else "無(未達標)"
                val_avg = avg_df['AVG'].max() if not avg_df.empty else 0.0

                name_h = f"[{h_df.sort_values(by=['安打', '打席', 'AVG'], ascending=[False, True, False]).iloc[0]['球隊']}] {h_df.sort_values(by=['安打', '打席', 'AVG'], ascending=[False, True, False]).iloc[0]['球員姓名']}" if not h_df.empty else "無"
                val_h = h_df['安打'].max() if not h_df.empty else 0

                name_hr = f"[{hr_df.sort_values(by=['全壘打', '打席', 'AVG'], ascending=[False, True, False]).iloc[0]['球隊']}] {hr_df.sort_values(by=['全壘打', '打席', 'AVG'], ascending=[False, True, False]).iloc[0]['球員姓名']}" if not hr_df.empty else "無"
                val_hr = hr_df['全壘打'].max() if not hr_df.empty else 0

                name_rbi = f"[{rbi_df.sort_values(by=['打點', '打席', '全壘打'], ascending=[False, True, False]).iloc[0]['球隊']}] {rbi_df.sort_values(by=['打點', '打席', '全壘打'], ascending=[False, True, False]).iloc[0]['球員姓名']}" if not rbi_df.empty else "無"
                val_rbi = rbi_df['打點'].max() if not rbi_df.empty else 0

                name_sb = f"[{sb_df.sort_values(by=['盜壘', '打席'], ascending=[False, True]).iloc[0]['球隊']}] {sb_df.sort_values(by=['盜壘', '打席'], ascending=[False, True]).iloc[0]['球員姓名']}" if not sb_df.empty else "無"
                val_sb = sb_df['盜壘'].max() if not sb_df.empty else 0

                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                lc1.metric(f"打擊王", f"{val_avg:.3f}", name_avg)
                lc2.metric(f"安打王", f"{int(val_h)} H", name_h)
                lc3.metric(f"全壘打王", f"{int(val_hr)} HR", name_hr)
                lc4.metric(f"打點王", f"{int(val_rbi)} RBI", name_rbi)
                lc5.metric(f"盜壘王", f"{int(val_sb)} SB", name_sb)
            
            st.markdown("---")
            lg_obp = (total_h + total_bb) / total_pa if total_pa > 0 else 0.0
            total_tb = lg_1b + 2*curr_b['二壘安打'].sum() + 3*curr_b['三壘安打'].sum() + 4*curr_b['全壘打'].sum()
            lg_slg = total_tb / total_ab if total_ab > 0 else 0.0
            lg_ops = lg_obp + lg_slg
            lg_avg = total_h / total_ab if total_ab > 0 else 0.0
            
            summary_b = []
            summary_b.append({'隊伍': '🌎 全聯盟平均', 'wRC+': 100, 'OPS': lg_ops, 'AVG': lg_avg, 'OBP': lg_obp, 'SLG': lg_slg})
            for team in TEAMS:
                t_df = curr_b[curr_b['球隊'] == team]
                if not t_df.empty:
                    t_pa = t_df['打席'].sum()
                    t_ab = t_df['打數'].sum()
                    t_h = t_df['安打'].sum()
                    t_bb = t_df['四壞球'].sum()
                    t_1b = t_h - t_df['二壘安打'].sum() - t_df['三壘安打'].sum() - t_df['全壘打'].sum()
                    t_obp = (t_h + t_bb) / t_pa if t_pa > 0 else 0
                    t_tb = t_1b + 2*t_df['二壘安打'].sum() + 3*t_df['三壘安打'].sum() + 4*t_df['全壘打'].sum()
                    t_slg = t_tb / t_ab if t_ab > 0 else 0
                    t_ops = t_obp + t_slg
                    t_avg = t_h / t_ab if t_ab > 0 else 0
                    t_woba_num = 0.69 * t_bb + 0.88 * t_1b + 1.25 * t_df['二壘安打'].sum() + 1.59 * t_df['三壘安打'].sum() + 2.06 * t_df['全壘打'].sum()
                    t_woba = t_woba_num / t_pa if t_pa > 0 else 0
                    t_wrc_plus = 100 * (t_woba / lg_woba) if (lg_woba > 0 and t_pa > 0) else 0
                    summary_b.append({'隊伍': f"🔴 {team}" if team == "LAA" else f"🔵 {team}", 'wRC+': int(round(t_wrc_plus, 0)), 'OPS': t_ops, 'AVG': t_avg, 'OBP': t_obp, 'SLG': t_slg})
            
            st.markdown("#### ⚖️ 團隊火力對比")
            df_sum_b = pd.DataFrame(summary_b)
            b_col_config = {
                "wRC+": st.column_config.NumberColumn(help="加權創造得分：100為聯盟平均。150代表火力高出平均50%，現代棒球最精準火力指標。"),
                "OPS": st.column_config.NumberColumn(help="攻擊指數 (上壘率 + 長打率)"),
                "AVG": st.column_config.NumberColumn(help="打擊率"),
                "OBP": st.column_config.NumberColumn(help="上壘率"),
                "SLG": st.column_config.NumberColumn(help="長打率"),
                "ISO": st.column_config.NumberColumn(help="純長打率 (長打率 - 打擊率)：評估真正長打火力，> 0.200 即為重砲手。"),
                "BABIP": st.column_config.NumberColumn(help="場內安打率：剔除全壘打與三振後的安打率。異常高代表強運，異常低代表被守備針對或運氣極差。"),
                "eWAR": st.column_config.NumberColumn(help="預期勝場貢獻值：綜合所有數據，衡量比替補多替球隊拿幾勝。"),
                "K%": st.column_config.NumberColumn(help="被三振率：吞K次數佔打席的比例。"),
                "BB%": st.column_config.NumberColumn(help="保送率：獲得保送次數佔打席的比例。")
            }
            st.dataframe(df_sum_b.style.format({'OPS': '{:.3f}', 'AVG': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}'}), use_container_width=True, hide_index=True, column_config=b_col_config)

            show_cols_b = ['球隊', '球員姓名', '出賽數', '打席', '打數', 'wRC+', 'OPS', 'AVG', 'OBP', 'SLG', 'ISO', 'BABIP', 'BB%', 'K%', '全壘打', '打點', '盜壘', 'eWAR']
            show_df = agg_b[show_cols_b].copy().sort_values(by=['球隊', 'wRC+'], ascending=[True, False])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人打擊榜")
                team_df = show_df[show_df['球隊'] == team]
                if not team_df.empty: 
                    styled_df = team_df.drop(columns=['球隊']).style.format({
                        'OPS': '{:.3f}', 'AVG': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'ISO': '{:.3f}', 'BABIP': '{:.3f}',
                        'BB%': '{:.1f}%', 'K%': '{:.1f}%', 'eWAR': '{:.1f}'
                    })
                    st.dataframe(styled_df, use_container_width=True, hide_index=True, column_config=b_col_config)
    else: st.info("目前沒有打擊紀錄可以顯示！")

    st.markdown("---")
    
    st.markdown("### 🥎 投球成績")
    if not df_p.empty:
        curr_p = p_filter_df
        if curr_p.empty: st.info("查無符合條件的投球紀錄。")
        else:
            agg_p = curr_p.groupby(['球隊', '投手姓名']).agg({
                '局數(整數)': 'sum', '局數(出局數)': 'sum', '打者數': 'sum', '投球數': 'sum', '被安打': 'sum', 
                '被全壘打': 'sum', '四壞球': 'sum', '奪三振': 'sum', '失分': 'sum', '自責分': 'sum',
                '角色': lambda x: x.value_counts().index[0] if '角色' in curr_p.columns else 'SP'
            }).reset_index()
            
            apps = curr_p.groupby(['球隊', '投手姓名']).size().reset_index(name='出賽數')
            agg_p = pd.merge(agg_p, apps, on=['球隊', '投手姓名'], how='left')
            
            stats_counts = curr_p.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
            for col in ['勝', '敗', '中繼', '救援']:
                if col not in stats_counts.columns: stats_counts[col] = 0
            agg_p = pd.merge(agg_p, stats_counts, on=['球隊', '投手姓名'], how='left')
            agg_p.rename(columns={'勝': '勝投', '救援': '救援成功', '中繼': '中繼成功'}, inplace=True)
            
            total_outs = (agg_p['局數(整數)'] * 3) + agg_p['局數(出局數)']
            ip_calc = total_outs / 3.0
            agg_p['實際局數'] = ip_calc
            agg_p['總局數'] = (total_outs // 3) + (total_outs % 3) / 10.0
            
            agg_p['NP'] = agg_p['投球數']
            agg_p['P/IP'] = (agg_p['NP'] / agg_p['實際局數'].replace(0, 1)).fillna(0)
            
            agg_p['ERA'] = agg_p.apply(lambda r: (r['自責分'] * 9) / r['實際局數'] if r['實際局數'] > 0 else (float('inf') if r['自責分'] > 0 else 0.0), axis=1)
            agg_p['FIP'] = agg_p.apply(lambda r: (((13 * r['被全壘打']) + (3 * r['四壞球']) - (2 * r['奪三振'])) / r['實際局數'] + 3.10) if r['實際局數'] > 0 else (float('inf') if (13 * r['被全壘打'] + 3 * r['四壞球'] - 2 * r['奪三振']) > 0 else 3.10), axis=1)
            
            agg_p['WHIP'] = ((agg_p['被安打'] + agg_p['四壞球']) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['K/9'] = ((agg_p['奪三振'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['BB/9'] = ((agg_p['四壞球'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['HR/9'] = ((agg_p['被全壘打'] * 9) / ip_calc.replace(0, 1)).fillna(0)
            agg_p['K/BB'] = (agg_p['奪三振'] / agg_p['四壞球'].replace(0, 1)).fillna(agg_p['奪三振'])
            agg_p['TRA'] = (agg_p['ERA'] + agg_p['FIP']) / 2.0
            
            agg_p['eWAR'] = agg_p.apply(lambda r: (-0.1 * r['自責分'] - 0.05 * r['四壞球']) if r['實際局數'] == 0 else ((5.00 - r['TRA']) / 1.5) * (r['實際局數'] / 10), axis=1)
            agg_p['eWAR'] = agg_p['eWAR'].apply(lambda x: 0.0 if round(x, 1) == 0 else x)

            qual_p = agg_p[agg_p['實際局數'] >= dyn_ip_limit]
            
            if not agg_p.empty:
                st.markdown(f"#### 👑 聯盟投球領先者 (規定局數: {dyn_ip_limit:.1f})")
                
                # ✨ MLB Tie-breaker 同步系統 (ERA需達標，計數數據看全體)
                era_df = qual_p 
                w_df = agg_p[agg_p['勝投'] > 0]
                sv_df = agg_p[agg_p['救援成功'] > 0]
                hld_df = agg_p[agg_p['中繼成功'] > 0]
                so_df = agg_p[agg_p['奪三振'] > 0]

                name_era = f"[{era_df.sort_values(by=['ERA', '實際局數', '奪三振'], ascending=[True, False, False]).iloc[0]['球隊']}] {era_df.sort_values(by=['ERA', '實際局數', '奪三振'], ascending=[True, False, False]).iloc[0]['投手姓名']}" if not era_df.empty else "無(未達標)"
                val_era = era_df['ERA'].min() if not era_df.empty else float('inf')

                name_w = f"[{w_df.sort_values(by=['勝投', 'ERA', '實際局數'], ascending=[False, True, False]).iloc[0]['球隊']}] {w_df.sort_values(by=['勝投', 'ERA', '實際局數'], ascending=[False, True, False]).iloc[0]['投手姓名']}" if not w_df.empty else "無"
                val_w = w_df['勝投'].max() if not w_df.empty else 0

                name_sv = f"[{sv_df.sort_values(by=['救援成功', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['球隊']}] {sv_df.sort_values(by=['救援成功', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['投手姓名']}" if not sv_df.empty else "無"
                val_sv = sv_df['救援成功'].max() if not sv_df.empty else 0

                name_hld = f"[{hld_df.sort_values(by=['中繼成功', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['球隊']}] {hld_df.sort_values(by=['中繼成功', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['投手姓名']}" if not hld_df.empty else "無"
                val_hld = hld_df['中繼成功'].max() if not hld_df.empty else 0

                name_so = f"[{so_df.sort_values(by=['奪三振', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['球隊']}] {so_df.sort_values(by=['奪三振', 'ERA', '實際局數'], ascending=[False, True, True]).iloc[0]['投手姓名']}" if not so_df.empty else "無"
                val_so = so_df['奪三振'].max() if not so_df.empty else 0

                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                era_str = "∞" if val_era == float('inf') else f"{val_era:.2f}"
                lc1.metric(f"防禦率王", era_str, name_era)
                lc2.metric(f"勝投王", f"{int(val_w)} W", name_w)
                lc3.metric(f"救援王", f"{int(val_sv)} SV", name_sv)
                lc4.metric(f"中繼王", f"{int(val_hld)} HLD", name_hld)
                lc5.metric(f"三振王", f"{int(val_so)} K", name_so)

            st.markdown("---")
            lg_outs = (curr_p['局數(整數)'].sum() * 3) + curr_p['局數(出局數)'].sum()
            lg_ip = lg_outs / 3.0
            lg_er = curr_p['自責分'].sum()
            lg_hr = curr_p['被全壘打'].sum()
            lg_bb = curr_p['四壞球'].sum()
            lg_so = curr_p['奪三振'].sum()
            lg_h = curr_p['被安打'].sum()
            lg_era = (lg_er * 9) / lg_ip if lg_ip > 0 else float('inf') if lg_er > 0 else 0.0
            lg_whip = (lg_h + lg_bb) / lg_ip if lg_ip > 0 else 0
            lg_fip = (((13 * lg_hr) + (3 * lg_bb) - (2 * lg_so)) / lg_ip + 3.10) if lg_ip > 0 else float('inf') if (13*lg_hr+3*lg_bb-2*lg_so)>0 else 3.10

            summary_p = []
            summary_p.append({'隊伍': '🌎 全聯盟平均', 'ERA': lg_era, 'FIP': lg_fip, 'WHIP': lg_whip, 'K/9': (lg_so * 9 / lg_ip) if lg_ip > 0 else 0, 'BB/9': (lg_bb * 9 / lg_ip) if lg_ip > 0 else 0})
            for team in TEAMS:
                t_df = curr_p[curr_p['球隊'] == team]
                if not t_df.empty:
                    t_outs = (t_df['局數(整數)'].sum() * 3) + t_df['局數(出局數)'].sum()
                    t_ip = t_outs / 3.0
                    t_er = t_df['自責分'].sum()
                    t_hr = t_df['被全壘打'].sum()
                    t_bb = t_df['四壞球'].sum()
                    t_so = t_df['奪三振'].sum()
                    t_h = t_df['被安打'].sum()
                    t_era = (t_er * 9) / t_ip if t_ip > 0 else float('inf') if t_er > 0 else 0.0
                    t_whip = (t_h + t_bb) / t_ip if t_ip > 0 else 0
                    t_fip = (((13 * t_hr) + (3 * t_bb) - (2 * t_so)) / t_ip + 3.10) if t_ip > 0 else float('inf') if (13*t_hr+3*t_bb-2*t_so)>0 else 3.10
                    summary_p.append({'隊伍': f"🔴 {team}" if team == "LAA" else f"🔵 {team}", 'ERA': t_era, 'FIP': t_fip, 'WHIP': t_whip, 'K/9': (t_so * 9 / t_ip) if t_ip > 0 else 0, 'BB/9': (t_bb * 9 / t_ip) if t_ip > 0 else 0})
                    
            st.markdown("#### ⚖️ 團隊防線對比")
            df_sum_p = pd.DataFrame(summary_p)
            p_col_config = {
                "ERA": st.column_config.NumberColumn(help="防禦率 (每9局平均自責失分)"),
                "FIP": st.column_config.NumberColumn(help="獨立防禦率：剔除守備與運氣成分，純看三振、保送與挨轟，最能反映投手真實硬實力。"),
                "WHIP": st.column_config.NumberColumn(help="每局被上壘率：< 1.20 為極優。"),
                "P/IP": st.column_config.NumberColumn(help="每局用球數：投手效率指標。14球以下為極致省球，18球以上容易陷入纏鬥與體力透支。"),
                "HR/9": st.column_config.NumberColumn(help="每九局被全壘打：飛球與失投球控制力指標。"),
                "K/9": st.column_config.NumberColumn(help="每九局三振數：壓制力指標。"),
                "BB/9": st.column_config.NumberColumn(help="每九局保送數：控球力指標。"),
                "eWAR": st.column_config.NumberColumn(help="預期勝場貢獻值：綜合所有數據，衡量比替補多替球隊拿幾勝。")
            }
            st.dataframe(df_sum_p.style.format({'ERA': '{:.2f}', 'FIP': '{:.2f}', 'WHIP': '{:.2f}', 'K/9': '{:.2f}', 'BB/9': '{:.2f}'}), use_container_width=True, hide_index=True, column_config=p_col_config)
            
            show_cols_p = ['球隊', '投手姓名', '出賽數', '勝投', '中繼成功', '救援成功', 'ERA', 'FIP', 'WHIP', 'K/9', 'BB/9', 'HR/9', 'P/IP', '總局數', '奪三振', 'eWAR']
            show_p = agg_p[show_cols_p].copy().sort_values(by=['球隊', 'FIP'], ascending=[True, True])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人投手榜")
                team_df = show_p[show_p['球隊'] == team]
                if not team_df.empty: 
                    styled_p = team_df.drop(columns=['球隊']).style.format({
                        'ERA': lambda x: '∞' if x == float('inf') else f"{x:.2f}",
                        'FIP': lambda x: '∞' if x == float('inf') else f"{x:.2f}",
                        'WHIP': '{:.2f}', 'K/9': '{:.2f}', 'BB/9': '{:.2f}', 'HR/9': '{:.2f}', 'P/IP': '{:.1f}',
                        '總局數': '{:.1f}', 'eWAR': '{:.1f}'
                    })
                    st.dataframe(styled_p, use_container_width=True, hide_index=True, column_config=p_col_config)
    else: st.info("目前沒有投球紀錄可以顯示！")

# ==========================================
# --- 分頁 4：📋 賽前戰情室 (究極防護完整版) ---
# ==========================================
with tab4:
    st.header("📋 賽前戰情室與 AI 深度戰報")
    get_career_stats()

    # --- 1. 賽季與模式選擇 ---
    season_options_wr = ["十年總成績"] + SEASONS
    saved_wr_season = st.session_state.get("wr_season_memory", "十年總成績")
    wr_s_idx = season_options_wr.index(saved_wr_season) if saved_wr_season in season_options_wr else 0
    
    col_ai_s1, col_ai_s2, col_ai_s3 = st.columns([1.2, 1, 1.2])
    def update_wr_season():
        st.session_state.wr_season_memory = st.session_state.wr_season_sel_v48
        if 'save_settings' in globals(): save_settings()
        
    with col_ai_s1: 
        wr_season = st.selectbox("📊 選擇分析賽季", season_options_wr, index=wr_s_idx, key="wr_season_sel_v48", on_change=update_wr_season)
    with col_ai_s2:
        if wr_season != "十年總成績":
            wr_mode = st.selectbox("🎯 戰報模式", ["例行賽/綜合模式", "🏆 世界大賽特別戰報"], key="wr_mode_sel_v48")
        else:
            wr_mode = "例行賽/綜合模式"
            
    with col_ai_s3:
        matchup_format = st.radio("🏟️ 賽事主客場設定", ["LAA (客) @ LAD (主)", "LAD (客) @ LAA (主)"], horizontal=True, key="matchup_toggle")
        is_laa_home = (matchup_format == "LAD (客) @ LAA (主)")
        away_team = "LAD" if is_laa_home else "LAA"
        home_team = "LAA" if is_laa_home else "LAD"

    is_ws_mode = (wr_mode == "🏆 世界大賽特別戰報")

    # --- 2. 獲取數據與動態門檻 (嚴格分離賽事階段) ---
    def get_season_data(target_season, target_stage=""):
        df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
        df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_b_raw.empty and df_p_raw.empty: return {}, {}
        
        prefix = ""
        if target_season != "十年總成績":
            s_num = target_season.split(" ")[1]
            prefix = f"[S{s_num}]"

        b_sub = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_b_raw
        p_sub = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_raw
        
        if target_stage:
            b_sub = b_sub[b_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]
            p_sub = p_sub[p_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]

        b_dict, p_dict = {'LAA': {}, 'LAD': {}}, {'LAA': {}, 'LAD': {}}
        
        if not b_sub.empty:
            total_pa = b_sub['打席'].sum()
            lg_1b = b_sub['安打'].sum() - b_sub['二壘安打'].sum() - b_sub['三壘安打'].sum() - b_sub['全壘打'].sum()
            lg_woba_num = 0.69 * b_sub['四壞球'].sum() + 0.88 * lg_1b + 1.25 * b_sub['二壘安打'].sum() + 1.59 * b_sub['三壘安打'].sum() + 2.06 * b_sub['全壘打'].sum()
            lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.001

            agg_b = b_sub.groupby(['球隊', '球員姓名']).sum().reset_index()
            for _, row in agg_b.iterrows():
                avg = row['安打'] / max(1, row['打數'])
                obp = (row['安打'] + row['四壞球']) / max(1, row['打席'])
                b_1b = row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']
                xbh = row['二壘安打'] + row['三壘安打'] + row['全壘打'] 
                woba = (0.69 * row['四壞球'] + 0.88 * b_1b + 1.25 * row['二壘安打'] + 1.59 * row['三壘安打'] + 2.06 * row['全壘打']) / max(1, row['打席'])
                wrc_plus = 100 * (woba / lg_woba) if lg_woba > 0 else 0
                ewar = ((wrc_plus - 70) / 80) * (row['打席'] / 15)
                ewar = 0.0 if round(ewar, 1) == 0 else ewar 
                k_pct = (row['三振'] / max(1, row['打席'])) * 100
                bb_pct = (row['四壞球'] / max(1, row['打席'])) * 100
                iso = (((b_1b) + 2*row['二壘安打'] + 3*row['三壘安打'] + 4*row['全壘打']) / max(1, row['打數'])) - avg
                babip = (row['安打'] - row['全壘打']) / max(1, (row['打數'] - row['三振'] - row['全壘打']))
                
                team = row['球隊']
                if team not in b_dict: b_dict[team] = {}
                b_dict[team][row['球員姓名']] = {
                    'OPS+': wrc_plus, 'wRC+': wrc_plus, 'eWAR': ewar, 'AVG': avg, 'OBP': obp, 'HR': row['全壘打'],
                    'ISO': iso, 'K%': k_pct, 'BB%': bb_pct, 'BABIP': babip, 'SB': row['盜壘'], 'PA': row['打席'],
                    'K': row['三振'], 'BB': row['四壞球'], 'AB': row['打數'], 'H': row['安打'], 'XBH': xbh
                }

        if not p_sub.empty:
            # ✨ 動態聯盟防禦率基準
            lg_ip_total = ((p_sub['局數(整數)'].sum() * 3) + p_sub['局數(出局數)'].sum()) / 3.0
            lg_era_baseline = (p_sub['自責分'].sum() * 9) / lg_ip_total if lg_ip_total > 0 else 10.60
            era_divisor = max(1.5, lg_era_baseline * 0.2)
            
            agg_p = p_sub.groupby(['球隊', '投手姓名']).sum().reset_index()
            for _, row in agg_p.iterrows():
                ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                era = (row['自責分'] * 9) / max(1, ip_calc) if ip_calc > 0 else float('inf') if row['自責分'] > 0 else 0.0
                fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10 if ip_calc > 0 else float('inf') if (13*row['被全壘打']+3*row['四壞球']-2*row['奪三振'])>0 else 3.10
                tra = (era + fip) / 2.0
                ewar = (-0.1 * row['自責分'] - 0.05 * row['四壞球']) if ip_calc == 0 else ((lg_era_baseline - tra) / era_divisor) * (ip_calc / 10)
                ewar = 0.0 if round(ewar, 1) == 0 else ewar 
                whip = (row['被安打'] + row['四壞球']) / max(1, ip_calc)
                k9 = (row['奪三振'] * 9) / max(1, ip_calc)
                p_ip = row['投球數'] / max(0.1, ip_calc)
                
                team = row['球隊']
                if team not in p_dict: p_dict[team] = {}
                p_dict[team][row['投手姓名']] = {
                    'ERA': era, 'eWAR': ewar, 'K': row['奪三振'], 'FIP': fip,
                    'WHIP': whip, 'K/9': k9, 'P/IP': p_ip, 'IP': ip_calc, 'NP': row['投球數'],
                    'BF': row['打者數'], 'BB': row['四壞球'], 'H': row['被安打'], 'HR': row['被全壘打']
                }

        return b_dict, p_dict

    reg_b_stats, reg_p_stats = get_season_data(wr_season, "例行賽")
    ws_b_stats, ws_p_stats = get_season_data(wr_season, "世界大賽")

    if is_ws_mode:
        curr_b_stats, curr_p_stats = ws_b_stats, ws_p_stats
    else:
        curr_b_stats, curr_p_stats = reg_b_stats, reg_p_stats
        
    display_b_stats = curr_b_stats
    display_p_stats = curr_p_stats

    prev_season_str = "十年總成績"
    if wr_season != "十年總成績":
        curr_s_num = int(wr_season.split(" ")[1])
        if curr_s_num > 1: prev_season_str = f"Season {curr_s_num - 1}"
    prev_b_stats, prev_p_stats = get_season_data(prev_season_str)

    cached_players_b = get_player_list("打擊單場紀錄")
    cached_players_p = get_player_list("投手單場紀錄")

    # ✨ 修正1：確保打席與局數門檻，會嚴格區分「例行賽」與「世界大賽」的場次！
    df_b_full_raw = st.session_state.get('df_b_raw', pd.DataFrame())
    prefix_eval = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
    stage_keyword = "世界大賽" if is_ws_mode else "例行賽"
    
    if not df_b_full_raw.empty:
        b_filter_eval = df_b_full_raw[
            (df_b_full_raw['賽事階段'].astype(str).str.contains(prefix_eval, regex=False)) & 
            (df_b_full_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))
        ]
    else:
        b_filter_eval = pd.DataFrame()
        
    team_games_eval = b_filter_eval['賽事階段'].nunique() if not b_filter_eval.empty else 1
    
    # ✨ 修正 1：季後賽專屬固定門檻，不再隨場次無限縮放！
    if is_ws_mode:
        dyn_pa_limit = 3.0  # 世界大賽打席門檻固定為 3
        dyn_ip_limit = 1.0  # 世界大賽局數門檻固定為 1.0 局 (投過一局就及格)
    else:
        dyn_pa_limit = max(1.0, team_games_eval * 1.0)
        dyn_ip_limit = max(0.1, team_games_eval * 0.33)

    def get_bullpen_status(team_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty or wr_season == "十年總成績": return [], []
        s_num = wr_season.split(' ')[1]
        prefix = f"[S{s_num}] 世界大賽"
        sub_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)]
        t_df = sub_df[sub_df['球隊'] == team_name]
        
        games, ws_starters = [], set() 
        for stage, group in t_df.groupby('賽事階段', sort=False):
            g_sorted = group.sort_values('時間戳記')
            games.append(g_sorted)
            if not g_sorted.empty: ws_starters.add(g_sorted.iloc[0]['投手姓名']) 
        
        unavailable, warnings = [], []
        if not games: return unavailable, warnings
        
        last_g = games[-1]
        prev_g = games[-2] if len(games) >= 2 else pd.DataFrame()
        prev_prev_g = games[-3] if len(games) >= 3 else pd.DataFrame()
        team_pitchers = cached_players_p.get(team_name, [])
        
        for p in team_pitchers:
            if p in ws_starters: continue 
            p_last = last_g[last_g['投手姓名'] == p] if not last_g.empty else pd.DataFrame()
            p_prev = prev_g[prev_g['投手姓名'] == p] if not prev_g.empty else pd.DataFrame()
            p_prev_prev = prev_prev_g[prev_prev_g['投手姓名'] == p] if not prev_prev_g.empty else pd.DataFrame()
            
            pitched_last = not p_last.empty and pd.to_numeric(p_last['打者數'], errors='coerce').sum() > 0
            pitched_prev = not p_prev.empty and pd.to_numeric(p_prev['打者數'], errors='coerce').sum() > 0
            pitched_prev_prev = not p_prev_prev.empty and pd.to_numeric(p_prev_prev['打者數'], errors='coerce').sum() > 0
            
            np_last = pd.to_numeric(p_last['投球數'], errors='coerce').sum() if pitched_last else 0
            np_prev = pd.to_numeric(p_prev['投球數'], errors='coerce').sum() if pitched_prev else 0
            
            is_banned = False
            if np_last >= 25: unavailable.append(f"❌ {p} (前場 {int(np_last)} 球，須休 2 場)"); is_banned = True
            elif np_prev >= 25 and not pitched_last: unavailable.append(f"❌ {p} (前兩場 {int(np_prev)} 球，尚須休 1 場)"); is_banned = True
            elif np_last >= 15: unavailable.append(f"❌ {p} (前場 {int(np_last)} 球，須休 1 場)"); is_banned = True
            elif pitched_last and pitched_prev and pitched_prev_prev: unavailable.append(f"❌ {p} (已連 3 場登板，須休 1 場)"); is_banned = True
                
            if not is_banned:
                if pitched_last and pitched_prev: warnings.append(f"⚠️ {p} (已連 2 場登板，今日若上場明日強制禁賽)")
                elif pitched_last: warnings.append(f"⚠️ {p} (前場出賽 {int(np_last)} 球，請注意體力條)")
                    
        return unavailable, warnings

    if is_ws_mode:
        st.markdown("---")
        st.markdown("### 🏥 牛棚疲勞管制與停賽名單 (世界大賽專屬)")
        col_med_left, col_med_right = st.columns(2)
        
        def render_bullpen_status(team):
            unavail, warns = get_bullpen_status(team)
            if unavail:
                for msg in unavail: st.error(msg)
            if warns:
                for msg in warns: st.warning(msg)
            if not unavail and not warns: st.success(f"✅ {team} 牛棚全員健康，隨時待命")
                
        with col_med_left:
            st.write(f"**{away_team} (客場)**")
            render_bullpen_status(away_team)
        with col_med_right:
            st.write(f"**{home_team} (主場)**")
            render_bullpen_status(home_team)

    st.markdown("---")
    
    # --- 4. 動態陣容交換引擎 ---
    DEFAULT_9_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
    
    if 'lineups' not in st.session_state or type(st.session_state.lineups) is not dict: st.session_state.lineups = {}
    if 'lineup_pos' not in st.session_state or type(st.session_state.lineup_pos) is not dict: st.session_state.lineup_pos = {}

    for team in TEAMS:
        if team not in st.session_state.lineups: st.session_state.lineups[team] = ["未指定"] * 9
        if team not in st.session_state.lineup_pos: st.session_state.lineup_pos[team] = list(DEFAULT_9_POS)
        if len(set(st.session_state.lineup_pos[team])) < 9: st.session_state.lineup_pos[team] = list(DEFAULT_9_POS)
            
        for i in range(9):
            b_key = f"{team.lower()}_b{i+1}"
            pos_key = f"{team.lower()}_pos{i+1}"
            if b_key not in st.session_state: st.session_state[b_key] = st.session_state.lineups[team][i] if len(st.session_state.lineups[team]) > i else "未指定"
            if pos_key not in st.session_state: st.session_state[pos_key] = st.session_state.lineup_pos[team][i] if len(st.session_state.lineup_pos[team]) > i else DEFAULT_9_POS[i]

    def handle_lineup_change(team, idx):
        b_key = f"{team.lower()}_b{idx+1}"
        new_player = st.session_state[b_key]
        old_player = st.session_state.lineups[team][idx]

        if new_player != old_player:
            if new_player != "未指定" and new_player in st.session_state.lineups[team]:
                conflict_idx = st.session_state.lineups[team].index(new_player)
                st.session_state.lineups[team][conflict_idx] = old_player
                st.session_state[f"{team.lower()}_b{conflict_idx+1}"] = old_player
                
                old_pos = st.session_state.lineup_pos[team][idx]
                conflict_pos = st.session_state.lineup_pos[team][conflict_idx]
                st.session_state.lineup_pos[team][conflict_idx] = old_pos
                st.session_state[f"{team.lower()}_pos{conflict_idx+1}"] = old_pos
                st.session_state.lineup_pos[team][idx] = conflict_pos
                st.session_state[f"{team.lower()}_pos{idx+1}"] = conflict_pos

            st.session_state.lineups[team][idx] = new_player
            if 'save_settings' in globals(): save_settings()

    def handle_pos_change(team, idx):
        pos_key = f"{team.lower()}_pos{idx+1}"
        new_pos = st.session_state[pos_key]
        old_pos = st.session_state.lineup_pos[team][idx]

        if new_pos != old_pos:
            if new_pos in st.session_state.lineup_pos[team]:
                conflict_idx = st.session_state.lineup_pos[team].index(new_pos)
                st.session_state.lineup_pos[team][conflict_idx] = old_pos
                st.session_state[f"{team.lower()}_pos{conflict_idx+1}"] = old_pos
            
            st.session_state.lineup_pos[team][idx] = new_pos
            if 'save_settings' in globals(): save_settings()

    def log5(a, b, l):
        if l <= 0 or l >= 1: return 0
        if a == 0 and b == 0: return 0
        num = (a * b) / l
        den = num + ((1 - a) * (1 - b) / (1 - l))
        if den == 0: return 0
        return num / den

    def get_x_stats(b_name, b_team, p_name, p_team):
        b_s = curr_b_stats.get(b_team, {}).get(b_name)
        p_s = curr_p_stats.get(p_team, {}).get(p_name)
        if not b_s or not p_s or b_s.get('PA', 0) == 0 or p_s.get('BF', 0) == 0: return 0, 0, 0, 0, 0
        lg_pa = sum([v.get('PA',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
        lg_ab = sum([v.get('AB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
        if lg_pa < 10 or lg_ab == 0: return 0, 0, 0, 0, 0
        
        l_ba = sum([v.get('H',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_ab
        l_obp = sum([v.get('H',0)+v.get('BB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa
        l_hr = sum([v.get('HR',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa
        l_k = sum([v.get('K',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa
        l_xbh = sum([v.get('XBH',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa

        W = 10.0 
        b_ba = (b_s['H'] + l_ba * W) / (max(1, b_s['AB']) + W)
        b_obp = (b_s['H'] + b_s['BB'] + l_obp * W) / (b_s['PA'] + W)
        b_hr = (b_s['HR'] + l_hr * W) / (b_s['PA'] + W)
        b_k = (b_s['K'] + l_k * W) / (b_s['PA'] + W)
        b_xbh = (b_s['XBH'] + l_xbh * W) / (b_s['PA'] + W)

        p_bf, p_ab = p_s['BF'], max(1, p_s['BF'] - p_s.get('BB',0))
        p_ba = (p_s['H'] + l_ba * W) / (p_ab + W)
        p_obp = (p_s['H'] + p_s['BB'] + l_obp * W) / (p_bf + W)
        p_hr = (p_s['HR'] + l_hr * W) / (p_bf + W)
        p_k = (p_s['K'] + l_k * W) / (p_bf + W)
        
        lg_hr_tot, lg_h_tot, lg_xbh_tot = sum([v.get('HR',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]), sum([v.get('H',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]), sum([v.get('XBH',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
        p_xbh_est = p_s['HR'] + max(0, p_s['H'] - p_s['HR']) * (max(0, lg_xbh_tot - lg_hr_tot) / max(1, lg_h_tot - lg_hr_tot))
        p_xbh = (p_xbh_est + l_xbh * W) / (p_bf + W)

        xBA = max(0.01, min(0.99, log5(b_ba, p_ba, l_ba)))
        xOBP = max(0.01, min(0.99, log5(b_obp, p_obp, l_obp)))
        xHR = max(0.001, min(0.99, log5(b_hr, p_hr, l_hr)))
        xXBH = max(0.001, min(0.99, log5(b_xbh, p_xbh, l_xbh)))
        xK = max(0.01, min(0.99, log5(b_k, p_k, l_k)))
        return xBA, xOBP, xHR, xXBH, xK

    def render_log5_card(b_name, b_team, p_name, p_team, t_color):
        xBA, xOBP, xHR, xXBH, xK = get_x_stats(b_name, b_team, p_name, p_team)
        if xBA == 0: return f"<div style='padding:20px; background:#111; border-radius:10px; color:#666; text-align:center;'>尚未產生足夠數據，無法預測 {b_name} vs {p_name}</div>"
        
        def make_bar(label, prob, color, warning_threshold=None):
            p_pct = prob * 100
            warn_tag = " <span style='color:#ff4b4b; font-size:10px; font-weight:bold;'>(🚨警戒)</span>" if warning_threshold and p_pct >= warning_threshold else ""
            return f"<div style='margin-bottom:8px;'><div style='display:flex; justify-content:space-between; font-size:13px; color:#ddd; margin-bottom:2px;'><span>{label}</span><span>{p_pct:.1f}%{warn_tag}</span></div><div style='width:100%; background:#333; height:8px; border-radius:4px; overflow:hidden;'><div style='width:{p_pct}%; background:{color}; height:100%; border-radius:4px;'></div></div></div>"
        
        stats_pool = [
            make_bar('預期安打 (xBA)', xBA, '#00e5ff'), make_bar('預期上壘 (xOBP)', xOBP, '#007bff'),
            make_bar('預期長打 (xXBH%)', xXBH, '#ff9f00'), make_bar('預期全壘打 (xHR%)', xHR, '#ff4b4b', 8.0),
            make_bar('預期被三振 (xK%)', xK, '#b052d9')
        ]
        chosen_stats = "".join(random.sample(stats_pool, 3))
        
        html = f"<div style='background: linear-gradient(145deg, #161616 0%, #222 100%); padding: 20px; border-radius: 12px; border-left: 5px solid {t_color}; box-shadow: 0 4px 15px rgba(0,0,0,0.5);'><h4 style='color:#aaa; margin:0 0 15px 0; font-size:12px; text-transform:uppercase; letter-spacing:1px;'>📺 Spotlight Matchup</h4><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;'><div style='text-align:left; width: 40%;'><div style='font-size:10px; color:#888;'>BATTER [{b_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{b_name}</div></div><div style='font-size:16px; color:#555; font-weight:900; font-style:italic;'>VS</div><div style='text-align:right; width: 40%;'><div style='font-size:10px; color:#888;'>PITCHER [{p_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{p_name}</div></div></div>{chosen_stats}<div style='font-size:10px; color:#666; margin-top:15px; text-align:right;'>*Log5 Smoothed Projection</div></div>"
        return html

    def get_spotlight_batter(team_batters, team_name):
        valid = [b for b in team_batters if b != "未指定" and b in curr_b_stats.get(team_name, {})]
        if not valid: valid = list(curr_b_stats.get(team_name, {}).keys())
        return random.choice(valid) if valid else None

    def get_spotlight_pitcher(selected_sp, team_name):
        if selected_sp and selected_sp != "未指定" and selected_sp in curr_p_stats.get(team_name, {}):
            return selected_sp
        p_list = curr_p_stats.get(team_name, {})
        if not p_list: return None
        return max(p_list.keys(), key=lambda x: p_list[x]['IP'])

    laa_batters = st.session_state.lineups.get('LAA', [])
    lad_batters = st.session_state.lineups.get('LAD', [])
    laa_spotlight_p = get_spotlight_pitcher(st.session_state.pitchers.get('LAA'), 'LAA')
    lad_spotlight_p = get_spotlight_pitcher(st.session_state.pitchers.get('LAD'), 'LAD')
    
    laa_spotlight_b = get_spotlight_batter(laa_batters, 'LAA')
    lad_spotlight_b = get_spotlight_batter(lad_batters, 'LAD')
    
    c_card1, c_card2 = st.columns(2)
    has_matchup = False
    
    with c_card1:
        if away_team == "LAD" and lad_spotlight_b and laa_spotlight_p:
            card_html = render_log5_card(lad_spotlight_b, 'LAD', laa_spotlight_p, 'LAA', '#005A9C')
            if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
        elif away_team == "LAA" and laa_spotlight_b and lad_spotlight_p:
            card_html = render_log5_card(laa_spotlight_b, 'LAA', lad_spotlight_p, 'LAD', '#BA0021')
            if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
            
    with c_card2:
        if home_team == "LAA" and laa_spotlight_b and lad_spotlight_p:
            card_html = render_log5_card(laa_spotlight_b, 'LAA', lad_spotlight_p, 'LAD', '#BA0021')
            if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
        elif home_team == "LAD" and lad_spotlight_b and laa_spotlight_p:
            card_html = render_log5_card(lad_spotlight_b, 'LAD', laa_spotlight_p, 'LAA', '#005A9C')
            if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
    
    if has_matchup: st.markdown("<br>", unsafe_allow_html=True)

    col_ai1, col_ai2 = st.columns(2)

    def auto_lineup_v48(team_name):
        s_prefix = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
        stage_keyword = "世界大賽" if is_ws_mode else "例行賽"
        s_df = df_b_raw[(df_b_raw['球隊'] == team_name) & 
                        (df_b_raw['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) &
                        (df_b_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))]
        
        if s_df.empty:
            st.toast(f"⚠️ {team_name} 在本賽季尚無數據，無法代排。")
            return

        agg = s_df.groupby('球員姓名').agg({'打席': 'sum', '四壞球': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', '全壘打': 'sum'}).reset_index()
        
        # ✨ 升級 1：貝氏平滑穩定機制 (加上 10 個打席的聯盟平均，避免 1 席 1 保送的球員 wRC+ 暴衝)
        agg['woba_num'] = 0.69 * agg['四壞球'] + 0.88 * (agg['安打'] - agg['二壘安打'] - agg['三壘安打'] - agg['全壘打']) + 1.25 * agg['二壘安打'] + 1.59 * agg['三壘安打'] + 2.06 * agg['全壘打']
        agg['wRC+'] = (((agg['woba_num'] + 0.320 * 10) / (agg['打席'] + 10)) / 0.320 * 100).astype(int)
        
        eligibility = s_df.groupby('球員姓名')['守位'].unique().to_dict()
        final_9_match = {} 
        remaining_players = agg.sort_values('wRC+', ascending=False)['球員姓名'].tolist()
        
        for pos in DEFAULT_9_POS:
            if pos == "DH": continue
            for p in remaining_players:
                if pos in eligibility.get(p, []):
                    final_9_match[p] = pos
                    remaining_players.remove(p)
                    break
                    
        for pos in DEFAULT_9_POS:
            if pos not in final_9_match.values():
                if remaining_players:
                    final_9_match[remaining_players.pop(0)] = pos

        best_9_names = list(final_9_match.keys())
        best_9_df = agg[agg['球員姓名'].isin(best_9_names)].sort_values('wRC+', ascending=False).reset_index(drop=True)
        prefix_team = team_name.lower()
        
        # ✨ 升級 2：現代棒球打序觀念對位 (2棒最強、4棒重砲、1棒高上壘)
        modern_mapping = {1: 2, 2: 0, 3: 4, 4: 1, 5: 3, 6: 5, 7: 6, 8: 7, 9: 8}
        
        for order_idx in range(1, 10):
            rank_idx = modern_mapping[order_idx]
            if rank_idx < len(best_9_df):
                new_n = best_9_df.iloc[rank_idx]['球員姓名']
                new_p = final_9_match[new_n]
            else:
                new_n, new_p = "未指定", "DH"
            
            st.session_state[f"{prefix_team}_b{order_idx}"] = new_n
            st.session_state[f"{prefix_team}_pos{order_idx}"] = new_p
            st.session_state.lineups[team_name][order_idx-1] = new_n if new_n != "未指定" else ""
            st.session_state.lineup_pos[team_name][order_idx-1] = new_p

    # ✨ 修正 3：合併成單一按鈕，雙隊同步排線！
    if st.button("🤖 AI 一鍵最佳化打線 (雙隊同步 / 現代棒球觀念)", type="primary", use_container_width=True, key="btn_ai_both_tab4"):
        auto_lineup_v48("LAA")
        auto_lineup_v48("LAD")
        if 'save_settings' in globals(): save_settings()
        st.rerun()

    st.markdown("---")

        
    # --- 5. 打線與投手選擇 UI ---
    col_left_lineup, col_right_lineup = st.columns(2)
    
    def render_team_lineup_ui(team, location_tag):
        st.subheader(f"{'🔴' if team == 'LAA' else '🔵'} {team} 先發陣容 ({location_tag})")
        available_players = cached_players_b.get(team, []).copy()
        prefix_str = "WS " if is_ws_mode else ""
        team_lower = team.lower()
        
        for i in range(1, 10):
            c_name, c_pos = st.columns([2, 1])
            b_key = f"{team_lower}_b{i}"
            pos_key = f"{team_lower}_pos{i}"
            
            with c_name:
                options = ["未指定"] + available_players 
                p = st.selectbox(f"第 {i} 棒", options, key=b_key, on_change=handle_lineup_change, args=(team, i-1))
            with c_pos:
                pos = st.selectbox(f"守位", DEFAULT_9_POS, key=pos_key, label_visibility="hidden", on_change=handle_pos_change, args=(team, i-1))
            
            if p and p != "未指定":
                stats = display_b_stats.get(team, {}).get(p, {'wRC+': 0, 'eWAR': 0, 'AVG': 0})
                st.caption(f"📊 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}wRC+: **{stats['wRC+']:.0f}** | {prefix_str}AVG: {stats['AVG']:.3f}")
        
        # ✨ 修復點：特別加上分隔線，讓投手下拉選單絕對不迷路！
        st.markdown("---")
        st.markdown(f"##### ⚾ {team} 先發投手 (SP)")
        sp_options = ["未指定"] + cached_players_p.get(team, [])
        sp_key = f"{team_lower}_sp_v48_final"
        if sp_key not in st.session_state:
            st.session_state[sp_key] = st.session_state.pitchers.get(team, "未指定")
        if st.session_state[sp_key] not in sp_options: st.session_state[sp_key] = "未指定"
        
        sp = st.selectbox(f"選擇 {team} 先發", sp_options, key=sp_key, label_visibility="collapsed")
        st.session_state.pitchers[team] = sp if sp != "未指定" else ""
        if sp and sp != "未指定":
            stats = display_p_stats.get(team, {}).get(sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
            era_str = '∞' if stats['ERA'] == float('inf') else f"{stats['ERA']:.2f}"
            st.caption(f"🥎 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}ERA: **{era_str}** | {prefix_str}K: {stats['K']}")

    with col_left_lineup: render_team_lineup_ui(away_team, "客場")
    with col_right_lineup: render_team_lineup_ui(home_team, "主場")

    st.markdown("---")
    
    # --- 6. 賽前戰力天秤與 AI 戰報生成 ---
    st.subheader("🔮 賽前戰力天秤 (Expected Win %)")
    
    def get_streak_bonus(team_name, ws_only=False):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return 0
        if wr_season != "十年總成績":
            s_num = wr_season.split(" ")[1]
            prefix = f"[S{s_num}]"
            df_p_season = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)]
        else:
            df_p_season = df_p_full

        if ws_only and wr_season != "十年總成績":
            t_df = df_p_season[(df_p_season['球隊'] == team_name) & (df_p_season['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].sort_values(by='時間戳記', ascending=True)
        else:
            t_df = df_p_season[df_p_season['球隊'] == team_name].sort_values(by='時間戳記', ascending=True)
            
        results = []
        for stage, group in t_df.groupby('賽事階段', sort=False):
            res = group['勝敗'].astype(str).values
            if any('勝' in x for x in res): results.append('W')
            elif any('敗' in x for x in res): results.append('L')
            else: results.append('D') 
        if not results: return 0
        streak_type = results[-1]
        streak_count = 0
        for r in reversed(results):
            if r == streak_type: streak_count += 1
            else: break
        return streak_count * 1.5 if streak_type == 'W' else streak_count * -1.5 if streak_type == 'L' else 0

    def get_starter_ratio(team_name, p_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return 1.0 
        t_df = df_p_full[df_p_full['球隊'] == team_name]
        if t_df.empty: return 1.0
        total_apps, starts = 0, 0
        for stage, group in t_df.groupby('賽事階段', sort=False):
            g_sorted = group.sort_values('時間戳記', ascending=True)
            if not g_sorted.empty and p_name in g_sorted['投手姓名'].values:
                total_apps += 1
                if g_sorted.iloc[0]['投手姓名'] == p_name: starts += 1
        return starts / total_apps if total_apps > 0 else 1.0

    def calc_win_prob():
        def get_b_ewar(team, p):
            base = curr_b_stats.get(team, {}).get(p, {'eWAR':0})['eWAR']
            if is_ws_mode and p in ws_b_stats.get(team, {}):
                return ws_b_stats[team][p]['eWAR'] * 6.0 if ws_b_stats[team][p].get('PA', 0) > 0 else base
            return base

        def get_p_ewar(team, sp):
            if not sp or sp == "未指定": return 0
            base = curr_p_stats.get(team, {}).get(sp, {'eWAR':0})['eWAR']
            if is_ws_mode and sp in ws_p_stats.get(team, {}):
                return ws_p_stats[team][sp]['eWAR'] * 6.0 if ws_p_stats[team][sp].get('IP', 0) > 0 else base * 5.0
            return base * 5.0 
        
        curr_laa_batters = [st.session_state.lineups['LAA'][i] for i in range(9) if st.session_state.lineups['LAA'][i] != "未指定"]
        curr_lad_batters = [st.session_state.lineups['LAD'][i] for i in range(9) if st.session_state.lineups['LAD'][i] != "未指定"]
        laa_sp = st.session_state.pitchers.get("LAA", "未指定")
        lad_sp = st.session_state.pitchers.get("LAD", "未指定")
        
        laa_power = sum([get_b_ewar('LAA', p) for p in curr_laa_batters]) + get_p_ewar('LAA', laa_sp) + get_streak_bonus('LAA', is_ws_mode)/3.0 - (3.0 if laa_sp != "未指定" and get_starter_ratio('LAA', laa_sp) <= 0.30 else 0)
        lad_power = sum([get_b_ewar('LAD', p) for p in curr_lad_batters]) + get_p_ewar('LAD', lad_sp) + get_streak_bonus('LAD', is_ws_mode)/3.0 - (3.0 if lad_sp != "未指定" and get_starter_ratio('LAD', lad_sp) <= 0.30 else 0)
        
        laa_power += 1.5 if is_laa_home else 0
        lad_power += 1.5 if not is_laa_home else 0

        laa_prob = max(15.0, min(85.0, round((1 / (1 + math.exp(-0.12 * (laa_power - lad_power)))) * 100, 1)))
        return laa_prob, round(100.0 - laa_prob, 1), laa_sp != "未指定" and get_starter_ratio('LAA', laa_sp) <= 0.30, lad_sp != "未指定" and get_starter_ratio('LAD', lad_sp) <= 0.30

    prob_laa, prob_lad, is_laa_opener, is_lad_opener = calc_win_prob()
    ml_laa = f"-{int(round((prob_laa / (100.0 - prob_laa)) * 100))}" if prob_laa > 50 else f"+{int(round(((100.0 - prob_laa) / max(0.1, prob_laa)) * 100))}" if prob_laa < 50 else "PK"
    ml_lad = f"-{int(round((prob_lad / (100.0 - prob_lad)) * 100))}" if prob_lad > 50 else f"+{int(round(((100.0 - prob_lad) / max(0.1, prob_lad)) * 100))}" if prob_lad < 50 else "PK"
    
    if away_team == "LAD":
        left_p, right_p, left_t, right_t, left_ml, right_ml, c_left, c_right = prob_lad, prob_laa, "LAD", "LAA", ml_lad, ml_laa, "#005A9C", "#BA0021"
    else:
        left_p, right_p, left_t, right_t, left_ml, right_ml, c_left, c_right = prob_laa, prob_lad, "LAA", "LAD", ml_laa, ml_lad, "#BA0021", "#005A9C"

    st.markdown(f"<div style='display: flex; height: 35px; border-radius: 8px; overflow: hidden; font-weight: bold; color: white; text-align: center; line-height: 35px; font-size: 16px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);'><div style='width: {left_p}%; background-color: {c_left}; transition: width 0.5s;'>{left_t} {left_p}% ({left_ml})</div><div style='width: {right_p}%; background-color: {c_right}; transition: width 0.5s;'>{right_t} {right_p}% ({right_ml})</div></div>", unsafe_allow_html=True)
    
    msg = "💡 **AI 魔球演算模型**：納入打線火力、守位價值、先發(權重5倍)、球隊連勝動能與**主場優勢 (+1.5 eWAR)**。"
    if is_ws_mode: msg += " 🏆 **[世界大賽模式] 已強制套用季後賽手感加權！**"
    if is_laa_opener or is_lad_opener: msg += " ⚠️ **偵測到牛棚假先發 (生涯先發比例過低)，該隊勝率已遭系統大幅下修。**"
    st.caption(msg)

    st.markdown("---")
    st.subheader("📈 FanGraphs 魔球長期走勢與預期勝率分析 (Monte Carlo & Pyth%)")
    import altair as alt

    def get_team_pyth_stats(team, season_prefix):
        df_b = st.session_state.get('df_b_raw', pd.DataFrame())
        df_p = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_b.empty and df_p.empty: return 0, 0, 0
        
        t_b = df_b[(df_b['球隊']==team) & df_b['賽事階段'].astype(str).str.contains(season_prefix, regex=False)] if season_prefix else df_b[df_b['球隊']==team]
        t_p = df_p[(df_p['球隊']==team) & df_p['賽事階段'].astype(str).str.contains(season_prefix, regex=False)] if season_prefix else df_p[df_p['球隊']==team]
        
        rs = pd.to_numeric(t_b['得分'], errors='coerce').sum() if not t_b.empty else 0
        ra = pd.to_numeric(t_p['失分'], errors='coerce').sum() if not t_p.empty else 0
        games = t_p['賽事階段'].nunique() if not t_p.empty else 0
        return rs, ra, games

    curr_s_str = wr_season.split(" ")[1] if wr_season != "十年總成績" else ""
    curr_prefix = f"[S{curr_s_str}]" if curr_s_str else ""
    
    laa_rs_c, laa_ra_c, laa_g_c = get_team_pyth_stats("LAA", curr_prefix)
    lad_rs_c, lad_ra_c, lad_g_c = get_team_pyth_stats("LAD", curr_prefix)
    
    def calc_pyth(rs, ra):
        if rs + ra == 0: return 0.5
        return (rs**1.83) / (rs**1.83 + ra**1.83)

    pyth_laa_curr = calc_pyth(laa_rs_c, laa_ra_c)
    pyth_lad_curr = calc_pyth(lad_rs_c, lad_ra_c)

    if laa_g_c < 5 and curr_s_str and int(curr_s_str) > 1:
        prev_prefix = f"[S{int(curr_s_str)-1}]"
        laa_rs_p, laa_ra_p, _ = get_team_pyth_stats("LAA", prev_prefix)
        lad_rs_p, lad_ra_p, _ = get_team_pyth_stats("LAD", prev_prefix)
        pyth_laa_prev = calc_pyth(laa_rs_p, laa_ra_p)
        
        weight = laa_g_c / 5.0
        true_prob_laa = pyth_laa_curr * weight + pyth_laa_prev * (1 - weight)
    else:
        true_prob_laa = pyth_laa_curr

    def calc_true_game_prob(laa_home):
        p = true_prob_laa + (0.04 if laa_home else -0.04)
        return max(0.05, min(0.95, p))

    df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
    df_b_full = st.session_state.get('df_b_raw', pd.DataFrame())

    def get_game_score_str(stage_name):
        if df_b_full.empty: return "無比分"
        b_sub = df_b_full[df_b_full['賽事階段'] == stage_name]
        r_laa = pd.to_numeric(b_sub[b_sub['球隊']=='LAA']['得分'], errors='coerce').sum() if not b_sub.empty else 0
        r_lad = pd.to_numeric(b_sub[b_sub['球隊']=='LAD']['得分'], errors='coerce').sum() if not b_sub.empty else 0
        return f"{int(r_laa)} : {int(r_lad)}"

    g_order = [f"G{i}" for i in range(12)]

    if is_ws_mode:
        # ==========================================
        # 🏆 模式 A：世界大賽動態奪冠機率圖 (2-3-2 賽制)
        # ==========================================
        actual_ws_winners = []
        actual_ws_stages = []
        if not df_p_full.empty:
            ws_df_temp = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(f"{curr_prefix} 世界大賽", regex=False)]
            for stage, group in ws_df_temp.groupby('賽事階段', sort=False):
                g_sorted = group.sort_values('時間戳記')
                if any('勝' in str(x) for x in g_sorted[g_sorted['球隊']=='LAA']['勝敗'].values): actual_ws_winners.append("LAA")
                elif any('勝' in str(x) for x in g_sorted[g_sorted['球隊']=='LAD']['勝敗'].values): actual_ws_winners.append("LAD")
                actual_ws_stages.append(stage)

        laa_ws_wins_temp = actual_ws_winners.count("LAA")
        lad_ws_wins_temp = actual_ws_winners.count("LAD")

        st.markdown(f"##### 實時戰況系列賽比分：🔴 LAA **{laa_ws_wins_temp}** : **{lad_ws_wins_temp}** 🔵 LAD")
        
        ws_hfa_team = "LAA"
        if wr_season != "十年總成績":
            current_rs_prefix = f"{curr_prefix} 例行賽"
            laa_rs_wins, lad_rs_wins = 0, 0
            laa_rs_r, laa_rs_ra, lad_rs_r, lad_rs_ra = 0, 0, 0, 0
            
            if not df_p_full.empty:
                t_p_rs = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(current_rs_prefix, regex=False)]
                for stage, group in t_p_rs.groupby('賽事階段', sort=False):
                    if any('勝' in str(x) for x in group[group['球隊']=='LAA']['勝敗'].values): laa_rs_wins += 1
                    if any('勝' in str(x) for x in group[group['球隊']=='LAD']['勝敗'].values): lad_rs_wins += 1
                laa_rs_ra = pd.to_numeric(t_p_rs[t_p_rs['球隊']=='LAA']['失分'], errors='coerce').sum()
                lad_rs_ra = pd.to_numeric(t_p_rs[t_p_rs['球隊']=='LAD']['失分'], errors='coerce').sum()
                
            if not df_b_full.empty:
                t_b_rs = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(current_rs_prefix, regex=False)]
                laa_rs_r = pd.to_numeric(t_b_rs[t_b_rs['球隊']=='LAA']['得分'], errors='coerce').sum()
                lad_rs_r = pd.to_numeric(t_b_rs[t_b_rs['球隊']=='LAD']['得分'], errors='coerce').sum()
                
            if laa_rs_wins > lad_rs_wins: ws_hfa_team = "LAA"
            elif lad_rs_wins > laa_rs_wins: ws_hfa_team = "LAD"
            else: ws_hfa_team = "LAA" if (laa_rs_r - laa_rs_ra) >= (lad_rs_r - lad_rs_ra) else "LAD"

        seed_string = f"WS_{wr_season}_{laa_ws_wins_temp}_{lad_ws_wins_temp}"
        random.seed(sum(ord(c) for c in seed_string) % 999999)

        def is_laa_home_in_ws(g_num, hfa):
            return (g_num in [1, 2, 6, 7]) if hfa == "LAA" else not (g_num in [1, 2, 6, 7])

        def get_ws_odds_at(w_l, w_d):
            if w_l >= 4: return 1.0, 0.0
            if w_d >= 4: return 0.0, 1.0
            s_l, s_d = 0, 0
            for _ in range(3000):
                c_l, c_d = w_l, w_d
                g = w_l + w_d
                while c_l < 4 and c_d < 4:
                    g += 1
                    if random.random() < calc_true_game_prob(is_laa_home_in_ws(g, ws_hfa_team)): c_l += 1
                    else: c_d += 1
                if c_l == 4: s_l += 1
                else: s_d += 1
            return s_l/3000.0, s_d/3000.0

        chart_data = []
        cur_l, cur_d = 0, 0
        p_l, p_d = get_ws_odds_at(0, 0)
        chart_data.append({"Game": "G0", "Team": "LAA", "Prob": p_l, "Type": "實績", "Score": "系列賽開打"})
        chart_data.append({"Game": "G0", "Team": "LAD", "Prob": p_d, "Type": "實績", "Score": "系列賽開打"})

        for idx, winner in enumerate(actual_ws_winners):
            g_num = idx + 1
            if winner == "LAA": cur_l += 1
            else: cur_d += 1
            p_l, p_d = get_ws_odds_at(cur_l, cur_d)
            s_str = get_game_score_str(actual_ws_stages[idx])
            chart_data.append({"Game": f"G{g_num}", "Team": "LAA", "Prob": p_l, "Type": "實績", "Score": s_str})
            chart_data.append({"Game": f"G{g_num}", "Team": "LAD", "Prob": p_d, "Type": "實績", "Score": s_str})

        final_l_odds, final_d_odds = p_l, p_d
        game_ends = {4:0, 5:0, 6:0, 7:0}
        for _ in range(10000):
            c_l, c_d = laa_ws_wins_temp, lad_ws_wins_temp
            g = c_l + c_d
            while c_l < 4 and c_d < 4:
                g += 1
                if random.random() < calc_true_game_prob(is_laa_home_in_ws(g, ws_hfa_team)): c_l += 1
                else: c_d += 1
            game_ends[g] += 1

        curr_g = len(actual_ws_winners)
        if curr_g < 7 and laa_ws_wins_temp < 4 and lad_ws_wins_temp < 4:
            chart_data.append({"Game": f"G{curr_g}", "Team": "LAA", "Prob": final_l_odds, "Type": "預測", "Score": "實績起點"})
            chart_data.append({"Game": f"G{curr_g}", "Team": "LAD", "Prob": final_d_odds, "Type": "預測", "Score": "實績起點"})
            for g_num in range(curr_g + 1, 8):
                chart_data.append({"Game": f"G{g_num}", "Team": "LAA", "Prob": final_l_odds, "Type": "預測", "Score": "未來賽事"})
                chart_data.append({"Game": f"G{g_num}", "Team": "LAD", "Prob": final_d_odds, "Type": "預測", "Score": "未來賽事"})

        st.caption(f"🏆 **經判定本季世界大賽主場優勢方：{ws_hfa_team}** (總決賽採 2-3-2 制度)")
        df_chart = pd.DataFrame(chart_data)
        
        base = alt.Chart(df_chart).encode(
            x=alt.X('Game:O', sort=g_order, title='賽事進度', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Prob:Q', title='預期奪冠率', axis=alt.Axis(format='%'), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('Team:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=alt.Legend(title="球隊")),
            strokeDash=alt.StrokeDash('Type:N', scale=alt.Scale(domain=['實績', '預測'], range=[[1,0], [5,5]]), legend=alt.Legend(title="數據狀態")),
            tooltip=[
                alt.Tooltip('Team:N', title='球隊'),
                alt.Tooltip('Game:N', title='進度'),
                alt.Tooltip('Prob:Q', title='奪冠機率', format='.1%'),
                alt.Tooltip('Score:N', title='該場比分 (LAA:LAD)')
            ]
        ).properties(height=350)
        
        line = base.mark_line(point=True, strokeWidth=3).interactive(bind_y=False, bind_x=False)
        st.altair_chart(line, use_container_width=True)

        if laa_ws_wins_temp >= 4 or lad_ws_wins_temp >= 4:
            st.success("🎉 本賽季世界大賽已圓滿結束，冠軍金盃已誕生！")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("LAA 奪冠總機率 (Playoff Odds)", f"{(final_l_odds*100.0):.1f}%")
            c2.metric("LAD 奪冠總機率 (Playoff Odds)", f"{(final_d_odds*100.0):.1f}%")
            most_likely_games = max(game_ends, key=game_ends.get)
            c3.metric("預測此系列賽幾場結束", f"Game {most_likely_games}", f"該場完賽機率 {(game_ends[most_likely_games]/100.0):.1f}%")

    else:
        # ==========================================
        # 📅 模式 B：10 場例行賽 ROS 預期賽季終局總勝場圖
        # ==========================================
        rs_game1_home_team = "LAA" 
        if curr_s_str and int(curr_s_str) > 1:
            prev_season_prefix = f"[S{int(curr_s_str) - 1}] 世界大賽"
            if not df_p_full.empty:
                prev_ws_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prev_season_prefix, regex=False)]
                if not prev_ws_df.empty:
                    laa_prev_w = sum(1 for _, g in prev_ws_df.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAA']['勝敗'].values))
                    lad_prev_w = sum(1 for _, g in prev_ws_df.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAD']['勝敗'].values))
                    if lad_prev_w > laa_prev_w: rs_game1_home_team = "LAA"
                    elif laa_prev_w > lad_prev_w: rs_game1_home_team = "LAD"

        actual_rs_winners = []
        actual_rs_stages = []
        current_rs_prefix = f"{curr_prefix} 例行賽"
        if not df_p_full.empty:
            rs_df_temp = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(current_rs_prefix, regex=False)]
            for stage, group in rs_df_temp.groupby('賽事階段', sort=False):
                g_sorted = group.sort_values('時間戳記')
                if any('勝' in str(x) for x in g_sorted[g_sorted['球隊']=='LAA']['勝敗'].values): actual_rs_winners.append("LAA")
                elif any('勝' in str(x) for x in g_sorted[g_sorted['球隊']=='LAD']['勝敗'].values): actual_rs_winners.append("LAD")
                actual_rs_stages.append(stage)
        
        rs_games_played = len(actual_rs_winners)
        laa_actual_rs_wins = actual_rs_winners.count("LAA")
        lad_actual_rs_wins = actual_rs_winners.count("LAD")
        
        # ✨ 升級：計算在任何指定時間點，基於已拿下的勝場，預期賽末的最終勝場數
        def get_ros_expected_wins(current_l_wins, current_d_wins, games_played):
            exp_l = current_l_wins
            for g in range(games_played + 1, 11):
                laa_home_game = (g % 2 == 1) if rs_game1_home_team == "LAA" else (g % 2 == 0)
                exp_l += calc_true_game_prob(laa_home_game)
            return exp_l, 10.0 - exp_l

        chart_data = []
        cur_l, cur_d = 0, 0
        
        # G0 (開季前的最初預期)
        exp_l, exp_d = get_ros_expected_wins(0, 0, 0)
        chart_data.append({"Game": "G0", "Team": "LAA", "Wins": exp_l, "Type": "實績", "Score": "球季開打"})
        chart_data.append({"Game": "G0", "Team": "LAD", "Wins": exp_d, "Type": "實績", "Score": "球季開打"})

        # G1 至目前已完賽的場次，計算每一場打完後的最新「預期總勝場」
        for idx, winner in enumerate(actual_rs_winners):
            g_num = idx + 1
            if winner == "LAA": cur_l += 1
            else: cur_d += 1
            s_str = get_game_score_str(actual_rs_stages[idx])
            
            exp_l, exp_d = get_ros_expected_wins(cur_l, cur_d, g_num)
            chart_data.append({"Game": f"G{g_num}", "Team": "LAA", "Wins": exp_l, "Type": "實績", "Score": s_str})
            chart_data.append({"Game": f"G{g_num}", "Team": "LAD", "Wins": exp_d, "Type": "實績", "Score": s_str})
            
        # 未來賽事：由於期望值的特性，未來的滾動預測線將是一條水平延伸的虛線，總和始終等於 10
        if rs_games_played < 10:
            chart_data.append({"Game": f"G{rs_games_played}", "Team": "LAA", "Wins": exp_l, "Type": "預測", "Score": "實績起點"})
            chart_data.append({"Game": f"G{rs_games_played}", "Team": "LAD", "Wins": exp_d, "Type": "預測", "Score": "實績起點"})
            
            for g_num in range(rs_games_played + 1, 11):
                chart_data.append({"Game": f"G{g_num}", "Team": "LAA", "Wins": exp_l, "Type": "預測", "Score": "未來賽事"})
                chart_data.append({"Game": f"G{g_num}", "Team": "LAD", "Wins": exp_d, "Type": "預測", "Score": "未來賽事"})

        st.caption(f"🏟️ **例行賽排程設定**：上季世界大賽亞軍 **{rs_game1_home_team}** 自動獲得 G1 主場，後續主客精準交替。")
        df_chart = pd.DataFrame(chart_data)
        
        base = alt.Chart(df_chart).encode(
            x=alt.X('Game:O', sort=g_order, title='賽事進度', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Wins:Q', title='預估賽季最終總勝場', scale=alt.Scale(domain=[0, 10])),
            color=alt.Color('Team:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=alt.Legend(title="球隊")),
            strokeDash=alt.StrokeDash('Type:N', scale=alt.Scale(domain=['實績', '預測'], range=[[1,0], [5,5]]), legend=alt.Legend(title="數據狀態")),
            tooltip=[
                alt.Tooltip('Team:N', title='球隊'),
                alt.Tooltip('Game:N', title='進度'),
                alt.Tooltip('Wins:Q', title='賽季預期總勝場', format='.1f'),
                alt.Tooltip('Score:N', title='該場比分 (LAA:LAD)')
            ]
        ).properties(height=350)
        
        line = base.mark_line(point=True, strokeWidth=3).interactive(bind_y=False, bind_x=False)
        st.altair_chart(line, use_container_width=True)

        seed_string_rs = f"RS_{wr_season}_{rs_games_played}"
        random.seed(sum(ord(c) for c in seed_string_rs) % 999999)
        laa_hfa_sims = 0
        for _ in range(10000):
            l_w, d_w = laa_actual_rs_wins, lad_actual_rs_wins
            for g in range(rs_games_played + 1, 11):
                laa_home_this_game = (g % 2 == 1) if rs_game1_home_team == "LAA" else (g % 2 == 0)
                if random.random() < calc_true_game_prob(laa_home_this_game): l_w += 1
                else: d_w += 1
            if l_w > d_w: laa_hfa_sims += 1
            elif l_w == d_w: laa_hfa_sims += 0.5 

        st.markdown(f"##### 實時累積勝場：🔴 LAA **{laa_actual_rs_wins}** : **{lad_actual_rs_wins}** 🔵 LAD (目前已賽 **{rs_games_played}** 場)")
        c1, c2, c3 = st.columns(3)
        c1.metric("LAA 賽季末預估總勝場", f"{exp_l:.1f} 勝", f"已獲的 {laa_actual_rs_wins} 勝保底")
        c2.metric("LAD 賽季末預估總勝場", f"{exp_d:.1f} 勝", f"已獲的 {lad_actual_rs_wins} 勝保底")
        c3.metric("LAA 奪得季後賽主場優勢率", f"{(laa_hfa_sims/100.0):.1f}%", "含5勝5敗比得分期望")

    st.markdown("---")
    
    if st.button("🎙️ 產生賽前深度戰報 (含數據預測與球評講評)", type="primary", use_container_width=True, key="btn_report_tab4_v48_final"):
        if 'save_settings' in globals(): save_settings()
        with st.spinner("AI 球評正在運算高階 Sabermetrics 數據與戰術推演..."):
            time.sleep(1.5)
            df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
            
            def get_league_era(p_stats_dict):
                all_ip = sum([val['IP'] for t, plrs in p_stats_dict.items() for p, val in plrs.items()])
                all_er = sum([val['ERA'] * val['IP'] for t, plrs in p_stats_dict.items() for p, val in plrs.items() if val['ERA'] != float('inf')])
                return (all_er / all_ip) if all_ip > 0 else 4.50

            current_lg_era = get_league_era(curr_p_stats)

            st.markdown(f"## 📰 【{wr_season}】 賽前魔球戰報")
            
            base_b_stats = reg_b_stats if is_ws_mode else curr_b_stats
            base_p_stats = reg_p_stats if is_ws_mode else curr_p_stats
            all_b_ewar = {p: v['eWAR'] for t, plrs in base_b_stats.items() for p, v in plrs.items() if v.get('PA', 0) >= dyn_pa_limit}
            all_p_ewar = {p: v['eWAR'] for t, plrs in base_p_stats.items() for p, v in plrs.items() if v.get('IP', 0) >= dyn_ip_limit}
            mvp_top3 = sorted(all_b_ewar, key=all_b_ewar.get, reverse=True)[:3] if all_b_ewar else []
            cy_top3 = sorted(all_p_ewar, key=all_p_ewar.get, reverse=True)[:3] if all_p_ewar else []

            curr_laa_batters = [st.session_state.lineups['LAA'][i] for i in range(9) if st.session_state.lineups['LAA'][i] != "未指定"]
            curr_lad_batters = [st.session_state.lineups['LAD'][i] for i in range(9) if st.session_state.lineups['LAD'][i] != "未指定"]
            laa_sp = st.session_state.pitchers.get("LAA", "未指定")
            lad_sp = st.session_state.pitchers.get("LAD", "未指定")

            st.markdown("### 🏟️ 球隊近況與牛棚防線")
            
            def get_team_streak_str(team_name, ws_only=False):
                df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
                if df_p_full.empty: return "尚無賽事"
                if wr_season != "十年總成績":
                    s_num = wr_season.split(" ")[1]
                    prefix = f"[S{s_num}]"
                    df_p_season = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)]
                else:
                    df_p_season = df_p_full

                if ws_only and wr_season != "十年總成績":
                    t_df = df_p_season[(df_p_season['球隊'] == team_name) & (df_p_season['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].sort_values(by='時間戳記', ascending=True)
                else:
                    t_df = df_p_season[df_p_season['球隊'] == team_name].sort_values(by='時間戳記', ascending=True)
                    
                results = []
                for stage, group in t_df.groupby('賽事階段', sort=False):
                    res = group['勝敗'].astype(str).values
                    if any('勝' in x for x in res): results.append('W')
                    elif any('敗' in x for x in res): results.append('L')
                    else: results.append('D') 
                if not results: return "尚無勝負"
                streak_type = results[-1]
                streak_count = 0
                for r in reversed(results):
                    if r == streak_type: streak_count += 1
                    else: break
                return f"**{streak_count} 連勝** 🔥" if streak_type == 'W' else f"**{streak_count} 連敗** 🧊" if streak_type == 'L' else f"**{streak_count} 連和** 🤝"

            def get_bullpen_era_val(team_name, ws_only=False):
                df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
                if df_p_full.empty: return None
                if ws_only and wr_season != "十年總成績":
                    s_num = wr_season.split(" ")[1]
                    prefix = f"[S{s_num}] 世界大賽"
                else:
                    prefix = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
                    
                sub_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_full
                t_df = sub_df[sub_df['球隊'] == team_name].sort_values(by='時間戳記', ascending=True)
                if t_df.empty: return None
                
                bp_outs, bp_er = 0, 0
                for stage, group in t_df.groupby('賽事階段', sort=False):
                    g_sorted = group.sort_values('時間戳記', ascending=True)
                    if len(g_sorted) > 1:
                        bp_group = g_sorted.iloc[1:] 
                        bp_outs += (pd.to_numeric(bp_group['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(bp_group['局數(出局數)'], errors='coerce').fillna(0)).sum()
                        bp_er += pd.to_numeric(bp_group['自責分'], errors='coerce').fillna(0).sum()
                return (bp_er * 9) / (bp_outs / 3.0) if (bp_outs / 3.0) > 0 else 0.0

            def generate_team_momentum(team):
                streak = get_team_streak_str(team, is_ws_mode)
                bp_era = get_bullpen_era_val(team, is_ws_mode)
                text = f"**【{team} 戰力概況】**\n- **近期氣勢**：目前處於 {streak}。\n"
                if bp_era is not None:
                    text += f"- **後援安定度**：牛棚 ERA 為 **{bp_era:.2f}**。"
                    if bp_era > current_lg_era + 1.0: text += " 🚨 **(放火警報)** 領先 3 分都不安全！\n\n"
                    elif bp_era < current_lg_era - 1.0: text += " 🔒 **(鐵壁防線)** 領先進入後半段幾乎等於比賽結束。\n\n"
                    else: text += " 調度時機將是關鍵。\n\n"
                else: text += "- **牛棚安定度**：尚無數據。\n\n"
                return text
                
            st.info(generate_team_momentum(away_team) + generate_team_momentum(home_team))
            
            st.markdown("### 🥎 投手丘上的進階剖析")
            def get_pitcher_insights(team, sp, stats_dict, prev_dict, reg_dict, ws_dict, is_ws_mode):
                if not sp or sp == "未指定" or sp not in stats_dict.get(team, {}): return ""
                s = stats_dict[team][sp]
                era, fip = s['ERA'], s['FIP']
                
                all_ip = sum([val['IP'] for t, plrs in stats_dict.items() for p, val in plrs.items()])
                all_era_sum = sum([val['ERA'] * val['IP'] for t, plrs in stats_dict.items() for p, val in plrs.items() if val['ERA'] != float('inf')])
                lg_era = all_era_sum / all_ip if all_ip > 0 else 4.00
                all_np = sum([val.get('NP', 0) for t, plrs in stats_dict.items() for p, val in plrs.items()])
                lg_pip = all_np / all_ip if all_ip > 0 else 15.0
                
                qualified_pitchers_eras = [val['ERA'] for t, plrs in stats_dict.items() for p, val in plrs.items() if val['IP'] >= dyn_ip_limit]
                all_eras = sorted(list(set(qualified_pitchers_eras)))
                rank_str = f"聯盟第 {all_eras.index(era) + 1}" if s['IP'] >= dyn_ip_limit and era in all_eras else "未達局數門檻"
                
                era_str = "∞" if era == float('inf') else f"{era:.2f}"
                fip_str = "∞" if fip == float('inf') else f"{fip:.2f}"
                
                trend = ""
                if wr_season != "十年總成績":
                    curr_s = int(wr_season.split(" ")[1])
                    if curr_s > 1:
                        p_era = prev_dict.get(team, {}).get(sp, {}).get('ERA', None)
                        if p_era is not None:
                            p_era_str = "∞" if p_era == float('inf') else f"{p_era:.2f}"
                            trend = f"(去年 ERA {p_era_str})"
                
                insight = f"**【{team} 先發】 {sp}**\n- **數據**：ERA **{era_str} ({rank_str})** {trend} | eWAR **{s['eWAR']:.1f}**\n"
                insight += f"- **壓制與效率**：WHIP **{s['WHIP']:.2f}** | K/9 **{s['K/9']:.2f}** | 每局用球 (P/IP) **{s['P/IP']:.1f}** 球\n"
                
                if s['P/IP'] >= lg_pip + 4.0 and era < lg_era: insight += f"- ⚠️ **體力消耗警報**：用球數高達 {s['P/IP']:.1f} 球 (平均 {lg_pip:.1f})，容易陷入纏鬥，今晚可能投不長。\n\n"
                elif s['P/IP'] > 0 and s['P/IP'] <= lg_pip - 3.0 and era < lg_era: insight += f"- ⚡ **極致省球大師**：每局平均只需 {s['P/IP']:.1f} 球！極具侵略性能拉長投球局數。\n\n"

                if is_ws_mode and sp in ws_dict.get(team, {}) and ws_dict[team][sp]['IP'] > 1.0:
                    ws_era = ws_dict[team][sp]['ERA']
                    reg_era = reg_dict.get(team, {}).get(sp, {}).get('ERA', 0)
                    ws_era_str, reg_era_str = "∞" if ws_era == float('inf') else f"{ws_era:.2f}", "∞" if reg_era == float('inf') else f"{reg_era:.2f}"
                    if ws_era < 2.5 and reg_era > 4.0: insight += f"- 🌟 **季後賽賽揚 ({sp})**：例行賽防禦率高達 {reg_era_str}，一進世界大賽直接鬼神化 ({ws_era_str})！\n\n"
                    elif ws_era > 5.5 and reg_era < 3.5: insight += f"- 🥶 **大賽軟手症 ({sp})**：例行賽神級表現，到了世界大賽完全失常 (ERA {ws_era_str})！\n\n"
                    elif ws_era <= 3.0 and reg_era <= 3.0: insight += f"- 👑 **大場面王牌 ({sp})**：無論例行賽或世界大賽 (WS ERA {ws_era_str})，壓制力始終如一。\n\n"
                    return insight 
                
                fip_diff = fip - era
                if era >= current_lg_era + 1.5 and fip >= current_lg_era + 1.5: insight += f"- 🚨 **發球機警報 (狀況慘烈)**：防禦率 ({era_str}) 還是 FIP ({fip_str}) 都突破天際，今晚隨時會被打退場。\n\n"
                elif era <= current_lg_era - 1.5 and fip <= current_lg_era - 1.5: insight += f"- 👑 **鬼神級王牌 (真材實料)**：進階數據 FIP 更是只有 {fip_str}！今晚對手只能自求多福。\n\n"
                elif fip_diff < -0.5:
                    if era > current_lg_era: insight += random.choice([f"- 💡 **悲情王牌 (被守備雷到)**：帳面 ERA 看似平凡，但 FIP 僅 {fip_str}！失分多半是非戰之罪。\n\n", f"- 📉 **進階數據平反**：別被 {era_str} 的防禦率騙了，FIP 只有 {fip_str}，投球內容相當優異。\n\n"])
                    else: insight += f"- 🛡️ **深不見底的壓制力**：防禦率 {era_str}，FIP ({fip_str}) 還能更低！把命運完全掌握在自己手中。\n\n"
                elif fip_diff > 0.5:
                    if era < current_lg_era: insight += random.choice([f"- 🚨 **強運校正警報**：防禦率 {era_str} 看似無懈可擊，但 FIP 高達 {fip_str}。靠完美的守備與運氣撐，有核爆風險。\n\n", f"- ⚠️ **虛假繁榮**：ERA 只有 {era_str}，但進階數據 FIP 殘酷地指出他的真實壓制力並不理想。\n\n"])
                    else: insight += f"- 💣 **雪上加霜**：防禦率已經不理想，FIP ({fip_str}) 更是慘烈。過度依賴守備，狀況堪憂。\n\n"
                else: insight += f"- ⚖️ **真金不怕火煉**：FIP ({fip_str}) 與 ERA 極為吻合，帳面成績就是真實硬實力。\n\n"
                return insight
                
            p_rep = ""
            if away_team == "LAA" and laa_sp != "未指定": p_rep += get_pitcher_insights("LAA", laa_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            elif away_team == "LAD" and lad_sp != "未指定": p_rep += get_pitcher_insights("LAD", lad_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            
            if home_team == "LAA" and laa_sp != "未指定": p_rep += get_pitcher_insights("LAA", laa_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            elif home_team == "LAD" and lad_sp != "未指定": p_rep += get_pitcher_insights("LAD", lad_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            if p_rep: st.success(p_rep)

            st.markdown("### 💥 打線雷達掃描與教練點評")
            def get_lineup_insights(team, batters, stats_dict, reg_dict, ws_dict, is_ws_mode):
                team_stats = stats_dict.get(team, {})
                valid_b = [b for b in batters if b in team_stats]
                if not valid_b: return ""
                insights = [f"**【{team} 打線掃描】**"]
                used_players = set()
                
                all_pa = sum([v.get('PA', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                all_ab = sum([v.get('AB', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                all_k = sum([v.get('K', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                all_bb = sum([v.get('BB', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                all_hr = sum([v.get('HR', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                all_h = sum([v.get('H', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])

                lg_k_pct = (all_k / all_pa * 100) if all_pa > 0 else 20.0
                lg_bb_pct = (all_bb / all_pa * 100) if all_pa > 0 else 8.0
                iso_sum = sum([v.get('ISO', 0) * v.get('AB', 0) for t, plrs in stats_dict.items() for p, v in plrs.items()])
                lg_iso = iso_sum / all_ab if all_ab > 0 else 0.150
                babip_num = all_h - all_hr
                babip_den = all_ab - all_k - all_hr
                lg_babip = babip_num / babip_den if babip_den > 0 else 0.300
                
                if is_ws_mode:
                    for b in batters:
                        if b in used_players: continue
                        ws_ops = ws_dict.get(team, {}).get(b, {}).get('wRC+', 0)
                        ws_pa = ws_dict.get(team, {}).get(b, {}).get('PA', 0)
                        reg_ops = reg_dict.get(team, {}).get(b, {}).get('wRC+', 0)
                        
                        if ws_pa >= 3:
                            if ws_ops >= 140 and reg_ops <= 100:
                                insights.append(f"- 🌟 **十月先生 ({b})**：例行賽裝死 (wRC+ {reg_ops:.0f})，季後賽甦醒的大賽型球員 (WS wRC+ {ws_ops:.0f})！")
                                used_players.add(b)
                            elif ws_ops <= 60 and reg_ops >= 120:
                                insights.append(f"- 🥶 **大賽軟手症 ({b})**：例行賽猛如虎 (wRC+ {reg_ops:.0f})，世界大賽卻急需找回手感 (WS wRC+ {ws_ops:.0f})。")
                                used_players.add(b)
                
                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= dyn_pa_limit]
                if rem_batters:
                    best_b = max(rem_batters, key=lambda x: team_stats[x]['wRC+'])
                    best_ops = team_stats[best_b]['wRC+']
                    all_ops = sorted([v['wRC+'] for t, plrs in stats_dict.items() for p, v in plrs.items() if v['PA'] >= dyn_pa_limit], reverse=True)
                    rank = all_ops.index(best_ops) + 1 if best_ops in all_ops else "-"
                    if best_ops >= 200:
                        insights.append(f"- ☄️ **神話級打者 ({best_b})**：wRC+ 高達 {best_ops:.0f} (聯盟第 {rank})，完全超越聯盟維度的外星人，建議對手直接保送。")
                        used_players.add(best_b)
                    elif best_ops >= 150:
                        insights.append(f"- 🌟 **頂級核心 ({best_b})**：wRC+ {best_ops:.0f} (聯盟第 {rank})，是全隊最可靠的火力輸出，對方投手最好選擇避開他。")
                        used_players.add(best_b)
                    elif best_ops >= 120:
                        insights.append(f"- 🔥 **進攻中樞 ({best_b})**：wRC+ {best_ops:.0f} (聯盟第 {rank})，狀態絕佳的打線箭頭。")
                        used_players.add(best_b)
                
                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= dyn_pa_limit]
                if rem_batters:
                    lucky_b = max(rem_batters, key=lambda x: team_stats[x]['BABIP'])
                    unlucky_b = min(rem_batters, key=lambda x: team_stats[x]['BABIP'])
                    if team_stats[lucky_b]['BABIP'] >= lg_babip + 0.200:
                        insights.append(f"- 🎰 **魔法安打 ({lucky_b})**：BABIP 高達 {team_stats[lucky_b]['BABIP']:.3f}！連隨便碰都會變安打，極度強運。")
                        used_players.add(lucky_b)
                    elif team_stats[lucky_b]['BABIP'] >= lg_babip + 0.100:
                        insights.append(f"- 🍀 **天選之人 ({lucky_b})**：BABIP {team_stats[lucky_b]['BABIP']:.3f}，運氣也是實力的一部份！")
                        used_players.add(lucky_b)
                    if unlucky_b not in used_players:
                        if team_stats[unlucky_b]['BABIP'] <= lg_babip - 0.150:
                            insights.append(f"- 🐈‍⬛ **地獄倒楣鬼 ({unlucky_b})**：BABIP 慘到只有 {team_stats[unlucky_b]['BABIP']:.3f}，打得再強勁也會找手套，建議賽前去拜拜。")
                            used_players.add(unlucky_b)

                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= 3]
                if rem_batters:
                    blind_b = max(rem_batters, key=lambda x: team_stats[x]['K%'])
                    if team_stats[blind_b]['K%'] >= lg_k_pct + 20.0:
                        insights.append(f"- 🌪️ **人體電風扇 ({blind_b})**：K% 高達 {team_stats[blind_b]['K%']:.1f}%！選球徹底迷失，變化球隨便騙隨便揮。")
                        used_players.add(blind_b)
                
                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= 3]
                if rem_batters:
                    eye_b = max(rem_batters, key=lambda x: team_stats[x]['BB%'])
                    if team_stats[eye_b]['BB%'] >= lg_bb_pct + 10.0:
                        insights.append(f"- 👁️ **神之眼 ({eye_b})**：BB% 達 {team_stats[eye_b]['BB%']:.1f}%！選球精準到讓投手懷疑人生。")
                        used_players.add(eye_b)

                rem_batters = [b for b in valid_b if b not in used_players]
                if rem_batters:
                    iso_b = max(rem_batters, key=lambda x: team_stats[x]['ISO'])
                    if team_stats[iso_b]['ISO'] >= lg_iso + 0.400:
                        insights.append(f"- ☄️ **外星級神力 ({iso_b})**：純長打率 ISO {team_stats[iso_b]['ISO']:.3f}！這不是重砲，這是把棒球當高爾夫球打的外星怪物！")
                        used_players.add(iso_b)
                    elif team_stats[iso_b]['ISO'] >= lg_iso + 0.200:
                        insights.append(f"- 🌋 **怪力重砲 ({iso_b})**：純長打率 ISO {team_stats[iso_b]['ISO']:.3f}！隨時能把球轟出球場。")
                        used_players.add(iso_b)
                
                for i, b in enumerate(batters):
                    if b not in team_stats or b in used_players: continue
                    ops, order = team_stats[b]['wRC+'], i + 1
                    if order <= 3 and ops <= 60 and team_stats[b]['PA'] >= 5:
                        insights.append(f"- 🥶 **嚴重冰冷 ({b})**：wRC+ 慘到只有 {ops:.0f} 卻卡在第 {order} 棒，這簡直是進攻斷點。")
                    elif order >= 7 and ops >= 150:
                        insights.append(f"- 🥷 **核彈級伏兵 ({b})**：wRC+ {ops:.0f} 的怪物竟然埋伏在第 {order} 棒，這打線深不見底！")

                if len(insights) == 1: insights.append("- ℹ️ 目前樣本數較少，戰術雷達尚未偵測到極端表現。")
                return "\n".join(insights) + "\n\n"
                
            b_rep = ""
            if away_team == "LAA" and curr_laa_batters: b_rep += get_lineup_insights("LAA", curr_laa_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)
            elif away_team == "LAD" and curr_lad_batters: b_rep += get_lineup_insights("LAD", curr_lad_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)
            
            if home_team == "LAA" and curr_laa_batters: b_rep += get_lineup_insights("LAA", curr_laa_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)
            elif home_team == "LAD" and curr_lad_batters: b_rep += get_lineup_insights("LAD", curr_lad_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)

            if b_rep: st.warning(b_rep)

            st.markdown("### 🧠 賽前戰況總結 (轉播台視角)")
            tactics = []
            bp_laa = get_bullpen_era_val("LAA", is_ws_mode) or 0.0
            bp_lad = get_bullpen_era_val("LAD", is_ws_mode) or 0.0
            
            if is_ws_mode:
                laa_ws_wins, lad_ws_wins = 0, 0
                df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
                if not df_p_full.empty:
                    ws_df = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(f"[S{wr_season.split(' ')[1]}] 世界大賽", regex=False))]
                    for stage, group in ws_df.groupby('賽事階段', sort=False):
                        if any('勝' in str(x) for x in group[group['球隊']=='LAA']['勝敗'].values): laa_ws_wins += 1
                        if any('勝' in str(x) for x in group[group['球隊']=='LAD']['勝敗'].values): lad_ws_wins += 1

                if laa_ws_wins == 3 and lad_ws_wins == 3: tactics.append("🔥 **【Game 7 生死戰】** 「各位觀眾，歡迎來到世界大賽 Game 7！贏家通吃，輸家回家！今天沒有保留體力的空間，連王牌先發隨時都會從牛棚走出來，這將是載入史冊的一役！」")
                elif laa_ws_wins == 3: tactics.append(f"🏆 **【聽牌之戰】** 「LAA 目前以 {laa_ws_wins}:{lad_ws_wins} 取得絕對聽牌優勢！LAD 已經被逼到了懸崖邊緣，今晚必定精銳盡出，試圖在{'主場' if home_team=='LAD' else '客場'}延長戰線！」")
                elif lad_ws_wins == 3: tactics.append(f"🏆 **【聽牌之戰】** 「LAD 帶著 {lad_ws_wins}:{laa_ws_wins} 的優勢來到今晚！LAA 退無可退，這場背水一戰絕對會是火花四濺、傾盡所有！」")
                elif laa_ws_wins == lad_ws_wins and laa_ws_wins > 0: tactics.append(f"⚔️ **【天王山之戰】** 「雙方目前戰成 {laa_ws_wins}:{lad_ws_wins} 平手！在短期賽制中，拿下這場『天王山之戰』的球隊，將獲得無比巨大的心理與調度優勢！」")
                elif laa_ws_wins == 0 and lad_ws_wins == 0: tactics.append("🎆 **【秋季經典首戰】** 「世界大賽 Game 1 正式點燃戰火！雙方都在試探彼此的底牌，今天誰能搶下開門紅，就能初步掌控系列賽的節奏。」")
                else:
                    lead_team = "LAA" if laa_ws_wins > lad_ws_wins else "LAD"
                    trail_team = "LAD" if laa_ws_wins > lad_ws_wins else "LAA"
                    tactics.append(f"📈 **【系列賽走勢】** 「目前 {lead_team} 取得領先，但 {trail_team} 的反撲力道絕對不容小覷，今天的比賽將決定系列賽會是一面倒還是陷入泥淖。」")
            else:
                tactics.append(random.choice([
                    "🎙️ **【例行賽焦點】** 「漫長的賽季中，每一場勝利都是通往十月的基石，且看今天雙方能為球迷帶來什麼樣的高水準交鋒。」",
                    "🎙️ **【例行賽焦點】** 「例行賽就是一場馬拉松，但今天這場洛杉磯內戰，雙方絕對都想在氣勢上壓過對手！」"
                ]))

            x_factors = []
            
            if is_ws_mode:
                for team, batters in [('LAA', curr_laa_batters), ('LAD', curr_lad_batters)]:
                    for b in batters:
                        if b in mvp_top3:
                            ws_wrc = ws_b_stats.get(team, {}).get(b, {}).get('wRC+', 0)
                            if ws_wrc < 80 and ws_b_stats.get(team, {}).get(b, {}).get('PA', 0) >= 3:
                                x_factors.append(f"🥶 **【X-Factor：MVP 迷失十月】** 例行賽 MVP 大熱門 **{b}** 到了世界大賽竟然嚴重當機 (WS wRC+ 僅 {ws_wrc:.0f})。今晚他能否找回 MVP 級的身手，將是 {team} 死裡逃生的關鍵！")
                            elif ws_wrc > 150:
                                x_factors.append(f"👑 **【X-Factor：MVP 降臨】** 例行賽 MVP 級別的 **{b}** 到了十月大場面一樣毫不手軟 (WS wRC+ 高達 {ws_wrc:.0f})，對手今晚的投手群絕對要拉起最高層級的防空警報！")
                
                for team, sp in [('LAA', laa_sp), ('LAD', lad_sp)]:
                    if sp != "未指定" and sp in cy_top3:
                        ws_era = ws_p_stats.get(team, {}).get(sp, {}).get('ERA', 0.0)
                        ws_fip = ws_p_stats.get(team, {}).get(sp, {}).get('FIP', 0.0)
                        if ws_p_stats.get(team, {}).get(sp, {}).get('IP', 0) > 1.0:
                            if ws_era > current_lg_era + 1.0 and ws_fip < current_lg_era - 0.5:
                                x_factors.append(f"💡 **【X-Factor：賽揚悲情王牌】** 賽揚熱門 **{sp}** 在季後賽帳面 ERA ({ws_era:.2f}) 被打爆，但進階的 FIP ({ws_fip:.2f}) 證明他其實非常倒楣。今晚只要守備幫忙，他絕對會投出一場史詩級的好球平反！")
                            elif ws_era > current_lg_era + 1.5:
                                x_factors.append(f"🥀 **【X-Factor：王牌軟手】** 誰能想到例行賽神擋殺神的賽揚級王牌 **{sp}**，在世界大賽居然頂不住壓力 (ERA 高達 {ws_era:.2f})。今晚他必須克服心魔，否則球隊凶多吉少！")

            for team, batters in [('LAA', curr_laa_batters), ('LAD', curr_lad_batters)]:
                for b in batters:
                    if b in curr_b_stats.get(team, {}):
                        s = curr_b_stats[team][b]
                        if s['PA'] >= dyn_pa_limit and s['wRC+'] > 180:
                            x_factors.append(f"🔥 **【X-Factor：無法阻擋的 {b}】** 他近期的火力指標 wRC+ 高達 {s['wRC+']:.0f}，完全是外星人等級。對手今晚如果壘上有人，非常有可能選擇直接敬遠保送他！")
                            
            def get_x_stats_simple(b_name, b_team, p_name, p_team):
                b_s = curr_b_stats.get(b_team, {}).get(b_name)
                p_s = curr_p_stats.get(p_team, {}).get(p_name)
                if not b_s or not p_s or b_s.get('PA',0) < 1 or p_s.get('BF',0) < 1: return 0,0,0
                lg_pa = sum([v.get('PA',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_ab = sum([v.get('AB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                if lg_pa < 10 or lg_ab == 0: return 0,0,0
                l_ba = sum([v.get('H',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_ab
                l_obp = sum([v.get('H',0)+v.get('BB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa
                l_hr = sum([v.get('HR',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()]) / lg_pa
                W = 10.0
                b_ba = (b_s['H'] + l_ba * W) / (max(1, b_s['AB']) + W)
                p_ba = (p_s['H'] + l_ba * W) / (max(1, p_s['BF']-p_s.get('BB',0)) + W)
                b_obp = (b_s['H'] + b_s['BB'] + l_obp * W) / (b_s['PA'] + W)
                p_obp = (p_s['H'] + p_s['BB'] + l_obp * W) / (p_s['BF'] + W)
                b_hr = (b_s['HR'] + l_hr * W) / (b_s['PA'] + W)
                p_hr = (p_s['HR'] + l_hr * W) / (p_s['BF'] + W)
                return log5(b_ba, p_ba, l_ba), log5(b_obp, p_obp, l_obp), log5(b_hr, p_hr, l_hr)

            if laa_sp != "未指定" and curr_lad_batters:
                for b in random.sample(curr_lad_batters, min(3, len(curr_lad_batters))):
                    xBA, xOBP, xHR = get_x_stats_simple(b, 'LAD', laa_sp, 'LAA')
                    if xHR > 0.08: x_factors.append(f"💣 **【X-Factor：全壘打預警】** 模型推測 LAD 的 **{b}** 今晚面對 {laa_sp}，開轟的機率 (xHR%) 高達 **{xHR*100:.1f}%**！這個對決只要一失投就是一發大號全壘打。")
                    elif xOBP > 0.45: x_factors.append(f"🦅 **【X-Factor：上壘機器】** LAD 的 **{b}** 遇到 {laa_sp} 預期上壘率 (xOBP) 突破 **{xOBP*100:.1f}%**！他將會是今晚不斷製造對手麻煩的攻勢發動機。")
                    
            if lad_sp != "未指定" and curr_laa_batters:
                for b in random.sample(curr_laa_batters, min(3, len(curr_laa_batters))):
                    xBA, xOBP, xHR = get_x_stats_simple(b, 'LAA', lad_sp, 'LAD')
                    if xBA > 0.35: x_factors.append(f"🎯 **【X-Factor：安打製造機】** 根據 Log5 運算，LAA 的 **{b}** 打 {lad_sp} 預期會非常順手 (xBA 高達 **{xBA*100:.1f}%**)，他極有可能成為今晚撕裂對手防線的關鍵！")
                    elif xHR > 0.08: x_factors.append(f"💣 **【X-Factor：重砲威脅】** 模型警告，LAA 的 **{b}** 面對 {lad_sp} 擊出全壘打的機率極高 (xHR% **{xHR*100:.1f}%**)！投手在面對他時配球必須非常謹慎。")

            if bp_laa > current_lg_era + 1.0 and bp_lad > current_lg_era + 1.0:
                x_factors.append(f"🧨 **【X-Factor：打者聯盟的牛棚地雷陣】** 在這個打者極度佔優的聯盟裡，兩隊後援 ERA (均突破 {max(bp_laa, bp_lad):.2f}) 都處於核爆邊緣。先發投手退場後的那一刻，才是這場比賽真正血流成河的起點！")
            elif bp_laa > 0 and bp_laa < current_lg_era - 1.0 and bp_lad > 0 and bp_lad < current_lg_era - 1.0:
                x_factors.append("🔒 **【X-Factor：逆流而上的鐵壁】** 在這個打者橫行的聯盟中，雙方居然都握有低於均值極多的超強牛棚！今晚誰能在前六局先取得領先，幾乎就等於把勝利放進了口袋。")

            if x_factors: tactics.append(random.choice(x_factors))
            else: tactics.append("🧩 **【X-Factor：總教練的魔法】** 雙方今晚的戰力極度緊繃，勝負的關鍵將完全落在兩邊總教練的戰術推進與換投時機拿捏。")

            prediction = []
            if is_laa_home: home_str = "主場球迷的加持"
            else: home_str = "身處客場卻握有極佳的數據優勢"

            # --- AI 動態比分精算模型 (3局制專屬版) ---
            # ✨ 修改點 1：基準得分環境從 9 局的 4.5 分，等比例縮減為 3 局的 1.5 分
            run_env = 1.5
            
            # ✨ 修改點 2：在 3 局制中每一分價值極高！勝率每超過 50% 約 20% (原本是10%)，期望得分大約多 1 分
            power_diff = (prob_laa - 50) / 20.0
            
            exp_runs_laa = run_env + power_diff
            exp_runs_lad = run_env - power_diff
            
            pred_laa = max(0, int(round(exp_runs_laa)))
            pred_lad = max(0, int(round(exp_runs_lad)))
            
            # 棒球沒有和局，若推算出來同分，交由勝率天平 (prob_laa) 的微小優勢方打破僵局加 1 分 (完美模擬突破僵局制)
            if pred_laa == pred_lad:
                if prob_laa >= 50: pred_laa += 1
                else: pred_lad += 1

            # 產生結合勝率與比分的終極預測字串
            if pred_laa > pred_lad:
                prediction.append(f"🔮 **【AI 大數據終極預測】**\n「綜合今日雙方陣容火力與 **3 局制賽制環境**，模型顯示勝率天平傾向 LAA (**{prob_laa}%**)。\n👉 系統推演最可能出現的結果為：**LAA 將以 {pred_laa} : {pred_lad} 擊敗 LAD！**」")
            else:
                prediction.append(f"🔮 **【AI 大數據終極預測】**\n「綜合今日雙方陣容火力與 **3 局制賽制環境**，模型顯示勝率天平傾向 LAD (**{prob_lad}%**)。\n👉 系統推演最可能出現的結果為：**LAD 將以 {pred_lad} : {pred_laa} 擊敗 LAA！**」")

            tactics.append(prediction[0])
            st.error("\n\n".join(tactics))

            # ==========================================
            # ✨ 戰情室特別警報 (Active Streaks Radar)
            # ==========================================
            st.markdown("---")
            st.markdown("#### 🚨 戰情室特別警報 (Active Streaks Radar)")
            
            active_alerts = []
            df_b_raw_radar = st.session_state.get('df_b_raw', pd.DataFrame())
            df_p_raw_radar = st.session_state.get('df_p_raw', pd.DataFrame())

            if not df_b_raw_radar.empty:
                for team in ['LAA', 'LAD']:
                    t_df = df_b_raw_radar[df_b_raw_radar['球隊'] == team]
                    for name, g in t_df.groupby('球員姓名', sort=False):
                        # ✨ 核心優化 1：只對今天「有進入先發打線」的球員發出警報，板凳老鳥直接略過！
                        is_starting_today = name in (curr_laa_batters + curr_lad_batters)
                        if not is_starting_today: continue
                        
                        g_sorted = g.sort_values('時間戳記', ascending=False)
                        hit_streak, hr_streak, hitless_streak = 0, 0, 0
                        
                        # 算連續安打場次
                        for _, r in g_sorted.iterrows():
                            if pd.to_numeric(r.get('安打', 0), errors='coerce') > 0: hit_streak += 1
                            else: break
                            
                        # 算連續全壘打場次
                        for _, r in g_sorted.iterrows():
                            if pd.to_numeric(r.get('全壘打', 0), errors='coerce') > 0: hr_streak += 1
                            else: break
                            
                        # 算連續無安打場次
                        for _, r in g_sorted.iterrows():
                            h = pd.to_numeric(r.get('安打', 0), errors='coerce')
                            ab = pd.to_numeric(r.get('打數', 0), errors='coerce')
                            if h > 0: break
                            elif h == 0 and ab > 0: hitless_streak += 1

                        playing_str = " 🎯(今日先發)"
                        
                        if hr_streak >= 2:
                            active_alerts.append(f"🌋 [{team}] **{name}**{playing_str} 砲火猛烈！目前已跨場 **連 {hr_streak} 場全壘打**，絕對要注意他的長打威脅！")
                        if hit_streak >= 4: # ✨ 核心優化 2：火燙安打提高到 4 場
                            active_alerts.append(f"🔥 [{team}] **{name}**{playing_str} 手感發燙，目前正處於跨場 **連 {hit_streak} 場安打** 的狀態！")
                        if hitless_streak >= 5: # ✨ 核心優化 3：嚴重低潮提高到 5 場
                            active_alerts.append(f"📉 [{team}] **{name}**{playing_str} 近期陷入嚴重低潮，已經連續 **{hitless_streak} 場出賽沒有安打**，急需一棒擊沉來改運！")

            if not df_p_raw_radar.empty:
                df_p_sort = df_p_raw_radar.sort_values('時間戳記')
                df_p_sort['is_SP'] = df_p_sort.groupby(['球隊', '賽事階段']).cumcount() == 0
                
                for team in ['LAA', 'LAD']:
                    t_df = df_p_sort[df_p_sort['球隊'] == team]
                    for name, g in t_df.groupby('投手姓名', sort=False):
                        g_sorted = g.sort_values('時間戳記', ascending=False)
                        
                        # 先發無失分紀錄
                        sp_games = g_sorted[g_sorted['is_SP'] == True]
                        zr_sp_streak = 0
                        for _, r in sp_games.iterrows():
                            er = pd.to_numeric(r.get('失分', 1), errors='coerce')
                            outs = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                            if er == 0 and outs > 0: zr_sp_streak += 1
                            else: break
                        
                        # 後援無失分紀錄
                        rp_games = g_sorted[g_sorted['is_SP'] == False]
                        zr_rp_streak = 0
                        for _, r in rp_games.iterrows():
                            er = pd.to_numeric(r.get('失分', 1), errors='coerce')
                            outs = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                            if er == 0 and outs > 0: zr_rp_streak += 1
                            else: break
                            
                        if zr_sp_streak >= 2:
                            # 只針對今天確定的先發投手發警報
                            if name in [laa_sp, lad_sp]:
                                active_alerts.append(f"🛡️ [{team}] **{name}** ⚾(今日先發) 展現窒息式壓制力，已連續 **{zr_sp_streak} 場先發無失分**！")
                        if zr_rp_streak >= 4:
                            playing_str = " 🔒(牛棚待命)" if name not in [laa_sp, lad_sp] else ""
                            active_alerts.append(f"🔒 [{team}] **{name}**{playing_str} 近期扮演牛棚鐵壁，已連續 **{zr_rp_streak} 場後援無失分**！")

            if active_alerts:
                st.info("\n\n".join(active_alerts))
            else:
                st.caption("目前雙方陣容中，尚無值得注意的極端連續紀錄。")
# ==========================================
# --- 分頁 5：🏛️ 聯盟歷史與榮耀殿堂 ---
# ==========================================
with tab5:
    st.header("🏛️ 聯盟歷史與榮耀殿堂 (History & Awards)")
    st.caption("結合 BBWAA 年度大獎、大聯盟歷史資料庫、里程碑追蹤與進階數據極端的終極榮耀殿堂。")
    
    df_b_full = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
    
    if df_b_full.empty or df_p_full.empty:
        st.warning("⚠️ 目前聯盟尚無足夠的歷史數據來產生紀錄，請先完成幾場比賽！")
    else:
        import re
        import numpy as np
        
        # ✨ 全域時空與賽季偵測
        all_s_nums = []
        for stg in df_p_full['賽事階段'].dropna().unique():
            m = re.search(r'\[S(\d+)\]', str(stg))
            if m: all_s_nums.append(int(m.group(1)))
        max_season = max(all_s_nums) if all_s_nums else 1
        curr_s_str = wr_season.split(" ")[1] if wr_season != "十年總成績" else str(max_season)
        curr_s_prefix = f"[S{curr_s_str}]"
        
        global_last_ts_p_team = df_p_full.groupby('球隊', sort=False)['時間戳記'].max().to_dict()
        global_last_ts_b_player = df_b_full.groupby(['球隊', '球員姓名'], sort=False)['時間戳記'].max().to_dict()
        global_last_ts_p_player = df_p_full.groupby(['球隊', '投手姓名'], sort=False)['時間戳記'].max().to_dict()

        def clean_stage_name(stage_str):
            s = str(stage_str)
            return s.replace(" 例行賽 第", "例行 G").replace(" 世界大賽 第", "WS G").replace("場", "")

        def build_home_dict(df_p_all, df_b_all):
            home_dict = {}
            if df_p_all.empty: return home_dict
            stages = df_p_all['賽事階段'].unique()
            seasons = sorted(list(set([int(re.search(r'\[S(\d+)\]', str(s)).group(1)) for s in stages if re.search(r'\[S(\d+)\]', str(s))])))
            prev_ws_loser = "LAD" 
            for s in seasons:
                s_pref = f"[S{s}]"
                rs_stages = sorted([st for st in stages if s_pref in str(st) and '例行賽' in str(st)], key=lambda x: int(re.search(r'第(\d+)場', str(x)).group(1)) if re.search(r'第(\d+)場', str(x)) else 0)
                laa_w, lad_w, laa_rs_ra, lad_rs_ra, laa_rs_r, lad_rs_r = 0, 0, 0, 0, 0, 0
                curr_home = prev_ws_loser
                for idx, stage in enumerate(rs_stages):
                    g_num = idx + 1
                    h_team = curr_home if g_num % 2 == 1 else ("LAA" if curr_home == "LAD" else "LAD")
                    home_dict[stage] = h_team
                    g_p = df_p_all[df_p_all['賽事階段'] == stage]
                    if any('勝' in str(x) for x in g_p[g_p['球隊']=='LAA']['勝敗'].values): laa_w += 1
                    if any('勝' in str(x) for x in g_p[g_p['球隊']=='LAD']['勝敗'].values): lad_w += 1
                    laa_rs_ra += pd.to_numeric(g_p[g_p['球隊']=='LAA']['失分'], errors='coerce').fillna(0).sum()
                    lad_rs_ra += pd.to_numeric(g_p[g_p['球隊']=='LAD']['失分'], errors='coerce').fillna(0).sum()
                    if not df_b_all.empty:
                        g_b = df_b_all[df_b_all['賽事階段'] == stage]
                        laa_rs_r += pd.to_numeric(g_b[g_b['球隊']=='LAA']['得分'], errors='coerce').fillna(0).sum()
                        lad_rs_r += pd.to_numeric(g_b[g_b['球隊']=='LAD']['得分'], errors='coerce').fillna(0).sum()
                ws_hfa = "LAA" if laa_w > lad_w else "LAD" if lad_w > laa_w else ("LAA" if (laa_rs_r - laa_rs_ra) >= (lad_rs_r - lad_rs_ra) else "LAD")
                ws_stages = sorted([st for st in stages if s_pref in str(st) and '世界大賽' in str(st)], key=lambda x: int(re.search(r'第(\d+)場', str(x)).group(1)) if re.search(r'第(\d+)場', str(x)) else 0)
                for idx, stage in enumerate(ws_stages):
                    g_num = idx + 1
                    h_team = ws_hfa if g_num in [1, 2, 6, 7] else ("LAA" if ws_hfa == "LAD" else "LAD")
                    home_dict[stage] = h_team
            return home_dict
        global_home_dict = build_home_dict(df_p_full, df_b_full)

        # ------------------------------------
        # ✨ 六大榮耀子分頁
        # ------------------------------------
        t_awards, t_all_mlb, t_leaders, t_milestones, t_streaks, t_extremes = st.tabs([
            "🏆 賽季大獎", 
            "🌟 最佳陣容", 
            "👑 歷史神主牌", 
            "⏳ 里程碑追蹤", 
            "💎 神聖與連勝", 
            "🤯 單場極端榜"
        ])

        # ==========================================
        # ✨ 預先計算所有賽季的大獎與陣容 (快取化)
        # ==========================================
        def get_hist_awards(s_idx):
            s_prefix = f"[S{s_idx}]"
            df_b_rs = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains("例行賽", regex=False))].copy()
            df_p_rs = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains("例行賽", regex=False))].copy()
            df_b_ws = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].copy()
            df_p_ws = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].copy()
            
            pos_adj_dict = {"C": 0.5, "SS": 0.4, "2B": 0.2, "3B": 0.2, "CF": 0.2, "LF": -0.2, "RF": -0.2, "1B": -0.3, "DH": -0.5}
            
            def extract_and_vote(b_sub, p_sub, is_ws=False, ws_winner=None, rookie_set=None):
                if b_sub.empty and p_sub.empty: 
                    return ("無", pd.DataFrame()) if is_ws else ("無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), {})
                    
                team_games = b_sub['賽事階段'].nunique() if not b_sub.empty else 1
                min_pa = 3.0 if is_ws else max(1.0, team_games * 1.0) 
                min_ip = 1.0 if is_ws else max(0.1, team_games * 0.33)
                
                cand = {}
                if not b_sub.empty:
                    for col in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振']:
                        b_sub[col] = pd.to_numeric(b_sub.get(col, 0), errors='coerce').fillna(0)
                    t_pa = b_sub['打席'].sum()
                    lg_1b = b_sub['安打'].sum() - b_sub['二壘安打'].sum() - b_sub['三壘安打'].sum() - b_sub['全壘打'].sum()
                    lg_woba = (0.69*b_sub['四壞球'].sum() + 0.88*lg_1b + 1.25*b_sub['二壘安打'].sum() + 1.59*b_sub['三壘安打'].sum() + 2.06*b_sub['全壘打'].sum()) / t_pa if t_pa > 0 else 0.001
                    
                    b_agg = b_sub.groupby(['球隊', '球員姓名']).agg({'打席':'sum','打數':'sum','安打':'sum','二壘安打':'sum','三壘安打':'sum','全壘打':'sum','打點':'sum','四壞球':'sum','三振':'sum', '守位': 'first'}).reset_index()
                    for _, r in b_agg.iterrows():
                        b_1b = r['安打'] - r['二壘安打'] - r['三壘安打'] - r['全壘打']
                        woba = (0.69*r['四壞球'] + 0.88*b_1b + 1.25*r['二壘安打'] + 1.59*r['三壘安打'] + 2.06*r['全壘打']) / max(1, r['打席'])
                        wrc_plus = 100 * (woba / lg_woba) if lg_woba > 0 else 0
                        ewar = (((wrc_plus - 70) / 80) + pos_adj_dict.get(r.get('守位','DH'), 0)) * (r['打席'] / 15)
                        cand[f"[{r['球隊']}] {r['球員姓名']}"] = {
                            '球隊': r['球隊'], '球員姓名': r['球員姓名'], '類型':'打者', 'Pos': r.get('守位', 'DH'), 
                            'HR':r['全壘打'], 'RBI':r['打點'], 'AVG': r['安打']/max(1,r['打數']), 'wRC+': wrc_plus,
                            'eWAR': ewar, 'Qual': r['打席'] >= min_pa, 'PA': r['打席']
                        }
                
                if not p_sub.empty:
                    for col in ['局數(整數)', '局數(出局數)', '奪三振', '自責分', '四壞球', '被全壘打']:
                        p_sub[col] = pd.to_numeric(p_sub.get(col, 0), errors='coerce').fillna(0)
                    lg_ip = ((p_sub['局數(整數)'].sum()*3) + p_sub['局數(出局數)'].sum()) / 3.0
                    lg_era_base = (p_sub['自責分'].sum()*9) / lg_ip if lg_ip > 0 else 10.60
                    era_div = max(1.5, lg_era_base * 0.2)
                    
                    p_sub_c = p_sub.copy()
                    p_sub_c['勝'] = p_sub_c['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                    p_sub_c['救援'] = p_sub_c['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                    p_sub_c['中繼'] = p_sub_c['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
                    p_agg = p_sub_c.groupby(['球隊', '投手姓名']).agg({'局數(整數)':'sum', '局數(出局數)':'sum', '勝':'sum', '救援':'sum', '中繼':'sum', '奪三振':'sum', '自責分':'sum', '四壞球':'sum', '被全壘打':'sum'}).reset_index()
                    
                    for _, r in p_agg.iterrows():
                        ip_c = (r['局數(整數)']*3 + r['局數(出局數)'])/3.0
                        era = (r['自責分']*9)/max(1, ip_c) if ip_c>0 else float('inf') if r['自責分'] > 0 else 0.0
                        fip = (((13*r['被全壘打'])+(3*r['四壞球'])-(2*r['奪三振']))/max(1,ip_c))+3.10 if ip_c>0 else float('inf') if (13*r['被全壘打']+3*r['四壞球']-2*r['奪三振'])>0 else 3.10
                        tra = (era + fip) / 2.0
                        ewar = (-0.1*r['自責分']-0.05*r['四壞球']) if ip_c==0 else ((lg_era_base-tra)/era_div)*(ip_c/10)
                        name = f"[{r['球隊']}] {r['投手姓名']}"
                        if name in cand:
                            cand[name].update({'類型':'二刀流', 'W':r['勝'], 'SV':r['救援'], 'HLD':r['中繼'], 'ERA':era, 'K_p':r['奪三振'], 'FIP':fip, 'IP':ip_c, 'Qual': (cand[name]['Qual'] or ip_c >= min_ip)})
                            cand[name]['eWAR'] += ewar
                        else:
                            cand[name] = {'球隊': r['球隊'], '球員姓名': r['投手姓名'], '類型':'投手', 'W':r['勝'], 'SV':r['救援'], 'HLD':r['中繼'], 'ERA':era, 'K_p':r['奪三振'], 'FIP':fip, 'eWAR':ewar, 'IP':ip_c, 'Qual': ip_c >= min_ip}
                
                if not cand: return (("無", pd.DataFrame()) if is_ws else ("無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), {}))

                qual_cands = {k: v for k, v in cand.items() if v.get('Qual', False)}
                if not qual_cands and not is_ws: return "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), cand

                leaders = {'HR': max([s.get('HR',0) for s in qual_cands.values()]+[0]), 'RBI': max([s.get('RBI',0) for s in qual_cands.values()]+[0]), 'W': max([s.get('W',0) for s in qual_cands.values()]+[0]), 'K_p': max([s.get('K_p',0) for s in qual_cands.values()]+[0])}

                def simulate_voting_local(target_award, cands_dict):
                    eval_cands = {k: v for k, v in cands_dict.items() if v.get('Qual', False)}
                    if not eval_cands: return "無", pd.DataFrame()
                    
                    results = {name: {'1st': 0, '2nd': 0, '3rd': 0, 'Points': 0} for name in eval_cands}
                    voter_types = ['Traditional']*12 + ['Sabermetric']*10 + ['Balanced']*8
                    max_hr, max_rbi, max_w, max_k = leaders.get('HR',0), leaders.get('RBI',0), leaders.get('W',0), leaders.get('K_p',0)
                    valid_eras = [s['ERA'] for s in eval_cands.values() if s['類型'] in ['投手', '二刀流'] and 'ERA' in s]
                    min_era = min(valid_eras) if valid_eras else 99.9

                    for voter in voter_types:
                        scores = {}
                        for name, stats in eval_cands.items():
                            score, leader_bonus = 0, 0
                            if target_award != "FMVP": 
                                if stats.get('HR',0) == max_hr and max_hr > 0: leader_bonus += 30
                                if stats.get('RBI',0) == max_rbi and max_rbi > 0: leader_bonus += 20
                                if stats.get('W',0) == max_w and max_w > 0: leader_bonus += 10
                                if stats.get('K_p',0) == max_k and max_k > 0: leader_bonus += 20
                                if stats.get('ERA',99.9) == min_era and min_era < 4.0: leader_bonus += 35
                            
                            if target_award == "MVP":
                                if voter == 'Traditional':
                                    if stats['類型'] in ['打者', '二刀流']: score += stats.get('HR',0)*20 + stats.get('RBI',0)*10 + leader_bonus + (20 if stats.get('AVG',0)>0.300 else -30 if stats.get('AVG',0)<0.250 else 0)
                                    if stats['類型'] in ['投手', '二刀流']: score += stats.get('W',0)*12 + stats.get('SV',0)*10 + stats.get('K_p',0)*1.5 - stats.get('ERA',5)*15 + leader_bonus + (25 if stats.get('ERA',5)<3.00 else 0)
                                elif voter == 'Sabermetric': score += stats.get('eWAR',0)*80 + leader_bonus*0.2 
                                else: score += stats.get('eWAR',0)*50 + stats.get('HR',0)*12 + stats.get('W',0)*5 - stats.get('ERA',5)*10 + leader_bonus*0.5
                            elif target_award == "CyYoung":
                                if stats['類型'] == '打者': continue
                                if stats.get('ERA', 5) > 5.00: score -= 500 
                                if voter == 'Traditional': score += stats.get('W',0)*12 + stats.get('SV',0)*12 + stats.get('K_p',0)*1.5 - stats.get('ERA',5)*20 + leader_bonus + (30 if stats.get('ERA',5)<2.50 else 0)
                                else: score += stats.get('eWAR',0)*60 - stats.get('FIP',5)*15 - stats.get('ERA',5)*10 + leader_bonus*0.5
                            elif target_award == "SilverSlugger":
                                if stats['類型'] == '投手': continue
                                if voter == 'Traditional': score += stats.get('HR',0)*25 + stats.get('AVG',0)*100 + leader_bonus
                                else: score += stats.get('eWAR',0)*20 + stats.get('wRC+',0)*2
                            elif target_award == "FMVP":
                                if ws_winner and f"[{ws_winner}]" not in name: score -= 1000
                                if stats['類型'] in ['打者', '二刀流']: score += stats.get('HR',0)*40 + stats.get('RBI',0)*20 + stats.get('wRC+',0)*0.5
                                if stats['類型'] in ['投手', '二刀流']: score += stats.get('W',0)*25 + stats.get('SV',0)*25 + stats.get('K_p',0)*2 - stats.get('ERA',5)*20
                                score += stats.get('eWAR',0)*60 

                            deterministic_tiebreaker = (sum(ord(c) for c in name) % 100) / 100.0
                            scores[name] = score + deterministic_tiebreaker 
                        
                        if not scores: continue
                        top5 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                        if len(top5) >= 1: results[top5[0][0]]['1st'] += 1; results[top5[0][0]]['Points'] += 14
                        if len(top5) >= 2: results[top5[1][0]]['2nd'] += 1; results[top5[1][0]]['Points'] += 9
                        if len(top5) >= 3: results[top5[2][0]]['3rd'] += 1; results[top5[2][0]]['Points'] += 8
                        if len(top5) >= 4: results[top5[3][0]]['Points'] += 5
                        if len(top5) >= 5: results[top5[4][0]]['Points'] += 3
                            
                    df_res = pd.DataFrame.from_dict(results, orient='index').reset_index()
                    df_res.columns = ['球員', '第一名選票', '第二名選票', '第三名選票', '總積分']
                    df_res = df_res[df_res['總積分'] > 0].sort_values('總積分', ascending=False)
                    df_res.index = np.arange(1, len(df_res) + 1)
                    
                    if df_res.empty: return "無", pd.DataFrame()
                    winner_name = df_res.iloc[0]['球員']
                    w_stats = cands_dict[winner_name]
                    return f"{winner_name} (eWAR {w_stats.get('eWAR',0):.1f})", df_res

                if is_ws: return simulate_voting_local("FMVP", qual_cands)
                
                mvp, mvp_df = simulate_voting_local("MVP", qual_cands)
                cy, cy_df = simulate_voting_local("CyYoung", qual_cands)
                ss, ss_df = simulate_voting_local("SilverSlugger", qual_cands)
                
                roty, roty_df = "無", pd.DataFrame()
                if rookie_set is not None:
                    rookie_cands = {k: v for k, v in qual_cands.items() if k in rookie_set}
                    if rookie_cands: roty, roty_df = simulate_voting_local("MVP", rookie_cands)
                return mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, "無", pd.DataFrame(), cand

            ws_winner_team = None
            if not df_p_ws.empty:
                laa_w = sum(1 for _, g in df_p_ws.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAA']['勝敗'].values))
                lad_w = sum(1 for _, g in df_p_ws.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAD']['勝敗'].values))
                if laa_w >= 4: ws_winner_team = "LAA"
                elif lad_w >= 4: ws_winner_team = "LAD"

            r_set = set()
            if s_idx == 1: 
                b_agg = df_b_rs.groupby(['球隊', '球員姓名']).size().reset_index()
                p_agg = df_p_rs.groupby(['球隊', '投手姓名']).size().reset_index()
                if not b_agg.empty: r_set.update([f"[{r['球隊']}] {r['球員姓名']}" for _, r in b_agg.iterrows()])
                if not p_agg.empty: r_set.update([f"[{r['球隊']}] {r['投手姓名']}" for _, r in p_agg.iterrows()])
            else:
                past_regex = "|".join([f"\\[S{i}\\]" for i in range(1, s_idx)])
                past_b = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(past_regex)] if not df_b_full.empty else pd.DataFrame()
                past_p = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(past_regex)] if not df_p_full.empty else pd.DataFrame()
                vets = set()
                if not past_b.empty: vets.update([f"[{r['球隊']}] {r['球員姓名']}" for _, r in past_b.iterrows()])
                if not past_p.empty: vets.update([f"[{r['球隊']}] {r['投手姓名']}" for _, r in past_p.iterrows()])
                curr_b = df_b_rs.groupby(['球隊', '球員姓名']).size().reset_index()
                curr_p = df_p_rs.groupby(['球隊', '投手姓名']).size().reset_index()
                curr_all = set()
                if not curr_b.empty: curr_all.update([f"[{r['球隊']}] {r['球員姓名']}" for _, r in curr_b.iterrows()])
                if not curr_p.empty: curr_all.update([f"[{r['球隊']}] {r['投手姓名']}" for _, r in curr_p.iterrows()])
                r_set = curr_all - vets

            mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, _, _, rs_cand = extract_and_vote(df_b_rs, df_p_rs, False, rookie_set=r_set)
            if ws_winner_team: fmvp, fmvp_df = extract_and_vote(df_b_ws, df_p_ws, True, ws_winner_team)
            else: fmvp, fmvp_df = "無 (賽事未完/尚未產生冠軍)", pd.DataFrame()
            return mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, rs_cand

        # 執行快取
        season_cache = {}
        for s_idx in range(1, max_season + 1):
            season_cache[s_idx] = get_hist_awards(s_idx)

        def track_award(dict_counts, df):
            if not df.empty:
                winner = df.iloc[0]['球員']
                dict_counts[winner] = dict_counts.get(winner, 0) + 1
                return dict_counts[winner]
            return 0

        # ==========================================
        # 🏆 Tab 1: 賽季大獎與記者票選明細
        # ==========================================
        with t_awards:
            st.subheader("🏆 歷屆賽季大獎與 BBWAA 記者票選明細")
            award_counts = {'MVP': {}, 'CyYoung': {}, 'ROTY': {}, 'SilverSlugger': {}, 'FMVP': {}}
            
            for s_idx in range(1, max_season + 1):
                with st.expander(f"📖 Season {s_idx} 大獎得主與票選結果", expanded=(s_idx == max_season)):
                    mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, _ = season_cache[s_idx]
                    
                    c_mvp = track_award(award_counts['MVP'], mvp_df)
                    c_cy = track_award(award_counts['CyYoung'], cy_df)
                    c_ss = track_award(award_counts['SilverSlugger'], ss_df)
                    c_roty = track_award(award_counts['ROTY'], roty_df)
                    c_fmvp = track_award(award_counts['FMVP'], fmvp_df)
                    
                    mvp_str = f"{mvp} {'★第'+str(c_mvp)+'次' if c_mvp > 1 else ''}" if "無" not in mvp else mvp
                    cy_str = f"{cy} {'★第'+str(c_cy)+'次' if c_cy > 1 else ''}" if "無" not in cy else cy
                    ss_str = f"{ss} {'★第'+str(c_ss)+'次' if c_ss > 1 else ''}" if "無" not in ss else ss
                    fmvp_str = f"{fmvp} {'★第'+str(c_fmvp)+'次' if c_fmvp > 1 else ''}" if "無" not in fmvp else fmvp
                    roty_str = f"{roty}" 
                    
                    c1, c2 = st.columns(2)
                    fmt = {'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}
                    
                    with c1:
                        st.markdown(f"**🏅 年度 MVP**：\n{mvp_str}")
                        if not mvp_df.empty:
                            with st.expander("📊 查看 MVP BBWAA 記者投票明細", expanded=True): st.dataframe(mvp_df.head(5).style.format(fmt), use_container_width=True)
                        st.markdown("---")
                        st.markdown(f"**⚾ 賽揚獎 (Cy Young)**：\n{cy_str}")
                        if not cy_df.empty:
                            with st.expander("📊 查看賽揚獎 BBWAA 記者投票明細", expanded=True): st.dataframe(cy_df.head(5).style.format(fmt), use_container_width=True)
                        st.markdown("---")
                        st.markdown(f"**🌟 世界大賽 FMVP**：\n{fmvp_str}")
                        if not fmvp_df.empty:
                            with st.expander("📊 查看 FMVP 評委投票明細", expanded=True): st.dataframe(fmvp_df.head(5).style.format(fmt), use_container_width=True)
                    with c2:
                        st.markdown(f"**👶 新人王 (ROTY)**：\n{roty_str}")
                        if not roty_df.empty:
                            with st.expander("📊 查看新人王 BBWAA 記者投票明細", expanded=True): st.dataframe(roty_df.head(5).style.format(fmt), use_container_width=True)
                        st.markdown("---")
                        st.markdown(f"**🏏 銀棒獎 (Silver Slugger)**：\n{ss_str}")
                        if not ss_df.empty:
                            with st.expander("📊 查看銀棒獎 BBWAA 記者投票明細", expanded=True): st.dataframe(ss_df.head(5).style.format(fmt), use_container_width=True)

        # ==========================================
        # 🌟 Tab 2: 年度最佳陣容第一隊 (All-MLB)
        # ==========================================
        with t_all_mlb:
            st.subheader("🌟 歷屆年度最佳陣容第一隊 (All-MLB First Team)")
            all_mlb_counts = {}
            
            for s_idx in range(1, max_season + 1):
                with st.expander(f"📖 Season {s_idx} 最佳陣容", expanded=(s_idx == max_season)):
                    rs_cand = season_cache[s_idx][10]
                    first_team = {}
                    
                    if rs_cand:
                        batters = {k: v for k, v in rs_cand.items() if v['類型'] in ['打者', '二刀流']}
                        pitchers = {k: v for k, v in rs_cand.items() if v['類型'] in ['投手', '二刀流']}
                        selected_players = set()
                        
                        def get_best_hitter(pos_list, is_dh=False):
                            if is_dh:
                                cands = {k: v for k, v in batters.items() if k not in selected_players and v.get('Qual', False)}
                                empty_reason = "無 (無剩餘達標打者)"
                            else:
                                cands = {k: v for k, v in batters.items() if v.get('Pos', 'DH') in pos_list and k not in selected_players and v.get('Qual', False)}
                                empty_reason = "無 (無人達打席門檻)"
                                
                            if not cands: return empty_reason
                            pos_cands = {k: v for k, v in cands.items() if v['eWAR'] > 0}
                            if not pos_cands: return "無 (貢獻值皆為負)"
                            
                            best = max(pos_cands.items(), key=lambda x: x[1]['eWAR'])
                            best_name = best[0]
                            selected_players.add(best_name)
                            all_mlb_counts[best_name] = all_mlb_counts.get(best_name, 0) + 1
                            cnt = all_mlb_counts[best_name]
                            return f"{best_name} (eWAR {best[1]['eWAR']:.1f}){f' ★第{cnt}次' if cnt > 1 else ''}"
                            
                        first_team['C'] = get_best_hitter(['C'])
                        first_team['1B'] = get_best_hitter(['1B'])
                        first_team['2B'] = get_best_hitter(['2B'])
                        first_team['3B'] = get_best_hitter(['3B'])
                        first_team['SS'] = get_best_hitter(['SS'])
                        
                        of_base = {k: v for k, v in batters.items() if v.get('Pos', 'DH') in ['LF', 'CF', 'RF', 'OF'] and k not in selected_players and v.get('Qual', False)}
                        of_cands = {k: v for k, v in of_base.items() if v['eWAR'] > 0}
                        if not of_base: first_team['OF'] = "無 (無外野手達標)"
                        elif not of_cands: first_team['OF'] = "無 (外野貢獻值皆為負)"
                        else:
                            top_ofs = sorted(of_cands.items(), key=lambda x: x[1]['eWAR'], reverse=True)[:3]
                            of_strs = []
                            for x in top_ofs: 
                                best_name = x[0]
                                selected_players.add(best_name)
                                all_mlb_counts[best_name] = all_mlb_counts.get(best_name, 0) + 1
                                cnt = all_mlb_counts[best_name]
                                of_strs.append(f"{best_name} (eWAR {x[1]['eWAR']:.1f}){f' ★第{cnt}次' if cnt > 1 else ''}")
                            first_team['OF'] = "  \n".join(of_strs)
                            
                        first_team['DH'] = get_best_hitter([], is_dh=True)
                        
                        if pitchers:
                            sp_base = {k: v for k, v in pitchers.items() if v.get('Qual', False)}
                            sp_cands = {k: v for k, v in sp_base.items() if v['eWAR'] > 0}
                            if not sp_base: first_team['SP'] = "無 (無先發達局數門檻)"
                            elif not sp_cands: first_team['SP'] = "無 (先發貢獻值皆為負)"
                            else:
                                best_sp = max(sp_cands.items(), key=lambda x: x[1]['eWAR'])
                                best_name = best_sp[0]
                                all_mlb_counts[best_name] = all_mlb_counts.get(best_name, 0) + 1
                                cnt = all_mlb_counts[best_name]
                                first_team['SP'] = f"{best_name} (eWAR {best_sp[1]['eWAR']:.1f}, {best_sp[1]['ERA']:.2f} ERA){f' ★第{cnt}次' if cnt > 1 else ''}"
                        else: first_team['SP'] = "無 (無投手資料)"
                            
                        rp_base = {k: v for k, v in pitchers.items() if v.get('SV', 0) > 0 or v.get('HLD', 0) > 0}
                        if not rp_base: first_team['RP'] = "無 (無人有中繼/救援紀錄)"
                        else:
                            rp_cands = {k: v for k, v in rp_base.items() if v['eWAR'] > 0}
                            if not rp_cands: first_team['RP'] = "無 (牛棚貢獻值皆為負)"
                            else:
                                best_rp = max(rp_cands.items(), key=lambda x: x[1]['eWAR'])
                                best_name = best_rp[0]
                                all_mlb_counts[best_name] = all_mlb_counts.get(best_name, 0) + 1
                                cnt = all_mlb_counts[best_name]
                                first_team['RP'] = f"{best_name} (eWAR {best_rp[1]['eWAR']:.1f}, {int(best_rp[1]['SV'])} SV){f' ★第{cnt}次' if cnt > 1 else ''}"
                    else:
                        for p in ['C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']: first_team[p] = "無 (賽事數據不足)"
                        
                    tc1, tc2, tc3 = st.columns(3)
                    tc1.markdown(f"**⚾ 先發投手 (SP)**：\n{first_team.get('SP', '無')}\n\n**🔒 後援投手 (RP)**：\n{first_team.get('RP', '無')}\n\n**🎯 捕手 (C)**：\n{first_team.get('C', '無')}")
                    tc2.markdown(f"**🧱 一壘手 (1B)**：\n{first_team.get('1B', '無')}\n\n**⚡ 二壘手 (2B)**：\n{first_team.get('2B', '無')}\n\n**🔥 三壘手 (3B)**：\n{first_team.get('3B', '無')}\n\n**✨ 游擊手 (SS)**：\n{first_team.get('SS', '無')}")
                    tc3.markdown(f"**🦅 外野手 (OF)**：\n{first_team.get('OF', '無')}\n\n**☄️ 指定打擊 (DH)**：\n{first_team.get('DH', '無')}")

        # ==========================================
        # 👑 Tab 3: 歷史神主牌與單季極限
        # ==========================================
        with t_leaders:
            st.subheader("👑 歷史隊史紀錄與單季極限")
            
            st.markdown("#### 🏛️ 隊史累積神主牌 (Franchise All-Time Leaders)")
            
            # --- 隊史戰績 Meta ---
            team_meta_summary = {}
            for team in ['LAA', 'LAD']:
                t_p_raw = df_p_full[df_p_full['球隊'] == team].sort_values('時間戳記') if not df_p_full.empty else pd.DataFrame()
                t_b_raw = df_b_full[df_b_full['球隊'] == team] if not df_b_full.empty else pd.DataFrame()
                
                tot_hits = pd.to_numeric(t_b_raw['安打'], errors='coerce').fillna(0).sum() if not t_b_raw.empty else 0
                tot_hr = pd.to_numeric(t_b_raw['全壘打'], errors='coerce').fillna(0).sum() if not t_b_raw.empty else 0
                tot_rbi = pd.to_numeric(t_b_raw['打點'], errors='coerce').fillna(0).sum() if not t_b_raw.empty else 0
                tot_so = pd.to_numeric(t_p_raw['奪三振'], errors='coerce').fillna(0).sum() if not t_p_raw.empty else 0
                
                h_w, h_l, h_d = 0, 0, 0
                a_w, a_l, a_d = 0, 0, 0
                oner_w, oner_l = 0, 0
                
                if not df_p_full.empty:
                    for stage, group in df_p_full.groupby('賽事階段'):
                        g_team = group[group['球隊'] == team]
                        if g_team.empty: continue
                        
                        is_w = any('勝' in str(x) for x in g_team['勝敗'].values)
                        is_l = any('敗' in str(x) for x in g_team['勝敗'].values)
                        
                        laa_ra = pd.to_numeric(group[group['球隊']=='LAA']['失分'], errors='coerce').fillna(0).sum()
                        lad_ra = pd.to_numeric(group[group['球隊']=='LAD']['失分'], errors='coerce').fillna(0).sum()
                        diff = abs(laa_ra - lad_ra)
                        
                        if diff == 1:
                            if is_w: oner_w += 1
                            elif is_l: oner_l += 1
                            
                        h_team = global_home_dict.get(stage, "Unknown")
                        if h_team == team:
                            if is_w: h_w += 1
                            elif is_l: h_l += 1
                            else: h_d += 1
                        else:
                            if is_w: a_w += 1
                            elif is_l: a_l += 1
                            else: a_d += 1
                        
                team_meta_summary[team] = {
                    'hits': int(tot_hits), 'hr': int(tot_hr), 'rbi': int(tot_rbi), 'so': int(tot_so),
                    'home_rec': f"{h_w}勝 {h_l}敗 {h_d}和",
                    'away_rec': f"{a_w}勝 {a_l}敗 {a_d}和",
                    'one_run': f"{oner_w}勝 {oner_l}敗"
                }

            b_agg_all = df_b_full.copy()
            for col in ['打席','打數','安打','全壘打','打點','四壞球']: b_agg_all[col] = pd.to_numeric(b_agg_all.get(col, 0), errors='coerce').fillna(0)
            b_all = b_agg_all.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
            
            p_agg_all = df_p_full.copy()
            p_agg_all['勝'] = p_agg_all['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
            p_agg_all['救援'] = p_agg_all['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
            for col in ['局數(整數)', '局數(出局數)', '奪三振', '自責分']: p_agg_all[col] = pd.to_numeric(p_agg_all.get(col, 0), errors='coerce').fillna(0)
            p_agg_all = p_agg_all.sort_values('時間戳記')
            p_agg_all['is_SP'] = p_agg_all.groupby(['球隊', '賽事階段']).cumcount() == 0
            p_agg_all['outs'] = p_agg_all['局數(整數)'] * 3 + p_agg_all['局數(出局數)']
            p_agg_all['QS'] = ((p_agg_all['is_SP']) & (p_agg_all['outs'] >= 6) & (p_agg_all['自責分'] <= 1)).astype(int)
            p_all = p_agg_all.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
            p_all['局數'] = (p_all['局數(整數)']*3 + p_all['局數(出局數)'])/3.0
            
            def get_top3_str(df, sort_col, name_col):
                if df.empty: return "無"
                top3 = df.sort_values(by=sort_col, ascending=False).head(3)
                res = [f"{i+1}. {r[name_col]} ({int(r[sort_col])})" for i, (_, r) in enumerate(top3.iterrows()) if r[sort_col] > 0]
                return "  \n".join(res) if res else "無"

            c_laa, c_lad = st.columns(2)
            for team, col_obj in [("LAA", c_laa), ("LAD", c_lad)]:
                with col_obj:
                    st.markdown(f"#### {'🔴' if team=='LAA' else '🔵'} {team} 隊史神主牌")
                    
                    meta = team_meta_summary[team]
                    st.markdown("##### 📊 歷史團隊累積總和")
                    st.markdown(f"**團隊火力**：{meta['hits']} 安打 | {meta['hr']} 全壘打 | {meta['rbi']} 打點")
                    st.markdown(f"**團隊壓制**：{meta['so']} 次防守三振")
                    
                    st.markdown("##### 🏟️ 主客場與極端戰績")
                    st.markdown(f"🏠 **主場戰績**：{meta['home_rec']}")
                    st.markdown(f"✈️ **客場戰績**：{meta['away_rec']}")
                    st.markdown(f"📐 **一分差生死戰**：{meta['one_run']}")
                    st.markdown("---")

                    st.markdown("##### 🎖️ 隊史累積排行榜 (Top 3)")
                    tb = b_all[b_all['球隊']==team]
                    tp = p_all[p_all['球隊']==team]
                    if not tb.empty:
                        st.caption(f"**🏏 安打王**：\n{get_top3_str(tb, '安打', '球員姓名')}")
                        st.caption(f"**🚀 全壘打王**：\n{get_top3_str(tb, '全壘打', '球員姓名')}")
                        st.caption(f"**🔥 打點王**：\n{get_top3_str(tb, '打點', '球員姓名')}")
                    if not tp.empty:
                        st.caption(f"**⚾ 勝投王**：\n{get_top3_str(tp, '勝', '投手姓名')}")
                        st.caption(f"**🌪️ 三振王**：\n{get_top3_str(tp, '奪三振', '投手姓名')}")
                        st.caption(f"**🌟 優質先發(QS)**：\n{get_top3_str(tp, 'QS', '投手姓名')}")
                        st.caption(f"**🔒 救援王**：\n{get_top3_str(tp, '救援', '投手姓名')}")
            st.divider()

            st.markdown("#### 🥇 歷史單一賽季極限紀錄 (Single-Season Records)")
            s_b_records = []
            s_p_records = []
            for s in range(1, max_season + 1):
                pref = f"[S{s}] 例行賽"
                s_b = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(pref, regex=False)].copy()
                s_p = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(pref, regex=False)].copy()
                if not s_b.empty:
                    for c in ['打席','打數','安打','全壘打','打點']: s_b[c] = pd.to_numeric(s_b.get(c, 0), errors='coerce').fillna(0)
                    min_pa = max(1.0, s_b['賽事階段'].nunique() * 1.0)
                    s_agg = s_b.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
                    for _, r in s_agg.iterrows():
                        avg = r['安打']/max(1, r['打數']) if r['打席'] >= min_pa else 0
                        s_b_records.append({'Season': s, 'Name': f"[{r['球隊']}] {r['球員姓名']}", 'HR': r['全壘打'], 'RBI': r['打點'], 'H': r['安打'], 'AVG': avg})
                if not s_p.empty:
                    s_p['勝'] = s_p['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                    s_p['救援'] = s_p['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                    for c in ['局數(整數)', '局數(出局數)', '奪三振', '自責分']: s_p[c] = pd.to_numeric(s_p.get(c, 0), errors='coerce').fillna(0)
                    s_p = s_p.sort_values('時間戳記')
                    s_p['is_SP'] = s_p.groupby(['球隊', '賽事階段']).cumcount() == 0
                    s_p['outs'] = s_p['局數(整數)'] * 3 + s_p['局數(出局數)']
                    s_p['QS'] = ((s_p['is_SP']) & (s_p['outs'] >= 6) & (s_p['自責分'] <= 1)).astype(int)
                    p_agg = s_p.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
                    min_ip = max(0.1, s_p['賽事階段'].nunique() * 0.33)
                    for _, r in p_agg.iterrows():
                        ip = (r['局數(整數)']*3 + r['局數(出局數)'])/3.0
                        era = (r['自責分']*9)/max(1, ip) if ip >= min_ip else 99.9
                        s_p_records.append({'Season': s, 'Name': f"[{r['球隊']}] {r['投手姓名']}", 'W': r['勝'], 'SV': r['救援'], 'K': r['奪三振'], 'QS': r['QS'], 'ERA': era})
                        
            c3, c4 = st.columns(2)
            with c3:
                st.caption("🏏 **打擊單季極限**")
                if s_b_records:
                    df_s_b = pd.DataFrame(s_b_records)
                    hr_max = df_s_b.loc[df_s_b['HR'].idxmax()]
                    rbi_max = df_s_b.loc[df_s_b['RBI'].idxmax()]
                    avg_max = df_s_b.loc[df_s_b['AVG'].idxmax()]
                    h_max = df_s_b.loc[df_s_b['H'].idxmax()]
                    st.markdown(f"- **最多全壘打**：{int(hr_max['HR'])} 轟 ({hr_max['Name']}, S{hr_max['Season']})")
                    st.markdown(f"- **最多打點**：{int(rbi_max['RBI'])} 分 ({rbi_max['Name']}, S{rbi_max['Season']})")
                    st.markdown(f"- **最多安打**：{int(h_max['H'])} 支 ({h_max['Name']}, S{h_max['Season']})")
                    if avg_max['AVG'] > 0: st.markdown(f"- **最高打擊率**：{avg_max['AVG']:.3f} ({avg_max['Name']}, S{avg_max['Season']})")
            with c4:
                st.caption("⚾ **投球單季極限**")
                if s_p_records:
                    df_s_p = pd.DataFrame(s_p_records)
                    w_max = df_s_p.loc[df_s_p['W'].idxmax()]
                    k_max = df_s_p.loc[df_s_p['K'].idxmax()]
                    qs_max = df_s_p.loc[df_s_p['QS'].idxmax()]
                    era_min = df_s_p[df_s_p['ERA'] < 99.9]
                    era_max = era_min.loc[era_min['ERA'].idxmin()] if not era_min.empty else None
                    st.markdown(f"- **最多勝投**：{int(w_max['W'])} 勝 ({w_max['Name']}, S{w_max['Season']})")
                    st.markdown(f"- **最多三振**：{int(k_max['K'])} 次 ({k_max['Name']}, S{k_max['Season']})")
                    st.markdown(f"- **最多 QS**：{int(qs_max['QS'])} 場 ({qs_max['Name']}, S{qs_max['Season']})")
                    if era_max is not None: st.markdown(f"- **最低防禦率**：{era_max['ERA']:.2f} ({era_max['Name']}, S{era_max['Season']})")

        # ==========================================
        # ⏳ Tab 4: 偉大里程碑追蹤 (Milestones - 3 Inning Edition)
        # ==========================================
        with t_milestones:
            st.subheader("⏳ 偉大里程碑追蹤器 (Milestones Tracker)")
            st.caption("系統自動掃描全聯盟，倒數即將達成的各項歷史指標 (僅顯示目前累積大於 2 且差距 3 以內的目標)。")
            
            pending_milestones = []
            
            def add_milestone(type_str, name, curr_val, targets):
                if curr_val <= 2: return # ✨ 嚴格過濾：本來就 2 以下的直接略過
                next_t = next((t for t in targets if curr_val < t), None)
                if next_t:
                    m = next_t - curr_val
                    if m <= 3: # ✨ 嚴格過濾：差距 3 步以內才顯示
                        pending_milestones.append({
                            'Type': type_str, 'Name': name, 'Curr': curr_val, 'Target': next_t, 'M': m
                        })

            # --- 1. 球員個人里程碑 (3局制專屬縮放) ---
            b_career = df_b_full.copy()
            for c in ['安打', '全壘打', '打點']: b_career[c] = pd.to_numeric(b_career.get(c, 0), errors='coerce').fillna(0)
            b_c_agg = b_career.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
            for _, r in b_c_agg.iterrows():
                name = f"[{r['球隊']}] {r['球員姓名']}"
                add_milestone('🏏 生涯安打', name, r['安打'], [15, 30, 50, 100, 150, 200])
                add_milestone('🚀 生涯全壘打', name, r['全壘打'], [5, 10, 20, 30, 50, 100])
                add_milestone('🔥 生涯打點', name, r['打點'], [10, 30, 50, 100, 150])
            
            p_career = df_p_full.copy()
            p_career['勝'] = p_career['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
            p_career['救援'] = p_career['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
            p_career['奪三振'] = pd.to_numeric(p_career.get('奪三振', 0), errors='coerce').fillna(0)
            p_c_agg = p_career.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
            for _, r in p_c_agg.iterrows():
                name = f"[{r['球隊']}] {r['投手姓名']}"
                add_milestone('⚾ 生涯勝投', name, r['勝'], [5, 10, 20, 30, 50])
                add_milestone('🌪️ 生涯三振', name, r['奪三振'], [10, 30, 50, 100, 150])
                add_milestone('🔒 生涯救援', name, r['救援'], [5, 10, 20, 30])

            # --- 2. 團隊累積里程碑 (3局制專屬縮放) ---
            team_wins = {'LAA': 0, 'LAD': 0}
            team_hrs = {'LAA': 0, 'LAD': 0}
            team_hits = {'LAA': 0, 'LAD': 0}
            team_ks = {'LAA': 0, 'LAD': 0}
            
            if not df_p_full.empty:
                for _, group in df_p_full.groupby('賽事階段'):
                    for team in ['LAA', 'LAD']:
                        t_g = group[group['球隊'] == team]
                        if not t_g.empty and any('勝' in str(x) for x in t_g['勝敗'].values): team_wins[team] += 1
                for team in ['LAA', 'LAD']:
                    t_g = df_p_full[df_p_full['球隊'] == team]
                    team_ks[team] = pd.to_numeric(t_g['奪三振'], errors='coerce').fillna(0).sum()
                    
            if not df_b_full.empty:
                for team in ['LAA', 'LAD']:
                    t_b = df_b_full[df_b_full['球隊'] == team]
                    team_hrs[team] = pd.to_numeric(t_b['全壘打'], errors='coerce').fillna(0).sum()
                    team_hits[team] = pd.to_numeric(t_b['安打'], errors='coerce').fillna(0).sum()
            
            for team in ['LAA', 'LAD']:
                add_milestone('🏟️ 團隊總勝場', f"[{team}] 隊史", team_wins[team], [10, 20, 30, 50, 100])
                add_milestone('🏟️ 團隊總全壘打', f"[{team}] 隊史", team_hrs[team], [30, 50, 100, 200])
                add_milestone('🏟️ 團隊總安打', f"[{team}] 隊史", team_hits[team], [50, 100, 200, 300, 500])
                add_milestone('🏟️ 團隊總三振', f"[{team}] 隊史", team_ks[team], [50, 100, 200, 300, 500])

            # --- ✨ 分開獨立顯示 ---
            ms_df = pd.DataFrame(pending_milestones)
            if not ms_df.empty:
                categories = ['🏏 生涯安打', '🚀 生涯全壘打', '🔥 生涯打點', '⚾ 生涯勝投', '🌪️ 生涯三振', '🔒 生涯救援', 
                              '🏟️ 團隊總安打', '🏟️ 團隊總全壘打', '🏟️ 團隊總勝場', '🏟️ 團隊總三振']
                
                c1, c2 = st.columns(2)
                cols = [c1, c2]
                col_idx = 0
                
                for cat in categories:
                    cat_df = ms_df[ms_df['Type'] == cat]
                    if not cat_df.empty:
                        with cols[col_idx % 2]:
                            st.markdown(f"#### {cat}")
                            cat_df = cat_df.sort_values('M')
                            for _, r in cat_df.iterrows():
                                icon = "🔥" if r['M'] <= 1 else "⏳"
                                # ✨ 改用溫和底色 (info 藍色 / warning 黃色) 替代原本可怕的紅色
                                if r['M'] <= 1:
                                    st.warning(f"{icon} **{r['Name']}** 累積 {int(r['Curr'])} ➔ 目標 **{int(r['Target'])}** (M{int(r['M'])})")
                                else:
                                    st.info(f"{icon} **{r['Name']}** 累積 {int(r['Curr'])} ➔ 目標 **{int(r['Target'])}** (M{int(r['M'])})")
                        col_idx += 1
            else:
                st.success("目前全聯盟距離下一個里程碑都還有一段距離。")

        # ==========================================
        # 💎 Tab 5: 神聖領域與連勝 (Streaks & No-Hitters)
        # ==========================================
        with t_streaks:
            st.subheader("💎 神聖領域 (No-Hitters & Perfect Games)")
            perfect_games, no_hitters, combined_pgs, combined_nohos = [], [], [], []
            if not df_p_full.empty:
                for stage, g_stage in df_p_full.groupby('賽事階段', sort=False):
                    for team, g_team in g_stage.groupby('球隊', sort=False):
                        g_t = g_team.sort_values('時間戳記')
                        outs = pd.to_numeric(g_t.get('局數(整數)', 0), errors='coerce').fillna(0) * 3 + pd.to_numeric(g_t.get('局數(出局數)', 0), errors='coerce').fillna(0)
                        tot_outs = outs.sum()
                        tot_hits = pd.to_numeric(g_t.get('被安打', 0), errors='coerce').fillna(0).sum()
                        tot_bb = pd.to_numeric(g_t.get('四壞球', 0), errors='coerce').fillna(0).sum()
                        tot_runs = pd.to_numeric(g_t.get('失分', 0), errors='coerce').fillna(0).sum()
                        
                        if tot_outs >= 9 and tot_hits == 0:
                            p_list = []
                            for idx, r in g_t.iterrows():
                                o = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                                if o > 0: p_list.append(f"{r['投手姓名']} ({int(o//3)}.{int(o%3)} 局)")
                            if not p_list: continue
                            p_str = " ➔ ".join(p_list)
                            stg_clean = clean_stage_name(stage)
                            rec_str = f"**[{team}]** {p_str}  \n*(於 {stg_clean} 達成)*"
                            
                            is_pg = (tot_bb == 0 and tot_runs == 0)
                            is_comb = len(g_t['投手姓名'].unique()) > 1
                            if is_pg and is_comb: combined_pgs.append(rec_str)
                            elif is_pg and not is_comb: perfect_games.append(rec_str)
                            elif not is_pg and is_comb: combined_nohos.append(rec_str)
                            elif not is_pg and not is_comb: no_hitters.append(rec_str)

            def display_shrine(title, records, icon):
                st.markdown(f"#### {title}")
                if not records: st.caption("📌 尚無人達成此神聖領域")
                else:
                    for r in records: st.markdown(f"{icon} {r}")
                st.divider()

            display_shrine("🌟 完全比賽 (Perfect Game)", perfect_games, "🏆")
            display_shrine("🤝 接力完全比賽 (Combined PG)", combined_pgs, "🏅")
            display_shrine("✨ 無安打比賽 (No-Hitter)", no_hitters, "💎")
            display_shrine("🤝 接力無安打比賽 (Combined No-Hitter)", combined_nohos, "🎖️")

            st.subheader("🔥 史詩連續紀錄 (Streaks)")
            def display_record(title, val_all, names_all, val_curr, names_curr, unit="場"):
                st.markdown(f"#### {title}")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**🥇 歷史最高：{val_all} {unit}**")
                    if val_all == 0: st.caption("📌 無")
                    elif len(names_all) <= 5: 
                        for n in names_all: st.caption(f"📌 {n}")
                    else:
                        for n in names_all[:3]: st.caption(f"📌 {n}")
                        with st.expander(f"🤝 查看並列保持者 (共 {len(names_all)} 位)"):
                            for n in names_all[3:]: st.caption(f"📌 {n}")
                with c2:
                    st.markdown(f"**📍 本季最高：{val_curr} {unit}**")
                    if val_curr == 0: st.caption("📌 無")
                    elif len(names_curr) <= 5:
                        for n in names_curr: st.caption(f"📌 {n}")
                    else:
                        for n in names_curr[:3]: st.caption(f"📌 {n}")
                        with st.expander(f"🤝 查看本季保持者 (共 {len(names_curr)} 位)"):
                            for n in names_curr[3:]: st.caption(f"📌 {n}")
                st.divider()

            def get_streak_record_exact(df, streak_type, loc_filter=None):
                if df.empty: return 0, []
                records = []
                if streak_type in ['win', 'loss']:
                    for (team, stage), g in df.groupby(['球隊', '賽事階段'], sort=False):
                        ts = g['時間戳記'].min()
                        if streak_type == 'win': cond = any('勝' in str(x) for x in g.get('勝敗', []))
                        else: cond = any('敗' in str(x) for x in g.get('勝敗', []))
                        records.append({'keys': team, 'stage': stage, 'ts': ts, 'cond': cond})
                elif streak_type in ['hit', 'hr', 'hitless']:
                    for (team, name, stage), g in df.groupby(['球隊', '球員姓名', '賽事階段'], sort=False):
                        ts = g['時間戳記'].min()
                        hit_v = pd.to_numeric(g['安打'], errors='coerce').fillna(0).sum()
                        hr_v = pd.to_numeric(g['全壘打'], errors='coerce').fillna(0).sum()
                        ab_v = pd.to_numeric(g['打數'], errors='coerce').fillna(0).sum()
                        if streak_type == 'hit': cond = hit_v > 0
                        elif streak_type == 'hr': cond = hr_v > 0
                        elif streak_type == 'hitless': cond = (ab_v > 0 and hit_v == 0)
                        records.append({'keys': (team, name), 'stage': stage, 'ts': ts, 'cond': cond})
                elif streak_type.startswith('zero_run') or streak_type == 'hr_allowed':
                    for (team, stage), g_stage in df.groupby(['球隊', '賽事階段'], sort=False):
                        g_stage = g_stage.sort_values('時間戳記')
                        for i, (_, r) in enumerate(g_stage.iterrows()):
                            is_sp = (i == 0)
                            if streak_type == 'zero_run_sp' and not is_sp: continue
                            if streak_type == 'zero_run_rp' and is_sp: continue
                            ts = r['時間戳記']
                            name = r['投手姓名']
                            if streak_type.startswith('zero_run'):
                                r_runs = pd.to_numeric(r.get('失分', 0), errors='coerce')
                                ip_out = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                                cond = (r_runs == 0 and ip_out > 0)
                            else:
                                hr_a = pd.to_numeric(r.get('被全壘打', 0), errors='coerce')
                                cond = hr_a > 0
                            records.append({'keys': (team, name), 'stage': stage, 'ts': ts, 'cond': cond})
                if not records: return 0, []
                seq_df = pd.DataFrame(records).sort_values('ts')
                if loc_filter:
                    filtered = []
                    for _, r in seq_df.iterrows():
                        team = r['keys'][0] if isinstance(r['keys'], tuple) else r['keys']
                        h_team = global_home_dict.get(r['stage'], "Unknown")
                        if loc_filter == 'home' and team == h_team: filtered.append(r)
                        elif loc_filter == 'away' and team != h_team: filtered.append(r)
                    seq_df = pd.DataFrame(filtered)
                    if seq_df.empty: return 0, []
                max_streak = 0
                holders = []
                for k, group in seq_df.groupby('keys', sort=False):
                    curr_streak = 0
                    st_stage = ""
                    for _, r in group.iterrows():
                        if r['cond']:
                            if curr_streak == 0: st_stage = r['stage']
                            curr_streak += 1
                            ed_stage = r['stage']
                            ed_ts = r['ts']
                            if curr_streak > max_streak:
                                max_streak = curr_streak
                                holders = [{'keys': k, 'start': st_stage, 'end': ed_stage, 'end_ts': ed_ts}]
                            elif curr_streak == max_streak and max_streak > 0:
                                holders.append({'keys': k, 'start': st_stage, 'end': ed_stage, 'end_ts': ed_ts})
                        else: curr_streak = 0
                if max_streak == 0: return 0, []
                names_list = []
                for h in holders:
                    k = h['keys']
                    st_clean = clean_stage_name(h['start'])
                    ed_clean = clean_stage_name(h['end'])
                    span_str = f"({st_clean} ~ {ed_clean})" if st_clean != ed_clean else f"({st_clean})"
                    t_name = k[0] if isinstance(k, tuple) else k
                    if streak_type in ['win', 'loss']: p_last_ts = global_last_ts_p_team.get(t_name, 0)
                    elif streak_type in ['hit', 'hr', 'hitless']: p_last_ts = global_last_ts_b_player.get(k, 0)
                    else: p_last_ts = global_last_ts_p_player.get(k, 0)
                    is_ongoing = (h['end_ts'] >= p_last_ts) and (f"[S{max_season}]" in h['end'])
                    ongoing_str = " 🔥(延續中)" if is_ongoing else ""
                    if isinstance(k, tuple): names_list.append(f"[{k[0]}] {k[1]} {span_str}{ongoing_str}")
                    else: names_list.append(f"{k} {span_str}{ongoing_str}")
                return max_streak, names_list

            df_b_curr = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(curr_s_prefix, regex=False)] if not df_b_full.empty else pd.DataFrame()
            df_p_curr = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(curr_s_prefix, regex=False)]
            
            w_val_a, w_nam_a = get_streak_record_exact(df_p_full, 'win')
            w_val_c, w_nam_c = get_streak_record_exact(df_p_curr, 'win')
            display_record("🔥 聯盟最長連勝", w_val_a, w_nam_a, w_val_c, w_nam_c)
            
            hw_val_a, hw_nam_a = get_streak_record_exact(df_p_full, 'win', loc_filter='home')
            hw_val_c, hw_nam_c = get_streak_record_exact(df_p_curr, 'win', loc_filter='home')
            display_record("🏠 最長主場連勝", hw_val_a, hw_nam_a, hw_val_c, hw_nam_c)
            
            aw_val_a, aw_nam_a = get_streak_record_exact(df_p_full, 'win', loc_filter='away')
            aw_val_c, aw_nam_c = get_streak_record_exact(df_p_curr, 'win', loc_filter='away')
            display_record("✈️ 最長客場連勝", aw_val_a, aw_nam_a, aw_val_c, aw_nam_c)

            l_val_a, l_nam_a = get_streak_record_exact(df_p_full, 'loss')
            l_val_c, l_nam_c = get_streak_record_exact(df_p_curr, 'loss')
            display_record("🥶 聯盟最長連敗 (黑暗期)", l_val_a, l_nam_a, l_val_c, l_nam_c)

            h_val_a, h_nam_a = get_streak_record_exact(df_b_full, 'hit')
            h_val_c, h_nam_c = get_streak_record_exact(df_b_curr, 'hit')
            display_record("🏏 最長連續場次安打", h_val_a, h_nam_a, h_val_c, h_nam_c)

            hr_val_a, hr_nam_a = get_streak_record_exact(df_b_full, 'hr')
            hr_val_c, hr_nam_c = get_streak_record_exact(df_b_curr, 'hr')
            display_record("🚀 最長連續場次全壘打", hr_val_a, hr_nam_a, hr_val_c, hr_nam_c)

            zsp_val_a, zsp_nam_a = get_streak_record_exact(df_p_full, 'zero_run_sp')
            zsp_val_c, zsp_nam_c = get_streak_record_exact(df_p_curr, 'zero_run_sp')
            display_record("🛡️ 先發投手連續出賽無失分", zsp_val_a, zsp_nam_a, zsp_val_c, zsp_nam_c)
            
            zrp_val_a, zrp_nam_a = get_streak_record_exact(df_p_full, 'zero_run_rp')
            zrp_val_c, zrp_nam_c = get_streak_record_exact(df_p_curr, 'zero_run_rp')
            display_record("🔒 牛棚後援連續出賽無失分", zrp_val_a, zrp_nam_a, zrp_val_c, zrp_nam_c)

        # ==========================================
        # 🤯 Tab 6: 單場極端與進階榜 (Sabermetrics Extremes)
        # ==========================================
        with t_extremes:
            st.subheader("🤯 聯盟單場極端紀錄與進階大數據榜 (Extremes & Sabermetrics)")
            
            st.markdown("### ⚖️ 歷史運氣與進階數據極端榜")
            st.caption("透過 BABIP 與 FIP 窺探球員的真實命運！誰是天選之人？誰又是地獄倒楣鬼？(※ 需達一定生涯打席/局數門檻)")
            
            min_career_pa = max_season * 3.0
            min_career_ip = max_season * 1.0
            
            b_agg_saber = df_b_full.copy()
            for col in ['打席','打數','安打','全壘打','三振','四壞球']: b_agg_saber[col] = pd.to_numeric(b_agg_saber.get(col, 0), errors='coerce').fillna(0)
            b_saber = b_agg_saber.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
            
            p_agg_saber = df_p_full.copy()
            for col in ['局數(整數)', '局數(出局數)', '奪三振', '自責分', '四壞球', '被全壘打']: p_agg_saber[col] = pd.to_numeric(p_agg_saber.get(col, 0), errors='coerce').fillna(0)
            p_saber = p_agg_saber.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
            p_saber['局數'] = (p_saber['局數(整數)']*3 + p_saber['局數(出局數)'])/3.0
            
            c_ext1, c_ext2 = st.columns(2)
            with c_ext1:
                st.markdown("#### 🎰 運氣天平 (BABIP 極端值)")
                b_saber_qual = b_saber[b_saber['打席'] >= min_career_pa].copy()
                if not b_saber_qual.empty:
                    b_saber_qual['BABIP'] = (b_saber_qual['安打'] - b_saber_qual['全壘打']) / (b_saber_qual['打數'] - b_saber_qual['三振'] - b_saber_qual['全壘打']).replace(0, 1)
                    
                    lucky = b_saber_qual.sort_values('BABIP', ascending=False).iloc[0]
                    st.metric("🍀 天選之人 (生涯最高 BABIP)", f"{lucky['BABIP']:.3f}", f"[{lucky['球隊']}] {lucky['球員姓名']}")
                    
                    unlucky = b_saber_qual.sort_values('BABIP', ascending=True).iloc[0]
                    st.metric("🐈‍⬛ 地獄倒楣鬼 (生涯最低 BABIP)", f"{unlucky['BABIP']:.3f}", f"[{unlucky['球隊']}] {unlucky['球員姓名']}")
                else: st.info("尚無球員達生涯打席門檻。")
                
                if not b_saber_qual.empty:
                    b_saber_qual['TTO'] = (b_saber_qual['全壘打'] + b_saber_qual['三振'] + b_saber_qual['四壞球']) / b_saber_qual['打席'].replace(0, 1) * 100
                    tto_king = b_saber_qual.sort_values('TTO', ascending=False).iloc[0]
                    st.metric("🎲 一翻兩瞪眼 (生涯最高 TTO%)", f"{tto_king['TTO']:.1f}%", f"[{tto_king['球隊']}] {tto_king['球員姓名']}", help="打出去的球完全不靠野手守備，直接靠全壘打、保送或三振定生死！")
                    
            with c_ext2:
                st.markdown("#### 🛡️ 真金不怕火煉 (FIP-ERA 差距)")
                p_saber_qual = p_saber[p_saber['局數'] >= min_career_ip].copy()
                if not p_saber_qual.empty:
                    p_saber_qual['ERA'] = (p_saber_qual['自責分'] * 9) / p_saber_qual['局數'].replace(0, 1)
                    p_saber_qual['FIP'] = (((13*p_saber_qual['被全壘打'])+(3*p_saber_qual['四壞球'])-(2*p_saber_qual['奪三振']))/p_saber_qual['局數'].replace(0, 1)) + 3.10
                    p_saber_qual['DIFF'] = p_saber_qual['FIP'] - p_saber_qual['ERA']
                    
                    real_deal = p_saber_qual.sort_values('DIFF', ascending=True).iloc[0]
                    st.metric("💡 悲情實力派 (FIP 遠低於 ERA)", f"FIP {real_deal['FIP']:.2f} (ERA {real_deal['ERA']:.2f})", f"[{real_deal['球隊']}] {real_deal['投手姓名']}", help="防禦率看起來差，但獨立防禦率極低，代表他的失分幾乎都是隊友守備雷的非戰之罪！")
                    
                    mirage = p_saber_qual.sort_values('DIFF', ascending=False).iloc[0]
                    st.metric("🎰 強運幻象 (ERA 遠低於 FIP)", f"ERA {mirage['ERA']:.2f} (FIP {mirage['FIP']:.2f})", f"[{mirage['球隊']}] {mirage['投手姓名']}", help="防禦率極漂亮，但其實獨立防禦率很高，代表他極度依賴隊友的超神守備來度過難關！")
                else: st.info("尚無投手達生涯局數門檻。")
            st.divider()

            st.markdown("### 🏟️ 團隊與個人單場極端紀錄")
            def get_extreme_clean(df, col, is_max=True, is_pitcher=False):
                if df.empty or col not in df.columns: return 0, []
                df_c = df.copy()
                df_c[col] = pd.to_numeric(df_c[col], errors='coerce').fillna(0)
                if df_c.empty: return 0, []
                val = df_c[col].max() if is_max else df_c[col].min()
                if val == 0: return 0, []
                rows = df_c[df_c[col] == val]
                name_col = '投手姓名' if is_pitcher else '球員姓名'
                holder_list = []
                for _, r in rows.iterrows():
                    stage_clean = clean_stage_name(r.get('賽事階段', ''))
                    h_str = f"[{r['球隊']}] {r[name_col]} ({stage_clean})"
                    if h_str not in holder_list: holder_list.append(h_str)
                return val, holder_list

            def get_team_extreme_clean(df, col, is_max=True):
                if df.empty or col not in df.columns: return 0, []
                df_c = df.copy()
                df_c[col] = pd.to_numeric(df_c[col], errors='coerce').fillna(0)
                if df_c.empty: return 0, []
                team_agg = df_c.groupby(['賽事階段', '球隊'])[col].sum().reset_index()
                val = team_agg[col].max() if is_max else team_agg[col].min()
                if val == 0: return 0, []
                rows = team_agg[team_agg[col] == val]
                holder_list = []
                for _, r in rows.iterrows():
                    stage_clean = clean_stage_name(r['賽事階段'])
                    h_str = f"[{r['球隊']}] ({stage_clean})"
                    if h_str not in holder_list: holder_list.append(h_str)
                return val, holder_list

            def display_extreme(title, val, names, unit="", icon="🥇"):
                st.markdown(f"#### {title}")
                st.markdown(f"**{icon} 歷史極端值：{int(val)} {unit}**")
                if val == 0: st.caption("📌 無人達標")
                else:
                    if len(names) <= 5:
                        for n in names: st.caption(f"📌 {n}")
                    else:
                        for n in names[:5]: st.caption(f"📌 {n}")
                        with st.expander(f"🤝 查看其餘 {len(names)-5} 筆紀錄"):
                            for n in names[5:]: st.caption(f"📌 {n}")
                st.divider()

            diff_records, max_diff = [], 0
            if not df_p_full.empty:
                for stage, group in df_p_full.groupby('賽事階段'):
                    laa_ra = pd.to_numeric(group[group['球隊']=='LAA']['失分'], errors='coerce').fillna(0).sum()
                    lad_ra = pd.to_numeric(group[group['球隊']=='LAD']['失分'], errors='coerce').fillna(0).sum()
                    diff = abs(laa_ra - lad_ra)
                    if diff > 0:
                        win_team = 'LAA' if lad_ra > laa_ra else 'LAD'
                        lose_team = 'LAD' if win_team == 'LAA' else 'LAA'
                        win_score = max(laa_ra, lad_ra)
                        lose_score = min(laa_ra, lad_ra)
                        diff_records.append({'stage': stage, 'diff': diff, 'desc': f"[{win_team}] 狂勝 [{lose_team}] ({int(win_score)}:{int(lose_score)})"})
                if diff_records:
                    max_diff = max([x['diff'] for x in diff_records])
                    diff_holders = []
                    for x in diff_records:
                        if x['diff'] == max_diff:
                            stage_clean = clean_stage_name(x['stage'])
                            h_str = f"{x['desc']} ({stage_clean})"
                            if h_str not in diff_holders: diff_holders.append(h_str)
            display_extreme("🩸 血流成河 (單場最大比分差)", max_diff, diff_holders if max_diff > 0 else [], "分", "😱")

            team_runs_records = []
            if not df_p_full.empty:
                for stage, group in df_p_full.groupby('賽事階段'):
                    laa_runs = pd.to_numeric(group[group['球隊']=='LAD']['失分'], errors='coerce').fillna(0).sum()
                    lad_runs = pd.to_numeric(group[group['球隊']=='LAA']['失分'], errors='coerce').fillna(0).sum()
                    if laa_runs > 0: team_runs_records.append({'keys': 'LAA', 'stage': stage, 'runs': laa_runs})
                    if lad_runs > 0: team_runs_records.append({'keys': 'LAD', 'stage': stage, 'runs': lad_runs})
            tr_val, tr_nam = 0, []
            if team_runs_records:
                tr_val = max([x['runs'] for x in team_runs_records])
                for x in team_runs_records:
                    if x['runs'] == tr_val:
                        stg = clean_stage_name(x['stage'])
                        h_str = f"[{x['keys']}] ({stg})"
                        if h_str not in tr_nam: tr_nam.append(h_str)
            display_extreme("🎇 煙火大會 (球隊單場最多得分)", tr_val, tr_nam, "分", "🔥")

            t_h_val, t_h_nam = get_team_extreme_clean(df_b_full, '安打', True)
            display_extreme("🏏 機槍打線 (球隊單場最多安打)", t_h_val, t_h_nam, "支", "🔥")

            t_hr_val, t_hr_nam = get_team_extreme_clean(df_b_full, '全壘打', True)
            display_extreme("🚀 轟炸大隊 (球隊單場最多全壘打)", t_hr_val, t_hr_nam, "轟", "🔥")

            np_p_val, np_p_nam = get_extreme_clean(df_p_full, '投球數', True, True)
            display_extreme("💪 燃燒手臂 (單一投手最多用球數)", np_p_val, np_p_nam, "球")

            k_b_val, k_b_nam = get_extreme_clean(df_b_full, '三振', True, False)
            display_extreme("🌪️ 電風扇之王 (打者單場最多被三振)", k_b_val, k_b_nam, "次")

            r_p_val, r_p_nam = get_extreme_clean(df_p_full, '失分', True, True)
            display_extreme("🧨 發球機核爆 (投手單場最多失分)", r_p_val, r_p_nam, "分")
            
            df_b_c = df_b_full.copy()
            for c in ['打數', '安打', '打點']: df_b_c[c] = pd.to_numeric(df_b_c.get(c, 0), errors='coerce').fillna(0)
            
            df_sombrero = df_b_c[(df_b_c['安打'] == 0) & (df_b_c['打數'] >= 3)]
            sombrero_val, sombrero_nam = get_extreme_clean(df_sombrero, '打數', True, False)
            display_extreme("🏆 黃金老帽 (單場至少3打數且0安打)", sombrero_val, sombrero_nam, "打數")

            df_no_rbi = df_b_c[(df_b_c['打點'] == 0) & (df_b_c['安打'] >= 2)]
            norbi_val, norbi_nam = get_extreme_clean(df_no_rbi, '安打', True, False)
            display_extreme("🏃‍♂️ 白做工 (單場至少2安打卻0打點)", norbi_val, norbi_nam, "支")