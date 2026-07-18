# ==========================================
# 1. 核心套件與全域設定 (Imports & Settings)
# ==========================================
import streamlit as st
import gspread
import pandas as pd
import numpy as np
import re
from datetime import datetime
import time
import random
import json
import os
import math
import altair as alt

st.set_page_config(page_title="LAA vs LAD 數據中心", page_icon="⚾", layout="wide")

SERVICE_ACCOUNT_FILE = 'baseball.json'
SHEET_NAME = '棒球數據資料庫'
TEAMS = ["LAA", "LAD"]

POSITIONS = ["DH", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "PH", "PR"]
ROLES_P = ["SP", "RP", "CP"]

SEASONS = [f"Season {i}" for i in range(1, 11)]
GAME_STAGES = [f"例行賽 G{i}" for i in range(1, 11)] + [f"世界大賽 G{i}" for i in range(1, 8)]
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_settings():
    data = {
        "lineups": st.session_state.get("lineups", {'LAA': ["" for _ in range(9)], 'LAD': ["" for _ in range(9)]}),
        "lineup_pos": st.session_state.get("lineup_pos", {'LAA': ["DH" for _ in range(9)], 'LAD': ["DH" for _ in range(9)]}),
        "pitchers": st.session_state.get("pitchers", {'LAA': "", 'LAD': ""}),
        "default_season": st.session_state.get("f_season", "十年總成績"),
        "f_game_pref": st.session_state.get("f_game_pref", "看整季"),
        "completed_games": st.session_state.get("completed_games", []),
        "rotation_plan": st.session_state.get("rotation_plan", {})
    }
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

saved_data = load_settings()
if "completed_games" not in st.session_state: st.session_state.completed_games = saved_data.get("completed_games", [])
if "rotation_plan" not in st.session_state: st.session_state.rotation_plan = saved_data.get("rotation_plan", {})
if "pitchers" not in st.session_state: st.session_state.pitchers = saved_data.get("pitchers", {'LAA': "", 'LAD': ""})
if "lineups" not in st.session_state: st.session_state.lineups = saved_data.get("lineups", {'LAA': ["" for _ in range(9)], 'LAD': ["" for _ in range(9)]})
if "lineup_pos" not in st.session_state: st.session_state.lineup_pos = saved_data.get("lineup_pos", {'LAA': ["DH" for _ in range(9)], 'LAD': ["DH" for _ in range(9)]})

@st.cache_resource
def get_sheet():
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return gc.open(SHEET_NAME)

@st.cache_data(ttl=600)
def get_raw_records(worksheet_name):
    try:
        sh = get_sheet()
        ws = sh.worksheet(worksheet_name)
        return ws.get_all_values()
    except Exception as e:
        return []

@st.cache_data(ttl=600)
def get_player_list(worksheet_name):
    records = get_raw_records(worksheet_name)
    if not records or len(records) <= 1: return {'LAA': [], 'LAD': []}
    df = pd.DataFrame(records[1:], columns=records[0])
    name_col = '球員姓名' if '球員姓名' in df.columns else '投手姓名'
    team_col = '球隊'
    players = {'LAA': [], 'LAD': []}
    for team in TEAMS:
        if team_col in df.columns and name_col in df.columns:
            players[team] = [p for p in df[df[team_col] == team][name_col].dropna().unique().tolist() if p.strip()]
    return players

def get_career_stats():
    if 'cache_cleared_vfinal' not in st.session_state:
        st.cache_data.clear()
        st.session_state.cache_cleared_vfinal = True
        
    df_b = get_raw_records("打擊單場紀錄")
    df_p = get_raw_records("投手單場紀錄")
    
    # 徹底清除全半形空白與隱藏字元，保護資料對接
    db = pd.DataFrame(df_b[1:], columns=[re.sub(r'\s+', '', str(h)) for h in df_b[0]]) if df_b and len(df_b) > 1 else pd.DataFrame()
    dp = pd.DataFrame(df_p[1:], columns=[re.sub(r'\s+', '', str(h)) for h in df_p[0]]) if df_p and len(df_p) > 1 else pd.DataFrame()

    if not dp.empty and '勝敗' not in dp.columns:
        for col in dp.columns:
            if '勝' in col or '結果' in col: dp.rename(columns={col: '勝敗'}, inplace=True); break
    if not db.empty and '四壞球' not in db.columns:
        for col in db.columns:
            if '四壞' in col or '保送' in col: db.rename(columns={col: '四壞球'}, inplace=True); break
    if not dp.empty and '四壞球' not in dp.columns:
        for col in dp.columns:
            if '四壞' in col or '保送' in col: dp.rename(columns={col: '四壞球'}, inplace=True); break

    st.session_state.df_b_raw = db
    st.session_state.df_p_raw = dp


# ==========================================
# 2. ✨ 全域大聯盟進階數據統一引擎 (Unified Sabermetrics Engine)
# ==========================================
def global_calc_ops_plus(obp, slg, lg_obp, lg_slg):
    lg_obp = max(0.001, lg_obp)
    lg_slg = max(0.001, lg_slg)
    return 100 * ((obp / lg_obp) + (slg / lg_slg) - 1)

def global_calc_wrc_plus(woba, lg_woba):
    lg_woba = max(0.001, lg_woba)
    # ✨ 動態校正：微型聯盟的得分環境極端，捨棄大聯盟死板的 0.115 (R/PA) 參數
    # 改採動態比例常態化公式，能出現負數，且完美將極端值收斂在 -100 ~ 250 的合理區間！
    wrc_plus = ((woba / lg_woba) - 1) * 200 + 100
    return wrc_plus

def global_calc_batter_ewar(wrc_plus, pos, pa):
    pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
    adj = pos_adj_dict.get(pos, -0.12)
    e_war = (((wrc_plus - 70) / 80) + adj) * (pa / 15)
    return 0.0 if abs(e_war) < 0.05 else round(e_war, 1)

def global_calc_pitcher_ewar(era, fip, ip, lg_era, season_idx):
    if ip == 0: return 0.0
    if season_idx >= 6: tra = (era * 0.3) + (fip * 0.7) 
    else: tra = (era + fip) / 2.0
    
    # ✨ 導入真實替補水準 (Replacement Level) 校正
    # 打者平均是 100，替補是 70 (差 30%)
    # 投手現在改為減去替補水準防禦率 (平均 ERA * 1.30)，徹底拉平投打 WAR 基準點！
    rep_level = lg_era * 1.30
    era_div = max(1.5, lg_era * 0.2)
    
    e_war = ((rep_level - tra) / era_div) * (ip / 10)
    return 0.0 if abs(e_war) < 0.05 else round(e_war, 1)

def global_pitcher_cy_young_points(ip, er, so, w, sv, season_idx):
    if season_idx >= 6: return (ip / 2.0) - (er * 2.0) + (so / 10.0) + (w * 2.0) + (sv * 1.5)
    return 0.0

def global_game_mvp_score_b(ab, h, h2, h3, hr, rbi, run, bb, so, season_idx):
    tb = (h - h2 - h3 - hr) + 2*h2 + 3*h3 + 4*hr
    if season_idx >= 6: return tb*1.5 + rbi*2.0 + run*1.0 + bb*1.0 - so*1.0
    return tb*1.5 + rbi*2.0 + run*1.0 + bb*1.0 - so*0.5

def global_game_mvp_score_p(ip, er, h, bb, so, w, sv, hld, season_idx):
    if season_idx >= 6:
        outs = ip * 3
        return 40 + (outs * 2.0) + (so * 1.5) - (h * 1.0) - (bb * 1.0) - (er * 2.0) + (w * 4.0) + (sv * 4.0) + (hld * 2.0)
    return ip*3.0 - er*3.0 - h*1.0 - bb*1.0 + so*1.0 + w*6.0 + sv*5.0 + hld*3.0

def generate_initials(name):
    clean_name = str(name).replace('.', ' ').replace('-', ' ')
    parts = clean_name.split()
    if len(parts) >= 2: return (parts[0][0] + parts[-1][0]).upper()
    return str(name)[:2].upper()
# ==========================================
# 2.5 🌐 全域主客場動態推演矩陣 (Global Home/Away Engine)
# ==========================================
get_career_stats()
df_b_full_global = st.session_state.get('df_b_raw', pd.DataFrame())
df_p_full_global = st.session_state.get('df_p_raw', pd.DataFrame())

if '賽事階段' not in df_b_full_global.columns: df_b_full_global['賽事階段'] = ""
if '賽事階段' not in df_p_full_global.columns: df_p_full_global['賽事階段'] = ""

df_b_global_clean = df_b_full_global.copy()
if not df_b_global_clean.empty:
    for c in ['得分']: 
        if c in df_b_global_clean.columns: df_b_global_clean[c] = pd.to_numeric(df_b_global_clean[c], errors='coerce').fillna(0)
df_p_global_clean = df_p_full_global.copy()
if not df_p_global_clean.empty:
    df_p_global_clean['勝'] = df_p_global_clean['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
    for c in ['失分']: 
        if c in df_p_global_clean.columns: df_p_global_clean[c] = pd.to_numeric(df_p_global_clean[c], errors='coerce').fillna(0)

global_home_dict = {}

for s in range(1, 12):
    # 1. 決定例行賽主場優勢 (RS HFA：上季亞軍先 G1，所以輸家拿 RS HFA)
    rs_hfa = "LAD" # Season 1 依照指示：LAD 先擔任 G1 主場
    if s > 1:
        p_prev_ws = df_p_global_clean[df_p_global_clean['賽事階段'].astype(str).str.contains(f"[S{s-1}] 世界大賽", regex=False)]
        laa_prev_ws_w, lad_prev_ws_w = 0, 0
        if not p_prev_ws.empty:
            for stage, group in p_prev_ws.groupby('賽事階段'):
                if group[group['球隊']=='LAA']['勝'].sum() > 0: laa_prev_ws_w += 1
                if group[group['球隊']=='LAD']['勝'].sum() > 0: lad_prev_ws_w += 1
        
        if laa_prev_ws_w >= 4 or lad_prev_ws_w >= 4:
            rs_hfa = "LAD" if laa_prev_ws_w >= 4 else "LAA"
        else:
            p_prev_rs = df_p_global_clean[df_p_global_clean['賽事階段'].astype(str).str.contains(f"[S{s-1}] 例行賽", regex=False)]
            laa_prev_rs_w, lad_prev_rs_w = 0, 0
            if not p_prev_rs.empty:
                for stage, group in p_prev_rs.groupby('賽事階段'):
                    if group[group['球隊']=='LAA']['勝'].sum() > 0: laa_prev_rs_w += 1
                    if group[group['球隊']=='LAD']['勝'].sum() > 0: lad_prev_rs_w += 1
            
            if laa_prev_rs_w > lad_prev_rs_w: rs_hfa = "LAD" 
            elif lad_prev_rs_w > laa_prev_rs_w: rs_hfa = "LAA"
            else:
                b_prev_rs = df_b_global_clean[df_b_global_clean['賽事階段'].astype(str).str.contains(f"[S{s-1}] 例行賽", regex=False)]
                laa_rd, lad_rd = 0, 0
                if not p_prev_rs.empty and not b_prev_rs.empty:
                    laa_rd = b_prev_rs[b_prev_rs['球隊']=='LAA']['得分'].sum() - p_prev_rs[p_prev_rs['球隊']=='LAA']['失分'].sum()
                    lad_rd = b_prev_rs[b_prev_rs['球隊']=='LAD']['得分'].sum() - p_prev_rs[p_prev_rs['球隊']=='LAD']['失分'].sum()
                rs_hfa = "LAD" if laa_rd > lad_rd else "LAA" 

    for g in range(1, 13):
        h_tm = rs_hfa if g % 2 == 1 else ("LAD" if rs_hfa == "LAA" else "LAA")
        global_home_dict[f"[S{s}] 例行賽 G{g}"] = h_tm
        global_home_dict[f"[S{s}] 例行賽 第{g}場"] = h_tm

    # 2. 決定世界大賽主場優勢 (WS HFA：今年例行賽冠軍拿 G1，平手比得失分差)
    c_rs_p = df_p_global_clean[df_p_global_clean['賽事階段'].astype(str).str.contains(f"[S{s}] 例行賽", regex=False)]
    c_rs_b = df_b_global_clean[df_b_global_clean['賽事階段'].astype(str).str.contains(f"[S{s}] 例行賽", regex=False)]
    
    laa_curr_w, lad_curr_w = 0, 0
    if not c_rs_p.empty:
        for stage, group in c_rs_p.groupby('賽事階段'):
            if group[group['球隊']=='LAA']['勝'].sum() > 0: laa_curr_w += 1
            if group[group['球隊']=='LAD']['勝'].sum() > 0: lad_curr_w += 1
            
    ws_hfa = "LAA"
    if laa_curr_w > lad_curr_w: ws_hfa = "LAA"
    elif lad_curr_w > laa_curr_w: ws_hfa = "LAD"
    else:
        laa_rd, lad_rd = 0, 0
        if not c_rs_p.empty and not c_rs_b.empty:
            laa_rd = c_rs_b[c_rs_b['球隊']=='LAA']['得分'].sum() - c_rs_p[c_rs_p['球隊']=='LAA']['失分'].sum()
            lad_rd = c_rs_b[c_rs_b['球隊']=='LAD']['得分'].sum() - c_rs_p[c_rs_p['球隊']=='LAD']['失分'].sum()
        ws_hfa = "LAA" if laa_rd >= lad_rd else "LAD" 
        
    for g in range(1, 8):
        h_tm = ws_hfa if g in [1, 2, 6, 7] else ("LAD" if ws_hfa == "LAA" else "LAA")
        global_home_dict[f"[S{s}] 世界大賽 G{g}"] = h_tm
        global_home_dict[f"[S{s}] 世界大賽 第{g}場"] = h_tm

manual_home_correction = {
    "[S6] 世界大賽 G1": "LAD", "[S6] 世界大賽 G2": "LAD", "[S6] 世界大賽 G3": "LAA",
    "[S6] 世界大賽 G4": "LAA", "[S6] 世界大賽 G5": "LAA", "[S6] 世界大賽 G6": "LAD", "[S6] 世界大賽 G7": "LAD",
}
global_home_dict.update(manual_home_correction)
st.session_state['global_home_dict'] = global_home_dict

# ==========================================
# 3. 🏆 全域年度大獎與快取結算中心 (時空隔離引擎)
# ==========================================
get_career_stats()
df_b_full = st.session_state.get('df_b_raw', pd.DataFrame())
df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())

# 🩹 補丁：覆蓋全域的單場 MVP 演算法 (專為 3 局制特化，強制拉平投打分數天花板)
def global_game_mvp_score_b(ab, h, h2, h3, hr, rbi, run, bb, so, s_idx=1):
    try:
        h1 = h - h2 - h3 - hr
        score = (hr * 25) + (h3 * 15) + (h2 * 10) + (h1 * 6)
        score += (rbi * 12) + (run * 8) + (bb * 5) - (so * 3)
        return score
    except: return 0

def global_game_mvp_score_p(ip, er, h_allowed, bb_allowed, k, w, sv, hld, s_idx=1):
    try:
        score = (ip * 10) + (k * 4) + (w * 15) + (sv * 15) + (hld * 10)
        score -= (er * 15) + (h_allowed * 3) + (bb_allowed * 3)
        return score
    except: return 0

# 🛡️ 確保空資料庫仍有標準欄位
required_b = ['賽事階段', '球隊', '得分', '安打', '棒次', '時間戳記', '守位', '球員姓名', '打數', '打點', '四壞球', '三振', '全壘打', '二壘安打', '三壘安打', '盜壘', '打席']
for c in required_b:
    if c not in df_b_full.columns: df_b_full[c] = "0"
required_p = ['賽事階段', '球隊', '勝敗', '時間戳記', '投手姓名', '角色', '局數(整數)', '局數(出局數)', '被安打', '失分', '自責分', '四壞球', '奪三振', '被全壘打', '投球數']
for c in required_p:
    if c not in df_p_full.columns: df_p_full[c] = "無" if c == '勝敗' else "0"

max_season = 1
if not df_b_full.empty:
    b_seasons = df_b_full['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]')[0].dropna().astype(int)
    if not b_seasons.empty: max_season = max(max_season, b_seasons.max())
if not df_p_full.empty:
    p_seasons = df_p_full['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]')[0].dropna().astype(int)
    if not p_seasons.empty: max_season = max(max_season, p_seasons.max())

# 🔥 核心修正：此處已徹底移除會洗掉全域主客場字典的「 global_home_dict = {} 」叛徒區塊，完美傳承 2.5 矩陣！

# ⏳ 歷史原生演算法 (Legacy Function - S1~S5 舊制時空膠囊) 
def get_hist_awards_legacy(s_idx, df_b_full, df_p_full):
    s_prefix = f"[S{s_idx}]"
    df_b_rs = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains("例行賽", regex=False))].copy()
    df_p_rs = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains("例行賽", regex=False))].copy()
    df_b_ws = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].copy()
    df_p_ws = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains("世界大賽", regex=False))].copy()
    
    rs_games_played = df_p_rs['賽事階段'].nunique() if not df_p_rs.empty else 0
    is_rs_finished = (rs_games_played >= 10)
    
    ws_winner_team = None
    if not df_p_ws.empty:
        laa_w = sum(1 for _, g in df_p_ws.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAA']['勝敗'].values))
        lad_w = sum(1 for _, g in df_p_ws.groupby('賽事階段', sort=False) if any('勝' in str(x) for x in g[g['球隊']=='LAD']['勝敗'].values))
        if laa_w >= 4: ws_winner_team = "LAA"
        elif lad_w >= 4: ws_winner_team = "LAD"
    is_ws_finished = (ws_winner_team is not None)
    
    pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
    
    def extract_and_vote(b_sub, p_sub, is_ws=False, ws_winner=None, rookie_set=None):
        if b_sub.empty and p_sub.empty: 
            if is_ws: return ("無", pd.DataFrame())
            else: return ("無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), {}, [])
            
        team_games = b_sub['賽事階段'].nunique() if not b_sub.empty else 1
        min_pa = 3.0 if is_ws else max(1.0, team_games * 1.0) 
        min_ip = 1.0 if is_ws else max(0.1, team_games * 0.33)
        
        cand = {}
        if not b_sub.empty:
            for col in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振']: 
                if col not in b_sub.columns: b_sub[col] = 0
                b_sub[col] = pd.to_numeric(b_sub[col], errors='coerce').fillna(0)
            t_pa = b_sub['打席'].sum()
            lg_1b = b_sub['安打'].sum() - b_sub['二壘安打'].sum() - b_sub['三壘安打'].sum() - b_sub['全壘打'].sum()
            lg_woba = (0.69*b_sub['四壞球'].sum() + 0.88*lg_1b + 1.25*b_sub['二壘安打'].sum() + 1.59*b_sub['三壘安打'].sum() + 2.06*b_sub['全壘打'].sum()) / t_pa if t_pa > 0 else 0.001
            
            b_agg = b_sub.groupby(['球隊', '球員姓名']).agg({'打席':'sum','打數':'sum','安打':'sum','二壘安打':'sum','三壘安打':'sum','全壘打':'sum','打點':'sum','四壞球':'sum','三振':'sum', '守位': lambda x: x.value_counts().index[0] if not x.empty else 'DH'}).reset_index()
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
                if col not in p_sub.columns: p_sub[col] = 0
                p_sub[col] = pd.to_numeric(p_sub[col], errors='coerce').fillna(0)
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
                if ip_c == 0: ewar = (-0.1*r['自責分']-0.05*r['四壞球'])
                else: ewar = ((lg_era_base-tra)/era_div)*(ip_c/10)
                
                name = f"[{r['球隊']}] {r['投手姓名']}"
                if name in cand:
                    cand[name].update({'類型':'二刀流', 'W':r['勝'], 'SV':r['救援'], 'HLD':r['中繼'], 'ERA':era, 'K_p':r['奪三振'], 'FIP':fip, 'IP':ip_c, 'Qual': (cand[name]['Qual'] or ip_c >= min_ip)})
                    cand[name]['eWAR'] += ewar
                else:
                    cand[name] = {'球隊': r['球隊'], '球員姓名': r['投手姓名'], '類型':'投手', 'W':r['勝'], 'SV':r['救援'], 'HLD':r['中繼'], 'ERA':era, 'K_p':r['奪三振'], 'FIP':fip, 'eWAR':ewar, 'IP':ip_c, 'Qual': ip_c >= min_ip}
        
        for n, v in cand.items(): 
            v['eWAR'] = 0.0 if abs(v['eWAR']) < 0.05 else round(v['eWAR'], 1)

        if not cand: 
            if is_ws: return ("無", pd.DataFrame())
            else: return ("無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), {}, [])

        qual_cands = {k: v for k, v in cand.items() if v.get('Qual', False)}
        if not qual_cands and not is_ws: 
            return "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), "無", pd.DataFrame(), cand, []

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

        if is_ws:
            return simulate_voting_local("FMVP", qual_cands)
        
        mvp, mvp_df = simulate_voting_local("MVP", qual_cands)
        cy, cy_df = simulate_voting_local("CyYoung", qual_cands)
        ss, ss_df = simulate_voting_local("SilverSlugger", qual_cands)
        roty, roty_df = "無", pd.DataFrame()
        
        if rookie_set is not None:
            rookie_cands = {k: v for k, v in qual_cands.items() if k in rookie_set}
            if rookie_cands: 
                roty, roty_df = simulate_voting_local("MVP", rookie_cands)
        
        all_mlb_winners = []
        batters = {k: v for k, v in cand.items() if v['類型'] in ['打者', '二刀流']}
        pitchers = {k: v for k, v in cand.items() if v['類型'] in ['投手', '二刀流']}
        selected_players = set()
        
        def get_best(pos_list, is_dh=False):
            cands = {k: v for k, v in batters.items() if (is_dh or v.get('Pos','DH') in pos_list) and k not in selected_players and v.get('Qual', False)}
            pos_cands = {k: v for k, v in cands.items() if v['eWAR'] > 0}
            if pos_cands:
                best_n = max(pos_cands.items(), key=lambda x: x[1]['eWAR'])[0]
                selected_players.add(best_n)
                all_mlb_winners.append(best_n)
                
        for p in [['C'], ['1B'], ['2B'], ['3B'], ['SS'], [], ['LF','CF','RF','OF'], ['LF','CF','RF','OF'], ['LF','CF','RF','OF']]: 
            get_best(p, is_dh=not p)
            
        if pitchers:
            sp_cands = {k: v for k, v in pitchers.items() if v.get('Qual', False) and v['eWAR'] > 0}
            if sp_cands: 
                all_mlb_winners.append(max(sp_cands.items(), key=lambda x: x[1]['eWAR'])[0])
            rp_cands = {k: v for k, v in pitchers.items() if (v.get('SV',0)>0 or v.get('HLD',0)>0) and v['eWAR'] > 0}
            if rp_cands: 
                all_mlb_winners.append(max(rp_cands.items(), key=lambda x: x[1]['eWAR'])[0])

        return mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, "無", pd.DataFrame(), cand, all_mlb_winners

    r_set = set()
    if s_idx == 1: 
        b_agg = df_b_rs.groupby(['球隊', '球員姓名']).size().reset_index()
        p_agg = df_p_rs.groupby(['球隊', '投手姓名']).size().reset_index()
        if not b_agg.empty: r_set.update([f"[{r['球隊']}] {r['球員姓名']}" for _, r in b_agg.iterrows()])
        if not p_agg.empty: r_set.update([f"[{r['球隊']}] {r['投手姓名']}" for _, r in p_agg.iterrows()])
    else:
        past_pa, past_ip = {}, {}
        past_regex = "|".join([f"\\[S{i}\\]" for i in range(1, s_idx)])
        past_b = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(past_regex)] if not df_b_full.empty else pd.DataFrame()
        past_p = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(past_regex)] if not df_p_full.empty else pd.DataFrame()
        
        if not past_b.empty:
            for _, r in past_b.iterrows():
                name = f"[{r['球隊']}] {r['球員姓名']}"
                pa = pd.to_numeric(r.get('打席', 0), errors='coerce')
                past_pa[name] = past_pa.get(name, 0) + (0 if pd.isna(pa) else pa)
        if not past_p.empty:
            for _, r in past_p.iterrows():
                name = f"[{r['球隊']}] {r['投手姓名']}"
                o_int = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce')
                o_dec = pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                o_int = 0 if pd.isna(o_int) else o_int
                o_dec = 0 if pd.isna(o_dec) else o_dec
                ip = (o_int * 3 + o_dec) / 3.0
                past_ip[name] = past_ip.get(name, 0.0) + ip

        curr_b = df_b_rs.groupby(['球隊', '球員姓名']).size().reset_index()
        curr_p = df_p_rs.groupby(['球隊', '投手姓名']).size().reset_index()
        curr_all = set()
        if not curr_b.empty: curr_all.update([f"[{r['球隊']}] {r['球員姓名']}" for _, r in curr_b.iterrows()])
        if not curr_p.empty: curr_all.update([f"[{r['球隊']}] {r['投手姓名']}" for _, r in curr_p.iterrows()])
        
        for p in curr_all:
            if past_pa.get(p, 0) < 6 and past_ip.get(p, 0.0) < 2.0: 
                r_set.add(p)

    mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, _, _, rs_cand, all_mlb_winners = extract_and_vote(df_b_rs, df_p_rs, False, rookie_set=r_set)
    
    if ws_winner_team: 
        fmvp, fmvp_df = extract_and_vote(df_b_ws, df_p_ws, True, ws_winner_team)
    else: 
        fmvp, fmvp_df = "無 (尚未產生冠軍)", pd.DataFrame()
        
    return mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, rs_cand, all_mlb_winners, is_rs_finished, is_ws_finished

# === 執行全局賽季快取演算 ===
season_cache = {}
for s_idx in range(1, max_season + 1):
    s_pref = f"[S{s_idx}]"
    b_s = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)] if not df_b_full.empty else pd.DataFrame(columns=required_b)
    p_s = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)] if not df_p_full.empty else pd.DataFrame(columns=required_p)
    if b_s.empty and p_s.empty: continue

    b_rs = b_s[b_s['賽事階段'].astype(str).str.contains("例行賽", regex=False)] if not b_s.empty else pd.DataFrame(columns=required_b)
    p_rs = p_s[p_s['賽事階段'].astype(str).str.contains("例行賽", regex=False)] if not p_s.empty else pd.DataFrame(columns=required_p)
    b_ws = b_s[b_s['賽事階段'].astype(str).str.contains("世界大賽", regex=False)] if not b_s.empty else pd.DataFrame(columns=required_b)
    p_ws = p_s[p_s['賽事階段'].astype(str).str.contains("世界大賽", regex=False)] if not p_s.empty else pd.DataFrame(columns=required_p)

    rs_stages = set(b_rs['賽事階段'].unique()) | set(p_rs['賽事階段'].unique())
    is_rs_fin = len(rs_stages) >= 10
    ws_stages = set(b_ws['賽事階段'].unique()) | set(p_ws['賽事階段'].unique())
    is_ws_fin = len(ws_stages) >= 4

    if s_idx < 6:
        mvp_w, mvp_d, cy_w, cy_d, ss_w, ss_d, ro_w, ro_d, fmvp_w, fmvp_d, r_cand, all_mlb, is_rs_f, is_ws_f = get_hist_awards_legacy(s_idx, df_b_full, df_p_full)
        season_cache[s_idx] = (mvp_w, mvp_d, cy_w, cy_d, ss_w, ss_d, ro_w, ro_d, fmvp_w, fmvp_d, r_cand, all_mlb, is_rs_f, is_ws_f)
    else:
        # 🚀 S6+ 現代新制 
        team_games = p_rs['賽事階段'].nunique() if not p_rs.empty else 1
        req_pa = max(3.1, team_games * 1.5)
        req_ip = max(1.0, team_games * 0.4)
        
        rs_cand = {}
        lg_obp, lg_slg, lg_woba, lg_era_base = 0.320, 0.400, 0.320, 4.50
        if not b_rs.empty:
            for c in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','得分','四壞球','三振','盜壘']:
                b_rs[c] = pd.to_numeric(b_rs.get(c, 0), errors='coerce').fillna(0)
            l_pa, l_ab = b_rs['打席'].sum(), b_rs['打數'].sum()
            l_h, l_bb = b_rs['安打'].sum(), b_rs['四壞球'].sum()
            l_h2, l_h3, l_hr = b_rs['二壘安打'].sum(), b_rs['三壘安打'].sum(), b_rs['全壘打'].sum()
            l_h1 = l_h - l_h2 - l_h3 - l_hr
            if l_pa > 0:
                lg_obp = (l_h + l_bb) / l_pa
                lg_woba = (0.69*l_bb + 0.88*l_h1 + 1.25*l_h2 + 1.59*l_h3 + 2.06*l_hr) / l_pa
            if l_ab > 0: lg_slg = (l_h1 + 2*l_h2 + 3*l_h3 + 4*l_hr) / l_ab

        if not p_rs.empty:
            for c in ['局數(整數)','局數(出局數)','被安打','四壞球','奪三振','失分','自責分','死球','被全壘打']:
                if c in p_rs.columns: p_rs[c] = pd.to_numeric(p_rs.get(c, 0), errors='coerce').fillna(0)
            l_er = p_rs['自責分'].sum()
            l_ip = (p_rs['局數(整數)'].sum()*3 + p_rs['局數(出局數)'].sum()) / 3.0
            if l_ip > 0: lg_era_base = (l_er * 9) / l_ip

        if not b_rs.empty:
            b_agg = b_rs.groupby('球員姓名').agg({'打席':'sum', '打數':'sum', '安打':'sum', '二壘安打':'sum', '三壘安打':'sum', '全壘打':'sum', '打點':'sum', '得分':'sum', '四壞球':'sum', '三振':'sum', '盜壘':'sum'}).reset_index()
            last_team_b = b_rs.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
            last_pos_b = b_rs.sort_values('時間戳記').groupby('球員姓名')['守位'].last() if '守位' in b_rs.columns else {}
            
            for _, r in b_agg.iterrows():
                name = f"[{last_team_b.get(r['球員姓名'], 'Unknown')}] {r['球員姓名']}"
                team = last_team_b.get(r['球員姓名'], 'Unknown')
                pos = last_pos_b.get(r['球員姓名'], 'DH') if isinstance(last_pos_b, dict) else last_pos_b.get(r['球員姓名'], 'DH')
                pa, ab, h, h2, h3, hr, bb = r['打席'], r['打數'], r['安打'], r['二壘安打'], r['三壘安打'], r['全壘打'], r['四壞球']
                h1 = h - h2 - h3 - hr
                obp = (h + bb) / max(1, pa)
                slg = (h1 + 2*h2 + 3*h3 + 4*hr) / max(1, ab)
                woba = (0.69*bb + 0.88*h1 + 1.25*h2 + 1.59*h3 + 2.06*hr) / max(1, pa)
                ops_plus = global_calc_ops_plus(obp, slg, lg_obp, lg_slg)
                wrc_plus = global_calc_wrc_plus(woba, lg_woba)
                ewar = global_calc_batter_ewar(wrc_plus, pos, pa)
                rs_cand[name] = {'team': team, 'name': name, '球員姓名': r['球員姓名'], '類型':'打者', 'Pos': pos, 'eWAR': ewar, 'OPS+': ops_plus, 'wRC+': wrc_plus, 'HR': int(hr), 'RBI': int(r['打點']), 'AVG': h/max(1, ab), 'PA': int(pa), 'Qual': pa >= req_pa}

        if not p_rs.empty:
            p_rs['勝'] = p_rs['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
            p_rs['救援'] = p_rs['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
            p_agg = p_rs.groupby('投手姓名').sum(numeric_only=True).reset_index()
            last_team_p = p_rs.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
            for _, r in p_agg.iterrows():
                name = f"[{last_team_p.get(r['投手姓名'], 'Unknown')}] {r['投手姓名']}"
                team = last_team_p.get(r['投手姓名'], 'Unknown')
                ip = (r['局數(整數)']*3 + r['局數(出局數)']) / 3.0
                er, hr, bb, so, w, sv = r['自責分'], r['開被全壘打' if '開被全壘打' in r else '被全壘打'], r['四壞球'], r['奪三振'], r['勝'], r['救援']
                era = (er * 9) / ip if ip > 0 else 0.0
                fip = (((13*hr) + (3*bb) - (2*so)) / ip) + 3.10 if ip > 0 else 3.10
                ewar = global_calc_pitcher_ewar(era, fip, ip, lg_era_base, s_idx)
                cyp = global_pitcher_cy_young_points(ip, er, so, w, sv, s_idx)
                
                if name in rs_cand:
                    rs_cand[name]['類型'] = '二刀流'
                    rs_cand[name]['eWAR'] = round(rs_cand[name]['eWAR'] + ewar, 1)
                    rs_cand[name]['Qual'] = rs_cand[name]['Qual'] or (ip >= req_ip)
                    rs_cand[name].update({'P_eWAR': ewar, 'CYP': cyp, 'ERA': era, 'FIP': fip, 'W': w, 'SV': sv, 'K_p': so, 'IP': ip})
                    rs_cand[name]['team'] = team
                else:
                    rs_cand[name] = {'team': team, 'name': name, '球員姓名': r['投手姓名'], '類型':'投手', 'eWAR': ewar, 'P_eWAR': ewar, 'CYP': cyp, 'ERA': era, 'FIP': fip, 'W': w, 'SV': sv, 'K_p': so, 'IP': ip, 'Qual': ip >= req_ip}

        mvp_winner, cy_winner, roty_winner, ss_winner, fmvp_winner = "無", "無", "無", "無", "無"
        mvp_df, cy_df, roty_df, ss_df, fmvp_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        all_mlb_1st = []

        def simulate_voting_local(target_award, cands_dict):
            eval_cands = {k: v for k, v in cands_dict.items() if v.get('Qual', False)}
            if not eval_cands: return "無", pd.DataFrame()
            results = {name: {'1st': 0, '2nd': 0, '3rd': 0, 'Points': 0} for name in eval_cands}
            voter_types = ['Traditional']*12 + ['Sabermetric']*10 + ['Balanced']*8
            
            max_hr = max([v.get('HR',0) for v in eval_cands.values()] + [0])
            max_rbi = max([v.get('RBI',0) for v in eval_cands.values()] + [0])
            max_w = max([v.get('W',0) for v in eval_cands.values()] + [0])
            max_k = max([v.get('K_p',0) for v in eval_cands.values()] + [0])
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
                            if stats['類型'] in ['打者', '二刀流']: score += stats.get('OPS+', 100)*0.5 + stats.get('HR',0)*20 + stats.get('RBI',0)*12 + leader_bonus + (30 if stats.get('AVG',0)>0.330 else 0)
                            if stats['類型'] in ['投手', '二刀流']: score += stats.get('W',0)*30 + stats.get('SV',0)*25 + stats.get('K_p',0)*4 - stats.get('ERA',5)*15 + leader_bonus
                        elif voter == 'Sabermetric':
                            if stats['類型'] == '打者': score += stats.get('eWAR',0)*100 + stats.get('OPS+',100)*0.2
                            if stats['類型'] == '投手': score += stats.get('P_eWAR', stats.get('eWAR',0))*130 + stats.get('CYP',0)*2
                            if stats['類型'] == '二刀流': score += stats.get('eWAR',0)*100 + stats.get('OPS+',100)*0.1 + stats.get('CYP',0)*1
                        else: # Balanced
                            if stats['類型'] == '打者': score += stats.get('eWAR',0)*60 + stats.get('OPS+',100)*0.3 + stats.get('HR',0)*10 + leader_bonus*0.5
                            if stats['類型'] == '投手': score += stats.get('P_eWAR', stats.get('eWAR',0))*80 + stats.get('W',0)*15 + stats.get('K_p',0)*2 + leader_bonus*0.5
                            if stats['類型'] == '二刀流': score += stats.get('eWAR',0)*70 + stats.get('HR',0)*5 + stats.get('W',0)*10
                    elif target_award == "CyYoung":
                        if stats['類型'] == '打者': continue
                        if stats.get('ERA', 5) > 5.00: score -= 500 
                        if voter == 'Traditional': score += stats.get('CYP',0)*3 + stats.get('W',0)*10 - stats.get('ERA',5)*10 + leader_bonus
                        else: score += stats.get('P_eWAR',0)*60 + stats.get('CYP',0)*2 - stats.get('ERA',5)*5 + leader_bonus*0.5
                    elif target_award == "SilverSlugger":
                        if stats['類型'] == '投手': continue
                        if voter == 'Traditional': score += stats.get('HR',0)*25 + stats.get('AVG',0)*100 + leader_bonus
                        else: score += stats.get('eWAR',0)*20 + stats.get('wRC+',0)*2

                    scores[name] = score 
                
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

        if rs_cand:
            mvp_winner, mvp_df = simulate_voting_local("MVP", rs_cand)
            cy_winner, cy_df = simulate_voting_local("CyYoung", rs_cand)
            ss_winner, ss_df = simulate_voting_local("SilverSlugger", rs_cand)
            
            if s_idx == 1: 
                roty_winner, roty_df = "無 (首賽季不頒發)", pd.DataFrame()
            else:
                past_pa, past_ip, debut_season = {}, {}, {}
                for ps in range(1, s_idx):
                    if ps in season_cache:
                        for p_name, stats in season_cache[ps][10].items():
                            clean_name = p_name.split('] ')[1] if ']' in p_name else p_name
                            past_pa[clean_name] = past_pa.get(clean_name, 0) + stats.get('PA', 0)
                            past_ip[clean_name] = past_ip.get(clean_name, 0.0) + stats.get('IP', 0.0)
                            if clean_name not in debut_season: debut_season[clean_name] = ps
                
                rookies = {}
                for k, v in rs_cand.items():
                    clean_k = k.split('] ')[1] if ']' in k else k
                    if past_pa.get(clean_k, 0) < 6 and past_ip.get(clean_k, 0.0) < 2.0:
                        if debut_season.get(clean_k, s_idx) >= s_idx - 1:
                            rookies[k] = v
                roty_winner, roty_df = simulate_voting_local("MVP", rookies) if rookies else ("無符合資格球員", pd.DataFrame())

            valid_mvp = [x for x in rs_cand.items() if x[1].get('Qual', False)]
            all_mlb_1st = [x[0] for x in sorted(valid_mvp, key=lambda x: x[1]['eWAR'], reverse=True)[:9]]

        def safe_val(val):
            try: return float(val) if pd.notna(val) else 0.0
            except: return 0.0

        if not b_ws.empty or not p_ws.empty:
            ws_winner_team = None
            laa_ws_w, lad_ws_w = 0, 0
            if not p_ws.empty:
                for stg, grp in p_ws.groupby('賽事階段'):
                    if any('勝' in str(x) for x in grp[grp['球隊']=='LAA']['勝敗'].values): laa_ws_w += 1
                    if any('勝' in str(x) for x in grp[grp['球隊']=='LAD']['勝敗'].values): lad_ws_w += 1
            if laa_ws_w >= 4: ws_winner_team = "LAA"
            elif lad_ws_w >= 4: ws_winner_team = "LAD"

            ws_cand = {}
            if not b_ws.empty:
                b_ws_c = b_ws.copy()
                for c in ['安打', '全壘打', '打點', '得分', '四壞球']:
                    if c in b_ws_c.columns: b_ws_c[c] = pd.to_numeric(b_ws_c[c], errors='coerce').fillna(0)
                b_ws_agg = b_ws_c.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index()
                for _, r in b_ws_agg.iterrows():
                    name = f"[{r['球隊']}] {r['球員姓名']}"
                    b_score = r.get('全壘打',0)*40 + r.get('打點',0)*20 + r.get('安打',0)*15 + r.get('得分',0)*10 + r.get('四壞球',0)*5
                    ws_cand[name] = {'類型':'打者', 'score': b_score}
            
            if not p_ws.empty:
                p_ws_c = p_ws.copy()
                p_ws_c['勝'] = p_ws_c['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                p_ws_c['救援'] = p_ws_c['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                p_ws_c['中繼'] = p_ws_c['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
                for c in ['局數(整數)', '局數(出局數)', '自責分', '被安打', '四壞球', '奪三振', '被全壘打']:
                    if c in p_ws_c.columns: p_ws_c[c] = pd.to_numeric(p_ws_c[c], errors='coerce').fillna(0)
                p_ws_agg = p_ws_c.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
                for _, r in p_ws_agg.iterrows():
                    name = f"[{r['球隊']}] {r['投手姓名']}"
                    ip = (r.get('局數(整數)',0)*3 + r.get('局數(出局數)',0)) / 3.0
                    p_score = r.get('勝',0)*45 + r.get('救援',0)*35 + r.get('中繼',0)*20 + (ip * 3)*15 + (r.get('奪三振',0) * 3)*3 - r.get('自責分',0)*15 - r.get('被全壘打',0)*10
                    
                    if name in ws_cand:
                        ws_cand[name]['類型'] = '二刀流'
                        ws_cand[name]['score'] += p_score
                    else:
                        ws_cand[name] = {'類型':'投手', 'score': p_score}
            
            fmvp_s = sorted(ws_cand.items(), key=lambda x: x[1]['score'], reverse=True)
            if ws_winner_team:
                fmvp_s = [x for x in fmvp_s if f"[{ws_winner_team}]" in x[0]]

            if fmvp_s:
                fmvp_df = pd.DataFrame([
                    {
                        '球員': k, 
                        'WS貢獻積分': v['score'], 
                        '第一名選票': 30 if i==0 else 0, 
                        '第二名選票': 20 if i==1 else 0,
                        '第三名選票': 10 if i==2 else 0,
                        '總積分': 100 if i==0 else (60 if i==1 else 30)
                    } for i, (k,v) in enumerate(fmvp_s[:5])
                ])
                fmvp_winner = fmvp_s[0][0]
                if not ws_winner_team: fmvp_winner += " (領跑中)"
            else: fmvp_winner, fmvp_df = "無", pd.DataFrame()
        else: fmvp_winner, fmvp_df = "尚未產生", pd.DataFrame()

        season_cache[s_idx] = (mvp_winner, mvp_df, cy_winner, cy_df, ss_winner, ss_df, roty_winner, roty_df, fmvp_winner, fmvp_df, rs_cand, all_mlb_1st, is_rs_fin, is_ws_fin)
# ==========================================
# 4. 宣告頂部分頁導覽列 (Tabs)
# ==========================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏠 聯盟官方首頁", 
    "🏟️ 聯盟賽程中心", 
    "📊 聯盟數據總表",
    "📈 球員數據總表",  
    "🏛️ 歷史與榮耀殿堂",
    "🆚 球員 PK 台",
])


# ==========================================
# --- 分頁 1：🏠 聯盟官方首頁 (Home Portal) ---
# ==========================================
with tab1:
    import re
    from datetime import datetime
    import random
    import math
    import altair as alt

    def generate_initials(name):
        clean_name = str(name).replace('.', ' ').replace('-', ' ')
        parts = clean_name.split()
        if len(parts) >= 2: return (parts[0][0] + parts[-1][0]).upper()
        return str(name)[:2].upper()

    def fmt_rate_t1(val):
        if val >= 1: return f"{val:.3f}"
        return f"{val:.3f}".lstrip('0')
        
    st.title("⚾ 洛杉磯雙雄數據追蹤系統 V51 (官方數據控制中心)")
    st.caption("即時提煉底層 1200+ 筆數據，自動生成聯盟最高榮譽排行榜與奪冠機率預測。")

    df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())

    required_b = ['賽事階段', '球隊', '得分', '安打', '打數', '打點', '四壞球', '三振', '全壘打', '球員姓名', '二壘安打', '三壘安打', '盜壘', '打席']
    for c in required_b:
        if c not in df_b_raw.columns: df_b_raw[c] = "0"
        
    required_p = ['賽事階段', '球隊', '勝敗', '時間戳記', '投手姓名', '角色', '局數(整數)', '局數(出局數)', '自責分', '失分', '奪三振', '四壞球', '被全壘打', '投球數']
    for c in required_p:
        if c not in df_p_raw.columns: df_p_raw[c] = "無" if c == '勝敗' else "0"

    latest_s_str = "Season 1"
    if not df_p_raw.empty:
        s_nums = df_p_raw['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]')[0].dropna().astype(int)
        if not s_nums.empty: latest_s_str = f"Season {s_nums.max()}"

    col_h_s, _ = st.columns([1.2, 4])
    with col_h_s:
        h_season = st.selectbox("📅 選擇首頁聚焦賽季", SEASONS, key="h_season_sel", index=SEASONS.index(latest_s_str) if latest_s_str in SEASONS else 0)
    
    curr_s_num = h_season.split(" ")[1]
    curr_s_int = int(curr_s_num)
    wr_season = h_season
    
    df_b_s = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)] if not df_b_raw.empty else pd.DataFrame(columns=required_b)
    df_p_s = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)] if not df_p_raw.empty else pd.DataFrame(columns=required_p)

    global_home_dict = st.session_state.get('global_home_dict', {})

    played_stages = []
    for g in GAME_STAGES:
        full_stg = f"[S{curr_s_num}] {g}"
        if not df_p_s.empty and not df_p_s[df_p_s['賽事階段'] == full_stg].empty: played_stages.append(full_stg)
        
    ws_l_w, ws_d_w = 0, 0
    if not df_p_s.empty:
        ws_p_s = df_p_s[df_p_s['賽事階段'].astype(str).str.contains("世界大賽", regex=False)]
        for stg, grp in ws_p_s.groupby('賽事階段', sort=False):
            if any('勝' in str(x) for x in grp[grp['球隊']=='LAA']['勝敗'].values): ws_l_w += 1
            if any('勝' in str(x) for x in grp[grp['球隊']=='LAD']['勝敗'].values): ws_d_w += 1
    
    is_season_over = (ws_l_w >= 4 or ws_d_w >= 4)
    is_ws_mode = (len([s for s in played_stages if "例行賽" in s]) >= 10)

    # =======================================================
    # ⚡ 區塊一：最新戰報動態
    # =======================================================
    st.markdown("---")
    st.subheader("⚡ 賽事即時動態 (Recent Results & Upcoming)")
    
    target_stages = [None, None, None] 
    if len(played_stages) >= 2:
        target_stages[0] = played_stages[-2]
        target_stages[1] = played_stages[-1]
    elif len(played_stages) == 1:
        target_stages[1] = played_stages[-1]
        
    if not is_season_over:
        for g in GAME_STAGES:
            stg = f"[S{curr_s_num}] {g}"
            if stg not in played_stages:
                target_stages[2] = stg
                break
            
    mini_cols = st.columns(3)
    titles = ["⏪ 前場戰報 (Prev Final)", "🔥 最新完賽 (Latest Final)", "🔜 準備開打 (Upcoming)"]
    current_fake_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_pitcher_season_stats_t1(p_name, current_ts, df_p_season):
        p_history = df_p_season[(df_p_season['投手姓名'] == p_name) & (df_p_season['時間戳記'] <= current_ts)]
        w = sum([1 for x in p_history['勝敗'].astype(str) if '勝' in x])
        l = sum([1 for x in p_history['勝敗'].astype(str) if '敗' in x])
        sv = sum([1 for x in p_history['勝敗'].astype(str) if '救援' in x])
        outs = (pd.to_numeric(p_history['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(p_history['局數(出局數)'], errors='coerce').fillna(0)).sum()
        er = pd.to_numeric(p_history['自責分'], errors='coerce').fillna(0).sum()
        era = (er * 9) / (outs / 3.0) if outs > 0 else (float('inf') if er > 0 else 0.0)
        return w, l, sv, era
    
    for idx, (t_stg, col_title) in enumerate(zip(target_stages, titles)):
        with mini_cols[idx]:
            with st.container(border=True):
                if t_stg:
                    g_name = t_stg.split("] ")[1] if "] " in t_stg else t_stg
                    m_g = re.search(r'G(\d+)', g_name)
                    g_num = int(m_g.group(1)) if m_g else 0
                    
                    home_tm = global_home_dict.get(t_stg, "LAA")
                    away_tm = "LAD" if home_tm == "LAA" else "LAA"
                        
                    away_col_txt = "🔴 LAA" if away_tm == "LAA" else "🔵 LAD"
                    home_col_txt = "🔴 LAA" if home_tm == "LAA" else "🔵 LAD"
                    
                    bg = df_b_s[df_b_s['賽事階段'] == t_stg]
                    pg = df_p_s[df_p_s['賽事階段'] == t_stg]
                    
                    if idx in [0, 1] and t_stg: 
                        away_r = pd.to_numeric(bg[bg['球隊']==away_tm]['得分'], errors='coerce').fillna(0).sum()
                        home_r = pd.to_numeric(bg[bg['球隊']==home_tm]['得分'], errors='coerce').fillna(0).sum()
                        wp_name, lp_name, sv_name = "—", "—", ""
                        for _, r in pg[pg['勝敗'] != '無'].iterrows():
                            if '勝' in str(r['勝敗']): wp_name = r['投手姓名']
                            if '敗' in str(r['勝敗']): lp_name = r['投手姓名']
                            if '救援' in str(r['勝敗']): sv_name = r['投手姓名']
                        sv_str = f" | SV: {sv_name}" if sv_name else ""
                        
                        away_score_style = "color:#ffcc00; font-weight:900; font-size:18px;" if away_r > home_r else "font-weight:bold; font-size:16px;"
                        home_score_style = "color:#ffcc00; font-weight:900; font-size:18px;" if home_r > away_r else "font-weight:bold; font-size:16px;"
                        
                        st.markdown(f"<div style='font-size:12px; color:#888; font-weight:bold; margin-bottom:5px;'>{col_title}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='font-size:11px; color:#aaa; margin-bottom:4px;'>✓ {g_name.split(' ')[0]} (第 {g_num} 場) | Final</div>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div style='display:flex; justify-content:space-between; align-items:center; margin:4px 0;'>
                            <span style='font-weight:bold; font-size:16px;'>{away_col_txt}</span> <span style='{away_score_style}'>{int(away_r)}</span>
                        </div>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin:4px 0;'>
                            <span style='font-weight:bold; font-size:16px;'>{home_col_txt}</span> <span style='{home_score_style}'>{int(home_r)}</span>
                        </div>
                        <div style='font-size:11px; color:#bbb; margin-top:8px; border-top:1px solid #333; padding-top:6px;'>
                            <b>W:</b> {wp_name} | <b>L:</b> {lp_name}{sv_str}
                        </div>
                        """, unsafe_allow_html=True)
                    elif t_stg: 
                        next_starters = {"LAA": "未指定", "LAD": "未指定"}
                        for t_key in ["LAA", "LAD"]:
                            stg_keyword_auto = "世界大賽" if "世界大賽" in g_name else "例行賽"
                            t_df_auto = df_p_raw[(df_p_raw['球隊'] == t_key) & (df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}] {stg_keyword_auto}", regex=False))]
                            starters_played = []
                            if not t_df_auto.empty:
                                for stage_auto, group_auto in t_df_auto.groupby('賽事階段', sort=False):
                                    g_sorted_auto = group_auto.sort_values('時間戳記')
                                    if not g_sorted_auto.empty: starters_played.append(g_sorted_auto.iloc[0]['投手姓名'])
                            if starters_played:
                                unique_sps = list(set(starters_played))
                                sp_last_idx = {sp: len(starters_played) - 1 - starters_played[::-1].index(sp) for sp in unique_sps}
                                next_starters[t_key] = min(unique_sps, key=lambda x: sp_last_idx[x])
                            else:
                                hist_df_auto = df_p_raw[df_p_raw['球隊'] == t_key]
                                if not hist_df_auto.empty:
                                    hist_starters = []
                                    for stage_auto, group_auto in hist_df_auto.groupby('賽事階段', sort=False):
                                        g_sorted_auto = group_auto.sort_values('時間戳記')
                                        if not g_sorted_auto.empty: hist_starters.append(g_sorted_auto.iloc[0]['投手姓名'])
                                    if hist_starters: next_starters[t_key] = max(set(hist_starters), key=hist_starters.count)

                        away_sp = next_starters.get(away_tm, "未指定")
                        home_sp = next_starters.get(home_tm, "未指定")
                        away_sp_st, home_sp_st = "", ""
                        if away_sp != "未指定":
                            w, l, _, era = get_pitcher_season_stats_t1(away_sp, current_fake_ts, df_p_s)
                            away_sp_st = f"({w}-{l}, {era:.2f})" if era != float('inf') else f"({w}-{l}, ∞)"
                        if home_sp != "未指定":
                            w, l, _, era = get_pitcher_season_stats_t1(home_sp, current_fake_ts, df_p_s)
                            home_sp_st = f"({w}-{l}, {era:.2f})" if era != float('inf') else f"({w}-{l}, ∞)"
                            
                        st.markdown(f"<div style='font-size:12px; color:#D4AF37; font-weight:bold; margin-bottom:5px;'>{col_title}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='font-size:11px; color:#aaa; margin-bottom:4px;'>▶ {g_name.split(' ')[0]} (第 {g_num} 場) | Live / Scheduled</div>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div style='margin-bottom:8px;'>
                            <div style='font-weight:bold; font-size:16px;'>{away_col_txt}</div>
                            <div style='font-size:12px; color:#aaa; margin-left:14px; margin-top:2px;'>SP: <span style='color:#eee; font-weight:bold;'>{away_sp}</span> <span style='color:#777;'>{away_sp_st}</span></div>
                        </div>
                        <div style='margin-bottom:4px;'>
                            <div style='font-weight:bold; font-size:16px;'>{home_col_txt}</div>
                            <div style='font-size:12px; color:#aaa; margin-left:14px; margin-top:2px;'>SP: <span style='color:#eee; font-weight:bold;'>{home_sp}</span> <span style='color:#777;'>{home_sp_st}</span></div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='font-size:12px; color:#888; font-weight:bold;'>{col_title}</div>", unsafe_allow_html=True)
                    txt = "🏆 本賽季已圓滿結束" if is_season_over else "賽程準備中"
                    st.markdown(f"<div style='text-align:center; padding:20px; color:#555;'>{txt}</div>", unsafe_allow_html=True)

    # =======================================================
    # 📺 區塊二：焦點對戰 (Spotlight Matchup)
    # =======================================================
    st.markdown("---")
    st.subheader("📺 焦點對戰 (Spotlight Matchup)")
    
    def get_season_data_t1(target_season, target_stage=""):
        prefix = f"[S{target_season.split(' ')[1]}]" if target_season != "十年總成績" else ""
        b_sub = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_b_raw
        p_sub = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_raw
        
        if target_stage:
            b_sub = b_sub[b_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]
            p_sub = p_sub[p_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]

        b_dict, p_dict = {'LAA': {}, 'LAD': {}}, {'LAA': {}, 'LAD': {}}
        
        if not b_sub.empty:
            b_clean = b_sub.copy()
            if '四壞' in b_clean.columns and '四壞球' not in b_clean.columns: b_clean['四壞球'] = b_clean['四壞']
            for col in ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '四壞球', '三振']:
                b_clean[col] = pd.to_numeric(b_clean.get(col, 0), errors='coerce').fillna(0)
            
            total_pa = b_clean['打席'].sum()
            lg_1b = b_clean['安打'].sum() - b_clean['二壘安打'].sum() - b_clean['三壘安打'].sum() - b_clean['全壘打'].sum()
            lg_woba_num = 0.69 * b_clean['四壞球'].sum() + 0.88 * lg_1b + 1.25 * b_clean['二壘安打'].sum() + 1.59 * b_clean['三壘安打'].sum() + 2.06 * b_clean['全壘打'].sum()
            lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.001

            cols_to_sum = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '四壞球', '三振']
            agg_b = b_clean.groupby('球員姓名')[cols_to_sum].sum().reset_index()
            last_team_b = b_clean.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
            
            for _, row in agg_b.iterrows():
                name = row['球員姓名']
                team = last_team_b.get(name, 'Unknown')
                b_1b = row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']
                woba = (0.69 * row['四壞球'] + 0.88 * b_1b + 1.25 * row['二壘安打'] + 1.59 * row['三壘安打'] + 2.06 * row['全壘打']) / max(1, row['打席'])
                wrc_plus = global_calc_wrc_plus(woba, lg_woba)
                
                if team not in b_dict: b_dict[team] = {}
                b_dict[team][name] = {
                    'wRC+': wrc_plus, 'HR': row['全壘打'], 'K': row['三振'], 'BB': row['四壞球'], 
                    'AB': row['打數'], 'H': row['安打'], 'XBH': row['二壘安打']+row['三壘安打']+row['全壘打'], 'PA': row['打席']
                }

        if not p_sub.empty:
            p_clean = p_sub.copy()
            for col in ['局數(整數)', '局數(出局數)', '打者數', '被安打', '被全壘打', '奪三振', '四壞球']:
                p_clean[col] = pd.to_numeric(p_clean.get(col, 0), errors='coerce').fillna(0)
            
            p_cols_to_sum = ['局數(整數)', '局數(出局數)', '打者數', '被安打', '被全壘打', '奪三振', '四壞球']
            agg_p = p_clean.groupby('投手姓名')[p_cols_to_sum].sum().reset_index()
            last_team_p = p_clean.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
            
            for _, row in agg_p.iterrows():
                name = row['投手姓名']
                team = last_team_p.get(name, 'Unknown')
                ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                
                if team not in p_dict: p_dict[team] = {}
                p_dict[team][name] = {
                    'K': row['奪三振'], 'IP': ip_calc, 'BF': row.get('打者數', 0), 'BB': row['四壞球'], 'H': row['被安打'], 'HR': row['被全壘打']
                }
        return b_dict, p_dict

    reg_b_stats_t1, reg_p_stats_t1 = get_season_data_t1(f"Season {curr_s_num}", "例行賽")
    ws_b_stats_t1, ws_p_stats_t1 = get_season_data_t1(f"Season {curr_s_num}", "世界大賽")
    curr_b_stats_t1 = ws_b_stats_t1 if is_ws_mode else reg_b_stats_t1
    curr_p_stats_t1 = ws_p_stats_t1 if is_ws_mode else reg_p_stats_t1

    def log5_t1(a, b, l):
        if l <= 0 or l >= 1: return 0
        if a == 0 and b == 0: return 0
        num = (a * b) / l
        den = num + ((1 - a) * (1 - b) / (1 - l))
        if den == 0: return 0
        return num / den

    def get_x_stats_t1(b_name, b_team, p_name, p_team):
        b_s = curr_b_stats_t1.get(b_team, {}).get(b_name)
        p_s = curr_p_stats_t1.get(p_team, {}).get(p_name)
        if not b_s or not p_s or b_s.get('PA', 0) == 0 or p_s.get('BF', 0) == 0: return 0, 0, 0, 0, 0
        lg_pa = sum([v.get('PA',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()])
        lg_ab = sum([v.get('AB',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()])
        if lg_pa < 10 or lg_ab == 0: return 0, 0, 0, 0, 0
        
        l_ba = sum([v.get('H',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()]) / lg_ab
        l_obp = sum([v.get('H',0)+v.get('BB',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()]) / lg_pa
        l_hr = sum([v.get('HR',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()]) / lg_pa
        l_k = sum([v.get('K',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()]) / lg_pa
        l_xbh = sum([v.get('XBH',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()]) / lg_pa

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
        
        lg_hr_tot = sum([v.get('HR',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()])
        lg_h_tot = sum([v.get('H',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()])
        lg_xbh_tot = sum([v.get('XBH',0) for t, plrs in curr_b_stats_t1.items() for p, v in plrs.items()])
        p_xbh_est = p_s['HR'] + max(0, p_s['H'] - p_s['HR']) * (max(0, lg_xbh_tot - lg_hr_tot) / max(1, lg_h_tot - lg_hr_tot))
        p_xbh = (p_xbh_est + l_xbh * W) / (p_bf + W)

        return log5_t1(b_ba, p_ba, l_ba), log5_t1(b_obp, p_obp, l_obp), log5_t1(b_hr, p_hr, l_hr), log5_t1(b_xbh, p_xbh, l_xbh), log5_t1(b_k, p_k, l_k)

    def render_log5_card_t1(b_name, b_team, p_name, p_team, t_color):
        xBA, xOBP, xHR, xXBH, xK = get_x_stats_t1(b_name, b_team, p_name, p_team)
        if xBA == 0: return f"<div style='padding:20px; background:#111; border-radius:10px; color:#666; text-align:center;'>尚未產生足夠數據，無法預測 {b_name} vs {p_name}</div>"
        
        def make_bar(label, prob, color):
            p_pct = prob * 100
            return f"<div style='margin-bottom:8px;'><div style='display:flex; justify-content:space-between; font-size:13px; color:#ddd; margin-bottom:2px;'><span>{label}</span><span>{p_pct:.1f}%</span></div><div style='width:100%; background:#333; height:8px; border-radius:4px; overflow:hidden;'><div style='width:{p_pct}%; background:{color}; height:100%; border-radius:4px;'></div></div></div>"
        
        stats_pool = [make_bar('預期安打 (xBA)', xBA, '#00e5ff'), make_bar('預期上壘 (xOBP)', xOBP, '#007bff'), make_bar('預期長打 (xXBH%)', xXBH, '#ff9f00'), make_bar('預期全壘打 (xHR%)', xHR, '#ff4b4b'), make_bar('預期被三振 (xK%)', xK, '#b052d9')]
        chosen_stats = "".join(random.sample(stats_pool, 3))
        
        return f"<div style='background: linear-gradient(145deg, #161616 0%, #222 100%); padding: 20px; border-radius: 12px; border-left: 5px solid {t_color}; box-shadow: 0 4px 15px rgba(0,0,0,0.5);'><h4 style='color:#aaa; margin:0 0 15px 0; font-size:12px; text-transform:uppercase; letter-spacing:1px;'>📺 Spotlight Matchup</h4><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;'><div style='text-align:left; width: 40%;'><div style='font-size:10px; color:#888;'>BATTER [{b_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{b_name}</div></div><div style='font-size:16px; color:#555; font-weight:900; font-style:italic;'>VS</div><div style='text-align:right; width: 40%;'><div style='font-size:10px; color:#888;'>PITCHER [{p_team}]</div><div style='font-size:16px; font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{p_name}</div></div></div>{chosen_stats}</div>"

    target_matchup_stg = target_stages[2] if target_stages[2] else target_stages[1]
    if target_matchup_stg:
        home_team_t1 = global_home_dict.get(target_matchup_stg, "LAA")
        away_team_t1 = "LAD" if home_team_t1 == "LAA" else "LAA"

        laa_spotlight_b = max(curr_b_stats_t1['LAA'].keys(), key=lambda x: curr_b_stats_t1['LAA'][x]['wRC+']) if curr_b_stats_t1.get('LAA') else None
        lad_spotlight_b = max(curr_b_stats_t1['LAD'].keys(), key=lambda x: curr_b_stats_t1['LAD'][x]['wRC+']) if curr_b_stats_t1.get('LAD') else None
        laa_spotlight_p = max(curr_p_stats_t1['LAA'].keys(), key=lambda x: curr_p_stats_t1['LAA'][x]['IP']) if curr_p_stats_t1.get('LAA') else None
        lad_spotlight_p = max(curr_p_stats_t1['LAD'].keys(), key=lambda x: curr_p_stats_t1['LAD'][x]['IP']) if curr_p_stats_t1.get('LAD') else None

        c_card1, c_card2 = st.columns(2)
        has_matchup = False
        with c_card1:
            if away_team_t1 == "LAD" and lad_spotlight_b and laa_spotlight_p:
                card_html = render_log5_card_t1(lad_spotlight_b, 'LAD', laa_spotlight_p, 'LAA', '#005A9C')
                if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
            elif away_team_t1 == "LAA" and laa_spotlight_b and lad_spotlight_p:
                card_html = render_log5_card_t1(laa_spotlight_b, 'LAA', lad_spotlight_p, 'LAD', '#BA0021')
                if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
        with c_card2:
            if home_team_t1 == "LAA" and laa_spotlight_b and lad_spotlight_p:
                card_html = render_log5_card_t1(laa_spotlight_b, 'LAA', lad_spotlight_p, 'LAD', '#BA0021')
                if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
            elif home_team_t1 == "LAD" and lad_spotlight_b and laa_spotlight_p:
                card_html = render_log5_card_t1(lad_spotlight_b, 'LAD', laa_spotlight_p, 'LAA', '#005A9C')
                if card_html: st.markdown(card_html, unsafe_allow_html=True); has_matchup = True
                
        if has_matchup: st.markdown("<br>", unsafe_allow_html=True)
        else: st.info("尚無足夠賽程資料產生焦點對決。")
        
        # ✨ 季後賽牛棚出賽警告復原
        if is_ws_mode and not is_season_over:
            st.markdown("<br>", unsafe_allow_html=True)
            bullpen_warnings = []
            rp_c = df_p_s[df_p_s['賽事階段'].astype(str).str.contains("世界大賽", regex=False)].copy()
            if not rp_c.empty:
                rp_c['g_idx'] = rp_c.groupby(['球隊', '賽事階段']).cumcount()
                rp_only = rp_c[rp_c['g_idx'] > 0]
                ws_stg_sort = sorted(list(rp_only['賽事階段'].unique()))
                if len(ws_stg_sort) >= 2:
                    last_2_stgs = ws_stg_sort[-2:]
                    for tm in ['LAA', 'LAD']:
                        tm_rp = rp_only[rp_only['球隊'] == tm]
                        recent_rps = tm_rp[tm_rp['賽事階段'].isin(last_2_stgs)]['投手姓名'].value_counts()
                        overworked = recent_rps[recent_rps >= 2].index.tolist()
                        if overworked:
                            for rp in overworked: bullpen_warnings.append(f"[{tm}] {rp} 已連兩場登板。")
            if bullpen_warnings:
                warn_text = "，".join(bullpen_warnings)
                st.warning(f"⚠️ **牛棚過勞警戒**：{warn_text}")
    else:
        st.info("尚無足夠賽程資料產生焦點對決。")

    # =======================================================
    # 📈 區塊三：FanGraphs 魔球預期勝率分析 (例行賽與季後賽)
    # =======================================================
    st.markdown("---")
    st.subheader("📈 FanGraphs 魔球長期走勢與預期勝率分析 (Monte Carlo & Pyth%)")
    
    actual_rs_winners = []
    actual_rs_stages = []
    if not df_p_raw.empty:
        rs_df_temp = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains("例行賽", regex=False))]
        for stage_rs, group_rs in rs_df_temp.groupby('賽事階段', sort=False):
            g_sorted_rs = group_rs.sort_values('時間戳記')
            if any('勝' in str(x) for x in g_sorted_rs[g_sorted_rs['球隊']=='LAA']['勝敗'].values): actual_rs_winners.append("LAA")
            elif any('勝' in str(x) for x in g_sorted_rs[g_sorted_rs['球隊']=='LAD']['勝敗'].values): actual_rs_winners.append("LAD")
            else: actual_rs_winners.append("D") 
            actual_rs_stages.append(stage_rs)
    
    rs_games_played = len(actual_rs_stages) 
    laa_actual_rs_wins = actual_rs_winners.count("LAA")
    lad_actual_rs_wins = actual_rs_winners.count("LAD")

    def get_team_pyth_stats_t1(team, season_prefix):
        if df_b_raw.empty and df_p_raw.empty: return 0, 0, 0
        t_b = df_b_raw[(df_b_raw['球隊']==team) & df_b_raw['賽事階段'].astype(str).str.contains(season_prefix, regex=False)] if season_prefix else df_b_raw[df_b_raw['球隊']==team]
        t_p = df_p_raw[(df_p_raw['球隊']==team) & df_p_raw['賽事階段'].astype(str).str.contains(season_prefix, regex=False)] if season_prefix else df_p_raw[df_p_raw['球隊']==team]
        rs = pd.to_numeric(t_b['得分'], errors='coerce').sum() if not t_b.empty else 0
        ra = pd.to_numeric(t_p['失分'], errors='coerce').sum() if not t_p.empty else 0
        games = t_p['賽事階段'].nunique() if not t_p.empty else 0
        return rs, ra, games

    curr_prefix_rs = f"[S{curr_s_num}] 例行賽"
    laa_rs_c, laa_ra_c, laa_g_c = get_team_pyth_stats_t1("LAA", curr_prefix_rs)
    lad_rs_c, lad_ra_c, lad_g_c = get_team_pyth_stats_t1("LAD", curr_prefix_rs)
    laa_rd = laa_rs_c - laa_ra_c
    lad_rd = lad_rs_c - lad_ra_c
    
    def calc_pyth_t1(rs, ra):
        if rs + ra == 0: return 0.5
        return (rs**1.83) / (rs**1.83 + ra**1.83)

    pyth_laa_curr = calc_pyth_t1(laa_rs_c, laa_ra_c)
    
    if laa_g_c < 5 and curr_s_int > 1:
        prev_prefix_rs = f"[S{curr_s_int-1}] 例行賽"
        laa_rs_p, laa_ra_p, _ = get_team_pyth_stats_t1("LAA", prev_prefix_rs)
        pyth_laa_prev = calc_pyth_t1(laa_rs_p, laa_ra_p)
        weight = laa_g_c / 5.0
        true_prob_laa = pyth_laa_curr * weight + pyth_laa_prev * (1 - weight)
    else:
        true_prob_laa = pyth_laa_curr

    def calc_true_game_prob_t1(laa_home):
        p = true_prob_laa + (0.04 if laa_home else -0.04)
        return max(0.05, min(0.95, p))

    def get_game_score_str_t1(stage_name):
        if df_b_raw.empty: return "無比分"
        b_sub = df_b_raw[df_b_raw['賽事階段'] == stage_name]
        r_laa = pd.to_numeric(b_sub[b_sub['球隊']=='LAA']['得分'], errors='coerce').sum() if not b_sub.empty else 0
        r_lad = pd.to_numeric(b_sub[b_sub['球隊']=='LAD']['得分'], errors='coerce').sum() if not b_sub.empty else 0
        return f"{int(r_laa)} : {int(r_lad)}"
    
    def get_ros_expected_wins_t1(current_l_wins, current_d_wins, games_played):
        exp_l = current_l_wins
        for g_idx_py in range(games_played + 1, 11):
            stg_sim = f"[S{curr_s_num}] 例行賽 G{g_idx_py}"
            laa_home_game = True if global_home_dict.get(stg_sim) == 'LAA' else False
            exp_l += calc_true_game_prob_t1(laa_home_game)
        exp_future_l = exp_l - current_l_wins
        exp_future_d = (10 - games_played) - exp_future_l
        exp_d = current_d_wins + exp_future_d
        return exp_l, exp_d

    g_order = [f"G{i}" for i in range(12)]
    chart_data_rs = []
    exp_l, exp_d = get_ros_expected_wins_t1(0, 0, 0)
    chart_data_rs.append({"Game": "G0", "Team": "LAA", "Wins": exp_l, "Type": "實績", "Score": "球季開打"})
    chart_data_rs.append({"Game": "G0", "Team": "LAD", "Wins": exp_d, "Type": "實績", "Score": "球季開打"})

    for idx, winner in enumerate(actual_rs_winners):
        g_num_rs = idx + 1
        exp_l, exp_d = get_ros_expected_wins_t1(actual_rs_winners[:g_num_rs].count("LAA"), actual_rs_winners[:g_num_rs].count("LAD"), g_num_rs)
        s_str_rs = get_game_score_str_t1(actual_rs_stages[idx])
        chart_data_rs.append({"Game": f"G{g_num_rs}", "Team": "LAA", "Wins": exp_l, "Type": "實績", "Score": s_str_rs})
        chart_data_rs.append({"Game": f"G{g_num_rs}", "Team": "LAD", "Wins": exp_d, "Type": "實績", "Score": s_str_rs})
        
    if rs_games_played < 10:
        chart_data_rs.append({"Game": f"G{rs_games_played}", "Team": "LAA", "Wins": exp_l, "Type": "預測", "Score": "實績起點"})
        chart_data_rs.append({"Game": f"G{rs_games_played}", "Team": "LAD", "Wins": exp_d, "Type": "預測", "Score": "實績起點"})
        for g_num_rs in range(rs_games_played + 1, 11):
            chart_data_rs.append({"Game": f"G{g_num_rs}", "Team": "LAA", "Wins": exp_l, "Type": "預測", "Score": "未來賽事"})
            chart_data_rs.append({"Game": f"G{g_num_rs}", "Team": "LAD", "Wins": exp_d, "Type": "預測", "Score": "未來賽事"})

    actual_ws_winners = []
    actual_ws_stages = []
    if not df_p_raw.empty:
        ws_df_temp = df_p_raw[(df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)) & (df_p_raw['賽事階段'].astype(str).str.contains("世界大賽", regex=False))]
        for stage_ws, group_ws in ws_df_temp.groupby('賽事階段', sort=False):
            g_sorted_ws = group_ws.sort_values('時間戳記')
            if any('勝' in str(x) for x in g_sorted_ws[g_sorted_ws['球隊']=='LAA']['勝敗'].values): actual_ws_winners.append("LAA")
            elif any('勝' in str(x) for x in g_sorted_ws[g_sorted_ws['球隊']=='LAD']['勝敗'].values): actual_ws_winners.append("LAD")
            else: actual_ws_winners.append("D")
            actual_ws_stages.append(stage_ws)

    laa_ws_wins_temp = actual_ws_winners.count("LAA")
    lad_ws_wins_temp = actual_ws_winners.count("LAD")

    def get_ws_odds_at_t1(w_l, w_d):
        if w_l >= 4: return 1.0, 0.0
        if w_d >= 4: return 0.0, 1.0
        s_l, s_d = 0, 0
        random.seed(f"WS_ODDS_{curr_s_num}_{w_l}_{w_d}_{true_prob_laa}")
        
        for _ in range(2000):
            c_l, c_d = w_l, w_d
            g_ws_sim = w_l + w_d
            while c_l < 4 and c_d < 4:
                g_ws_sim += 1
                stg_sim = f"[S{curr_s_num}] 世界大賽 G{g_ws_sim}"
                laa_home_game = True if global_home_dict.get(stg_sim) == 'LAA' else False
                if random.random() < calc_true_game_prob_t1(laa_home_game): c_l += 1
                else: c_d += 1
            if c_l == 4: s_l += 1
            else: s_d += 1
        return s_l/2000.0, s_d/2000.0

    chart_data_ws = []
    p_l, p_d = get_ws_odds_at_t1(0, 0)
    chart_data_ws.append({"Game": "G0", "Team": "LAA", "Prob": p_l, "Type": "實績", "Score": "系列賽開打"})
    chart_data_ws.append({"Game": "G0", "Team": "LAD", "Prob": p_d, "Type": "實績", "Score": "系列賽開打"})
    for idx, winner in enumerate(actual_ws_winners):
        g_num_ws = idx + 1
        p_l, p_d = get_ws_odds_at_t1(actual_ws_winners[:g_num_ws].count("LAA"), actual_ws_winners[:g_num_ws].count("LAD"))
        s_str_ws = get_game_score_str_t1(actual_ws_stages[idx])
        chart_data_ws.append({"Game": f"G{g_num_ws}", "Team": "LAA", "Prob": p_l, "Type": "實績", "Score": s_str_ws})
        chart_data_ws.append({"Game": f"G{g_num_ws}", "Team": "LAD", "Prob": p_d, "Type": "實績", "Score": s_str_ws})

    curr_g_ws = len(actual_ws_winners)
    final_l_odds, final_d_odds = p_l, p_d
    
    random.seed(f"WS_ENDS_{curr_s_num}_{laa_ws_wins_temp}_{lad_ws_wins_temp}")
    game_ends = {4:0, 5:0, 6:0, 7:0}
    for _ in range(10000):
        c_l, c_d = laa_ws_wins_temp, lad_ws_wins_temp
        g = c_l + c_d
        while c_l < 4 and c_d < 4:
            g += 1
            stg_sim = f"[S{curr_s_num}] 世界大賽 G{g}"
            laa_home_game = True if global_home_dict.get(stg_sim) == 'LAA' else False
            if random.random() < calc_true_game_prob_t1(laa_home_game): c_l += 1
            else: c_d += 1
        game_ends[g] += 1

    if curr_g_ws < 7 and laa_ws_wins_temp < 4 and lad_ws_wins_temp < 4:
        chart_data_ws.append({"Game": f"G{curr_g_ws}", "Team": "LAA", "Prob": p_l, "Type": "預測", "Score": "實績起點"})
        chart_data_ws.append({"Game": f"G{curr_g_ws}", "Team": "LAD", "Prob": p_d, "Type": "預測", "Score": "實績起點"})
        for g_num_ws in range(curr_g_ws + 1, 8):
            chart_data_ws.append({"Game": f"G{g_num_ws}", "Team": "LAA", "Prob": p_l, "Type": "預測", "Score": "未來賽事"})
            chart_data_ws.append({"Game": f"G{g_num_ws}", "Team": "LAD", "Prob": p_d, "Type": "預測", "Score": "未來賽事"})

    col_chart_rs, col_chart_ws = st.columns(2)
    with col_chart_rs:
        st.markdown("##### 1️⃣ 例行賽最終累積勝場走勢 (Regular Season)")
        df_chart_rs = pd.DataFrame(chart_data_rs)
        base_rs = alt.Chart(df_chart_rs).encode(
            x=alt.X('Game:O', sort=g_order, title='例行賽進度', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Wins:Q', title='預估賽季最終總勝場', scale=alt.Scale(domain=[0, 10])),
            color=alt.Color('Team:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=alt.Legend(title="球隊")),
            strokeDash=alt.StrokeDash('Type:N', scale=alt.Scale(domain=['實績', '預測'], range=[[1,0], [5,5]])),
            tooltip=['Team:N', 'Game:N', 'Wins:Q', 'Score:N']
        ).properties(height=300)
        st.altair_chart(base_rs.mark_line(point=True, strokeWidth=3).interactive(bind_y=False, bind_x=False), use_container_width=True)
        
        if rs_games_played >= 10:
            if laa_actual_rs_wins > lad_actual_rs_wins: laa_hfa_sims = 10000
            elif lad_actual_rs_wins > laa_actual_rs_wins: laa_hfa_sims = 0
            else: laa_hfa_sims = 10000 if laa_rd >= lad_rd else 0
        else:
            seed_string_rs = f"RS_HFA_{wr_season}_{rs_games_played}"
            random.seed(sum(ord(c) for c in seed_string_rs) % 999999)
            laa_hfa_sims = 0
            for _ in range(10000):
                l_w, d_w = laa_actual_rs_wins, lad_actual_rs_wins
                l_rd_sim, d_rd_sim = laa_rd, lad_rd
                for g in range(rs_games_played + 1, 11):
                    stg_sim = f"[S{curr_s_num}] 例行賽 G{g}"
                    laa_home_this_game = True if global_home_dict.get(stg_sim) == 'LAA' else False
                    if random.random() < calc_true_game_prob_t1(laa_home_this_game):
                        l_w += 1
                        sim_margin = random.randint(1, 5)
                        l_rd_sim += sim_margin 
                        d_rd_sim -= sim_margin
                    else:
                        d_w += 1
                        sim_margin = random.randint(1, 5)
                        l_rd_sim -= sim_margin
                        d_rd_sim += sim_margin
                if l_w > d_w: laa_hfa_sims += 1
                elif l_w == d_w:
                    if l_rd_sim > d_rd_sim: laa_hfa_sims += 1
                    elif l_rd_sim == d_rd_sim: laa_hfa_sims += 0.5 

        st.caption(f"🔴 LAA **{laa_actual_rs_wins}勝** : **{lad_actual_rs_wins}勝** 🔵 LAD (已賽 {rs_games_played} 場)")
        c1, c2, c3 = st.columns(3)
        c1.metric("LAA 賽季末預估勝場", f"{exp_l:.1f}")
        c2.metric("LAD 賽季末預估勝場", f"{exp_d:.1f}")
        c3.metric("LAA 奪得主場優勢率", f"{(laa_hfa_sims/100.0):.1f}%")

    with col_chart_ws:
        st.markdown("##### 2️⃣ 季後賽世界大賽奪冠率走勢 (Playoff Odds)")
        df_chart_ws = pd.DataFrame(chart_data_ws)
        base_ws = alt.Chart(df_chart_ws).encode(
            x=alt.X('Game:O', sort=g_order, title='世界大賽進度', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Prob:Q', title='預期奪冠率', axis=alt.Axis(format='%'), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('Team:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=alt.Legend(title="球隊")),
            strokeDash=alt.StrokeDash('Type:N', scale=alt.Scale(domain=['實績', '預測'], range=[[1,0], [5,5]])),
            tooltip=['Team:N', 'Game:N', 'Prob:Q', 'Score:N']
        ).properties(height=300)
        st.altair_chart(base_ws.mark_line(point=True, strokeWidth=3).interactive(bind_y=False, bind_x=False), use_container_width=True)
        
        st.caption(f"系列賽比分：🔴 LAA **{laa_ws_wins_temp}勝** : **{lad_ws_wins_temp}勝** 🔵 LAD")
        if is_season_over:
            st.success("🎉 本賽季世界大賽已圓滿結束，冠軍金盃已誕生！")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("LAA 奪冠總機率", f"{(final_l_odds*100.0):.1f}%")
            c2.metric("LAD 奪冠總機率", f"{(final_d_odds*100.0):.1f}%")
            most_likely_games = max(game_ends, key=game_ends.get)
            c3.metric("預測結束場次", f"Game {most_likely_games}", f"完賽機率 {(game_ends[most_likely_games]/100.0):.1f}%")

    st.markdown("---")
    col_main_left, col_main_right = st.columns([1, 1])

    # =======================================================
    # 🏆 區塊四：大獎競逐預測中心 (✨ 對齊 3 局特化新制)
    # =======================================================
    with col_main_left:
        st.subheader("🏆 大獎競逐預測中心 (Award Race Radar)")
        
        mvp_view_sel = st.radio(
            "切換預測榜單", 
            ["🏆 例行賽 MVP (BBWAA 票選)", "🌟 世界大賽 FMVP (短期爆發)"], 
            index=1 if is_ws_mode else 0, 
            horizontal=True,
            key="mvp_fmvp_toggle"
        )
        is_fmvp_view = "FMVP" in mvp_view_sel
        
        if is_fmvp_view:
            st.caption("目前顯示：世界大賽最有價值球員 (FMVP) 評估模式！機率將與球隊奪冠機率同步連動。")
        else:
            st.caption("目前顯示：模擬全美棒球記者協會 (BBWAA) 依照現代魔球標準進行的 MVP 投票推演。")
        
        def safe_val(val):
            try: return float(val) if pd.notna(val) else 0.0
            except: return 0.0

        def compute_mvp_t1(stages_list, is_fmvp=False):
            if not stages_list: return {}
            b_df = df_b_raw[df_b_raw['賽事階段'].isin(stages_list)].copy()
            p_df = df_p_raw[df_p_raw['賽事階段'].isin(stages_list)].copy()
            if b_df.empty and p_df.empty: return {}
            
            for col in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','得分','四壞球','三振']:
                if col in b_df.columns: b_df[col] = pd.to_numeric(b_df[col], errors='coerce').fillna(0)
            for col in ['局數(整數)', '局數(出局數)', '奪三振', '自責分', '四壞球', '被全壘打']:
                if col in p_df.columns: p_df[col] = pd.to_numeric(p_df[col], errors='coerce').fillna(0)
            
            team_games = len(stages_list)
            req_pa = max(3.1, team_games * 1.5) if curr_s_int >= 6 else 15.0
            req_ip = max(1.0, team_games * 0.4) if curr_s_int >= 6 else 5.0

            if is_fmvp:
                cand_fmvp = {}
                if not b_df.empty:
                    b_agg = b_df.groupby('球員姓名').sum(numeric_only=True).reset_index()
                    last_team_b = b_df.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                    for _, r in b_agg.iterrows():
                        name = r['球員姓名']
                        # ✨ FMVP 對齊：打者火力常態化權重
                        score = safe_val(r.get('全壘打',0))*40 + safe_val(r.get('打點',0))*20 + safe_val(r.get('安打',0))*15 + safe_val(r.get('得分',0))*10 + safe_val(r.get('四壞球',0))*5
                        cand_fmvp[name] = {'team': last_team_b.get(name, 'Unknown'), 'name': name, 'score': score}
                
                if not p_df.empty:
                    p_df_c = p_df.copy()
                    p_df_c['勝'] = p_df_c['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                    p_df_c['救援'] = p_df_c['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                    p_df_c['中繼'] = p_df_c['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
                    p_agg = p_df_c.groupby('投手姓名').sum(numeric_only=True).reset_index()
                    last_team_p = p_df_c.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
                    for _, r in p_agg.iterrows():
                        name = r['投手姓名']
                        ip = (safe_val(r.get('局數(整數)',0))*3 + safe_val(r.get('局數(出局數)',0)))/3.0
                        
                        # ✨ FMVP 對齊：3局特化版投手公式
                        score = safe_val(r.get('勝',0))*45 + safe_val(r.get('救援',0))*35 + safe_val(r.get('中繼',0))*20 + (ip * 3)*15 + (safe_val(r.get('奪三振',0)) * 3)*3 - safe_val(r.get('自責分',0))*15 - safe_val(r.get('被全壘打',0))*10
                        
                        if name in cand_fmvp:
                            cand_fmvp[name]['score'] += score
                            cand_fmvp[name]['team'] = last_team_p.get(name, 'Unknown')
                        else:
                            cand_fmvp[name] = {'team': last_team_p.get(name, 'Unknown'), 'name': name, 'score': score}
                
                if not cand_fmvp: return {}
                
                total_laa = sum(v['score'] for v in cand_fmvp.values() if v['team'] == 'LAA' and v['score'] > 0)
                total_lad = sum(v['score'] for v in cand_fmvp.values() if v['team'] == 'LAD' and v['score'] > 0)
                
                final_res = {}
                for name, v in cand_fmvp.items():
                    if v['score'] <= 0: continue
                    tm = v['team']
                    team_share = (v['score'] / total_laa) if tm == 'LAA' and total_laa > 0 else (v['score'] / total_lad) if tm == 'LAD' and total_lad > 0 else 0
                    team_win_prob = final_l_odds if tm == 'LAA' else final_d_odds
                    prob = team_share * team_win_prob * 100
                    
                    final_res[name] = {'Prob': prob, 'team': tm, 'name': name, 'score': v['score']}
                    
                sorted_f = sorted(final_res.items(), key=lambda x: x[1]['Prob'], reverse=True)
                for rank, (name, v) in enumerate(sorted_f):
                    final_res[name]['Rank'] = rank + 1
                    
                return final_res

            t_pa_m = b_df['打席'].sum() if not b_df.empty else 1
            lg_1b_m = (b_df['安打'].sum() - b_df['二壘安打'].sum() - b_df['三壘安打'].sum() - b_df['全壘打'].sum()) if not b_df.empty else 0
            lg_woba_m = (0.69*b_df['四壞球'].sum() + 0.88*lg_1b_m + 1.25*b_df['二壘安打'].sum() + 1.59*b_df['三壘安打'].sum() + 2.06*b_df['全壘打'].sum()) / t_pa_m if t_pa_m > 0 else 0.320
            
            cand_mvp = {}
            if not b_df.empty:
                group_cols = ['球隊', '球員姓名'] if curr_s_int < 6 else '球員姓名'
                b_agg_m = b_df.groupby(group_cols).agg({'打席':'sum','打數':'sum','安打':'sum','二壘安打':'sum','三壘安打':'sum','全壘打':'sum','打點':'sum','四壞球':'sum','三振':'sum'}).reset_index()
                last_team_b = b_df.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                last_pos_b = b_df.sort_values('時間戳記').groupby('球員姓名')['守位'].last() if '守位' in b_df.columns else {}
                
                for _, r in b_agg_m.iterrows():
                    name_key = f"[{r['球隊']}] {r['球員姓名']}" if curr_s_int < 6 else r['球員姓名']
                    team = r['球隊'] if curr_s_int < 6 else last_team_b.get(r['球員姓名'], 'Unknown')
                    pos = last_pos_b.get(r['球員姓名'], 'DH') if isinstance(last_pos_b, dict) else last_pos_b.get(r['球員姓名'], 'DH')
                    
                    b_1b = r['安打'] - r['二壘安打'] - r['三壘安打'] - r['全壘打']
                    woba = (0.69*r['四壞球'] + 0.88*b_1b + 1.25*r['二壘安打'] + 1.59*r['三壘安打'] + 2.06*r['全壘打']) / max(1, r['打席'])
                    wrc_plus = global_calc_wrc_plus(woba, lg_woba_m) if curr_s_int >= 6 else (100 * (woba / lg_woba_m) if lg_woba_m > 0 else 0)
                    
                    pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
                    if curr_s_int < 6: ewar = (((wrc_plus - 70) / 80) + pos_adj_dict.get(pos, 0)) * (r['打席'] / 15)
                    else: ewar = global_calc_batter_ewar(wrc_plus, pos, r['打席'])
                    
                    cand_mvp[name_key] = {
                        'team': team, 'name': name_key, 'type':'打者', 'HR':r['全壘打'], 'RBI':r['打點'], 'AVG': r['安打']/max(1,r['打數']), 'eWAR': ewar, 'OPS+': wrc_plus, 'Qual': r['打席'] >= req_pa
                    }
            
            if not p_df.empty:
                p_df_c = p_df.copy()
                p_df_c['勝'] = p_df_c['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                p_df_c['救援'] = p_df_c['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                group_cols_p = ['球隊', '投手姓名'] if curr_s_int < 6 else '投手姓名'
                p_agg_m = p_df_c.groupby(group_cols_p).sum(numeric_only=True).reset_index()
                last_team_p = p_df_c.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
                
                lg_ip_m = ((p_df_c['局數(整數)'].sum()*3) + p_df_c['局數(出局數)'].sum()) / 3.0
                lg_era_base_m = (p_df_c['自責分'].sum()*9) / lg_ip_m if lg_ip_m > 0 else 10.60
                
                for _, r in p_agg_m.iterrows():
                    name_key = f"[{r['球隊']}] {r['投手姓名']}" if curr_s_int < 6 else r['投手姓名']
                    team = r['球隊'] if curr_s_int < 6 else last_team_p.get(r['投手姓名'], 'Unknown')
                    
                    ip_c = (r['局數(整數)']*3 + r['局數(出局數)'])/3.0
                    era = (r['自責分']*9)/max(1, ip_c) if ip_c > 0 else float('inf') if r['自責分'] > 0 else 0.0
                    fip = (((13*r['被全壘打' if '被全壘打' in r else '開被全壘打'])+(3*r['四壞球'])-(2*r['奪三振']))/max(1,ip_c))+3.10 if ip_c > 0 else 3.10
                    
                    if curr_s_int < 6:
                        tra = (era + fip) / 2.0
                        era_div = max(1.5, lg_era_base_m * 0.2)
                        ewar = (-0.1*r['自責分']-0.05*r['四壞球']) if ip_c == 0 else ((lg_era_base_m-tra)/era_div)*(ip_c/10)
                        cyp = 0
                    else:
                        ewar = global_calc_pitcher_ewar(era, fip, ip_c, lg_era_base_m, curr_s_int)
                        cyp = global_pitcher_cy_young_points(ip_c, r['自責分'], r['奪三振'], r['勝'], r['救援'], curr_s_int)
                    
                    if name_key in cand_mvp:
                        cand_mvp[name_key].update({'type':'二刀流', 'W':r['勝'], 'SV':r['救援'], 'ERA':era, 'K_p':r['奪三振'], 'CYP': cyp})
                        cand_mvp[name_key]['eWAR'] = round(cand_mvp[name_key]['eWAR'] + ewar, 1)
                        cand_mvp[name_key]['team'] = team
                        cand_mvp[name_key]['Qual'] = cand_mvp[name_key]['Qual'] or (ip_c >= req_ip)
                    else:
                        cand_mvp[name_key] = {'team': team, 'name': name_key, 'type':'投手', 'W':r['勝'], 'SV':r['救援'], 'ERA':era, 'K_p':r['奪三振'], 'eWAR':ewar, 'CYP': cyp, 'Qual': ip_c >= req_ip}
                        
            eval_cands = {k: v for k, v in cand_mvp.items() if v.get('Qual', False)}
            if not eval_cands: return {}
            
            leaders = {
                'HR': max([s.get('HR',0) for s in eval_cands.values()]+[0]), 'RBI': max([s.get('RBI',0) for s in eval_cands.values()]+[0]),
                'W': max([s.get('W',0) for s in eval_cands.values()]+[0]), 'K_p': max([s.get('K_p',0) for s in eval_cands.values()]+[0])
            }
            results = {name: {'Points': 0} for name in eval_cands}
            voter_types = ['Traditional']*12 + ['Sabermetric']*10 + ['Balanced']*8
            
            for voter in voter_types:
                scores = {}
                for name, stats in eval_cands.items():
                    score, leader_bonus = 0, 0
                    if stats.get('HR',0) == leaders['HR'] and leaders['HR'] > 0: leader_bonus += 30
                    if stats.get('RBI',0) == leaders['RBI'] and leaders['RBI'] > 0: leader_bonus += 20
                    if stats.get('W',0) == leaders['W'] and leaders['W'] > 0: leader_bonus += 10
                    if stats.get('K_p',0) == leaders['K_p'] and leaders['K_p'] > 0: leader_bonus += 20
                    
                    if curr_s_int >= 6:
                        # ✨ MVP 對齊：3局特化版大獎推演權重
                        if voter == 'Traditional':
                            if stats['type'] in ['打者', '二刀流']: score += stats.get('OPS+', 100)*0.5 + stats.get('HR',0)*20 + stats.get('RBI',0)*12 + leader_bonus + (30 if stats.get('AVG',0)>0.330 else 0)
                            if stats['type'] in ['投手', '二刀流']: score += stats.get('W',0)*30 + stats.get('SV',0)*25 + stats.get('K_p',0)*4 - stats.get('ERA',5)*15 + leader_bonus
                        elif voter == 'Sabermetric': 
                            if stats['type'] == '打者': score += stats.get('eWAR',0)*100 + stats.get('OPS+',100)*0.2
                            if stats['type'] == '投手': score += stats.get('eWAR',0)*130 + stats.get('CYP',0)*2
                            if stats['type'] == '二刀流': score += stats.get('eWAR',0)*100 + stats.get('OPS+',100)*0.1 + stats.get('CYP',0)*1
                        else: 
                            if stats['type'] == '打者': score += stats.get('eWAR',0)*60 + stats.get('OPS+',100)*0.3 + stats.get('HR',0)*10 + leader_bonus*0.5
                            if stats['type'] == '投手': score += stats.get('eWAR',0)*80 + stats.get('W',0)*15 + stats.get('K_p',0)*2 + leader_bonus*0.5
                            if stats['type'] == '二刀流': score += stats.get('eWAR',0)*70 + stats.get('HR',0)*5 + stats.get('W',0)*10
                    else:
                        if voter == 'Traditional':
                            if stats['type'] in ['打者', '二刀流']: score += stats.get('HR',0)*20 + stats.get('RBI',0)*10 + leader_bonus + (20 if stats.get('AVG',0)>0.300 else -30 if stats.get('AVG',0)<0.250 else 0)
                            if stats['type'] in ['投手', '二刀流']: score += stats.get('W',0)*12 + stats.get('SV',0)*10 + stats.get('K_p',0)*1.5 - stats.get('ERA',5)*15 + leader_bonus + (25 if stats.get('ERA',5)<3.00 else 0)
                        elif voter == 'Sabermetric': score += stats.get('eWAR',0)*80 + leader_bonus*0.2
                        else: score += stats.get('eWAR',0)*50 + stats.get('HR',0)*12 + stats.get('W',0)*5 - stats.get('ERA',5)*10 + leader_bonus*0.5
                        
                    scores[name] = score + (sum(ord(c) for c in name) % 100) / 100.0
                    
                top5 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                if len(top5) >= 1: results[top5[0][0]]['Points'] += 14
                if len(top5) >= 2: results[top5[1][0]]['Points'] += 9
                if len(top5) >= 3: results[top5[2][0]]['Points'] += 8
                if len(top5) >= 4: results[top5[3][0]]['Points'] += 5
                if len(top5) >= 5: results[top5[4][0]]['Points'] += 3
            
            power = 1.0 + (len(stages_list) / 10.0) * 3.0 
            total_points_power = sum(math.pow(v['Points'], power) for v in results.values() if v['Points'] > 0)
            
            final_res = {}
            sorted_by_prob = sorted(results.items(), key=lambda x: (math.pow(x[1]['Points'], power)/total_points_power*100) if x[1]['Points']>0 and total_points_power>0 else 0, reverse=True)
            for rank, (name, v) in enumerate(sorted_by_prob):
                prob = (math.pow(v['Points'], power) / total_points_power) * 100 if v['Points'] > 0 and total_points_power > 0 else 0.0
                final_res[name] = {'Rank': rank+1, 'Prob': prob, 'team': cand_mvp[name]['team'], 'name': name}
            return final_res

        eval_stages = actual_ws_stages if is_fmvp_view else actual_rs_stages
        curr_mvp_data = compute_mvp_t1(eval_stages, is_fmvp=is_fmvp_view)
        prev_mvp_data = compute_mvp_t1(eval_stages[:-1], is_fmvp=is_fmvp_view) if len(eval_stages) > 1 else {}
        
        with st.container(border=True):
            if curr_mvp_data:
                medals = ["🥇", "🥈", "🥉", "④", "⑤"]
                sorted_mvp = sorted(curr_mvp_data.items(), key=lambda x: x[1]['Rank'])[:5]
                for rank_idx, (p_name_only, v_data) in enumerate(sorted_mvp):
                    if v_data['Prob'] == 0: continue
                    tm_chk = v_data['team']
                    c_badge = "#BA0021" if tm_chk == "LAA" else "#005A9C"
                    
                    prev_data = prev_mvp_data.get(p_name_only, {'Rank': 99, 'Prob': 0.0})
                    rank_change = prev_data['Rank'] - v_data['Rank']
                    prob_change = v_data['Prob'] - prev_data['Prob']
                    
                    if rank_change > 0 and prev_data['Rank'] != 99: rank_html = f"<span style='color:#00e5ff; font-size:12px; margin-left:8px;'>▲{rank_change}</span>"
                    elif rank_change < 0: rank_html = f"<span style='color:#ff4b4b; font-size:12px; margin-left:8px;'>▼{abs(rank_change)}</span>"
                    elif prev_data['Rank'] == 99: rank_html = f"<span style='color:#D4AF37; font-size:12px; margin-left:8px;'>NEW</span>"
                    else: rank_html = f"<span style='color:#666; font-size:12px; margin-left:8px;'>-</span>"
                    
                    if prob_change > 0 and prev_data['Rank'] != 99: prob_html = f"<span style='color:#00e5ff; font-size:11px;'> (+{prob_change:.1f}%)</span>"
                    elif prob_change < 0: prob_html = f"<span style='color:#ff4b4b; font-size:11px;'> ({prob_change:.1f}%)</span>"
                    else: prob_html = ""
                    
                    st.markdown(f"""
                    <div style='display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #2a2a2a;'>
                        <div style='display:flex; align-items:center;'>
                            <span style='font-size:20px; margin-right:10px;'>{medals[rank_idx]}</span>{rank_html}
                            <span style='background-color:{c_badge}; color:white; font-size:10px; font-weight:bold; padding:2px 6px; border-radius:4px; margin-left:10px; margin-right:10px;'>{tm_chk}</span>
                            <span style='font-size:15px; font-weight:bold;'>{p_name_only}</span>
                        </div>
                        <span style='font-size:14px; font-weight:bold; color:#D4AF37;'>{v_data['Prob']:.1f}% 奪獎機率{prob_html}</span>
                    </div>
                    """, unsafe_allow_html=True)
                st.caption(f"機率會隨{'世界大賽' if is_fmvp_view else '例行賽'}進度產生 Softmax 滾動集中效應。")
            else: st.caption(f"暫無賽事紀錄可供 BBWAA 精算{' FMVP ' if is_fmvp_view else ' MVP '}機率。")

    # =======================================================
    # 🔥 區塊五：近期火燙榜 (跨隊伍合併計算 - 動態場次版)
    # =======================================================
    with col_main_right:
        st.subheader("🔥 近期火燙榜 (Who's Hot)")
        recent_hot_b = []
        team_hot_dict = {'LAA': [], 'LAD': []}
        
        def safe_sum_t1(df, col): return pd.to_numeric(df[col], errors='coerce').fillna(0).sum() if col in df.columns else 0

        for name, g in df_b_s.groupby('球員姓名'):
            g_sorted = g.sort_values('時間戳記', ascending=False)
            current_team = g_sorted.iloc[0]['球隊']
            if current_team not in team_hot_dict: continue
            
            best_n = 0
            best_ops = 0
            best_data = {}
            
            max_n = min(7, len(g_sorted))
            for n in range(3, max_n + 1):
                g_recent = g_sorted.head(n)
                pa = safe_sum_t1(g_recent, '打席')
                if pa < 4: continue 
                
                ab = safe_sum_t1(g_recent, '打數')
                h = safe_sum_t1(g_recent, '安打')
                h2 = safe_sum_t1(g_recent, '二壘安打')
                h3 = safe_sum_t1(g_recent, '三壘安打')
                hr = safe_sum_t1(g_recent, '全壘打')
                bb = safe_sum_t1(g_recent, '四壞球') if '四壞球' in g_recent.columns else safe_sum_t1(g_recent, '四壞')
                rbi = safe_sum_t1(g_recent, '打點')
                
                obp = (h + bb) / pa if pa > 0 else 0
                slg = (h - h2 - h3 - hr + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                ops = obp + slg
                
                if ops >= 0.850 or hr >= 2 or h >= n:
                    if ops >= best_ops:
                        best_n = n
                        best_ops = ops
                        best_data = {'Name': name, 'Team': current_team, 'OPS': ops, 'HR': hr, 'H': h, 'AB': ab, 'RBI': rbi, 'N': n}
                        
            if best_n >= 3:
                team_hot_dict[current_team].append(best_data)
                    
        for team in ['LAA', 'LAD']:
            recent_hot_b.extend(sorted(team_hot_dict[team], key=lambda x: x['OPS'], reverse=True)[:2])
        recent_hot_b = sorted(recent_hot_b, key=lambda x: x['OPS'], reverse=True)
        
        if_hot_any = False
        if recent_hot_b:
            for hot_plr in recent_hot_b:
                tm_color = "#BA0021" if hot_plr['Team'] == "LAA" else "#005A9C"
                
                hr_val = int(hot_plr['HR'])
                rbi_val = int(hot_plr['RBI'])
                if hr_val > 0 and rbi_val > 0: extra_desc = f"，包含 <b>{hr_val}</b> 轟 <b>{rbi_val}</b> 打點"
                elif hr_val > 0: extra_desc = f"，包含 <b>{hr_val}</b> 轟"
                elif rbi_val > 0: extra_desc = f"，貢獻 <b>{rbi_val}</b> 打點"
                else: extra_desc = ""
                    
                st.markdown(f"""
                <div style='background-color:#1a1a1a; padding:12px; border-radius:8px; border-left: 4px solid {tm_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.3); margin-bottom: 10px;'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <div>
                            <span style='font-size:11px; color:#aaa;'>[{hot_plr['Team']}]</span>
                            <span style='font-size:16px; font-weight:bold; color:white; margin-left:5px;'>{hot_plr['Name']} ☄️</span>
                        </div>
                        <div style='font-size:13px; color:#fc8d59; font-weight:bold;'>OPS: {hot_plr['OPS']:.3f}</div>
                    </div>
                    <div style='font-size:12px; color:#eee; margin-top:5px;'>近 <b>{hot_plr['N']}</b> 場：<b>{int(hot_plr['AB'])}</b> 支 <b>{int(hot_plr['H'])}</b>{extra_desc}</div>
                </div>
                """, unsafe_allow_html=True)
                if_hot_any = True
        if not if_hot_any: st.info("近期賽程中，兩隊暫無極端火燙的表現。")

    # =======================================================
    # 👑 區塊六：聯盟數據領跑者 (跨隊伍合併計算)
    # =======================================================
    st.markdown("---")
    st.subheader("👑 聯盟數據領跑者 (League Leaders)")
    l_col1, l_col2, l_col3, l_col4 = st.columns(4)
    
    with l_col1:
        with st.container(border=True):
            st.markdown("<div style='font-size:12px; color:#aaa;'>🔥 全壘打王</div>", unsafe_allow_html=True)
            if not df_b_s.empty and '全壘打' in df_b_s.columns:
                df_b_s_copy = df_b_s.copy()
                df_b_s_copy['全壘打_num'] = pd.to_numeric(df_b_s_copy['全壘打'], errors='coerce').fillna(0)
                last_team_map = df_b_s_copy.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                hr_leader = df_b_s_copy.groupby('球員姓名').agg({'全壘打_num': 'sum'}).sort_values('全壘打_num', ascending=False)
                
                if not hr_leader.empty and hr_leader.iloc[0]['全壘打_num'] > 0:
                    leader_name = hr_leader.index[0]
                    leader_team = last_team_map.get(leader_name, 'Unknown')
                    st.markdown(f"<div style='font-size:24px; font-weight:bold; color:#fff;'>{leader_name}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:14px; color:#D4AF37; font-weight:bold;'>{int(hr_leader.iloc[0]['全壘打_num'])} HR <span style='font-size:11px; color:#888;'>({leader_team})</span></div>", unsafe_allow_html=True)
                else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            
    with l_col2:
        with st.container(border=True):
            st.markdown("<div style='font-size:12px; color:#aaa;'>🏏 打擊王</div>", unsafe_allow_html=True)
            if not df_b_s.empty and '安打' in df_b_s.columns and '打數' in df_b_s.columns:
                df_b_s_copy = df_b_s.copy()
                df_b_s_copy['安打_num'] = pd.to_numeric(df_b_s_copy['安打'], errors='coerce').fillna(0)
                df_b_s_copy['打數_num'] = pd.to_numeric(df_b_s_copy['打數'], errors='coerce').fillna(0)
                last_team_map = df_b_s_copy.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                avg_df = df_b_s_copy.groupby('球員姓名').agg({'安打_num': 'sum', '打數_num': 'sum'})
                avg_df = avg_df[avg_df['打數_num'] >= 3] 
                if not avg_df.empty:
                    avg_df['AVG_val'] = avg_df['安打_num'] / avg_df['打數_num']
                    avg_df = avg_df.sort_values('AVG_val', ascending=False)
                    leader_name = avg_df.index[0]
                    leader_team = last_team_map.get(leader_name, 'Unknown')
                    st.markdown(f"<div style='font-size:24px; font-weight:bold; color:#fff;'>{leader_name}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:14px; color:#D4AF37; font-weight:bold;'>{fmt_rate_t1(avg_df.iloc[0]['AVG_val'])} <span style='font-size:11px; color:#888;'>({leader_team})</span></div>", unsafe_allow_html=True)
                else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            
    with l_col3:
        with st.container(border=True):
            st.markdown("<div style='font-size:12px; color:#aaa;'>🥎 防禦率王</div>", unsafe_allow_html=True)
            if not df_p_s.empty and '自責分' in df_p_s.columns and '局數(整數)' in df_p_s.columns:
                df_p_s_copy = df_p_s.copy()
                df_p_s_copy['自責分_num'] = pd.to_numeric(df_p_s_copy['自責分'], errors='coerce').fillna(0)
                df_p_s_copy['outs'] = pd.to_numeric(df_p_s_copy['局數(整數)'], errors='coerce').fillna(0)*3 + pd.to_numeric(df_p_s_copy.get('局數(出局數)', 0), errors='coerce').fillna(0)
                last_team_map = df_p_s_copy.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
                era_df = df_p_s_copy.groupby('投手姓名').agg({'自責分_num': 'sum', 'outs': 'sum'})
                era_df = era_df[era_df['outs'] >= 3]
                if not era_df.empty:
                    era_df['ERA_val'] = (era_df['自責分_num'] * 9) / (era_df['outs'] / 3.0)
                    era_df = era_df.sort_values('ERA_val', ascending=True)
                    leader_name = era_df.index[0]
                    leader_team = last_team_map.get(leader_name, 'Unknown')
                    st.markdown(f"<div style='font-size:24px; font-weight:bold; color:#fff;'>{leader_name}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:14px; color:#D4AF37; font-weight:bold;'>{era_df.iloc[0]['ERA_val']:.2f} <span style='font-size:11px; color:#888;'>({leader_team})</span></div>", unsafe_allow_html=True)
                else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            
    with l_col4:
        with st.container(border=True):
            st.markdown("<div style='font-size:12px; color:#aaa;'>⚡ 三振王</div>", unsafe_allow_html=True)
            if not df_p_s.empty and '奪三振' in df_p_s.columns:
                df_p_s_copy = df_p_s.copy()
                df_p_s_copy['奪三振_num'] = pd.to_numeric(df_p_s_copy['奪三振'], errors='coerce').fillna(0)
                last_team_map = df_p_s_copy.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
                so_leader = df_p_s_copy.groupby('投手姓名').agg({'奪三振_num': 'sum'}).sort_values('奪三振_num', ascending=False)
                if not so_leader.empty and so_leader.iloc[0]['奪三振_num'] > 0:
                    leader_name = so_leader.index[0]
                    leader_team = last_team_map.get(leader_name, 'Unknown')
                    st.markdown(f"<div style='font-size:24px; font-weight:bold; color:#fff;'>{leader_name}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:14px; color:#D4AF37; font-weight:bold;'>{int(so_leader.iloc[0]['奪三振_num'])} SO <span style='font-size:11px; color:#888;'>({leader_team})</span></div>", unsafe_allow_html=True)
                else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)
            else: st.markdown("<div style='font-size:20px; color:#666;'>—</div>", unsafe_allow_html=True)

    # =======================================================
    # 📊 區塊七：高階數據象限分析 (跨隊合併版)
    # =======================================================
    st.markdown("---")
    st.subheader("📊 高階數據象限分析 (Sabermetrics Quadrant Charts)")
    
    team_games_eval_t1 = df_b_s['賽事階段'].nunique() if not df_b_s.empty else 1
    dyn_pa_limit = max(1.0, team_games_eval_t1 * 1.0)
    dyn_ip_limit = max(0.1, team_games_eval_t1 * 0.33)
    
    st.caption(f"🤖 **AI 自動過濾機制**：系統已偵測本季當前進度 (已賽 {team_games_eval_t1} 場)，自動套用最低打席 ({dyn_pa_limit:.1f} PA) 與最低局數 ({dyn_ip_limit:.1f} IP) 門檻，剔除極端離群值。")

    df_b_quad = pd.DataFrame()
    if not df_b_s.empty:
        b_clean = df_b_s.copy()
        for col in ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '四壞球', '三振']:
            if col not in b_clean.columns: b_clean[col] = 0
            b_clean[col] = pd.to_numeric(b_clean[col], errors='coerce').fillna(0)
        
        total_pa = b_clean['打席'].sum()
        lg_1b = b_clean['安打'].sum() - b_clean['二壘安打'].sum() - b_clean['三壘安打'].sum() - b_clean['全壘打'].sum()
        lg_woba = (0.69 * b_clean['四壞球'].sum() + 0.88 * lg_1b + 1.25 * b_clean['二壘安打'].sum() + 1.59 * b_clean['三壘安打'].sum() + 2.06 * b_clean['全壘打'].sum()) / max(1, total_pa) if total_pa > 0 else 0.001
        
        agg_b = b_clean.groupby('球員姓名').sum(numeric_only=True).reset_index()
        last_team_b = b_clean.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
        
        b_quad_list = []
        for _, row in agg_b.iterrows():
            name = row['球員姓名']
            team = last_team_b.get(name, 'Unknown')
            if row['打席'] >= dyn_pa_limit:
                b_1b = row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']
                woba = (0.69 * row['四壞球'] + 0.88 * b_1b + 1.25 * row['二壘安打'] + 1.59 * row['三壘安打'] + 2.06 * row['全壘打']) / max(1, row['打席'])
                wrc_plus = global_calc_wrc_plus(woba, lg_woba)
                babip = (row['安打'] - row['全壘打']) / max(1, (row['打數'] - row['三振'] - row['全壘打']))
                b_quad_list.append({
                    '球員姓名': name, '球隊': team, 'wRC+': wrc_plus,
                    'BABIP': babip, 'PA': row['打席'], '縮寫': generate_initials(name)
                })
        df_b_quad = pd.DataFrame(b_quad_list)

    df_p_quad = pd.DataFrame()
    if not df_p_s.empty:
        p_clean = df_p_s.copy()
        for col in ['局數(整數)', '局數(出局數)', '被安打', '失分', '自責分', '四壞球', '奪三振', '被全壘打']:
            if col not in p_clean.columns: p_clean[col] = 0
            p_clean[col] = pd.to_numeric(p_clean[col], errors='coerce').fillna(0)
            
        agg_p = p_clean.groupby('投手姓名').sum(numeric_only=True).reset_index()
        last_team_p = p_clean.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
        
        p_quad_list = []
        for _, row in agg_p.iterrows():
            name = row['投手姓名']
            team = last_team_p.get(name, 'Unknown')
            ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
            if ip_calc >= dyn_ip_limit:
                era = (row['自責分'] * 9) / ip_calc if ip_calc > 0 else 0.0
                fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / ip_calc) + 3.10 if ip_calc > 0 else 3.10
                p_quad_list.append({
                    '投手姓名': name, '球隊': team, 'ERA': era,
                    'FIP': fip, 'IP': ip_calc, '縮寫': generate_initials(name)
                })
        df_p_quad = pd.DataFrame(p_quad_list)

    quad_c1, quad_c2 = st.columns(2)
    
    with quad_c1:
        st.markdown("##### 🏏 打者火力與運氣張力象限 (BABIP vs wRC+)")
        if not df_b_quad.empty:
            x_mean = df_b_quad['BABIP'].mean()
            y_mean = df_b_quad['wRC+'].mean()
            
            base_b = alt.Chart(df_b_quad).encode(
                x=alt.X('BABIP:Q', title="場內安打率 (BABIP)", scale=alt.Scale(zero=False, padding=1)),
                y=alt.Y('wRC+:Q', title="加權創造得分 (wRC+)", scale=alt.Scale(zero=False, padding=1)),
                tooltip=[
                    alt.Tooltip('球員姓名', title='打者'), alt.Tooltip('球隊', title='球隊'),
                    alt.Tooltip('wRC+:Q', title='wRC+', format='.0f'), alt.Tooltip('BABIP:Q', title='BABIP', format='.3f'),
                    alt.Tooltip('PA:Q', title='打席', format='.0f')
                ]
            )
            
            circles_b = base_b.mark_circle(size=600, opacity=0.8).encode(
                color=alt.Color('球隊:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=None)
            )
            
            labels_b = base_b.mark_text(baseline='middle', fontWeight='bold', color='white', fontSize=10).encode(text='縮寫:N')
            rule_x_b = alt.Chart(pd.DataFrame({'x': [x_mean]})).mark_rule(color='gray', strokeDash=[5,5], opacity=0.5).encode(x='x:Q')
            rule_y_b = alt.Chart(pd.DataFrame({'y': [y_mean]})).mark_rule(color='gray', strokeDash=[5,5], opacity=0.5).encode(y='y:Q')
            
            chart_b = (circles_b + labels_b + rule_x_b + rule_y_b).properties(height=350)
            st.altair_chart(chart_b, use_container_width=True)
            st.caption("↗️ 右上方為高火力且打擊極具侵略性的強運打者；↙️ 左下方為正處於手感低迷的掙扎打者。")
        else: st.info("尚無符合規定打席的打者可產生象限圖。")

    with quad_c2:
        st.markdown("##### 🥎 投手真實實力丘象限 (FIP vs ERA)")
        if not df_p_quad.empty:
            x_mean = df_p_quad['FIP'].mean()
            y_mean = df_p_quad['ERA'].mean()
            
            base_p = alt.Chart(df_p_quad).encode(
                x=alt.X('FIP:Q', title="獨立防禦率 (FIP) *越右越優", scale=alt.Scale(reverse=True, zero=False, padding=1)),
                y=alt.Y('ERA:Q', title="防禦率 (ERA) *越上越優", scale=alt.Scale(reverse=True, zero=False, padding=1)), 
                tooltip=[
                    alt.Tooltip('投手姓名', title='投手'), alt.Tooltip('球隊', title='球隊'),
                    alt.Tooltip('ERA:Q', title='ERA', format='.2f'), alt.Tooltip('FIP:Q', title='FIP', format='.2f'),
                    alt.Tooltip('IP:Q', title='局數', format='.1f')
                ]
            )
            
            circles_p = base_p.mark_circle(size=600, opacity=0.8).encode(
                color=alt.Color('球隊:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=None)
            )
            
            labels_p = base_p.mark_text(baseline='middle', fontWeight='bold', color='white', fontSize=10).encode(text='縮寫:N')
            rule_x_p = alt.Chart(pd.DataFrame({'x': [x_mean]})).mark_rule(color='gray', strokeDash=[5,5], opacity=0.5).encode(x='x:Q')
            rule_y_p = alt.Chart(pd.DataFrame({'y': [y_mean]})).mark_rule(color='gray', strokeDash=[5,5], opacity=0.5).encode(y='y:Q')
            
            chart_p = (circles_p + labels_p + rule_x_p + rule_y_p).properties(height=350)
            st.altair_chart(chart_p, use_container_width=True)
            st.caption("↗️ 右上方為真實壓制力極強的「雙重真王牌」；↙️ 左下方為防禦數據較為掙扎的放火區。")
        else: st.info("尚無符合規定局數的投手可產生象限圖。")
# ==========================================
# --- 分頁 2：🏟️ 聯盟賽程中心 (Scores & Schedule) ---
# ==========================================
with tab2:
    import re
    from datetime import datetime
    import time
    import random
    import math

    st.header("🏟️ 聯盟賽程與比分中心 (Scores & Schedule)")
    st.caption("比照 MLB.com 官方介面：已完賽提供 Box Score，未開打賽事可直接展開進行成績登錄。")
    
    get_career_stats()
    df_b_raw = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p_raw = st.session_state.get('df_p_raw', pd.DataFrame())
    
    if '賽事階段' not in df_b_raw.columns: 
        df_b_raw = pd.DataFrame(columns=['賽事階段', '球隊', '得分', '安打', '棒次', '時間戳記', '守位', '球員姓名', '打數', '打點', '四壞球', '三振'])
    if '賽事階段' not in df_p_raw.columns: 
        df_p_raw = pd.DataFrame(columns=['賽事階段', '球隊', '勝敗', '時間戳記', '投手姓名', '局數(整數)', '局數(出局數)', '被安打', '失分', '自責分', '四壞球', '奪三振', '被全壘打', '投球數'])

    latest_s_str = "Season 1"
    if not df_p_raw.empty:
        s_nums = df_p_raw['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]')[0].dropna().astype(int)
        if not s_nums.empty: latest_s_str = f"Season {s_nums.max()}"
            
    if 'has_auto_set_season_tab2' not in st.session_state:
        st.session_state.ss_season = latest_s_str
        st.session_state.has_auto_set_season_tab2 = True

    col_s_ss, _ = st.columns([1, 4])
    with col_s_ss:
        selected_season_ss = st.selectbox("📅 選擇賽季", SEASONS, key="ss_season")
    
    curr_s_num = selected_season_ss.split(" ")[1]
    
    # 讀取全域精準主客場字典
    global_home_dict = st.session_state.get('global_home_dict', {})

    ws_wins = {'LAA': 0, 'LAD': 0}
    if not df_p_raw.empty:
        ws_df = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}] 世界大賽", regex=False)]
        for stg, grp in ws_df.groupby('賽事階段', sort=False):
            if any('勝' in str(x) for x in grp[grp['球隊']=='LAA']['勝敗'].values): ws_wins['LAA'] += 1
            if any('勝' in str(x) for x in grp[grp['球隊']=='LAD']['勝敗'].values): ws_wins['LAD'] += 1
    champ_crowned = (ws_wins['LAA'] >= 4 or ws_wins['LAD'] >= 4)
    games_played_ws = ws_wins['LAA'] + ws_wins['LAD']

    latest_played_idx = -1
    for i, g_name in enumerate(GAME_STAGES):
        full_stage = f"[S{curr_s_num}] {g_name}"
        if not df_b_raw[df_b_raw['賽事階段'] == full_stage].empty or not df_p_raw[df_p_raw['賽事階段'] == full_stage].empty: 
            latest_played_idx = i

    def generate_initials(name):
        clean_name = str(name).replace('.', ' ').replace('-', ' ')
        parts = clean_name.split()
        if len(parts) >= 2: return (parts[0][0] + parts[-1][0]).upper()
        return str(name)[:2].upper()

    def get_pitcher_season_stats(p_name, current_ts, df_p_s):
        p_history = df_p_s[(df_p_s['投手姓名'] == p_name) & (df_p_s['時間戳記'] <= current_ts)]
        w = sum([1 for x in p_history['勝敗'].astype(str) if '勝' in x])
        l = sum([1 for x in p_history['勝敗'].astype(str) if '敗' in x])
        sv = sum([1 for x in p_history['勝敗'].astype(str) if '救援' in x])
        outs = (pd.to_numeric(p_history['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(p_history['局數(出局數)'], errors='coerce').fillna(0)).sum()
        er = pd.to_numeric(p_history['自責分'], errors='coerce').fillna(0).sum()
        h = pd.to_numeric(p_history['被安打'], errors='coerce').fillna(0).sum()
        bb = pd.to_numeric(p_history['四壞球'], errors='coerce').fillna(0).sum()
        
        era = (er * 9) / (outs / 3.0) if outs > 0 else (float('inf') if er > 0 else 0.0)
        whip = (h + bb) / (outs / 3.0) if outs > 0 else 0.0
        return w, l, sv, era, whip

    def get_batter_season_stats(p_name, current_ts, df_b_s):
        hist = df_b_s[(df_b_s['球員姓名'] == p_name) & (df_b_s['時間戳記'] <= current_ts)]
        ab = pd.to_numeric(hist['打數'], errors='coerce').fillna(0).sum()
        h = pd.to_numeric(hist['安打'], errors='coerce').fillna(0).sum()
        bb = pd.to_numeric(hist['四壞球'], errors='coerce').fillna(0).sum()
        pa = pd.to_numeric(hist['打席'], errors='coerce').fillna(0).sum()
        h2 = pd.to_numeric(hist['二壘安打'], errors='coerce').fillna(0).sum()
        h3 = pd.to_numeric(hist['三壘安打'], errors='coerce').fillna(0).sum()
        hr = pd.to_numeric(hist['全壘打'], errors='coerce').fillna(0).sum()
        
        h1 = h - h2 - h3 - hr
        avg = h / max(1, ab) if ab > 0 else 0
        obp = (h + bb) / max(1, pa) if pa > 0 else 0
        slg = (h1 + 2*h2 + 3*h3 + 4*hr) / max(1, ab) if ab > 0 else 0
        return avg, (obp + slg)

    def fmt_rate(val):
        if val >= 1: return f"{val:.3f}"
        return f"{val:.3f}".lstrip('0')

    st.markdown("---")
    df_p_season = df_p_raw[df_p_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)]
    df_b_season = df_b_raw[df_b_raw['賽事階段'].astype(str).str.contains(f"[S{curr_s_num}]", regex=False)]
    
    for i in range(0, len(GAME_STAGES), 2):
        cols = st.columns(2)
        games_in_row = GAME_STAGES[i:i+2]
        row_data = []
        
        # 1. 渲染計分板 (Score Bug)
        for idx, g_name in enumerate(games_in_row):
            with cols[idx]:
                full_stage = f"[S{curr_s_num}] {g_name}"
                is_ws = "世界大賽" in g_name
                
                b_game = df_b_raw[df_b_raw['賽事階段'] == full_stage]
                p_game = df_p_raw[df_p_raw['賽事階段'] == full_stage]
                is_played = not b_game.empty or not p_game.empty
                is_latest = (GAME_STAGES.index(g_name) == latest_played_idx)
                
                home_tm = global_home_dict.get(full_stage, "LAA")
                away_tm = "LAD" if home_tm == "LAA" else "LAA"
                away_col = "#005A9C" if away_tm == "LAD" else "#BA0021"
                home_col = "#BA0021" if home_tm == "LAA" else "#005A9C"
                
                is_cancelled = False
                status_text = "Upcoming"
                if is_ws and not is_played:
                    m_g = re.search(r'G(\d+)', g_name)
                    g_num = int(m_g.group(1)) if m_g else 0
                    if champ_crowned and g_num > games_played_ws:
                        is_cancelled = True
                        status_text = "Cancelled (系列賽結束)"
                    elif not champ_crowned and g_num > max(4, games_played_ws + 1):
                        status_text = "If Necessary (如有需要)"
                
                if is_cancelled:
                    with st.container(border=True):
                        st.markdown(f"<div style='color:#666; font-size:14px; font-weight:bold; text-align:center; padding:30px 0;'>🚫 {g_name} | {status_text}</div>", unsafe_allow_html=True)
                    continue
                
                is_final = (full_stage in st.session_state.completed_games) or (GAME_STAGES.index(g_name) < latest_played_idx)

                with st.container(border=True):
                    if is_played:
                        away_r = pd.to_numeric(b_game[b_game['球隊']==away_tm]['得分'], errors='coerce').fillna(0).sum()
                        home_r = pd.to_numeric(b_game[b_game['球隊']==home_tm]['得分'], errors='coerce').fillna(0).sum()
                        away_h = pd.to_numeric(b_game[b_game['球隊']==away_tm]['安打'], errors='coerce').fillna(0).sum()
                        home_h = pd.to_numeric(b_game[b_game['球隊']==home_tm]['安打'], errors='coerce').fillna(0).sum()
                        
                        if is_final: status_display = f"Final - {g_name}"
                        else: status_display = f"🔴 Live (成績登錄中) - {g_name}"
                        
                        current_ts = p_game['時間戳記'].max() if not p_game.empty else b_game['時間戳記'].max()
                        wp, lp, sv, wp_tm, lp_tm, sv_tm = None, None, None, "", "", ""
                        wp_str, lp_str, sv_str = "", "", ""
                        
                        for _, r in p_game[p_game['勝敗'] != '無'].iterrows():
                            pn, pt = r['投手姓名'], r['球隊']
                            if '勝' in str(r['勝敗']):
                                wp, wp_tm = pn, pt
                                w, l, _, era, _ = get_pitcher_season_stats(pn, current_ts, df_p_season)
                                wp_str = f"({w}-{l}, {'∞' if era == float('inf') else f'{era:.2f}'})"
                            if '敗' in str(r['勝敗']):
                                lp, lp_tm = pn, pt
                                w, l, _, era, _ = get_pitcher_season_stats(pn, current_ts, df_p_season)
                                lp_str = f"({w}-{l}, {'∞' if era == float('inf') else f'{era:.2f}'})"
                            if '救援' in str(r['勝敗']):
                                sv, sv_tm = pn, pt
                                _, _, sv_cnt, _, _ = get_pitcher_season_stats(pn, current_ts, df_p_season)
                                sv_str = f"({sv_cnt})"

                        game_mvp, win_team = "", wp_tm if wp_tm else (home_tm if home_r > away_r else away_tm)
                        if win_team and is_final:
                            cands = []
                            for _, r in b_game[b_game['球隊'] == win_team].iterrows():
                                stats_vals = [pd.to_numeric(r.get(col, 0), errors='coerce') for col in ['打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振']]
                                ab, h, h2, h3, hr, rbi, run, bb, so = [0 if pd.isna(x) else x for x in stats_vals]
                                score = global_game_mvp_score_b(ab, h, h2, h3, hr, rbi, run, bb, so, int(curr_s_num))
                                cands.append({'name': r['球員姓名'], 'score': score, 'raw_rbi': rbi})
                                
                            for _, r in p_game[p_game['球隊'] == win_team].iterrows():
                                o_int = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce')
                                o_dec = pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                                outs = (0 if pd.isna(o_int) else o_int)*3 + (0 if pd.isna(o_dec) else o_dec)
                                ip = outs / 3.0
                                
                                p_vals = [pd.to_numeric(r.get(c, 0), errors='coerce') for c in ['自責分', '被安打', '四壞球', '奪三振']]
                                er, h_allowed, bb_allowed, k = [0 if pd.isna(x) else x for x in p_vals]
                                mvp_w = 1 if '勝' in str(r.get('勝敗','')) else 0
                                mvp_sv = 1 if '救援' in str(r.get('勝敗','')) else 0
                                mvp_hld = 1 if '中繼' in str(r.get('勝敗','')) else 0
                                
                                score = global_game_mvp_score_p(ip, er, h_allowed, bb_allowed, k, mvp_w, mvp_sv, mvp_hld, int(curr_s_num))
                                cands.append({'name': r['投手姓名'], 'score': score, 'raw_rbi': 0})
                                
                            if cands:
                                cands.sort(key=lambda x: (x['score'], x['raw_rbi']), reverse=True)
                                game_mvp = cands[0]['name']
                            
                        def gen_badge(title, name, team, stats_txt):
                            if not name: return ""
                            color = "#BA0021" if team == "LAA" else "#005A9C"
                            bg_color = "#D4AF37" if "MVP" in title else color
                            txt_color = "#000" if "MVP" in title else "white"
                            init = generate_initials(name)
                            return f"<div style='display:inline-flex; align-items:center; margin-right:15px; margin-top:4px;'><span style='font-size:11px; color:#aaa; margin-right:4px;'>{title}</span><span style='display:inline-block; width:20px; height:20px; border-radius:50%; background-color:{bg_color}; color:{txt_color}; text-align:center; line-height:20px; font-size:9px; font-weight:bold; margin-right:5px;'>{init}</span><span style='font-size:12px; font-weight:bold; color:#eee;'>{name}</span><span style='font-size:11px; color:#888; margin-left:5px;'>{stats_txt}</span></div>"
                            
                        pitcher_html = f"<div style='margin-top:12px; border-top:1px solid #333; padding-top:10px; display:flex; flex-wrap:wrap;'>{gen_badge('W', wp, wp_tm, wp_str)}{gen_badge('L', lp, lp_tm, lp_str)}{gen_badge('SV', sv, sv_tm, sv_str)}{gen_badge('🏅 MVP', game_mvp, win_team, '')}</div>" if (wp or lp or game_mvp) else ""
                        
                        # ✨ 獲勝隊伍比分金黃色高亮！
                        away_score_style = "color:#ffcc00; font-weight:900; font-size:24px;" if away_r > home_r else "color:white; font-weight:bold; font-size:22px;"
                        home_score_style = "color:#ffcc00; font-weight:900; font-size:24px;" if home_r > away_r else "color:white; font-weight:bold; font-size:22px;"
                        
                        runs_html = f"<div style='{away_score_style} width: 30px; text-align:right;'>{int(away_r)}</div><div style='font-size:12px; color:#aaa; width: 30px; text-align:right; margin-left:10px;'>{int(away_h)} H</div>"
                        runs_html2 = f"<div style='{home_score_style} width: 30px; text-align:right;'>{int(home_r)}</div><div style='font-size:12px; color:#aaa; width: 30px; text-align:right; margin-left:10px;'>{int(home_h)} H</div>"
                    else:
                        status_display = f"{status_text} - {g_name}"
                        runs_html = f"<div style='font-size:12px; color:#aaa; margin-top:2px;'></div>"
                        runs_html2 = f"<div style='font-size:12px; color:#aaa; margin-top:2px;'></div>"
                        pitcher_html = ""
                        game_mvp = ""

                    score_bug = f"""
                    <div style='background-color:#161618; padding:15px; border-radius:8px; font-family:sans-serif;'>
                        <div style='color:#aaa; font-size:12px; margin-bottom:12px; font-weight:bold;'>{status_display}</div>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;'>
                            <div style='display:flex; align-items:center;'>
                                <div style='width:24px; height:24px; border-radius:50%; background-color:{away_col}; margin-right:12px;'></div>
                                <div style='font-size:18px; font-weight:bold; color:white;'>{away_tm}</div>
                            </div>
                            <div style='display:flex; align-items:center;'>{runs_html}</div>
                        </div>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;'>
                            <div style='display:flex; align-items:center;'>
                                <div style='width:24px; height:24px; border-radius:50%; background-color:{home_col}; margin-right:12px;'></div>
                                <div style='font-size:18px; font-weight:bold; color:white;'>{home_tm}</div>
                            </div>
                            <div style='display:flex; align-items:center;'>{runs_html2}</div>
                        </div>
                        {pitcher_html}
                    </div>
                    """
                    st.markdown(score_bug, unsafe_allow_html=True)
                    
                    row_data.append({
                        "g_name": g_name, "full_stage": full_stage, "is_played": is_played, "is_final": is_final,
                        "is_latest": is_latest, "b_game": b_game, "p_game": p_game, 
                        "away_tm": away_tm, "home_tm": home_tm, "game_mvp": game_mvp
                    })
        
        # 2. 渲染全寬展開區塊 (Full-Width Expander)
        for g_data in row_data:
            g_name = g_data['g_name']
            full_stage = g_data['full_stage']
            is_played = g_data['is_played']
            is_final = g_data['is_final']
            is_latest = g_data['is_latest']
            b_game = g_data['b_game']
            p_game = g_data['p_game']
            away_tm = g_data['away_tm']
            home_tm = g_data['home_tm']
            game_mvp = g_data.get('game_mvp', '')
            
            if is_played and not is_final: exp_label = f"🔴 Live (成績登錄中) - {g_name}"
            elif is_played and is_final: exp_label = f"📊 查看 Box Score - {g_name}"
            else: exp_label = f"✍️ 登錄賽事成績與 AI 戰報 - {g_name}"
                
            with st.expander(exp_label, expanded=is_latest):
                show_mode = "Box Score"
                if is_played:
                    if not is_final:
                        c_rad, _ = st.columns([3, 5])
                        with c_rad:
                            mode_sel = st.radio("模式切換", ["📊 賽事 Box Score", "✍️ 繼續登錄 / 修改成績"], index=1, horizontal=True, key=f"mode_{full_stage}", label_visibility="collapsed")
                            show_mode = "Box Score" if "Box Score" in mode_sel else "Input"
                    else:
                        show_mode = "Box Score"
                else:
                    show_mode = "Input"
                    
                if show_mode == "Box Score" and is_played:
                    st.markdown("""
                    <style>
                    .box-table table { width: 100%; font-size: 13px; text-align: right; border-collapse: collapse; }
                    .box-table th { background-color: #222; color: white; text-align: right !important; padding: 6px; border-bottom: 2px solid #555; }
                    .box-table th:first-child, .box-table td:first-child { text-align: left !important; }
                    .box-table td { padding: 6px; border-bottom: 1px solid #333; }
                    </style>
                    """, unsafe_allow_html=True)
                    
                    tab_away, tab_home = st.tabs([f"✈️ {away_tm} (客隊)", f"🏠 {home_tm} (主隊)"])
                    for tm, tab_col in zip([away_tm, home_tm], [tab_away, tab_home]):
                        with tab_col:
                            st.markdown(f"<h5 style='color:{'#BA0021' if tm=='LAA' else '#005A9C'}; margin-top:10px;'>{tm} Batters</h5>", unsafe_allow_html=True)
                            b_tm = b_game[b_game['球隊'] == tm].copy()
                            if not b_tm.empty:
                                b_tm['棒次_num'] = pd.to_numeric(b_tm['棒次'], errors='coerce').fillna(99.0)
                                b_tm = b_tm.sort_values(['棒次_num', '時間戳記'])
                                
                                b_tm['AVG'], b_tm['OPS'], b_tm['TB'] = "", "", 0
                                for idx, row in b_tm.iterrows():
                                    avg, ops = get_batter_season_stats(row['球員姓名'], row['時間戳記'], df_b_season)
                                    tb = pd.to_numeric(row['安打']) + pd.to_numeric(row['二壘安打']) + pd.to_numeric(row['三壘安打'])*2 + pd.to_numeric(row['全壘打'])*3
                                    b_tm.at[idx, 'AVG'] = fmt_rate(avg)
                                    b_tm.at[idx, 'OPS'] = fmt_rate(ops)
                                    b_tm.at[idx, 'TB'] = int(tb)
                                
                                def fmt_name(r):
                                    ord_str = str(r.get('棒次', ''))
                                    pos = r.get('守位', '')
                                    nm = r['球員姓名']
                                    mvp_tag = " <span title='單場 MVP' style='font-size:14px;'>🏅</span>" if nm == game_mvp else ""
                                    if '.' in ord_str and not ord_str.endswith('.0') and ord_str != '':
                                        return f"<span style='margin-left: 20px; color: #999; font-size: 13px;'>{pos}-{nm}</span>{mvp_tag}"
                                    return f"<b>{nm}</b> <span style='color: #888; font-size: 11px;'>{pos}</span>{mvp_tag}"
                                    
                                b_tm['打者'] = b_tm.apply(fmt_name, axis=1)
                                b_table = b_tm[['打者', '打數', '得分', '安打', '打點', '四壞球', '三振', '二壘安打', '三壘安打', '全壘打', 'TB', '盜壘', 'AVG', 'OPS']].copy()
                                b_table.columns = ['Batters', 'AB', 'R', 'H', 'RBI', 'BB', 'SO', '2B', '3B', 'HR', 'TB', 'SB', 'AVG', 'OPS']
                                html_b = b_table.to_html(escape=False, index=False)
                                st.markdown(f"<div class='box-table'>{html_b}</div>", unsafe_allow_html=True)
                            else: st.caption("尚無紀錄")
                            
                            st.markdown(f"<h5 style='color:{'#BA0021' if tm=='LAA' else '#005A9C'}; margin-top:20px;'>{tm} Pitchers</h5>", unsafe_allow_html=True)
                            p_tm = p_game[p_game['球隊'] == tm].copy()
                            if not p_tm.empty:
                                p_tm = p_tm.sort_values('時間戳記')
                                
                                p_tm['S_ERA'], p_tm['S_WHIP'] = "0.00", "0.00"
                                for idx, row in p_tm.iterrows():
                                    _, _, _, era, whip = get_pitcher_season_stats(row['投手姓名'], row['時間戳記'], df_p_season)
                                    p_tm.at[idx, 'S_ERA'] = "∞" if era == float('inf') else f"{era:.2f}"
                                    p_tm.at[idx, 'S_WHIP'] = f"{whip:.2f}"

                                def fmt_p_name(r):
                                    nm = r['投手姓名']
                                    res = []
                                    if '勝' in str(r.get('勝敗','')): res.append('W')
                                    if '敗' in str(r.get('勝敗','')): res.append('L')
                                    if '救援' in str(r.get('勝敗','')): res.append('SV')
                                    if '中繼' in str(r.get('勝敗','')): res.append('H')
                                    res_str = f" <span style='color:#ff4b4b; font-size:11px;'>({','.join(res)})</span>" if res else ""
                                    mvp_tag = " <span title='單場 MVP' style='font-size:14px;'>🏅</span>" if nm == game_mvp else ""
                                    return f"<b>{nm}</b>{res_str}{mvp_tag}"
                                    
                                p_tm['投手'] = p_tm.apply(fmt_p_name, axis=1)
                                p_tm['IP'] = p_tm.apply(lambda r: f"{int(r['局數(整數)'])}.{int(r['局數(出局數)'])}", axis=1)
                                p_table = p_tm[['投手', 'IP', '被安打', '失分', '自責分', '四壞球', '奪三振', '被全壘打', '投球數', 'S_ERA', 'S_WHIP']].copy()
                                p_table.columns = ['Pitchers', 'IP', 'H', 'R', 'ER', 'BB', 'SO', 'HR', 'PC', 'ERA', 'WHIP']
                                html_p = p_table.to_html(escape=False, index=False)
                                st.markdown(f"<div class='box-table'>{html_p}</div>", unsafe_allow_html=True)
                            else: st.caption("尚無紀錄")
                            
                elif show_mode == "Input":
                    cached_players_b = get_player_list("打擊單場紀錄")
                    cached_players_p = get_player_list("投手單場紀錄")
                    
                    tab_in_b, tab_in_p = st.tabs(["🏏 登錄打線", "🥎 登錄投手"])
                    with tab_in_b:
                        team_b = st.selectbox("所屬球隊", [away_tm, home_tm], key=f"tm_b_{full_stage}")
                        
                        inputted_b = b_game[b_game['球隊'] == team_b]['球員姓名'].tolist()
                        avail_batters = [p for p in cached_players_b.get(team_b, []) if p not in inputted_b]
                        
                        c_b_top1, c_b_top2, c_b_top3, c_b_top4 = st.columns([1.5, 1, 1, 1])
                        with c_b_top1:
                            sel_p_b = st.selectbox("選擇打者", ["➕ 手動輸入..."] + avail_batters, key=f"sel_b_{full_stage}")
                            player_b = st.text_input("輸入姓名", key=f"txt_b_{full_stage}") if sel_p_b == "➕ 手動輸入..." else sel_p_b
                            
                            if player_b != st.session_state.get(f"prev_b_{full_stage}", ""):
                                st.session_state[f"prev_b_{full_stage}"] = player_b
                                if not df_b_raw.empty and player_b in df_b_raw['球員姓名'].values:
                                    last_pos = df_b_raw[df_b_raw['球員姓名'] == player_b].sort_values('時間戳記', ascending=False).iloc[0]['守位']
                                    if last_pos in POSITIONS: st.session_state[f"pos_b_{full_stage}"] = last_pos

                        if f"ord_b_{full_stage}" not in st.session_state: st.session_state[f"ord_b_{full_stage}"] = 1.0
                        
                        if st.session_state.get(f"advance_ord_{full_stage}"):
                            try:
                                cv = st.session_state[f"ord_b_{full_stage}"]
                                if cv % 1 == 0: st.session_state[f"ord_b_{full_stage}"] = float(int(cv) + 1)
                            except: pass
                            st.session_state[f"advance_ord_{full_stage}"] = False

                        with c_b_top2: cur_order_b = st.number_input("棒次", min_value=1.0, max_value=9.9, step=1.0, key=f"ord_b_{full_stage}")
                        with c_b_top3: cur_pos_b = st.selectbox("守位", POSITIONS, key=f"pos_b_{full_stage}")
                        with c_b_top4:
                            st.markdown("<br>", unsafe_allow_html=True)
                            if st.button("⚾ 儲存打擊", type="primary", use_container_width=True, key=f"btn_save_b_{full_stage}"):
                                if player_b == "": st.error("❌ 請填寫姓名！")
                                elif st.session_state[f"h_{full_stage}"] > st.session_state[f"ab_{full_stage}"]: st.error("❌ 安打大於打數！")
                                else:
                                    sh = get_sheet()
                                    if sh:
                                        sh.worksheet("打擊單場紀錄").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), full_stage, team_b, player_b, st.session_state[f"pa_{full_stage}"], st.session_state[f"ab_{full_stage}"], st.session_state[f"h_{full_stage}"], st.session_state[f"tb2_{full_stage}"], st.session_state[f"tb3_{full_stage}"], st.session_state[f"hr_{full_stage}"], st.session_state[f"rbi_{full_stage}"], st.session_state[f"r_{full_stage}"], st.session_state[f"bb_{full_stage}"], st.session_state[f"so_{full_stage}"], st.session_state[f"sb_{full_stage}"], cur_pos_b, str(cur_order_b)])
                                        st.success(f"✅ {player_b} 登錄成功！")
                                        get_raw_records.clear()
                                        
                                        st.session_state[f"advance_ord_{full_stage}"] = True
                                        for k in ['h', 'rbi', 'r', 'hr', 'bb', 'so', 'sb', 'tb2', 'tb3']:
                                            st.session_state[f"{k}_{full_stage}"] = 0
                                            
                                        import time
                                        time.sleep(0.4)
                                        st.rerun()
                        
                        cb1, cb2, cb3, cb4 = st.columns(4)
                        pa = cb1.number_input("打席", min_value=0, step=1, key=f"pa_{full_stage}")
                        ab = cb2.number_input("打數", min_value=0, step=1, key=f"ab_{full_stage}")
                        h = cb3.number_input("安打", min_value=0, step=1, key=f"h_{full_stage}")
                        rbi = cb4.number_input("打點", min_value=0, step=1, key=f"rbi_{full_stage}")
                        
                        cb5, cb6, cb7, cb8 = st.columns(4)
                        run = cb5.number_input("得分", min_value=0, step=1, key=f"r_{full_stage}")
                        hr = cb6.number_input("全壘打", min_value=0, step=1, key=f"hr_{full_stage}")
                        bb = cb7.number_input("四壞", min_value=0, step=1, key=f"bb_{full_stage}")
                        so = cb8.number_input("三振", min_value=0, step=1, key=f"so_{full_stage}")
                        
                        cb9, cb10, cb11, cb12 = st.columns(4)
                        sb = cb9.number_input("盜壘", min_value=0, step=1, key=f"sb_{full_stage}")
                        tb2 = cb10.number_input("二安", min_value=0, step=1, key=f"tb2_{full_stage}")
                        tb3 = cb11.number_input("三安", min_value=0, step=1, key=f"tb3_{full_stage}")

                    with tab_in_p:
                        team_p = st.selectbox("所屬球隊", [away_tm, home_tm], key=f"tm_p_{full_stage}")
                        
                        inputted_p = p_game[p_game['球隊'] == team_p]['投手姓名'].tolist()
                        avail_pitchers = [p for p in cached_players_p.get(team_p, []) if p not in inputted_p]
                        
                        existing_res = p_game['勝敗'].astype(str).tolist() if not p_game.empty else []
                        p_res_options = ["無"]
                        if not any('勝' in x for x in existing_res): p_res_options.append("勝")
                        if not any('敗' in x for x in existing_res): p_res_options.append("敗")
                        if not any('救援' in x for x in existing_res): p_res_options.append("救援")
                        p_res_options.append("中繼")

                        c_p_top1, c_p_top2, c_p_top3, c_p_top4 = st.columns([1.5, 1, 1, 1])
                        with c_p_top1:
                            sel_p_p = st.selectbox("選擇投手", ["➕ 手動輸入..."] + avail_pitchers, key=f"sel_p_{full_stage}")
                            player_p = st.text_input("輸入姓名", key=f"txt_p_{full_stage}") if sel_p_p == "➕ 手動輸入..." else sel_p_p
                            
                            if player_p != st.session_state.get(f"prev_p_{full_stage}", ""):
                                st.session_state[f"prev_p_{full_stage}"] = player_p
                                if not df_p_raw.empty and player_p in df_p_raw['投手姓名'].values:
                                    last_role = df_p_raw[df_p_raw['投手姓名'] == player_p].sort_values('時間戳記', ascending=False).iloc[0]['角色']
                                    if last_role in ROLES_P: st.session_state[f"role_p_{full_stage}"] = last_role

                        with c_p_top2: p_res = st.selectbox("勝敗", p_res_options, key=f"res_p_{full_stage}")
                        with c_p_top3: cur_role_p = st.selectbox("角色", ROLES_P, key=f"role_p_{full_stage}")
                        with c_p_top4:
                            st.markdown("<br>", unsafe_allow_html=True)
                            if st.button("🥎 儲存投球", type="primary", use_container_width=True, key=f"btn_save_p_{full_stage}"):
                                if player_p == "": st.error("❌ 請填寫姓名！")
                                elif st.session_state[f"erp_{full_stage}"] > st.session_state[f"rp_{full_stage}"]: st.error("❌ 責失大於失分！")
                                else:
                                    sh = get_sheet()
                                    if sh:
                                        sh.worksheet("投手單場紀錄").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), full_stage, team_p, player_p, p_res, st.session_state[f"ipf_{full_stage}"], st.session_state[f"ipo_{full_stage}"], st.session_state[f"bfp_{full_stage}"], st.session_state[f"npp_{full_stage}"], st.session_state[f"hp_{full_stage}"], st.session_state[f"hrp_{full_stage}"], st.session_state[f"bbp_{full_stage}"], st.session_state[f"sop_{full_stage}"], st.session_state[f"rp_{full_stage}"], st.session_state[f"erp_{full_stage}"], cur_role_p])
                                        st.success(f"✅ {player_p} 登錄成功！")
                                        get_raw_records.clear()
                                        for k in ['ipf', 'ipo', 'bfp', 'sop', 'bbp', 'rp', 'erp', 'hp', 'hrp', 'npp']:
                                            st.session_state[f"{k}_{full_stage}"] = 0
                                        import time
                                        time.sleep(0.4)
                                        st.rerun()
                                        
                        cpp1, cpp2, cpp3, cpp4 = st.columns(4)
                        ip_full = cpp1.number_input("局數(整)", min_value=0, step=1, key=f"ipf_{full_stage}")
                        ip_outs = cpp2.number_input("出局數", min_value=0, max_value=2, step=1, key=f"ipo_{full_stage}")
                        bf_p = cpp3.number_input("打者數", min_value=0, step=1, key=f"bfp_{full_stage}")
                        so_p = cpp4.number_input("奪三振", min_value=0, step=1, key=f"sop_{full_stage}")
                        
                        cpp5, cpp6, cpp7, cpp8 = st.columns(4)
                        bb_p = cpp5.number_input("四壞球", min_value=0, step=1, key=f"bbp_{full_stage}")
                        r_p = cpp6.number_input("失分", min_value=0, step=1, key=f"rp_{full_stage}")
                        er_p = cpp7.number_input("自責分", min_value=0, step=1, key=f"erp_{full_stage}")
                        h_p = cpp8.number_input("被安打", min_value=0, step=1, key=f"hp_{full_stage}")
                        
                        cpp9, cpp10, _, _ = st.columns(4)
                        hr_p = cpp9.number_input("被全壘打", min_value=0, step=1, key=f"hrp_{full_stage}")
                        np_pitch = cpp10.number_input("投球數", min_value=0, step=1, key=f"npp_{full_stage}")

                    st.markdown("---")
                    if full_stage not in st.session_state.completed_games:
                        st.info("💡 **賽事鎖定區**：如果您已登錄完所有打者與投手成績，請於下方勾選確認並鎖定賽事，系統將為您產生 Box Score。")
                        if st.checkbox("⚠️ 警告：我已確認兩隊所有先發/替換打者、以及牛棚投手的單場數據皆全數登錄完畢", key=f"lock_confirm_{full_stage}"):
                            if st.button("🔒 確定宣告本場賽事正式結束 (Finalize Game)", type="primary", use_container_width=True, key=f"final_btn_{full_stage}"):
                                st.session_state.completed_games.append(full_stage)
                                save_settings()
                                st.success(f"🎉 封裝成功！{g_name} 成績已全面鎖定。")
                                get_raw_records.clear()
                                import time
                                time.sleep(1)
                                st.rerun()
                                
                    # =======================================================
                    # 🌟 AI 打線與賽前戰報 (僅限下一場即將開打的賽事) 🌟
                    # =======================================================
                    is_next_upcoming = (not is_played) and (GAME_STAGES.index(g_name) == latest_played_idx + 1)
                    if is_next_upcoming:
                        st.markdown("---")
                        st.markdown(f"### 🤖 【{g_name}】 AI 戰情室與賽前準備")
                        
                        wr_season = selected_season_ss
                        is_ws_mode = "世界大賽" in g_name
                        away_team = away_tm
                        home_team = home_tm
                        # ✨ 徹底解決 NameError，直接判斷是否為主隊
                        is_laa_home_ai = (home_tm == "LAA") 
                        
                        _laa_p = st.session_state.pitchers.get("LAA", "")
                        laa_sp_val = _laa_p if _laa_p else "未指定"
                        _lad_p = st.session_state.pitchers.get("LAD", "")
                        lad_sp_val = _lad_p if _lad_p else "未指定"
                        
                        def get_season_data_t2(target_season, target_stage=""):
                            df_b_raw_local = st.session_state.get('df_b_raw', pd.DataFrame())
                            df_p_raw_local = st.session_state.get('df_p_raw', pd.DataFrame())
                            if df_b_raw_local.empty and df_p_raw_local.empty: return {}, {}
                            
                            prefix = ""
                            if target_season != "十年總成績":
                                s_num = target_season.split(" ")[1]
                                prefix = f"[S{s_num}]"

                            b_sub = df_b_raw_local[df_b_raw_local['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_b_raw_local
                            p_sub = df_p_raw_local[df_p_raw_local['賽事階段'].astype(str).str.contains(prefix, regex=False)] if prefix else df_p_raw_local
                            
                            if target_stage:
                                b_sub = b_sub[b_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]
                                p_sub = p_sub[p_sub['賽事階段'].astype(str).str.contains(target_stage, regex=False)]

                            b_dict, p_dict = {'LAA': {}, 'LAD': {}}, {'LAA': {}, 'LAD': {}}
                            
                            if not b_sub.empty:
                                b_clean = b_sub.copy()
                                for col in ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振', '盜壘']:
                                    if col not in b_clean.columns: b_clean[col] = 0
                                    b_clean[col] = pd.to_numeric(b_clean[col], errors='coerce').fillna(0)
                                    
                                total_pa = b_clean['打席'].sum()
                                lg_1b = b_clean['安打'].sum() - b_clean['二壘安打'].sum() - b_clean['三壘安打'].sum() - b_clean['全壘打'].sum()
                                lg_woba_num = 0.69 * b_clean['四壞球'].sum() + 0.88 * lg_1b + 1.25 * b_clean['二壘安打'].sum() + 1.59 * b_clean['三壘安打'].sum() + 2.06 * b_clean['全壘打'].sum()
                                lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.001

                                agg_b = b_clean.groupby('球員姓名').sum(numeric_only=True).reset_index()
                                last_team_b = b_clean.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                                
                                for _, row in agg_b.iterrows():
                                    name = row['球員姓名']
                                    team = last_team_b.get(name, 'Unknown')
                                    avg = row['安打'] / max(1, row['打數'])
                                    obp = (row['安打'] + row['四壞球']) / max(1, row['打席'])
                                    b_1b = row['安打'] - row['二壘安打'] - row['三壘安打'] - row['全壘打']
                                    xbh = row['二壘安打'] + row['三壘安打'] + row['全壘打'] 
                                    woba = (0.69 * row['四壞球'] + 0.88 * b_1b + 1.25 * row['二壘安打'] + 1.59 * row['三壘安打'] + 2.06 * row['全壘打']) / max(1, row['打席'])
                                    wrc_plus = global_calc_wrc_plus(woba, lg_woba)
                                    pos = b_clean[b_clean['球員姓名']==name].sort_values('時間戳記').iloc[-1]['守位'] if '守位' in b_clean.columns else 'DH'
                                    ewar = global_calc_batter_ewar(wrc_plus, pos, row['打席'])
                                    k_pct = (row['三振'] / max(1, row['打席'])) * 100
                                    bb_pct = (row['四壞球'] / max(1, row['打席'])) * 100
                                    iso = (((b_1b) + 2*row['二壘安打'] + 3*row['三壘安打'] + 4*row['全壘打']) / max(1, row['打數'])) - avg
                                    babip = (row['安打'] - row['全壘打']) / max(1, (row['打數'] - row['三振'] - row['全壘打']))
                                    
                                    if team not in b_dict: b_dict[team] = {}
                                    b_dict[team][name] = {
                                        'OPS+': wrc_plus, 'wRC+': wrc_plus, 'eWAR': ewar, 'AVG': avg, 'OBP': obp, 'HR': row['全壘打'],
                                        'ISO': iso, 'K%': k_pct, 'BB%': bb_pct, 'BABIP': babip, 'SB': row.get('盜壘', 0), 'PA': row['打席'],
                                        'K': row['三振'], 'BB': row['四壞球'], 'AB': row['打數'], 'H': row['安打'], 'XBH': xbh
                                    }

                            if not p_sub.empty:
                                p_clean = p_sub.copy()
                                for col in ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '奪三振', '失分', '自責分', '四壞球']:
                                    if col not in p_clean.columns: p_clean[col] = 0
                                    p_clean[col] = pd.to_numeric(p_clean[col], errors='coerce').fillna(0)
                                    
                                lg_ip_total = ((p_clean['局數(整數)'].sum() * 3) + p_clean['局數(出局數)'].sum()) / 3.0
                                lg_era_baseline = (p_clean['自責分'].sum() * 9) / lg_ip_total if lg_ip_total > 0 else 10.60
                                
                                agg_p = p_clean.groupby('投手姓名').sum(numeric_only=True).reset_index()
                                last_team_p = p_clean.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
                                
                                for _, row in agg_p.iterrows():
                                    name = row['投手姓名']
                                    team = last_team_p.get(name, 'Unknown')
                                    ip_calc = (row['局數(整數)'] * 3 + row['局數(出局數)']) / 3.0
                                    era = (row['自責分'] * 9) / max(1, ip_calc) if ip_calc > 0 else float('inf') if row['自責分'] > 0 else 0.0
                                    fip = (((13 * row['被全壘打']) + (3 * row['四壞球']) - (2 * row['奪三振'])) / max(1, ip_calc)) + 3.10 if ip_calc > 0 else float('inf') if (13*row['被全壘打']+3*row['四壞球']-2*row['奪三振'])>0 else 3.10
                                    
                                    ewar = global_calc_pitcher_ewar(era, fip, ip_calc, lg_era_baseline, int(wr_season.split(' ')[1]) if wr_season != "十年總成績" else 1)
                                    whip = (row['被安打'] + row['四壞球']) / max(1, ip_calc)
                                    k9 = (row['奪三振'] * 9) / max(1, ip_calc)
                                    p_ip = row['投球數'] / max(0.1, ip_calc)
                                    
                                    if team not in p_dict: p_dict[team] = {}
                                    p_dict[team][name] = {
                                        'ERA': era, 'eWAR': ewar, 'K': row['奪三振'], 'FIP': fip,
                                        'WHIP': whip, 'K/9': k9, 'P/IP': p_ip, 'IP': ip_calc, 'NP': row['投球數'],
                                        'BF': row.get('打者數', 0), 'BB': row['四壞球'], 'H': row['被安打'], 'HR': row['被全壘打']
                                    }

                            return b_dict, p_dict

                        reg_b_stats, reg_p_stats = get_season_data_t2(wr_season, "例行賽")
                        ws_b_stats, ws_p_stats = get_season_data_t2(wr_season, "世界大賽")

                        if is_ws_mode:
                            curr_b_stats, curr_p_stats = ws_b_stats, ws_p_stats
                        else:
                            curr_b_stats, curr_p_stats = reg_b_stats, reg_p_stats
                            
                        display_b_stats = curr_b_stats
                        display_p_stats = curr_p_stats

                        prev_season_str = "十年總成績"
                        if wr_season != "十年總成績":
                            curr_s_num_int = int(wr_season.split(" ")[1])
                            if curr_s_num_int > 1: prev_season_str = f"Season {curr_s_num_int - 1}"
                        prev_b_stats, prev_p_stats = get_season_data_t2(prev_season_str)
                        
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
                        
                        if is_ws_mode:
                            dyn_pa_limit = 3.0 
                            dyn_ip_limit = 1.0 
                        else:
                            dyn_pa_limit = max(1.0, team_games_eval * 1.0)
                            dyn_ip_limit = max(0.1, team_games_eval * 0.33)

                        # =======================================================
                        # ✨ 核心升級：AI 自動排線 (跨隊伍合併計算 + 現代棒球思維)
                        # =======================================================
                        DEFAULT_9_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
                        if 'lineups' not in st.session_state or type(st.session_state.lineups) is not dict: st.session_state.lineups = {}
                        if 'lineup_pos' not in st.session_state or type(st.session_state.lineup_pos) is not dict: st.session_state.lineup_pos = {}

                        for team in TEAMS:
                            if team not in st.session_state.lineups: st.session_state.lineups[team] = ["未指定"] * 9
                            if team not in st.session_state.lineup_pos: st.session_state.lineup_pos[team] = list(DEFAULT_9_POS)
                            if len(set(st.session_state.lineup_pos[team])) < 9: st.session_state.lineup_pos[team] = list(DEFAULT_9_POS)

                        def auto_lineup_smart_v48(team_name, is_home):
                            s_prefix = "" if wr_season == "十年總成績" else f"[S{wr_season.split(' ')[1]}]"
                            df_b_raw_local = st.session_state.get('df_b_raw', pd.DataFrame())
                            if df_b_raw_local.empty: return {i: {'name': '未指定', 'pos': DEFAULT_9_POS[i-1]} for i in range(1, 10)}
                            
                            # 找出現在真正穿這件球衣的人
                            last_team_map = df_b_raw_local.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
                            current_roster = [n for n, t in last_team_map.items() if t == team_name]
                            if not current_roster: return {i: {'name': '未指定', 'pos': DEFAULT_9_POS[i-1]} for i in range(1, 10)}
                            
                            rs_df = df_b_raw_local[(df_b_raw_local['球員姓名'].isin(current_roster)) & 
                                                   (df_b_raw_local['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) &
                                                   (df_b_raw_local['賽事階段'].astype(str).str.contains("例行賽", regex=False))]
                                                   
                            ws_df_curr = df_b_raw_local[(df_b_raw_local['球員姓名'].isin(current_roster)) & 
                                                        (df_b_raw_local['賽事階段'].astype(str).str.contains(s_prefix, regex=False)) &
                                                        (df_b_raw_local['賽事階段'].astype(str).str.contains("世界大賽", regex=False))]
                                                        
                            ws_df_all = df_b_raw_local[(df_b_raw_local['球員姓名'].isin(current_roster)) & 
                                                       (df_b_raw_local['賽事階段'].astype(str).str.contains("世界大賽", regex=False))]

                            if rs_df.empty:
                                return {i: {'name': '未指定', 'pos': DEFAULT_9_POS[i-1]} for i in range(1, 10)}

                            def calc_wrc(df, dummy_pa=10):
                                if df.empty: return pd.DataFrame()
                                df_clean = df.copy()
                                numeric_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '四壞球', '三振', '得分', '打點']
                                for col in numeric_cols:
                                    if col not in df_clean.columns: df_clean[col] = 0
                                    df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0)
                                        
                                agg = df_clean.groupby('球員姓名').sum(numeric_only=True).reset_index()
                                agg['woba_num'] = 0.69 * agg['四壞球'] + 0.88 * (agg['安打'] - agg['二壘安打'] - agg['三壘安打'] - agg['全壘打']) + 1.25 * agg['二壘安打'] + 1.59 * agg['三壘安打'] + 2.06 * agg['全壘打']
                                agg['wRC+'] = (((agg['woba_num'] + 0.320 * dummy_pa) / (agg['打席'] + dummy_pa)) / 0.320 * 100).astype(int)
                                return agg[['球員姓名', 'wRC+', '打席']].set_index('球員姓名')

                            base_scores = calc_wrc(rs_df, dummy_pa=10)
                            
                            _home_dict = st.session_state.get('global_home_dict', {})
                            s_df_loc = rs_df.copy()
                            s_df_loc['Loc'] = s_df_loc.apply(lambda r: 'Home' if _home_dict.get(str(r['賽事階段']),'') == r['球隊'] else 'Away', axis=1)
                            target_loc = 'Home' if is_home else 'Away'
                            loc_scores = calc_wrc(s_df_loc[s_df_loc['Loc'] == target_loc], dummy_pa=5)
                            
                            recent_pool = ws_df_curr if is_ws_mode and not ws_df_curr.empty else rs_df
                            s_df_rec = recent_pool.sort_values('時間戳記', ascending=False)
                            rec_stages = s_df_rec['賽事階段'].unique()[:5]
                            rec_scores = calc_wrc(s_df_rec[s_df_rec['賽事階段'].isin(rec_stages)], dummy_pa=5)
                            
                            clutch_scores = calc_wrc(ws_df_all, dummy_pa=5) if is_ws_mode else pd.DataFrame()
                            eligibility = df_b_raw_local.groupby('球員姓名')['守位'].unique().to_dict()
                            final_scores = {}
                            
                            for p in base_scores.index:
                                b_val = base_scores.loc[p, 'wRC+']
                                l_val = loc_scores.loc[p, 'wRC+'] if not loc_scores.empty and p in loc_scores.index and loc_scores.loc[p, '打席'] >= 5 else b_val
                                r_val = rec_scores.loc[p, 'wRC+'] if not rec_scores.empty and p in rec_scores.index and rec_scores.loc[p, '打席'] >= 3 else b_val
                                
                                if is_ws_mode:
                                    c_val = clutch_scores.loc[p, 'wRC+'] if not clutch_scores.empty and p in clutch_scores.index and clutch_scores.loc[p, '打席'] >= 5 else b_val
                                    weighted_score = (b_val * 0.35) + (r_val * 0.25) + (l_val * 0.10) + (c_val * 0.30)
                                else:
                                    weighted_score = (b_val * 0.50) + (r_val * 0.30) + (l_val * 0.20)
                                    
                                final_scores[p] = weighted_score

                            sorted_players = sorted(final_scores.keys(), key=lambda x: final_scores[x], reverse=True)
                            final_9_match = {} 
                            remaining_players = sorted_players.copy()
                            
                            for pos in DEFAULT_9_POS:
                                if pos == "DH": continue
                                for p in remaining_players:
                                    if pos in eligibility.get(p, []):
                                        final_9_match[p] = pos
                                        remaining_players.remove(p)
                                        break
                                        
                            for pos in DEFAULT_9_POS:
                                if pos not in final_9_match.values():
                                    if remaining_players: final_9_match[remaining_players.pop(0)] = pos

                            best_9_names = list(final_9_match.keys())
                            best_9_df = pd.DataFrame([{'球員姓名': p, 'Score': final_scores[p]} for p in best_9_names]).sort_values('Score', ascending=False).reset_index(drop=True)
                            
                            modern_mapping = {1: 3, 2: 0, 3: 2, 4: 1, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}
                            
                            temp_lineup = {}
                            for order_idx in range(1, 10):
                                rank_idx = modern_mapping[order_idx]
                                if rank_idx < len(best_9_df):
                                    new_n = best_9_df.iloc[rank_idx]['球員姓名']
                                    new_p = final_9_match[new_n]
                                else:
                                    new_n, new_p = "未指定", "DH"
                                temp_lineup[order_idx] = {'name': new_n, 'pos': new_p}
                                
                            dh_idx = next((k for k, v in temp_lineup.items() if v['pos'] == 'DH'), None)
                            if dh_idx and dh_idx >= 7:
                                dh_data = temp_lineup[dh_idx]
                                for i in range(dh_idx, 6, -1): temp_lineup[i] = temp_lineup[i-1]
                                temp_lineup[6] = dh_data
                                
                            for order_idx in range(1, 10):
                                st.session_state.lineups[team_name][order_idx-1] = temp_lineup[order_idx]['name'] if temp_lineup[order_idx]['name'] != "未指定" else ""
                                st.session_state.lineup_pos[team_name][order_idx-1] = temp_lineup[order_idx]['pos']
                                
                            return temp_lineup

                        laa_auto_lineup = auto_lineup_smart_v48("LAA", is_laa_home_ai)
                        lad_auto_lineup = auto_lineup_smart_v48("LAD", not is_laa_home_ai)

                        col_left_lineup, col_right_lineup = st.columns(2)
                        
                        def render_team_lineup_ui(team, location_tag, auto_lineup):
                            st.subheader(f"{'🔴' if team == 'LAA' else '🔵'} {team} 先發陣容 ({location_tag})")
                            st.caption("🤖 AI 根據數據近況自動排定，採用現代棒球 (最強第2棒) 思維")
                            prefix_str = "WS " if is_ws_mode else ""
                            team_lower = team.lower()
                            
                            st.markdown("<div style='background-color:#1e1e1e; padding:10px; border-radius:8px;'>", unsafe_allow_html=True)
                            for i in range(1, 10):
                                p_data = auto_lineup[i]
                                p_name = p_data['name']
                                p_pos = p_data['pos']
                                
                                stats = display_b_stats.get(team, {}).get(p_name, {'wRC+': 0, 'eWAR': 0, 'AVG': 0})
                                stat_txt = f"{prefix_str}eWAR: {stats['eWAR']:.1f} &nbsp;|&nbsp; wRC+: {stats['wRC+']:.0f}"
                                
                                st.markdown(f"""
                                <div style='display:flex; justify-content:space-between; align-items:center; padding: 6px 5px; border-bottom: 1px solid #333;'>
                                    <div style='display:flex; align-items:center;'>
                                        <span style='color:#888; font-size:12px; width:35px; font-weight:bold;'>{i} 棒</span>
                                        <span style='color:#ccc; font-size:11px; width:30px; text-align:center; background:#000; border-radius:3px; padding:2px; margin-right:10px;'>{p_pos}</span>
                                        <span style='font-size:15px; font-weight:bold; color:white;'>{p_name}</span>
                                    </div>
                                    <div style='font-size:11px; color:#aaa;'>{stat_txt}</div>
                                </div>
                                """, unsafe_allow_html=True)
                            st.markdown("</div>", unsafe_allow_html=True)
                            
                            st.markdown("---")
                            st.markdown(f"##### ⚾ {team} 先發投手 (SP)")
                            sp_options = ["未指定"] + cached_players_p.get(team, [])
                            sp_key = f"t2_{team_lower}_sp_{full_stage}"
                            
                            auto_sp = laa_sp_val if team == 'LAA' else lad_sp_val
                            if sp_key not in st.session_state:
                                st.session_state[sp_key] = auto_sp if auto_sp in sp_options else st.session_state.pitchers.get(team, "未指定")
                            if st.session_state[sp_key] not in sp_options: st.session_state[sp_key] = "未指定"
                            
                            sp = st.selectbox(f"選擇 {team} 先發", sp_options, key=sp_key, label_visibility="collapsed")
                            st.session_state.pitchers[team] = sp if sp != "未指定" else ""
                            if sp and sp != "未指定":
                                stats = display_p_stats.get(team, {}).get(sp, {'ERA': 0, 'eWAR': 0, 'K': 0})
                                era_str = '∞' if stats['ERA'] == float('inf') else f"{stats['ERA']:.2f}"
                                st.caption(f"🥎 {prefix_str}eWAR: **{stats['eWAR']:.1f}** | {prefix_str}ERA: **{era_str}** | {prefix_str}K: {stats['K']}")

                        with col_left_lineup: render_team_lineup_ui(away_team, "客場", lad_auto_lineup if away_team=="LAD" else laa_auto_lineup)
                        with col_right_lineup: render_team_lineup_ui(home_team, "主場", laa_auto_lineup if home_team=="LAA" else lad_auto_lineup)

                        st.markdown("---")
                        st.subheader("🔮 賽前戰力天秤 (Expected Win %)")
                        
                        def get_streak_bonus(team_name, ws_only=False):
                            df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
                            if df_p_full.empty: return 0
                            if wr_season != "十年總成績":
                                s_num = wr_season.split(" ")[1]
                                prefix = f"[S{s_num}]"
                                df_p_season = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(prefix, regex=False)]
                            else: df_p_season = df_p_full

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
                            def get_player_ewar(team, p, is_batter=True):
                                if is_batter:
                                    base = curr_b_stats.get(team, {}).get(p, {'eWAR':0})['eWAR']
                                    if is_ws_mode and p in ws_b_stats.get(team, {}):
                                        return ws_b_stats[team][p]['eWAR'] * 6.0 if ws_b_stats[team][p].get('PA', 0) > 0 else base
                                    return base
                                else:
                                    base = curr_p_stats.get(team, {}).get(p, {'eWAR':0})['eWAR']
                                    if is_ws_mode and p in ws_p_stats.get(team, {}):
                                        return ws_p_stats[team][p]['eWAR'] * 6.0 if ws_p_stats[team][p].get('IP', 0) > 0 else base * 5.0
                                    return base * 5.0 

                            def get_team_roster_power(team):
                                team_players = curr_b_stats.get(team, {}).keys()
                                player_powers = [get_player_ewar(team, p, True) for p in team_players]
                                return sum(sorted(player_powers, reverse=True)[:9])

                            laa_sp_prob = st.session_state.pitchers.get("LAA", "未指定")
                            lad_sp_prob = st.session_state.pitchers.get("LAD", "未指定")
                            
                            laa_sp_power = get_player_ewar('LAA', laa_sp_prob, False) if laa_sp_prob != "未指定" else 0
                            lad_sp_power = get_player_ewar('LAD', lad_sp_prob, False) if lad_sp_prob != "未指定" else 0
                            
                            laa_power = get_team_roster_power('LAA') + laa_sp_power + get_streak_bonus('LAA', is_ws_mode)/3.0 - (3.0 if laa_sp_prob != "未指定" and get_starter_ratio('LAA', laa_sp_prob) <= 0.30 else 0)
                            lad_power = get_team_roster_power('LAD') + lad_sp_power + get_streak_bonus('LAD', is_ws_mode)/3.0 - (3.0 if lad_sp_prob != "未指定" and get_starter_ratio('LAD', lad_sp_prob) <= 0.30 else 0)
                            
                            laa_power += 1.5 if is_laa_home_ai else 0
                            lad_power += 1.5 if not is_laa_home_ai else 0

                            laa_prob = max(15.0, min(85.0, round((1 / (1 + math.exp(-0.12 * (laa_power - lad_power)))) * 100, 1)))
                            return laa_prob, round(100.0 - laa_prob, 1), laa_sp_prob != "未指定" and get_starter_ratio('LAA', laa_sp_prob) <= 0.30, lad_sp_prob != "未指定" and get_starter_ratio('LAD', lad_sp_prob) <= 0.30

                        prob_laa, prob_lad, is_laa_opener, is_lad_opener = calc_win_prob()
                        ml_laa = f"-{int(round((prob_laa / (100.0 - prob_laa)) * 100))}" if prob_laa > 50 else f"+{int(round(((100.0 - prob_laa) / max(0.1, prob_laa)) * 100))}" if prob_laa < 50 else "PK"
                        ml_lad = f"-{int(round((prob_lad / (100.0 - prob_lad)) * 100))}" if prob_lad > 50 else f"+{int(round(((100.0 - prob_lad) / max(0.1, prob_lad)) * 100))}" if prob_lad < 50 else "PK"
                        
                        if away_team == "LAD":
                            left_p, right_p, left_t, right_t, left_ml, right_ml, c_left, c_right = prob_lad, prob_laa, "LAD", "LAA", ml_lad, ml_laa, "#005A9C", "#BA0021"
                        else:
                            left_p, right_p, left_t, right_t, left_ml, right_ml, c_left, c_right = prob_laa, prob_lad, "LAA", "LAD", ml_laa, ml_lad, "#BA0021", "#005A9C"

                        st.markdown(f"<div style='display: flex; height: 35px; border-radius: 8px; overflow: hidden; font-weight: bold; color: white; text-align: center; line-height: 35px; font-size: 16px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);'><div style='width: {left_p}%; background-color: {c_left}; transition: width 0.5s;'>{left_t} {left_p}% ({left_ml})</div><div style='width: {right_p}%; background-color: {c_right}; transition: width 0.5s;'>{right_t} {right_p}% ({right_ml})</div></div>", unsafe_allow_html=True)
                        
                        msg = "💡 **AI 宏觀演算模型**：已捨棄單點打線排列，改以 **球隊本季核心陣容火力 (Top 9 打者 eWAR 總和)** 為絕對基底，結合今日先發(權重5倍)、近期氣勢與主場優勢 (+1.5 eWAR)。"
                        if is_ws_mode: msg += " 🏆 **[世界大賽模式] 已強制套用季後賽手感加權！**"
                        if is_laa_opener or is_lad_opener: msg += " ⚠️ **偵測到牛棚假先發 (生涯先發比例過低)，該隊勝率已遭系統大幅下修。**"
                        st.caption(msg)
                        
                        st.markdown("<br>", unsafe_allow_html=True)

                        if st.button(f"🎙️ 產生賽前深度戰報 ({g_name})", type="primary", use_container_width=True, key=f"btn_report_{full_stage}"):
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
                                    else: df_p_season = df_p_full

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
                                        ws_df = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(f"\\[S{wr_season.split(' ')[1]}\\] 世界大賽", regex=False))]
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
                                        "🎙️ **【例行賽焦點】** 「例行賽就是一場馬拉松，但今天這場洛杉康內戰，雙方絕對都想在氣勢上壓過對手！」"
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
                                                
                                def log5(a, b, l):
                                    if l <= 0 or l >= 1: return 0
                                    if a == 0 and b == 0: return 0
                                    num = (a * b) / l
                                    den = num + ((1 - a) * (1 - b) / (1 - l))
                                    if den == 0: return 0
                                    return num / den

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
                                run_env = 1.5
                                power_diff = (prob_laa - 50) / 20.0
                                
                                exp_runs_laa = run_env + power_diff
                                exp_runs_lad = run_env - power_diff
                                
                                pred_laa = max(0, int(round(exp_runs_laa)))
                                pred_lad = max(0, int(round(exp_runs_lad)))
                                
                                if pred_laa == pred_lad:
                                    if prob_laa >= 50: pred_laa += 1
                                    else: pred_lad += 1

                                if pred_laa > pred_lad:
                                    prediction.append(f"🔮 **【AI 大數據終極預測】**\n「綜合今日雙方陣容火力與 **3 局制賽制環境**，模型顯示勝率天平傾向 LAA (**{prob_laa}%**)。\n👉 系統推演最可能出現的結果為：**LAA 將以 {pred_laa} : {pred_lad} 擊敗 LAD！**」")
                                else:
                                    prediction.append(f"🔮 **【AI 大數據終極預測】**\n「綜合今日雙方陣容火力與 **3 局制賽制環境**，模型顯示勝率天平傾向 LAD (**{prob_lad}%**)。\n👉 系統推演最可能出現的結果為：**LAD 將以 {pred_lad} : {pred_laa} 擊敗 LAA！**」")

                                tactics.append(prediction[0])
                                st.error("\n\n".join(tactics))

                                st.markdown("---")
                                st.markdown("#### 🚨 戰情室特別警報 (Active Streaks Radar)")
                                
                                active_alerts = []
                                df_b_raw_radar = st.session_state.get('df_b_raw', pd.DataFrame())
                                df_p_raw_radar = st.session_state.get('df_p_raw', pd.DataFrame())

                                if not df_b_raw_radar.empty:
                                    for team in ['LAA', 'LAD']:
                                        t_df = df_b_raw_radar[df_b_raw_radar['球隊'] == team]
                                        for name, g in t_df.groupby('球員姓名', sort=False):
                                            is_starting_today = name in (curr_laa_batters + curr_lad_batters)
                                            if not is_starting_today: continue
                                            
                                            g_sorted = g.sort_values('時間戳記', ascending=False)
                                            hit_streak, hr_streak, hitless_streak = 0, 0, 0
                                            
                                            for _, r in g_sorted.iterrows():
                                                if pd.to_numeric(r.get('安打', 0), errors='coerce') > 0: hit_streak += 1
                                                else: break
                                                
                                            for _, r in g_sorted.iterrows():
                                                if pd.to_numeric(r.get('全壘打', 0), errors='coerce') > 0: hr_streak += 1
                                                else: break
                                                
                                            for _, r in g_sorted.iterrows():
                                                h = pd.to_numeric(r.get('安打', 0), errors='coerce')
                                                ab = pd.to_numeric(r.get('打數', 0), errors='coerce')
                                                if h > 0: break
                                                elif h == 0 and ab > 0: hitless_streak += 1

                                            playing_str = " 🎯(今日先發)"
                                            
                                            if hr_streak >= 2:
                                                active_alerts.append(f"🌋 [{team}] **{name}**{playing_str} 砲火猛烈！目前已跨場 **連 {hr_streak} 場全壘打**，絕對要注意他的長打威脅！")
                                            if hit_streak >= 4: 
                                                active_alerts.append(f"🔥 [{team}] **{name}**{playing_str} 手感發燙，目前正處於跨場 **連 {hit_streak} 場安打** 的狀態！")
                                            if hitless_streak >= 5: 
                                                active_alerts.append(f"📉 [{team}] **{name}**{playing_str} 近期陷入嚴重低潮，已經連續 **{hitless_streak} 場出賽沒有安打**，急需一棒擊沉來改運！")

                                if not df_p_raw_radar.empty:
                                    df_p_sort = df_p_raw_radar.sort_values('時間戳記')
                                    df_p_sort['is_SP'] = df_p_sort.groupby(['球隊', '賽事階段']).cumcount() == 0
                                    
                                    for team in ['LAA', 'LAD']:
                                        t_df = df_p_sort[df_p_sort['球隊'] == team]
                                        for name, g in t_df.groupby('投手姓名', sort=False):
                                            g_sorted = g.sort_values('時間戳記', ascending=False)
                                            
                                            sp_games = g_sorted[g_sorted['is_SP'] == True]
                                            zr_sp_streak = 0
                                            for _, r in sp_games.iterrows():
                                                er = pd.to_numeric(r.get('失分', 1), errors='coerce')
                                                outs = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                                                if er == 0 and outs > 0: zr_sp_streak += 1
                                                else: break
                                            
                                            rp_games = g_sorted[g_sorted['is_SP'] == False]
                                            zr_rp_streak = 0
                                            for _, r in rp_games.iterrows():
                                                er = pd.to_numeric(r.get('失分', 1), errors='coerce')
                                                outs = pd.to_numeric(r.get('局數(整數)', 0), errors='coerce') * 3 + pd.to_numeric(r.get('局數(出局數)', 0), errors='coerce')
                                                if er == 0 and outs > 0: zr_rp_streak += 1
                                                else: break
                                                
                                            if zr_sp_streak >= 2:
                                                if name in [laa_sp_val, lad_sp_val]:
                                                    active_alerts.append(f"🛡️ [{team}] **{name}** ⚾(今日先發) 展現窒息式壓制力，已連續 **{zr_sp_streak} 場先發無失分**！")
                                            if zr_rp_streak >= 4:
                                                playing_str = " 🔒(牛棚待命)" if name not in [laa_sp_val, lad_sp_val] else ""
                                                active_alerts.append(f"🔒 [{team}] **{name}**{playing_str} 近期扮演牛棚鐵壁，已連續 **{zr_rp_streak} 場後援無失分**！")

                                if active_alerts:
                                    st.info("\n\n".join(active_alerts))
                                else:
                                    st.caption("目前雙方陣容中，尚無值得注意的極端連續紀錄。")
# ==========================================
# --- 分頁 3：數據總表 + 核心戰績與棒次生產線 ---
# ==========================================
with tab3:
    import re
    import altair as alt
    import pandas as pd
    import numpy as np

    st.subheader("🏆 累積數據與聯盟戰績")
    
    with st.expander("💡 棒球進階數據 (Sabermetrics) 與 BR 格式深度解析小教室 (點我展開)"):
        st.markdown("""
        **【指標基底宣告】**：本系統進階數據皆「**以本微型聯盟當下賽事的整體環境**」做為聯盟平均基準動態精算，真實反映球員的絕對壓制力與貢獻度。

        * **WAR (eWAR)：** 預期勝場貢獻值。衡量一名球員「比替補多替球隊拿幾勝」，是評斷球員價值的最終依據。
        * **rOBA+ (原 wRC+)：** 加權創造得分。✨ **100 為本聯盟平均**。150 代表火力高出平均 50%；若打擊極度掙扎將真實呈現為負數。
        * **OPS+：** 標準化攻擊指數。將球員的 OBP 與 SLG 除以聯盟平均後的綜合指標，100 為平均。
        * **TB (Total Bases)：** 壘打數。1B + 2×2B + 3×3B + 4×HR。
        * **ISO (純長打率)：** 公式為 `SLG - BA`。只評估打者真正的長打火力。
        * **BAbip：** 剔除全壘打與三振後的場內安打率。數值異常高代表強運；異常低則代表被對手針對或運氣極差。
        * **ERA+：** 標準化防禦率。公式為 `100 × (聯盟防禦率 / 該投手防禦率)`。150 代表防禦率比聯盟好 50%。
        * **FIP (獨立防禦率)：** 剔除守備與運氣成分，純看投手「能自己掌握的」三振、保送與挨轟，反映真實硬實力。
        * **GS (Games Started)：** 先發場次。
        * **H9 / HR9 / BB9 / SO9：** 投手每九局平均被安打、被全壘打、保送與三振數。
        * **SO/BB：** 三振保送比。投手控球與解決打者能力的絕佳指標。
        * **P/BF：** 投手每打席平均用球數。**3.5球以下**為省球大師，**4.2球以上**代表常陷入滿球數纏鬥。
        * **對手打擊三圍 (BA/OBP/SLG/OPS)：** 投手右側的打擊數據，代表「面對該投手時，打者繳出的成績」。
        
        **【Baseball-Reference (BR) Pos 守位密碼學】**
        * **1~9**：標準棒球守位 (1=投手, 2=捕手... 8=中外野, 9=右外野)。 **D**=指定打擊, **H**=代打/代跑。
        * **排列順序**：依出賽頻率由高到低排列 (例：`87` 代表主要守中外野，其次左外野)。
        * **符號 `*`**：代表出賽至少三分之二 (不動先發)。
        * **符號 `/`**：斜線後面的守位代表客串場次極少。
        """)

    get_career_stats()
    df_b = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p = st.session_state.get('df_p_raw', pd.DataFrame())
    
    def fmt_rate_t3(val):
        if pd.isna(val) or val == float('inf'): return ".000"
        if val >= 1: return f"{val:.3f}"
        return f"{val:.3f}".lstrip('0')

    latest_s_str = "Season 1"
    if not df_p.empty and '賽事階段' in df_p.columns:
        s_nums = df_p['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]').dropna()[0].astype(int)
        if not s_nums.empty: latest_s_str = f"Season {s_nums.max()}"
            
    if 'has_auto_set_season' not in st.session_state:
        st.session_state.default_season = latest_s_str
        st.session_state.has_auto_set_season = True

    col_f1, col_f2, col_f3 = st.columns([1, 1.5, 2.5])
    with col_f1:
        if st.button("🔄 刷新數據", type="primary", key="btn_refresh_tab3_br"): 
            get_raw_records.clear()
            st.rerun()
            
    with col_f2:
        season_options = ["十年總成績"] + SEASONS
        s_idx = season_options.index(st.session_state.default_season) if st.session_state.default_season in season_options else 0
        def update_season():
            st.session_state.default_season = st.session_state.tab3_f_season_br
            if 'save_settings' in globals(): save_settings()
        filter_season = st.selectbox("篩選賽季", season_options, index=s_idx, key="tab3_f_season_br", on_change=update_season)

    with col_f3:
        if filter_season == "十年總成績":
            game_options_career = ["不限 (看全部)", "例行賽總和", "世界大賽總和"]
            saved_game_career = st.session_state.get("f_game_pref_career", "不限 (看全部)")
            gc_idx = game_options_career.index(saved_game_career) if saved_game_career in game_options_career else 0
            def update_game_career():
                st.session_state.f_game_pref_career = st.session_state.tab3_f_game_sel_career
                if 'save_settings' in globals(): save_settings()
            filter_game = st.selectbox("比賽階段", game_options_career, index=gc_idx, key="tab3_f_game_sel_career", on_change=update_game_career)
            
            if filter_game == "不限 (看全部)": target_prefix = ""
            elif filter_game == "例行賽總和": target_prefix = "例行賽"
            elif filter_game == "世界大賽總和": target_prefix = "世界大賽"
            is_exact_match = False
        else:
            game_options = ["看整季", "例行賽總和", "世界大賽總和"] + GAME_STAGES
            saved_game = st.session_state.get("f_game_pref", "看整季")
            g_idx = game_options.index(saved_game) if saved_game in game_options else 0
            def update_game():
                st.session_state.f_game_pref = st.session_state.tab3_f_game_sel_br
                if 'save_settings' in globals(): save_settings()
            filter_game = st.selectbox("比賽階段", game_options, index=g_idx, key="tab3_f_game_sel_br", on_change=update_game)
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
                is_exact_match = True

    def apply_filter(df, prefix, exact):
        if df.empty or not prefix: return df
        if exact: return df[df['賽事階段'].astype(str) == prefix]
        else: return df[df['賽事階段'].astype(str).str.contains(prefix, regex=False)]

    b_filter_df = apply_filter(df_b, target_prefix, is_exact_match)
    p_filter_df = apply_filter(df_p, target_prefix, is_exact_match)

    team_games_played = b_filter_df['賽事階段'].nunique() if not b_filter_df.empty and '賽事階段' in b_filter_df.columns else 1
    dyn_pa_limit = max(1.0, team_games_played * 1.0)
    dyn_ip_limit = max(0.1, team_games_played * 0.33)

    st.markdown("### 📊 球隊戰績排名 (Team Standings)")
    
    if not df_p.empty and '球隊' in df_p.columns:
        stand_b = b_filter_df
        stand_p = p_filter_df
        
        team_data = []
        for team in TEAMS:
            t_p = stand_p[stand_p['球隊'] == team]
            t_b = stand_b[stand_b['球隊'] == team] if not stand_b.empty else pd.DataFrame()
            
            wins, losses, draws = 0, 0, 0
            if '賽事階段' in t_p.columns:
                for stage, group in t_p.groupby('賽事階段', sort=False):
                    res = group['勝敗'].astype(str).values if '勝敗' in group.columns else []
                    if any('勝' in x for x in res): wins += 1
                    elif any('敗' in x for x in res): losses += 1
                    else: draws += 1 
            
            rs = pd.to_numeric(t_b['得分'], errors='coerce').fillna(0).sum() if not t_b.empty and '得分' in t_b.columns else 0
            ra = pd.to_numeric(t_p['失分'], errors='coerce').fillna(0).sum() if not t_p.empty and '失分' in t_p.columns else 0
            
            team_data.append({
                "球隊": f"🔴 {team}" if team == "LAA" else f"🔵 {team}",
                "已賽": wins + losses + draws,
                "勝": wins, "敗": losses, "和": draws,
                "勝率": wins / (wins + losses) if (wins + losses) > 0 else 0,
                "總得分": int(rs), "總失分": int(ra), "得失分差": int(rs - ra)
            })
        
        df_standings = pd.DataFrame(team_data).sort_values("勝率", ascending=False)
        st.dataframe(df_standings.style.format({"勝率": "{:.3f}"}), use_container_width=True, hide_index=True)
    else: st.info("尚無數據可計算戰績。")
    st.markdown("---")
    
    st.markdown("""
    <style>
    [data-testid="stDataFrame"] div[data-testid="stTable"] { font-size: 12px; }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown("### ⚾ 打擊成績 (Batting)")
    if not df_b.empty:
        curr_b = b_filter_df.copy()
        if curr_b.empty: 
            st.info("查無符合條件的打擊紀錄。")
        else:
            numeric_cols = ['打席', '打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '三振', '盜壘']
            for col in numeric_cols:
                curr_b[col] = pd.to_numeric(curr_b[col], errors='coerce').fillna(0) if col in curr_b.columns else 0
            
            if '四壞球' in curr_b.columns: curr_b['四壞球'] = pd.to_numeric(curr_b['四壞球'], errors='coerce').fillna(0)
            elif '四壞' in curr_b.columns: curr_b['四壞球'] = pd.to_numeric(curr_b['四壞'], errors='coerce').fillna(0)
            else: curr_b['四壞球'] = 0

            total_h = curr_b['安打'].sum()
            total_bb = curr_b['四壞球'].sum()
            total_pa = curr_b['打席'].sum()
            total_ab = curr_b['打數'].sum()
            
            lg_1b = total_h - curr_b['二壘安打'].sum() - curr_b['三壘安打'].sum() - curr_b['全壘打'].sum()
            lg_woba_num = 0.69 * total_bb + 0.88 * lg_1b + 1.25 * curr_b['二壘安打'].sum() + 1.59 * curr_b['三壘安打'].sum() + 2.06 * curr_b['全壘打'].sum()
            lg_woba = lg_woba_num / total_pa if total_pa > 0 else 0.320
            
            lg_obp = (total_h + total_bb) / total_pa if total_pa > 0 else 0.320
            total_tb_lg = lg_1b + 2*curr_b['二壘安打'].sum() + 3*curr_b['三壘安打'].sum() + 4*curr_b['全壘打'].sum()
            lg_slg = total_tb_lg / total_ab if total_ab > 0 else 0.400

            curr_b['Season'] = curr_b['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
            player_ewar_b = {}
            pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
            
            for s in curr_b['Season'].unique():
                s_df = curr_b[curr_b['Season'] == s]
                s_pa = s_df['打席'].sum()
                s_lg_woba = (0.69*s_df['四壞球'].sum() + 0.88*(s_df['安打'].sum()-s_df['二壘安打'].sum()-s_df['三壘安打'].sum()-s_df['全壘打'].sum()) + 1.25*s_df['二壘安打'].sum() + 1.59*s_df['三壘安打'].sum() + 2.06*s_df['全壘打'].sum()) / s_pa if s_pa > 0 else 0.320
                
                s_agg = s_df.groupby('球員姓名').agg({'打席': 'sum', '打數': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', '全壘打': 'sum', '四壞球': 'sum', '三振': 'sum', '守位': lambda x: x.value_counts().index[0] if not x.empty else 'DH'}).reset_index()
                
                for _, r in s_agg.iterrows():
                    p_1b = r['安打'] - r['二壘安打'] - r['三壘安打'] - r['全壘打']
                    p_woba = (0.69 * r['四壞球'] + 0.88 * p_1b + 1.25 * r['二壘安打'] + 1.59 * r['三壘安打'] + 2.06 * r['全壘打']) / max(1, r['打席'])
                    p_wrc_plus = ((p_woba / s_lg_woba) - 1) * 200 + 100 if s_lg_woba > 0 else 0
                    ewar = (((p_wrc_plus - 70) / 80) + pos_adj_dict.get(r['守位'], -0.12)) * (r['打席'] / 15)
                    ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)
                    player_ewar_b[r['球員姓名']] = player_ewar_b.get(r['球員姓名'], 0.0) + ewar

            def get_br_pos(pos_series):
                if pos_series.empty: return "D"
                pos_map = {"P":"1", "C":"2", "1B":"3", "2B":"4", "3B":"5", "SS":"6", "LF":"7", "CF":"8", "RF":"9", "DH":"D", "PH":"H", "PR":"H"}
                counts = {}
                for p in pos_series.dropna():
                    char = pos_map.get(str(p).strip(), "")
                    if char: counts[char] = counts.get(char, 0) + 1
                if not counts: return "D"
                
                is_career = (filter_season == "十年總成績")
                threshold = 10 if is_career else max(2, int(team_games_played * 0.15))
                star_thresh = team_games_played * 0.66
                
                main_str, minor_str = "", ""
                for char, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                    if not is_career and count >= star_thresh: main_str += f"*{char}"
                    elif count >= threshold: main_str += char
                    else: minor_str += char
                
                res = main_str.replace("**", "*")
                if not res and minor_str: return minor_str
                if minor_str: res += f"/{minor_str}"
                return res if res else "D"

            agg_b = curr_b.groupby('球員姓名').agg({
                '打席': 'sum', '打數': 'sum', '得分': 'sum', '安打': 'sum', '二壘安打': 'sum', '三壘安打': 'sum', 
                '全壘打': 'sum', '打點': 'sum', '盜壘': 'sum', '四壞球': 'sum', '三振': 'sum',
                '賽事階段': 'nunique', '守位': get_br_pos
            }).reset_index()
            
            last_team_b = curr_b.sort_values('時間戳記').groupby('球員姓名')['球隊'].last()
            all_team_b = curr_b.sort_values('時間戳記').groupby('球員姓名')['球隊'].unique().apply(lambda x: "/".join(x))
            
            agg_b['最新球隊'] = agg_b['球員姓名'].map(last_team_b)
            agg_b['Tm'] = agg_b['球員姓名'].map(all_team_b)
            
            agg_b.rename(columns={
                '球員姓名': 'Player', '賽事階段': 'G', '打席': 'PA', '打數': 'AB', '得分': 'R', '安打': 'H',
                '二壘安打': '2B', '三壘安打': '3B', '全壘打': 'HR', '打點': 'RBI', '盜壘': 'SB', '四壞球': 'BB', '三振': 'SO', '守位': 'Pos'
            }, inplace=True)
            
            agg_b['1B'] = agg_b['H'] - agg_b['2B'] - agg_b['3B'] - agg_b['HR']
            agg_b['TB'] = agg_b['1B'] + 2*agg_b['2B'] + 3*agg_b['3B'] + 4*agg_b['HR']
            agg_b['BA'] = (agg_b['H'] / agg_b['AB'].replace(0, 1)).fillna(0)
            agg_b['OBP'] = ((agg_b['H'] + agg_b['BB']) / agg_b['PA'].replace(0, 1)).fillna(0)
            agg_b['SLG'] = (agg_b['TB'] / agg_b['AB'].replace(0, 1)).fillna(0)
            agg_b['OPS'] = agg_b['OBP'] + agg_b['SLG']
            
            agg_b['OPS+'] = (100 * ((agg_b['OBP'] / lg_obp) + (agg_b['SLG'] / lg_slg) - 1)).fillna(100).astype(int)
            agg_b['wOBA'] = (0.69 * agg_b['BB'] + 0.88 * agg_b['1B'] + 1.25 * agg_b['2B'] + 1.59 * agg_b['3B'] + 2.06 * agg_b['HR']) / agg_b['PA'].replace(0, 1)
            agg_b['rOBA+'] = (((agg_b['wOBA'] / lg_woba) - 1) * 200 + 100).fillna(100).astype(int)
            
            agg_b['BAbip'] = ((agg_b['H'] - agg_b['HR']) / (agg_b['AB'] - agg_b['SO'] - agg_b['HR']).replace(0, 1)).fillna(0)
            agg_b['ISO'] = agg_b['SLG'] - agg_b['BA']
            agg_b['HR%'] = (agg_b['HR'] / agg_b['PA'].replace(0, 1) * 100).fillna(0)
            agg_b['SO%'] = (agg_b['SO'] / agg_b['PA'].replace(0, 1) * 100).fillna(0)
            agg_b['BB%'] = (agg_b['BB'] / agg_b['PA'].replace(0, 1) * 100).fillna(0)
            
            agg_b['WAR'] = agg_b['Player'].map(player_ewar_b).fillna(0.0)

            qual_b = agg_b[agg_b['PA'] >= dyn_pa_limit]
            if not agg_b.empty:
                st.markdown(f"#### 👑 聯盟打擊領先者 (規定打席: {dyn_pa_limit:.1f})")
                avg_df = qual_b[qual_b['BA'] > 0]
                h_df = agg_b[agg_b['H'] > 0]
                hr_df = agg_b[agg_b['HR'] > 0]
                rbi_df = agg_b[agg_b['RBI'] > 0]
                sb_df = agg_b[agg_b['SB'] > 0]

                name_avg = f"[{avg_df.sort_values(by=['BA', 'H'], ascending=[False, False]).iloc[0]['最新球隊']}] {avg_df.sort_values(by=['BA', 'H'], ascending=[False, False]).iloc[0]['Player']}" if not avg_df.empty else "無(未達標)"
                val_avg = avg_df['BA'].max() if not avg_df.empty else 0.0

                name_h = f"[{h_df.sort_values(by=['H', 'BA'], ascending=[False, False]).iloc[0]['最新球隊']}] {h_df.sort_values(by=['H', 'BA'], ascending=[False, False]).iloc[0]['Player']}" if not h_df.empty else "無"
                val_h = h_df['H'].max() if not h_df.empty else 0

                name_hr = f"[{hr_df.sort_values(by=['HR', 'BA'], ascending=[False, False]).iloc[0]['最新球隊']}] {hr_df.sort_values(by=['HR', 'BA'], ascending=[False, False]).iloc[0]['Player']}" if not hr_df.empty else "無"
                val_hr = hr_df['HR'].max() if not hr_df.empty else 0

                name_rbi = f"[{rbi_df.sort_values(by=['RBI', 'HR'], ascending=[False, False]).iloc[0]['最新球隊']}] {rbi_df.sort_values(by=['RBI', 'HR'], ascending=[False, False]).iloc[0]['Player']}" if not rbi_df.empty else "無"
                val_rbi = rbi_df['RBI'].max() if not rbi_df.empty else 0

                name_sb = f"[{sb_df.sort_values(by=['SB', 'PA'], ascending=[False, True]).iloc[0]['最新球隊']}] {sb_df.sort_values(by=['SB', 'PA'], ascending=[False, True]).iloc[0]['Player']}" if not sb_df.empty else "無"
                val_sb = sb_df['SB'].max() if not sb_df.empty else 0

                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                lc1.metric(f"打擊王", f"{fmt_rate_t3(val_avg)}", name_avg)
                lc2.metric(f"安打王", f"{int(val_h)} H", name_h)
                lc3.metric(f"全壘打王", f"{int(val_hr)} HR", name_hr)
                lc4.metric(f"打點王", f"{int(val_rbi)} RBI", name_rbi)
                lc5.metric(f"盜壘王", f"{int(val_sb)} SB", name_sb)
                
            st.markdown("---")

            br_b_cols = ['Player', 'Tm', 'WAR', 'G', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'BB', 'SO', 'BA', 'OBP', 'SLG', 'OPS', 'OPS+', 'rOBA+', 'BAbip', 'ISO', 'HR%', 'SO%', 'BB%', 'TB', 'Pos']
            b_format_dict = {'WAR': '{:.1f}', 'BA': fmt_rate_t3, 'OBP': fmt_rate_t3, 'SLG': fmt_rate_t3, 'OPS': fmt_rate_t3, 'BAbip': fmt_rate_t3, 'ISO': fmt_rate_t3, 'HR%': '{:.1f}%', 'SO%': '{:.1f}%', 'BB%': '{:.1f}%'}

            def style_b_leaders(df):
                styles = pd.DataFrame('', index=df.index, columns=df.columns)
                for col in ['WAR', 'G', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'BB', 'TB']:
                    if col in df.columns and col in agg_b.columns:
                        max_v = agg_b[col].max()
                        if max_v > 0: styles[col] = np.where((df[col] == max_v) & (df['Player'] != 'Team Total'), 'font-weight: 900; color: #ffcc00;', '')
                for col in ['BA', 'OBP', 'SLG', 'OPS', 'OPS+', 'rOBA+', 'BAbip', 'ISO']:
                    if col in df.columns and not qual_b.empty and col in qual_b.columns:
                        max_v = qual_b[col].max()
                        if max_v > 0: styles[col] = np.where((df[col] == max_v) & (df['Player'] != 'Team Total'), 'font-weight: 900; color: #ffcc00;', '')
                return styles

            for team in TEAMS:
                st.markdown(f"#### {team} 打擊總表 (以最新效力球隊分類)")
                team_b = agg_b[agg_b['最新球隊'] == team].copy()
                if not team_b.empty:
                    team_raw_b = curr_b[curr_b['球隊'] == team]
                    
                    t_row = pd.DataFrame([{
                        'Player': 'Team Total', 'Tm': team, 'WAR': team_b['WAR'].sum(), 'G': team_games_played, 'PA': team_raw_b['打席'].sum(),
                        'AB': team_raw_b['打數'].sum(), 'R': team_raw_b['得分'].sum(), 'H': team_raw_b['安打'].sum(), '2B': team_raw_b['二壘安打'].sum(),
                        '3B': team_raw_b['三壘安打'].sum(), 'HR': team_raw_b['全壘打'].sum(), 'RBI': team_raw_b['打點'].sum(), 'SB': team_raw_b['盜壘'].sum(),
                        'BB': team_raw_b['四壞球'].sum(), 'SO': team_raw_b['三振'].sum(), 'Pos': ''
                    }])
                    
                    t_h, t_ab, t_pa, t_bb = t_row['H'].iloc[0], t_row['AB'].iloc[0], t_row['PA'].iloc[0], t_row['BB'].iloc[0]
                    t_hr, t_so = t_row['HR'].iloc[0], t_row['SO'].iloc[0]
                    t_1b = t_h - t_row['2B'].iloc[0] - t_row['3B'].iloc[0] - t_hr
                    t_tb = t_1b + 2*t_row['2B'].iloc[0] + 3*t_row['3B'].iloc[0] + 4*t_hr
                    t_row['TB'] = t_tb
                    
                    t_ba = t_h / t_ab if t_ab > 0 else 0
                    t_obp = (t_h + t_bb) / t_pa if t_pa > 0 else 0
                    t_slg = t_tb / t_ab if t_ab > 0 else 0
                    t_woba = (0.69*t_bb + 0.88*t_1b + 1.25*t_row['2B'].iloc[0] + 1.59*t_row['3B'].iloc[0] + 2.06*t_hr) / t_pa if t_pa > 0 else 0
                    
                    t_row['BA'], t_row['OBP'], t_row['SLG'] = t_ba, t_obp, t_slg
                    t_row['OPS'] = t_obp + t_slg
                    t_row['BAbip'] = (t_h - t_hr) / (t_ab - t_so - t_hr) if (t_ab - t_so - t_hr) > 0 else 0
                    t_row['ISO'] = t_slg - t_ba
                    t_row['HR%'] = (t_hr / t_pa * 100) if t_pa > 0 else 0
                    t_row['SO%'] = (t_so / t_pa * 100) if t_pa > 0 else 0
                    t_row['BB%'] = (t_bb / t_pa * 100) if t_pa > 0 else 0
                    t_row['OPS+'] = int(100 * ((t_obp/lg_obp) + (t_slg/lg_slg) - 1)) if lg_obp > 0 and lg_slg > 0 else 100
                    t_row['rOBA+'] = int(((t_woba/lg_woba) - 1) * 200 + 100) if lg_woba > 0 else 100
                    
                    final_team_b = pd.concat([team_b[br_b_cols].sort_values('WAR', ascending=False), t_row[br_b_cols]], ignore_index=True)
                    st.dataframe(final_team_b.style.format(b_format_dict).apply(style_b_leaders, axis=None), use_container_width=True, hide_index=True)
                else: st.caption("無數據")

            st.markdown("---")
            st.markdown("#### 📊 各棒次生產線火力對比 (Lineup Production: rOBA+ by Slot)")
            df_order = curr_b.copy()
            df_order['棒次_idx'] = pd.to_numeric(df_order['棒次'], errors='coerce').fillna(0).astype(int)
            df_order = df_order[(df_order['棒次_idx'] >= 1) & (df_order['棒次_idx'] <= 9)]
            
            if not df_order.empty:
                slot_agg = df_order.groupby(['球隊', '棒次_idx']).sum(numeric_only=True).reset_index()
                slot_data = []
                for _, r in slot_agg.iterrows():
                    s_1b = r['安打'] - r['二壘安打'] - r['三壘安打'] - r['全壘打']
                    s_woba = (0.69 * r['四壞球'] + 0.88 * s_1b + 1.25 * r['二壘安打'] + 1.59 * r['三壘安打'] + 2.06 * r['全壘打']) / max(1, r['打席'])
                    s_wrc_plus = ((s_woba / lg_woba) - 1) * 200 + 100 if lg_woba > 0 else 100
                    slot_data.append({'球隊': r['球隊'], '棒次': f"第 {int(r['棒次_idx'])} 棒", '棒次_num': int(r['棒次_idx']), 'rOBA+': int(round(s_wrc_plus, 0)), '總打席': int(r['打席'])})
                
                chart_slot = alt.Chart(pd.DataFrame(slot_data)).mark_bar(cornerRadiusEnd=4).encode(
                    y=alt.Y('棒次:N', sort=alt.SortField('棒次_num', 'ascending'), title='打擊棒次'),
                    x=alt.X('rOBA+:Q', title='棒次累積生產力 (rOBA+)'),
                    color=alt.Color('球隊:N', scale=alt.Scale(domain=['LAA', 'LAD'], range=['#BA0021', '#005A9C']), legend=alt.Legend(title="球隊")),
                    yOffset='球隊:N',
                    tooltip=['球隊', '棒次', 'rOBA+', '總打席']
                ).properties(height=380)
                st.altair_chart(chart_slot, use_container_width=True)
    else: st.info("目前沒有打擊紀錄可以顯示！")

    st.markdown("---")
    
    # =======================================================
    # 🥎 投球成績區塊 (BR 格式)
    # =======================================================
    st.markdown("### 🥎 投球成績 (Pitching)")
    if not df_p.empty:
        curr_p = p_filter_df.copy()
        if curr_p.empty: 
            st.info("查無符合條件的投球紀錄。")
        else:
            numeric_cols_p = ['局數(整數)', '局數(出局數)', '打者數', '投球數', '被安打', '被全壘打', '奪三振', '失分', '自責分']
            for col in numeric_cols_p:
                if col not in curr_p.columns: curr_p[col] = 0
                curr_p[col] = pd.to_numeric(curr_p[col], errors='coerce').fillna(0)
            
            if '四壞球' in curr_p.columns: curr_p['四壞球'] = pd.to_numeric(curr_p['四壞球'], errors='coerce').fillna(0)
            elif '四壞' in curr_p.columns: curr_p['四壞球'] = pd.to_numeric(curr_p['四壞'], errors='coerce').fillna(0)
            else: curr_p['四壞球'] = 0

            curr_p = curr_p.sort_values(['賽事階段', '時間戳記'])
            curr_p['is_GS'] = curr_p.groupby(['賽事階段', '球隊']).cumcount() == 0

            curr_p['Season'] = curr_p['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
            player_ewar_p = {}
            lg_era_base_global = 10.60
            
            for s in curr_p['Season'].unique():
                s_df = curr_p[curr_p['Season'] == s]
                s_outs = (s_df['局數(整數)'].sum() * 3) + s_df['局數(出局數)'].sum()
                s_ip = s_outs / 3.0
                s_lg_era = (s_df['自責分'].sum() * 9) / s_ip if s_ip > 0 else 10.60
                lg_era_base_global = s_lg_era 
                
                s_rep_level = s_lg_era * 1.30
                s_era_div = max(1.5, s_lg_era * 0.2)
                
                s_agg = s_df.groupby('投手姓名').agg({'局數(整數)': 'sum', '局數(出局數)': 'sum', '奪三振': 'sum', '自責分': 'sum', '四壞球': 'sum', '被全壘打': 'sum'}).reset_index()
                
                for _, r in s_agg.iterrows():
                    ip = ((r['局數(整數)'] * 3) + r['局數(出局數)']) / 3.0
                    era = (r['自責分'] * 9) / ip if ip > 0 else float('inf') if r['自責分'] > 0 else 0.0
                    fip = (((13 * r['被全壘打']) + (3 * r['四壞球']) - (2 * r['奪三振'])) / ip) + 3.10 if ip > 0 else float('inf') if (13*r['被全壘打']+3*r['四壞球']-2*r['奪三振'])>0 else 3.10
                    
                    tra = (era * 0.3) + (fip * 0.7) if int(s) >= 6 else (era + fip) / 2.0
                    if ip == 0: ewar = -0.1 * r['自責分'] - 0.05 * r['四壞球']
                    else: ewar = ((s_rep_level - tra) / s_era_div) * (ip / 10)
                    
                    ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)
                    player_ewar_p[r['投手姓名']] = player_ewar_p.get(r['投手姓名'], 0.0) + ewar

            agg_p = curr_p.groupby('投手姓名').agg({
                '賽事階段': 'nunique', 'is_GS': 'sum', '局數(整數)': 'sum', '局數(出局數)': 'sum', '被安打': 'sum', 
                '失分': 'sum', '自責分': 'sum', '被全壘打': 'sum', '四壞球': 'sum', '奪三振': 'sum', 
                '打者數': 'sum', '投球數': 'sum'
            }).reset_index()
            
            last_team_p = curr_p.sort_values('時間戳記').groupby('投手姓名')['球隊'].last()
            all_team_p = curr_p.sort_values('時間戳記').groupby('投手姓名')['球隊'].unique().apply(lambda x: "/".join(x))
            
            agg_p['最新球隊'] = agg_p['投手姓名'].map(last_team_p)
            agg_p['Tm'] = agg_p['投手姓名'].map(all_team_p)
            
            agg_p.rename(columns={
                '投手姓名': 'Player', '賽事階段': 'G', 'is_GS': 'GS', '被安打': 'H', '失分': 'R', '自責分': 'ER',
                '被全壘打': 'HR', '四壞球': 'BB', '奪三振': 'SO', '打者數': 'BF'
            }, inplace=True)
            
            if '勝敗' in curr_p.columns:
                p_res_c = curr_p.copy()
                p_res_c['W'] = p_res_c['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                p_res_c['L'] = p_res_c['勝敗'].astype(str).apply(lambda x: 1 if '敗' in x else 0)
                p_res_c['SV'] = p_res_c['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                p_res_c['HLD'] = p_res_c['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
                res_agg = p_res_c.groupby('投手姓名')[['W', 'L', 'SV', 'HLD']].sum().reset_index()
                res_agg.rename(columns={'投手姓名': 'Player'}, inplace=True)
                agg_p = pd.merge(agg_p, res_agg, on='Player', how='left')
            else:
                agg_p['W'], agg_p['L'], agg_p['SV'], agg_p['HLD'] = 0, 0, 0, 0

            agg_p['W-L%'] = (agg_p['W'] / (agg_p['W'] + agg_p['L']).replace(0, 1)).fillna(0)
            
            outs = (agg_p['局數(整數)'] * 3) + agg_p['局數(出局數)']
            agg_p['IP_calc'] = outs / 3.0
            agg_p['IP'] = (outs // 3) + (outs % 3) / 10.0
            
            agg_p['ERA'] = (agg_p['ER'] * 9 / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            agg_p['ERA'] = agg_p.apply(lambda r: float('inf') if r['IP_calc'] == 0 and r['ER'] > 0 else r['ERA'], axis=1)
            
            agg_p['ERA+'] = (100 * (lg_era_base_global / agg_p['ERA'].replace(0, float('nan')))).fillna(0).astype(int)
            agg_p['FIP'] = (((13 * agg_p['HR']) + (3 * agg_p['BB']) - (2 * agg_p['SO'])) / agg_p['IP_calc'].replace(0, 1) + 3.10).fillna(3.10)
            agg_p['WHIP'] = ((agg_p['H'] + agg_p['BB']) / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            
            agg_p['H9'] = (agg_p['H'] * 9 / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            agg_p['HR9'] = (agg_p['HR'] * 9 / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            agg_p['BB9'] = (agg_p['BB'] * 9 / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            agg_p['SO9'] = (agg_p['SO'] * 9 / agg_p['IP_calc'].replace(0, 1)).fillna(0)
            agg_p['SO/BB'] = (agg_p['SO'] / agg_p['BB'].replace(0, 1)).fillna(float('inf'))
            
            opp_ab = agg_p['BF'] - agg_p['BB']
            agg_p['BA'] = (agg_p['H'] / opp_ab.replace(0, 1)).fillna(0)
            agg_p['OBP'] = ((agg_p['H'] + agg_p['BB']) / agg_p['BF'].replace(0, 1)).fillna(0)
            opp_1b = agg_p['H'] - agg_p['HR']
            agg_p['SLG'] = ((opp_1b + 4 * agg_p['HR']) / opp_ab.replace(0, 1)).fillna(0)
            agg_p['OPS'] = agg_p['OBP'] + agg_p['SLG']
            agg_p['BAbip'] = ((agg_p['H'] - agg_p['HR']) / (opp_ab - agg_p['SO'] - agg_p['HR']).replace(0, 1)).fillna(0)
            agg_p['P/BF'] = (agg_p['投球數'] / agg_p['BF'].replace(0, 1)).fillna(0)
            
            agg_p['WAR'] = agg_p['Player'].map(player_ewar_p).fillna(0.0)

            qual_p = agg_p[agg_p['IP_calc'] >= dyn_ip_limit]
            if not agg_p.empty:
                st.markdown(f"#### 👑 聯盟投球領先者 (規定局數: {dyn_ip_limit:.1f})")
                era_df = qual_p 
                w_df = agg_p[agg_p['W'] > 0]
                sv_df = agg_p[agg_p['SV'] > 0]
                hld_df = agg_p[agg_p['HLD'] > 0]
                so_df = agg_p[agg_p['SO'] > 0]

                name_era = f"[{era_df.sort_values(by=['ERA', 'IP_calc'], ascending=[True, False]).iloc[0]['最新球隊']}] {era_df.sort_values(by=['ERA', 'IP_calc'], ascending=[True, False]).iloc[0]['Player']}" if not era_df.empty else "無(未達標)"
                val_era = era_df['ERA'].min() if not era_df.empty else float('inf')

                name_w = f"[{w_df.sort_values(by=['W', 'ERA'], ascending=[False, True]).iloc[0]['最新球隊']}] {w_df.sort_values(by=['W', 'ERA'], ascending=[False, True]).iloc[0]['Player']}" if not w_df.empty else "無"
                val_w = w_df['W'].max() if not w_df.empty else 0

                name_sv = f"[{sv_df.sort_values(by=['SV', 'ERA'], ascending=[False, True]).iloc[0]['最新球隊']}] {sv_df.sort_values(by=['SV', 'ERA'], ascending=[False, True]).iloc[0]['Player']}" if not sv_df.empty else "無"
                val_sv = sv_df['SV'].max() if not sv_df.empty else 0

                name_hld = f"[{hld_df.sort_values(by=['HLD', 'ERA'], ascending=[False, True]).iloc[0]['最新球隊']}] {hld_df.sort_values(by=['HLD', 'ERA'], ascending=[False, True]).iloc[0]['Player']}" if not hld_df.empty else "無"
                val_hld = hld_df['HLD'].max() if not hld_df.empty else 0

                name_so = f"[{so_df.sort_values(by=['SO', 'ERA'], ascending=[False, True]).iloc[0]['最新球隊']}] {so_df.sort_values(by=['SO', 'ERA'], ascending=[False, True]).iloc[0]['Player']}" if not so_df.empty else "無"
                val_so = so_df['SO'].max() if not so_df.empty else 0

                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                era_str = "∞" if val_era == float('inf') else f"{val_era:.2f}"
                lc1.metric(f"防禦率王", era_str, name_era)
                lc2.metric(f"勝投王", f"{int(val_w)} W", name_w)
                lc3.metric(f"救援王", f"{int(val_sv)} SV", name_sv)
                lc4.metric(f"中繼王", f"{int(val_hld)} HLD", name_hld)
                lc5.metric(f"三振王", f"{int(val_so)} K", name_so)
                
            st.markdown("---")

            br_p_cols = ['Player', 'Tm', 'WAR', 'W', 'L', 'W-L%', 'ERA', 'G', 'GS', 'SV', 'IP', 'H', 'R', 'ER', 'HR', 'BB', 'SO', 'BF', 'ERA+', 'FIP', 'WHIP', 'H9', 'HR9', 'BB9', 'SO9', 'SO/BB', 'BA', 'OBP', 'SLG', 'OPS', 'BAbip', 'P/BF']
            
            p_format_dict = {
                'WAR': '{:.1f}', 'W-L%': fmt_rate_t3, 'ERA': lambda x: '∞' if x == float('inf') else f"{x:.2f}",
                'IP': '{:.1f}', 'ERA+': lambda x: '∞' if x == float('inf') or x > 999 else f"{x:.0f}",
                'FIP': lambda x: '∞' if x == float('inf') else f"{x:.2f}", 'WHIP': '{:.2f}', 
                'H9': '{:.2f}', 'HR9': '{:.2f}', 'BB9': '{:.2f}', 'SO9': '{:.2f}', 'SO/BB': lambda x: '∞' if x == float('inf') else f"{x:.2f}",
                'BA': fmt_rate_t3, 'OBP': fmt_rate_t3, 'SLG': fmt_rate_t3, 'OPS': fmt_rate_t3, 
                'BAbip': fmt_rate_t3, 'P/BF': '{:.2f}'
            }

            def style_p_leaders(df):
                styles = pd.DataFrame('', index=df.index, columns=df.columns)
                for col in ['WAR', 'W', 'SV', 'G', 'GS', 'IP', 'SO']:
                    if col in df.columns and col in agg_p.columns:
                        max_v = agg_p[col].max()
                        if max_v > 0: styles[col] = np.where((df[col] == max_v) & (df['Player'] != 'Team Total'), 'font-weight: 900; color: #ffcc00;', '')
                for col in ['ERA', 'FIP', 'WHIP', 'BB9', 'H9', 'HR9', 'P/BF', 'BA', 'OBP', 'SLG', 'OPS', 'BAbip']:
                    if col in df.columns and not qual_p.empty and col in qual_p.columns:
                        min_v = qual_p[col].min()
                        if min_v < float('inf'): styles[col] = np.where((df[col] == min_v) & (df['Player'] != 'Team Total'), 'font-weight: 900; color: #ffcc00;', '')
                for col in ['ERA+', 'SO9', 'SO/BB']:
                    if col in df.columns and not qual_p.empty and col in qual_p.columns:
                        max_v = qual_p[col].max()
                        if max_v > 0: styles[col] = np.where((df[col] == max_v) & (df['Player'] != 'Team Total'), 'font-weight: 900; color: #ffcc00;', '')
                return styles

            for team in TEAMS:
                st.markdown(f"#### {team} 投球總表 (以最新效力球隊分類)")
                team_p = agg_p[agg_p['最新球隊'] == team].copy()
                if not team_p.empty:
                    team_raw_p = curr_p[curr_p['球隊'] == team]
                    t_outs = team_raw_p['局數(整數)'].sum()*3 + team_raw_p['局數(出局數)'].sum()
                    t_ip_calc = t_outs / 3.0
                    
                    t_row = pd.DataFrame([{
                        'Player': 'Team Total', 'Tm': team, 'WAR': team_p['WAR'].sum(), 'W': team_p['W'].sum(), 'L': team_p['L'].sum(),
                        'G': team_games_played, 'GS': team_raw_p['is_GS'].sum(), 'SV': team_p['SV'].sum(),
                        'IP': (t_outs // 3) + (t_outs % 3) / 10.0, 'H': team_raw_p['被安打'].sum(), 'R': team_raw_p['失分'].sum(),
                        'ER': team_raw_p['自責分'].sum(), 'HR': team_raw_p['被全壘打'].sum(), 'BB': team_raw_p['四壞球'].sum(), 'SO': team_raw_p['奪三振'].sum(),
                        'BF': team_raw_p['打者數'].sum(), '投球數': team_raw_p['投球數'].sum()
                    }])
                    
                    t_w, t_l, t_er, t_h, t_hr = t_row['W'].iloc[0], t_row['L'].iloc[0], t_row['ER'].iloc[0], t_row['H'].iloc[0], t_row['HR'].iloc[0]
                    t_bb, t_so, t_bf, t_np = t_row['BB'].iloc[0], t_row['SO'].iloc[0], t_row['BF'].iloc[0], t_row['投球數'].iloc[0]
                    
                    t_row['W-L%'] = t_w / (t_w + t_l) if (t_w + t_l) > 0 else 0
                    t_row['ERA'] = (t_er * 9) / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['ERA+'] = int(100 * (lg_era_base_global / t_row['ERA'].iloc[0])) if t_row['ERA'].iloc[0] > 0 else 999
                    t_row['FIP'] = (((13*t_hr) + (3*t_bb) - (2*t_so)) / t_ip_calc) + 3.10 if t_ip_calc > 0 else 3.10
                    t_row['WHIP'] = (t_h + t_bb) / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['H9'] = t_h * 9 / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['HR9'] = t_hr * 9 / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['BB9'] = t_bb * 9 / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['SO9'] = t_so * 9 / t_ip_calc if t_ip_calc > 0 else 0
                    t_row['SO/BB'] = t_so / t_bb if t_bb > 0 else float('inf')
                    
                    t_opp_ab = t_bf - t_bb
                    t_row['BA'] = t_h / t_opp_ab if t_opp_ab > 0 else 0
                    t_row['OBP'] = (t_h + t_bb) / t_bf if t_bf > 0 else 0
                    t_row['SLG'] = ((t_h - t_hr) + 4*t_hr) / t_opp_ab if t_opp_ab > 0 else 0
                    t_row['OPS'] = t_row['OBP'].iloc[0] + t_row['SLG'].iloc[0]
                    t_row['BAbip'] = (t_h - t_hr) / (t_opp_ab - t_so - t_hr) if (t_opp_ab - t_so - t_hr) > 0 else 0
                    t_row['P/BF'] = t_np / t_bf if t_bf > 0 else 0

                    final_team_p = pd.concat([team_p[br_p_cols].sort_values('WAR', ascending=False), t_row[br_p_cols]], ignore_index=True)
                    st.dataframe(final_team_p.style.format(p_format_dict).apply(style_p_leaders, axis=None), use_container_width=True, hide_index=True)
                else: st.caption("無數據")
    else: st.info("目前沒有投球紀錄可以顯示！")

# ==========================================
# --- 分頁 4：👤 球員專屬資料庫 (Player Page) ---
# ==========================================
with tab4:
    import re
    import numpy as np
    import pandas as pd
    import altair as alt

    st.header("👤 球員專屬資料庫與球探雷達 (Player Profile & Savant)")
    st.caption("在這裡您可以查看全聯盟球員的歷年成績、主客場差異、Savant PR，以及專屬的逐場 Game Log！")

    # 本地 BR 格式打擊率/上壘率專用去零格式化工具
    def fmt_br_style_rate(val):
        if pd.isna(val) or val == float('inf'): return ".000"
        if val >= 1: return f"{val:.3f}"
        return f"{val:.3f}".lstrip('0')

    if df_b_full.empty and df_p_full.empty:
        st.warning("⚠️ 目前無數據可供分析。")
    else:
        if 'sv_player' not in st.session_state: st.session_state['sv_player'] = None
        def update_sv_player(): st.session_state['sv_player'] = st.session_state['sv_player_sel']

        col_name, _ = st.columns([1, 1])
        with col_name:
            b_names = df_b_full['球員姓名'].dropna().unique().tolist() if not df_b_full.empty else []
            p_names = df_p_full['投手姓名'].dropna().unique().tolist() if not df_p_full.empty else []
            
            opts = []
            if b_names: opts.extend([f"🏏 {n}" for n in sorted(b_names)])
            if p_names:
                if b_names: opts.append("--- 投手區 ---")
                opts.extend([f"⚾ {n}" for n in sorted(p_names)])
                
            if not opts:
                st.warning("聯盟尚無球員資料。")
                selected_opt = None
                selected_player = None
                is_pitcher = False
            else:
                player_idx = 0
                if st.session_state['sv_player'] in opts:
                    player_idx = opts.index(st.session_state['sv_player'])
                
                selected_opt = st.selectbox("👤 搜尋全聯盟球員", opts, index=player_idx, key='sv_player_sel', on_change=update_sv_player)
                
                if selected_opt == "--- 投手區 ---":
                    st.warning("請選擇一位球員。")
                    selected_player = None
                    is_pitcher = False
                else:
                    is_pitcher = selected_opt.startswith("⚾")
                    selected_player = selected_opt[2:]

        if selected_player:
            # 抓取球員所屬的所有球隊歷史
            if not is_pitcher:
                p_history = df_b_full[df_b_full['球員姓名'] == selected_player]
                team_history = "/".join(p_history.sort_values('時間戳記')['球隊'].unique())
            else:
                p_history = df_p_full[df_p_full['投手姓名'] == selected_player]
                team_history = "/".join(p_history.sort_values('時間戳記')['球隊'].unique())
                
            full_name = f"[{team_history}] {selected_player}"
            st.markdown(f"## {full_name}")
            
            awards_won = []
            if 'season_cache' in locals() or 'season_cache' in globals():
                for s_idx, cache_data in season_cache.items():
                    mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, _, all_mlb, is_rs_fin, is_ws_fin = cache_data
                    if is_rs_fin:
                        if not mvp_df.empty and selected_player in str(mvp_df.iloc[0]['球員']): awards_won.append("🏅 MVP")
                        if not cy_df.empty and selected_player in str(cy_df.iloc[0]['球員']): awards_won.append("⚾ Cy Young")
                        if not ss_df.empty and selected_player in str(ss_df.iloc[0]['球員']): awards_won.append("🏏 SS")
                        if not roty_df.empty and selected_player in str(roty_df.iloc[0]['球員']): awards_won.append("👶 ROY")
                        for mlb_p in all_mlb:
                            if selected_player in str(mlb_p): awards_won.append("🌟 1st Team")
                    if is_ws_fin:
                        if not fmvp_df.empty and selected_player in str(fmvp_df.iloc[0]['球員']): awards_won.append("🌟 FMVP")
                        ws_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(f"\\[S{s_idx}\\] 世界大賽", regex=False)]
                        if not ws_df.empty:
                            laa_w, lad_w = 0, 0
                            for stg, grp in ws_df.groupby('賽事階段', sort=False):
                                if any('勝' in str(x) for x in grp[grp['球隊']=='LAA']['勝敗'].values): laa_w += 1
                                if any('勝' in str(x) for x in grp[grp['球隊']=='LAD']['勝敗'].values): lad_w += 1
                            ws_winner = "LAA" if laa_w >= 4 else "LAD" if lad_w >= 4 else None
                            
                            played_this_season = False
                            if is_pitcher:
                                s_sub = df_p_full[(df_p_full['投手姓名']==selected_player) & (df_p_full['賽事階段'].astype(str).str.contains(f"\\[S{s_idx}\\]", regex=False))]
                                if not s_sub.empty and s_sub.iloc[-1]['球隊'] == ws_winner: played_this_season = True
                            else:
                                s_sub = df_b_full[(df_b_full['球員姓名']==selected_player) & (df_b_full['賽事階段'].astype(str).str.contains(f"\\[S{s_idx}\\]", regex=False))]
                                if not s_sub.empty and s_sub.iloc[-1]['球隊'] == ws_winner: played_this_season = True
                                
                            if played_this_season:
                                awards_won.append("💍 WS Champ")

            if awards_won:
                award_counts = pd.Series(awards_won).value_counts()
                badges = "  ".join([f"**{k}** (x{v})" for k, v in award_counts.items()])
                st.success(f"**🏆 榮耀勳章櫃**：\n{badges}")

            season_type = st.radio("⚾ 選擇賽事類型", ["例行賽 (Regular Season)", "世界大賽 (Postseason)"], horizontal=True)
            filter_str = "例行賽" if "例行賽" in season_type else "世界大賽"

            t_main, t_log, t_slot_split, t_hof = st.tabs(["📊 生涯數據與進階雷達", "📅 逐場紀錄 (Game Log)", "🔄 生涯各棒次生產力 (Slot Splits)", "🏛️ 歷史定位與相似度 (HOF & Similarity)"])

            def get_award_rank(df_aw, aw_name, p_name):
                if df_aw.empty: return None
                players = df_aw['球員'].tolist()
                for i, p in enumerate(players):
                    if p_name in str(p):
                        rank = i + 1
                        if rank == 1: return aw_name
                        else: return f"{aw_name}-{rank}"
                return None

            if 'global_home_dict' not in st.session_state: st.session_state['global_home_dict'] = {}
            global_home_dict = st.session_state['global_home_dict']

            def clean_stage_name(stage_str): return re.sub(r'\[S\d+\]\s*', '', stage_str)

            # ===============================================
            # 🏏 打者邏輯
            # ===============================================
            if not is_pitcher:
                b_sub_all = df_b_full[df_b_full['球員姓名'] == selected_player].copy()
                b_sub = b_sub_all[b_sub_all['賽事階段'].astype(str).str.contains(filter_str, regex=False)].copy()
                
                if not b_sub_all.empty:
                    for c in ['得分','打席','打數','安打','二壘安打','三壘安打','全壘打','打點','盜壘','四壞球','三振']: 
                        if c not in b_sub_all.columns: b_sub_all[c] = 0
                        b_sub_all[c] = pd.to_numeric(b_sub_all[c], errors='coerce').fillna(0)
                    b_sub_all['Season'] = b_sub_all['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
                    played_seasons = sorted([int(x) for x in b_sub_all['Season'].unique()])
                else:
                    played_seasons = []

                if not b_sub.empty:
                    for c in ['得分','打席','打數','安打','二壘安打','三壘安打','全壘打','打點','盜壘','四壞球','三振']: 
                        if c not in b_sub.columns: b_sub[c] = 0
                        b_sub[c] = pd.to_numeric(b_sub[c], errors='coerce').fillna(0)
                    b_sub['Season'] = b_sub['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
                    sub_played_seasons = sorted([int(x) for x in b_sub['Season'].unique()])

                    def calc_b_stats(df, label, s_idx, is_career=False):
                        pa, ab, r, h, h2, h3, hr = df['打席'].sum(), df['打數'].sum(), df['得分'].sum(), df['安打'].sum(), df['二壘安打'].sum(), df['三壘安打'].sum(), df['全壘打'].sum()
                        rbi, sb, bb, so = df['打點'].sum(), df['盜壘'].sum(), df['四壞球'].sum(), df['三振'].sum()
                        h1 = h - h2 - h3 - hr
                        ba = h / ab if ab > 0 else 0
                        obp = (h + bb) / pa if pa > 0 else 0
                        slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                        ops = obp + slg
                        roba = (0.69*bb + 0.88*h1 + 1.25*h2 + 1.59*h3 + 2.06*hr) / pa if pa > 0 else 0
                        
                        tm_str = "/".join(df.sort_values('時間戳記')['球隊'].unique()) if not is_career else "Multi"
                        if not is_career and len(df.sort_values('時間戳記')['球隊'].unique()) == 1:
                            tm_str = df.sort_values('時間戳記').iloc[0]['球隊']
                            
                        lg_obp, lg_slg = 0.320, 0.400
                        if not is_career:
                            s_pref = f"[S{s_idx}]"
                            lg_b = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        else: 
                            pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                            lg_b = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                            
                        if not lg_b.empty:
                            l_pa = pd.to_numeric(lg_b['打席'], errors='coerce').fillna(0).sum()
                            l_ab = pd.to_numeric(lg_b['打數'], errors='coerce').fillna(0).sum()
                            l_h = pd.to_numeric(lg_b['安打'], errors='coerce').fillna(0).sum()
                            l_bb = pd.to_numeric(lg_b['四壞球'], errors='coerce').fillna(0).sum()
                            l_h2 = pd.to_numeric(lg_b['二壘安打'], errors='coerce').fillna(0).sum()
                            l_h3 = pd.to_numeric(lg_b['三壘安打'], errors='coerce').fillna(0).sum()
                            l_hr = pd.to_numeric(lg_b['全壘打'], errors='coerce').fillna(0).sum()
                            l_h1 = l_h - l_h2 - l_h3 - l_hr
                            lg_obp = (l_h + l_bb) / l_pa if l_pa > 0 else 0.320
                            lg_slg = (l_h1 + 2*l_h2 + 3*l_h3 + 4*l_hr) / l_ab if l_ab > 0 else 0.400
                            lg_woba = (0.69*l_bb + 0.88*l_h1 + 1.25*l_h2 + 1.59*l_h3 + 2.06*l_hr) / l_pa if l_pa > 0 else 0.320
                            
                        ops_plus = 100 * (obp / max(0.001, lg_obp) + slg / max(0.001, lg_slg) - 1)
                        wrc_plus = ((roba / lg_woba) - 1) * 200 + 100 if lg_woba > 0 and pa > 0 else 0
                        
                        pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
                        if '守位' in df.columns:
                            total_pos_adj = sum(pos_adj_dict.get(row['守位'], -0.12) * pd.to_numeric(row['打席'], errors='coerce') for _, row in df.iterrows())
                            weighted_pos_adj = total_pos_adj / pa if pa > 0 else -0.12
                        else:
                            weighted_pos_adj = -0.12

                        ewar = (((wrc_plus - 70) / 80) + weighted_pos_adj) * (pa / 15)
                        ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)
                        
                        aw_list = []
                        if not is_career and int(s_idx) in season_cache:
                            mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, _, all_mlb, is_rs_fin, is_ws_fin = season_cache[int(s_idx)]
                            if "例行賽" in filter_str and is_rs_fin:
                                for aw_name, df_aw in [('MVP', mvp_df), ('ROY', roty_df)]:
                                    r_str = get_award_rank(df_aw, aw_name, selected_player)
                                    if r_str: aw_list.append(r_str)
                                if not ss_df.empty and selected_player in str(ss_df.iloc[0]['球員']): aw_list.append("SS")
                                for mlb_p in all_mlb:
                                    if selected_player in str(mlb_p): aw_list.append("1st Team")
                            elif "世界大賽" in filter_str and is_ws_fin:
                                f_str = get_award_rank(fmvp_df, 'FMVP', selected_player)
                                if f_str: aw_list.append(f_str)
                        
                        aw_str = ", ".join(aw_list) if aw_list and not is_career else ""
                        g = df['賽事階段'].nunique()
                        
                        return {'Season': label, 'Tm': tm_str, 'WAR': ewar, 'G': g, 'PA': int(pa), 'AB': int(ab), 'R': int(r), 
                                'H': int(h), '2B': int(h2), '3B': int(h3), 'HR': int(hr), 'RBI': int(rbi), 'SB': int(sb), 
                                'BB': int(bb), 'SO': int(so), 'BA': ba, 'OBP': obp, 'SLG': slg, 'OPS': ops, 
                                'OPS+': round(ops_plus), 'wRC+': round(wrc_plus), 'rOBA': roba, 'Awards': aw_str}

                    def calc_b_splits(df, label):
                        pa, ab, h, h2, h3, hr = df['打席'].sum(), df['打數'].sum(), df['安打'].sum(), df['二壘安打'].sum(), df['三壘安打'].sum(), df['全壘打'].sum()
                        rbi, bb, so = df['打點'].sum(), df['四壞球'].sum(), df['三振'].sum()
                        h1 = h - h2 - h3 - hr
                        ba = h / ab if ab > 0 else 0
                        obp = (h + bb) / pa if pa > 0 else 0
                        slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                        ops = obp + slg
                        babip_den = ab - so - hr
                        babip = (h - hr) / babip_den if babip_den > 0 else 0
                        
                        roba = (0.69*bb + 0.88*h1 + 1.25*h2 + 1.59*h3 + 2.06*hr) / pa if pa > 0 else 0
                        lg_woba = 0.320
                        pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                        lg_b = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        if not lg_b.empty:
                            l_pa = pd.to_numeric(lg_b['打席'], errors='coerce').fillna(0).sum()
                            l_h, l_bb = pd.to_numeric(lg_b['安打'], errors='coerce').fillna(0).sum(), pd.to_numeric(lg_b['四壞球'], errors='coerce').fillna(0).sum()
                            l_h2, l_h3, l_hr = pd.to_numeric(lg_b['二壘安打'], errors='coerce').fillna(0).sum(), pd.to_numeric(lg_b['三壘安打'], errors='coerce').fillna(0).sum(), pd.to_numeric(lg_b['全壘打'], errors='coerce').fillna(0).sum()
                            l_h1 = l_h - l_h2 - l_h3 - l_hr
                            lg_woba = (0.69*l_bb + 0.88*l_h1 + 1.25*l_h2 + 1.59*l_h3 + 2.06*l_hr) / l_pa if l_pa > 0 else 0.320
                        
                        wrc_plus = ((roba / lg_woba) - 1) * 200 + 100 if lg_woba > 0 and pa > 0 else 0
                        pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
                        if '守位' in df.columns:
                            total_pos_adj = sum(pos_adj_dict.get(row['守位'], -0.12) * pd.to_numeric(row['打席'], errors='coerce') for _, row in df.iterrows())
                            weighted_pos_adj = total_pos_adj / pa if pa > 0 else -0.12
                        else:
                            weighted_pos_adj = -0.12

                        ewar = (((wrc_plus - 70) / 80) + weighted_pos_adj) * (pa / 15)
                        ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)
                        return {'Split': label, 'WAR': ewar, 'PA': int(pa), 'AB': int(ab), 'H': int(h), '2B': int(h2), '3B': int(h3), 'HR': int(hr), 'RBI': int(rbi), 'BB': int(bb), 'SO': int(so), 'BA': ba, 'OBP': obp, 'SLG': slg, 'OPS': ops, 'BABIP': babip}

                    s_wars = []
                    with t_main:
                        st.markdown("### 📊 歷年成績總表 (Career Stats)")
                        stats_list = []
                        career_war = 0.0
                        for s in sub_played_seasons:
                            s_dict = calc_b_stats(b_sub[b_sub['Season'] == str(s)], f"Season {s}", s, is_career=False)
                            career_war += s_dict['WAR']
                            s_wars.append(s_dict['WAR'])
                            stats_list.append(s_dict)
                        
                        yrs = len(sub_played_seasons)
                        c_dict = calc_b_stats(b_sub, f"{yrs}年總和 (Career)", "Career", is_career=True)
                        c_dict['WAR'] = 0.0 if abs(career_war) < 0.05 else round(career_war, 1)
                        c_dict['Tm'] = "Multi" if b_sub['球隊'].nunique() > 1 else b_sub.iloc[0]['球隊']
                        stats_list.append(c_dict)
                        df_disp = pd.DataFrame(stats_list)
                        st.dataframe(df_disp.style.format({'WAR': '{:.1f}', 'BA': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'OPS': '{:.3f}', 'OPS+': '{:.0f}', 'wRC+': '{:.0f}', 'rOBA': '{:.3f}'}), use_container_width=True)

                        st.markdown("### 🏟️ 主客場拆分 (Home/Away Splits)")
                        b_sub_home = b_sub[b_sub.apply(lambda r: global_home_dict.get(r['賽事階段'], "") == r['球隊'], axis=1)]
                        b_sub_away = b_sub[b_sub.apply(lambda r: global_home_dict.get(r['賽事階段'], "") != r['球隊'], axis=1)]
                        spl_list = []
                        if not b_sub_home.empty: spl_list.append(calc_b_splits(b_sub_home, "🏠 主場 (Home)"))
                        if not b_sub_away.empty: spl_list.append(calc_b_splits(b_sub_away, "✈️ 客場 (Away)"))
                        if spl_list:
                            st.dataframe(pd.DataFrame(spl_list).style.format({'WAR': '{:.1f}', 'BA': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'OPS': '{:.3f}', 'BABIP': '{:.3f}'}), use_container_width=True)
                        else:
                            st.info("無主客場數據。")
                            
                        # 球隊拆分
                        if b_sub['球隊'].nunique() > 1:
                            st.markdown("### 🔀 球隊拆分 (Team Splits)")
                            tm_spl_list = []
                            for tm in b_sub['球隊'].unique():
                                tm_df = b_sub[b_sub['球隊'] == tm]
                                tm_spl_list.append(calc_b_splits(tm_df, f"{tm}"))
                            st.dataframe(pd.DataFrame(tm_spl_list).style.format({'WAR': '{:.1f}', 'BA': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'OPS': '{:.3f}', 'BABIP': '{:.3f}'}), use_container_width=True)

                        st.markdown("### 📈 Savant PR 雷達 (Percentile Rankings)")
                        savant_seasons = ["生涯總成績"] + [f"Season {s}" for s in sub_played_seasons]
                        target_savant_season = st.selectbox("📅 選擇 Savant PR 評估年份", savant_seasons, key="savant_season_sel_b")
                        
                        if target_savant_season != "生涯總成績":
                            s_pref = f"[S{target_savant_season.split(' ')[1]}]"
                            b_pool = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)) & (df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        else:
                            pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                            b_pool = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                            
                        if not b_pool.empty:
                            for c in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振']: 
                                if c not in b_pool.columns: b_pool[c] = 0
                                b_pool[c] = pd.to_numeric(b_pool[c], errors='coerce').fillna(0)
                            b_agg = b_pool.groupby('球員姓名').sum(numeric_only=True).reset_index()
                            b_agg = b_agg[b_agg['打席'] > 0].copy()
                            min_pa_savant = 5 if target_savant_season != "生涯總成績" else 10
                            b_agg['Qual'] = b_agg['打席'] >= min_pa_savant
                            if not b_agg.empty:
                                b_agg['1B'] = b_agg['安打'] - b_agg['二壘安打'] - b_agg['三壘安打'] - b_agg['全壘打']
                                b_agg['wOBA'] = (0.69*b_agg['四壞球'] + 0.88*b_agg['1B'] + 1.25*b_agg['二壘安打'] + 1.59*b_agg['三壘安打'] + 2.06*b_agg['全壘打']) / b_agg['打席']
                                t_pa = b_pool['打席'].sum()
                                lg_1b = b_pool['安打'].sum() - b_pool['二壘安打'].sum() - b_pool['三壘安打'].sum() - b_pool['全壘打'].sum()
                                lg_woba = (0.69 * b_pool['四壞球'].sum() + 0.88 * lg_1b + 1.25 * b_pool['二壘安打'].sum() + 1.59 * b_pool['三壘安打'].sum() + 2.06 * b_pool['全壘打'].sum()) / t_pa if t_pa > 0 else 0.320
                                
                                b_agg['wRC+'] = (((b_agg['wOBA'] / lg_woba) - 1) * 200 + 100).fillna(0).astype(int)
                                
                                b_agg['HR%'] = b_agg['全壘打'] / b_agg['打席']
                                b_agg['BB%'] = b_agg['四壞球'] / b_agg['打席']
                                b_agg['K%'] = b_agg['三振'] / b_agg['打席']
                                b_agg['ISO'] = (b_agg['1B'] + 2*b_agg['二壘安打'] + 3*b_agg['三壘安打'] + 4*b_agg['全壘打']) / b_agg['打數'].replace(0, 1) - (b_agg['安打']/b_agg['打數'].replace(0, 1))
                                b_agg['BABIP'] = (b_agg['安打'] - b_agg['全壘打']) / (b_agg['打數'] - b_agg['三振'] - b_agg['全壘打']).replace(0, 1)
                                
                                lg_babip_den = b_pool['打數'].sum() - b_pool['三振'].sum() - b_pool['全壘打'].sum()
                                lg_babip = (b_pool['安打'].sum() - b_pool['全壘打'].sum()) / lg_babip_den if lg_babip_den > 0 else 0.300
                                b_agg['xHits'] = (b_agg['打數'] - b_agg['三振'] - b_agg['全壘打']) * lg_babip
                                luck = np.where((b_agg['安打'] - b_agg['全壘打']) > 0, b_agg['xHits'] / (b_agg['安打'] - b_agg['全壘打']), 1.0)
                                b_agg['x1B'] = b_agg['1B'] * luck
                                b_agg['xBA'] = (b_agg['xHits'] + b_agg['全壘打']) / b_agg['打數'].replace(0, 1)
                                b_agg['xSLG'] = (b_agg['x1B'] + 2*(b_agg['二壘安打']*luck) + 3*(b_agg['三壘安打']*luck) + 4*b_agg['全壘打']) / b_agg['打數'].replace(0, 1)
                                b_agg['xwOBA'] = (0.69*b_agg['四壞球'] + 0.88*b_agg['x1B'] + 1.25*(b_agg['二壘安打']*luck) + 1.59*(b_agg['三壘安打']*luck) + 2.06*b_agg['全壘打']) / b_agg['打席'].replace(0, 1)
                                
                                b_agg['PR_wOBA'] = b_agg['wOBA'].rank(pct=True) * 100
                                b_agg['PR_xwOBA'] = b_agg['xwOBA'].rank(pct=True) * 100
                                b_agg['PR_wRC+'] = b_agg['wRC+'].rank(pct=True) * 100
                                b_agg['PR_xBA'] = b_agg['xBA'].rank(pct=True) * 100
                                b_agg['PR_xSLG'] = b_agg['xSLG'].rank(pct=True) * 100
                                b_agg['PR_HR%'] = b_agg['HR%'].rank(pct=True) * 100
                                b_agg['PR_ISO'] = b_agg['ISO'].rank(pct=True) * 100
                                b_agg['PR_BB%'] = b_agg['BB%'].rank(pct=True) * 100
                                b_agg['PR_K%'] = b_agg['K%'].rank(pct=True, ascending=False) * 100 

                            def render_savant_bar(label, pr_val, raw_val_str, is_qual=True):
                                if pd.isna(pr_val): return
                                pr = max(1, min(100, int(round(pr_val))))
                                if pr >= 90: color = "#d73027"   
                                elif pr >= 70: color = "#fc8d59" 
                                elif pr >= 40: color = "#e0e0e0" 
                                elif pr >= 10: color = "#91bfdb" 
                                else: color = "#4575b4"         
                                bg_style = f"background-color: {color};" if is_qual else f"background: repeating-linear-gradient(45deg, {color}, {color} 8px, #2b2b2b 8px, #2b2b2b 16px);"
                                html = f"""
                                <div style="display: flex; align-items: center; margin-bottom: 12px; font-family: sans-serif;">
                                    <div style="width: 170px; font-weight: 600; font-size: 15px;">{label}</div>
                                    <div style="width: 70px; text-align: right; margin-right: 15px; font-size: 14px; color: gray;">{raw_val_str}</div>
                                    <div style="flex-grow: 1; background-color: #2b2b2b; height: 22px; border-radius: 4px; position: relative; overflow: hidden;">
                                        <div style="width: {pr}%; {bg_style} height: 100%; border-radius: 4px; transition: width 0.5s ease-in-out;"></div>
                                    </div>
                                    <div style="width: 45px; text-align: right; font-weight: 800; font-size: 17px; color: {color};">{pr}</div>
                                </div>
                                """
                                st.markdown(html, unsafe_allow_html=True)

                            c_rad, c_desc = st.columns([2, 1])
                            with c_rad:
                                p_df = b_agg[b_agg['球員姓名'] == selected_player]
                                if not p_df.empty:
                                    p_data = p_df.iloc[0]
                                    is_q = p_data['Qual']
                                    if not is_q: st.warning(f"⚠️ 該範圍僅 {int(p_data['打席'])} 打席，未達門檻，數據可能具高波動性。")
                                    render_savant_bar("綜合指標 (wRC+)", p_data['PR_wRC+'], f"{p_data['wRC+']:.0f}", is_q)
                                    render_savant_bar("預期火力 (xwOBA)", p_data['PR_xwOBA'], f"{p_data['xwOBA']:.3f}", is_q)
                                    render_savant_bar("表面火力 (wOBA)", p_data['PR_wOBA'], f"{p_data['wOBA']:.3f}", is_q)
                                    render_savant_bar("預期打擊率 (xBA)", p_data['PR_xBA'], f"{p_data['xBA']:.3f}", is_q)
                                    render_savant_bar("預期長打率 (xSLG)", p_data['PR_xSLG'], f"{p_data['xSLG']:.3f}", is_q)
                                    render_savant_bar("純長打力 (ISO)", p_data['PR_ISO'], f"{p_data['ISO']:.3f}", is_q)
                                    render_savant_bar("開轟能力 (HR%)", p_data['PR_HR%'], f"{p_data['HR%']*100:.1f}%", is_q)
                                    render_savant_bar("選球能力 (BB%)", p_data['PR_BB%'], f"{p_data['BB%']*100:.1f}%", is_q)
                                    render_savant_bar("不易三振 (K%)", p_data['PR_K%'], f"{p_data['K%']*100:.1f}%", is_q)
                                else: st.info("無此年份數據。")
                            with c_desc:
                                st.markdown("#### 📖 圖例說明")
                                st.markdown("""
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#d73027; border-radius:3px;"></span> <b style="color:#d73027;">PR 90-100</b>：聯盟頂尖</div>
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#fc8d59; border-radius:3px;"></span> <b style="color:#fc8d59;">PR 70-89</b>：優於平均</div>
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#e0e0e0; border-radius:3px;"></span> <b style="color:#e0e0e0;">PR 40-69</b>：聯盟平均</div>
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#91bfdb; border-radius:3px;"></span> <b style="color:#91bfdb;">PR 10-39</b>：低於平均</div>
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#4575b4; border-radius:3px;"></span> <b style="color:#4575b4;">PR 1-9</b>：聯盟墊底</div>
                                <br>
                                <div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background: repeating-linear-gradient(45deg, #e0e0e0, #e0e0e0 4px, #2b2b2b 4px, #2b2b2b 8px); border-radius:3px; vertical-align:middle;"></span> <b>斜線條紋背景</b>：<br>代表打席數尚未達到聯盟門檻，數據可能含有大量運氣成分。</div>
                                """, unsafe_allow_html=True)
                        else:
                            st.info("⚠️ 該賽季無數據。")

                with t_log:
                    if not b_sub_all.empty:
                        st.markdown("### 📅 逐場紀錄 (Game Log)")
                        st.caption("✨ 這裡包含該季**例行賽與世界大賽**的完整逐場紀錄。")
                        log_seasons = [f"Season {s}" for s in played_seasons]
                        log_sel = st.selectbox("📅 選擇紀錄賽季", log_seasons, key="gamelog_b")
                        log_s_str = log_sel.replace("Season ", "")
                        b_game = b_sub_all[b_sub_all['Season'] == log_s_str].sort_values('時間戳記')
                        
                        gl_list = []
                        for idx, r in b_game.iterrows():
                            pa, ab, h, h2 = r.get('打席',0), r.get('打數',0), r.get('安打',0), r.get('二壘安打',0)
                            h3, hr, run, rbi = r.get('三壘安打',0), r.get('全壘打',0), r.get('得分',0), r.get('打點',0)
                            bb, so = r.get('四壞球',0), r.get('三振',0)
                            h1 = h - h2 - h3 - hr
                            ba = h / ab if ab > 0 else 0
                            obp = (h + bb) / pa if pa > 0 else 0
                            slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                            woba = (0.69*bb + 0.88*h1 + 1.25*h2 + 1.59*h3 + 2.06*hr) / pa if pa > 0 else 0
                            
                            stg_cl = clean_stage_name(r['賽事階段'])
                            h_team = global_home_dict.get(r['賽事階段'], "")
                            loc = "主場" if h_team == r['球隊'] else "客場"
                            
                            gl_list.append({
                                '球隊': r['球隊'], '場次': stg_cl, '主客': loc, '打席': int(pa), '打數': int(ab), '得分': int(run), '安打': int(h),
                                '二安': int(h2), '三安': int(h3), '全壘打': int(hr), '打點': int(rbi), '四壞': int(bb), '三振': int(so),
                                '打擊率': ba, '上壘率': obp, '長打率': slg, 'wOBA': woba
                            })
                        if gl_list:
                            st.dataframe(pd.DataFrame(gl_list).style.format({'打擊率':'{:.3f}', '上壘率':'{:.3f}', '長打率':'{:.3f}', 'wOBA':'{:.3f}'}), use_container_width=True)
                    else:
                        st.info("尚無出賽紀錄。")

                with t_slot_split:
                    st.markdown("### 🔄 個人生涯各棒次生產力拆分 (Career Splits by Lineup Slot)")
                    st.caption("✨ 此圖表統計球員生涯在各打序（1~9棒）的真實表現，已修正為 **正統魔球 wRC+**。長條越長代表火力越狂暴，**長條越胖代表在該棒次的打席數越多**！")
                    
                    df_slot = b_sub_all.copy()
                    if not df_slot.empty:
                        df_slot['棒次_idx'] = pd.to_numeric(df_slot['棒次'], errors='coerce').fillna(0).astype(int)
                        df_slot = df_slot[(df_slot['棒次_idx'] >= 1) & (df_slot['棒次_idx'] <= 9)]
                        
                        for tc in ['打席','打數','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振']:
                            if tc in df_slot.columns: df_slot[tc] = pd.to_numeric(df_slot[tc], errors='coerce').fillna(0)
                        
                        if not df_slot.empty:
                            pattern = "|".join([f"\\[S{s}\\]" for s in played_seasons])
                            lg_b = df_b_full[(df_b_full['賽事階段'].astype(str).str.contains(pattern, regex=True))] if not df_b_full.empty else pd.DataFrame()
                            lg_obp, lg_slg, lg_woba = 0.320, 0.400, 0.320
                            if not lg_b.empty:
                                for tc in ['打席','打數','安打','二壘安打','三壘安打','全壘打','四壞球']:
                                    lg_b[tc] = pd.to_numeric(lg_b.get(tc, 0), errors='coerce').fillna(0)
                                l_pa, l_ab = lg_b['打席'].sum(), lg_b['打數'].sum()
                                l_h, l_bb = lg_b['安打'].sum(), lg_b['四壞球'].sum()
                                l_h2, l_h3, l_hr = lg_b['二壘安打'].sum(), lg_b['三壘安打'].sum(), lg_b['全壘打'].sum()
                                l_h1 = l_h - l_h2 - l_h3 - l_hr
                                lg_woba = (0.69*l_bb + 0.88*l_h1 + 1.25*l_h2 + 1.59*l_h3 + 2.06*l_hr) / l_pa if l_pa > 0 else 0.320
                                
                            p_agg = df_slot.groupby('棒次_idx').sum(numeric_only=True).reset_index()
                            p_split_data = []
                            for _, r in p_agg.iterrows():
                                pa, ab, h, h2, h3, hr = r['打席'], r['打數'], r['安打'], r['二壘安打'], r['三壘安打'], r['全壘打']
                                rbi, bb, so = r.get('打點',0), r.get('四壞球',0), r.get('三振',0)
                                p_1b = h - h2 - h3 - hr
                                obp = (h + bb) / max(1, pa)
                                slg = (p_1b + 2*h2 + 3*h3 + 4*hr) / max(1, ab)
                                woba = (0.69*bb + 0.88*p_1b + 1.25*h2 + 1.59*h3 + 2.06*hr) / max(1, pa)
                                
                                wrc_plus = ((woba / lg_woba) - 1) * 200 + 100 if lg_woba > 0 else 0
                                
                                p_split_data.append({
                                    '棒次': f"第 {int(r['棒次_idx'])} 棒", '棒次_num': int(r['棒次_idx']), 'wRC+': int(round(wrc_plus)),
                                    'OPS': f"{(obp+slg):.3f}", '打擊率': f"{(h/max(1,ab)):.3f}", '上壘率': f"{obp:.3f}", '長打率': f"{slg:.3f}",
                                    '安打': int(h), '全壘打': int(hr), '打點': int(rbi), '保送': int(bb), '三振': int(so), '總打席': int(pa)
                                })
                            
                            df_p_split = pd.DataFrame(p_split_data)
                            
                            chart_p_split = alt.Chart(df_p_split).mark_bar(color='#fc8d59', cornerRadiusEnd=4).encode(
                                y=alt.Y('棒次:N', sort=alt.SortField('棒次_num', 'ascending'), title='打擊順序 (Lineup Slot)'),
                                x=alt.X('wRC+:Q', title='該棒次累積火力指數 (wRC+)'),
                                size=alt.Size('總打席:Q', scale=alt.Scale(range=[8, 35]), legend=alt.Legend(title="打席數 (胖瘦)")),
                                tooltip=[
                                    alt.Tooltip('棒次:N', title='打序'), alt.Tooltip('wRC+:Q', title='wRC+'), alt.Tooltip('OPS:N', title='OPS'),
                                    alt.Tooltip('打擊率:N'), alt.Tooltip('上壘率:N'), alt.Tooltip('長打率:N'),
                                    alt.Tooltip('安打:Q'), alt.Tooltip('全壘打:Q'), alt.Tooltip('打點:Q'), alt.Tooltip('保送:Q'), alt.Tooltip('三振:Q'), alt.Tooltip('總打席:Q')
                                ]
                            ).properties(height=360)
                            
                            rule = alt.Chart(pd.DataFrame({'x': [100]})).mark_rule(color='white', strokeDash=[5,5], opacity=0.5).encode(x='x:Q')
                            st.altair_chart((chart_p_split + rule), use_container_width=True)
                        else: st.info("該球員生涯尚無排入 1~9 棒次之常規數據。")
                    else: st.info("該球員無出賽紀錄。")

                with t_hof:
                    if filter_str == "世界大賽":
                        st.warning("⚠️ **【BR 數據庫規則】** 依據 Baseball-Reference 標準，名人堂 (JAWS) 與歷史相似度 (Similarity Scores) **完全不計入季後賽數據**。請將上方賽事類型切換為「例行賽」以解鎖此區塊分析！")
                    else:
                        st.markdown("### 🏛️ 名人堂神主牌預測儀 (JAWS & HOF Monitor)")
                        peak_war = sum(sorted(s_wars, reverse=True)[:7]) if s_wars else 0.0
                        jaws = (career_war + peak_war) / 2.0
                        hof_status = "✨ 首爵入選 (First Ballot)" if jaws >= 40 else "🏛️ 穩健入選 (Solid HOFer)" if jaws >= 30 else "🤔 邊緣徘徊 (Borderline)" if jaws >= 20 else "🏃 尚需努力"
                        
                        hj1, hj2, hj3 = st.columns(3)
                        hj1.metric("JAWS 分數", f"{jaws:.1f}", hof_status)
                        hj2.metric("生涯總 eWAR", f"{career_war:.1f}")
                        hj3.metric("7年巔峰 eWAR (WAR7)", f"{peak_war:.1f}")
                        st.progress(max(0.0, min(1.0, jaws / 30.0)))
    
                        st.markdown("---")
                        st.markdown("### 🧬 Bill James 歷史相似度分數 (Similarity Scores)")
                        st.caption("滿分為 1000，扣分越少代表生涯數據軌跡越相似。**（✨ 已導入強化版懲罰權重，嚴格篩選同型態球員）**")
                        
                        df_b_all = df_b_full[df_b_full['賽事階段'].astype(str).str.contains(filter_str, regex=False)].copy()
                        for c in ['打席','打數','得分','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振','盜壘']:
                            df_b_all[c] = pd.to_numeric(df_b_all.get(c, 0), errors='coerce').fillna(0)
                        
                        sim_agg = df_b_all.groupby('球員姓名').agg({'賽事階段':'nunique', '打席':'sum', '打數':'sum', '得分':'sum', '安打':'sum', '二壘安打':'sum', '三壘安打':'sum', '全壘打':'sum', '打點':'sum', '四壞球':'sum', '三振':'sum', '盜壘':'sum', '守位': lambda x: x.value_counts().index[0] if '守位' in df_b_all.columns and not x.empty else 'DH'}).reset_index()
                        tgt = sim_agg[sim_agg['球員姓名'] == selected_player]
                        
                        if tgt.empty: st.info("尚無數據進行相似度比對。")
                        else:
                            tgt = tgt.iloc[0]
                            sim_scores = []
                            for _, r in sim_agg.iterrows():
                                if r['球員姓名'] == selected_player: continue
                                pos_penalty = abs({"C": 8, "SS": 7, "2B": 6, "CF": 5, "3B": 4, "RF": 3, "LF": 2, "1B": 1, "DH": 0}.get(tgt['守位'], 0) - {"C": 8, "SS": 7, "2B": 6, "CF": 5, "3B": 4, "RF": 3, "LF": 2, "1B": 1, "DH": 0}.get(r['守位'], 0)) * 40
                                
                                diff = (
                                    abs(r['賽事階段'] - tgt['賽事階段'])*2 + 
                                    abs(r['打數'] - tgt['打數'])/20 + 
                                    abs(r['得分'] - tgt['得分'])/5 + 
                                    abs(r['安打'] - tgt['安打'])/5 + 
                                    abs(r['二壘安打'] - tgt['二壘安打'])/2 + 
                                    abs(r['三壘安打'] - tgt['三壘安打']) + 
                                    abs(r['全壘打'] - tgt['全壘打'])*3 + 
                                    abs(r['打點'] - tgt['打點'])/5 + 
                                    abs(r['四壞球'] - tgt['四壞球'])/10 + 
                                    abs(r['三振'] - tgt['三振'])/20 + 
                                    abs(r['盜壘'] - tgt['盜壘'])*2 + 
                                    abs((r['安打']/max(1,r['打數'])) - (tgt['安打']/max(1,tgt['打數'])))*2000 + 
                                    pos_penalty
                                )
                                sim_scores.append({'球員': f"{r['球員姓名']}", '守位': r['守位'], '相似度': 1000 - diff, 'AVG': r['安打']/max(1,r['打數']), 'HR': int(r['全壘打'])}) 
                            if sim_scores: st.dataframe(pd.DataFrame(sim_scores).sort_values('相似度', ascending=False).head(5).style.format({'相似度': '{:.1f}', 'AVG': '{:.3f}'}), use_container_width=True, hide_index=True)

            # ===============================================
            # 🥎 投手邏輯區塊 
            # ===============================================
            else: 
                p_sub_all = df_p_full[df_p_full['投手姓名'] == selected_player].copy()
                p_sub = p_sub_all[p_sub_all['賽事階段'].astype(str).str.contains(filter_str, regex=False)].copy()
                
                if not p_sub_all.empty:
                    for c in ['局數(整數)', '局數(出局數)', '奪三振', '失分', '自責分', '四壞球', '被安打', '被全壘打', '投球數', '被二壘安打', '被三壘安打']: 
                        if c not in p_sub_all.columns: p_sub_all[c] = 0
                        p_sub_all[c] = pd.to_numeric(p_sub_all[c], errors='coerce').fillna(0)
                    p_sub_all['Season'] = p_sub_all['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
                    played_seasons = sorted([int(x) for x in p_sub_all['Season'].unique()])
                else:
                    played_seasons = []

                if not p_sub.empty:
                    for c in ['局數(整數)', '局數(出局數)', '奪三振', '失分', '自責分', '四壞球', '被安打', '被全壘打', '投球數', '被二壘安打', '被三壘安打']: 
                        if c not in p_sub.columns: p_sub[c] = 0
                        p_sub[c] = pd.to_numeric(p_sub[c], errors='coerce').fillna(0)
                    p_sub['勝'] = p_sub['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                    p_sub['敗'] = p_sub['勝敗'].astype(str).apply(lambda x: 1 if '敗' in x else 0)
                    p_sub['救援'] = p_sub['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                    p_sub['中繼'] = p_sub['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
                    p_sub['Season'] = p_sub['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
                    sub_played_seasons = sorted([int(x) for x in p_sub['Season'].unique()])
                    
                    def calc_p_stats(df, label, s_idx, is_career=False):
                        w, l, sv = df['勝'].sum(), df['敗'].sum(), df['救援'].sum()
                        g = df['賽事階段'].nunique()
                        
                        gs = 0
                        stages = df['賽事階段'].unique()
                        for stg in stages:
                            g_full = df_p_full[df_p_full['賽事階段'] == stg].sort_values('時間戳記')
                            if not g_full.empty and g_full.iloc[0]['投手姓名'] == selected_player: gs += 1
                        
                        outs = int(df['局數(整數)'].sum()*3 + df['局數(出局數)'].sum())
                        ip_calc = outs / 3.0
                        ip_disp = (outs // 3) + (outs % 3) / 10.0 
                        
                        # ✨ 修復此處因 get 誤用造成的 SyntaxError
                        h, r, er = df['被安打'].sum(), df['失分'].sum(), df['自責分'].sum()
                        hr, bb, so = df['被全壘打'].sum(), df['四壞球'].sum(), df['奪三振'].sum()
                        bf = outs + h + bb
                        
                        wl_pct = w / (w+l) if (w+l) > 0 else 0
                        era = (er * 9) / ip_calc if ip_calc > 0 else float('inf') if er > 0 else 0.0
                        fip = (((13*hr)+(3*bb)-(2*so))/ip_calc) + 3.10 if ip_calc > 0 else float('inf') if (13*hr+3*bb-2*so)>0 else 3.10
                        whip = (h + bb) / ip_calc if ip_calc > 0 else float('inf') if (h+bb)>0 else 0.0
                        h9 = (h * 9) / ip_calc if ip_calc > 0 else 0.0
                        hr9 = (hr * 9) / ip_calc if ip_calc > 0 else 0.0
                        bb9 = (bb * 9) / ip_calc if ip_calc > 0 else 0.0
                        so9 = (so * 9) / ip_calc if ip_calc > 0 else 0.0
                        
                        so_bb = so / bb if bb > 0 else float('inf')
                        
                        tm_str = "/".join(df.sort_values('時間戳記')['球隊'].unique()) if not is_career else "Multi"
                        if not is_career and len(df.sort_values('時間戳記')['球隊'].unique()) == 1:
                            tm_str = df.sort_values('時間戳記').iloc[0]['球隊']
                        
                        lg_era, lg_era_base = 10.60, 10.60
                        if not is_career:
                            s_pref = f"[S{s_idx}]"
                            lg_p = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        else: 
                            pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                            lg_p = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                            
                        if not lg_p.empty:
                            l_er = pd.to_numeric(lg_p['自責分'], errors='coerce').fillna(0).sum()
                            l_ip = (pd.to_numeric(lg_p['局數(整數)'], errors='coerce').fillna(0).sum()*3 + pd.to_numeric(lg_p['局數(出局數)'], errors='coerce').fillna(0).sum()) / 3.0
                            lg_era = (l_er * 9) / l_ip if l_ip > 0 else 10.60
                            lg_era_base = lg_era
                        
                        era_plus = 100 * (lg_era / era) if era > 0 else (999 if era == 0 and ip_calc > 0 else 0)
                        
                        s_rep_level = lg_era_base * 1.30
                        era_div = max(1.5, lg_era_base * 0.2)
                        tra = (era + fip) / 2.0
                        if ip_calc == 0: ewar = (-0.1 * er) - (0.05 * bb)
                        else: ewar = ((s_rep_level - tra) / era_div) * (ip_calc / 10)
                        ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)
                            
                        aw_list = []
                        if not is_career and int(s_idx) in season_cache:
                            mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, _, all_mlb, is_rs_fin, is_ws_fin = season_cache[int(s_idx)]
                            if "例行賽" in filter_str and is_rs_fin:
                                for aw_name, df_aw in [('CYA', cy_df), ('MVP', mvp_df), ('ROY', roty_df)]:
                                    r_str = get_award_rank(df_aw, aw_name, selected_player)
                                    if r_str: aw_list.append(r_str)
                                for mlb_p in all_mlb:
                                    if selected_player in str(mlb_p): aw_list.append("1st Team")
                            elif "世界大賽" in filter_str and is_ws_fin:
                                f_str = get_award_rank(fmvp_df, 'FMVP', selected_player)
                                if f_str: aw_list.append(f_str)
                                
                        aw_str = ", ".join(aw_list) if aw_list and not is_career else ""
                        
                        return {'Season': label, 'Tm': tm_str, 'WAR': ewar, 'W': int(w), 'L': int(l), 'W-L%': wl_pct, 
                                'ERA': era, 'G': g, 'GS': gs, 'SV': int(sv), 'IP': ip_disp, 
                                'H': int(h), 'R': int(r), 'ER': int(er), 'HR': int(hr), 'BB': int(bb), 
                                'BF': int(bf), 'ERA+': round(era_plus), 'FIP': fip, 'WHIP': whip, 
                                'H9': h9, 'HR9': hr9, 'BB9': bb9, 'SO9': so9, 'SO/BB': so_bb, 'Awards': aw_str}

                    def calc_p_splits(df, label):
                        outs = int(df['局數(整數)'].sum()*3 + df['局數(出局數)'].sum())
                        ip_disp = (outs // 3) + (outs % 3) / 10.0
                        ip_calc = max(0.1, outs / 3.0)

                        h, h2, h3, hr = df['被安打'].sum(), df['被二壘安打'].sum(), df['被三壘安打'].sum(), df['被全壘打'].sum()
                        r, er = df['失分'].sum(), df['自責分'].sum()
                        bb, so = df['四壞球'].sum(), df['奪三振'].sum()
                        bf = outs + h + bb

                        ab = bf - bb if (bf - bb) > 0 else 1
                        ba = h / ab if ab > 0 else 0
                        obp = (h + bb) / bf if bf > 0 else 0
                        h1 = h - h2 - h3 - hr
                        slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                        ops = obp + slg

                        babip_den = bf - bb - so - hr
                        babip = (h - hr) / babip_den if babip_den > 0 else 0
                        
                        era = (er * 9) / ip_calc if ip_calc > 0 else 0.0
                        fip = (((13*hr)+(3*bb)-(2*so))/ip_calc) + 3.10 if ip_calc > 0 else 3.10
                        
                        lg_era_base = 10.60
                        pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                        lg_p = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        if not lg_p.empty:
                            l_er = pd.to_numeric(lg_p['自責分'], errors='coerce').fillna(0).sum()
                            l_ip = (pd.to_numeric(lg_p['局數(整數)'], errors='coerce').fillna(0).sum()*3 + pd.to_numeric(lg_p['局數(出局數)'], errors='coerce').fillna(0).sum()) / 3.0
                            lg_era_base = (l_er * 9) / l_ip if l_ip > 0 else 10.60
                            
                        era_div = max(1.5, lg_era_base * 0.2)
                        tra = (era + fip) / 2.0
                        s_rep_level = lg_era_base * 1.30
                        if ip_calc == 0: ewar = (-0.1 * er) - (0.05 * bb)
                        else: ewar = ((s_rep_level - tra) / era_div) * (ip_calc / 10)
                        ewar = 0.0 if abs(ewar) < 0.05 else round(ewar, 1)

                        return {'Split': label, 'WAR': ewar, 'BF': int(bf), 'IP': ip_disp, 'H': int(h), '2B': int(h2), '3B': int(h3), 'HR': int(hr), 'R': int(r), 'BB': int(bb), 'SO': int(so), 'BA': ba, 'OBP': obp, 'SLG': slg, 'OPS': ops, 'BABIP': babip}

                    s_wars = []
                    with t_main:
                        st.markdown("### 📊 歷年成績總表 (Career Stats)")
                        stats_list = []
                        career_war = 0.0
                        for s in sub_played_seasons:
                            s_dict = calc_p_stats(p_sub[p_sub['Season'] == str(s)], f"Season {s}", s, is_career=False)
                            career_war += s_dict['WAR']
                            s_wars.append(s_dict['WAR'])
                            stats_list.append(s_dict)
                            
                        yrs = len(sub_played_seasons)
                        c_dict = calc_p_stats(p_sub, f"{yrs}年總和 (Career)", "Career", is_career=True)
                        c_dict['WAR'] = 0.0 if abs(career_war) < 0.05 else round(career_war, 1)
                        c_dict['Tm'] = "Multi" if p_sub['球隊'].nunique() > 1 else p_sub.iloc[0]['球隊']
                        stats_list.append(c_dict)
                        df_disp = pd.DataFrame(stats_list)
                        
                        st.dataframe(df_disp.style.format({
                            'WAR': '{:.1f}', 'W-L%': '{:.3f}', 
                            'ERA': lambda x: '∞' if x == float('inf') else f"{x:.2f}", 
                            'FIP': lambda x: '∞' if x == float('inf') else f"{x:.2f}", 
                            'WHIP': lambda x: '∞' if x == float('inf') else f"{x:.2f}", 
                            'IP': '{:.1f}', 'H9': '{:.1f}', 'HR9': '{:.1f}', 'BB9': '{:.1f}', 'SO9': '{:.1f}', 
                            'SO/BB': lambda x: '∞' if x == float('inf') else f"{x:.2f}", 
                            'ERA+': lambda x: '∞' if x == float('inf') or x > 999 else f"{x:.0f}"
                        }), use_container_width=True)

                        st.markdown("### 🏟️ 主客場拆分 (Home/Away Splits)")
                        p_sub_home = p_sub[p_sub.apply(lambda r: global_home_dict.get(r['賽事階段'], "") == r['球隊'], axis=1)]
                        p_sub_away = p_sub[p_sub.apply(lambda r: global_home_dict.get(r['賽事階段'], "") != r['球隊'], axis=1)]
                        spl_list = []
                        if not p_sub_home.empty: spl_list.append(calc_p_splits(p_sub_home, "🏠 主場 (Home)"))
                        if not p_sub_away.empty: spl_list.append(calc_p_splits(p_sub_away, "✈️ 客場 (Away)"))
                        if spl_list:
                            st.dataframe(pd.DataFrame(spl_list).style.format({'WAR': '{:.1f}', 'IP': '{:.1f}', 'BA': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'OPS': '{:.3f}', 'BABIP': '{:.3f}'}), use_container_width=True)
                        else:
                            st.info("無主客場數據。")
                            
                        # 球隊拆分
                        if p_sub['球隊'].nunique() > 1:
                            st.markdown("### 🔀 球隊拆分 (Team Splits)")
                            tm_spl_list = []
                            for tm in p_sub['球隊'].unique():
                                tm_df = p_sub[p_sub['球隊'] == tm]
                                tm_spl_list.append(calc_p_splits(tm_df, f"{tm}"))
                            st.dataframe(pd.DataFrame(tm_spl_list).style.format({'WAR': '{:.1f}', 'IP': '{:.1f}', 'BA': '{:.3f}', 'OBP': '{:.3f}', 'SLG': '{:.3f}', 'OPS': '{:.3f}', 'BABIP': '{:.3f}'}), use_container_width=True)

                        st.markdown("### 🤝 投捕搭檔拆分 (Catcher Splits - BR Style)")
                        if not df_b_full.empty and '守位' in df_b_full.columns:
                            df_c_footprint = df_b_full[df_b_full['守位'].astype(str).str.strip().str.upper() == 'C'][['賽事階段', '球隊', '球員姓名']].drop_duplicates(subset=['賽事階段', '球隊'])
                            df_c_footprint.rename(columns={'球員姓名': 'Catcher'}, inplace=True)
                            
                            p_sub_with_c = pd.merge(p_sub, df_c_footprint, on=['賽事階段', '球隊'], how='left')
                            p_sub_with_c['Catcher'] = p_sub_with_c['Catcher'].fillna('未知捕手')
                            
                            battery_agg = p_sub_with_c.groupby('Catcher').agg({
                                '局數(整數)': 'sum', '局數(出局數)': 'sum', '自責分': 'sum', '奪三振': 'sum', '四壞球': 'sum',
                                '被安打': 'sum', '被全壘打': 'sum', '打者數': 'sum', '失分': 'sum',
                                '被二壘安打': 'sum' if '被二壘安打' in p_sub_with_c.columns else 'count',
                                '被三壘安打': 'sum' if '被三壘安打' in p_sub_with_c.columns else 'count',
                                '賽事階段': 'nunique'
                            }).reset_index()
                            
                            if '被二壘安打' not in p_sub_with_c.columns or battery_agg['被二壘安打'].dtype == object: battery_agg['被二壘打'] = 0
                            else: battery_agg.rename(columns={'被二壘安打': '被二壘打'}, inplace=True)
                            if '被三壘安打' not in p_sub_with_c.columns or battery_agg['被三壘安打' if '被三壘安打' in battery_agg else '被三壘安打'].dtype == object: battery_agg['被三壘打'] = 0
                            else: battery_agg.rename(columns={'被三壘安打': '被三壘打'}, inplace=True)
                                
                            battery_list = []
                            for _, r in battery_agg.iterrows():
                                c_name = r['Catcher']
                                g_cnt = r['賽事階段']
                                c_outs = int(r['局數(整數)']*3 + r['局數(出局數)'])
                                c_ip_calc = c_outs / 3.0
                                c_ip_disp = (c_outs // 3) + (c_outs % 3) / 10.0
                                
                                c_er = r['自責分']
                                c_era = (c_er * 9) / c_ip_calc if c_ip_calc > 0 else 0.0
                                c_so = r['奪三振']
                                c_bb = r['四壞球']
                                c_so_bb = c_so / c_bb if c_bb > 0 else float('inf')
                                
                                c_h = r['被安打']
                                c_hr = r['被全壘打']
                                c_r = r['失分']
                                c_bf = int(c_outs + c_h + c_bb)
                                
                                c_ab = c_bf - c_bb
                                c_ba = c_h / max(1, c_ab)
                                c_obp = (c_h + c_bb) / max(1, c_bf)
                                
                                c_2b = r['被二壘打']
                                c_3b = r['被三壘打']
                                c_1b = c_h - c_2b - c_3b - c_hr
                                c_tb = c_1b + 2*c_2b + 3*c_3b + 4*c_hr
                                c_slg = c_tb / max(1, c_ab)
                                c_ops = c_obp + c_slg
                                
                                babip_den = c_ab - c_so - c_hr
                                c_babip = (c_h - c_hr) / max(1, babip_den)
                                
                                battery_list.append({
                                    'Catcher': c_name, 'G': int(g_cnt), 'IP': c_ip_disp, 'ER': int(c_er), 'ERA': c_era,
                                    'BF': int(c_bf), 'AB': int(c_ab), 'R': int(c_r), 'H': int(c_h), '2B': int(c_2b),
                                    '3B': int(c_3b), 'HR': int(c_hr), 'BB': int(c_bb), 'SO': int(c_so), 'SO/BB': c_so_bb,
                                    'BA': c_ba, 'OBP': c_obp, 'SLG': c_slg, 'OPS': c_ops, 'BAbip': c_babip
                                })
                            
                            if battery_list:
                                df_battery = pd.DataFrame(battery_list).sort_values('G', ascending=False)
                                st.dataframe(df_battery.style.format({
                                    'IP': '{:.1f}', 'ERA': '{:.2f}', 'SO/BB': lambda x: '∞' if x == float('inf') else f"{x:.2f}",
                                    'BA': fmt_br_style_rate, 'OBP': fmt_br_style_rate, 'SLG': fmt_br_style_rate, 'OPS': fmt_br_style_rate, 'BAbip': fmt_br_style_rate
                                }), use_container_width=True, hide_index=True)
                            else:
                                st.caption("暫無搭配捕手之數據組合。")
                        else:
                            st.caption("打者資料庫中無常規守位對照，無法進行投捕交叉推演。")

                        st.markdown("### 📈 Savant PR 雷達 (Percentile Rankings)")
                        savant_seasons = ["生涯總成績"] + [f"Season {s}" for s in sub_played_seasons]
                        target_savant_season = st.selectbox("📅 選擇 Savant PR 評估年份", savant_seasons, key="savant_season_sel_p")
                        
                        if target_savant_season != "生涯總成績":
                            s_pref = f"[S{target_savant_season.split(' ')[1]}]"
                            p_pool = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(s_pref, regex=False)) & (df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                        else:
                            pattern = "|".join([f"\\[S{s}\\]" for s in sub_played_seasons])
                            p_pool = df_p_full[(df_p_full['賽事階段'].astype(str).str.contains(pattern, regex=True)) & (df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False))]
                            
                        if not p_pool.empty:
                            for c in ['局數(整數)', '局數(出局數)', '奪三振', '自責分', '四壞球', '被安打', '被全壘打']: 
                                if c not in p_pool.columns: p_pool[c] = 0
                                p_pool[c] = pd.to_numeric(p_pool[c], errors='coerce').fillna(0)
                            p_agg = p_pool.groupby('投手姓名').sum(numeric_only=True).reset_index()
                            p_agg['IP'] = (p_agg['局數(整數)']*3 + p_agg['局數(出局數)'])/3.0
                            p_agg = p_agg[p_agg['IP'] >= 0].copy()
                            min_ip_savant = 2.0 if target_savant_season != "生涯總成績" else 5.0
                            p_agg['Qual'] = p_agg['IP'] >= min_ip_savant
                            if not p_agg.empty:
                                ip_safe = p_agg['IP'].replace(0, 0.001)
                                p_agg['ERA'] = (p_agg['自責分'] * 9) / ip_safe
                                p_agg['FIP'] = (((13*p_agg['被全壘打'])+(3*p_agg['四壞球'])-(2*p_agg['奪三振']))/ip_safe) + 3.10
                                p_agg['xERA'] = (p_agg['ERA'] + p_agg['FIP']) / 2.0 
                                p_agg['WHIP'] = (p_agg['被安打'] + p_agg['四壞球']) / ip_safe
                                p_agg['K9'] = (p_agg['奪三振'] * 9) / ip_safe
                                p_agg['BB9'] = (p_agg['四壞球'] * 9) / ip_safe
                                p_agg['HR9'] = (p_agg['被全壘打'] * 9) / ip_safe
                                
                                ab_safe = (p_agg['IP']*3 + p_agg['被安打']).replace(0, 0.001)
                                lg_p_bip = p_pool['局數(整數)'].sum()*3 + p_pool['局數(出局數)'].sum() + p_pool['被安打'].sum() - p_pool['奪三振'].sum() - p_pool['被全壘打'].sum()
                                lg_p_babip = (p_pool['被安打'].sum() - p_pool['被全壘打'].sum()) / lg_p_bip if lg_p_bip > 0 else 0.300
                                p_agg['BA'] = p_agg['被安打'] / ab_safe
                                p_agg['xBA'] = (((p_agg['IP']*3 + p_agg['被安打'] - p_agg['奪三振'] - p_agg['被全壘打']) * lg_p_babip) + p_agg['被全壘打']) / ab_safe
                                
                                p_agg['PR_ERA'] = p_agg['ERA'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_xERA'] = p_agg['xERA'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_FIP'] = p_agg['FIP'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_WHIP'] = p_agg['WHIP'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_K9'] = p_agg['K9'].rank(pct=True) * 100
                                p_agg['PR_BB9'] = p_agg['BB9'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_HR9'] = p_agg['HR9'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_BA'] = p_agg['BA'].rank(pct=True, ascending=False) * 100
                                p_agg['PR_xBA'] = p_agg['xBA'].rank(pct=True, ascending=False) * 100

                            def render_savant_bar_local_p(label, pr_val, raw_val_str, is_qual=True):
                                if pd.isna(pr_val): return
                                pr = max(1, min(100, int(round(pr_val))))
                                color = "#d73027" if pr >= 90 else "#fc8d59" if pr >= 70 else "#e0e0e0" if pr >= 40 else "#91bfdb" if pr >= 10 else "#4575b4"
                                bg_style = f"background-color: {color};" if is_qual else f"background: repeating-linear-gradient(45deg, {color}, {color} 8px, #2b2b2b 8px, #2b2b2b 16px);"
                                st.markdown(f"""<div style="display: flex; align-items: center; margin-bottom: 12px; font-family: sans-serif;"><div style="width: 170px; font-weight: 600; font-size: 15px;">{label}</div><div style="width: 70px; text-align: right; margin-right: 15px; font-size: 14px; color: gray;">{raw_val_str}</div><div style="flex-grow: 1; background-color: #2b2b2b; height: 22px; border-radius: 4px; position: relative; overflow: hidden;"><div style="width: {pr}%; {bg_style} height: 100%; border-radius: 4px;"></div></div><div style="width: 45px; text-align: right; font-weight: 800; font-size: 17px; color: {color};">{pr}</div></div>""", unsafe_allow_html=True)

                            c_rad, c_desc = st.columns([2, 1])
                            with c_rad:
                                p_df = p_agg[p_agg['投手姓名'] == selected_player]
                                if not p_df.empty:
                                    p_data = p_df.iloc[0]
                                    is_q = p_data['Qual']
                                    if not is_q: st.warning(f"⚠️ 該範圍僅 {p_data['IP']:.1f} 局，未達門檻，數據可能具高波動性。")
                                    render_savant_bar_local_p("預期防禦率 (xERA)", p_data['PR_xERA'], f"{p_data['xERA']:.2f}", is_q)
                                    render_savant_bar_local_p("獨立防禦率 (FIP)", p_data['PR_FIP'], f"{p_data['FIP']:.2f}", is_q)
                                    render_savant_bar_local_p("表面防禦率 (ERA)", p_data['PR_ERA'], f"{p_data['ERA']:.2f}", is_q)
                                    render_savant_bar_local_p("預期被打擊率 (xBA)", p_data['PR_xBA'], f"{p_data['xBA']:.3f}", is_q)
                                    render_savant_bar_local_p("被打擊率 (BA)", p_data['PR_BA'], f"{p_data['BA']:.3f}", is_q)
                                    render_savant_bar_local_p("每局被上壘率 (WHIP)", p_data['PR_WHIP'], f"{p_data['WHIP']:.2f}", is_q)
                                    render_savant_bar_local_p("三振能力 (K/9)", p_data['PR_K9'], f"{p_data['K9']:.1f}", is_q)
                                    render_savant_bar_local_p("控球能力 (BB/9)", p_data['PR_BB9'], f"{p_data['BB9']:.1f}", is_q)
                                    render_savant_bar_local_p("壓制長打 (HR/9)", p_data['PR_HR9'], f"{p_data['HR9']:.1f}", is_q)
                                else: st.info("無此年份數據。")
                            with c_desc:
                                st.markdown("#### 📖 圖例說明")
                                st.markdown("""<div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#d73027; border-radius:3px;"></span> <b style="color:#d73027;">PR 90-100</b>：聯盟頂尖</div><div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#fc8d59; border-radius:3px;"></span> <b style="color:#fc8d59;">PR 70-89</b>：優於平均</div><div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#e0e0e0; border-radius:3px;"></span> <b style="color:#e0e0e0;">PR 40-69</b>：聯盟平均</div><div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#91bfdb; border-radius:3px;"></span> <b style="color:#91bfdb;">PR 10-39</b>：低於平均</div><div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background-color:#4575b4; border-radius:3px;"></span> <b style="color:#4575b4;">PR 1-9</b>：聯盟墊底</div><br><div style="margin-bottom: 8px;"><span style="display:inline-block; width:15px; height:15px; background: repeating-linear-gradient(45deg, #e0e0e0, #e0e0e0 4px, #2b2b2b 4px, #2b2b2b 8px); border-radius:3px; vertical-align:middle;"></span> <b>斜線條紋背景</b>：<br>代表局數尚未達到聯盟門檻，數據可能含有大量運氣成分。</div>""", unsafe_allow_html=True)
                        else: st.info("⚠️ 該賽季無數據。")
                        
                with t_log:
                    if not p_sub_all.empty:
                        st.markdown("### 📅 逐場紀錄 (Game Log)")
                        st.caption("✨ 這裡包含該季**例行賽與世界大賽**的完整逐場紀錄。")
                        log_seasons = [f"Season {s}" for s in played_seasons]
                        log_sel = st.selectbox("📅 選擇紀錄賽季", log_seasons, key="gamelog_p")
                        log_s_str = log_sel.replace("Season ", "")
                        p_game = p_sub_all[p_sub_all['Season'] == log_s_str].sort_values('時間戳記')
                        
                        gl_list = []
                        for idx, r in p_game.iterrows():
                            rec_l = []
                            if '勝' in r.get('勝敗',''): rec_l.append('W')
                            if '敗' in r.get('勝敗',''): rec_l.append('L')
                            if '救援' in r.get('勝敗',''): rec_l.append('SV')
                            if '中繼' in r.get('勝敗',''): rec_l.append('HLD')
                            rec_str = ",".join(rec_l) if rec_l else "-"
                            
                            outs = int(r.get('局數(整數)',0)*3 + r.get('局數(出局數)',0))
                            ip_c = outs / 3.0
                            ip_disp = (outs // 3) + (outs % 3) / 10.0
                            
                            h, run, er = r.get('被安打',0), r.get('失分',0), r.get('自責分',0)
                            h2, h3, hr = r.get('被二壘安打',0), r.get('被三壘安打',0), r.get('被全壘打',0)
                            bb, np_c, so = r.get('四壞球',0), r.get('投球數',0), r.get('奪三振',0)
                            bf = outs + h + bb
                            
                            era = (er * 9) / ip_c if ip_c > 0 else 0.0
                            ab = bf - bb if (bf - bb) > 0 else 1
                            ba = h / ab if ab > 0 else 0
                            obp = (h + bb) / bf if bf > 0 else 0
                            
                            h1 = h - h2 - h3 - hr
                            slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                            
                            stg_cl = clean_stage_name(r['賽事階段'])
                            h_team = global_home_dict.get(r['賽事階段'], "")
                            loc = "主場" if h_team == r['球隊'] else "客場"
                            
                            gl_list.append({
                                '球隊': r['球隊'], '場次': stg_cl, '主客': loc, '紀錄': rec_str, '局數': ip_disp, '面對打者': int(bf), '投球數': int(np_c),
                                '失分': int(run), '責失': int(er), '被安打': int(h), '二安': int(h2), '三安': int(h3), '全壘打': int(hr),
                                '四壞': int(bb), '三振': int(so), '打擊率': ba, '上壘率': obp, '長打率': slg, '防禦率': era
                            })
                        if gl_list:
                            st.dataframe(pd.DataFrame(gl_list).style.format({'局數':'{:.1f}', '打擊率':'{:.3f}', '上壘率':'{:.3f}', '長打率':'{:.3f}', '防禦率':'{:.2f}'}), use_container_width=True)
                    else:
                        st.info("尚無出賽紀錄。")

                with t_slot_split:
                    st.info("💡 投手並無打擊棒次數據。")

                # =======================================================
                # 🏛️ 投手：歷史定位與相似度 (HOF & Similarity)
                # =======================================================
                with t_hof:
                    if filter_str == "世界大賽":
                        st.warning("⚠️ **【BR 數據庫規則】** 依據 Baseball-Reference 標準，名人堂 (JAWS) 與歷史相似度 (Similarity Scores) **完全不計入季後賽數據**。請將上方賽事類型切換為「例行賽」以解鎖此區塊分析！")
                    else:
                        st.markdown("### 🏛️ 名人堂神主牌預測儀 (JAWS & HOF Monitor)")
                        peak_war = sum(sorted(s_wars, reverse=True)[:7]) if s_wars else 0.0
                        jaws = (career_war + peak_war) / 2.0
                        st.columns(3)[0].metric("JAWS 分數", f"{jaws:.1f}", "✨ 殿堂級王牌" if jaws >= 35 else "🏃 穩定累積中")
                        st.progress(max(0.0, min(1.0, jaws / 35.0)))
    
                        st.markdown("---")
                        st.markdown("### 🧬 Bill James 歷史相似度分數 (Similarity Scores)")
                        st.caption("滿分為 1000，扣分越少代表生涯投球數據軌跡越相似。**（✨ 已導入強化版懲罰權重，嚴格篩選同型態球員）**")
                        
                        df_p_all = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(filter_str, regex=False)].copy()
                        for c in ['局數(整數)','局數(出局數)','被安打','四壞球','奪三振','自責分']:
                            if c not in df_p_all.columns: df_p_all[c] = 0
                            df_p_all[c] = pd.to_numeric(df_p_all[c], errors='coerce').fillna(0)
                            
                        df_p_all['W'] = df_p_all['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
                        df_p_all['L'] = df_p_all['勝敗'].astype(str).apply(lambda x: 1 if '敗' in x else 0)
                        df_p_all['SV'] = df_p_all['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
                        df_p_all['GS'] = df_p_all.groupby(['賽事階段', '球隊']).cumcount() == 0
                        df_p_all['GS'] = df_p_all['GS'].astype(int)
                        
                        sim_agg_p = df_p_all.groupby('投手姓名').agg({
                            '賽事階段':'nunique', '局數(整數)':'sum', '局數(出局數)':'sum', '被安打':'sum', 
                            '四壞球':'sum', '奪三振':'sum', '自責分':'sum', 'W':'sum', 'L':'sum', 'SV':'sum', 'GS':'sum'
                        }).reset_index()
                        
                        tgt = sim_agg_p[sim_agg_p['投手姓名'] == selected_player]
                        if tgt.empty:
                            st.info("尚無數據進行相似度比對。")
                        else:
                            tgt = tgt.iloc[0]
                            t_ip = (tgt['局數(整數)']*3 + tgt['局數(出局數)'])/3.0
                            t_era = (tgt['自責分'] * 9) / t_ip if t_ip > 0 else 0
                            t_wpct = tgt['W'] / (tgt['W'] + tgt['L']) if (tgt['W'] + tgt['L']) > 0 else 0
                            t_is_sp = (tgt['GS'] / max(1, tgt['賽事階段'])) > 0.5
                            
                            sim_scores = []
                            for _, r in sim_agg_p.iterrows():
                                if r['投手姓名'] == selected_player: continue
                                r_ip = (r['局數(整數)']*3 + r['局數(出局數)'])/3.0
                                r_era = (r['自責分'] * 9) / r_ip if r_ip > 0 else 0
                                r_wpct = r['W'] / (r['W'] + r['L']) if (r['W'] + r['L']) > 0 else 0
                                
                                r_is_sp = (r['GS'] / max(1, r['賽事階段'])) > 0.5
                                role_penalty = 100 if t_is_sp != r_is_sp else 0
                                
                                diff = (
                                    abs(r['W'] - tgt['W'])*3 + 
                                    abs(r['L'] - tgt['L']) + 
                                    (abs(r_wpct - t_wpct)*1000 if max(r['W'], tgt['W']) >= 10 else 0) + 
                                    abs(r_era - t_era)*100 + 
                                    abs(r['賽事階段'] - tgt['賽事階段'])*2 + 
                                    abs(r_ip - t_ip)/5 + 
                                    abs(r['被安打'] - tgt['被安打'])/15 + 
                                    abs(r['奪三振'] - tgt['奪三振'])/10 + 
                                    abs(r['四壞球'] - tgt['四壞球'])/5 + 
                                    abs(r['SV'] - tgt['SV'])*3 + 
                                    role_penalty
                                )
                                
                                score = 1000 - diff
                                t_role_str = "SP" if r_is_sp else "RP"
                                sim_scores.append({'球員': f"{r['投手姓名']}", '角色': t_role_str, '相似度': score, 'W': r['W'], 'ERA': r_era, 'SO': r['奪三振']})
                                
                            sim_df = pd.DataFrame(sim_scores)
                            if not sim_df.empty:
                                sim_df = sim_df.sort_values('相似度', ascending=False).head(5)
                                st.dataframe(sim_df.style.format({'相似度': '{:.1f}', 'ERA': '{:.2f}'}), use_container_width=True, hide_index=True)
                            else:
                                st.info("資料庫中尚無其他球員可供比對。")
# ==========================================
# --- 分頁 5：🏛️ 聯盟大獎與極端紀錄室 ---
# ==========================================
with tab5:
    import re
    import pandas as pd
    import numpy as np
    import altair as alt

    st.header("🏛️ 聯盟大獎與極端紀錄室 (Awards & Extremes)")
    st.caption("全聯盟的賽季大獎、最佳陣容、里程碑以及單場極端紀錄。")
    
    df_b_full = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p_full = st.session_state.get('df_p_raw', pd.DataFrame())
    
    # 🛡️ 建立全數值化的純淨底層 (解決 Groupby 字串被丟棄導致算錯的致命問題)
    df_b_clean = df_b_full.copy()
    for col in ['打席','打數','得分','安打','二壘安打','三壘安打','全壘打','打點','四壞球','三振','盜壘']: 
        if col in df_b_clean.columns: df_b_clean[col] = pd.to_numeric(df_b_clean[col], errors='coerce').fillna(0)
        
    df_p_clean = df_p_full.copy()
    if not df_p_clean.empty:
        df_p_clean['勝'] = df_p_clean['勝敗'].astype(str).apply(lambda x: 1 if '勝' in x else 0)
        df_p_clean['敗'] = df_p_clean['勝敗'].astype(str).apply(lambda x: 1 if '敗' in x else 0)
        df_p_clean['救援'] = df_p_clean['勝敗'].astype(str).apply(lambda x: 1 if '救援' in x else 0)
        df_p_clean['中繼'] = df_p_clean['勝敗'].astype(str).apply(lambda x: 1 if '中繼' in x else 0)
        for col in ['局數(整數)', '局數(出局數)', '奪三振', '失分', '自責分', '四壞球', '被全壘打', '投球數', '被安打']: 
            if col in df_p_clean.columns: df_p_clean[col] = pd.to_numeric(df_p_clean[col], errors='coerce').fillna(0)
    
    if '賽事階段' not in df_b_clean.columns: df_b_clean['賽事階段'] = ""
    if '賽事階段' not in df_p_clean.columns: df_p_clean['賽事階段'] = ""
    
    def safe_val(val):
        try: return float(val) if pd.notna(val) else 0.0
        except: return 0.0
    
    max_season = 1
    if not df_p_clean.empty:
        s_nums_ext = df_p_clean['賽事階段'].astype(str).str.extract(r'\[S(\d+)\]')[0].dropna().astype(int)
        if not s_nums_ext.empty: max_season = int(s_nums_ext.max())

    # ✨ 終極無敵：分頁五專屬主客場推演引擎 (完美處理和局與得失分差)
    def build_tab5_home_dict(df_p, df_b, max_s):
        h_dict = {}
        prev_ws_loser = "LAD"
        for s in range(1, max_s + 2):
            # 1. 決定例行賽主場優勢 (前一年 WS 輸家)
            rs_hfa = "LAA" if s == 1 else prev_ws_loser
            if s > 1:
                p_ws = df_p[df_p['賽事階段'].astype(str).str.contains(f"\\[S{s-1}\\] 世界大賽", regex=False)]
                if not p_ws.empty:
                    laa_ws = p_ws[p_ws['球隊']=='LAA']['勝'].sum()
                    lad_ws = p_ws[p_ws['球隊']=='LAD']['勝'].sum()
                    if laa_ws > lad_ws: rs_hfa = "LAD"
                    elif lad_ws > laa_ws: rs_hfa = "LAA"
                    else:
                        # WS 和局或沒打完，回推看前一年例行賽戰績
                        p_rs = df_p[df_p['賽事階段'].astype(str).str.contains(f"\\[S{s-1}\\] 例行賽", regex=False)]
                        laa_rs = p_rs[p_rs['球隊']=='LAA']['勝'].sum()
                        lad_rs = p_rs[p_rs['球隊']=='LAD']['勝'].sum()
                        if laa_rs > lad_rs: rs_hfa = "LAD"
                        elif lad_rs > laa_rs: rs_hfa = "LAA"
                        else:
                            # 例行賽也平手 (包含和局)，比得失分差
                            b_rs = df_b[df_b['賽事階段'].astype(str).str.contains(f"\\[S{s-1}\\] 例行賽", regex=False)]
                            laa_rd = b_rs[b_rs['球隊']=='LAA']['得分'].sum() - p_rs[p_rs['球隊']=='LAA']['失分'].sum()
                            lad_rd = b_rs[b_rs['球隊']=='LAD']['得分'].sum() - p_rs[p_rs['球隊']=='LAD']['失分'].sum()
                            rs_hfa = "LAD" if laa_rd > lad_rd else "LAA"

            for g in range(1, 13):
                h_tm = rs_hfa if g % 2 == 1 else ("LAD" if rs_hfa == "LAA" else "LAA")
                h_dict[f"[S{s}] 例行賽 G{g}"] = h_tm
                h_dict[f"[S{s}] 例行賽 第{g}場"] = h_tm

            # 2. 決定世界大賽主場優勢 (今年例行賽戰績，平手比得失分差)
            ws_hfa = "LAA"
            c_rs_p = df_p[df_p['賽事階段'].astype(str).str.contains(f"\\[S{s}\\] 例行賽", regex=False)]
            if not c_rs_p.empty:
                laa_rs = c_rs_p[c_rs_p['球隊']=='LAA']['勝'].sum()
                lad_rs = c_rs_p[c_rs_p['球隊']=='LAD']['勝'].sum()
                if laa_rs > lad_rs: ws_hfa = "LAA"
                elif lad_rs > laa_rs: ws_hfa = "LAD"
                else:
                    c_rs_b = df_b[df_b['賽事階段'].astype(str).str.contains(f"\\[S{s}\\] 例行賽", regex=False)]
                    laa_rd = c_rs_b[c_rs_b['球隊']=='LAA']['得分'].sum() - c_rs_p[c_rs_p['球隊']=='LAA']['失分'].sum()
                    lad_rd = c_rs_b[c_rs_b['球隊']=='LAD']['得分'].sum() - c_rs_p[c_rs_p['球隊']=='LAD']['失分'].sum()
                    ws_hfa = "LAD" if lad_rd > laa_rd else "LAA"
                    
            for g in range(1, 8):
                h_tm = ws_hfa if g in [1, 2, 6, 7] else ("LAD" if ws_hfa == "LAA" else "LAA")
                h_dict[f"[S{s}] 世界大賽 G{g}"] = h_tm
                h_dict[f"[S{s}] 世界大賽 第{g}場"] = h_tm
                
            # 3. 更新下一年起始用的 WS 輸家
            s_ws_p = df_p[df_p['賽事階段'].astype(str).str.contains(f"\\[S{s}\\] 世界大賽", regex=False)]
            if not s_ws_p.empty:
                laa_ws = s_ws_p[s_ws_p['球隊']=='LAA']['勝'].sum()
                lad_ws = s_ws_p[s_ws_p['球隊']=='LAD']['勝'].sum()
                if laa_ws > lad_ws: prev_ws_loser = "LAD"
                elif lad_ws > laa_ws: prev_ws_loser = "LAA"

        manual_home_correction = {
            "[S6] 世界大賽 G1": "LAD", "[S6] 世界大賽 G2": "LAD", "[S6] 世界大賽 G3": "LAA",
            "[S6] 世界大賽 G4": "LAA", "[S6] 世界大賽 G5": "LAA", "[S6] 世界大賽 G6": "LAD", "[S6] 世界大賽 G7": "LAD",
        }
        h_dict.update(manual_home_correction)
        return h_dict

    tab5_home_dict = build_tab5_home_dict(df_p_clean, df_b_clean, max_season)
    
    def get_home_team_tab5(stage_str):
        clean = str(stage_str).strip()
        if clean in tab5_home_dict: return tab5_home_dict[clean]
        for k, v in tab5_home_dict.items():
            if k.replace(' ', '') == clean.replace(' ', ''): return v
        return "LAA" 

    curr_s_prefix = f"[S{max_season}]"

    b_saber = df_b_clean.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index() if not df_b_clean.empty else pd.DataFrame()
    p_saber = df_p_clean.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index() if not df_p_clean.empty else pd.DataFrame()
    if not p_saber.empty:
        p_saber['局數'] = (p_saber['局數(整數)']*3 + p_saber['局數(出局數)'])/3.0
    
    t_awards, t_all_mlb, t_game_mvps, t_leaders, t_milestones, t_streaks, t_extremes = st.tabs([
        "🏆 賽季大獎", "🌟 最佳陣容", "🏅 歷場 MVP", "👑 歷史神主牌", "⏳ 里程碑追蹤", "💎 神聖與連勝", "🤯 單場極端榜"
    ])

    def track_award(dict_counts, df):
        if not df.empty:
            winner = df.iloc[0]['球員']
            dict_counts[winner] = dict_counts.get(winner, 0) + 1
            return dict_counts[winner]
        return 0

    with t_awards:
        st.subheader("🏆 歷屆賽季大獎與 BBWAA 記者票選明細")
        award_counts = {'MVP': {}, 'CyYoung': {}, 'ROTY': {}, 'SilverSlugger': {}, 'FMVP': {}}
        st.caption("※ 註：MVP與賽揚獎的 WAR 值皆為「例行賽限定」之計算基準。(例行賽未滿 10 場將只顯示領跑者)")
        
        for s_idx in range(1, max_season + 1):
            if s_idx not in season_cache: continue
                
            is_expanded = (s_idx == max_season)
            with st.expander(f"📖 Season {s_idx} 大獎得主與票選結果", expanded=is_expanded):
                mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, rs_cand, all_mlb_winners, is_rs_fin, is_ws_fin = season_cache[s_idx]
                
                if not is_rs_fin: st.warning(f"⚠️ Season {s_idx} 例行賽尚未打滿 10 場，下方為「模擬領跑者」，大獎尚未正式定案。")
                
                c_mvp = track_award(award_counts['MVP'], mvp_df) if is_rs_fin else 0
                c_cy = track_award(award_counts['CyYoung'], cy_df) if is_rs_fin else 0
                c_ss = track_award(award_counts['SilverSlugger'], ss_df) if is_rs_fin else 0
                c_roty = track_award(award_counts['ROTY'], roty_df) if is_rs_fin else 0
                c_fmvp = track_award(award_counts['FMVP'], fmvp_df) if is_ws_fin else 0
                
                mvp_str = f"{mvp} {'★第'+str(c_mvp)+'次' if c_mvp > 1 else ''}" if "無" not in mvp else mvp
                if not is_rs_fin and mvp_str != "無": mvp_str += " (領跑中)"
                cy_str = f"{cy} {'★第'+str(c_cy)+'次' if c_cy > 1 else ''}" if "無" not in cy else cy
                if not is_rs_fin and cy_str != "無": cy_str += " (領跑中)"
                ss_str = f"{ss} {'★第'+str(c_ss)+'次' if c_ss > 1 else ''}" if "無" not in ss else ss
                if not is_rs_fin and ss_str != "無": ss_str += " (領跑中)"
                fmvp_str = f"{fmvp} {'★第'+str(c_fmvp)+'次' if c_fmvp > 1 else ''}" if "無" not in fmvp else fmvp
                roty_str = f"{roty}" 
                if not is_rs_fin and roty_str != "無": roty_str += " (領跑中)"
                
                c1, c2 = st.columns(2)
                fmt = {'第一名選票': '{:.0f}', '第二名選票': '{:.0f}', '第三名選票': '{:.0f}', '總積分': '{:.0f}'}
                
                with c1:
                    st.markdown(f"**🏅 年度 MVP**：\n{mvp_str}")
                    if not mvp_df.empty:
                        with st.expander("📊 查看 MVP BBWAA 記者投票明細"): st.dataframe(mvp_df.head(5).style.format(fmt), use_container_width=True)
                    st.markdown("---")
                    st.markdown(f"**⚾ 賽揚獎 (Cy Young)**：\n{cy_str}")
                    if not cy_df.empty:
                        with st.expander("📊 查看賽揚獎 BBWAA 記者投票明細"): st.dataframe(cy_df.head(5).style.format(fmt), use_container_width=True)
                    st.markdown("---")
                    st.markdown(f"**🌟 世界大賽 FMVP**：\n{fmvp_str}")
                    if not fmvp_df.empty:
                        with st.expander("📊 查看 FMVP 評委投票明細", expanded=not is_ws_fin): st.dataframe(fmvp_df.head(5).style.format(fmt), use_container_width=True)
                with c2:
                    st.markdown(f"**👶 新人王 (ROTY)**：\n{roty_str}")
                    if not roty_df.empty:
                        with st.expander("📊 查看新人王 BBWAA 記者投票明細"): st.dataframe(roty_df.head(5).style.format(fmt), use_container_width=True)
                    st.markdown("---")
                    st.markdown(f"**🏏 銀棒獎 (Silver Slugger)**：\n{ss_str}")
                    if not ss_df.empty:
                        with st.expander("📊 查看銀棒獎 BBWAA 記者投票明細"): st.dataframe(ss_df.head(5).style.format(fmt), use_container_width=True)

                st.markdown("---")
                st.markdown("### 🎖️ 聯盟特別肯定獎項 (Special Awards)")
                
                tough_cy_str = "無"
                if rs_cand:
                    pitchers_pool = {k: v for k, v in rs_cand.items() if v.get('類型') in ['投手', '二刀流'] and v.get('Qual', False)}
                    if pitchers_pool:
                        zero_wins = [k for k, v in pitchers_pool.items() if v.get('W', 0) == 0 and v.get('eWAR', 0) >= 0.5]
                        if zero_wins:
                            tough_winner = max(zero_wins, key=lambda k: pitchers_pool[k]['eWAR'])
                            tough_cy_str = f"😢 {tough_winner} (eWAR {pitchers_pool[tough_winner]['eWAR']:.1f} | 0勝 | ERA {pitchers_pool[tough_winner].get('ERA', 0):.2f})"
                        else:
                            top_pitchers = sorted(pitchers_pool.items(), key=lambda x: x[1]['eWAR'], reverse=True)[:3]
                            low_wins = [x for x in top_pitchers if x[1].get('W', 0) <= 1]
                            if low_wins:
                                tough_winner = min(low_wins, key=lambda x: x[1].get('W', 0))
                                tough_cy_str = f"😢 {tough_winner[0]} (eWAR {tough_winner[1]['eWAR']:.1f} | {int(tough_winner[1].get('W',0))}勝 | ERA {tough_winner[1].get('ERA', 0):.2f})"
                
                bullpen_king_str = "無"
                s_pref = f"[S{s_idx}]"
                df_p_rs_streak = df_p_clean[(df_p_clean['賽事階段'].astype(str).str.contains(s_pref, regex=False)) & (df_p_clean['賽事階段'].astype(str).str.contains("例行賽", regex=False))].copy()
                if not df_p_rs_streak.empty:
                    df_p_rs_streak = df_p_rs_streak.sort_values('時間戳記')
                    df_p_rs_streak['g_idx'] = df_p_rs_streak.groupby(['賽事階段', '球隊']).cumcount()
                    df_rp_only = df_p_rs_streak[df_p_rs_streak['g_idx'] > 0]
                    if not df_rp_only.empty:
                        rp_rank = df_rp_only.groupby(['球隊', '投手姓名']).size().reset_index(name='apps')
                        max_rp = rp_rank.sort_values('apps', ascending=False).iloc[0]
                        bullpen_king_str = f"🔒 [{max_rp['球隊']}] {max_rp['投手姓名']} (瘋狂出賽 {int(max_rp['apps'])} 場後援)"
                    else: bullpen_king_str = "無 (全季皆由先發投手完投)"

                comeback_str = "無 (首賽季不頒發)"
                if s_idx > 1 and (s_idx - 1) in season_cache:
                    past_cand = season_cache[s_idx - 1][10]
                    if rs_cand and past_cand:
                        cb_scores = {}
                        for name, curr_stats in rs_cand.items():
                            curr_war = curr_stats.get('eWAR', 0.0)
                            p_name_only = name.split('] ')[1] if '] ' in name else name
                            found_past, past_war = False, 0.0
                            for old_name, old_stats in past_cand.items():
                                old_name_only = old_name.split('] ')[1] if '] ' in old_name else old_name
                                if p_name_only == old_name_only:
                                    past_war = old_stats.get('eWAR', 0.0)
                                    found_past = True
                                    break
                            if found_past and past_war <= 0.5 and curr_war > 0.5:
                                cb_scores[name] = curr_war - past_war
                        if cb_scores:
                            cb_winner = max(cb_scores.items(), key=lambda x: x[1])
                            comeback_str = f"🔥 {cb_winner[0]} (eWAR 從去年的 {rs_cand[cb_winner[0]]['eWAR'] - cb_winner[1]:.1f} 暴升至 {rs_cand[cb_winner[0]]['eWAR']:.1f}!)"
                        else: comeback_str = "無符合回春資格之球員"

                cx1, cx2, cx3 = st.columns(3)
                cx1.info(f"**🔥 年度東山再起獎**：\n{comeback_str}")
                cx2.info(f"**😢 年度悲情賽揚獎**：\n{tough_cy_str}")
                cx3.info(f"**🔒 天天牛棚鐵人獎**：\n{bullpen_king_str}")

    with t_all_mlb:
        st.subheader("🌟 歷屆年度最佳陣容第一隊 (All-MLB First Team)")
        all_mlb_counts = {}
        for s_idx in range(1, max_season + 1):
            if s_idx not in season_cache: continue
            with st.expander(f"📖 Season {s_idx} 最佳陣容", expanded=(s_idx == max_season)):
                rs_cand = season_cache[s_idx][10]
                is_rs_fin = season_cache[s_idx][12]
                t_games = df_p_clean[df_p_clean['賽事階段'].astype(str).str.contains(f"\\[S{s_idx}\\] 例行賽")].get('賽事階段', pd.Series()).nunique() or 10
                r_pa, r_ip = max(15.0, t_games * 1.5) if s_idx >= 6 else 15.0, max(5.0, t_games * 0.4) if s_idx >= 6 else 5.0
                st.markdown(f"<blockquote><b> All-MLB 評選標準宣告</b>：<br>野手達標門檻：<b>{r_pa:.1f} 打席</b> ｜ 投手達標門檻：<b>{r_ip:.1f} 局</b>。依據該季例行賽標準進階魔球公式之累積 eWAR 分數，跨隊進行頂峰對決，各守位僅取最強第一人入選。</blockquote>", unsafe_allow_html=True)
                
                first_team = {p: "無 (達標數據不足)" for p in ['C','1B','2B','3B','SS','OF','DH','SP','RP']}
                if rs_cand:
                    batters = {k: v for k, v in rs_cand.items() if v['類型'] in ['打者', '二刀流']}
                    pitchers = {k: v for k, v in rs_cand.items() if v['類型'] in ['投手', '二刀流']}
                    sel_p = set()
                    
                    def pick_best(pos_list, is_dh=False):
                        cands = {k: v for k, v in batters.items() if (is_dh or v.get('Pos') in pos_list) and k not in sel_p and v.get('Qual', False)}
                        pos_cands = {k: v for k, v in cands.items() if v['eWAR'] > 0}
                        if pos_cands:
                            best = max(pos_cands.items(), key=lambda x: x[1]['eWAR'])[0]
                            sel_p.add(best)
                            if is_rs_fin:
                                all_mlb_counts[best] = all_mlb_counts.get(best, 0) + 1
                                cnt = all_mlb_counts[best]
                                return f"{best} (eWAR {pos_cands[best]['eWAR']:.1f}){f' ★第{cnt}次' if cnt > 1 else ''}"
                            return f"{best} (eWAR {pos_cands[best]['eWAR']:.1f}) (領跑中)"
                        return "無符合常規資格者"
                        
                    first_team['C'] = pick_best(['C'])
                    first_team['1B'] = pick_best(['1B'])
                    first_team['2B'] = pick_best(['2B'])
                    first_team['3B'] = pick_best(['3B'])
                    first_team['SS'] = pick_best(['SS'])
                    
                    of_cands = {k: v for k, v in batters.items() if v.get('Pos') in ['LF','CF','RF','OF'] and k not in sel_p and v.get('Qual', False) and v['eWAR'] > 0}
                    if of_cands:
                        top_ofs = sorted(of_cands.items(), key=lambda x: x[1]['eWAR'], reverse=True)[:3]
                        of_strs = []
                        for x in top_ofs:
                            sel_p.add(x[0])
                            if is_rs_fin:
                                all_mlb_counts[x[0]] = all_mlb_counts.get(x[0], 0) + 1
                                cnt = all_mlb_counts[x[0]]
                                of_strs.append(f"{x[0]} (eWAR {x[1]['eWAR']:.1f}){f' ★第{cnt}次' if cnt > 1 else ''}")
                            else: of_strs.append(f"{x[0]} (eWAR {x[1]['eWAR']:.1f}) (領跑中)")
                        first_team['OF'] = "  \n".join(of_strs)
                        
                    first_team['DH'] = pick_best([], is_dh=True)
                    
                    if pitchers:
                        sp_cands = {k: v for k, v in pitchers.items() if v.get('Qual', False) and v['eWAR'] > 0}
                        if sp_cands: 
                            b_sp = max(sp_cands.items(), key=lambda x: x[1]['eWAR'])[0]
                            if is_rs_fin:
                                all_mlb_counts[b_sp] = all_mlb_counts.get(b_sp, 0) + 1
                                cnt = all_mlb_counts[b_sp]
                                first_team['SP'] = f"{b_sp} (eWAR {sp_cands[b_sp]['eWAR']:.1f}, {sp_cands[b_sp]['ERA']:.2f} ERA){f' ★第{cnt}次' if cnt > 1 else ''}"
                            else: first_team['SP'] = f"{b_sp} (eWAR {sp_cands[b_sp]['eWAR']:.1f}) (領跑中)"
                            
                        rp_cands = {k: v for k, v in pitchers.items() if (v.get('SV',0)>0 or v.get('HLD',0)>0) and v['eWAR'] > 0}
                        if rp_cands: 
                            b_rp = max(rp_cands.items(), key=lambda x: x[1]['eWAR'])[0]
                            if is_rs_fin:
                                all_mlb_counts[b_rp] = all_mlb_counts.get(b_rp, 0) + 1
                                cnt = all_mlb_counts[b_rp]
                                first_team['RP'] = f"{b_rp} (eWAR {rp_cands[b_rp]['eWAR']:.1f}, {int(rp_cands[b_rp]['SV'])} SV){f' ★第{cnt}次' if cnt > 1 else ''}"
                            else: first_team['RP'] = f"{b_rp} (eWAR {rp_cands[b_rp]['eWAR']:.1f}) (領跑中)"
                
                tc1, tc2, tc3 = st.columns(3)
                tc1.markdown(f"**⚾ 先發投手 (SP)**：\n{first_team.get('SP', '無')}\n\n**🔒 後援投手 (RP)**：\n{first_team.get('RP', '無')}\n\n**🎯 捕手 (C)**：\n{first_team.get('C', '無')}")
                tc2.markdown(f"**🧱 一壘手 (1B)**：\n{first_team.get('1B', '無')}\n\n**⚡ 二壘手 (2B)**：\n{first_team.get('2B', '無')}\n\n**🔥 三壘手 (3B)**：\n{first_team.get('3B', '無')}\n\n**✨ 游擊手 (SS)**：\n{first_team.get('SS', '無')}")
                tc3.markdown(f"**🦅 外野手 (OF)**：\n{first_team.get('OF', '無')}\n\n**☄️ 指定打擊 (DH)**：\n{first_team.get('DH', '無')}")

    with t_game_mvps:
        st.subheader("🏅 歷場單場 MVP 榮譽榜與投打走勢")
        all_time_mvps = {}
        season_mvps_data = {}
        curr_p_mvp_cnt, curr_b_mvp_cnt = 0, 0
        
        for s_idx in range(1, max_season + 1):
            s_pref = f"[S{s_idx}]"
            b_s = df_b_clean[df_b_clean['賽事階段'].astype(str).str.contains(s_pref, regex=False)] if not df_b_clean.empty else pd.DataFrame()
            p_s = df_p_clean[df_p_clean['賽事階段'].astype(str).str.contains(s_pref, regex=False)] if not df_p_clean.empty else pd.DataFrame()
            if b_s.empty and p_s.empty: continue
            
            stages = set(b_s['賽事階段'].unique()) | set(p_s['賽事階段'].unique())
            sorted_stages = sorted(list(stages), key=lambda x: (1 if '世界大賽' in str(x) else 0, int(re.search(r'G(\d+)|第(\d+)場', str(x)).group(1) or re.search(r'G(\d+)|第(\d+)場', str(x)).group(2)) if re.search(r'G(\d+)|第(\d+)場', str(x)) else 0))
            season_results = []
            season_counts = {}
            
            for stage in sorted_stages:
                g_b = b_s[b_s['賽事階段'] == stage]
                g_p = p_s[p_s['賽事階段'] == stage]
                w_team = None
                if not g_p.empty:
                    w_rows = g_p[g_p['勝'] == 1]
                    if not w_rows.empty: w_team = w_rows.iloc[0]['球隊']
                
                cands = []
                if not g_b.empty:
                    for _, r in g_b.iterrows():
                        if w_team and r['球隊'] != w_team: continue
                        vals = [r.get(col, 0) for col in ['打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振']]
                        # ✨ 統一呼叫全域的大聯盟單場 MVP 引擎
                        score = global_game_mvp_score_b(vals[0], vals[1], vals[2], vals[3], vals[4], vals[5], vals[6], vals[7], vals[8], s_idx)
                        cands.append({'name': f"[{r['球隊']}] {r['球員姓名']}", 'score': score, 'type': 'Batter', 'raw_rbi': vals[5]})
                if not g_p.empty:
                    for _, r in g_p.iterrows():
                        if w_team and r['球隊'] != w_team: continue
                        outs = r.get('局數(整數)', 0)*3 + r.get('局數(出局數)', 0)
                        p_v = [r.get(c, 0) for c in ['自責分', '被安打', '四壞球', '奪三振']]
                        w_f, sv_f, hld_f = r.get('勝', 0), r.get('救援', 0), r.get('中繼', 0)
                        # ✨ 統一呼叫全域的大聯盟單場 MVP 引擎
                        score = global_game_mvp_score_p(outs/3.0, p_v[0], p_v[1], p_v[2], p_v[3], w_f, sv_f, hld_f, s_idx)
                        cands.append({'name': f"[{r['球隊']}] {r['投手姓名']}", 'score': score, 'type': 'Pitcher', 'raw_rbi': 0})
                
                if cands:
                    cands.sort(key=lambda x: (x['score'], x['raw_rbi']), reverse=True)
                    mvp_cand = cands[0]
                    winner_name = mvp_cand['name']
                    season_counts[winner_name] = season_counts.get(winner_name, 0) + 1
                    all_time_mvps[winner_name] = all_time_mvps.get(winner_name, 0) + 1
                    
                    if s_idx == max_season:
                        if mvp_cand['type'] == 'Pitcher': curr_p_mvp_cnt += 1
                        else: curr_b_mvp_cnt += 1
                        
                    season_results.append({'賽事階段': str(stage).strip(), 'MVP 球員': winner_name, '本季累積': f"{season_counts[winner_name]} 次"})
            if season_results: season_mvps_data[s_idx] = pd.DataFrame(season_results)

        top_5_mvps = sorted(all_time_mvps.items(), key=lambda x: x[1], reverse=True)[:5]
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        cols = st.columns(5)
        for i, (name, count) in enumerate(top_5_mvps): cols[i].metric(f"{medals[i]} {name}", f"{count} 次")
            
        st.divider()
        st.markdown("#### 📊 投打戰力失衡觀測窗")
        if curr_p_mvp_cnt + curr_b_mvp_cnt > 0:
            p_pct = (curr_p_mvp_cnt / (curr_p_mvp_cnt + curr_b_mvp_cnt)) * 100
            st.info(f"💡 **轉播台特別通報**：本賽季（Season {max_season}）目前共產生 **{curr_p_mvp_cnt + curr_b_mvp_cnt}** 場單場 MVP。其中投手獲獎 **{curr_p_mvp_cnt}次（佔 {p_pct:.1f}%）**，打者獲獎 **{curr_b_mvp_cnt}次**。數據證實：系統已為3局制進行投打權重特化校正，勝負掌控力目前完美分配！")
        else: st.caption("暫無本季數據。")

        for s_idx in reversed(range(1, max_season + 1)):
            if s_idx in season_mvps_data:
                with st.expander(f"📖 Season {s_idx} 歷場 MVP 明細", expanded=(s_idx == max_season)):
                    st.dataframe(season_mvps_data[s_idx], use_container_width=True, hide_index=True)

    with t_leaders:
        st.subheader("👑 歷史隊史紀錄與單季極限")
        st.markdown("#### 🏛️ 隊史累積神主牌 (Franchise All-Time Leaders)")
        
        team_meta_summary = {}
        for team in ['LAA', 'LAD']:
            t_p_raw = df_p_clean[df_p_clean['球隊'] == team] if not df_p_clean.empty else pd.DataFrame()
            t_b_raw = df_b_clean[df_b_clean['球隊'] == team] if not df_b_clean.empty else pd.DataFrame()
            tot_hits = t_b_raw['安打'].sum() if not t_b_raw.empty else 0
            tot_hr = t_b_raw['全壘打'].sum() if not t_b_raw.empty else 0
            tot_rbi = t_b_raw['打點'].sum() if not t_b_raw.empty else 0
            tot_so = t_p_raw['奪三振'].sum() if not t_p_raw.empty else 0
            
            h_w, h_l, h_d, a_w, a_l, a_d, oner_w, oner_l = 0, 0, 0, 0, 0, 0, 0, 0
            if not df_p_clean.empty:
                for stage, group in df_p_clean.groupby('賽事階段'):
                    g_team = group[group['球隊'] == team]
                    if g_team.empty: continue
                    is_w = g_team['勝'].sum() > 0
                    is_l = g_team['敗'].sum() > 0
                    is_d = len(g_team) > 0 and not is_w and not is_l
                    
                    laa_ra = group[group['球隊']=='LAA']['失分'].sum()
                    lad_ra = group[group['球隊']=='LAD']['失分'].sum()
                    if abs(laa_ra - lad_ra) == 1:
                        if is_w: oner_w += 1
                        elif is_l: oner_l += 1
                        
                    h_team = get_home_team_tab5(str(stage))
                    if team == h_team:
                        if is_w: h_w += 1
                        elif is_l: h_l += 1
                        else: h_d += 1
                    elif h_team != "Unknown":
                        if is_w: a_w += 1
                        elif is_l: a_l += 1
                        else: a_d += 1
            
            team_meta_summary[team] = {
                'hits': int(tot_hits), 'hr': int(tot_hr), 'rbi': int(tot_rbi), 'so': int(tot_so),
                'home_rec': f"{h_w}勝 {h_l}敗 {h_d}和", 'away_rec': f"{a_w}勝 {a_l}敗 {a_d}和", 'one_run': f"{oner_w}勝 {oner_l}敗"
            }

        c_laa, c_lad = st.columns(2)
        for team, col_obj in [("LAA", c_laa), ("LAD", c_lad)]:
            with col_obj:
                st.markdown(f"#### {'🔴' if team=='LAA' else '🔵'} {team} 隊史神主牌")
                if team in team_meta_summary:
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
                def get_top3_str(df, sort_col, name_col):
                    if df.empty or sort_col not in df.columns: return "無"
                    top3 = df.sort_values(by=sort_col, ascending=False).head(3)
                    res = [f"{i+1}. {r[name_col]} ({int(r[sort_col])})" for i, (_, r) in enumerate(top3.iterrows()) if r[sort_col] > 0]
                    return "  \n".join(res) if res else "無"

                st.caption(f"**🏏 安打王**：\n{get_top3_str(b_saber[b_saber['球隊']==team], '安打', '球員姓名')}")
                st.caption(f"**🚀 全壘打王**：\n{get_top3_str(b_saber[b_saber['球隊']==team], '全壘打', '球員姓名')}")
                st.caption(f"**🔥 打點王**：\n{get_top3_str(b_saber[b_saber['球隊']==team], '打點', '球員姓名')}")
                if not p_saber.empty:
                    tp = p_saber[p_saber['球隊']==team]
                    st.caption(f"**⚾ 勝投王**：\n{get_top3_str(tp, '勝', '投手姓名')}")
                    st.caption(f"**🌪️ 三振王**：\n{get_top3_str(tp, '奪三振', '投手姓名')}")
                    st.caption(f"**🔒 救援王**：\n{get_top3_str(tp, '救援', '投手姓名')}")
        st.divider()

        # ✨【歷史單一賽季極限 WAR】完全獨立精算，確保無懈可擊
        all_season_war_records = []
        team_season_b_dict, team_season_p_dict = {}, {} 
        
        for s in range(1, max_season + 1):
            s_pref = f"[S{s}] 例行賽"
            s_b = df_b_clean[df_b_clean['賽事階段'].astype(str).str.contains(s_pref, regex=False)].copy()
            s_p = df_p_clean[df_p_clean['賽事階段'].astype(str).str.contains(s_pref, regex=False)].copy()
            
            if s_b.empty and s_p.empty: continue
            
            lg_woba = 0.320
            if not s_b.empty:
                t_pa = s_b['打席'].sum()
                t_1b = s_b['安打'].sum() - s_b['二壘安打'].sum() - s_b['三壘安打'].sum() - s_b['全壘打'].sum()
                if t_pa > 0:
                    lg_woba = (0.69*s_b['四壞球'].sum() + 0.88*t_1b + 1.25*s_b['二壘安打'].sum() + 1.59*s_b['三壘安打'].sum() + 2.06*s_b['全壘打'].sum()) / t_pa
                    
                for tm in ['LAA', 'LAD']:
                    tm_b = s_b[s_b['球隊'] == tm]
                    if not tm_b.empty:
                        team_season_b_dict[f"[{tm}] [S{s}]"] = {
                            'H': tm_b['安打'].sum(), 'HR': tm_b['全壘打'].sum(), 
                            'RBI': tm_b['打點'].sum(), 'AB': tm_b['打數'].sum()
                        }
            
            lg_era_base = 10.60
            if not s_p.empty:
                l_ip = (s_p['局數(整數)'].sum()*3 + s_p['局數(出局數)'].sum()) / 3.0
                if l_ip > 0: lg_era_base = (s_p['自責分'].sum() * 9) / l_ip
                
                for tm in ['LAA', 'LAD']:
                    tm_p = s_p[s_p['球隊'] == tm]
                    if not tm_p.empty:
                        outs_tm = tm_p['局數(整數)'].sum()*3 + tm_p['局數(出局數)'].sum()
                        team_season_p_dict[f"[{tm}] [S{s}]"] = {
                            'W': tm_p['勝'].sum(), 'K': tm_p['奪三振'].sum(), 
                            'ER': tm_p['自責分'].sum(), 'IP': outs_tm / 3.0
                        }

            player_seas_war = {}
            player_type = {}
            pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
            
            if not s_b.empty:
                b_agg = s_b.groupby(['球隊', '球員姓名']).agg({'打席':'sum','安打':'sum','二壘安打':'sum','三壘安打':'sum','全壘打':'sum','四壞球':'sum','守位': lambda x: x.value_counts().index[0] if not x.empty else 'DH'}).reset_index()
                for _, r in b_agg.iterrows():
                    pa, h, h2, h3, hr, bb = r['打席'], r['安打'], r['二壘安打'], r['三壘安打'], r['全壘打'], r['四壞球']
                    if pa == 0: continue
                    p_1b = h - h2 - h3 - hr
                    woba = (0.69*bb + 0.88*p_1b + 1.25*h2 + 1.59*h3 + 2.06*hr) / pa
                    wrc_p = ((woba / lg_woba) - 1) * 200 + 100 if lg_woba > 0 else 0
                    ewar = (((wrc_p - 70) / 80) + pos_adj_dict.get(r.get('守位','DH'), -0.12)) * (pa / 15)
                    name_key = f"[{r['球隊']}] {r['球員姓名']}"
                    player_seas_war[name_key] = ewar
                    player_type[name_key] = '打者'
                    
            if not s_p.empty:
                p_agg = s_p.groupby(['球隊', '投手姓名']).agg({'局數(整數)':'sum','局數(出局數)':'sum','自責分':'sum','被全壘打':'sum','四壞球':'sum','奪三振':'sum'}).reset_index()
                for _, r in p_agg.iterrows():
                    outs = r['局數(整數)']*3 + r['局數(出局數)']
                    ip = outs/3.0
                    er, hr, bb, so = r['自責分'], r['被全壘打'], r['四壞球'], r['奪三振']
                    era = (er*9)/ip if ip>0 else 0.0
                    fip = (((13*hr)+(3*bb)-(2*so))/ip)+3.10 if ip>0 else 3.10
                    tra = (era * 0.3) + (fip * 0.7) if s >= 6 else (era + fip)/2.0
                    
                    s_rep_level = lg_era_base * 1.30
                    era_div = max(1.5, lg_era_base * 0.2)
                    
                    if ip == 0: ewar = (-0.1*er-0.05*bb)
                    else: ewar = ((s_rep_level - tra)/era_div)*(ip/10)
                    
                    name_key = f"[{r['球隊']}] {r['投手姓名']}"
                    player_seas_war[name_key] = player_seas_war.get(name_key, 0.0) + ewar
                    player_type[name_key] = '二刀流' if name_key in player_type else '投手'
                    
            for p_name, total_war in player_seas_war.items():
                all_season_war_records.append({'Season': f"[S{s}]", 'Name': p_name, 'eWAR': round(total_war, 1), 'Type': player_type[p_name]})

        st.markdown("#### 🥇 歷史單一賽季極限紀錄 (Single-Season Records)")
        if all_season_war_records:
            df_all_war = pd.DataFrame(all_season_war_records)
            c_war1, c_war2, c_war3, c_war4 = st.columns(4)
            with c_war1:
                st.markdown("**打者最高 WAR**")
                for _, r in df_all_war[df_all_war['Type'].isin(['打者', '二刀流'])].sort_values('eWAR', ascending=False).head(3).iterrows(): st.caption(f"🥇 {r['Name']} {r['Season']}: **{r['eWAR']:.1f}**")
            with c_war2:
                st.markdown("**投手最高 WAR**")
                for _, r in df_all_war[df_all_war['Type'].isin(['投手', '二刀流'])].sort_values('eWAR', ascending=False).head(3).iterrows(): st.caption(f"🥇 {r['Name']} {r['Season']}: **{r['eWAR']:.1f}**")
            with c_war3:
                st.markdown("**打者最低 WAR**")
                for _, r in df_all_war[df_all_war['Type'].isin(['打者', '二刀流'])].sort_values('eWAR', ascending=True).head(3).iterrows(): st.caption(f"💣 {r['Name']} {r['Season']}: **{r['eWAR']:.1f}**")
            with c_war4:
                st.markdown("**投手最低 WAR**")
                for _, r in df_all_war[df_all_war['Type'].isin(['投手', '二刀流'])].sort_values('eWAR', ascending=True).head(3).iterrows(): st.caption(f"🧨 {r['Name']} {r['Season']}: **{r['eWAR']:.1f}**")
        st.markdown("<br>", unsafe_allow_html=True)

        s_b_records, s_p_records = [], []
        for s in range(1, max_season + 1):
            pref = f"[S{s}] 例行賽"
            s_b = df_b_clean[df_b_clean['賽事階段'].astype(str).str.contains(pref, regex=False)].copy()
            s_p = df_p_clean[df_p_clean['賽事階段'].astype(str).str.contains(pref, regex=False)].copy()
            if not s_b.empty:
                min_pa = max(1.0, s_b['賽事階段'].nunique() * 1.0)
                for _, r in s_b.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index().iterrows():
                    s_b_records.append({'Season': f"[S{s}]", 'Name': f"[{r['球隊']}] {r['球員姓名']}", 'HR': r['全壘打'], 'RBI': r['打點'], 'H': r['安打'], 'AVG': r['安打']/max(1, r['打數']) if r['打席'] >= min_pa else 0})
            if not s_p.empty:
                min_ip = max(0.1, s_p['賽事階段'].nunique() * 0.25)
                p_agg = s_p.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index()
                for _, r in p_agg.iterrows():
                    ip = (r['局數(整數)']*3 + r['局數(出局數)'])/3.0
                    s_p_records.append({'Season': f"[S{s}]", 'Name': f"[{r['球隊']}] {r['投手姓名']}", 'W': r['勝'], 'SV': r['救援'], 'K': r['奪三振'], 'ERA': (r['自責分']*9)/ip if ip >= min_ip else 99.9})
                            
        c3, c4 = st.columns(2)
        with c3:
            st.caption("🏏 **個人打擊單季極限**")
            if s_b_records:
                df_s_b = pd.DataFrame(s_b_records)
                st.markdown(f"- **最多全壘打**：{int(df_s_b.loc[df_s_b['HR'].idxmax()]['HR'])} 轟 ({df_s_b.loc[df_s_b['HR'].idxmax()]['Name']} {df_s_b.loc[df_s_b['HR'].idxmax()]['Season']})")
                st.markdown(f"- **最多打點**：{int(df_s_b.loc[df_s_b['RBI'].idxmax()]['RBI'])} 分 ({df_s_b.loc[df_s_b['RBI'].idxmax()]['Name']} {df_s_b.loc[df_s_b['RBI'].idxmax()]['Season']})")
                st.markdown(f"- **最多安打**：{int(df_s_b.loc[df_s_b['H'].idxmax()]['H'])} 支 ({df_s_b.loc[df_s_b['H'].idxmax()]['Name']} {df_s_b.loc[df_s_b['H'].idxmax()]['Season']})")
                if df_s_b['AVG'].max() > 0: st.markdown(f"- **最高打擊率**：{df_s_b.loc[df_s_b['AVG'].idxmax()]['AVG']:.3f} ({df_s_b.loc[df_s_b['AVG'].idxmax()]['Name']} {df_s_b.loc[df_s_b['AVG'].idxmax()]['Season']})")
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("🔴🔵 **團隊打擊單季極限**")
            if team_season_b_dict:
                df_tm_b = pd.DataFrame.from_dict(team_season_b_dict, orient='index').reset_index()
                st.markdown(f"- **團隊單季最多轟**：{int(df_tm_b['HR'].max())} 轟 ({df_tm_b.loc[df_tm_b['HR'].idxmax()]['index']})")
                st.markdown(f"- **團隊單季最多打點**：{int(df_tm_b['RBI'].max())} 分 ({df_tm_b.loc[df_tm_b['RBI'].idxmax()]['index']})")
                st.markdown(f"- **團隊單季最高打擊率**：{(df_tm_b['H']/df_tm_b['AB']).max():.3f} ({df_tm_b.loc[(df_tm_b['H']/df_tm_b['AB']).idxmax()]['index']})")
        with c4:
            st.caption("⚾ **個人投球單季極限**")
            if s_p_records:
                df_s_p = pd.DataFrame(s_p_records)
                st.markdown(f"- **最多勝投**：{int(df_s_p.loc[df_s_p['W'].idxmax()]['W'])} 勝 ({df_s_p.loc[df_s_p['W'].idxmax()]['Name']} {df_s_p.loc[df_s_p['W'].idxmax()]['Season']})")
                st.markdown(f"- **最多三振**：{int(df_s_p.loc[df_s_p['K'].idxmax()]['K'])} 次 ({df_s_p.loc[df_s_p['K'].idxmax()]['Name']} {df_s_p.loc[df_s_p['K'].idxmax()]['Season']})")
                era_min = df_s_p[df_s_p['ERA'] < 99.9]
                if not era_min.empty: st.markdown(f"- **最低防禦率**：{era_min.loc[era_min['ERA'].idxmin()]['ERA']:.2f} ({era_min.loc[era_min['ERA'].idxmin()]['Name']} {era_min.loc[era_min['ERA'].idxmin()]['Season']})")
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("🔴🔵 **團隊投球單季極限**")
            if team_season_p_dict:
                df_tm_p = pd.DataFrame.from_dict(team_season_p_dict, orient='index').reset_index()
                st.markdown(f"- **團隊單季最多勝**：{int(df_tm_p['W'].max())} 勝 ({df_tm_p.loc[df_tm_p['W'].idxmax()]['index']})")
                st.markdown(f"- **團隊單季最多三振**：{int(df_tm_p['K'].max())} 次 ({df_tm_p.loc[df_tm_p['K'].idxmax()]['index']})")
                st.markdown(f"- **團隊單季最低防禦率**：{(df_tm_p['ER']*9/df_tm_p['IP']).min():.2f} ({df_tm_p.loc[(df_tm_p['ER']*9/df_tm_p['IP']).idxmin()]['index']})")

    with t_milestones:
        st.subheader("⏳ 偉大里程碑追蹤器 (Milestones Tracker)")
        pending_milestones = []
        def add_milestone(type_str, name, curr_val, targets):
            if curr_val <= 2: return 
            next_t = next((t for t in targets if curr_val < t), None)
            if next_t and (next_t - curr_val) <= 3: pending_milestones.append({'Type': type_str, 'Name': name, 'Curr': curr_val, 'Target': next_t, 'M': next_t - curr_val})

        for _, r in df_b_clean.groupby(['球隊', '球員姓名']).sum(numeric_only=True).reset_index().iterrows():
            name = f"[{r['球隊']}] {r['球員姓名']}"
            add_milestone('🏏 生涯安打', name, r['安打'], [15, 30, 50, 100, 150, 200])
            add_milestone('🚀 生涯全壘打', name, r['全壘打'], [5, 10, 20, 30, 50, 100])
            add_milestone('🔥 生涯打點', name, r['打點'], [10, 30, 50, 100, 150])
        
        if not df_p_clean.empty:
            for _, r in df_p_clean.groupby(['球隊', '投手姓名']).sum(numeric_only=True).reset_index().iterrows():
                name = f"[{r['球隊']}] {r['投手姓名']}"
                add_milestone('⚾ 生涯勝投', name, r['勝'], [5, 10, 20, 30, 50])
                add_milestone('🌪️ 生涯三振', name, r['奪三振'], [10, 30, 50, 100, 150])
                add_milestone('🔒 生涯救援', name, r['救援'], [5, 10, 20, 30])

        ms_df = pd.DataFrame(pending_milestones)
        if not ms_df.empty:
            categories = ['🏏 生涯安打', '🚀 生涯全壘打', '🔥 生涯打點', '⚾ 生涯勝投', '🌪️ 生涯三振', '🔒 生涯救援']
            c1, c2 = st.columns(2)
            cols = [c1, c2]
            col_idx = 0
            for cat in categories:
                cat_df = ms_df[ms_df['Type'] == cat]
                if not cat_df.empty:
                    with cols[col_idx % 2]:
                        st.markdown(f"#### {cat}")
                        for _, r in cat_df.sort_values('M').iterrows():
                            if r['M'] <= 1: st.warning(f"🔥 **{r['Name']}** 累積 {int(r['Curr'])} ➔ 目標 **{int(r['Target'])}** (M{int(r['M'])})")
                            else: st.info(f"⏳ **{r['Name']}** 累積 {int(r['Curr'])} ➔ 目標 **{int(r['Target'])}** (M{int(r['M'])})")
                    col_idx += 1
        else: st.success("目前全聯盟距離下一個里程碑都還有一段距離。")

    with t_streaks:
        st.subheader("💎 神聖與史詩連續紀錄 (Streaks Portal)")
        
        perfect_games, no_hitters, combined_pgs, combined_nohos = [], [], [], []
        if not df_p_clean.empty:
            for stage, g_stage in df_p_clean.groupby('賽事階段', sort=False):
                for team, g_team in g_stage.groupby('球隊', sort=False):
                    g_t = g_team.sort_values('時間戳記')
                    outs = g_t['局數(整數)'].sum()*3 + g_t['局數(出局數)'].sum()
                    if outs >= 9 and g_t['被安打'].sum() == 0:
                        p_list = []
                        for _, r in g_t.iterrows():
                            o = r['局數(整數)']*3 + r['局數(出局數)']
                            if o > 0: p_list.append(f"{r['投手姓名']} ({int(o//3)}.{int(o%3)}局)")
                        if not p_list: continue
                        
                        rec_str = f"**[{team}]** {' ➔ '.join(p_list)} *(於 {str(stage).strip()} 達成)*"
                        tot_bb, tot_runs = g_t['四壞球'].sum(), g_t['失分'].sum()
                        if tot_bb == 0 and tot_runs == 0:
                            if len(g_t['投手姓名'].unique()) > 1: combined_pgs.append(rec_str)
                            else: perfect_games.append(rec_str)
                        else:
                            if len(g_t['投手姓名'].unique()) > 1: combined_nohos.append(rec_str)
                            else: no_hitters.append(rec_str)

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
        
        def display_streak_clean(title, df, streak_type, loc_filter=None, unit="場"):
            if df.empty: return
            records = []
            
            latest_stg = {}
            if streak_type in ['win', 'loss', 'team_hr', 'team_hrless'] and '球隊' in df.columns:
                for t in df['球隊'].unique():
                    t_df = df[df['球隊'] == t]
                    if not t_df.empty: latest_stg[t] = t_df.sort_values('時間戳記').iloc[-1]['賽事階段']
            elif streak_type in ['hit', 'hr', 'hitless', 'hrless'] and '球員姓名' in df.columns:
                for n in df['球員姓名'].unique():
                    p_df = df[df['球員姓名'] == n]
                    if not p_df.empty: latest_stg[n] = p_df.sort_values('時間戳記').iloc[-1]['賽事階段']
            elif streak_type.startswith('zero_run') and '投手姓名' in df.columns:
                for n in df['投手姓名'].unique():
                    p_df = df[df['投手姓名'] == n]
                    if not p_df.empty: latest_stg[n] = p_df.sort_values('時間戳記').iloc[-1]['賽事階段']

            if streak_type in ['win', 'loss', 'team_hr', 'team_hrless']:
                for (team, stage), g in df.groupby(['球隊', '賽事階段'], sort=False):
                    ts = g['時間戳記'].min()
                    if streak_type == 'win': cond = g['勝'].sum() > 0
                    elif streak_type == 'loss': cond = g['敗'].sum() > 0
                    elif streak_type == 'team_hr': cond = g['全壘打'].sum() > 0 if '全壘打' in g.columns else False
                    elif streak_type == 'team_hrless': cond = g['全壘打'].sum() == 0 if '全壘打' in g.columns else True
                    records.append({'keys': team, 'stage': stage, 'ts': ts, 'cond': cond})
            elif streak_type in ['hit', 'hr', 'hitless', 'hrless']:
                for (team, name, stage), g in df.groupby(['球隊', '球員姓名', '賽事階段'], sort=False):
                    ts = g['時間戳記'].min()
                    hit_v = g['安打'].sum()
                    hr_v = g['全壘打'].sum()
                    pa_v = g['打席'].sum()
                    if streak_type == 'hit': cond = hit_v > 0
                    elif streak_type == 'hr': cond = hr_v > 0
                    elif streak_type == 'hitless': cond = (pa_v > 0 and hit_v == 0)
                    elif streak_type == 'hrless': cond = (pa_v > 0 and hr_v == 0)
                    records.append({'keys': (team, name), 'stage': stage, 'ts': ts, 'cond': cond})
            elif streak_type.startswith('zero_run'):
                for (team, stage), g_stage in df.groupby(['球隊', '賽事階段'], sort=False):
                    g_stage = g_stage.sort_values('時間戳記')
                    for i, (_, r) in enumerate(g_stage.iterrows()):
                        is_sp = (i == 0)
                        if streak_type == 'zero_run_sp' and not is_sp: continue
                        if streak_type == 'zero_run_rp' and is_sp: continue
                        ts = r.get('時間戳記', 0)
                        name = r.get('投手姓名', '')
                        r_runs = r.get('失分', 0)
                        ip_out = r.get('局數(整數)', 0) * 3 + r.get('局數(出局數)', 0)
                        cond = (r_runs == 0 and ip_out > 0)
                        records.append({'keys': (team, name), 'stage': stage, 'ts': ts, 'cond': cond})
                        
            seq_df = pd.DataFrame(records).sort_values('ts') if records else pd.DataFrame()
            if loc_filter and not seq_df.empty:
                filtered = []
                for _, r in seq_df.iterrows():
                    team_k = r['keys'][0] if isinstance(r['keys'], tuple) else r['keys']
                    hm_tm = get_home_team_tab5(str(r['stage']))
                    if loc_filter == 'home' and team_k == hm_tm: filtered.append(r)
                    elif loc_filter == 'away' and team_k != hm_tm and hm_tm != 'Unknown': filtered.append(r)
                seq_df = pd.DataFrame(filtered)
                
            all_streaks = []
            if not seq_df.empty:
                for k, group in seq_df.groupby('keys', sort=False):
                    curr_streak, st_stage, ed_stage = 0, "", ""
                    k_entity = k[1] if isinstance(k, tuple) else k
                    for _, r in group.iterrows():
                        if r['cond']:
                            if curr_streak == 0: st_stage = r['stage']
                            curr_streak += 1
                            ed_stage = r['stage']
                        else:
                            if curr_streak > 0: 
                                all_streaks.append({'keys': k, 'streak': curr_streak, 'start': st_stage, 'end': ed_stage, 'is_active': False})
                            curr_streak = 0
                    if curr_streak > 0: 
                        all_streaks.append({'keys': k, 'streak': curr_streak, 'start': st_stage, 'end': ed_stage, 'is_active': (ed_stage == latest_stg.get(k_entity))})

            def format_streak(s):
                stg1 = str(s['start']).strip()
                stg2 = str(s['end']).strip()
                span = f"({stg1} ~ {stg2})" if stg1 != stg2 else f"({stg1})"
                name_str = f"[{s['keys'][0]}] {s['keys'][1]}" if isinstance(s['keys'], tuple) else str(s['keys'])
                return f"{name_str} {span}"

            hist_top, act_top = [], []
            if all_streaks:
                max_all = max(s['streak'] for s in all_streaks)
                if max_all > 0:
                    hist_top = [{'val': max_all, 'holders': list(dict.fromkeys([format_streak(s) for s in all_streaks if s['streak'] == max_all]))}]
                
                active_streaks = [s for s in all_streaks if s['is_active']]
                if active_streaks:
                    max_act = max(s['streak'] for s in active_streaks)
                    if max_act > 0:
                        act_top = [{'val': max_act, 'holders': list(dict.fromkeys([format_streak(s) for s in active_streaks if s['streak'] == max_act]))}]

            st.markdown(f"##### {title}")
            c1, c2 = st.columns(2)
            with c1:
                if hist_top:
                    st.markdown(f"**🥇 歷史最高：{hist_top[0]['val']} {unit}**")
                    holders = hist_top[0]['holders']
                    for n in holders[:2]: st.caption(f" 📌 {n}")
                    if len(holders) > 2:
                        with st.expander(f"查看其餘 {len(holders)-2} 筆並列"):
                            for n in holders[2:]: st.caption(f" 📌 {n}")
                else: st.caption(" 📌 無紀錄")
            with c2:
                if act_top:
                    st.markdown(f"**🔥 目前持續中：{act_top[0]['val']} {unit}**")
                    holders = act_top[0]['holders']
                    for n in holders[:2]: st.caption(f" 📌 {n}")
                    if len(holders) > 2:
                        with st.expander(f"查看其餘 {len(holders)-2} 筆並列"):
                            for n in holders[2:]: st.caption(f" 📌 {n}")
                else: st.caption(" 📌 無持續中紀錄")
            st.markdown("<br>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("#### 🏁 團隊與勝敗連續紀錄")
            display_streak_clean("🔴🔵 聯盟最長連勝場次", df_p_clean, 'win')
            display_streak_clean("🏠 城堡壁壘：最長主場連勝", df_p_clean, 'win', 'home')
            display_streak_clean("✈️ 征服者：最長客場連勝", df_p_clean, 'win', 'away')
            display_streak_clean("🥶 冰封期：最長連續連敗", df_p_clean, 'loss')
            display_streak_clean("🚀 團隊連續場次全壘打", df_b_clean, 'team_hr')
            display_streak_clean("🏜️ 團隊連續場次無全壘打", df_b_clean, 'team_hrless')

        st.markdown("<br>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("#### 🚀 史詩火力與投手連續大榜")
            display_streak_clean("🏏 球員最長連續場次安打", df_b_clean, 'hit')
            display_streak_clean("🕳️ 球員最長連續無安打場次", df_b_clean, 'hitless')
            display_streak_clean("🚀 球員最長連續場次全壘打", df_b_clean, 'hr')
            display_streak_clean("⏳ 球員最長連續無全壘打場次", df_b_clean, 'hrless')
            display_streak_clean("🛡️ 先發投手連續出賽無失分", df_p_clean, 'zero_run_sp')
            display_streak_clean("🔒 牛棚後援連續出賽無失分", df_p_clean, 'zero_run_rp')

    with t_extremes:
        st.subheader("🤯 聯盟單場極端紀錄與進階大數據榜 (Extremes & Sabermetrics)")
        st.markdown("### ⚖️ 歷史運氣與進階數據極端榜")
        min_career_pa = max_season * 3.0
        min_career_ip = max_season * 1.0

        c_ext1, c_ext2 = st.columns(2)
        with c_ext1:
            st.markdown("#### 🎰 運氣天平與開轟里程碑")
            b_saber_qual = b_saber[b_saber['打席'] >= min_career_pa].copy()
            if not b_saber_qual.empty:
                b_saber_qual['BABIP'] = (b_saber_qual['安打'] - b_saber_qual['全壘打']) / (b_saber_qual['打數'] - b_saber_qual['三振'] - b_saber_qual['全壘打']).replace(0, 1)
                st.metric("🍀 天選之人 (生涯最高 BABIP)", f"{b_saber_qual['BABIP'].max():.3f}", f"[{b_saber_qual.loc[b_saber_qual['BABIP'].idxmax()]['球隊']}] {b_saber_qual.loc[b_saber_qual['BABIP'].idxmax()]['球員姓名']}")
                st.metric("🐈‍⬛ 地獄倒楣鬼 (生涯最低 BABIP)", f"{b_saber_qual['BABIP'].min():.3f}", f"[{b_saber_qual.loc[b_saber_qual['BABIP'].idxmin()]['球隊']}] {b_saber_qual.loc[b_saber_qual['BABIP'].idxmin()]['球員姓名']}")
                
                st.markdown("---")
                st.markdown("##### ⏳ 鐵血苦行僧 (生涯最難開轟 Top 3)")
                b_saber_qual['HR_Rate'] = b_saber_qual['全壘打'] / b_saber_qual['打席']
                kings = b_saber_qual.sort_values(by=['HR_Rate', '打席'], ascending=[True, False]).head(3)
                for i, (_, king) in enumerate(kings.iterrows()):
                    st.caption(f"{['🥇','🥈','🥉'][i]} [{king['球隊']}] {king['球員姓名']}：{int(king['打席'])} 打席 / {int(king['全壘打'])}轟")
                
                first_hr_records, longest_hr_intervals = [], []
                if not df_b_clean.empty:
                    df_b_sorted = df_b_clean.sort_values('時間戳記').copy()
                    for name, g_df in df_b_sorted.groupby(['球隊', '球員姓名']):
                        cum_pa, has_hr, hr_positions = 0, False, []
                        p_team, p_name = name[0], name[1]
                        for _, row in g_df.iterrows():
                            pa_val = row.get('打席', 0)
                            if pa_val == 0: continue
                            cum_pa += pa_val
                            if row.get('全壘打', 0) > 0:
                                stg_str = str(row['賽事階段']).strip()
                                if not has_hr:
                                    first_hr_records.append({'player': f"[{p_team}] {p_name}", 'pa': cum_pa, 'stage': stg_str})
                                    has_hr = True
                                hr_positions.append({'pa': cum_pa, 'stage': stg_str})
                        if len(hr_positions) >= 2:
                            for idx in range(len(hr_positions)-1):
                                gap = hr_positions[idx+1]['pa'] - hr_positions[idx]['pa']
                                longest_hr_intervals.append({'player': f"[{p_team}] {p_name}", 'gap': gap, 'stg1': hr_positions[idx]['stage'], 'stg2': hr_positions[idx+1]['stage']})
                
                st.markdown("---")
                st.markdown("##### ⏱️ 生涯首轟所需打席極值 (最快/最慢)")
                if first_hr_records:
                    df_first = pd.DataFrame(first_hr_records)
                    st.caption("🚀 **最快開轟 Top 3**：")
                    for i, r in df_first.sort_values('pa', ascending=True).head(3).reset_index().iterrows(): st.caption(f" {i+1}. {r['player']}：僅歷經 **{int(r['pa'])}** 打席 (於 {r['stage']})")
                    st.caption("🐢 **最慢大智若愚開轟 Top 3**：")
                    for i, r in df_first.sort_values('pa', ascending=False).head(3).reset_index().iterrows(): st.caption(f" {i+1}. {r['player']}：熬了 **{int(r['pa'])}** 打席才首轟 (於 {r['stage']})")
                
                st.markdown("##### 🌋 兩轟之間相隔最久打席 Top 3")
                if longest_hr_intervals:
                    df_gap = pd.DataFrame(longest_hr_intervals).sort_values('gap', ascending=False).head(3)
                    for i, r in df_gap.reset_index().iterrows(): 
                        st.caption(f" {['🥇','🥈','🥉'][i]} {r['player']}：乾涸了 **{int(r['gap'])}** 打席")
                        st.caption(f"  └ (從 {r['stg1']} ➔ {r['stg2']})")
        with c_ext2:
            st.markdown("#### 🛡️ 真金不怕火煉 (投手丘數據與苦勞)")
            p_saber_qual = p_saber[p_saber['局數'] >= min_career_ip].copy()
            if not p_saber_qual.empty:
                p_saber_qual['ERA'] = (p_saber_qual['自責分'] * 9) / p_saber_qual['局數'].replace(0, 1)
                p_saber_qual['FIP'] = (((13*p_saber_qual['被全壘打'])+(3*p_saber_qual['四壞球'])-(2*p_saber_qual['奪三振']))/p_saber_qual['局數'].replace(0, 1)) + 3.10
                p_saber_qual['DIFF'] = p_saber_qual['FIP'] - p_saber_qual['ERA']
                real_deal = p_saber_qual.sort_values('DIFF', ascending=True).iloc[0]
                mirage = p_saber_qual.sort_values('DIFF', ascending=False).iloc[0]
                
                st.markdown(f"**💡 悲情實力派 (FIP < ERA)**: [{real_deal['球隊']}] **{real_deal['投手姓名']}**")
                st.caption(f"► FIP: **{real_deal['FIP']:.2f}** ｜ ERA: {real_deal['ERA']:.2f} (落差 {abs(real_deal['DIFF']):.2f})")
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown(f"**🎰 強運幻象 (ERA < FIP)**: [{mirage['球隊']}] **{mirage['投手姓名']}**")
                st.caption(f"► ERA: **{mirage['ERA']:.2f}** ｜ FIP: {mirage['FIP']:.2f} (落差 {abs(mirage['DIFF']):.2f})")

        st.divider()

        st.markdown("### 🎭 判若兩人 (Splits Extremes)")
        st.caption("主客場表現落差最大、以及例行賽與世界大賽表現落差最大的球員排行榜 (需雙邊皆達 10 打席 / 5 局投球)。")
        
        def calc_ops_loop(df_sub):
            pa = df_sub['打席'].sum()
            ab = df_sub['打數'].sum()
            h = df_sub['安打'].sum()
            h2 = df_sub['二壘安打'].sum()
            h3 = df_sub['三壘安打'].sum()
            hr = df_sub['全壘打'].sum()
            bb = df_sub['四壞球'].sum()
            h1 = h - h2 - h3 - hr
            obp = (h + bb) / pa if pa > 0 else 0
            slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
            return obp + slg

        def calc_era_loop(df_sub):
            outs = df_sub['局數(整數)'].sum()*3 + df_sub['局數(出局數)'].sum()
            ip = outs / 3.0
            er = df_sub['自責分'].sum()
            return (er * 9) / ip if ip > 0 else 0.0

        b_split = df_b_clean.copy()
        ha_diff_b, rw_diff_b = [], []
        if not b_split.empty:
            b_split['Loc'] = b_split.apply(lambda r: 'Home' if get_home_team_tab5(str(r['賽事階段'])) == r['球隊'] else 'Away', axis=1)
            b_split['Type'] = b_split['賽事階段'].astype(str).apply(lambda x: 'RS' if '例行賽' in x else ('WS' if '世界大賽' in x else 'Other'))
            for (team, name), g in b_split.groupby(['球隊', '球員姓名']):
                g_h, g_a = g[g['Loc'] == 'Home'], g[g['Loc'] == 'Away']
                pa_h, pa_a = g_h['打席'].sum(), g_a['打席'].sum()
                if pa_h >= 10 and pa_a >= 10:
                    ops_h, ops_a = calc_ops_loop(g_h), calc_ops_loop(g_a)
                    ha_diff_b.append({'Name': f"[{team}] {name}", 'Diff': abs(ops_h - ops_a), 'Home_OPS': ops_h, 'Away_OPS': ops_a})
                
                g_rs, g_ws = g[g['Type'] == 'RS'], g[g['Type'] == 'WS']
                pa_rs, pa_ws = g_rs['打席'].sum(), g_ws['打席'].sum()
                if pa_rs >= 10 and pa_ws >= 10:
                    ops_rs, ops_ws = calc_ops_loop(g_rs), calc_ops_loop(g_ws)
                    rw_diff_b.append({'Name': f"[{team}] {name}", 'Diff': abs(ops_rs - ops_ws), 'RS_OPS': ops_rs, 'WS_OPS': ops_ws})

        p_split = df_p_clean.copy()
        ha_diff_p, rw_diff_p = [], []
        if not p_split.empty:
            p_split['Loc'] = p_split.apply(lambda r: 'Home' if get_home_team_tab5(str(r['賽事階段'])) == r['球隊'] else 'Away', axis=1)
            p_split['Type'] = p_split['賽事階段'].astype(str).apply(lambda x: 'RS' if '例行賽' in x else ('WS' if '世界大賽' in x else 'Other'))
            for (team, name), g in p_split.groupby(['球隊', '投手姓名']):
                g_h, g_a = g[g['Loc'] == 'Home'], g[g['Loc'] == 'Away']
                ip_h = (g_h['局數(整數)'].sum()*3 + g_h['局數(出局數)'].sum())/3.0
                ip_a = (g_a['局數(整數)'].sum()*3 + g_a['局數(出局數)'].sum())/3.0
                if ip_h >= 5.0 and ip_a >= 5.0:
                    era_h, era_a = calc_era_loop(g_h), calc_era_loop(g_a)
                    ha_diff_p.append({'Name': f"[{team}] {name}", 'Diff': abs(era_h - era_a), 'Home_ERA': era_h, 'Away_ERA': era_a})

                g_rs, g_ws = g[g['Type'] == 'RS'], g[g['Type'] == 'WS']
                ip_rs = (g_rs['局數(整數)'].sum()*3 + g_rs['局數(出局數)'].sum())/3.0
                ip_ws = (g_ws['局數(整數)'].sum()*3 + g_ws['局數(出局數)'].sum())/3.0
                if ip_rs >= 5.0 and ip_ws >= 5.0:
                    era_rs, era_ws = calc_era_loop(g_rs), calc_era_loop(g_ws)
                    rw_diff_p.append({'Name': f"[{team}] {name}", 'Diff': abs(era_rs - era_ws), 'RS_ERA': era_rs, 'WS_ERA': era_ws})

        c_split1, c_split2 = st.columns(2)
        with c_split1:
            st.markdown("##### 🏏 打者：主客場 OPS 差異最大")
            if ha_diff_b:
                for i, x in enumerate(sorted(ha_diff_b, key=lambda x: x['Diff'], reverse=True)[:3]):
                    st.markdown(f"{['🥇','🥈','🥉'][i]} **{x['Name']}** \nDiff: **{x['Diff']:.3f}** (主 {x['Home_OPS']:.3f} / 客 {x['Away_OPS']:.3f})")
            else: st.caption("尚無符合門檻打者")
            st.markdown("##### 🏏 打者：季賽/大賽 OPS 差異最大")
            if rw_diff_b:
                for i, x in enumerate(sorted(rw_diff_b, key=lambda x: x['Diff'], reverse=True)[:3]):
                    st.markdown(f"{['🥇','🥈','🥉'][i]} **{x['Name']}** \nDiff: **{x['Diff']:.3f}** (例賽 {x['RS_OPS']:.3f} / WS {x['WS_OPS']:.3f})")
            else: st.caption("尚無符合門檻打者")

        with c_split2:
            st.markdown("##### ⚾ 投手：主客場 ERA 差異最大")
            if ha_diff_p:
                for i, x in enumerate(sorted(ha_diff_p, key=lambda x: x['Diff'], reverse=True)[:3]):
                    st.markdown(f"{['🥇','🥈','🥉'][i]} **{x['Name']}** \nDiff: **{x['Diff']:.2f}** (主 {x['Home_ERA']:.2f} / 客 {x['Away_ERA']:.2f})")
            else: st.caption("尚無符合門檻投手")
            st.markdown("##### ⚾ 投手：季賽/大賽 ERA 差異最大")
            if rw_diff_p:
                for i, x in enumerate(sorted(rw_diff_p, key=lambda x: x['Diff'], reverse=True)[:3]):
                    st.markdown(f"{['🥇','🥈','🥉'][i]} **{x['Name']}** \nDiff: **{x['Diff']:.2f}** (例賽 {x['RS_ERA']:.2f} / WS {x['WS_ERA']:.2f})")
            else: st.caption("尚無符合門檻投手")

        st.divider()

        st.markdown("### 🎢 個人單場 WAR 值暴衝與狂扣紀錄 (Game of a Lifetime)")
        game_war_records = []
        if not df_b_clean.empty:
            for _, r in df_b_clean.iterrows():
                pa = r['打席']
                if pa == 0: continue
                ab, h, h2, h3, hr, rbi, run, bb, so = [r[c] for c in ['打數', '安打', '二壘安打', '三壘安打', '全壘打', '打點', '得分', '四壞球', '三振']]
                wrc_p = (((0.69*bb + 0.88*(h-h2-h3-hr) + 1.25*h2 + 1.59*h3 + 2.06*hr) / pa) / 0.320 - 1) * 200 + 100
                pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
                e_war = (((wrc_p - 70) / 80) + pos_adj_dict.get(r.get('守位','DH'), -0.12)) * (pa / 15)
                game_war_records.append({'Type': 'Batter', 'Stage': str(r['賽事階段']).strip(), 'WAR': e_war, 'Name': f"[{r['球隊']}] {r['球員姓名']} ({int(ab)}-{int(h)})"})
        if not df_p_clean.empty:
            for _, r in df_p_clean.iterrows():
                outs = r['局數(整數)']*3 + r['局數(出局數)']
                if outs == 0: continue
                er, h_a, bb_a, k, hr_a = [r[c] for c in ['自責分', '被安打', '四壞球', '奪三振', '被全壘打']]
                tra = ((er*9/(outs/3.0)) + (((13*hr_a)+(3*bb_a)-(2*k))/(outs/3.0) + 3.10)) / 2.0
                e_war = ((10.60*1.30 - tra) / 2.12) * ((outs/3.0) / 10)
                game_war_records.append({'Type': 'Pitcher', 'Stage': str(r['賽事階段']).strip(), 'WAR': e_war, 'Name': f"[{r['球隊']}] {r['投手姓名']} ({int(outs//3)}.{int(outs%3)}局)"})
        
        if game_war_records:
            df_gwar = pd.DataFrame(game_war_records)
            cg1, cg2 = st.columns(2)
            with cg1:
                st.markdown("**🔥 封神之戰 (單場最高 WAR Top 3)**")
                for _, r in df_gwar.sort_values('WAR', ascending=False).head(3).iterrows(): st.caption(f" 🥇 {r['Name']}：**+{r['WAR']:.2f} WAR** ({r['Stage']})")
            with cg2:
                st.markdown("**🥶 毀滅性戰犯 (單場最低 WAR Top 3)**")
                for _, r in df_gwar.sort_values('WAR', ascending=True).head(3).iterrows(): st.caption(f" 💣 {r['Name']}：**{r['WAR']:.2f} WAR** ({r['Stage']})")

        st.divider()

        st.markdown("### 🤯 團隊與個人單場極端紀錄大整合 (全部呈現 Top 3 排行)")
        
        def display_extreme_top3(title, df, col, is_max=True, is_pitcher=False, unit="", icon="🥇"):
            if df.empty or col not in df.columns: return
            df_c = df.copy()
            name_col = '投手姓名' if is_pitcher else '球員姓名'
            
            unique_vals = sorted(df_c[col].unique(), reverse=is_max)[:3]
            st.markdown(f"##### {title}")
            
            medals = ["🥇", "🥈", "🥉"]
            for i, val in enumerate(unique_vals):
                if val == 0 and is_max: continue
                rows = df_c[df_c[col] == val]
                holders = list(dict.fromkeys([f"[{r['球隊']}] {r[name_col]} ({str(r['賽事階段']).strip()})" for _, r in rows.iterrows()]))
                st.markdown(f" **{medals[i]} 歷史值：{int(val)} {unit}**")
                for h in holders[:3]: st.caption(f"  📌 {h}")
                if len(holders) > 3: st.caption(f"  💬 *...及其餘 {len(holders)-3} 筆並列紀錄*")
            st.markdown("<br>", unsafe_allow_html=True)

        def display_team_extreme_top3(title, df, col, is_max=True, unit="", icon="🥇"):
            if df.empty or col not in df.columns: return
            df_c = df.copy()
            
            team_agg = df_c.groupby(['賽事階段', '球隊'])[col].sum().reset_index()
            unique_vals = sorted(team_agg[col].unique(), reverse=is_max)[:3]
            st.markdown(f"##### {title}")
            
            medals = ["🥇", "🥈", "🥉"]
            for i, val in enumerate(unique_vals):
                if val == 0 and is_max: continue
                rows = team_agg[team_agg[col] == val]
                holders = list(dict.fromkeys([f"[{r['球隊']}] ({str(r['賽事階段']).strip()})" for _, r in rows.iterrows()]))
                st.markdown(f" **{medals[i]} 歷史值：{int(val)} {unit}**")
                for h in holders[:3]: st.caption(f"  📌 {h}")
                if len(holders) > 3: st.caption(f"  💬 *...及其餘 {len(holders)-3} 筆並列紀錄*")
            st.markdown("<br>", unsafe_allow_html=True)

        diff_records_top3 = []
        if not df_p_clean.empty:
            for stage, group in df_p_clean.groupby('賽事階段'):
                laa_ra = group[group['球隊']=='LAA']['失分'].sum()
                lad_ra = group[group['球隊']=='LAD']['失分'].sum()
                diff = abs(laa_ra - lad_ra)
                if diff > 0:
                    w_t, l_t = ('LAA', 'LAD') if lad_ra > laa_ra else ('LAD', 'LAA')
                    diff_records_top3.append({'stage': str(stage).strip(), 'diff': diff, 'desc': f"[{w_t}] 狂勝 [{l_t}] ({int(max(laa_ra, lad_ra))}:{int(min(laa_ra, lad_ra))})"})
        st.markdown("##### 😱 血流成河 (團隊單場最大比分差) Top 3")
        if diff_records_top3:
            df_diff3 = pd.DataFrame(diff_records_top3)
            u_diffs = sorted(df_diff3['diff'].unique(), reverse=True)[:3]
            medals = ["🥇", "🥈", "🥉"]
            for i, val in enumerate(u_diffs):
                st.markdown(f" **{medals[i]} 歷史值：{int(val)} 分差**")
                for _, r in df_diff3[df_diff3['diff'] == val].head(3).iterrows(): st.caption(f"  📌 {r['desc']} ({r['stage']})")
        else: st.caption(" 📌 暫無紀錄")
        st.markdown("<br>", unsafe_allow_html=True)

        team_runs_top3 = []
        if not df_p_clean.empty:
            for stage, group in df_p_clean.groupby('賽事階段'):
                laa_runs = group[group['球隊']=='LAD']['失分'].sum()
                lad_runs = group[group['球隊']=='LAA']['失分'].sum()
                stg_cleaned = str(stage).strip()
                if laa_runs > 0: team_runs_top3.append({'team': 'LAA', 'stage': stg_cleaned, 'runs': laa_runs})
                if lad_runs > 0: team_runs_top3.append({'team': 'LAD', 'stage': stg_cleaned, 'runs': lad_runs})
        st.markdown("##### 🔥 煙火大會 (團隊單場最多得分) Top 3")
        if team_runs_top3:
            df_runs3 = pd.DataFrame(team_runs_top3)
            u_runs = sorted(df_runs3['runs'].unique(), reverse=True)[:3]
            medals = ["🥇", "🥈", "🥉"]
            for i, val in enumerate(u_runs):
                st.markdown(f" **{medals[i]} 歷史值：{int(val)} 分**")
                for _, r in df_runs3[df_runs3['runs'] == val].head(3).iterrows(): st.caption(f"  📌 [{r['team']}] ({r['stage']})")
        else: st.caption(" 📌 暫無紀錄")
        st.markdown("<br>", unsafe_allow_html=True)

        display_team_extreme_top3("🏏 機槍打線 (球隊單場最多安打) Top 3", df_b_clean, '安打', True, "支")
        display_team_extreme_top3("🚀 轟炸大隊 (球隊單場最多全壘打) Top 3", df_b_clean, '全壘打', True, "轟")
        display_extreme_top3("💪 燃燒手臂 (單一投手單場最多用球數) Top 3", df_p_clean, '投球數', True, True, "球")
        display_team_extreme_top3("🥎 團隊血汗日 (團隊單場最多用球數) Top 3", df_p_clean, '投球數', True, "球")
        display_extreme_top3("🌪️ 電風扇之王 (打者單場最多被三振) Top 3", df_b_clean, '三振', True, False, "次")
        display_extreme_top3("🧨 發球機核爆 (投手單場最多失分) Top 3", df_p_clean, '失分', True, True, "分")
        
        display_extreme_top3("🎩 黃金老帽 (單場至少3打數且0安打) Top 3", df_b_clean[(df_b_clean['安打'] == 0) & (df_b_clean['打數'] >= 3)], '打數', True, False, "打數")
        display_extreme_top3("🏃‍♂️ 白做工 (單場至少2安打卻0打點) Top 3", df_b_clean[(df_b_clean['打點'] == 0) & (df_b_clean['安打'] >= 2)], '安打', True, False, "支")
# ==========================================
# --- 分頁 6：🆚 球員終極 PK 台 (Stathead Comparison) ---
# ==========================================
with tab6:
    st.header("🆚 球員終極 PK 台 (Head-to-Head Comparison)")
    st.caption("復刻 Baseball-Reference 經典比較工具：比對生涯或單季數據，系統將自動高光優勢方，並彙整所有跨隊得獎紀錄！")

    df_b = st.session_state.get('df_b_raw', pd.DataFrame())
    df_p = st.session_state.get('df_p_raw', pd.DataFrame())
    df_p_full = df_p.copy() # 用於算冠軍等全域判斷

    if df_b.empty and df_p.empty:
        st.warning("⚠️ 目前無數據可供比較。")
    else:
        # 1. 模式選擇 (打者/投手、賽事階段、生涯/單季)
        c_mode1, c_mode2, c_mode3 = st.columns([1.5, 1.5, 2])
        with c_mode1:
            pk_type = st.radio("⚾ 比較類型", ["🏏 打者 (Batters)", "🥎 投手 (Pitchers)"], horizontal=True)
            is_pk_batter = "打者" in pk_type
        with c_mode2:
            pk_stage = st.radio("⚾ 賽事類型", ["例行賽 (Regular Season)", "不限 (All)"], horizontal=True)
            stage_prefix = "例行賽" if "例行賽" in pk_stage else ""
        with c_mode3:
            season_options = ["十年總成績 (Career)"] + SEASONS
            pk_season = st.selectbox("📅 選擇比較時間區間", season_options)

        # 2. 篩選對應時間段的數據庫
        season_prefix = "" if "十年總成績" in pk_season else f"[S{pk_season.split(' ')[1]}]"
        
        # 建立基準資料庫 (先套用賽事階段過濾)
        if is_pk_batter:
            base_df = df_b[df_b['賽事階段'].astype(str).str.contains(stage_prefix, regex=False)] if stage_prefix else df_b.copy()
            name_col = '球員姓名'
        else:
            base_df = df_p[df_p['賽事階段'].astype(str).str.contains(stage_prefix, regex=False)] if stage_prefix else df_p.copy()
            name_col = '投手姓名'

        # 套用賽季過濾
        if season_prefix:
            pk_df = base_df[base_df['賽事階段'].astype(str).str.contains(season_prefix, regex=False)].copy()
        else:
            pk_df = base_df.copy()

        if pk_df.empty:
            st.info("該條件下尚無數據可供比較。")
        else:
            # ✨ 跨隊整合：只取球員姓名，動態組裝效力球隊
            all_team_map = pk_df.sort_values('時間戳記').groupby(name_col)['球隊'].unique().apply(lambda x: "/".join(x))
            
            all_players = []
            for p in pk_df[name_col].dropna().unique():
                tms = all_team_map.get(p, "Unknown")
                all_players.append(f"[{tms}] {p}")
            all_players = sorted(all_players)
            
            if 'pk_p1_memory' not in st.session_state: st.session_state['pk_p1_memory'] = None
            if 'pk_p2_memory' not in st.session_state: st.session_state['pk_p2_memory'] = None
            
            prev_p1 = st.session_state['pk_p1_memory']
            prev_p2 = st.session_state['pk_p2_memory']
            
            idx1 = all_players.index(prev_p1) if prev_p1 in all_players else 0
            idx2 = all_players.index(prev_p2) if prev_p2 in all_players else min(1, len(all_players)-1)
            
            def update_pk_players():
                st.session_state['pk_p1_memory'] = st.session_state['pk_p1_sel']
                st.session_state['pk_p2_memory'] = st.session_state['pk_p2_sel']
            
            st.markdown("---")
            c_p1, c_vs, c_p2 = st.columns([2, 0.5, 2])
            with c_p1:
                p1_sel = st.selectbox("選擇球員 A (Player A)", all_players, index=idx1, key='pk_p1_sel', on_change=update_pk_players)
            with c_vs:
                st.markdown("<h2 style='text-align:center; color:gray; margin-top:20px;'>VS</h2>", unsafe_allow_html=True)
            with c_p2:
                p2_sel = st.selectbox("選擇球員 B (Player B)", all_players, index=idx2, key='pk_p2_sel', on_change=update_pk_players)
                
            if st.session_state['pk_p1_memory'] is None: st.session_state['pk_p1_memory'] = p1_sel
            if st.session_state['pk_p2_memory'] is None: st.session_state['pk_p2_memory'] = p2_sel

            # 4. 數據運算引擎
            def get_pk_stats(full_name, is_batter):
                if not full_name: return None
                name = full_name.split('] ')[1]
                
                sub_df = pk_df[pk_df[name_col] == name].copy()
                if sub_df.empty: return None

                import re
                sub_df['Season'] = sub_df['賽事階段'].astype(str).apply(lambda x: re.search(r'\[S(\d+)\]', x).group(1) if re.search(r'\[S(\d+)\]', x) else '1')
                display_name = full_name

                # ✨ 掃描 Awards & Honors (精準版：修正 Regex 破圖，徹底恢復大獎)
                awards = {'Championships': 0, 'MVP': 0, 'Silver Slugg': 0, 'Cy Young': 0, '1st Team': 0, 'FMVP': 0, 'Game MVP': 0}
                if 'season_cache' in globals() or 'season_cache' in locals():
                    s_keys = [int(pk_season.split(' ')[1])] if season_prefix else list(season_cache.keys())
                    for s_k in s_keys:
                        if s_k in season_cache:
                            mvp, mvp_df, cy, cy_df, ss, ss_df, roty, roty_df, fmvp, fmvp_df, rs_cand, all_mlb, is_rs_fin, is_ws_fin = season_cache[s_k]
                            
                            played_this_season = False
                            if is_batter:
                                s_sub_b = df_b[(df_b['球員姓名']==name) & (df_b['賽事階段'].astype(str).str.contains(f"[S{s_k}]", regex=False))]
                                if not s_sub_b.empty: played_this_season = True
                            else:
                                s_sub_p = df_p[(df_p['投手姓名']==name) & (df_p['賽事階段'].astype(str).str.contains(f"[S{s_k}]", regex=False))]
                                if not s_sub_p.empty: played_this_season = True
                                
                            if played_this_season:
                                if is_rs_fin:
                                    if not mvp_df.empty and name in str(mvp_df.iloc[0]['球員']): awards['MVP'] += 1
                                    if not cy_df.empty and name in str(cy_df.iloc[0]['球員']): awards['Cy Young'] += 1
                                    if not ss_df.empty and name in str(ss_df.iloc[0]['球員']): awards['Silver Slugg'] += 1
                                    for mlb_p in all_mlb:
                                        if name in str(mlb_p): awards['1st Team'] += 1

                            if is_ws_fin:
                                if not fmvp_df.empty and name in str(fmvp_df.iloc[0]['球員']): awards['FMVP'] += 1
                                
                                ws_df = df_p_full[df_p_full['賽事階段'].astype(str).str.contains(f"[S{s_k}] 世界大賽", regex=False)]
                                if not ws_df.empty:
                                    laa_w, lad_w = 0, 0
                                    for stg, grp in ws_df.groupby('賽事階段', sort=False):
                                        if any('勝' in str(x) for x in grp[grp['球隊']=='LAA']['勝敗'].values): laa_w += 1
                                        if any('勝' in str(x) for x in grp[grp['球隊']=='LAD']['勝敗'].values): lad_w += 1
                                    ws_winner = "LAA" if laa_w >= 4 else "LAD" if lad_w >= 4 else None
                                    
                                    if ws_winner:
                                        played_ws_winner = False
                                        if is_batter:
                                            s_sub_ws = df_b[(df_b['球員姓名']==name) & (df_b['賽事階段'].astype(str).str.contains(f"[S{s_k}]", regex=False))]
                                            if not s_sub_ws.empty and s_sub_ws.iloc[-1]['球隊'] == ws_winner: played_ws_winner = True
                                        else:
                                            s_sub_ws = df_p[(df_p['投手姓名']==name) & (df_p['賽事階段'].astype(str).str.contains(f"[S{s_k}]", regex=False))]
                                            if not s_sub_ws.empty and s_sub_ws.iloc[-1]['球隊'] == ws_winner: played_ws_winner = True
                                            
                                        if played_ws_winner:
                                            awards['Championships'] += 1
                                        
                raw_df_for_mvp = base_df
                if season_prefix: raw_df_for_mvp = raw_df_for_mvp[raw_df_for_mvp['賽事階段'].astype(str).str.contains(season_prefix, regex=False)]
                if '單場MVP' in raw_df_for_mvp.columns:
                    awards['Game MVP'] = raw_df_for_mvp[(raw_df_for_mvp[name_col] == name) & (raw_df_for_mvp['單場MVP'].notna()) & (raw_df_for_mvp['單場MVP'].astype(str).str.strip() != "")].shape[0]

                res = {'Awards': awards, 'DisplayName': display_name}

                if is_batter:
                    pa = pd.to_numeric(sub_df['打席'], errors='coerce').fillna(0).sum()
                    ab = pd.to_numeric(sub_df['打數'], errors='coerce').fillna(0).sum()
                    h = pd.to_numeric(sub_df['安打'], errors='coerce').fillna(0).sum()
                    h2 = pd.to_numeric(sub_df['二壘安打'], errors='coerce').fillna(0).sum()
                    h3 = pd.to_numeric(sub_df['三壘安打'], errors='coerce').fillna(0).sum()
                    hr = pd.to_numeric(sub_df['全壘打'], errors='coerce').fillna(0).sum()
                    rbi = pd.to_numeric(sub_df['打點'], errors='coerce').fillna(0).sum()
                    bb = pd.to_numeric(sub_df['四壞球'], errors='coerce').fillna(0).sum()
                    so = pd.to_numeric(sub_df['三振'], errors='coerce').fillna(0).sum()
                    sb = pd.to_numeric(sub_df.get('盜壘', 0), errors='coerce').fillna(0).sum()
                    g = sub_df['賽事階段'].nunique()
                    
                    h1 = h - h2 - h3 - hr
                    avg = h / ab if ab > 0 else 0
                    obp = (h + bb) / pa if pa > 0 else 0
                    slg = (h1 + 2*h2 + 3*h3 + 4*hr) / ab if ab > 0 else 0
                    ops = obp + slg
                    
                    # ✨ 呼叫全域引擎，徹底統一打者 WAR (加權守位校正版)
                    player_ewar = 0.0
                    for s in sub_df['Season'].unique():
                        s_df = sub_df[sub_df['Season'] == s]
                        lg_s_df = base_df[base_df['賽事階段'].astype(str).str.contains(f"[S{s}]", regex=False)]
                        
                        s_pa = pd.to_numeric(lg_s_df['打席'], errors='coerce').fillna(0).sum()
                        s_h = pd.to_numeric(lg_s_df['安打'], errors='coerce').fillna(0).sum()
                        s_bb = pd.to_numeric(lg_s_df['四壞球'], errors='coerce').fillna(0).sum()
                        s_2b = pd.to_numeric(lg_s_df['二壘安打'], errors='coerce').fillna(0).sum()
                        s_3b = pd.to_numeric(lg_s_df['三壘安打'], errors='coerce').fillna(0).sum()
                        s_hr = pd.to_numeric(lg_s_df['全壘打'], errors='coerce').fillna(0).sum()
                        s_1b = s_h - s_2b - s_3b - s_hr
                        
                        s_lg_woba_num = 0.69 * s_bb + 0.88 * s_1b + 1.25 * s_2b + 1.59 * s_3b + 2.06 * s_hr
                        s_lg_woba = s_lg_woba_num / s_pa if s_pa > 0 else 0.001

                        p_pa = pd.to_numeric(s_df['打席'], errors='coerce').fillna(0).sum()
                        p_h = pd.to_numeric(s_df['安打'], errors='coerce').fillna(0).sum()
                        p_bb = pd.to_numeric(s_df['四壞球'], errors='coerce').fillna(0).sum()
                        p_2b = pd.to_numeric(s_df['二壘安打'], errors='coerce').fillna(0).sum()
                        p_3b = pd.to_numeric(s_df['三壘安打'], errors='coerce').fillna(0).sum()
                        p_hr = pd.to_numeric(s_df['全壘打'], errors='coerce').fillna(0).sum()
                        p_1b = p_h - p_2b - p_3b - p_hr
                        
                        p_woba = (0.69 * p_bb + 0.88 * p_1b + 1.25 * p_2b + 1.59 * p_3b + 2.06 * p_hr) / p_pa if p_pa > 0 else 0
                        p_wrc_plus = ((p_woba / s_lg_woba) - 1) * 200 + 100 if s_lg_woba > 0 else 0
                        
                        pos_adj_dict = {"C": 0.15, "SS": 0.12, "2B": 0.05, "3B": 0.05, "CF": 0.05, "LF": 0.00, "RF": 0.00, "1B": -0.05, "DH": -0.12, "PH": -0.12, "PR": -0.12}
                        if '守位' in s_df.columns:
                            total_pos_adj = sum(pos_adj_dict.get(row['守位'], -0.12) * pd.to_numeric(row['打席'], errors='coerce') for _, row in s_df.iterrows())
                            weighted_pos_adj = total_pos_adj / p_pa if p_pa > 0 else -0.12
                        else:
                            weighted_pos_adj = -0.12

                        s_ewar = (((p_wrc_plus - 70) / 80) + weighted_pos_adj) * (p_pa / 15)
                        s_ewar = 0.0 if abs(s_ewar) < 0.05 else round(s_ewar, 1)
                        player_ewar += s_ewar
                        
                    lg_pa = pd.to_numeric(pk_df['打席'], errors='coerce').fillna(0).sum()
                    lg_ab = pd.to_numeric(pk_df['打數'], errors='coerce').fillna(0).sum()
                    lg_h = pd.to_numeric(pk_df['安打'], errors='coerce').fillna(0).sum()
                    lg_bb = pd.to_numeric(pk_df['四壞球'], errors='coerce').fillna(0).sum()
                    lg_2b = pd.to_numeric(pk_df['二壘安打'], errors='coerce').fillna(0).sum()
                    lg_3b = pd.to_numeric(pk_df['三壘安打'], errors='coerce').fillna(0).sum()
                    lg_hr = pd.to_numeric(pk_df['全壘打'], errors='coerce').fillna(0).sum()
                    lg_1b = lg_h - lg_2b - lg_3b - lg_hr
                    
                    lg_obp = (lg_h + lg_bb) / lg_pa if lg_pa > 0 else 0.320
                    lg_slg = (lg_1b + 2*lg_2b + 3*lg_3b + 4*lg_hr) / lg_ab if lg_ab > 0 else 0.400
                    ops_plus = 100 * ((obp / max(0.001, lg_obp)) + (slg / max(0.001, lg_slg)) - 1)

                    res.update({'WAR': round(player_ewar, 1), 'G': int(g), 'PA': int(pa), 'H': int(h), 'HR': int(hr), 
                                'RBI': int(rbi), 'SB': int(sb), 'AVG': avg, 'OBP': obp, 'SLG': slg, 'OPS': ops, 'OPS+': round(ops_plus)})
                    return res
                else:
                    outs = (pd.to_numeric(sub_df['局數(整數)'], errors='coerce').fillna(0) * 3 + pd.to_numeric(sub_df['局數(出局數)'], errors='coerce').fillna(0)).sum()
                    ip = outs / 3.0
                    er = pd.to_numeric(sub_df['自責分'], errors='coerce').fillna(0).sum()
                    so = pd.to_numeric(sub_df['奪三振'], errors='coerce').fillna(0).sum()
                    bb = pd.to_numeric(sub_df['四壞球'], errors='coerce').fillna(0).sum()
                    h = pd.to_numeric(sub_df['被安打'], errors='coerce').fillna(0).sum()
                    hr = pd.to_numeric(sub_df['被全壘打'], errors='coerce').fillna(0).sum()
                    
                    w, l = 0, 0
                    for _, r in sub_df.iterrows():
                        res_str = str(r.get('勝敗', ''))
                        if '勝' in res_str: w += 1
                        if '敗' in res_str: l += 1
                    
                    g = sub_df['賽事階段'].nunique()
                    era = (er * 9) / ip if ip > 0 else 0.0
                    fip = (((13 * hr) + (3 * bb) - (2 * so)) / ip) + 3.10 if ip > 0 else 3.10
                    whip = (h + bb) / ip if ip > 0 else 0.0
                    so9 = (so * 9) / ip if ip > 0 else 0.0
                    so_bb = so / bb if bb > 0 else float('inf')
                    
                    lg_outs = (pd.to_numeric(pk_df['局數(整數)'], errors='coerce').fillna(0).sum() * 3 + pd.to_numeric(pk_df['局數(出局數)'], errors='coerce').fillna(0).sum())
                    lg_ip = lg_outs / 3.0
                    lg_er = pd.to_numeric(pk_df['自責分'], errors='coerce').fillna(0).sum()
                    lg_era = (lg_er * 9) / lg_ip if lg_ip > 0 else 10.60
                    era_plus = 100 * (lg_era / era) if era > 0 else (999 if era == 0 and ip > 0 else 0)
                    
                    # ✨ 呼叫全域引擎，徹底統一投手 eWAR！
                    player_ewar = 0.0
                    for s in sub_df['Season'].unique():
                        s_df = sub_df[sub_df['Season'] == s]
                        lg_s_df = base_df[base_df['賽事階段'].astype(str).str.contains(f"[S{s}]", regex=False)]
                        
                        s_outs = (pd.to_numeric(lg_s_df['局數(整數)'], errors='coerce').fillna(0).sum() * 3) + pd.to_numeric(lg_s_df['局數(出局數)'], errors='coerce').fillna(0).sum()
                        s_lg_ip = s_outs / 3.0
                        s_lg_er = pd.to_numeric(lg_s_df['自責分'], errors='coerce').fillna(0).sum()
                        s_lg_era = (s_lg_er * 9) / s_lg_ip if s_lg_ip > 0 else 10.60
                        
                        p_outs = (pd.to_numeric(s_df['局數(整數)'], errors='coerce').fillna(0).sum() * 3) + pd.to_numeric(s_df['局數(出局數)'], errors='coerce').fillna(0).sum()
                        p_ip = p_outs / 3.0
                        p_er = pd.to_numeric(s_df['自責分'], errors='coerce').fillna(0).sum()
                        p_hr = pd.to_numeric(s_df['被全壘打'], errors='coerce').fillna(0).sum()
                        p_bb = pd.to_numeric(s_df['四壞球'], errors='coerce').fillna(0).sum()
                        p_so = pd.to_numeric(s_df['奪三振'], errors='coerce').fillna(0).sum()
                        
                        p_era = (p_er * 9) / p_ip if p_ip > 0 else float('inf') if p_er > 0 else 0.0
                        p_fip = (((13 * p_hr) + (3 * p_bb) - (2 * p_so)) / p_ip) + 3.10 if p_ip > 0 else float('inf') if (13*p_hr+3*p_bb-2*p_so)>0 else 3.10
                        
                        s_rep_level = s_lg_era * 1.30
                        s_era_div = max(1.5, s_lg_era * 0.2)
                        tra = (p_era * 0.3) + (p_fip * 0.7) if int(s) >= 6 else (p_era + p_fip) / 2.0
                        
                        if p_ip == 0: s_ewar = (-0.1 * p_er) - (0.05 * p_bb)
                        else: s_ewar = ((s_rep_level - tra) / s_era_div) * (p_ip / 10)
                        
                        s_ewar = 0.0 if abs(s_ewar) < 0.05 else round(s_ewar, 1)
                        player_ewar += s_ewar

                    res.update({'WAR': round(player_ewar, 1), 'W': int(w), 'L': int(l), 'ERA': era, 'ERA+': round(era_plus), 'G': int(g), 
                                'IP': round(ip, 1), 'SO': int(so), 'WHIP': whip, 'FIP': fip, 'SO/BB': so_bb})
                    return res

            stats_A = get_pk_stats(p1_sel, is_pk_batter)
            stats_B = get_pk_stats(p2_sel, is_pk_batter)

            if stats_A and stats_B:
                def make_row(stat_key, label, format_str, lower_is_better=False):
                    val_a = stats_A[stat_key]
                    val_b = stats_B[stat_key]
                    
                    if stat_key == 'SO/BB' and val_a == float('inf'): str_a = "∞"
                    else: str_a = format_str.format(val_a)
                    
                    if stat_key == 'SO/BB' and val_b == float('inf'): str_b = "∞"
                    else: str_b = format_str.format(val_b)
                    
                    style_green = "background-color:#e8f4e9; font-weight:bold; color:#2e7d32;"
                    style_normal = "color:#eeeeee;"
                    
                    final_style_a = style_normal
                    final_style_b = style_normal

                    if val_a != val_b:
                        if lower_is_better:
                            if val_a < val_b: final_style_a = style_green
                            else: final_style_b = style_green
                        else:
                            if val_a > val_b: final_style_a = style_green
                            else: final_style_b = style_green
                    
                    return f"<tr><td style='text-align:center; padding:5px; border-bottom:1px solid #444; {final_style_a} font-size:14px;'>{str_a}</td><td style='text-align:center; padding:5px; border-bottom:1px solid #444; font-weight:bold; color:#aaa; font-size:12px;'>{label}</td><td style='text-align:center; padding:5px; border-bottom:1px solid #444; {final_style_b} font-size:14px;'>{str_b}</td></tr>"

                def make_row_award(val_a, label, val_b):
                    str_a = f"{val_a}" if val_a > 0 else ""
                    str_b = f"{val_b}" if val_b > 0 else ""
                    
                    style_green = "background-color:#e8f4e9; font-weight:bold; color:#2e7d32;"
                    style_normal = "color:#eeeeee;"
                    
                    final_style_a = style_normal
                    final_style_b = style_normal
                    
                    if val_a != val_b:
                        if val_a > val_b: final_style_a = style_green
                        else: final_style_b = style_green
                    
                    return f"<tr><td style='text-align:center; padding:5px; border-bottom:1px solid #444; {final_style_a} font-size:14px;'>{str_a}</td><td style='text-align:center; padding:5px; border-bottom:1px solid #444; font-weight:bold; color:#aaa; font-size:12px;'>{label}</td><td style='text-align:center; padding:5px; border-bottom:1px solid #444; {final_style_b} font-size:14px;'>{str_b}</td></tr>"

                html_table = f"<div style='background-color:#1e1e1e; padding:15px; border-radius:10px; border:1px solid #444; max-width:650px; margin:0 auto;'><table style='width:100%; border-collapse:collapse; font-family:sans-serif;'><tr><td style='text-align:center; padding-bottom:10px; width:35%;'><h4 style='color:#00e5ff; margin:0;'>{stats_A['DisplayName']}</h4></td><td style='text-align:center; padding-bottom:10px; width:30%;'><span style='color:gray; font-size:12px; letter-spacing:1px;'>STATHEAD</span></td><td style='text-align:center; padding-bottom:10px; width:35%;'><h4 style='color:#ff4b4b; margin:0;'>{stats_B['DisplayName']}</h4></td></tr><tr><td colspan='3' style='text-align:center; padding:6px; color:#ff4b4b; font-size:15px; font-weight:bold; border-bottom:1px solid #444; border-top:2px solid #555;'>Overall Stats</td></tr>"
                
                if is_pk_batter:
                    html_table += make_row('WAR', 'WAR', "{:.1f}")
                    html_table += make_row('G', 'G', "{:.0f}")
                    html_table += make_row('PA', 'PA', "{:.0f}")
                    html_table += make_row('H', 'H', "{:.0f}")
                    html_table += make_row('HR', 'HR', "{:.0f}")
                    html_table += make_row('RBI', 'RBI', "{:.0f}")
                    html_table += make_row('SB', 'SB', "{:.0f}")
                    html_table += make_row('AVG', 'BA', "{:.3f}")
                    html_table += make_row('OBP', 'OBP', "{:.3f}")
                    html_table += make_row('SLG', 'SLG', "{:.3f}")
                    html_table += make_row('OPS', 'OPS', "{:.3f}")
                    html_table += make_row('OPS+', 'OPS+', "{:.0f}")
                else:
                    html_table += make_row('WAR', 'WAR', "{:.1f}")
                    html_table += make_row('W', 'W', "{:.0f}")
                    html_table += make_row('L', 'L', "{:.0f}", lower_is_better=True)
                    html_table += make_row('ERA', 'ERA', "{:.2f}", lower_is_better=True)
                    html_table += make_row('ERA+', 'ERA+', "{:.0f}")
                    html_table += make_row('G', 'G', "{:.0f}")
                    html_table += make_row('IP', 'IP', "{:.1f}")
                    html_table += make_row('SO', 'SO', "{:.0f}")
                    html_table += make_row('WHIP', 'WHIP', "{:.2f}", lower_is_better=True)
                    html_table += make_row('FIP', 'FIP', "{:.2f}", lower_is_better=True)
                    html_table += make_row('SO/BB', 'SO/BB', "{:.2f}")

                aw_A = stats_A['Awards']
                aw_B = stats_B['Awards']
                
                if any(v > 0 for v in aw_A.values()) or any(v > 0 for v in aw_B.values()):
                    html_table += "<tr><td colspan='3' style='text-align:center; padding:15px 5px 6px 5px; color:#ff4b4b; font-size:15px; font-weight:bold; border-bottom:1px solid #444;'>Awards & Honors</td></tr>"
                    
                    if is_pk_batter:
                        award_keys = [
                            ('Championships', 'Championships'), 
                            ('1st Team', '1st Team'),
                            ('MVP', 'MVP'), 
                            ('Silver Slugg', 'Silver Slugg'), 
                            ('FMVP', 'WS MVP')
                        ]
                    else:
                        award_keys = [
                            ('Championships', 'Championships'), 
                            ('1st Team', '1st Team'),
                            ('MVP', 'MVP'), 
                            ('Cy Young', 'Cy Young'), 
                            ('FMVP', 'WS MVP')
                        ]
                    
                    for dict_key, label in award_keys:
                        val_a = aw_A[dict_key]
                        val_b = aw_B[dict_key]
                        if val_a > 0 or val_b > 0:
                            html_table += make_row_award(val_a, label, val_b)

                html_table += "</table></div>"
                st.markdown(html_table, unsafe_allow_html=True)