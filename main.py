import asyncio
import requests
import json
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from openai import OpenAI
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ----------------- 🛠️ 全域參數設定區 -----------------
OPENAI_API_KEY = "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"
BOT_TOKEN = "8936011094:AAEhPR3FSgVYp2ZtNe3zWpxXB2MxqrP2r4Q"
ADMIN_CHAT_ID = "5681949363"  # 你的管理員 Telegram ID
SEEN_POSTS_FILE = "seen_posts.json"
CLIENTS_FILE = "clients.json"

client = OpenAI(api_key=OPENAI_API_KEY)
admin_states = {}  # 暫存管理員操作步驟

# ----------------- 📂 防重複機制與讀寫 -----------------
if os.path.exists(SEEN_POSTS_FILE):
    try:
        with open(SEEN_POSTS_FILE, "r", encoding="utf-8") as f:
            seen_posts = set(json.load(f))
    except Exception:
        seen_posts = set()
else:
    seen_posts = set()

def save_seen_posts():
    try:
        with open(SEEN_POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_posts), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

# ----------------- 🤖 AI 智慧多客戶比對核心 -----------------
def analyze_post_for_multiple_clients(post_text: str, active_clients: list):
    """ 讓 AI 一次檢視貼文，比對所有有效客戶需求，回傳符合資格的清單 """
    clients_info_str = ""
    for idx, c in enumerate(active_clients):
        clients_info_str += f"[{idx}] ID: {c['chat_id']}, 名稱: {c['client_name']}, 產業: {c['industry']}, 關鍵字: {c['keywords']}\n"

    system_prompt = f"""
你是一位專業的 SaaS 獲客分發助手。請分析以下的 Threads 貼文，並逐一比對下方的所有客戶資料，判斷這篇貼文是否為他們的潛在客源。

有效客戶清單：
{clients_info_str}

請嚴格輸出 JSON 格式（回傳一個陣列，符合條件的客戶才放進來）：
[
  {{
    "chat_id": "對應客戶的chat_id",
    "category": "需求分類",
    "urgency": "高" | "中" | "低",
    "reason": "判定原因",
    "reply_draft": "自然專業的私訊/回覆建議（100字內）"
  }}
]
如果沒有任何一位客戶符合，請回傳空陣列 `[]`。
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"貼文內容：\n{post_text}"}
            ],
            temperature=0.2
        )
        result = json.loads(response.choices[0].message.content)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "matches" in result:
            return result["matches"]
        return []
    except Exception as e:
        print(f"❌ AI 批次比對發生錯誤: {e}")
        return []

# ----------------- 📲 Telegram 發送訊息 -----------------
def send_telegram_msg(chat_id: str, text: str, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")

# ----------------- 🔘 Telegram 完整互動與管理員五合一控制台 -----------------
def handle_telegram_updates():
    global admin_states
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=-1"
    try:
        res = requests.get(url, timeout=5).json()
        for result in res.get("result", []):
            
            # 1. 處理按鈕點擊 (Callback Query)
            if "callback_query" in result:
                query = result["callback_query"]
                chat_id = str(query["message"]["chat"]["id"])
                data = query["data"]
                
                # 客戶端按鈕
                if data == "check_status":
                    clients_dict = load_json(CLIENTS_FILE)
                    client_info = clients_dict.get(chat_id, {})
                    status_text = f"🟢 <b>系統運行正常</b>\n👤 客戶：{client_info.get('client_name', '未知')}\n⏳ 到期：{client_info.get('expire_date', '無')}"
                    send_telegram_msg(chat_id, status_text)

                elif data == "view_keywords":
                    clients_dict = load_json(CLIENTS_FILE)
                    client_info = clients_dict.get(chat_id, {})
                    kw = ", ".join(client_info.get('keywords', []))
                    send_telegram_msg(chat_id, f"📌 <b>您目前的專屬關鍵字：</b>\n{kw}")

                # 管理員控制台按鈕分流
                elif chat_id == ADMIN_CHAT_ID and data == "admin_list_clients":
                    clients_dict = load_json(CLIENTS_FILE)
                    if not clients_dict:
                        send_telegram_msg(ADMIN_CHAT_ID, "📋 目前系統中沒有任何客戶。")
                    else:
                        list_text = "📋 <b>【現有客戶列表】</b>\n━━━━━━━━━━\n"
                        for cid, info in clients_dict.items():
                            list_text += f"👤 <b>{info.get('client_name')}</b>\n🆔 ID: <code>{cid}</code>\n🏢 產業: {info.get('industry')}\n⏳ 到期: {info.get('expire_date')}\n🔍 關鍵字: {', '.join(info.get('keywords', []))}\n━━━━━━━━━━\n"
                        send_telegram_msg(ADMIN_CHAT_ID, list_text)

                elif chat_id == ADMIN_CHAT_ID and data == "start_add_client":
                    admin_states[ADMIN_CHAT_ID] = {"step": "wait_for_id", "data": {}}
                    send_telegram_msg(ADMIN_CHAT_ID, "➕ <b>【新增客戶精靈】</b>\n步驟 1/4：請輸入新客戶的 <b>Telegram Chat ID</b>：")

                elif chat_id == ADMIN_CHAT_ID and data.startswith("ind_"):
                    if data == "ind_other":
                        admin_states[ADMIN_CHAT_ID]["step"] = "wait_for_custom_industry"
                        send_telegram_msg(ADMIN_CHAT_ID, "🌐 請直接傳送您想設定的<b>自訂產業名稱</b>（例如：房地產仲介、醫美諮詢）：")
                    else:
                        industry_map = {"ind_pawn": "當舖融資", "ind_car": "中古車買賣", "ind_insurance": "保險規劃"}
                        selected_industry = industry_map.get(data, "其他")
                        
                        if ADMIN_CHAT_ID in admin_states and admin_states[ADMIN_CHAT_ID]["step"] == "wait_for_industry":
                            admin_states[ADMIN_CHAT_ID]["data"]["industry"] = selected_industry
                            admin_states[ADMIN_CHAT_ID]["step"] = "wait_for_duration"
                            
                            duration_markup = {
                                "inline_keyboard": [
                                    [{"text": "30 天 (月繳)", "callback_data": "dur_30"}, {"text": "90 天 (季繳)", "callback_data": "dur_90"}],
                                    [{"text": "365 天 (年繳)", "callback_data": "dur_365"}]
                                ]
                            }
                            send_telegram_msg(ADMIN_CHAT_ID, f"🏢 已選擇產業：<b>{selected_industry}</b>\n\n步驟 3/4：請選擇合約有效期限：", duration_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("dur_"):
                    days_map = {"dur_30": 30, "dur_90": 90, "dur_365": 365}
                    days = days_map.get(data, 30)
                    
                    if ADMIN_CHAT_ID in admin_states and admin_states[ADMIN_CHAT_ID]["step"] == "wait_for_duration":
                        expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
                        admin_states[ADMIN_CHAT_ID]["data"]["expire_date"] = expire_date
                        admin_states[ADMIN_CHAT_ID]["step"] = "wait_for_keywords"
                        
                        send_telegram_msg(ADMIN_CHAT_ID, f"⏳ 有效期：{days} 天 (到期日: <code>{expire_date}</code>)\n\n步驟 4/4：請輸入要監控的<b>關鍵字</b>（多個請用逗號隔開，例如：高雄 借錢, 高雄 周轉）：")

                elif chat_id == ADMIN_CHAT_ID and data == "admin_keyword_menu":
                    clients_dict = load_json(CLIENTS_FILE)
                    if not clients_dict:
                        send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶資料。")
                    else:
                        buttons = []
                        for cid, info in clients_dict.items():
                            buttons.append([{"text": f"🎯 管理【{info.get('client_name')}】的關鍵字", "callback_data": f"kw_manage_{cid}"}])
                        kw_markup = {"inline_keyboard": buttons}
                        send_telegram_msg(ADMIN_CHAT_ID, "✏️ <b>【關鍵字管理】</b>\n請選擇要為哪位客戶調整關鍵字：", kw_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_manage_"):
                    target_cid = data.replace("kw_manage_", "")
                    clients_dict = load_json(CLIENTS_FILE)
                    if target_cid in clients_dict:
                        client_info = clients_dict[target_cid]
                        keywords = client_info.get("keywords", [])
                        kw_text = f"🎯 客戶：<b>{client_info.get('client_name')}</b>\n📌 目前關鍵字：\n"
                        for i, kw in enumerate(keywords):
                            kw_text += f"{i+1}. {kw}\n"
                            
                        action_markup = {
                            "inline_keyboard": [
                                [{"text": "➕ 新增關鍵字", "callback_data": f"kw_add_{target_cid}"}],
                                [{"text": "🗑️ 刪除特定關鍵字", "callback_data": f"kw_del_menu_{target_cid}"}]
                            ]
                        }
                        send_telegram_msg(ADMIN_CHAT_ID, kw_text, action_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_add_"):
                    target_cid = data.replace("kw_add_", "")
                    admin_states[ADMIN_CHAT_ID] = {"step": "wait_for_new_keyword", "target_cid": target_cid}
                    send_telegram_msg(ADMIN_CHAT_ID, "➕ 請直接傳送您想為該客戶**新增的關鍵字**（若有多個請用逗號隔開）：")

                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_del_menu_"):
                    target_cid = data.replace("kw_del_menu_", "")
                    clients_dict = load_json(CLIENTS_FILE)
                    if target_cid in clients_dict:
                        keywords = clients_dict[target_cid].get("keywords", [])
                        buttons = []
                        for idx, kw in enumerate(keywords):
                            buttons.append([{"text": f"❌ 刪除：{kw}", "callback_data": f"kw_remove_{target_cid}_{idx}"}])
                        del_kw_markup = {"inline_keyboard": buttons}
                        send_telegram_msg(ADMIN_CHAT_ID, "🗑️ 請點擊你想刪除的關鍵字：", del_kw_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_remove_"):
                    parts = data.replace("kw_remove_", "").split("_")
                    target_cid = parts[0]
                    kw_index = int(parts[1])
                    clients_dict = load_json(CLIENTS_FILE)
                    if target_cid in clients_dict:
                        keywords = clients_dict[target_cid].get("keywords", [])
                        if 0 <= kw_index < len(keywords):
                            removed_kw = keywords.pop(kw_index)
                            clients_dict[target_cid]["keywords"] = keywords
                            with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                                json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                            send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功刪除關鍵字：<b>{removed_kw}</b>！")

                elif chat_id == ADMIN_CHAT_ID and data == "admin_extend_menu":
                    clients_dict = load_json(CLIENTS_FILE)
                    if not clients_dict:
                        send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶可供延期。")
                    else:
                        buttons = []
                        for cid, info in clients_dict.items():
                            buttons.append([{"text": f"⏳ 幫【{info.get('client_name')}】延長 30 天", "callback_data": f"ext_{cid}"}])
                        extend_markup = {"inline_keyboard": buttons}
                        send_telegram_msg(ADMIN_CHAT_ID, "⏳ <b>【一鍵延期管理】</b>\n請選擇要幫哪位客戶延長 30 天合約：", extend_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("ext_"):
                    target_cid = data.replace("ext_", "")
                    clients_dict = load_json(CLIENTS_FILE)
                    if target_cid in clients_dict:
                        client_info = clients_dict[target_cid]
                        current_expire = client_info.get("expire_date", datetime.now().strftime("%Y-%m-%d"))
                        base_date = datetime.strptime(current_expire, "%Y-%m-%d") if current_expire >= datetime.now().strftime("%Y-%m-%d") else datetime.now()
                        new_expire = (base_date + timedelta(days=30)).strftime("%Y-%m-%d")
                        client_info["expire_date"] = new_expire
                        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                            json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                        send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功幫【{client_info.get('client_name')}】延長 30 天！\n新到期日為：<b>{new_expire}</b>")

                elif chat_id == ADMIN_CHAT_ID and data == "admin_delete_menu":
                    clients_dict = load_json(CLIENTS_FILE)
                    if not clients_dict:
                        send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶可供刪除。")
                    else:
                        buttons = []
                        for cid, info in clients_dict.items():
                            buttons.append([{"text": f"❌ 刪除: {info.get('client_name')}", "callback_data": f"del_{cid}"}])
                        delete_markup = {"inline_keyboard": buttons}
                        send_telegram_msg(ADMIN_CHAT_ID, "⚠️ <b>【停權/刪除客戶】</b>\n請點擊你想移除的客戶：", delete_markup)

                elif chat_id == ADMIN_CHAT_ID and data.startswith("del_"):
                    target_cid = data.replace("del_", "")
                    clients_dict = load_json(CLIENTS_FILE)
                    if target_cid in clients_dict:
                        removed_name = clients_dict[target_cid].get("client_name")
                        del clients_dict[target_cid]
                        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                            json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                        send_telegram_msg(ADMIN_CHAT_ID, f"✅ 已成功將客戶【{removed_name}】自系統中移除！")

            # 2. 處理文字輸入
            elif "message" in result:
                msg = result["message"]
                chat_id = str(msg["chat"]["id"])
                text = msg.get("text", "").strip()

                if chat_id == ADMIN_CHAT_ID and text == "/admin":
                    admin_markup = {
                        "inline_keyboard": [
                            [{"text": "📋 查看現有客戶列表", "callback_data": "admin_list_clients"}],
                            [{"text": "➕ 新增客戶 (按鈕精靈)", "callback_data": "start_add_client"}],
                            [{"text": "✏️ 管理客戶關鍵字", "callback_data": "admin_keyword_menu"}],
                            [{"text": "⏳ 幫客戶一鍵延期", "callback_data": "admin_extend_menu"}],
                            [{"text": "❌ 停權/刪除客戶", "callback_data": "admin_delete_menu"}]
                        ]
                    }
                    send_telegram_msg(ADMIN_CHAT_ID, "🛠️ <b>【SaaS 獲客系統 - 管理員控制台】</b>\n請選擇您要執行的管理動作：", admin_markup)

                elif chat_id == ADMIN_CHAT_ID and ADMIN_CHAT_ID in admin_states:
                    state = admin_states[ADMIN_CHAT_ID]
                    step = state["step"]

                    if step == "wait_for_id":
                        state["data"]["chat_id"] = text
                        state["step"] = "wait_for_name"
                        send_telegram_msg(ADMIN_CHAT_ID, f"🆔 已記錄 ID：<code>{text}</code>\n\n步驟 2/4：請輸入該客戶的 <b>店名或名稱</b>：")

                    elif step == "wait_for_name":
                        state["data"]["name"] = text
                        state["step"] = "wait_for_industry"
                        ind_markup = {
                            "inline_keyboard": [
                                [{"text": "💰 當舖融資", "callback_data": "ind_pawn"}, {"text": "🚗 中古車買賣", "callback_data": "ind_car"}],
                                [{"text": "🛡️ 保險規劃", "callback_data": "ind_insurance"}, {"text": "🌐 其他自訂產業", "callback_data": "ind_other"}]
                            ]
                        }
                        send_telegram_msg(ADMIN_CHAT_ID, f"👤 已記錄名稱：<b>{text}</b>\n\n請點擊選擇客戶的<b>產業類別</b>：", ind_markup)

                    elif step == "wait_for_custom_industry":
                        state["data"]["industry"] = text
                        state["step"] = "wait_for_duration"
                        duration_markup = {
                            "inline_keyboard": [
                                [{"text": "30 天 (月繳)", "callback_data": "dur_30"}, {"text": "90 天 (季繳)", "callback_data": "dur_90"}],
                                [{"text": "365 天 (年繳)", "callback_data": "dur_365"}]
                            ]
                        }
                        send_telegram_msg(ADMIN_CHAT_ID, f"🏢 已自訂產業：<b>{text}</b>\n\n步驟 3/4：請選擇合約有效期限：", duration_markup)

                    elif step == "wait_for_keywords":
                        keywords = [k.strip() for k in text.split(",") if k.strip()]
                        data = state["data"]
                        new_client_id = data["chat_id"]
                        
                        clients_dict = load_json(CLIENTS_FILE)
                        clients_dict[new_client_id] = {
                            "client_name": data["name"],
                            "industry": data["industry"],
                            "keywords": keywords,
                            "expire_date": data["expire_date"]
                        }
                        
                        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                            json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                            
                        send_telegram_msg(
                            ADMIN_CHAT_ID,
                            f"✅ <b>客戶新增成功並已即時生效！</b>\n"
                            f"👤 名稱：{data['name']}\n"
                            f"🆔 ID：{new_client_id}\n"
                            f"🏢 產業：{data['industry']}\n"
                            f"⏳ 到期：{data['expire_date']}\n"
                            f"🔍 關鍵字：{', '.join(keywords)}"
                        )
                        del admin_states[ADMIN_CHAT_ID]

                    elif step == "wait_for_new_keyword":
                        target_cid = state["target_cid"]
                        new_keywords = [k.strip() for k in text.split(",") if k.strip()]
                        clients_dict = load_json(CLIENTS_FILE)
                        if target_cid in clients_dict:
                            current_kw = clients_dict[target_cid].get("keywords", [])
                            for nk in new_keywords:
                                if nk not in current_kw:
                                    current_kw.append(nk)
                            clients_dict[target_cid]["keywords"] = current_kw
                            with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                                json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                            send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功新增關鍵字！目前該客戶的所有關鍵字為：\n{', '.join(current_kw)}")
                        del admin_states[ADMIN_CHAT_ID]

    except Exception as e:
        pass

# ----------------- 🕷️ 全域共享池爬蟲核心 (方案二) -----------------
async def run_global_pool_scraper():
    clients_dict = load_json(CLIENTS_FILE)
    if not clients_dict:
        print("❌ 目前沒有任何客戶設定。")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")

    active_clients = []
    for chat_id, info in clients_dict.items():
        expire_date = info.get("expire_date", "2099-12-31")
        if today_str > expire_date:
            renew_markup = {"inline_keyboard": [[{"text": "💳 立即聯繫續費", "url": f"t.me/{ADMIN_CHAT_ID}"}]]}
            expired_msg = f"⚠️ <b>【服務到期通知】</b>\n您的獲客雷達服務已於 <b>{expire_date}</b> 到期，系統已暫停推播。"
            send_telegram_msg(chat_id, expired_msg, renew_markup)
            continue
        
        active_clients.append({
            "chat_id": chat_id,
            "client_name": info.get("client_name"),
            "industry": info.get("industry"),
            "keywords": info.get("keywords", [])
        })

    if not active_clients:
        print("⚠️ 目前沒有任何合約有效的客戶正在運行。")
        return

    global_keywords_set = set()
    for c in active_clients:
        for kw in c["keywords"]:
            global_keywords_set.add(kw)

    print(f"📋 系統運作中：有效客戶 {len(active_clients)} 位 | 萃取出不重複關鍵字共 {len(global_keywords_set)} 個：{list(global_keywords_set)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        if os.path.exists("cookies.json"):
            with open("cookies.json", "r") as f:
                await context.add_cookies(json.load(f))

        page = await context.new_page()

        for keyword in global_keywords_set:
            search_url = f"https://www.threads.net/search?q={keyword}"
            print(f"🔍 全域共享池正在搜尋關鍵字: {keyword}")

            try:
                await page.goto(search_url, wait_until="networkidle")
                await page.wait_for_timeout(3000)

                try:
                    latest_tab = page.get_by_text("最新", exact=True)
                    if await latest_tab.is_visible():
                        await latest_tab.click()
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass

                post_elements = await page.query_selector_all('div[data-pressable-container="true"]')

                for el in post_elements:
                    text_content = await el.inner_text()
                    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                    if len(lines) < 2:
                        continue

                    author = lines[0]
                    full_text = " ".join(lines[1:])

                    post_url = ""
                    try:
                        link_el = await el.query_selector('a[href*="/post/"]')
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                post_url = href if href.startswith('http') else f"https://www.threads.net{href}"
                    except Exception:
                        pass
                    
                    if not post_url:
                        post_url = search_url

                    unique_id = post_url if post_url and "/post/" in post_url else f"{author}_{full_text[:50]}"
                    if unique_id in seen_posts:
                        continue

                    if any(k in full_text for k in ["借錢", "周轉", "急需", "當鋪", "當舖", "缺錢", "借款", "換現金", "融資", "買車", "車貸", "保險", "推薦", "諮詢"]):
                        seen_posts.add(unique_id)
                        save_seen_posts()

                        matches = analyze_post_for_multiple_clients(full_text, active_clients)

                        for match in matches:
                            target_chat_id = match.get("chat_id")
                            category = match.get("category", "未分類")
                            urgency = match.get("urgency", "中")
                            reason = match.get("reason", "")
                            reply_draft = match.get("reply_draft", "")

                            c_name = next((c["client_name"] for c in active_clients if c["chat_id"] == target_chat_id), "客戶")

                            tg_message = (
                                f"🎯 <b>【即時獲客雷達通知】</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📌 <b>需求分類：</b> #{category}\n"
                                f"🚨 <b>急迫程度：</b> {urgency}\n"
                                f"👤 <b>發文用戶：</b> {author}\n"
                                f"🔍 <b>命中全域關鍵字：</b> {keyword}\n\n"
                                f"📝 <b>貼文內容：</b>\n{full_text}\n\n"
                                f"💡 <b>AI 研判：</b> {reason}\n"
                                f"💬 <b>建議回覆草稿：</b>\n<i>{reply_draft}</i>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"🔗 <a href='{post_url}'>點擊前往 Threads 貼文立即聯繫</a>"
                            )

                            print(f"✨ 成功派發線索給客戶 [{c_name}] (ID: {target_chat_id})")
                            send_telegram_msg(target_chat_id, tg_message)
                            await asyncio.sleep(0.5)

            except Exception as e:
                print(f"⚠️ 爬取關鍵字 [{keyword}] 發生錯誤: {e}")
                continue
            await page.wait_for_timeout(2000)

        await browser.close()

# ----------------- 🌐 輕量 HTTP 健檢伺服器 (供 Render Web Service 驗證) -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def start_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

if __name__ == "__main__":
    print("🚀 SaaS 智慧獲客系統（全域共享池極速版）已啟動！")
    
    # 在背景啟動 HTTP 伺服器
    threading.Thread(target=start_health_check_server, daemon=True).start()
    
    while True:
        try:
            handle_telegram_updates()
            asyncio.run(run_global_pool_scraper())
            print("\n⏳ 本輪全域巡邏完畢，等待 15 分鐘...")
        except Exception as e:
            print(f"⚠️ 執行錯誤: {e}")
        time.sleep(900)
