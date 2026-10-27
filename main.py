import asyncio
import os
import json
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from openai import OpenAI
from aiohttp import web
import aiohttp

# ----------------- 🛠️ 全域參數設定區 -----------------
OPENAI_API_KEY = "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"
BOT_TOKEN = "8936011094:AAEhPR3FSgVYp2ZtNe3zWpxXb2MxqrP2r4Q"
ADMIN_CHAT_ID = "5681949363"  # 管理員 Telegram ID
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

# ----------------- 📲 非同步 Telegram 發送訊息 -----------------
async def send_telegram_msg(chat_id: str, text: str, reply_markup=None):
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                pass
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")

# ----------------- 🔘 非同步 Telegram 互動與管理員控制台 -----------------
async def handle_telegram_updates():
    global admin_states
    offset = -1
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        for result in res.get("result", []):
                            offset = result["update_id"] + 1
                            
                            # 1. 處理按鈕點擊 (Callback Query)
                            if "callback_query" in result:
                                query = result["callback_query"]
                                chat_id = str(query["message"]["chat"]["id"])
                                data = query["data"]
                                
                                # 立即消除轉圈
                                async with aiohttp.ClientSession() as s:
                                    await s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": query["id"]})
                                
                                if data == "check_status":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    client_info = clients_dict.get(chat_id, {})
                                    status_text = f"🟢 <b>系統運行正常</b>\n👤 客戶：{client_info.get('client_name', '未知')}\n⏳ 到期：{client_info.get('expire_date', '無')}"
                                    await send_telegram_msg(chat_id, status_text)

                                elif data == "view_keywords":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    client_info = clients_dict.get(chat_id, {})
                                    kw = ", ".join(client_info.get('keywords', []))
                                    await send_telegram_msg(chat_id, f"📌 <b>您目前的專屬關鍵字：</b>\n{kw}")

                                elif chat_id == ADMIN_CHAT_ID and data == "admin_list_clients":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if not clients_dict:
                                        await send_telegram_msg(ADMIN_CHAT_ID, "📋 目前系統中沒有任何客戶。")
                                    else:
                                        list_text = "📋 <b>【現有客戶列表】</b>\n━━━━━━━━━━\n"
                                        for cid, info in clients_dict.items():
                                            list_text += f"👤 <b>{info.get('client_name')}</b>\n🆔 ID: <code>{cid}</code>\n🏢 產業: {info.get('industry')}\n⏳ 到期: {info.get('expire_date')}\n🔍 關鍵字: {', '.join(info.get('keywords', []))}\n━━━━━━━━━━\n"
                                        await send_telegram_msg(ADMIN_CHAT_ID, list_text)

                                elif chat_id == ADMIN_CHAT_ID and data == "start_add_client":
                                    admin_states[ADMIN_CHAT_ID] = {"step": "wait_for_id", "data": {}}
                                    await send_telegram_msg(ADMIN_CHAT_ID, "➕ <b>【新增客戶精靈】</b>\n步驟 1/4：請輸入新客戶的 <b>Telegram Chat ID</b>：")

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("ind_"):
                                    if data == "ind_other":
                                        admin_states[ADMIN_CHAT_ID]["step"] = "wait_for_custom_industry"
                                        await send_telegram_msg(ADMIN_CHAT_ID, "🌐 請直接傳送您想設定的<b>自訂產業名稱</b>：")
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
                                            await send_telegram_msg(ADMIN_CHAT_ID, f"🏢 已選擇產業：<b>{selected_industry}</b>\n\n步驟 3/4：請選擇合約有效期限：", duration_markup)

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("dur_"):
                                    days_map = {"dur_30": 30, "dur_90": 90, "dur_365": 365}
                                    days = days_map.get(data, 30)
                                    if ADMIN_CHAT_ID in admin_states and admin_states[ADMIN_CHAT_ID]["step"] == "wait_for_duration":
                                        expire_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
                                        admin_states[ADMIN_CHAT_ID]["data"]["expire_date"] = expire_date
                                        admin_states[ADMIN_CHAT_ID]["step"] = "wait_for_keywords"
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"⏳ 有效期：{days} 天 (到期日: <code>{expire_date}</code>)\n\n步驟 4/4：請輸入要監控的<b>關鍵字</b>（用逗號隔開）：")

                                elif chat_id == ADMIN_CHAT_ID and data == "admin_keyword_menu":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if not clients_dict:
                                        await send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶資料。")
                                    else:
                                        buttons = [[{"text": f"🎯 管理【{info.get('client_name')}】的關鍵字", "callback_data": f"kw_manage_{cid}"}] for cid, info in clients_dict.items()]
                                        await send_telegram_msg(ADMIN_CHAT_ID, "✏️ <b>【關鍵字管理】</b>\n請選擇要為哪位客戶調整關鍵字：", {"inline_keyboard": buttons})

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_manage_"):
                                    target_cid = data.replace("kw_manage_", "")
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if target_cid in clients_dict:
                                        client_info = clients_dict[target_cid]
                                        keywords = client_info.get("keywords", [])
                                        kw_text = f"🎯 客戶：<b>{client_info.get('client_name')}</b>\n📌 目前關鍵字：\n" + "\n".join([f"{i+1}. {kw}" for i, kw in enumerate(keywords)])
                                        action_markup = {
                                            "inline_keyboard": [
                                                [{"text": "➕ 新增關鍵字", "callback_data": f"kw_add_{target_cid}"}],
                                                [{"text": "🗑️ 刪除特定關鍵字", "callback_data": f"kw_del_menu_{target_cid}"}]
                                            ]
                                        }
                                        await send_telegram_msg(ADMIN_CHAT_ID, kw_text, action_markup)

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_add_"):
                                    target_cid = data.replace("kw_add_", "")
                                    admin_states[ADMIN_CHAT_ID] = {"step": "wait_for_new_keyword", "target_cid": target_cid}
                                    await send_telegram_msg(ADMIN_CHAT_ID, "➕ 請傳送您想新增的關鍵字：")

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_del_menu_"):
                                    target_cid = data.replace("kw_del_menu_", "")
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if target_cid in clients_dict:
                                        keywords = clients_dict[target_cid].get("keywords", [])
                                        buttons = [[{"text": f"❌ 刪除：{kw}", "callback_data": f"kw_remove_{target_cid}_{idx}"}] for idx, kw in enumerate(keywords)]
                                        await send_telegram_msg(ADMIN_CHAT_ID, "🗑️ 請點擊你想刪除的關鍵字：", {"inline_keyboard": buttons})

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("kw_remove_"):
                                    parts = data.replace("kw_remove_", "").split("_")
                                    target_cid, kw_index = parts[0], int(parts[1])
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if target_cid in clients_dict:
                                        keywords = clients_dict[target_cid].get("keywords", [])
                                        if 0 <= kw_index < len(keywords):
                                            removed_kw = keywords.pop(kw_index)
                                            clients_dict[target_cid]["keywords"] = keywords
                                            with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                                                json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                                            await send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功刪除關鍵字：<b>{removed_kw}</b>！")

                                elif chat_id == ADMIN_CHAT_ID and data == "admin_extend_menu":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if not clients_dict:
                                        await send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶可供延期。")
                                    else:
                                        buttons = [[{"text": f"⏳ 幫【{info.get('client_name')}】延長 30 天", "callback_data": f"ext_{cid}"}] for cid, info in clients_dict.items()]
                                        await send_telegram_msg(ADMIN_CHAT_ID, "⏳ <b>【一鍵延期管理】</b>\n請選擇要幫哪位客戶延長 30 天合約：", {"inline_keyboard": buttons})

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
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功幫【{client_info.get('client_name')}】延長 30 天！\n新到期日為：<b>{new_expire}</b>")

                                elif chat_id == ADMIN_CHAT_ID and data == "admin_delete_menu":
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if not clients_dict:
                                        await send_telegram_msg(ADMIN_CHAT_ID, "📋 目前沒有客戶可供刪除。")
                                    else:
                                        buttons = [[{"text": f"❌ 刪除: {info.get('client_name')}", "callback_data": f"del_{cid}"}] for cid, info in clients_dict.items()]
                                        await send_telegram_msg(ADMIN_CHAT_ID, "⚠️ <b>【停權/刪除客戶】</b>\n請點擊你想移除的客戶：", {"inline_keyboard": buttons})

                                elif chat_id == ADMIN_CHAT_ID and data.startswith("del_"):
                                    target_cid = data.replace("del_", "")
                                    clients_dict = load_json(CLIENTS_FILE)
                                    if target_cid in clients_dict:
                                        removed_name = clients_dict[target_cid].get("client_name")
                                        del clients_dict[target_cid]
                                        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                                            json.dump(clients_dict, f, ensure_ascii=False, indent=2)
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"✅ 已成功將客戶【{removed_name}】自系統中移除！")

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
                                    await send_telegram_msg(ADMIN_CHAT_ID, "🛠️ <b>【SaaS 獲客系統 - 管理員控制台】</b>\n請選擇您要執行的管理動作：", admin_markup)

                                elif chat_id == ADMIN_CHAT_ID and ADMIN_CHAT_ID in admin_states:
                                    state = admin_states[ADMIN_CHAT_ID]
                                    step = state["step"]

                                    if step == "wait_for_id":
                                        state["data"]["chat_id"] = text
                                        state["step"] = "wait_for_name"
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"🆔 已記錄 ID：<code>{text}</code>\n\n步驟 2/4：請輸入該客戶的 <b>店名或名稱</b>：")

                                    elif step == "wait_for_name":
                                        state["data"]["name"] = text
                                        state["step"] = "wait_for_industry"
                                        ind_markup = {
                                            "inline_keyboard": [
                                                [{"text": "💰 當舖融資", "callback_data": "ind_pawn"}, {"text": "🚗 中古車買賣", "callback_data": "ind_car"}],
                                                [{"text": "🛡️ 保險規劃", "callback_data": "ind_insurance"}, {"text": "🌐 其他自訂產業", "callback_data": "ind_other"}]
                                            ]
                                        }
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"👤 已記錄名稱：<b>{text}</b>\n\n請點擊選擇客戶的<b>產業類別</b>：", ind_markup)

                                    elif step == "wait_for_custom_industry":
                                        state["data"]["industry"] = text
                                        state["step"] = "wait_for_duration"
                                        duration_markup = {
                                            "inline_keyboard": [
                                                [{"text": "30 天 (月繳)", "callback_data": "dur_30"}, {"text": "90 天 (季繳)", "callback_data": "dur_90"}],
                                                [{"text": "365 天 (年繳)", "callback_data": "dur_365"}]
                                            ]
                                        }
                                        await send_telegram_msg(ADMIN_CHAT_ID, f"🏢 已自訂產業：<b>{text}</b>\n\n步驟 3/4：請選擇合約有效期限：", duration_markup)

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
                                        await send_telegram_msg(
                                            ADMIN_CHAT_ID,
                                            f"✅ <b>客戶新增成功並已即時生效！</b>\n👤 名稱：{data['name']}\n🆔 ID：{new_client_id}"
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
                                            await send_telegram_msg(ADMIN_CHAT_ID, f"✅ 成功新增關鍵字！")
                                        del admin_states[ADMIN_CHAT_ID]
        except Exception as e:
            await asyncio.sleep(3)

# ----------------- 🕷️ 背景爬蟲排程核心 -----------------
async def run_global_pool_scraper_loop():
    while True:
        try:
            clients_dict = load_json(CLIENTS_FILE)
            if clients_dict:
                today_str = datetime.now().strftime("%Y-%m-%d")
                active_clients = []
                for chat_id, info in clients_dict.items():
                    if today_str > info.get("expire_date", "2099-12-31"):
                        continue
                    active_clients.append({
                        "chat_id": chat_id,
                        "client_name": info.get("client_name"),
                        "industry": info.get("industry"),
                        "keywords": info.get("keywords", [])
                    })

                if active_clients:
                    global_keywords_set = set(kw for c in active_clients for kw in c["keywords"])
                    print(f"🔍 開始執行背景爬蟲，監控關鍵字：{list(global_keywords_set)}")

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context()
                        if os.path.exists("cookies.json"):
                            with open("cookies.json", "r") as f:
                                await context.add_cookies(json.load(f))
                        page = await context.new_page()

                        for keyword in global_keywords_set:
                            try:
                                await page.goto(f"https://www.threads.net/search?q={keyword}", wait_until="networkidle")
                                await page.wait_for_timeout(3000)
                                post_elements = await page.query_selector_all('div[data-pressable-container="true"]')

                                for el in post_elements:
                                    text_content = await el.inner_text()
                                    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                                    if len(lines) < 2:
                                        continue
                                    author, full_text = lines[0], " ".join(lines[1:])
                                    
                                    post_url = ""
                                    try:
                                        link_el = await el.query_selector('a[href*="/post/"]')
                                        if link_el:
                                            href = await link_el.get_attribute("href")
                                            post_url = href if href.startswith('http') else f"https://www.threads.net{href}"
                                    except Exception:
                                        pass

                                    unique_id = post_url if post_url and "/post/" in post_url else f"{author}_{full_text[:50]}"
                                    if unique_id in seen_posts:
                                        continue

                                    if any(k in full_text for k in ["借錢", "週轉", "急需", "當鋪", "當舖", "缺錢", "借款", "換現金", "融資"]):
                                        seen_posts.add(unique_id)
                                        save_seen_posts()
                                        matches = analyze_post_for_multiple_clients(full_text, active_clients)

                                        for match in matches:
                                            tg_message = (
                                                f"🎯 <b>【即時獲客雷達通知】</b>\n"
                                                f"📌 需求：#{match.get('category')}\n"
                                                f"👤 用戶：{author}\n"
                                                f"📝 內容：\n{full_text}\n\n"
                                                f"💡 AI建議：<i>{match.get('reply_draft')}</i>\n"
                                                f"🔗 <a href='{post_url or 'https://www.threads.net'}'>點擊前往聯繫</a>"
                                            )
                                            await send_telegram_msg(match.get("chat_id"), tg_message)
                                            await asyncio.sleep(0.5)
                            except Exception as e:
                                print(f"⚠️ 爬取錯誤: {e}")
                        await browser.close()
        except Exception as e:
            print(f"⚠️ 爬蟲循環錯誤: {e}")
        
        await asyncio.sleep(900) # 每15分鐘執行一次

# ----------------- 🌐 輕量 HTTP 健檢伺服器 -----------------
async def handle_health(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ----------------- 🚀 主程式非同步啟動 -----------------
async def main():
    print("🚀 SaaS 智慧獲客系統（非同步極速版）正式啟動！")
    await start_web_server()
    await asyncio.gather(
        handle_telegram_updates(),
        run_global_pool_scraper_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
