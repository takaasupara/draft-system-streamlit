import streamlit as st
import json, os, math, random, hashlib, datetime, urllib.parse, time
import pandas as pd
from streamlit_cookies_manager import EncryptedCookieManager
from supabase import create_client, Client
import os

# -------- 環境設定 --------
DATA_FILE = "drafts.json"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
BASE_URL = "https://draft-system-app-armvfexpppgyuyfb9vzbn6.streamlit.app"   # 実運用URLに書き換え可

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



# --- Supabase 接続設定 ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- drafts.json 代替 ---
def load_drafts():
    res = supabase.table("drafts").select("data").eq("id", "main").execute()
    if not res.data:
        return {}
    return res.data[0]["data"]

def save_drafts(d):
    supabase.table("drafts").upsert({"id": "main", "data": d}).execute()

# --- config.json 代替 ---
def load_config():
    # ① JSON（config.json）を最優先で読む
    try:
        cfg = _load_json(CONFIG_FILE, None)
        if isinstance(cfg, dict) and cfg.get("admins"):
            return cfg
    except Exception:
        pass

    # ② だめなら Supabase をフォールバック
    try:
        res = supabase.table("config").select("data").eq("id", "main").execute()
        if res.data:
            data = res.data[0].get("data")
            if isinstance(data, dict) and data.get("admins") is not None:
                return data
    except Exception:
        pass

    # ③ どちらも無ければ空
    return {"admins": []}

def save_config(c):
    supabase.table("config").upsert({"id": "main", "data": c}).execute()


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
    """全員の投票が揃ったら抽選を実行し、結果ページに移行可能な状態にする"""
    d = drafts[draft_id]
    if d["status"] != "投票中":
        return False

    total = int(d.get("participants", 0))
    if total > 0 and len(d["votes"]) >= total:
        d["assigned"] = run_draft(d["votes"], d["choices"])
        d["status"] = "終了"
        save_drafts(drafts)
        st.session_state["page"] = "結果"
        st.session_state["draft_id"] = draft_id
        return True
    return False

# ---------------------------
# Cookie管理
# ---------------------------
cookies = EncryptedCookieManager(prefix="draft-system", password="super-secret-key")
if not cookies.ready():
    st.stop()

# cookie → session_state へ同期
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = cookies.get("logged_in") == "true"
if "username" not in st.session_state:
    st.session_state["username"] = cookies.get("username")
if "voter_name" not in st.session_state:
    st.session_state["voter_name"] = cookies.get("voter_name")

# ---------------------------
# ページ設定
# ---------------------------
st.set_page_config(page_title="ドラフトシステム", layout="wide")

drafts = load_drafts()
config = load_config()
ADMINS = config.get("admins", [])

if "page" not in st.session_state: 
    st.session_state["page"] = "ホーム"
if "draft_id" not in st.session_state: 
    st.session_state["draft_id"] = None

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
# サイドバー
# ---------------------------
st.sidebar.title("メニュー")
st.sidebar.markdown(f'<a href="{BASE_URL}/?page=ホーム" target="_self">ホーム</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="{BASE_URL}/?page=履歴" target="_self">履歴</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="{BASE_URL}/?page=管理者" target="_self">管理者</a>', unsafe_allow_html=True)

# ---------------------------
# ホーム（すべての投票中ドラフトを表示）
# ---------------------------
if page=="ホーム":
    st.title("ドラフトシステム")
    if drafts:
        st.subheader("現在行われているドラフト一覧（投票中）")
        active_drafts = {k: v for k, v in drafts.items() if v["status"] == "投票中"}
        if active_drafts:
            sorted_d = sorted(active_drafts.items(), key=lambda x: x[1]["date"], reverse=True)
            for draft_id, d in sorted_d:
                url = f"{BASE_URL}/?page=投票&draft_id={draft_id}"
                st.markdown(f"- {d['date']} <a href='{url}' target='_self'><b>{d['title']} | {d['status']}</b></a>", unsafe_allow_html=True)
        else:
            st.info("現在進行中のドラフトはありません。")

        # ✅ 最近のドラフト3件表示
        st.subheader("🕓 最近のドラフト（最新3件）")
        sorted_recent = sorted(drafts.items(), key=lambda x: x[1]["date"], reverse=True)[:3]
        for draft_id, d in sorted_recent:
            if d["status"] == "投票中":
                target_page = "投票"
            elif d["status"] == "終了":
                target_page = "結果"
            else:
                target_page = "中止"
            url = f"{BASE_URL}/?page={target_page}&draft_id={draft_id}"
            st.markdown(
                f"• <a href='{url}' target='_self'><b>{d['title']}</b></a> "
                f"({d['date']}｜{d['status']})",
                unsafe_allow_html=True
            )
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
        # ✅ 結果ページへのリダイレクト（確実動作版）
        if d["status"]=="終了":
            st.session_state["page"]="結果"
            st.session_state["draft_id"]=draft_id
            st.query_params.update({"page": "結果", "draft_id": draft_id})
            st.rerun()
        elif d["status"]=="中止":
            st.session_state["page"]="中止"
            st.query_params.update({"page": "中止", "draft_id": draft_id})
            st.rerun()
        else:
            st.title(f"投票: {d['title']}")
            if not st.session_state.get("voter_name"):
                name = st.text_input("名前")
                if name and st.button("保存"):
                    st.session_state["voter_name"]=name
                    cookies["voter_name"]=name
                    cookies.save()
                    st.rerun()
            else:
                name = st.session_state["voter_name"]
                st.write(f"あなたは **{name}** として投票中")
                st.caption("※投票を変更したい場合は、以下から再回答することで上書き可能です。")

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
                    st.success("投票しました（再投票時は上書きされます）")

                    if finalize_if_ready(drafts, draft_id):
                        st.success("全員の投票が完了しました！結果ページに移動します...")
                        st.session_state["page"] = "結果"
                        st.session_state["draft_id"] = draft_id
                        st.query_params.update({"page": "結果", "draft_id": draft_id})
                        time.sleep(1.0)
                        st.rerun()
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
        # ✅ 投票ページへのリダイレクト（確実動作版）
        if d["status"]=="投票中":
            st.session_state["page"]="投票"
            st.session_state["draft_id"]=draft_id
            st.query_params.update({"page": "投票", "draft_id": draft_id})
            st.rerun()
        elif d["status"]=="中止":
            st.session_state["page"]="中止"
            st.query_params.update({"page": "中止", "draft_id": draft_id})
            st.rerun()
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
        #デバッグ用
        st.write("DEBUG:", load_config())

        if st.button("ログイン"):
            if next((a for a in ADMINS if a["username"]==u and a["password"]==hash_password(p)),None):
                st.session_state["logged_in"]=True
                st.session_state["username"]=u
                cookies["logged_in"]="true"
                cookies["username"]=u
                cookies.save()
                st.rerun()
            else: st.error("ログイン失敗")
    else:
        st.write(f"ログイン中: {st.session_state['username']}")

        # 新規作成見出し
        st.divider()
        st.markdown("## 🆕 投票を新規作成")

        if "choice_count" not in st.session_state: st.session_state.choice_count=3
        title=st.text_input("ドラフトタイトル"); participants=st.number_input("参加人数",1,999,3)
        choices=[st.text_input(f"選択肢 {i+1}", key=f"choice_{i}") for i in range(st.session_state.choice_count)]
        col1,col2=st.columns(2)
        if col1.button("＋追加"): st.session_state.choice_count+=1; st.rerun()
        if col2.button("−削除") and st.session_state.choice_count>1: st.session_state.choice_count-=1; st.rerun()

        # ✅ 空欄除外 + 重複チェック追加
        if st.button("投票開始"):
            valid_choices = [c.strip() for c in choices if c.strip()]
            if not valid_choices:
                st.error("選択肢を1つ以上入力してください")
            elif len(valid_choices) != len(set(valid_choices)):
                st.error("選択肢が重複しています。同じ名前は使用できません。")
            else:
                draft_id=str(len(drafts)+1)
                drafts[draft_id]={ 
                    "title":sanitize_title(title),
                    "date":datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "status":"投票中",
                    "participants":int(participants),
                    "choices":valid_choices,
                    "votes":{},
                    "assigned":{},
                    "created_by": st.session_state["username"]
                }
                save_drafts(drafts)
                vote_url=f"{BASE_URL}/?page=投票&draft_id={draft_id}"
                st.success("ドラフト作成！")
                st.markdown(f'<a href="{vote_url}" target="_self">このドラフトの投票ページはこちら</a>', unsafe_allow_html=True)
                st.code(vote_url)

        # ---- 現在のドラフト一覧（中止ボタン付き） ----
        st.divider()
        st.subheader("現在のドラフト一覧（投票受付中・あなたが作成したもののみ）")
        for draft_id, d in drafts.items():
            if d["status"] == "投票中" and d.get("created_by") == st.session_state["username"]:
                st.write(f"{draft_id}: {d['title']} ({d['status']})")

                cancel_key = f"cancel_{draft_id}"
                confirm_key = f"confirm_cancel_{draft_id}"

                if st.session_state.get(confirm_key, False):
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ 本当に中止する", key=f"do_cancel_{draft_id}"):
                            d["status"] = "中止"
                            save_drafts(drafts)
                            st.success(f"「{d['title']}」を中止しました。")
                            st.session_state["page"] = "中止"
                            st.session_state["draft_id"] = draft_id
                            st.session_state[confirm_key] = False
                            st.rerun()
                    with col2:
                        if st.button("❌ やめる", key=f"cancel_cancel_{draft_id}"):
                            st.session_state[confirm_key] = False
                            st.rerun()
                else:
                    if st.button("🛑 中止", key=cancel_key):
                        st.session_state[confirm_key] = True
                        st.info("本当に中止しますか？")
                        st.rerun()
