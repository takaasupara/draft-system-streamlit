import streamlit as st
import json, os, math, random, hashlib, datetime
import pandas as pd
import urllib.parse

# -------- 環境設定 --------
DATA_FILE = "drafts.json"
CONFIG_FILE = "config.json"
BASE_URL = "http://localhost:8501"   # 実運用URLに書き換え可

# ---------------------------
# JSON 読み書き
# ---------------------------
def _load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_drafts(): return _load_json(DATA_FILE, {})
def save_drafts(drafts): _save_json(DATA_FILE, drafts)
def load_config(): return _load_json(CONFIG_FILE, {"admins": []})
def save_config(cfg): _save_json(CONFIG_FILE, cfg)

# ---------------------------
# セキュリティ
# ---------------------------
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def sanitize_title(title: str) -> str:
    t = title.strip()
    for ch in ["/","\\",":","?","*","[","]"]:
        t = t.replace(ch, "-")
    if len(t) > 100: t = t[:100]+"..."
    return t if t else "Untitled"

# ---------------------------
# 抽選ロジック
# ---------------------------
def run_draft(votes, choices):
    assigned, remaining = {}, choices.copy()
    for rank in [f"{i}位" for i in range(1, len(choices)+1)]:
        conflicts = {}
        for name, vote in votes.items():
            if name not in assigned and vote[rank] in remaining:
                conflicts.setdefault(vote[rank], []).append(name)
        for c, names in conflicts.items():
            if len(names)==1:
                assigned[names[0]]=c; remaining.remove(c)
            else:
                winner = random.choice(names)
                assigned[winner]=c; remaining.remove(c)
    for n in votes:
        if n not in assigned: assigned[n] = "-"
    return assigned

def finalize_if_ready(drafts, draft_id):
    d = drafts[draft_id]
    if d["status"]!="投票中": return False
    total = int(d.get("participants",0))
    if total>0 and len(d["votes"])>=total:
        d["assigned"]=run_draft(d["votes"], d["choices"])
        d["status"]="終了"; save_drafts(drafts)
        st.session_state["page"]="結果"; st.session_state["draft_id"]=draft_id
        st.rerun()
        return True
    return False

# ---------------------------
# ページ決定（URLとセッション同期）
# ---------------------------
st.set_page_config(page_title="ドラフトシステム", layout="wide")

drafts = load_drafts()
config = load_config()
ADMINS = config.get("admins", [])

# 初期化
if "page" not in st.session_state: 
    st.session_state["page"] = "ホーム"
if "draft_id" not in st.session_state: 
    st.session_state["draft_id"] = None
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = None

# クエリ取得（必ず文字列に変換）
qp_page = st.query_params.get("page", None)
if isinstance(qp_page, list): qp_page = qp_page[0]
if qp_page:
    qp_page = urllib.parse.unquote(str(qp_page))
    st.session_state["page"] = qp_page

qp_draft = st.query_params.get("draft_id", None)
if isinstance(qp_draft, list): qp_draft = qp_draft[0]
if qp_draft:
    st.session_state["draft_id"] = str(qp_draft)

page = st.session_state["page"]
draft_id = st.session_state["draft_id"]

# ---------------------------
# サイドバー（リンク表示のみ）
# ---------------------------
st.sidebar.title("メニュー")
st.sidebar.markdown(f"[ホーム]({BASE_URL}/?page=ホーム)", unsafe_allow_html=True)
st.sidebar.markdown(f"[履歴]({BASE_URL}/?page=履歴)", unsafe_allow_html=True)
st.sidebar.markdown(f"[管理者]({BASE_URL}/?page=管理者)", unsafe_allow_html=True)

# ---------------------------
# ホーム
# ---------------------------
if page=="ホーム":
    st.title("ドラフトシステム")
    if drafts:
        st.subheader("最新のドラフト")
        sorted_d = sorted(drafts.items(), key=lambda x:x[1]["date"], reverse=True)[:3]
        for draft_id, d in sorted_d:
            url = f"{BASE_URL}/?page={'投票' if d['status']=='投票中' else ('結果' if d['status']=='終了' else '中止')}&draft_id={draft_id}"
            st.markdown(f"- {d['date']} <a href='{url}' target='_self'><b>{d['title']} | {d['status']}</b></a>", unsafe_allow_html=True)
    else:
        st.info("まだドラフトはありません。")

# ---------------------------
# 履歴
# ---------------------------
elif page=="履歴":
    st.title("履歴")
    if drafts:
        sorted_d = sorted(drafts.items(), key=lambda x:x[1]["date"], reverse=True)
        per_page, total_pages = 10, max(1, math.ceil(len(sorted_d)/10))
        page_no = st.session_state.get("history_page", 1)
        start, end = (page_no-1)*per_page, (page_no)*per_page
        for draft_id,d in sorted_d[start:end]:
            url = f"{BASE_URL}/?page={'投票' if d['status']=='投票中' else ('結果' if d['status']=='終了' else '中止')}&draft_id={draft_id}"
            st.markdown(f"- {d['date']} <a href='{url}' target='_self'><b>{d['title']} | {d['status']}</b></a>", unsafe_allow_html=True)
        col1,col2,col3 = st.columns([1,2,1])
        with col1:
            if st.button("← 前へ") and page_no>1: st.session_state["history_page"]=page_no-1; st.rerun()
        with col3:
            if st.button("次へ →") and page_no<total_pages: st.session_state["history_page"]=page_no+1; st.rerun()
        st.write(f"{page_no}/{total_pages} ページ")
    else:
        st.info("履歴はありません。")

# ---------------------------
# 投票
# ---------------------------
elif page=="投票":
    if not draft_id or draft_id not in drafts: 
        st.error("指定ドラフトなし")
    else:
        d = drafts[draft_id]
        if d["status"]=="終了":
            st.session_state["page"]="結果"; st.rerun()
        elif d["status"]=="中止":
            st.session_state["page"]="中止"; st.rerun()
        else:
            st.title(f"投票: {d['title']}")

            name = st.text_input("名前")
            if name:
                rankings = {}
                used = set()
                num_ranks = len(d["choices"])

                for i in range(1, num_ranks+1):
                    options = ["---"] + [c for c in d["choices"] if c not in used]
                    selected = st.selectbox(f"{i}位", options, index=0, key=f"rank_{i}")
                    rankings[f"{i}位"] = selected
                    if selected != "---":
                        used.add(selected)

                all_filled = all(v != "---" for v in rankings.values())

                if not all_filled:
                    st.warning("⚠ すべての順位を選んでから投票してください")

                if st.button("投票する", disabled=not all_filled):
                    d["votes"][name] = rankings
                    save_drafts(drafts)
                    st.success("投票しました")
                    if finalize_if_ready(drafts, draft_id):
                        st.stop()
                    else:
                        st.rerun()

            remaining = d["participants"] - len(d["votes"])
            if remaining > 0:
                st.info(f"あと {remaining} 人の投票でドラフトが実行されます")

            st.subheader("投票済み")
            for voter in d["votes"]:
                st.write(f"{voter} → 投票済み")

# ---------------------------
# 結果
# ---------------------------
elif page=="結果":
    if not draft_id or draft_id not in drafts: 
        st.error("指定ドラフトなし")
    else:
        d=drafts[draft_id]
        if d["status"]=="投票中":
            st.session_state["page"]="投票"; st.rerun()
        elif d["status"]=="中止":
            st.session_state["page"]="中止"; st.rerun()
        else:
            st.title(f"結果: {d['title']}")
            st.subheader("割当結果")
            for n,v in d["assigned"].items(): st.write(f"{n} → {v}")
            st.subheader("希望順位")
            if d["votes"]:
                df = pd.DataFrame.from_dict(d["votes"], orient="index")
                df.index.name = "名前"
                st.table(df)
            else:
                st.write("投票データなし")

# ---------------------------
# 中止
# ---------------------------
elif page=="中止":
    st.title("このドラフトは中止されました")

# ---------------------------
# 管理者
# ---------------------------
elif page=="管理者":
    st.title("管理者ページ")
    if not st.session_state["logged_in"]:
        u=st.text_input("ユーザー名"); p=st.text_input("パスワード",type="password")
        if st.button("ログイン"):
            if next((a for a in ADMINS if a["username"]==u and a["password"]==hash_password(p)),None):
                st.session_state["logged_in"]=True
                st.session_state["username"]=u
                st.rerun()
            else: st.error("ログイン失敗")
    else:
        st.write(f"ログイン中: {st.session_state['username']}")
        if "choice_count" not in st.session_state: st.session_state.choice_count=3
        title=st.text_input("ドラフトタイトル"); participants=st.number_input("参加人数",1,999,3)
        choices=[st.text_input(f"選択肢 {i+1}", key=f"choice_{i}") for i in range(st.session_state.choice_count)]
        col1,col2=st.columns(2)
        if col1.button("＋追加"): st.session_state.choice_count+=1; st.rerun()
        if col2.button("−削除") and st.session_state.choice_count>1: st.session_state.choice_count-=1; st.rerun()
        if st.button("投票開始"):
            draft_id=str(len(drafts)+1)
            drafts[draft_id]={
                "title":sanitize_title(title),
                "date":datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status":"投票中",
                "participants":int(participants),
                "choices":choices,
                "votes":{},
                "assigned":{},
                "created_by": st.session_state["username"]
            }
            save_drafts(drafts)
            vote_url=f"{BASE_URL}/?page=投票&draft_id={draft_id}"
            st.success("ドラフト作成！")
            st.markdown(f'<a href="{vote_url}" target="_self">このドラフトの投票ページはこちら</a>', unsafe_allow_html=True)
            st.code(vote_url)
        st.subheader("現在のドラフト一覧（投票受付中・あなたが作成したもののみ）")
        for draft_id,d in drafts.items():
            if d["status"]=="投票中" and d.get("created_by")==st.session_state["username"]:
                st.write(f"{draft_id}: {d['title']} ({d['status']})")
