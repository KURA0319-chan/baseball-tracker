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
# 專屬設定 & 規定門檻設定 (MLB 標準)
# ==========================================
SERVICE_ACCOUNT_FILE = 'baseball.json'
SHEET_NAME = '棒球數據資料庫'
TEAMS = ["LAA", "LAD"]

SEASONS = [f"Season {i}" for i in range(1, 11)]
GAME_STAGES = [f"例行賽 G{i}" for i in range(1, 11)] + [f"世界大賽 G{i}" for i in range(1, 8)]

if 'clear_bat' not in st.session_state: st.session_state.clear_bat = False
if 'clear_pitch' not in st.session_state: st.session_state.clear_pitch = False

if st.session_state.get('clear_bat'):
    for k in ['h_b', 'rbi_b', 'run_b', 'hr_b', 'bb_b', 'so_b', 'sb_b', 'tb2_b', 'tb3_b']:
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
if 'pitchers' not in st.session_state: st.session_state.pitchers = saved_data.get("pitchers", {'LAA': "", 'LAD': ""})
if 'default_season' not in st.session_state: st.session_state.default_season = saved_data.get("default_season", "十年總成績")
if 'f_game_pref' not in st.session_state: st.session_state.f_game_pref = saved_data.get("f_game_pref", "看整季")
    
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

def get_career_stats():
    records_b = get_raw_records("打擊單場紀錄")
    records_p = get_raw_records("投手單場紀錄")
    
    try:
        if records_b:
            df_b = pd.DataFrame(records_b, columns=['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘'])
            num_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            for col in num_cols: df_b[col] = pd.to_numeric(df_b[col], errors='coerce').fillna(0)
            st.session_state.df_b_raw = df_b 
        else:
            # ✨ 防呆機制：就算沒資料，也要先建好有表頭的空表格，防止 KeyError
            st.session_state.df_b_raw = pd.DataFrame(columns=['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘'])
    except: pass

    try:
        if records_p:
            df_p = pd.DataFrame(records_p, columns=['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分'])
            p_cols = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            for col in p_cols: df_p[col] = pd.to_numeric(df_p[col], errors='coerce').fillna(0)
            st.session_state.df_p_raw = df_p
        else:
            # ✨ 防呆機制：就算沒資料，也要先建好有表頭的空表格，防止 KeyError
            st.session_state.df_p_raw = pd.DataFrame(columns=['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分'])
    except: pass
    try:
        if records_p:
            df_p = pd.DataFrame(records_p, columns=['時間戳記', '賽事階段', '球隊', '投手姓名', '勝敗', '局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分'])
            p_cols = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            for col in p_cols: df_p[col] = pd.to_numeric(df_p[col], errors='coerce').fillna(0)
            st.session_state.df_p_raw = df_p
    except: pass

# ==========================================
# 網頁介面設計
# ==========================================
st.set_page_config(page_title="LAA vs LAD 數據中心", page_icon="⚾", layout="wide")
st.title("⚾ 洛杉磯雙雄數據追蹤系統 V44 (正式開季版)")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["⚾ 打擊單場輸入", "🥎 投球單場輸入", "🏆 累積數據總表", "📋 賽前戰情室", "🎖️ 聯盟大獎預測"])

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
    st.info("💡 提醒：【安打】欄位請填寫包含長打在內的「總安打數」。(送出後會自動歸零累積數據，保留打席數方便連續登錄)")
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
                    ws.append_row([now, full_stage_b, team_b, player_b, pa, ab, h, tb2, tb3, hr, rbi, run, bb, so, sb])
                    st.success(f"✅ 成功儲存 {player_b} 的表現！")
                    get_raw_records.clear()
                    st.session_state.clear_bat = True
                    time.sleep(1)
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
        options_p = ["➕ 手動輸入新投手..."] + available_pitchers
        selected_p_p = st.selectbox("選擇投手", options_p, key="sel_p")
        if selected_p_p == "➕ 手動輸入新投手...": player_p = st.text_input("輸入姓名", key="txt_p")
        else: player_p = selected_p_p
    with col_res_p: 
        p_res = st.selectbox("勝敗紀錄", p_res_options, key="p_res", help="同場比賽的勝/敗/救援若已被其他投手登錄，選項會自動隱藏！")
        
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
                    ws.append_row([now, full_stage_p, team_p, player_p, p_res, ip_full, ip_outs, bf, np_pitch, h_p, hr_p, bb_p, so_p, r, er])
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
        * **WAR (勝場貢獻值)：** 衡量一名球員「比替補多替球隊拿幾勝」。本系統特製 **eWAR** 透過 wRC+ 與 FIP 精算而成。
        * **wRC+ (加權創造得分)：** ✨ **100 為全聯盟平均**。150 代表火力比聯盟平均高出 50%，是現代棒球最精準的打擊指標 (無負數)。
        * **wOBA (加權上壘率)：** 依照安打與保送的實際得分價值給予不同權重。
        * **ISO (純長打率)：** 評估打者真正的長打火力，> 0.200 即為重砲手。
        * **BABIP (場內安打率)：** 剔除全壘打與三振後的安打率。異常高代表強運，異常低代表被守備針對或運氣極差。
        * **FIP (獨立防禦率)：** 剔除守備與運氣成分。
        * **HR/9 (每九局被全壘打)：** 投手飛球控制力的指標。
        * **P/IP (每局用球數)：** 投手效率指標。**14球以下**為極致省球，**18球以上**代表常陷入纏鬥。
        * **WHIP (每局被上壘率)：** < **1.20** 就算是非常優秀的投手。
        """)

    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 2.5])
    with col_f1:
        if st.button("🔄 刷新數據", type="primary"): 
            get_raw_records.clear()
            st.rerun()
            
    with col_f2:
        season_options = ["十年總成績"] + SEASONS
        s_idx = season_options.index(st.session_state.default_season) if st.session_state.default_season in season_options else 0
        def update_season():
            st.session_state.default_season = st.session_state.f_season
            if 'save_settings' in globals(): save_settings()
        filter_season = st.selectbox("篩選賽季", season_options, index=s_idx, key="f_season", on_change=update_season)

    with col_f3:
        if filter_season == "十年總成績":
            filter_game = st.selectbox("比賽階段", ["不限 (看全部)"], disabled=True, key="f_game")
            target_prefix = ""
        else:
            game_options = ["看整季", "例行賽總和", "世界大賽總和"] + GAME_STAGES
            saved_game = st.session_state.get("f_game_pref", "看整季")
            g_idx = game_options.index(saved_game) if saved_game in game_options else 0
            def update_game():
                st.session_state.f_game_pref = st.session_state.f_game_sel
                if 'save_settings' in globals(): save_settings()
            filter_game = st.selectbox("比賽階段", game_options, index=g_idx, key="f_game_sel", on_change=update_game)
            s_num = filter_season.split(" ")[1]
            if filter_game == "看整季": target_prefix = f"[S{s_num}]"
            elif filter_game == "例行賽總和": target_prefix = f"[S{s_num}] 例行賽"
            elif filter_game == "世界大賽總和": target_prefix = f"[S{s_num}] 世界大賽"
            else: target_prefix = f"[S{s_num}] {filter_game}"

    get_career_stats()
    df_b = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p = st.session_state.get('df_p_raw', pd.DataFrame())

    b_filter_df = df_b[df_b['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix and not df_b.empty else df_b
    team_games_played = b_filter_df['賽事階段'].nunique() if not b_filter_df.empty else 1
    
    dynamic_qualify_pa = max(1.0, team_games_played * 1.2)
    dynamic_qualify_ip = max(0.1, team_games_played * 0.33)

    st.markdown("### 📊 球隊戰績排名 (Team Standings)")
    if not df_p.empty:
        stand_b = df_b[df_b['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix and not df_b.empty else df_b
        stand_p = df_p[df_p['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix else df_p
        
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
                
                if not group.empty:
                    starters.append(group.iloc[0]['投手姓名'])
            
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
                    if not g_sorted.empty:
                        reg_starters.append(g_sorted.iloc[0]['投手姓名'])
                
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
                    if not starters:
                        next_sp = top_ws_rotation[0] 
                    else:
                        last_app_idx = {}
                        for sp in top_ws_rotation:
                            if sp in starters:
                                last_app_idx[sp] = len(starters) - 1 - starters[::-1].index(sp)
                            else:
                                last_app_idx[sp] = -1 
                        next_sp = min(top_ws_rotation, key=lambda x: (last_app_idx[x], top_ws_rotation.index(x)))
                        
                        if next_sp == last_sp and len(top_ws_rotation) > 1:
                            temp_rot = [x for x in top_ws_rotation if x != last_sp]
                            next_sp = min(temp_rot, key=lambda x: (last_app_idx[x], top_ws_rotation.index(x)))
                            
            else:
                if target_prefix:
                    s_num_str = target_prefix.split(" ")[0] 
                    t_p_season = df_p[(df_p['球隊'] == team) & (df_p['賽事階段'].astype(str).str.contains(s_num_str, regex=False))].sort_values('時間戳記')
                else:
                    t_p_season = df_p[df_p['球隊'] == team].sort_values('時間戳記')
                    
                season_starters = []
                for stage, group in t_p_season.groupby('賽事階段', sort=False):
                    g_sorted = group.sort_values('時間戳記')
                    if not g_sorted.empty:
                        season_starters.append(g_sorted.iloc[0]['投手姓名'])
                
                if season_starters:
                    last_sp = season_starters[-1]
                    counts = {}
                    for sp in season_starters: counts[sp] = counts.get(sp, 0) + 1
                    top_sps = sorted(counts.keys(), key=lambda x: counts[x], reverse=True)[:5]
                    
                    last_app_idx = {}
                    for sp in top_sps:
                        last_app_idx[sp] = len(season_starters) - 1 - season_starters[::-1].index(sp)
                    
                    next_sp = min(top_sps, key=lambda x: last_app_idx[x])
                    
                    if next_sp == last_sp and len(top_sps) > 1:
                        temp_sps = [x for x in top_sps if x != last_sp]
                        next_sp = min(temp_sps, key=lambda x: last_app_idx[x])
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
            num_cols_b = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            agg_b = curr_b.groupby(['球隊', '球員姓名']).agg({
                '打席': 'sum', '打數': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', 
                '全壘打': 'sum', '打點': 'sum', '得分': 'sum', '四壞球': 'sum', '三振': 'sum', '盜壘': 'sum',
                '賽事階段': 'count' 
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
            lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.001
            
            agg_b['wOBA'] = (0.69 * agg_b['四壞球'] + 0.88 * agg_b['一壘安打'] + 1.25 * agg_b['二壘安打'] + 1.59 * agg_b['三壘安打'] + 2.06 * agg_b['全壘打']) / agg_b['打席'].replace(0, 1)
            agg_b['wRC+'] = (agg_b['wOBA'] / lg_woba * 100).fillna(0).astype(int)
            
            agg_b['eWAR'] = agg_b.apply(lambda r: ((r['wRC+'] - 70) / 80) * (r['打席'] / 15), axis=1)
            agg_b['eWAR'] = agg_b['eWAR'].apply(lambda x: 0.0 if round(x, 1) == 0 else x)

            qual_b = agg_b[agg_b['打席'] >= dynamic_qualify_pa]
            
            if not agg_b.empty:
                st.markdown(f"#### 👑 聯盟打擊領先者 (規定打席: {dynamic_qualify_pa:.1f})")
                
                def get_b_leader(df, col, is_max=True):
                    if df.empty: return 0, "無(未達標)"
                    sorted_df = df.sort_values(by=[col, '打席'], ascending=[not is_max, True])
                    top = sorted_df.iloc[0]
                    return top[col], f"[{top['球隊']}] {top['球員姓名']}"
                
                val_avg, name_avg = get_b_leader(qual_b, 'AVG', True)
                val_h, name_h = get_b_leader(agg_b, '安打', True) 
                val_hr, name_hr = get_b_leader(agg_b, '全壘打', True)
                val_rbi, name_rbi = get_b_leader(agg_b, '打點', True)
                val_sb, name_sb = get_b_leader(agg_b, '盜壘', True)
                
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
            show_df = agg_b[show_cols_b].copy()
            show_df = show_df.sort_values(by=['球隊', 'wRC+'], ascending=[True, False])

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
        curr_p = df_p[df_p['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix else df_p
        if curr_p.empty: st.info("查無符合條件的投球紀錄。")
        else:
            p_cols = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            agg_p = curr_p.groupby(['球隊', '投手姓名'])[p_cols].sum().reset_index()
            
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

            qual_p = agg_p[agg_p['實際局數'] >= dynamic_qualify_ip]
            
            if not agg_p.empty:
                st.markdown(f"#### 👑 聯盟投球領先者 (規定局數: {dynamic_qualify_ip:.1f})")
                
                def get_p_leader(df, col, is_max=True):
                    if df.empty: return 0, "無(未達標)"
                    if col == 'ERA': sorted_df = df.sort_values(by=[col, '實際局數'], ascending=[True, False])
                    else: sorted_df = df.sort_values(by=[col, '實際局數'], ascending=[not is_max, True])
                    top = sorted_df.iloc[0]
                    return top[col], f"[{top['球隊']}] {top['投手姓名']}"

                val_era, name_era = get_p_leader(qual_p, 'ERA', False)
                val_w, name_w = get_p_leader(agg_p, '勝投', True)
                val_sv, name_sv = get_p_leader(agg_p, '救援成功', True)
                val_hld, name_hld = get_p_leader(agg_p, '中繼成功', True)
                val_so, name_so = get_p_leader(agg_p, '奪三振', True)
                
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
            show_p = agg_p[show_cols_p].copy()
            show_p = show_p.sort_values(by=['球隊', 'FIP'], ascending=[True, True])

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
    else: st.info("目前沒有投球紀錄可以显示！")

# ==========================================
# --- 分頁 4：📋 賽前戰情室 (隨機焦點對決版) ---
# ==========================================
with tab4:
    st.header("📋 賽前戰情室與 AI 深度戰報")
    get_career_stats()

    season_options_wr = ["十年總成績"] + SEASONS
    saved_wr_season = st.session_state.get("wr_season", "十年總成績")
    wr_s_idx = season_options_wr.index(saved_wr_season) if saved_wr_season in season_options_wr else 0
    
    col_ai_s1, col_ai_s2 = st.columns(2)
    def update_wr_season():
        st.session_state.wr_season = st.session_state.wr_season_sel
        if 'save_settings' in globals(): save_settings()
        
    with col_ai_s1: 
        wr_season = st.selectbox("📊 選擇分析賽季", season_options_wr, index=wr_s_idx, key="wr_season_sel", on_change=update_wr_season)
    with col_ai_s2:
        if wr_season != "十年總成績":
            wr_mode = st.selectbox("🎯 戰報模式", ["例行賽/綜合模式", "🏆 世界大賽特別戰報"], key="wr_mode_sel")
        else:
            wr_mode = "例行賽/綜合模式"

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
            agg_p = p_sub.groupby(['球隊', '投手姓名']).sum().reset_index()
            for _, row in agg_p.iterrows():
                ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                era = (row['自責分'] * 9) / max(1, ip_calc) if ip_calc > 0 else float('inf') if row['自責分'] > 0 else 0.0
                fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10 if ip_calc > 0 else float('inf') if (13*row['被全壘打']+3*row['四壞球']-2*row['奪三振'])>0 else 3.10
                tra = (era + fip) / 2.0
                
                ewar = (-0.1 * row['自責分'] - 0.05 * row['四壞球']) if ip_calc == 0 else ((5.00 - tra) / 1.5) * (ip_calc / 10)
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

    is_ws_mode = (wr_mode == "🏆 世界大賽特別戰報")
    if is_ws_mode:
        curr_b_stats, curr_p_stats = get_season_data(wr_season) 
        ws_b_stats, ws_p_stats = get_season_data(wr_season, "世界大賽")
        reg_b_stats, reg_p_stats = get_season_data(wr_season, "例行賽")
    else:
        curr_b_stats, curr_p_stats = get_season_data(wr_season)
        ws_b_stats, ws_p_stats = {}, {}
        reg_b_stats, reg_p_stats = {}, {}
        
    display_b_stats = ws_b_stats if is_ws_mode else curr_b_stats
    display_p_stats = ws_p_stats if is_ws_mode else curr_p_stats

    prev_season_str = "十年總成績"
    if wr_season != "十年總成績":
        curr_s_num = int(wr_season.split(" ")[1])
        if curr_s_num > 1: prev_season_str = f"Season {curr_s_num - 1}"
    prev_b_stats, prev_p_stats = get_season_data(prev_season_str)

    cached_players_b = get_player_list("打擊單場紀錄")
    cached_players_p = get_player_list("投手單場紀錄")

    df_b_full_raw = st.session_state.get('df_b_raw', pd.DataFrame())
    prefix_eval = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
    b_filter_eval = df_b_full_raw[df_b_full_raw['賽事階段'].astype(str).str.contains(prefix_eval, regex=False)] if prefix_eval and not df_b_full_raw.empty else df_b_full_raw
    team_games_eval = b_filter_eval['賽事階段'].nunique() if not b_filter_eval.empty else 1
    dyn_pa_limit = max(1.0, team_games_eval * 1.2)
    dyn_ip_limit = max(0.1, team_games_eval * 0.33)

    def get_unavailable_bullpen(team_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return []
        
        if wr_season == "十年總成績": return []
        s_num = wr_season.split(' ')[1]
        prefix = f"[S{s_num}] 世界大賽"
        
        sub_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)]
        t_df = sub_df[sub_df['球隊'] == team_name]
        
        games = []
        ws_starters = set() 
        
        for stage, group in t_df.groupby('賽事階段', sort=False):
            g_sorted = group.sort_values('時間戳記')
            games.append(g_sorted)
            if not g_sorted.empty:
                ws_starters.add(g_sorted.iloc[0]['投手姓名']) 
        
        unavailable = []
        if not games: return unavailable
        
        last_g = games[-1]
        prev_g = games[-2] if len(games) >= 2 else pd.DataFrame()
        prev_prev_g = games[-3] if len(games) >= 3 else pd.DataFrame()
        
        team_pitchers = cached_players_p.get(team_name, [])
        
        for p in team_pitchers:
            if p in ws_starters: continue 
            
            reason = ""
            p_last = last_g[last_g['投手姓名'] == p] if not last_g.empty else pd.DataFrame()
            p_prev = prev_g[prev_g['投手姓名'] == p] if not prev_g.empty else pd.DataFrame()
            p_prev_prev = prev_prev_g[prev_prev_g['投手姓名'] == p] if not prev_prev_g.empty else pd.DataFrame()
            
            pitched_last = not p_last.empty and pd.to_numeric(p_last['打者數'], errors='coerce').sum() > 0
            pitched_prev = not p_prev.empty and pd.to_numeric(p_prev['打者數'], errors='coerce').sum() > 0
            pitched_prev_prev = not p_prev_prev.empty and pd.to_numeric(p_prev_prev['打者數'], errors='coerce').sum() > 0
            
            np_last = pd.to_numeric(p_last['投球數'], errors='coerce').sum() if pitched_last else 0
            np_prev = pd.to_numeric(p_prev['投球數'], errors='coerce').sum() if pitched_prev else 0
            
            if np_last >= 25:
                reason = f"前場用球數達 {int(np_last)} 球 (需休 2 場)"
            elif np_prev >= 25 and not pitched_last:
                reason = f"前兩場用球數達 {int(np_prev)} 球 (尚需休 1 場)"
            elif np_last >= 15:
                reason = f"前場用球數達 {int(np_last)} 球 (需休 1 場)"
            elif pitched_last and pitched_prev and pitched_prev_prev:
                reason = "已連續三天登板 (需休 1 場)"
                
            if reason:
                unavailable.append(f"❌ {p} ({reason})")
                
        return unavailable

    if is_ws_mode:
        st.markdown("---")
        st.markdown("### 🏥 牛棚疲勞管制與停賽名單 (世界大賽專屬)")
        col_med1, col_med2 = st.columns(2)
        with col_med1:
            laa_unavail = get_unavailable_bullpen("LAA")
            if laa_unavail:
                for msg in laa_unavail: st.error(msg)
            else: st.success("✅ LAA 牛棚全員健康，隨時待命")
        with col_med2:
            lad_unavail = get_unavailable_bullpen("LAD")
            if lad_unavail:
                for msg in lad_unavail: st.error(msg)
            else: st.success("✅ LAD 牛棚全員健康，隨時待命")
            
    st.markdown("---")
    col_ai1, col_ai2 = st.columns(2)
    
    def auto_lineup(team_name):
        available_players = cached_players_b.get(team_name, [])
        team_b_stats = curr_b_stats.get(team_name, {})
        valid_players = [p for p in available_players if p in team_b_stats]
        
        if len(valid_players) < 9:
            st.toast(f"⚠️ {team_name} 擁有數據的球員不足 9 人，無法啟動代排。")
            return
            
        top_9 = sorted(valid_players, key=lambda x: team_b_stats[x]['wRC+'], reverse=True)[:9]
        
        leadoff = max(top_9, key=lambda x: team_b_stats[x]['OBP'])  
        top_9.remove(leadoff)
        cleanup = max(top_9, key=lambda x: team_b_stats[x]['ISO'])  
        top_9.remove(cleanup)
        second = max(top_9, key=lambda x: team_b_stats[x]['wRC+'])  
        top_9.remove(second)
        third = max(top_9, key=lambda x: team_b_stats[x]['AVG'])    
        top_9.remove(third)
        fifth = max(top_9, key=lambda x: team_b_stats[x]['wRC+'])   
        top_9.remove(fifth)
        
        rest = sorted(top_9, key=lambda x: team_b_stats[x]['wRC+'], reverse=True)
        
        optimal_order = [leadoff, second, third, cleanup, fifth] + rest
        st.session_state.lineups[team_name] = optimal_order
        
        for i, p_name in enumerate(optimal_order):
            st.session_state[f"{team_name.lower()}_b{i+1}"] = p_name
            
        if 'save_settings' in globals(): save_settings()
        st.rerun()

    with col_ai1:
        if st.button("🤖 AI 一鍵代排 LAA 最佳火力打線", use_container_width=True): auto_lineup("LAA")
    with col_ai2:
        if st.button("🤖 AI 一鍵代排 LAD 最佳火力打線", use_container_width=True): auto_lineup("LAD")
    st.markdown("---")
    
    col_laa, col_lad = st.columns(2)
    
    with col_laa:
        st.subheader("🔴 LAA 先發陣容")
        laa_batters = []
        available_laa = cached_players_b.get("LAA", []).copy()
        for i in range(1, 10):
            current_options = ["未指定"] + available_laa
            saved_b = st.session_state.lineups["LAA"][i-1]
            b_idx = current_options.index(saved_b) if saved_b in current_options else 0
            
            p = st.selectbox(f"第 {i} 棒", current_options, index=b_idx, key=f"laa_b{i}")
            st.session_state.lineups["LAA"][i-1] = p if p != "未指定" else ""
            
            if p != "未指定":
                laa_batters.append(p)
                available_laa.remove(p)
                stats = display_b_stats.get("LAA", {}).get(p, {'wRC+': 0, 'eWAR': 0, 'AVG': 0})
                prefix_str = "WS " if is_ws_mode else ""
                st.caption(f"📊 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}wRC+: **{stats['wRC+']:.0f}** | {prefix_str}AVG: {stats['AVG']:.3f}")
            
        laa_sp_options = ["未指定"] + cached_players_p.get("LAA", [])
        saved_sp_laa = st.session_state.pitchers["LAA"]
        laa_sp_idx = laa_sp_options.index(saved_sp_laa) if saved_sp_laa in laa_sp_options else 0
        laa_sp = st.selectbox("先發投手 (SP)", laa_sp_options, index=laa_sp_idx, key="laa_sp")
        st.session_state.pitchers["LAA"] = laa_sp if laa_sp != "未指定" else ""
        if laa_sp != "未指定":
            stats = display_p_stats.get("LAA", {}).get(laa_sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
            prefix_str = "WS " if is_ws_mode else ""
            era_str = '∞' if stats['ERA'] == float('inf') else f"{stats['ERA']:.2f}"
            st.caption(f"🥎 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}ERA: **{era_str}** | {prefix_str}K: {stats['K']}")
        
    with col_lad:
        st.subheader("🔵 LAD 先發陣容")
        lad_batters = []
        available_lad = cached_players_b.get("LAD", []).copy()
        for i in range(1, 10):
            current_options = ["未指定"] + available_lad
            saved_b = st.session_state.lineups["LAD"][i-1]
            b_idx = current_options.index(saved_b) if saved_b in current_options else 0
            
            p = st.selectbox(f"第 {i} 棒", current_options, index=b_idx, key=f"lad_b{i}")
            st.session_state.lineups["LAD"][i-1] = p if p != "未指定" else ""
            
            if p != "未指定":
                lad_batters.append(p)
                available_lad.remove(p)
                stats = display_b_stats.get("LAD", {}).get(p, {'wRC+': 0, 'eWAR': 0, 'AVG': 0})
                prefix_str = "WS " if is_ws_mode else ""
                st.caption(f"📊 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}wRC+: **{stats['wRC+']:.0f}** | {prefix_str}AVG: {stats['AVG']:.3f}")
            
        lad_sp_options = ["未指定"] + cached_players_p.get("LAD", [])
        saved_sp_lad = st.session_state.pitchers["LAD"]
        lad_sp_idx = lad_sp_options.index(saved_sp_lad) if saved_sp_lad in lad_sp_options else 0
        lad_sp = st.selectbox("先發投手 (SP)", lad_sp_options, index=lad_sp_idx, key="lad_sp")
        st.session_state.pitchers["LAD"] = lad_sp if lad_sp != "未指定" else ""
        if lad_sp != "未指定":
            stats = display_p_stats.get("LAD", {}).get(lad_sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
            prefix_str = "WS " if is_ws_mode else ""
            era_str = '∞' if stats['ERA'] == float('inf') else f"{stats['ERA']:.2f}"
            st.caption(f"🥎 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}ERA: **{era_str}** | {prefix_str}K: {stats['K']}")

    st.markdown("---")
    
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
        
        if streak_type == 'W': return streak_count * 1.5
        elif streak_type == 'L': return streak_count * -1.5
        else: return 0

    def get_starter_ratio(team_name, p_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return 1.0 
        
        t_df = df_p_full[df_p_full['球隊'] == team_name]
        if t_df.empty: return 1.0
        
        total_apps = 0
        starts = 0
        for stage, group in t_df.groupby('賽事階段', sort=False):
            g_sorted = group.sort_values('時間戳記', ascending=True)
            if not g_sorted.empty:
                if p_name in g_sorted['投手姓名'].values:
                    total_apps += 1
                    if g_sorted.iloc[0]['投手姓名'] == p_name:
                        starts += 1
                        
        if total_apps == 0: return 1.0
        return starts / total_apps

    def calc_moneyline(prob):
        if prob > 50:
            return f"-{int(round((prob / (100.0 - prob)) * 100))}"
        elif prob < 50:
            return f"+{int(round(((100.0 - prob) / max(0.1, prob)) * 100))}"
        else:
            return "PK"

    def calc_win_prob():
        def get_b_ewar(team, p):
            base = curr_b_stats.get(team, {}).get(p, {'eWAR':0})['eWAR']
            if is_ws_mode and p in ws_b_stats.get(team, {}):
                ws_ewar = ws_b_stats[team][p]['eWAR'] * 6.0 
                return ws_ewar if ws_b_stats[team][p].get('PA', 0) > 0 else base
            return base

        def get_p_ewar(team, sp):
            if sp == "未指定": return 0
            base = curr_p_stats.get(team, {}).get(sp, {'eWAR':0})['eWAR']
            if is_ws_mode and sp in ws_p_stats.get(team, {}):
                ws_ewar = ws_p_stats[team][sp]['eWAR'] * 6.0 
                val = ws_ewar if ws_p_stats[team][sp].get('IP', 0) > 0 else base
            else:
                val = base
            return val * 5.0 
        
        laa_b_ewar = sum([get_b_ewar('LAA', p) for p in laa_batters])
        lad_b_ewar = sum([get_b_ewar('LAD', p) for p in lad_batters])
        
        laa_sp_ewar = get_p_ewar('LAA', laa_sp)
        lad_sp_ewar = get_p_ewar('LAD', lad_sp)
        
        laa_momentum = get_streak_bonus('LAA', is_ws_mode) / 3.0 
        lad_momentum = get_streak_bonus('LAD', is_ws_mode) / 3.0
        
        is_laa_op = laa_sp != "未指定" and get_starter_ratio('LAA', laa_sp) <= 0.30
        is_lad_op = lad_sp != "未指定" and get_starter_ratio('LAD', lad_sp) <= 0.30
        
        laa_penalty = -3.0 if is_laa_op else 0
        lad_penalty = -3.0 if is_lad_op else 0
        
        laa_power = laa_b_ewar + laa_sp_ewar + laa_momentum + laa_penalty
        lad_power = lad_b_ewar + lad_sp_ewar + lad_momentum + lad_penalty
        
        delta = laa_power - lad_power
        k = 0.12 
        
        laa_prob_raw = 1 / (1 + math.exp(-k * delta))
        laa_prob = round(laa_prob_raw * 100, 1)
        laa_prob = max(15.0, min(85.0, laa_prob)) 
        
        return round(laa_prob, 1), round(100.0 - laa_prob, 1), is_laa_op, is_lad_op

    prob_laa, prob_lad, is_laa_opener, is_lad_opener = calc_win_prob()
    ml_laa = calc_moneyline(prob_laa)
    ml_lad = calc_moneyline(prob_lad)
    
    st.markdown(
        f"<div style='display: flex; height: 35px; border-radius: 8px; overflow: hidden; font-weight: bold; color: white; text-align: center; line-height: 35px; font-size: 16px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);'><div style='width: {prob_laa}%; background-color: #BA0021; transition: width 0.5s;'>LAA {prob_laa}% ({ml_laa})</div><div style='width: {prob_lad}%; background-color: #005A9C; transition: width 0.5s;'>LAD {prob_lad}% ({ml_lad})</div></div>", 
        unsafe_allow_html=True
    )
    
    msg = "💡 **AI 魔球演算模型**：納入打線、先發(權重5倍)、與球隊連勝動能。"
    if is_ws_mode: msg += " 🏆 **[世界大賽模式] 已強制套用季後賽手感加權！**"
    if is_laa_opener or is_lad_opener: msg += " ⚠️ **偵測到牛棚假先發 (生涯先發比例過低)，勝率已大幅調降。**"
    st.caption(msg)

    st.markdown("---")
    
    if st.button("🎙️ 產生賽前深度戰報 (含數據排名與推演)", type="primary", use_container_width=True):
        if 'save_settings' in globals(): save_settings()
        
        with st.spinner("AI 球評正在運算高階 Sabermetrics 數據與排名..."):
            time.sleep(1.5)
            df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
            
            # --- ✨ Apple TV+ Log5 對決引擎 (貝氏平滑 + 隨機展示版) ---
            def log5(a, b, l):
                if l <= 0 or l >= 1: return 0
                if a == 0 and b == 0: return 0
                num = (a * b) / l
                den = num + ((1 - a) * (1 - b) / (1 - l))
                if den == 0: return 0
                return num / den

            def render_log5_card(b_name, b_team, p_name, p_team, t_color):
                b_s = curr_b_stats.get(b_team, {}).get(b_name)
                p_s = curr_p_stats.get(p_team, {}).get(p_name)
                
                if not b_s or not p_s or b_s.get('PA', 0) == 0 or p_s.get('BF', 0) == 0:
                    return f"<div style='padding:20px; background:#111; border-radius:10px; color:#666; text-align:center;'>樣本不足，無法預測 {b_name} vs {p_name}</div>"
                
                lg_pa = sum([v.get('PA',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_ab = sum([v.get('AB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                if lg_pa == 0 or lg_ab == 0: return ""
                
                lg_h = sum([v.get('H',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_bb = sum([v.get('BB',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_hr = sum([v.get('HR',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_k = sum([v.get('K',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                lg_xbh = sum([v.get('XBH',0) for t, plrs in curr_b_stats.items() for p, v in plrs.items()])
                
                l_ba = lg_h / max(1, lg_ab)
                l_obp = (lg_h + lg_bb) / max(1, lg_pa)
                l_hr = lg_hr / max(1, lg_pa)
                l_k = lg_k / max(1, lg_pa)
                l_xbh = lg_xbh / max(1, lg_pa)

                # ✨ Bayesian Smoothing (加權回歸均值，給予 10 個打席的聯盟平均緩衝)
                W = 10.0 
                b_ba = (b_s['H'] + l_ba * W) / (max(1, b_s['AB']) + W)
                b_obp = (b_s['H'] + b_s['BB'] + l_obp * W) / (b_s['PA'] + W)
                b_hr = (b_s['HR'] + l_hr * W) / (b_s['PA'] + W)
                b_k = (b_s['K'] + l_k * W) / (b_s['PA'] + W)
                b_xbh = (b_s['XBH'] + l_xbh * W) / (b_s['PA'] + W)

                p_bf = p_s['BF']
                p_ab = max(1, p_bf - p_s['BB']) 
                p_ba = (p_s['H'] + l_ba * W) / (p_ab + W)
                p_obp = (p_s['H'] + p_s['BB'] + l_obp * W) / (p_bf + W)
                p_hr = (p_s['HR'] + l_hr * W) / (p_bf + W)
                p_k = (p_s['K'] + l_k * W) / (p_bf + W)
                
                p_non_hr_h = max(0, p_s['H'] - p_s['HR'])
                lg_non_hr_h = max(1, lg_h - lg_hr)
                lg_non_hr_xbh = max(0, lg_xbh - lg_hr)
                p_xbh_est = p_s['HR'] + p_non_hr_h * (lg_non_hr_xbh / lg_non_hr_h)
                p_xbh = (p_xbh_est + l_xbh * W) / (p_bf + W)

                xBA = max(0.01, min(0.99, log5(b_ba, p_ba, l_ba)))
                xOBP = max(0.01, min(0.99, log5(b_obp, p_obp, l_obp)))
                xHR = max(0.001, min(0.99, log5(b_hr, p_hr, l_hr)))
                xXBH = max(0.001, min(0.99, log5(b_xbh, p_xbh, l_xbh)))
                xK = max(0.01, min(0.99, log5(b_k, p_k, l_k)))

                def make_bar(label, prob, color, warning_threshold=None):
                    prob_pct = prob * 100
                    warn_tag = " <span style='color:#ff4b4b; font-size:10px; font-weight:bold;'>(🚨 警戒)</span>" if warning_threshold and prob_pct >= warning_threshold else ""
                    return f"<div style='margin-bottom: 8px;'><div style='display:flex; justify-content:space-between; font-size: 13px; color: #ddd; margin-bottom: 2px;'><span>{label}</span><span>{prob_pct:.1f}%{warn_tag}</span></div><div style='width:100%; background:#333; height:8px; border-radius:4px; overflow:hidden;'><div style='width:{prob_pct}%; background:{color}; height:100%; border-radius:4px;'></div></div></div>"
                
                # ✨ 隨機挑選 2 項數據顯示
                stats_pool = [
                    make_bar('安打機率 (xBA)', xBA, '#00e5ff'),
                    make_bar('上壘機率 (xOBP)', xOBP, '#007bff'),
                    make_bar('長打機率 (xXBH%)', xXBH, '#ff9f00'),
                    make_bar('開轟機率 (xHR%)', xHR, '#ff4b4b', warning_threshold=8.0),
                    make_bar('三振機率 (xK%)', xK, '#b052d9')
                ]
                chosen_stats = "".join(random.sample(stats_pool, 2))
                
                html = f"<div style='background: linear-gradient(145deg, #161616 0%, #222 100%); padding: 20px; border-radius: 12px; border-left: 5px solid {t_color}; box-shadow: 0 4px 15px rgba(0,0,0,0.5);'><h4 style='color:#aaa; margin:0 0 15px 0; font-size:12px; text-transform:uppercase; letter-spacing:1px;'>📺 Spotlight Matchup</h4><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;'><div style='text-align:left; width: 40%;'><div style='font-size:10px; color:#888;'>BATTER [{b_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{b_name}</div></div><div style='font-size:16px; color:#555; font-weight:900; font-style:italic;'>VS</div><div style='text-align:right; width: 40%;'><div style='font-size:10px; color:#888;'>PITCHER [{p_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{p_name}</div></div></div>{chosen_stats}<div style='font-size:10px; color:#666; margin-top:15px; text-align:right;'>*Log5 Smoothed Projection</div></div>"
                return html
            # ----------------------------------------
            
            # --- ✨ 隨機挑選達標打者進行焦點對決 ---
            def get_random_spotlight_batter(team_batters, team_name):
                valid_b = [b for b in team_batters if b in curr_b_stats.get(team_name, {}) and curr_b_stats[team_name][b]['PA'] >= max(3.0, dyn_pa_limit)]
                if not valid_b: 
                    valid_b = [b for b in team_batters if b in curr_b_stats.get(team_name, {})]
                return random.choice(valid_b) if valid_b else None

            laa_spotlight_b = get_random_spotlight_batter(laa_batters, 'LAA')
            lad_spotlight_b = get_random_spotlight_batter(lad_batters, 'LAD')
            
            c_card1, c_card2 = st.columns(2)
            has_matchup = False
            with c_card1:
                if lad_spotlight_b and laa_sp != "未指定" and laa_sp in curr_p_stats.get('LAA', {}):
                    card_html = render_log5_card(lad_spotlight_b, 'LAD', laa_sp, 'LAA', '#005A9C')
                    if card_html:
                        st.markdown(card_html, unsafe_allow_html=True)
                        has_matchup = True
            with c_card2:
                if laa_spotlight_b and lad_sp != "未指定" and lad_sp in curr_p_stats.get('LAD', {}):
                    card_html = render_log5_card(laa_spotlight_b, 'LAA', lad_sp, 'LAD', '#BA0021')
                    if card_html:
                        st.markdown(card_html, unsafe_allow_html=True)
                        has_matchup = True
            
            if has_matchup:
                st.markdown("<br>", unsafe_allow_html=True)

            def get_team_streak_str(team_name, ws_only=False):
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
                
                if streak_type == 'W': return f"**{streak_count} 連勝** 🔥"
                elif streak_type == 'L': return f"**{streak_count} 連敗** 🧊"
                else: return f"**{streak_count} 連和** 🤝"

            def get_bullpen_era(team_name, ws_only=False):
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
                
                bp_ip = bp_outs / 3.0
                return (bp_er * 9) / bp_ip if bp_ip > 0 else 0.0

            st.markdown(f"## 📰 【{wr_season}】 賽前魔球戰報")
            
            st.markdown("### 🏟️ 球隊近況與牛棚防線")
            def generate_team_momentum(team):
                streak = get_team_streak_str(team, is_ws_mode)
                bp_era = get_bullpen_era(team, is_ws_mode)
                text = f"**【{team} 戰力概況】**\n- **近期氣勢**：目前處於 {streak}。\n"
                if bp_era is not None:
                    text += f"- **後援安定度**：牛棚 ERA 為 **{bp_era:.2f}**。"
                    if bp_era > 5.50: text += " 🚨 **(放火警報)** 領先 3 分都不安全！\n\n"
                    elif bp_era < 2.50: text += " 🔒 **(鐵壁防線)** 領先進入後半段幾乎等於比賽結束。\n\n"
                    else: text += " 調度時機將是關鍵。\n\n"
                else: text += "- **牛棚安定度**：尚無數據。\n\n"
                return text
            st.info(generate_team_momentum("LAA") + generate_team_momentum("LAD"))

            st.markdown("### 🥎 投手丘上的進階剖析")
            def get_pitcher_insights(team, sp, stats_dict, prev_dict, reg_dict, ws_dict, is_ws_mode):
                if sp not in stats_dict.get(team, {}): return ""
                s = stats_dict[team][sp]
                era, fip = s['ERA'], s['FIP']
                
                all_ip = sum([val['IP'] for t, plrs in stats_dict.items() for p, val in plrs.items()])
                all_era_sum = sum([val['ERA'] * val['IP'] for t, plrs in stats_dict.items() for p, val in plrs.items() if val['ERA'] != float('inf')])
                lg_era = all_era_sum / all_ip if all_ip > 0 else 4.00
                all_np = sum([val.get('NP', 0) for t, plrs in stats_dict.items() for p, val in plrs.items()])
                lg_pip = all_np / all_ip if all_ip > 0 else 15.0
                
                qualified_pitchers_eras = [val['ERA'] for t, plrs in stats_dict.items() for p, val in plrs.items() if val['IP'] >= dyn_ip_limit]
                all_eras = sorted(list(set(qualified_pitchers_eras)))
                if s['IP'] >= dyn_ip_limit:
                    rank_str = f"聯盟第 {all_eras.index(era) + 1}" if era in all_eras else "-"
                else:
                    rank_str = "未達局數門檻"
                
                p_era = prev_dict.get(team, {}).get(sp, {}).get('ERA', era)
                era_str = "∞" if era == float('inf') else f"{era:.2f}"
                p_era_str = "∞" if p_era == float('inf') else f"{p_era:.2f}"
                fip_str = "∞" if fip == float('inf') else f"{fip:.2f}"
                trend = f"(去年 ERA {p_era_str})" if p_era != era else ""
                
                insight = f"**【{team} 先發】 {sp}**\n- **數據**：ERA **{era_str} ({rank_str})** {trend} | eWAR **{s['eWAR']:.1f}**\n"
                insight += f"- **壓制與效率**：WHIP **{s['WHIP']:.2f}** | K/9 **{s['K/9']:.2f}** | 每局用球數 (P/IP) **{s['P/IP']:.1f}** 球\n"
                
                if s['P/IP'] >= lg_pip + 4.0 and era < lg_era:
                    insight += f"- ⚠️ **體力消耗警報**：雖然防禦率不錯，但每局用球數高達 {s['P/IP']:.1f} 球 (聯盟平均 {lg_pip:.1f})，這代表他容易陷入纏鬥，今晚可能投不長。\n\n"
                elif s['P/IP'] > 0 and s['P/IP'] <= lg_pip - 3.0 and era < lg_era:
                    insight += f"- ⚡ **極致省球大師**：每局平均只需 {s['P/IP']:.1f} 球 (遠低於平均 {lg_pip:.1f})！他極具侵略性的投球策略能有效拉長投球局數。\n\n"

                if is_ws_mode and sp in ws_dict.get(team, {}) and ws_dict[team][sp]['IP'] > 1.0:
                    ws_era = ws_dict[team][sp]['ERA']
                    reg_era = reg_dict.get(team, {}).get(sp, {}).get('ERA', 0)
                    ws_era_str = "∞" if ws_era == float('inf') else f"{ws_era:.2f}"
                    reg_era_str = "∞" if reg_era == float('inf') else f"{reg_era:.2f}"
                    
                    if ws_era < 2.5 and reg_era > 4.0:
                        insight += f"- 🌟 **季後賽賽揚 ({sp})**：例行賽防禦率高達 {reg_era_str}，一進世界大賽直接鬼神化 ({ws_era_str})，完全為大場面而生！\n\n"
                    elif ws_era > 5.5 and reg_era < 3.5:
                        insight += f"- 🥶 **大賽軟手症 ({sp})**：例行賽神級表現 (ERA {reg_era_str})，到了世界大賽卻壓力過大完全失常 (ERA {ws_era_str})！\n\n"
                    elif ws_era <= 3.0 and reg_era <= 3.0:
                        insight += f"- 👑 **大場面王牌 ({sp})**：無論例行賽還是世界大賽 (WS ERA {ws_era_str})，他的壓制力始終如一。\n\n"
                    return insight 
                
                fip_diff = fip - era
                if era >= 6.0 and fip >= 6.0: insight += f"- 🚨 **發球機警報 (狀況慘烈)**：無論是防禦率 ({era_str}) 還是 FIP ({fip_str}) 都突破天際的高。他目前在丘上幾乎沒有解決打者的能力，今晚隨時會被打退場。\n\n"
                elif era <= 2.5 and fip <= 2.5: insight += f"- 👑 **鬼神級王牌 (真材實料)**：防禦率 {era_str} 已經很可怕，沒想到進階數據 FIP 更是只有 {fip_str}！這代表他連隊友失誤都自己三振解決，今晚對手只能自求多福。\n\n"
                elif fip_diff < -0.5:
                    if era > 3.5: insight += random.choice([f"- 💡 **悲情王牌 (被守備雷到)**：帳面 ERA 看似平凡，但 FIP 僅 {fip_str}！這說明他投得極好，失分多半是非戰之罪。\n\n", f"- 📉 **進階數據平反**：別被他 {era_str} 的防禦率騙了，他的 FIP 只有 {fip_str}，代表他的投球內容相當優異。\n\n"])
                    else: insight += f"- 🛡️ **深不見底的壓制力**：防禦率 {era_str} 已經夠水準了，沒想到 FIP ({fip_str}) 還能更低！這代表他把命運完全掌握在自己手中。\n\n"
                elif fip_diff > 0.5:
                    if era < 3.5: insight += random.choice([f"- 🚨 **強運校正警報**：防禦率 {era_str} 看似無懈可擊，但 FIP 卻高達 {fip_str}。這代表他很大程度是靠著完美的守備與運氣在撐，隨時有核爆風險。\n\n", f"- ⚠️ **虛假繁榮 (海市蜃樓)**：雖然 ERA 只有 {era_str}，但進階數據 FIP 殘酷地指出他的真實壓制力並不理想。\n\n"])
                    else: insight += f"- 💣 **雪上加霜**：防禦率已經不理想，FIP ({fip_str}) 更是慘烈。這意味著他過度依賴守備，今晚狀況十分堪憂。\n\n"
                else:
                    insight += random.choice([f"- ⚖️ **真金不怕火煉**：他的 FIP ({fip_str}) 與 ERA 極為吻合，表現十分穩定，帳面成績就是真實硬實力。\n\n", f"- 🎯 **童叟無欺**：防禦率與 FIP 高度一致，代表他完全掌握了自己的投球節奏。\n\n"])
                return insight
                
            p_rep = ""
            if laa_sp != "未指定": p_rep += get_pitcher_insights("LAA", laa_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            if lad_sp != "未指定": p_rep += get_pitcher_insights("LAD", lad_sp, curr_p_stats, prev_p_stats, reg_p_stats, ws_p_stats, is_ws_mode)
            if p_rep: st.success(p_rep)

            st.markdown("### 💥 打線雷達掃描與教練點評")
            # --- ✨ 退回 V44 全打線掃描與動態基準點評版 ---
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
                    ws_heroes = []
                    for b in batters:
                        if b in used_players: continue
                        ws_ops = ws_dict.get(team, {}).get(b, {}).get('wRC+', 0)
                        ws_pa = ws_dict.get(team, {}).get(b, {}).get('PA', 0)
                        reg_ops = reg_dict.get(team, {}).get(b, {}).get('wRC+', 0)
                        
                        if ws_pa >= 3:
                            if ws_ops >= 140 and reg_ops <= 100:
                                insights.append(f"- 🌟 **十月先生 ({b})**：例行賽裝死 (wRC+ {reg_ops:.0f})，季後賽突然甦醒的大賽型球員 (WS wRC+ {ws_ops:.0f})！")
                                used_players.add(b)
                            elif ws_ops <= 60 and reg_ops >= 120:
                                insights.append(f"- 🥶 **大賽軟手症 ({b})**：例行賽猛如虎 (wRC+ {reg_ops:.0f})，世界大賽軟如蟲 (WS wRC+ {ws_ops:.0f})，急需找回手感。")
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
                    babip_val = team_stats[lucky_b]['BABIP']
                    unlucky_val = team_stats[unlucky_b]['BABIP']
                    
                    if babip_val >= lg_babip + 0.200:
                        insights.append(f"- 🎰 **魔法安打 ({lucky_b})**：BABIP 高達 {babip_val:.3f} (聯盟均值 {lg_babip:.3f})！連隨便碰都會變安打，極度強運，簡直有棒球之神眷顧！")
                        used_players.add(lucky_b)
                    elif babip_val >= lg_babip + 0.100:
                        insights.append(f"- 🍀 **天選之人 ({lucky_b})**：BABIP {babip_val:.3f}，這傢伙最近打出去的球就像長了眼睛一樣，運氣也是實力的一部份！")
                        used_players.add(lucky_b)
                        
                    if unlucky_b not in used_players:
                        if unlucky_val <= lg_babip - 0.150:
                            insights.append(f"- 🐈‍⬛ **地獄倒楣鬼 ({unlucky_b})**：BABIP 慘到只有 {unlucky_val:.3f} (聯盟均值 {lg_babip:.3f})，打得再強勁也會找手套，建議賽前去拜拜過個火。")
                            used_players.add(unlucky_b)
                        elif unlucky_val <= lg_babip - 0.080:
                            insights.append(f"- 🌧️ **時運不濟 ({unlucky_b})**：BABIP 僅 {unlucky_val:.3f}，最近擊球運氣非常差，常常把球打得強勁卻出局。")
                            used_players.add(unlucky_b)

                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= 3]
                if rem_batters:
                    blind_b = max(rem_batters, key=lambda x: team_stats[x]['K%'])
                    k_val = team_stats[blind_b]['K%']
                    if k_val >= lg_k_pct + 20.0:
                        insights.append(f"- 🌪️ **人體電風扇 ({blind_b})**：K% 高達 {k_val:.1f}% (遠超聯盟均值 {lg_k_pct:.1f}%)！選球徹底迷失，變化球隨便騙隨便揮。")
                        used_players.add(blind_b)
                    elif k_val >= lg_k_pct + 10.0:
                        insights.append(f"- 🤔 **揮空隱憂 ({blind_b})**：K% {k_val:.1f}% 偏高，容易被引誘球騙到出局。")
                        used_players.add(blind_b)
                
                rem_batters = [b for b in valid_b if b not in used_players and team_stats[b]['PA'] >= 3]
                if rem_batters:
                    eye_b = max(rem_batters, key=lambda x: team_stats[x]['BB%'])
                    bb_val = team_stats[eye_b]['BB%']
                    if bb_val >= lg_bb_pct + 10.0:
                        insights.append(f"- 👁️ **神之眼 ({eye_b})**：BB% 達 {bb_val:.1f}% (聯盟均值 {lg_bb_pct:.1f}%)！選球精準到讓投手懷疑人生，根本找不到好球帶。")
                        used_players.add(eye_b)
                    elif bb_val >= lg_bb_pct + 5.0:
                        insights.append(f"- 🦅 **選球大師 ({eye_b})**：BB% 達 {bb_val:.1f}%，上壘慾望極強，能大幅消耗敵方投手球數。")
                        used_players.add(eye_b)

                rem_batters = [b for b in valid_b if b not in used_players]
                if rem_batters:
                    iso_b = max(rem_batters, key=lambda x: team_stats[x]['ISO'])
                    iso_val = team_stats[iso_b]['ISO']
                    if iso_val >= lg_iso + 0.400:
                        insights.append(f"- ☄️ **外星級神力 ({iso_b})**：純長打率 ISO {iso_val:.3f} (聯盟均值 {lg_iso:.3f})！這不是重砲，這是把棒球當高爾夫球打的外星怪物！")
                        used_players.add(iso_b)
                    elif iso_val >= lg_iso + 0.200:
                        insights.append(f"- 🌋 **怪力重砲 ({iso_b})**：純長打率 ISO {iso_val:.3f}！他上來不是要短程安打的，隨時能把球轟出球場。")
                        used_players.add(iso_b)
                    elif iso_val >= lg_iso + 0.100:
                        insights.append(f"- 💪 **優質長打 ({iso_b})**：純長打率 ISO {iso_val:.3f}，具備不容忽視的長打威脅。")
                        used_players.add(iso_b)
                
                for i, b in enumerate(batters):
                    if b not in team_stats or b in used_players: continue
                    ops, order = team_stats[b]['wRC+'], i + 1
                    if order <= 3 and ops <= 60 and team_stats[b]['PA'] >= 5:
                        insights.append(f"- 🥶 **嚴重冰冷 ({b})**：wRC+ 慘到只有 {ops:.0f} 卻卡在第 {order} 棒，這簡直是進攻斷點，自動出局機。")
                        used_players.add(b)
                    elif order <= 3 and ops < 90:
                        insights.append(f"- 🤨 **總教練的謎之信任 ({b})**：wRC+ 不及格 ({ops:.0f}) 卻還能打前段棒次，球迷都在看教練何時會換人。")
                        used_players.add(b)
                    elif order >= 7 and ops >= 150:
                        insights.append(f"- 🥷 **核彈級伏兵 ({b})**：wRC+ {ops:.0f} 的怪物竟然埋伏在第 {order} 棒，這打線深不見底，對手下半段依然不能放鬆！")
                        used_players.add(b)

                if len(insights) == 1:
                    insights.append("- ℹ️ 目前樣本數較少，戰術雷達尚未偵測到極端表現。")

                return "\n".join(insights) + "\n\n"
                
            b_rep = ""
            if laa_batters: b_rep += get_lineup_insights("LAA", laa_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)
            if lad_batters: b_rep += get_lineup_insights("LAD", lad_batters, display_b_stats, reg_b_stats, ws_b_stats, is_ws_mode)
            if b_rep: st.warning(b_rep)

            st.markdown("### 🧠 數據總結推演")
            tactics = []
            
            bp_laa = get_bullpen_era("LAA", is_ws_mode) or 0.0
            bp_lad = get_bullpen_era("LAD", is_ws_mode) or 0.0
            
            if is_ws_mode:
                tactics.append("🏆 **【十月瘋狂】** 這是世界大賽！例行賽的戰績已經清零，現在比拚的是誰的大心臟能頂住壓力！")
                
                laa_ws_op = sum([ws_b_stats.get('LAA', {}).get(p, {'wRC+':0})['wRC+'] for p in laa_batters])
                lad_ws_op = sum([ws_b_stats.get('LAD', {}).get(p, {'wRC+':0})['wRC+'] for p in lad_batters])
                laa_reg_op = sum([reg_b_stats.get('LAA', {}).get(p, {'wRC+':0})['wRC+'] for p in laa_batters])
                lad_reg_op = sum([reg_b_stats.get('LAD', {}).get(p, {'wRC+':0})['wRC+'] for p in lad_batters])
                
                if laa_ws_op > lad_ws_op and laa_reg_op < lad_reg_op:
                    tactics.append("🔥 **【季後賽大覺醒】** LAA 雖然例行賽跌跌撞撞，但進入世界大賽後打線全面甦醒，目前的季後賽火力完全壓過 LAD，絕對是極大的威脅！")
                elif lad_ws_op > laa_ws_op and lad_reg_op < laa_reg_op:
                    tactics.append("🔥 **【季後賽大覺醒】** LAD 雖然例行賽打線不如對手耀眼，但來到十月戰場卻展現出無比的韌性與爆發力，LAA 稍有不慎就會翻船！")
            
            if prob_laa > 65:
                if bp_lad > 4.5: tactics.append("數據顯示 LAA 擁有壓倒性優勢，且對手牛棚防線脆弱，LAA 有望在比賽後半段進一步擴大領先。")
                elif bp_laa > 4.5: tactics.append("LAA 雖然先發與打線佔優，但自家牛棚是一大隱憂。對手若能將戰局逼入後半段，隨時有逆轉可能。")
                else: tactics.append("數據顯示 LAA 擁有極大優勢，投打戰力完整，對手今晚將面臨極大考驗。")
            elif prob_lad > 65:
                if bp_laa > 4.5: tactics.append("LAD 在戰力天秤上占據制高點，且對手牛棚防線脆弱，LAD 有望在比賽後半段定調戰局。")
                elif bp_lad > 4.5: tactics.append("LAD 雖然先發與打線佔優，但自家牛棚是一大隱憂。對手若能將戰局逼入後半段，隨時有逆轉可能。")
                else: tactics.append("數據顯示 LAD 擁有極大優勢，投打戰力完整，對手今晚將面臨極大考驗。")
                
            if bp_laa > 5.5 and bp_lad > 5.5:
                tactics.append("今晚兩隊牛棚都有『放火』基因，這場比賽在第七局之後才是真正的開始，心臟不好的觀眾請準備好藥品。")
                
            if laa_sp != "未指定" and lad_sp != "未指定":
                sp1 = ws_p_stats if is_ws_mode else curr_p_stats
                if sp1.get('LAA', {}).get(laa_sp,{'ERA':5.0})['ERA'] < 3.0 and sp1.get('LAD', {}).get(lad_sp,{'ERA':5.0})['ERA'] < 3.0:
                    tactics.append("罕見的王牌大賽！得分可能像擠牙膏一樣困難，一分定勝負的機率極高。")
                    
            if not tactics: tactics.append("雙方戰力極其接近，預期勝率幾乎是五五開，守備的細節將決定最後的贏家。")
            tactics.append(f"目前的預測氣氛：{'熱血沸騰' if abs(prob_laa-50) < 10 else '一面倒的屠殺？'}。")
            
            st.error(f"🎙️ **AI 魔球推演：** {random.choice(tactics)}")# --- 分頁 5：🎖️ 聯盟大獎預測 ---
# ==========================================
with tab5:
    st.header("🎖️ 全美棒球記者協會 (BBWAA) 年度大獎開票所")
    st.write("⚠️ **動態門檻系統**：系統會自動根據目前「球隊已賽場次」來換算規定的打席與局數 (3局制專用)。")
    st.write("⚠️ **世界大賽(FMVP)門檻**：打者滿 **3 打席**，投手滿 **1.0 局** 即可角逐。(👑 限定冠軍隊伍球員)")
    
    col_s1, col_s2 = st.columns([1, 3])
    with col_s1: target_season = st.selectbox("選擇結算賽季", SEASONS, key="award_season")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        btn_reg = st.button(f"🏆 結算 {target_season} 例行賽大獎", type="primary", use_container_width=True)
    with col_btn2:
        btn_ws = st.button(f"💍 結算 {target_season} 世界大賽 FMVP", type="primary", use_container_width=True)
    
    if btn_reg or btn_ws:
        get_career_stats() 
        df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
        df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())
        
        if df_b_raw.empty and df_p_raw.empty:
            st.warning("⚠️ 查無數據！請確認該賽季有輸入紀錄。")
        else:
            s_num_str = target_season.split(" ")[1]
            s_num_int = int(s_num_str)
            prefix = f"[S{s_num_str}]"
            
            def extract_stats(stage_keyword, search_prefix, is_ws=False):
                df_b_sub = df_b_raw[(df_b_raw['賽事階段'].astype(str).str.contains(search_prefix, regex=False)) & (df_b_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))] if not df_b_raw.empty else pd.DataFrame()
                df_p_sub = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(search_prefix, regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))] if not df_p_raw.empty else pd.DataFrame()
                
                team_games = df_b_sub['賽事階段'].nunique() if not df_b_sub.empty else 1
                if is_ws:
                    min_pa, min_ip = 3.0, 1.0
                else:
                    min_pa = max(1.0, team_games * 1.2)
                    min_ip = max(0.1, team_games * 0.33)
                
                cand_b, cand_p = {}, {}
                
                if not df_b_sub.empty:
                    total_pa = df_b_sub['打席'].sum()
                    lg_1b = df_b_sub['安打'].sum() - df_b_sub['二壘安打'].sum() - df_b_sub['三壘安打'].sum() - df_b_sub['全壘打'].sum()
                    lg_woba_num = 0.69 * df_b_sub['四壞球'].sum() + 0.88 * lg_1b + 1.25 * df_b_sub['二壘安打'].sum() + 1.59 * df_b_sub['三壘安打'].sum() + 2.06 * df_b_sub['全壘打'].sum()
                    lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.001
                    
                    df_b_agg = df_b_sub.groupby(['球隊', '球員姓名']).sum().reset_index()
                    for _, row in df_b_agg.iterrows():
                        if row['打席'] < min_pa: continue 
                        avg = row['安打'] / max(1, row['打數'])
                        
                        b_1b = row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']
                        woba = (0.69 * row['四壞球'] + 0.88 * b_1b + 1.25 * row['二壘安打'] + 1.59 * row['三壘安打'] + 2.06 * row['全壘打']) / max(1, row['打席'])
                        wrc_plus = 100 * (woba / lg_woba) if lg_woba > 0 else 0
                        
                        ewar = ((wrc_plus - 70) / 80) * (row['打席'] / 15)
                        ewar = 0.0 if round(ewar, 1) == 0 else ewar
                        
                        cand_b[f"[{row['球隊']}] {row['球員姓名']}"] = {'類型': '打者', 'HR': row['全壘打'], 'RBI': row['打點'], 'AVG': avg, 'wRC+': wrc_plus, 'eWAR': ewar, 'PA': row['打席'], 'K': row['三振'], 'BB': row['四壞球']}

                if not df_p_sub.empty:
                    df_p_agg = df_p_sub.groupby(['球隊', '投手姓名']).sum().reset_index()
                    counts = df_p_sub.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
                    if '勝' not in counts.columns: counts['勝'] = 0
                    if '敗' not in counts.columns: counts['敗'] = 0
                    if '救援' not in counts.columns: counts['救援'] = 0
                    if '中繼' not in counts.columns: counts['中繼'] = 0
                    df_p_agg = pd.merge(df_p_agg, counts, on=['球隊', '投手姓名'], how='left')
                    
                    for _, row in df_p_agg.iterrows():
                        ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                        if ip_calc < min_ip: continue 
                        era = (row['自責分'] * 9) / max(1, ip_calc) if ip_calc > 0 else float('inf') if row['自責分'] > 0 else 0.0
                        fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10 if ip_calc > 0 else float('inf') if (13*row['被全壘打']+3*row['四壞球']-2*row['奪三振'])>0 else 3.10
                        tra = (era + fip) / 2.0
                        
                        ewar = (-0.1 * row['自責分'] - 0.05 * row['四壞球']) if ip_calc == 0 else ((5.00 - tra) / 1.5) * (ip_calc / 10)
                        ewar = 0.0 if round(ewar, 1) == 0 else ewar 
                        
                        name = f"[{row['球隊']}] {row['投手姓名']}"
                        if name in cand_b: 
                            cand_b[name]['類型'] = '二刀流'
                            cand_b[name]['eWAR'] += ewar 
                            cand_b[name]['W'] = row.get('勝', 0)
                            cand_b[name]['L'] = row.get('敗', 0)
                            cand_b[name]['SV'] = row.get('救援', 0)
                            cand_b[name]['HLD'] = row.get('中繼', 0)
                            cand_b[name]['ERA'] = era
                            cand_b[name]['K_p'] = row.get('奪三振', 0)
                            cand_b[name]['FIP'] = fip
                            cand_b[name]['IP'] = ip_calc
                        else:
                            cand_p[name] = {'類型': '投手', 'W': row['勝'], 'L': row['敗'], 'SV': row['救援'], 'HLD': row['中繼'], 'ERA': era, 'FIP': fip, 'K_p': row['奪三振'], 'eWAR': ewar, 'IP': ip_calc}
                
                all_cand = {**cand_b, **cand_p}
                leaders = {
                    'HR': max([s.get('HR', 0) for s in all_cand.values()] + [0]),
                    'RBI': max([s.get('RBI', 0) for s in all_cand.values()] + [0]),
                    'W': max([s.get('W', 0) for s in all_cand.values()] + [0]),
                    'K_p': max([s.get('K_p', 0) for s in all_cand.values()] + [0])
                }
                return all_cand, leaders

            def simulate_voting(candidates, leaders, target_award, winner_team=None):
                if not candidates: return pd.DataFrame()
                results = {name: {'1st': 0, '2nd': 0, '3rd': 0, 'Points': 0} for name in candidates}
                voter_types = ['Traditional']*12 + ['Sabermetric']*10 + ['Balanced']*8
                
                max_hr, max_rbi, max_w, max_k = leaders.get('HR', 0), leaders.get('RBI', 0), leaders.get('W', 0), leaders.get('K_p', 0)
                
                min_era = 99.9
                for stats in candidates.values():
                    if stats['類型'] in ['投手', '二刀流'] and 'ERA' in stats:
                        if stats['ERA'] < min_era: min_era = stats['ERA']
                
                for voter in voter_types:
                    scores = {}
                    for name, stats in candidates.items():
                        score = 0
                        leader_bonus = 0
                        
                        if target_award != "FMVP": 
                            if stats.get('HR', 0) == max_hr and max_hr > 0: leader_bonus += 30
                            if stats.get('RBI', 0) == max_rbi and max_rbi > 0: leader_bonus += 20
                            if stats.get('W', 0) == max_w and max_w > 0: leader_bonus += 10
                            if stats.get('K_p', 0) == max_k and max_k > 0: leader_bonus += 20
                            if stats.get('ERA', 99.9) == min_era and min_era < 4.0: leader_bonus += 35
                        
                        if target_award == "MVP":
                            if voter == 'Traditional':
                                if stats['類型'] in ['打者', '二刀流']:
                                    score += stats.get('HR', 0) * 20 + stats.get('RBI', 0) * 10 + leader_bonus 
                                    if stats.get('AVG', 0) > 0.300: score += 20
                                    elif stats.get('AVG', 0) < 0.250: score -= 30
                                if stats['類型'] in ['投手', '二刀流']:
                                    score += stats.get('W', 0) * 12 + stats.get('SV', 0) * 10 + stats.get('K_p', 0) * 1.5 - stats.get('ERA', 5) * 15 + leader_bonus
                                    if stats.get('ERA', 5) < 3.00: score += 25
                            elif voter == 'Sabermetric':
                                score += stats.get('eWAR', 0) * 80 + leader_bonus * 0.2 
                            else: 
                                score += stats.get('eWAR', 0) * 50 + stats.get('HR', 0) * 12 + stats.get('W', 0) * 5 + stats.get('K_p', 0) * 1 - stats.get('ERA', 5) * 10 + leader_bonus * 0.5
                        
                        elif target_award == "CyYoung":
                            if stats['類型'] == '打者': continue
                            if stats.get('ERA', 5) > 5.00: score -= 500 
                            if voter == 'Traditional':
                                score += stats.get('W', 0) * 12 + stats.get('SV', 0) * 12 + stats.get('K_p', 0) * 1.5 - stats.get('ERA', 5) * 20 + leader_bonus
                                if stats.get('ERA', 5) < 2.50: score += 30
                            else:
                                score += stats.get('eWAR', 0) * 60 - stats.get('FIP', 5) * 15 - stats.get('ERA', 5) * 10 + leader_bonus * 0.5
                        
                        elif target_award == "SilverSlugger":
                            if stats['類型'] == '投手': continue
                            if voter == 'Traditional': score += stats.get('HR', 0) * 25 + stats.get('AVG', 0) * 100 + leader_bonus
                            else: score += stats.get('eWAR', 0) * 20 + stats.get('wRC+', 0) * 2
                        
                        elif target_award == "FMVP":
                            if winner_team and f"[{winner_team}]" not in name:
                                score -= 1000
                                
                            if stats['類型'] in ['打者', '二刀流']:
                                score += stats.get('HR', 0) * 40 + stats.get('RBI', 0) * 20 + stats.get('wRC+', 0) * 0.5
                            if stats['類型'] in ['投手', '二刀流']:
                                score += stats.get('W', 0) * 25 + stats.get('SV', 0) * 25 + stats.get('K_p', 0) * 2 - stats.get('ERA', 5) * 20
                            score += stats.get('eWAR', 0) * 60 

                        scores[name] = score + random.uniform(0, 5) 
                    
                    if not scores: continue
                    
                    top5 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                    if len(top5) >= 1:
                        results[top5[0][0]]['1st'] += 1
                        results[top5[0][0]]['Points'] += 14
                    if len(top5) >= 2:
                        results[top5[1][0]]['2nd'] += 1
                        results[top5[1][0]]['Points'] += 9
                    if len(top5) >= 3:
                        results[top5[2][0]]['3rd'] += 1
                        results[top5[2][0]]['Points'] += 8
                    if len(top5) >= 4: results[top5[3][0]]['Points'] += 5
                    if len(top5) >= 5: results[top5[4][0]]['Points'] += 3
                        
                df_res = pd.DataFrame.from_dict(results, orient='index').reset_index()
                df_res.columns = ['球員', '第一名選票', '第二名選票', '第三名選票', '總積分']
                df_res = df_res[df_res['總積分'] > 0].sort_values('總積分', ascending=False).reset_index(drop=True)
                df_res.index = df_res.index + 1 
                return df_res

            if btn_reg:
                with st.spinner("30 位 AI 記者正在查閱例行賽數據..."):
                    time.sleep(1.5)
                    cand_reg, lead_reg = extract_stats("例行賽", prefix, is_ws=False)
                    
                    st.balloons()
                    st.markdown("## 📅 例行賽大獎 (Regular Season Awards)")
                    
                    st.subheader(f"🏆 {target_season} 年度最有價值球員 (MVP)")
                    mvp_df = simulate_voting(cand_reg, lead_reg, "MVP")
                    if not mvp_df.empty:
                        st.success(f"🥇 **年度 MVP 得主：{mvp_df.iloc[0]['球員']}**")
                        st.dataframe(mvp_df.head(10).style.format({'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}), use_container_width=True)
                    else: st.info("例行賽：查無符合資格的球員。")

                    st.subheader(f"🎯 {target_season} 賽揚獎 (Cy Young Award)")
                    cy_df = simulate_voting(cand_reg, lead_reg, "CyYoung")
                    if not cy_df.empty:
                        st.info(f"🥇 **賽揚獎得主：{cy_df.iloc[0]['球員']}**")
                        st.dataframe(cy_df.head(5).style.format({'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}), use_container_width=True)
                    else: st.info("例行賽：查無符合資格的投手。")

                    st.subheader(f"🏏 {target_season} 最佳打者 (銀棒獎)")
                    ss_df = simulate_voting(cand_reg, lead_reg, "SilverSlugger")
                    if not ss_df.empty:
                        st.warning(f"🥇 **銀棒獎得主：{ss_df.iloc[0]['球員']}**")
                        st.dataframe(ss_df.head(5).style.format({'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}), use_container_width=True)
                    else: st.info("例行賽：查無符合資格的打者。")

                    st.markdown("---")
                    st.subheader("🎭 賽季趣味特別獎項")
                    
                    batters = {k: v for k, v in cand_reg.items() if v['類型'] in ['打者', '二刀流']}
                    if batters:
                        best_hitter = max(batters.items(), key=lambda x: x[1]['wRC+'])
                        c_fun0, _ = st.columns([1, 1])
                        c_fun0.metric("👑 漢克阿倫獎 (年度最佳打者)", f"wRC+ {int(best_hitter[1]['wRC+'])}", best_hitter[0], help="頒發給全聯盟綜合打擊火力 (wRC+) 最強的球員。")

                    if s_num_int > 1:
                        prev_prefix = f"[S{s_num_int - 1}]"
                        cand_prev, _ = extract_stats("例行賽", prev_prefix, is_ws=False)
                        
                        comeback_cands = {}
                        for name, current_stats in cand_reg.items():
                            if name in cand_prev:
                                prev_ewar = cand_prev[name].get('eWAR', 0)
                                curr_ewar = current_stats.get('eWAR', 0)
                                delta = curr_ewar - prev_ewar
                                if delta > 0:
                                    comeback_cands[name] = {
                                        'delta': delta,
                                        'prev_ewar': prev_ewar,
                                        'curr_ewar': curr_ewar
                                    }
                        
                        if comeback_cands:
                            best_comeback = max(comeback_cands.items(), key=lambda x: x[1]['delta'])
                            c_fun_cb, _ = st.columns([1, 1])
                            c_fun_cb.metric(
                                "🔥 東山再起獎 / 最佳進步獎", 
                                f"+{best_comeback[1]['delta']:.1f} eWAR", 
                                f"{best_comeback[0]} (去年 {best_comeback[1]['prev_ewar']:.1f} ➔ 今年 {best_comeback[1]['curr_ewar']:.1f})", 
                                help="頒發給對比去年賽季，eWAR（勝場貢獻值）進步幅度最大的球員！"
                            )

                    relievers = {k: v for k, v in cand_reg.items() if v['類型'] in ['投手', '二刀流'] and v.get('SV', 0) > 0}
                    if relievers:
                        best_reliever = sorted(relievers.items(), key=lambda x: (x[1]['SV'], -x[1]['ERA']), reverse=True)[0]
                        c_fun_r, _ = st.columns([1, 1])
                        era_str = "∞" if best_reliever[1]['ERA'] == float('inf') else f"{best_reliever[1]['ERA']:.2f}"
                        c_fun_r.metric("🔒 最佳救援投手 (李維拉/霍夫曼獎)", f"{int(best_reliever[1]['SV'])} SV (ERA {era_str})", best_reliever[0], help="頒發給聯盟最強的終結者。")

                    if not df_p_raw.empty:
                        reg_p_raw = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)) & 
                                             (df_p_raw['賽事階段'].astype(str).str.contains("例行賽", regex=False))]
                        if not reg_p_raw.empty:
                            relievers_only = []
                            for stage, group in reg_p_raw.groupby('賽事階段', sort=False):
                                g_sorted = group.sort_values('時間戳記', ascending=True)
                                if len(g_sorted) > 1:
                                    relievers_only.append(g_sorted.iloc[1:])
                            
                            if relievers_only:
                                true_relievers_df = pd.concat(relievers_only)
                                appearances = true_relievers_df.groupby(['球隊', '投手姓名']).size().reset_index(name='出賽數')
                                if not appearances.empty:
                                    max_app = appearances['出賽數'].max()
                                    top_relievers = appearances[appearances['出賽數'] == max_app]
                                    r_names = " / ".join([f"[{r['球隊']}] {r['投手姓名']}" for _, r in top_relievers.iterrows()])
                                    c_fun1, _ = st.columns([1, 1])
                                    c_fun1.metric("🏥 鐵人後援王", f"{max_app} 場", r_names, help="整季例行賽牛棚出賽次數最多的投手，教練最愛操的勞碌命。")

                    unlucky_pitchers = {k: v for k, v in cand_reg.items() if v['類型'] in ['投手', '二刀流'] and v.get('L', 0) > 0 and v['ERA'] < 3.5}
                    if unlucky_pitchers:
                        most_unlucky = sorted(unlucky_pitchers.items(), key=lambda x: (x[1]['L'], x[1]['ERA']), reverse=True)[0]
                        c_fun_un, _ = st.columns([1, 1])
                        c_fun_un.metric("😭 悲情賽揚 (地獄倒楣鬼)", f"{int(most_unlucky[1]['L'])} 敗 (ERA {most_unlucky[1]['ERA']:.2f})", most_unlucky[0], help="防禦率極佳卻吞下最多敗投，完全得不到打線支援的苦主。")

                    if batters:
                        blind_swinger = max(batters.items(), key=lambda x: x[1].get('K', 0))
                        if blind_swinger[1].get('K', 0) > 0:
                            c_fun_k, _ = st.columns([1, 1])
                            c_fun_k.metric("🌪️ 盲劍客 (電風扇大師)", f"{int(blind_swinger[1]['K'])} K", blind_swinger[0], help="整季吞下最多三振的打者。")

                        eye_batters = {k: v for k, v in batters.items() if v.get('K', 0) > 0 or v.get('BB', 0) > 0}
                        if eye_batters:
                            for k, v in eye_batters.items():
                                v['BBK'] = v.get('BB', 0) / max(0.5, v.get('K', 0))
                            top_eye = max(eye_batters.items(), key=lambda x: x[1]['BBK'])
                            c_fun2, _ = st.columns([1, 1])
                            c_fun2.metric("🦅 聯盟神之眼", f"{top_eye[1]['BBK']:.2f} BB/K", top_eye[0], help="保送三振比最高，投手最不想面對的纏鬥達人。")

            if btn_ws:
                with st.spinner("30 位 AI 記者正在查閱世界大賽戰報..."):
                    time.sleep(1.5)
                    cand_ws, lead_ws = extract_stats("世界大賽", prefix, is_ws=True) 
                    
                    ws_winner = None
                    laa_wins = 0
                    lad_wins = 0
                    
                    if not df_p_raw.empty:
                        df_p_ws = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains("世界大賽", regex=False))]
                        
                        def get_ws_wins(team_name):
                            t_ws = df_p_ws[df_p_ws['球隊'] == team_name]
                            w = 0
                            for stage, group in t_ws.groupby('賽事階段', sort=False):
                                res = group['勝敗'].astype(str).values
                                if any('勝' in x for x in res): w += 1
                            return w
                            
                        laa_wins = get_ws_wins('LAA')
                        lad_wins = get_ws_wins('LAD')
                        
                        if laa_wins > lad_wins: ws_winner = 'LAA'
                        elif lad_wins > laa_wins: ws_winner = 'LAD'
                            
                    if laa_wins >= 4:
                        st.success(f"## 🏆 🎊 恭喜 LAA 勇奪 {target_season} 世界大賽總冠軍！ 🎊 🏆", icon="🍾")
                        st.balloons()
                    elif lad_wins >= 4:
                        st.success(f"## 🏆 🎊 恭喜 LAD 勇奪 {target_season} 世界大賽總冠軍！ 🎊 🏆", icon="🍾")
                        st.balloons()
                    elif laa_wins == lad_wins and laa_wins > 0:
                        st.warning(f"🔥 激戰中！目前雙方戰成 **{laa_wins} : {lad_wins}** 平手！")
                    elif laa_wins > lad_wins:
                        st.warning(f"🔥 聽牌/激戰中！目前 LAA 以 **{laa_wins} : {lad_wins}** 領先 LAD！")
                    elif lad_wins > laa_wins:
                        st.warning(f"🔥 聽牌/激戰中！目前 LAD 以 **{lad_wins} : {laa_wins}** 領先 LAA！")
                    elif laa_wins == 0 and lad_wins == 0:
                        st.info("ℹ️ 尚未產生任何勝場紀錄。")
                    
                    st.markdown("## 💍 季後賽最高榮耀 (Postseason Honors)")
                    
                    st.subheader(f"🎆 {target_season} 世界大賽最有價值球員 (World Series MVP)")
                    fmvp_df = simulate_voting(cand_ws, lead_ws, "FMVP", winner_team=ws_winner)
                    
                    if not fmvp_df.empty:
                        st.error(f"💍 **FMVP 得主：{fmvp_df.iloc[0]['球員']}** (帶領 {ws_winner if ws_winner else '球隊'} 拿下最終金盃！)")
                        st.dataframe(fmvp_df.head(5).style.format({'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}), use_container_width=True)
                    else: st.info("尚未產生足夠的世界大賽數據，或無人達標。快去打世界大賽吧！")