import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
import time
import random
import json  
import os    

# ==========================================
# 專屬設定 & 規定門檻設定 (MLB 標準)
# ==========================================
SERVICE_ACCOUNT_FILE = 'baseball.json'
SHEET_NAME = '棒球數據資料庫'
TEAMS = ["LAA", "LAD"]

TOTAL_GAMES = 10  
QUALIFY_PA = TOTAL_GAMES * 1.0   
QUALIFY_IP = TOTAL_GAMES * 0.33  

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
    df_b_agg = pd.DataFrame()
    df_p_agg = pd.DataFrame()
    
    try:
        if records_b:
            df_b = pd.DataFrame(records_b, columns=['時間戳記', '賽事階段', '球隊', '球員姓名', '打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘'])
            num_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']
            for col in num_cols: df_b[col] = pd.to_numeric(df_b[col], errors='coerce').fillna(0)
            st.session_state.df_b_raw = df_b 
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
st.title("⚾ 洛杉磯雙雄數據追蹤系統 V30 (二刀流制霸版)")

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
        * **WAR (勝場貢獻值)：** 衡量一名球員「比替補多替球隊拿幾勝」。本系統特製 **eWAR** 是透過 OPS+ 與 FIP 精算而成。
        * **OPS+：** **100 為全聯盟平均**。150 代表火力比平均高出 50%。
        * **FIP (獨立防禦率)：** 剔除守備與運氣成分。
          * 📉 **FIP < ERA：** 投得很好，但運氣差或隊友雷，實力被低估。
          * 📈 **FIP > ERA：** 帳面好看，但很多出局是靠隊友，隨時可能核爆。
        * **ISO (純長打率)：** > **0.200** 就是貨真價實的重砲手。
        * **BABIP (場內安打率)：** 異常高代表強運；異常低則是地獄倒楣鬼。
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

    st.markdown("### 📊 球隊戰績排名 (Team Standings)")
    if not df_p.empty:
        stand_b = df_b[df_b['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix and not df_b.empty else df_b
        stand_p = df_p[df_p['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix else df_p
        
        team_data = []
        for team in TEAMS:
            t_p = stand_p[stand_p['球隊'] == team]
            t_b = stand_b[stand_b['球隊'] == team] if not stand_b.empty else pd.DataFrame()
            
            wins, losses, draws = 0, 0, 0
            starters = []
            
            for stage, group in t_p.groupby('賽事階段'):
                group = group.sort_values('時間戳記')
                res = group['勝敗'].astype(str).values
                
                # 模糊判定勝敗
                if any('勝' in x for x in res): wins += 1
                elif any('敗' in x for x in res): losses += 1
                else: draws += 1 
                
                starters.append(group.iloc[0]['投手姓名'])
            
            rs = pd.to_numeric(t_b['得分'], errors='coerce').sum() if not t_b.empty else 0
            ra = pd.to_numeric(t_p['失分'], errors='coerce').sum()
            
            recent_sps = []
            for sp in reversed(starters):
                if sp not in recent_sps:
                    recent_sps.append(sp)
                if len(recent_sps) >= 5: break
            recent_sps.reverse()
            
            last_sp = starters[-1] if starters else "無"
            try:
                idx = recent_sps.index(last_sp)
                next_sp = recent_sps[(idx + 1) % len(recent_sps)]
            except: 
                next_sp = last_sp if last_sp != "無" else "輪值待定"

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
        curr_b = df_b[df_b['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix else df_b
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
            total_tb = (total_h - curr_b['二壘安打'].sum() - curr_b['三壘安打'].sum() - curr_b['全壘打'].sum()) + 2*curr_b['二壘安打'].sum() + 3*curr_b['三壘安打'].sum() + 4*curr_b['全壘打'].sum()
            lg_obp = (total_h + total_bb) / total_pa if total_pa > 0 else 0.0
            lg_slg = total_tb / total_ab if total_ab > 0 else 0.0
            def calc_ops_plus(row):
                if lg_obp > 0 and lg_slg > 0 and row['打席'] > 0: return 100 * ((row['OBP'] / lg_obp) + (row['SLG'] / lg_slg) - 1)
                return 0.0
            agg_b['OPS+'] = agg_b.apply(calc_ops_plus, axis=1).round(0).astype(int)
            agg_b['eWAR'] = agg_b.apply(lambda r: ((r['OPS+'] - 80) / 100) * (r['打席'] / 20), axis=1)

            qual_b = agg_b[agg_b['打席'] >= QUALIFY_PA]
            avg_pool = qual_b if not qual_b.empty else agg_b
            
            if not agg_b.empty:
                st.markdown(f"#### 👑 聯盟打擊領先者 (規定打席: {QUALIFY_PA})")
                
                def get_b_leader(df, col, is_max=True):
                    if df.empty: return 0, "無"
                    sorted_df = df.sort_values(by=[col, '打席'], ascending=[not is_max, True])
                    top = sorted_df.iloc[0]
                    return top[col], f"[{top['球隊']}] {top['球員姓名']}"
                
                val_avg, name_avg = get_b_leader(avg_pool, 'AVG', True)
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
            lg_ops = lg_obp + lg_slg
            lg_avg = total_h / total_ab if total_ab > 0 else 0.0
            summary_b = []
            summary_b.append({'隊伍': '🌎 全聯盟平均', 'OPS+': 100, 'OPS': lg_ops, 'AVG': lg_avg, 'OBP': lg_obp, 'SLG': lg_slg})
            for team in TEAMS:
                t_df = curr_b[curr_b['球隊'] == team]
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

            show_cols_b = ['球隊', '球員姓名', '出賽數', '打席', '打數', 'OPS+', 'OPS', 'AVG', 'OBP', 'SLG', 'ISO', 'BABIP', 'BB%', 'K%', '全壘打', '打點', '盜壘', 'eWAR']
            show_df = agg_b[show_cols_b].copy()
            show_df = show_df.sort_values(by=['球隊', 'OPS+'], ascending=[True, False])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人打擊榜")
                team_df = show_df[show_df['球隊'] == team]
                if not team_df.empty: 
                    styled_df = team_df.drop(columns=['球隊']).style.format({
                        'OPS': '{:.3f}', 'AVG': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'ISO': '{:.3f}', 'BABIP': '{:.3f}',
                        'BB%': '{:.1f}%', 'K%': '{:.1f}%', 'eWAR': '{:.1f}'
                    })
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else: st.info("目前沒有打擊紀錄可以顯示！")

    st.markdown("---")
    
    st.markdown("### 🥎 投球成績")
    if not df_p.empty:
        curr_p = df_p[df_p['賽事階段'].astype(str).str.contains(target_prefix, regex=False)] if target_prefix else df_p
        if curr_p.empty: st.info("查無符合條件的投球紀錄。")
        else:
            p_cols = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '四壞球', '奪三振', '失分', '自責分']
            agg_p = curr_p.groupby(['球隊', '投手姓名'])[p_cols].sum().reset_index()
            stats_counts = curr_p.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
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
            
            agg_p['TRA'] = (agg_p['ERA'] + agg_p['FIP']) / 2.0
            agg_p['eWAR'] = agg_p.apply(lambda r: ((5.00 - r['TRA']) / 1.5) * (r['實際局數'] / 10), axis=1)

            qual_p = agg_p[agg_p['實際局數'] >= QUALIFY_IP]
            era_pool = qual_p if not qual_p.empty else agg_p
            
            if not agg_p.empty:
                st.markdown(f"#### 👑 聯盟投球領先者 (規定局數: {QUALIFY_IP})")
                
                def get_p_leader(df, col, is_max=True):
                    if df.empty: return 0, "無"
                    sorted_df = df.sort_values(by=[col, '實際局數'], ascending=[not is_max, True])
                    top = sorted_df.iloc[0]
                    return top[col], f"[{top['球隊']}] {top['投手姓名']}"

                val_era, name_era = get_p_leader(era_pool, 'ERA', False)
                val_w, name_w = get_p_leader(agg_p, '勝投', True)
                val_sv, name_sv = get_p_leader(agg_p, '救援成功', True)
                val_hld, name_hld = get_p_leader(agg_p, '中繼成功', True)
                val_so, name_so = get_p_leader(agg_p, '奪三振', True)
                
                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                lc1.metric(f"防禦率王", f"{val_era:.2f}", name_era)
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
            lg_era = (lg_er * 9) / lg_ip if lg_ip > 0 else 0
            lg_whip = (lg_h + lg_bb) / lg_ip if lg_ip > 0 else 0
            lg_fip = (((13 * lg_hr) + (3 * lg_bb) - (2 * lg_so)) / lg_ip + 3.10) if lg_ip > 0 else 0

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
                    t_era = (t_er * 9) / t_ip if t_ip > 0 else 0
                    t_whip = (t_h + t_bb) / t_ip if t_ip > 0 else 0
                    t_fip = (((13 * t_hr) + (3 * t_bb) - (2 * t_so)) / t_ip + 3.10) if t_ip > 0 else 0
                    summary_p.append({'隊伍': f"🔴 {team}" if team == "LAA" else f"🔵 {team}", 'ERA': t_era, 'FIP': t_fip, 'WHIP': t_whip, 'K/9': (t_so * 9 / t_ip) if t_ip > 0 else 0, 'BB/9': (t_bb * 9 / t_ip) if t_ip > 0 else 0})
                    
            st.markdown("#### ⚖️ 團隊防線對比")
            df_sum_p = pd.DataFrame(summary_p)
            st.dataframe(df_sum_p.style.format({'ERA': '{:.2f}', 'FIP': '{:.2f}', 'WHIP': '{:.2f}', 'K/9': '{:.2f}', 'BB/9': '{:.2f}'}), use_container_width=True, hide_index=True)
            
            show_cols_p = ['球隊', '投手姓名', '勝投', '中繼成功', '救援成功', 'ERA', 'FIP', 'WHIP', 'K/9', 'BB/9', 'HR/9', 'K/BB', '總局數', '奪三振', 'eWAR']
            show_p = agg_p[show_cols_p].copy()
            show_p = show_p.sort_values(by=['球隊', 'FIP'], ascending=[True, True])

            for team in TEAMS:
                st.markdown(f"#### {team} 個人投手榜")
                team_df = show_p[show_p['球隊'] == team]
                if not team_df.empty: 
                    styled_p = team_df.drop(columns=['球隊']).style.format({
                        'ERA': '{:.2f}', 'FIP': '{:.2f}', 'WHIP': '{:.2f}',
                        'K/9': '{:.2f}', 'BB/9': '{:.2f}', 'HR/9': '{:.2f}', 'K/BB': '{:.2f}',
                        '總局數': '{:.1f}', 'eWAR': '{:.1f}'
                    })
                    st.dataframe(styled_p, use_container_width=True, hide_index=True)
    else: st.info("目前沒有投球紀錄可以顯示！")

# ==========================================
# --- 分頁 4：📋 賽前戰情室 ---
# ==========================================
with tab4:
    st.header("📋 賽前戰情室與 AI 深度戰報")
    get_career_stats()

    season_options_wr = ["十年總成績"] + SEASONS
    saved_wr_season = st.session_state.get("wr_season", "十年總成績")
    wr_s_idx = season_options_wr.index(saved_wr_season) if saved_wr_season in season_options_wr else 0
    
    def update_wr_season():
        st.session_state.wr_season = st.session_state.wr_season_sel
        if 'save_settings' in globals(): save_settings()
        
    wr_season = st.selectbox("📊 選擇分析賽季 (排打線與戰報將以本季近況為主)", season_options_wr, index=wr_s_idx, key="wr_season_sel", on_change=update_wr_season)

    def get_season_data(target_season):
        df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
        df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_b_raw.empty and df_p_raw.empty: return {}, {}
        
        prefix = ""
        if target_season != "十年總成績":
            s_num = target_season.split(" ")[1]
            prefix = f"[S{s_num}]"

        b_sub = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_b_raw
        p_sub = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_raw

        b_dict, p_dict = {'LAA': {}, 'LAD': {}}, {'LAA': {}, 'LAD': {}}
        
        if not b_sub.empty:
            total_pa = b_sub['打席'].sum()
            lg_obp = (b_sub['安打'].sum() + b_sub['四壞球'].sum()) / total_pa if total_pa > 0 else 0
            lg_slg = ((b_sub['安打'].sum() - b_sub['二壘安打'].sum() - b_sub['三壘安打'].sum() - b_sub['全壘打'].sum()) + 2*b_sub['二壘安打'].sum() + 3*b_sub['三壘安打'].sum() + 4*b_sub['全壘打'].sum()) / b_sub['打數'].sum() if b_sub['打數'].sum() > 0 else 0

            agg_b = b_sub.groupby(['球隊', '球員姓名']).sum().reset_index()
            for _, row in agg_b.iterrows():
                avg = row['安打'] / max(1, row['打數'])
                obp = (row['安打'] + row['四壞球']) / max(1, row['打席'])
                slg = ((row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']) + 2*row['二壘安打'] + 3*row['三壘安打'] + 4*row['全壘打']) / max(1, row['打數'])
                ops_p = 100 * ((obp / lg_obp) + (slg / lg_slg) - 1) if lg_obp > 0 and lg_slg > 0 else 0
                ewar = ((ops_p - 80) / 100) * (row['打席'] / 20)
                
                iso = slg - avg
                k_pct = (row['三振'] / max(1, row['打席'])) * 100
                bb_pct = (row['四壞球'] / max(1, row['打席'])) * 100
                babip = (row['安打'] - row['全壘打']) / max(1, (row['打數'] - row['三振'] - row['全壘打']))
                
                team = row['球隊']
                if team not in b_dict: b_dict[team] = {}
                b_dict[team][row['球員姓名']] = {
                    'OPS+': ops_p, 'eWAR': ewar, 'AVG': avg, 'OBP': obp, 'HR': row['全壘打'],
                    'ISO': iso, 'K%': k_pct, 'BB%': bb_pct, 'BABIP': babip, 'SB': row['盜壘']
                }

        if not p_sub.empty:
            agg_p = p_sub.groupby(['球隊', '投手姓名']).sum().reset_index()
            for _, row in agg_p.iterrows():
                ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                era = (row['自責分'] * 9) / max(1, ip_calc)
                fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10
                tra = (era + fip) / 2.0
                ewar = ((5.00 - tra) / 1.5) * (ip_calc / 10)
                
                whip = (row['被安打'] + row['四壞球']) / max(1, ip_calc)
                k9 = (row['奪三振'] * 9) / max(1, ip_calc)
                
                team = row['球隊']
                if team not in p_dict: p_dict[team] = {}
                p_dict[team][row['投手姓名']] = {
                    'ERA': era, 'eWAR': ewar, 'K': row['奪三振'], 'FIP': fip,
                    'WHIP': whip, 'K/9': k9
                }

        return b_dict, p_dict

    curr_b_stats, curr_p_stats = get_season_data(wr_season)
    
    prev_season_str = "十年總成績"
    if wr_season != "十年總成績":
        curr_s_num = int(wr_season.split(" ")[1])
        if curr_s_num > 1: prev_season_str = f"Season {curr_s_num - 1}"
    prev_b_stats, prev_p_stats = get_season_data(prev_season_str)

    cached_players_b = get_player_list("打擊單場紀錄")
    cached_players_p = get_player_list("投手單場紀錄")
    
    st.markdown("---")
    col_ai1, col_ai2 = st.columns(2)
    
    def auto_lineup(team_name):
        available_players = cached_players_b.get(team_name, [])
        team_b_stats = curr_b_stats.get(team_name, {})
        valid_players = [p for p in available_players if p in team_b_stats]
        
        if len(valid_players) < 9:
            st.toast(f"⚠️ {team_name} 擁有數據的球員不足 9 人，無法啟動代排。")
            return
            
        top_9 = sorted(valid_players, key=lambda x: team_b_stats[x]['OPS+'], reverse=True)[:9]
        
        leadoff = max(top_9, key=lambda x: team_b_stats[x]['OBP'])  
        top_9.remove(leadoff)
        cleanup = max(top_9, key=lambda x: team_b_stats[x]['ISO'])  
        top_9.remove(cleanup)
        second = max(top_9, key=lambda x: team_b_stats[x]['OPS+'])  
        top_9.remove(second)
        third = max(top_9, key=lambda x: team_b_stats[x]['AVG'])    
        top_9.remove(third)
        fifth = max(top_9, key=lambda x: team_b_stats[x]['OPS+'])   
        top_9.remove(fifth)
        
        rest = sorted(top_9, key=lambda x: team_b_stats[x]['OPS+'], reverse=True)
        
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
                stats = curr_b_stats.get("LAA", {}).get(p, {'OPS+': 0, 'eWAR': 0, 'AVG': 0})
                st.caption(f"📊 eWAR: **{stats['eWAR']:.1f}** | OPS+: **{stats['OPS+']:.0f}** | AVG: {stats['AVG']:.3f}")
            
        laa_sp_options = ["未指定"] + cached_players_p.get("LAA", [])
        saved_sp_laa = st.session_state.pitchers["LAA"]
        laa_sp_idx = laa_sp_options.index(saved_sp_laa) if saved_sp_laa in laa_sp_options else 0
        laa_sp = st.selectbox("先發投手 (SP)", laa_sp_options, index=laa_sp_idx, key="laa_sp")
        st.session_state.pitchers["LAA"] = laa_sp if laa_sp != "未指定" else ""
        if laa_sp != "未指定":
            stats = curr_p_stats.get("LAA", {}).get(laa_sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
            st.caption(f"🥎 eWAR: **{stats['eWAR']:.1f}** | ERA: **{stats['ERA']:.2f}** | K: {stats['K']}")
        
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
                stats = curr_b_stats.get("LAD", {}).get(p, {'OPS+': 0, 'eWAR': 0, 'AVG': 0})
                st.caption(f"📊 eWAR: **{stats['eWAR']:.1f}** | OPS+: **{stats['OPS+']:.0f}** | AVG: {stats['AVG']:.3f}")
            
        lad_sp_options = ["未指定"] + cached_players_p.get("LAD", [])
        saved_sp_lad = st.session_state.pitchers["LAD"]
        lad_sp_idx = lad_sp_options.index(saved_sp_lad) if saved_sp_lad in lad_sp_options else 0
        lad_sp = st.selectbox("先發投手 (SP)", lad_sp_options, index=lad_sp_idx, key="lad_sp")
        st.session_state.pitchers["LAD"] = lad_sp if lad_sp != "未指定" else ""
        if lad_sp != "未指定":
            stats = curr_p_stats.get("LAD", {}).get(lad_sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
            st.caption(f"🥎 eWAR: **{stats['eWAR']:.1f}** | ERA: **{stats['ERA']:.2f}** | K: {stats['K']}")

    st.markdown("---")
    
    st.subheader("🔮 賽前戰力天秤 (Expected Win %)")
    
    def get_streak_bonus(team_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return 0
        t_df = df_p_full[df_p_full['球隊'] == team_name].sort_values(by='時間戳記', ascending=True)
        results = []
        for stage, group in t_df.groupby('賽事階段'):
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

    def get_avg_ip(team_name, p_name):
        df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
        if df_p_full.empty: return 5.0
        sub = df_p_full[(df_p_full['球隊'] == team_name) & (df_p_full['投手姓名'] == p_name)]
        if sub.empty: return 5.0
        outs = (pd.to_numeric(sub['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(sub['局數(出局數)'], errors='coerce').fillna(0)).sum()
        return (outs / 3.0) / len(sub)

    # ✨ 國際賭盤賠率轉換公式 (Moneyline)
    def calc_moneyline(prob):
        if prob > 50:
            return f"-{int(round((prob / (100.0 - prob)) * 100))}"
        elif prob < 50:
            return f"+{int(round(((100.0 - prob) / max(0.1, prob)) * 100))}"
        else:
            return "PK"

    def calc_win_prob():
        laa_b_ewar = sum([curr_b_stats.get('LAA', {}).get(p, {'eWAR':0})['eWAR'] for p in laa_batters])
        lad_b_ewar = sum([curr_b_stats.get('LAD', {}).get(p, {'eWAR':0})['eWAR'] for p in lad_batters])
        
        laa_sp_ewar = curr_p_stats.get('LAA', {}).get(laa_sp, {'eWAR':0})['eWAR'] * 2.5 if laa_sp != "未指定" else 0
        lad_sp_ewar = curr_p_stats.get('LAD', {}).get(lad_sp, {'eWAR':0})['eWAR'] * 2.5 if lad_sp != "未指定" else 0
        
        laa_total = laa_b_ewar + laa_sp_ewar
        lad_total = lad_b_ewar + lad_sp_ewar
        
        laa_momentum = get_streak_bonus('LAA')
        lad_momentum = get_streak_bonus('LAD')
        
        diff = laa_total - lad_total
        laa_prob = 50.0 + (diff * 3.0) + laa_momentum - lad_momentum
        
        is_laa_op = laa_sp != "未指定" and get_avg_ip('LAA', laa_sp) < 3.0
        is_lad_op = lad_sp != "未指定" and get_avg_ip('LAD', lad_sp) < 3.0
        
        if is_laa_op: laa_prob -= 4.0
        if is_lad_op: laa_prob += 4.0
        
        laa_prob = max(5.0, min(95.0, laa_prob)) 
        return round(laa_prob, 1), round(100.0 - laa_prob, 1), is_laa_op, is_lad_op

    prob_laa, prob_lad, is_laa_opener, is_lad_opener = calc_win_prob()
    ml_laa = calc_moneyline(prob_laa)
    ml_lad = calc_moneyline(prob_lad)
    
    st.markdown(f"""
    <div style="display: flex; height: 35px; border-radius: 8px; overflow: hidden; font-weight: bold; color: white; text-align: center; line-height: 35px; font-size: 16px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);">
        <div style="width: {prob_laa}%; background-color: #BA0021; transition: width 0.5s;">LAA {prob_laa}% ({ml_laa})</div>
        <div style="width: {prob_lad}%; background-color: #005A9C; transition: width 0.5s;">LAD {prob_lad}% ({ml_lad})</div>
    </div>
    """, unsafe_allow_html=True)
    
    msg = "💡 **AI 魔球演算模型**：納入打線、先發(權重2.5倍)、與球隊連勝動能。"
    if is_laa_opener or is_lad_opener: msg += " ⚠️ **偵測到牛棚代班先發 (平均<3局)，勝率已調降。**"
    st.caption(msg)

    st.markdown("---")
    
    if st.button("🎙️ 產生賽前深度戰報 (含數據排名與推演)", type="primary", use_container_width=True):
        if 'save_settings' in globals(): save_settings()
        
        with st.spinner("AI 球評正在運算高階 Sabermetrics 數據與排名..."):
            time.sleep(1.5)
            df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
            
            def get_team_streak_str(team_name):
                if df_p_full.empty: return "尚無賽事"
                t_df = df_p_full[df_p_full['球隊'] == team_name].sort_values(by='時間戳記', ascending=True)
                results = []
                for stage, group in t_df.groupby('賽事階段'):
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

            # ✨ 修正牛棚 ERA 校正邏輯 (先找出每場局數最多的人當先發，其餘全算牛棚)
            def get_bullpen_era(team_name):
                if df_p_full.empty: return None
                prefix = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
                sub_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_full
                t_df = sub_df[sub_df['球隊'] == team_name]
                if t_df.empty: return None
                
                bp_outs, bp_er = 0, 0
                for stage, group in t_df.groupby('賽事階段'):
                    group_copy = group.copy()
                    group_copy['局數_num'] = pd.to_numeric(group_copy['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(group_copy['局數(出局數)'], errors='coerce').fillna(0)
                    if group_copy['局數_num'].sum() > 0:
                        group_copy = group_copy.sort_values(by='局數_num', ascending=False)
                        bp_group = group_copy.iloc[1:] # 扣掉第一名(先發)，其餘都是牛棚
                        bp_outs += bp_group['局數_num'].sum()
                        bp_er += pd.to_numeric(bp_group['自責分'], errors='coerce').fillna(0).sum()
                
                bp_ip = bp_outs / 3.0
                return (bp_er * 9) / bp_ip if bp_ip > 0 else 0.0

            st.markdown(f"## 📰 【{wr_season}】 賽前魔球戰報")
            
            st.markdown("### 🏟️ 球隊近況與牛棚防線")
            def generate_team_momentum(team):
                streak = get_team_streak_str(team)
                bp_era = get_bullpen_era(team)
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
            def get_pitcher_insights(team, sp, stats_dict, prev_dict):
                team_stats = stats_dict.get(team, {})
                prev_team_stats = prev_dict.get(team, {})
                if sp not in team_stats: return ""
                s = team_stats[sp]
                era, fip = s['ERA'], s['FIP']
                
                all_eras = sorted(list(set([val['ERA'] for t, plrs in stats_dict.items() for p, val in plrs.items()])))
                rank = all_eras.index(era) + 1 if era in all_eras else "-"
                
                p_era = prev_team_stats.get(sp, {}).get('ERA', era)
                trend = f"(去年 ERA {p_era:.2f})" if p_era != era else ""
                
                insight = f"**【{team} 先發】 {sp}**\n- **數據**：ERA **{era:.2f} (聯盟第 {rank})** {trend} | eWAR **{s['eWAR']:.1f}**\n- **壓制力**：WHIP **{s['WHIP']:.2f}** | K/9 **{s['K/9']:.2f}**\n"
                fip_diff = fip - era
                
                if era >= 6.0 and fip >= 6.0: insight += f"- 🚨 **發球機警報 (狀況慘烈)**：無論是防禦率 ({era:.2f}) 還是 FIP ({fip:.2f}) 都突破天際的高。他目前在丘上幾乎沒有解決打者的能力，今晚隨時會被打退場。\n\n"
                elif era <= 2.5 and fip <= 2.5: insight += f"- 👑 **鬼神級王牌 (真材實料)**：防禦率 {era:.2f} 已經很可怕，沒想到進階數據 FIP 更是只有 {fip:.2f}！這代表他連隊友失誤都自己三振解決，今晚對手只能自求多福。\n\n"
                elif fip_diff < -0.5:
                    if era > 3.5: insight += random.choice([f"- 💡 **悲情王牌 (被守備雷到)**：帳面 ERA 看似平凡，但 FIP 僅 {fip:.2f}！這說明他投得極好，失分多半是非戰之罪。\n\n", f"- 📉 **進階數據平反**：別被他 {era:.2f} 的防禦率騙了，他的 FIP 只有 {fip:.2f}，代表他的投球內容相當優異。\n\n"])
                    else: insight += f"- 🛡️ **深不見底的壓制力**：防禦率 {era:.2f} 已經夠水準了，沒想到 FIP ({fip:.2f}) 還能更低！這代表他把命運完全掌握在自己手中。\n\n"
                elif fip_diff > 0.5:
                    if era < 3.5: insight += random.choice([f"- 🚨 **強運校正警報**：防禦率 {era:.2f} 看似無懈可擊，但 FIP 卻高達 {fip:.2f}。這代表他很大程度是靠著完美的守備與運氣在撐，隨時有核爆風險。\n\n", f"- ⚠️ **虛假繁榮 (海市蜃樓)**：雖然 ERA 只有 {era:.2f}，但進階數據 FIP 殘酷地指出他的真實壓制力並不理想。\n\n"])
                    else: insight += f"- 💣 **雪上加霜**：防禦率已經不理想，FIP ({fip:.2f}) 更是慘烈。這意味著他過度依賴守備，今晚狀況十分堪憂。\n\n"
                else:
                    insight += random.choice([f"- ⚖️ **真金不怕火煉**：他的 FIP ({fip:.2f}) 與 ERA 極為吻合，表現十分穩定，帳面成績就是真實硬實力。\n\n", f"- 🎯 **童叟無欺**：防禦率與 FIP 高度一致，代表他完全掌握了自己的投球節奏。\n\n"])
                return insight
                
            p_rep = ""
            if laa_sp != "未指定": p_rep += get_pitcher_insights("LAA", laa_sp, curr_p_stats, prev_p_stats)
            if lad_sp != "未指定": p_rep += get_pitcher_insights("LAD", lad_sp, curr_p_stats, prev_p_stats)
            if p_rep: st.success(p_rep)

            st.markdown("### 💥 打線雷達掃描與教練點評")
            def get_lineup_insights(team, batters, stats_dict):
                team_stats = stats_dict.get(team, {})
                valid_b = [b for b in batters if b in team_stats]
                if not valid_b: return ""
                insights = [f"**【{team} 打線掃描】**"]
                best_b = max(valid_b, key=lambda x: team_stats[x]['OPS+'])
                best_ops = team_stats[best_b]['OPS+']
                
                all_ops = sorted(list(set([v['OPS+'] for t, plrs in stats_dict.items() for p, v in plrs.items()])), reverse=True)
                rank = all_ops.index(best_ops) + 1 if best_ops in all_ops else "-"
                
                insights.append(random.choice([
                    f"- 🔥 **進攻中樞**：**{best_b}** (OPS+ **{best_ops:.0f}，聯盟第 {rank}**) 是全隊火力最旺盛的打者，絕對是頭號目標。",
                    f"- 👑 **打線大魔王**：狀態絕佳的 **{best_b}** (OPS+ **{best_ops:.0f}，聯盟第 {rank}**) 扛起進攻大旗，投手面對他絕對不能失投。"
                ]))
                
                high_k = [b for b in valid_b if team_stats[b]['K%'] >= 25.0]
                if high_k: insights.append(f"- 🌪️ **揮空隱憂**：**{', '.join(high_k)}** (K% ≥ 25%) 極容易被引誘球騙到出局。")
                high_bb = [b for b in valid_b if team_stats[b]['BB%'] >= 15.0]
                if high_bb: insights.append(f"- 🦅 **選球大師**：**{', '.join(high_bb)}** 具備極佳的上壘紀律，能有效消耗投手球數。")
                high_iso = [b for b in valid_b if team_stats[b]['ISO'] >= 0.250 and b != best_b]
                if high_iso: insights.append(f"- 🌋 **長打威脅**：千萬別輕忽 **{high_iso[0]}**！純長打率高達 {team_stats[high_iso[0]]['ISO']:.3f}，具備一擊逆轉的能力。")
                
                for i, b in enumerate(batters):
                    if b not in team_stats: continue
                    ops, order = team_stats[b]['OPS+'], i + 1
                    if order <= 4 and ops < 85:
                        insights.append(f"- 🤨 **總教練的謎之信任**：近況低迷的 **{b}** 竟然打第 {order} 棒，這絕對是進攻斷點。")
                    elif order >= 7 and ops >= 120:
                        insights.append(f"- 🥷 **恐怖的後段伏兵**：**{b}** 埋伏在第 {order} 棒，這打線深不見底！")
                return "\n".join(insights) + "\n\n"
                
            b_rep = ""
            if laa_batters: b_rep += get_lineup_insights("LAA", laa_batters, curr_b_stats)
            if lad_batters: b_rep += get_lineup_insights("LAD", lad_batters, curr_b_stats)
            if b_rep: st.warning(b_rep)

            st.markdown("### 🧠 數據總結推演")
            tactics = []
            if prob_laa > 65: tactics.append(f"數據顯示 LAA 擁有壓倒性優勢，除非先發投手提早核爆，否則 LAA 勝券在握。")
            elif prob_lad > 65: tactics.append(f"LAD 在戰力天秤上占據制高點，今晚的觀戰重點在於 LAA 能否利用牛棚漏洞進行反擊。")
            if (get_bullpen_era("LAA") or 0) > 5.5 and (get_bullpen_era("LAD") or 0) > 5.5:
                tactics.append("今晚兩隊牛棚都有『放火』基因，這場比賽在第七局之後才是真正的開始，心臟不好的觀眾請準備好藥品。")
            if laa_sp != "未指定" and lad_sp != "未指定":
                if curr_p_stats.get('LAA', {}).get(laa_sp,{'ERA':0})['ERA'] < 2.5 and curr_p_stats.get('LAD', {}).get(lad_sp,{'ERA':0})['ERA'] < 2.5:
                    tactics.append("罕見的王牌大賽！得分可能像擠牙膏一樣困難，一分定勝負的機率極高。")
            if not tactics: tactics.append("雙方戰力極其接近，預期勝率幾乎是五五開，守備的細節將決定最後的贏家。")
            tactics.append(f"目前的預測氣氛：{'熱血沸騰' if abs(prob_laa-50) < 10 else '一面倒的屠殺？'}。")
            st.error(f"🎙️ **AI 魔球推演：** {random.choice(tactics)}")

# ==========================================
# --- 分頁 5：🎖️ 聯盟大獎預測 (二刀流制霸版) ---
# ==========================================
with tab5:
    st.header("🎖️ 全美棒球記者協會 (BBWAA) 年度大獎開票所")
    st.write(f"⚠️ **例行賽大獎門檻**：打者需滿 **{QUALIFY_PA} 打席**，投手需滿 **{QUALIFY_IP} 局**。")
    st.write(f"⚠️ **世界大賽(FMVP)門檻**：打者滿 **3 打席**，投手滿 **1.0 局** 即可角逐。(👑 限定冠軍隊伍球員)")
    
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
            s_num = target_season.split(" ")[1]
            prefix = f"[S{s_num}]"
            
            def extract_stats(stage_keyword, min_pa, min_ip):
                df_b_sub = df_b_raw[(df_b_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)) & (df_b_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))] if not df_b_raw.empty else pd.DataFrame()
                df_p_sub = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains(stage_keyword, regex=False))] if not df_p_raw.empty else pd.DataFrame()
                
                cand_b, cand_p = {}, {}
                
                if not df_b_sub.empty:
                    total_pa = df_b_sub['打席'].sum()
                    lg_obp = (df_b_sub['安打'].sum() + df_b_sub['四壞球'].sum()) / total_pa if total_pa > 0 else 0
                    lg_slg = ((df_b_sub['安打'].sum() - df_b_sub['二壘安打'].sum() - df_b_sub['三壘安打'].sum() - df_b_sub['全壘打'].sum()) + 2*df_b_sub['二壘安打'].sum() + 3*df_b_sub['三壘安打'].sum() + 4*df_b_sub['全壘打'].sum()) / df_b_sub['打數'].sum() if df_b_sub['打數'].sum() > 0 else 0
                    
                    df_b_agg = df_b_sub.groupby(['球隊', '球員姓名']).sum().reset_index()
                    for _, row in df_b_agg.iterrows():
                        if row['打席'] < min_pa: continue 
                        avg = row['安打'] / max(1, row['打數'])
                        obp = (row['安打'] + row['四壞球']) / max(1, row['打席'])
                        slg = ((row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']) + 2*row['二壘安打'] + 3*row['三壘安打'] + 4*row['全壘打']) / max(1, row['打數'])
                        ops_p = 100 * ((obp / lg_obp) + (slg / lg_slg) - 1) if lg_obp > 0 and lg_slg > 0 else 0
                        ewar = ((ops_p - 80) / 100) * (row['打席'] / 20)
                        cand_b[f"[{row['球隊']}] {row['球員姓名']}"] = {'類型': '打者', 'HR': row['全壘打'], 'RBI': row['打點'], 'AVG': avg, 'OPS+': ops_p, 'eWAR': ewar}

                if not df_p_sub.empty:
                    df_p_agg = df_p_sub.groupby(['球隊', '投手姓名']).sum().reset_index()
                    counts = df_p_sub.groupby(['球隊', '投手姓名', '勝敗']).size().unstack(fill_value=0).reset_index()
                    if '勝' not in counts.columns: counts['勝'] = 0
                    if '救援' not in counts.columns: counts['救援'] = 0
                    df_p_agg = pd.merge(df_p_agg, counts, on=['球隊', '投手姓名'], how='left')
                    
                    for _, row in df_p_agg.iterrows():
                        ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                        if ip_calc < min_ip: continue 
                        era = (row['自責分'] * 9) / max(1, ip_calc)
                        fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10
                        tra = (era + fip) / 2.0
                        ewar = ((5.00 - tra) / 1.5) * (ip_calc / 10)
                        
                        name = f"[{row['球隊']}] {row['投手姓名']}"
                        # ✨ 二刀流邏輯合併
                        if name in cand_b: 
                            cand_b[name]['類型'] = '二刀流'
                            cand_b[name]['eWAR'] += ewar 
                            cand_b[name]['W'] = row.get('勝', 0)
                            cand_b[name]['SV'] = row.get('救援', 0)
                            cand_b[name]['ERA'] = era
                            cand_b[name]['K'] = row.get('奪三振', 0)
                            cand_b[name]['FIP'] = fip
                        else:
                            cand_p[name] = {'類型': '投手', 'W': row['勝'], 'SV': row['救援'], 'ERA': era, 'FIP': fip, 'K': row['奪三振'], 'eWAR': ewar}
                
                all_cand = {**cand_b, **cand_p}
                leaders = {
                    'HR': max([s.get('HR', 0) for s in all_cand.values()] + [0]),
                    'RBI': max([s.get('RBI', 0) for s in all_cand.values()] + [0]),
                    'W': max([s.get('W', 0) for s in all_cand.values()] + [0]),
                    'K': max([s.get('K', 0) for s in all_cand.values()] + [0])
                }
                return all_cand, leaders

            def simulate_voting(candidates, leaders, target_award, winner_team=None):
                if not candidates: return pd.DataFrame()
                results = {name: {'1st': 0, '2nd': 0, '3rd': 0, 'Points': 0} for name in candidates}
                voter_types = ['Traditional']*12 + ['Sabermetric']*10 + ['Balanced']*8
                
                max_hr, max_rbi, max_w, max_k = leaders['HR'], leaders['RBI'], leaders['W'], leaders['K']
                
                for voter in voter_types:
                    scores = {}
                    for name, stats in candidates.items():
                        score = 0
                        leader_bonus = 0
                        if target_award != "FMVP": 
                            if stats.get('HR', 0) == max_hr and max_hr > 0: leader_bonus += 50
                            if stats.get('RBI', 0) == max_rbi and max_rbi > 0: leader_bonus += 30
                            if stats.get('W', 0) == max_w and max_w > 0: leader_bonus += 50
                        
                        if target_award == "MVP":
                            if voter == 'Traditional':
                                if stats['類型'] in ['打者', '二刀流']:
                                    score += stats.get('HR', 0) * 20 + stats.get('RBI', 0) * 10 + leader_bonus * 1.5 
                                    if stats.get('AVG', 0) > 0.300: score += 20
                                    elif stats.get('AVG', 0) < 0.250: score -= 30
                                if stats['類型'] in ['投手', '二刀流']:
                                    score += stats.get('W', 0) * 25 + stats.get('SV', 0) * 10 - stats.get('ERA', 5) * 5 + leader_bonus * 1.5
                            elif voter == 'Sabermetric':
                                score += stats.get('eWAR', 0) * 80 + leader_bonus * 0.5 
                            else:
                                score += stats.get('eWAR', 0) * 40 + stats.get('HR', 0) * 12 + stats.get('W', 0) * 15 + leader_bonus
                        
                        elif target_award == "CyYoung":
                            if stats['類型'] == '打者': continue
                            if stats.get('ERA', 5) > 5.00: score -= 500 
                            if voter == 'Traditional':
                                score += stats.get('W', 0) * 20 + stats.get('SV', 0) * 15 - stats.get('ERA', 5) * 20 + leader_bonus
                            else:
                                score += stats.get('eWAR', 0) * 50 - stats.get('FIP', 5) * 15 - stats.get('ERA', 5) * 10
                        
                        elif target_award == "SilverSlugger":
                            if stats['類型'] == '投手': continue
                            if voter == 'Traditional': score += stats.get('HR', 0) * 25 + stats.get('AVG', 0) * 100 + leader_bonus
                            else: score += stats.get('eWAR', 0) * 20 + stats.get('OPS+', 0) * 2
                        
                        elif target_award == "FMVP":
                            if winner_team and f"[{winner_team}]" not in name:
                                score -= 1000
                                
                            if stats['類型'] in ['打者', '二刀流']:
                                score += stats.get('HR', 0) * 40 + stats.get('RBI', 0) * 20 + stats.get('OPS+', 0) * 0.5
                            if stats['類型'] in ['投手', '二刀流']:
                                score += stats.get('W', 0) * 35 + stats.get('SV', 0) * 25 - stats.get('ERA', 5) * 15
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
                    cand_reg, lead_reg = extract_stats("例行賽", QUALIFY_PA, QUALIFY_IP)
                    
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
                    
                    if not df_p_raw.empty:
                        reliever_df = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(prefix)) & 
                                              (df_p_raw['勝敗'].isin(['中繼', '救援', '無']))]
                        if not reliever_df.empty:
                            appearances = reliever_df.groupby(['球隊', '投手姓名']).size().reset_index(name='出賽數')
                            max_app = appearances['出賽數'].max()
                            top_relievers = appearances[appearances['出賽數'] == max_app]
                            r_names = " / ".join([f"[{r['球隊']}] {r['投手姓名']}" for _, r in top_relievers.iterrows()])
                            c_fun1, _ = st.columns([1, 1])
                            c_fun1.metric("🏥 鐵人後援王", f"{max_app} 場", r_names, help="整季牛棚出賽次數最多的投手，教練最愛操的勞碌命。")

                    if not df_b_raw.empty:
                        bbk_df = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(prefix)].groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
                        bbk_df = bbk_df[bbk_df['打席'] >= QUALIFY_PA]
                        if not bbk_df.empty:
                            bbk_df['BBK'] = bbk_df['四壞球'] / bbk_df['三振'].replace(0, 0.5)
                            max_bbk = bbk_df['BBK'].max()
                            top_eye = bbk_df[bbk_df['BBK'] == max_bbk].iloc[0]
                            st.write("") 
                            st.metric("🦅 聯盟神之眼", f"{max_bbk:.2f} BB/K", f"[{top_eye['球隊']}] {top_eye['球員姓名']}", help="保送三振比最高，投手最不想面對的纏鬥達人。")

            if btn_ws:
                with st.spinner("30 位 AI 記者正在查閱世界大賽戰報..."):
                    time.sleep(1.5)
                    cand_ws, lead_ws = extract_stats("世界大賽", 3.0, 1.0) 
                    
                    ws_winner = None
                    laa_wins = 0
                    lad_wins = 0
                    
                    if not df_p_raw.empty:
                        df_p_ws = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains("世界大賽", regex=False))]
                        
                        def get_ws_wins(team_name):
                            t_ws = df_p_ws[df_p_ws['球隊'] == team_name]
                            w = 0
                            for stage, group in t_ws.groupby('賽事階段'):
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