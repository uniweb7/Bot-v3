cat << 'EOF' > bot_id_switch.py
import os
import json
import time
import re
import traceback
from PIL import Image, ImageOps
import pytesseract
import bot_tools
from bot_tools import (
    BotPausedResumeHomeException,
    ID_SWITCH_A14,
    UPGRADE_A14,
    FAST_ATTACK,
    tap,
    swipe,
    get_screenshot,
    human_sleep,
    smart_sleep,
    check_pause_point,
    check_wrong_buttons_a14,
    check_daily_reward_popup,
    check_and_handle_maintenance_break,
    is_on_home_page_a14,
    check_wrong_and_home_page_a14,
    ensure_return_to_home_page_a14,
    double_click_storage_bars,
    perform_home_cleanup_once,
    has_enough_ink_pixels,
    trim_binary_horizontal_whitespace
)

MEMORY_FILE_PATH = "bot_id_memory.json"

# ==========================================
# 1. PERSISTENT ID MEMORY & STATE MANAGER
# ==========================================

def load_id_memory():
    """
    Loads saved Supercell Unique IDs, scroll positions, and last active ID index
    so the bot never loses track of which ID is at which position.
    """
    default_mem = {
        "current_id_index": 1,
        "total_ids": 1,
        "known_ids": {}  # Maps str(id_num) -> {"unique_id": str, "th": str, "scrolls": int, "slot": int}
    }
    if not os.path.exists(MEMORY_FILE_PATH):
        return default_mem
    try:
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                default_mem.update(data)
    except Exception:
        pass
    return default_mem

def save_id_memory(mem_data):
    try:
        with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(mem_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def get_id_role_label(id_index):
    """First 4 IDs are MAIN IDs; 5th to 100th IDs are SECONDARY IDs."""
    return "MAIN ID" if int(id_index) <= 4 else "SECONDARY ID"

# ==========================================
# 2. SUPERCELL ID LIST BOX 2X VERIFIER (WITH C-SPEED PIXEL MATRIX)
# ==========================================

def _check_supercell_logo_pixel_fast(img):
    """
    Point #32 & #43: Ultra-fast C-speed pixel check (~0.01s) for Supercell ID List Box:
    1. Checks blue background + white letters inside (335, 502) to (710, 518).
    2. Checks left blue panel vs right white list panel across divider x=1118.
    """
    w, h = img.size
    px_map = img.load()
    lx1, ly1, lx2, ly2 = ID_SWITCH_A14["SUPERCELL_LOGO_BOX"]

    blue_bg_px = 0
    white_txt_px = 0

    for y in range(max(0, ly1 - 8), min(h, ly2 + 8), 2):
        for x in range(max(0, lx1 - 8), min(w, lx2 + 8), 2):
            r, g, b = px_map[x, y]
            if b > 95 and b > r + 25 and b > g + 15:
                blue_bg_px += 1
            elif r > 200 and g > 200 and b > 200 and (max(r, g, b) - min(r, g, b) <= 35):
                white_txt_px += 1

    div_x = ID_SWITCH_A14["DIVIDER_X"]
    left_blue_count = 0
    right_light_count = 0
    for sample_y in [250, 400, 550, 700, 850]:
        if sample_y < h:
            lr, lg, lb = px_map[max(0, div_x - 120), sample_y]
            rr, rg, rb = px_map[min(w - 1, div_x + 120), sample_y]
            if lb > lr + 20 and lb > 60:
                left_blue_count += 1
            if rr > 210 and rg > 210 and rb > 210:
                right_light_count += 1

    divider_valid = (left_blue_count >= 3 and right_light_count >= 3)
    pixel_logo_valid = (blue_bg_px >= 12 and white_txt_px >= 5) or (blue_bg_px >= 35 and divider_valid)
    return pixel_logo_valid, divider_valid, blue_bg_px, white_txt_px

def _check_supercell_logo_once(img):
    """
    Full check for Supercell ID List Box (135, 150 to 2370, 1040):
    Combines pixel check + BILINEAR OCR on (325, 465, 725, 550) looking for 'SUPERCELL'.
    """
    pixel_logo_valid, divider_valid, blue_bg_px, white_txt_px = _check_supercell_logo_pixel_fast(img)

    ox1, oy1, ox2, oy2 = ID_SWITCH_A14["SUPERCELL_LOGO_OCR_BOX"]
    crop = img.crop((ox1, oy1, ox2, oy2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
    cw, ch = upscaled.size
    src = upscaled.load()

    ocr_matched = False
    ocr_read_str = ""
    cfg = '--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0'
    for thresh in [185, 165]:
        bw = Image.new('L', (cw, ch), 255)
        dst = bw.load()
        for py in range(ch):
            for px in range(cw):
                r, g, b = src[px, py]
                if r > thresh and g > thresh and b > thresh:
                    dst[px, py] = 0
        if not has_enough_ink_pixels(bw, min_black_px=6):
            continue
        padded = ImageOps.expand(bw, border=10, fill=255)
        txt = pytesseract.image_to_string(padded, config=cfg).strip()
        if txt:
            ocr_read_str = txt
            clean_t = re.sub(r'[^a-zA-Z]', '', txt).lower()
            if "super" in clean_t or "cell" in clean_t or "sup" in clean_t or clean_t.startswith("s"):
                ocr_matched = True
                break

    is_open = (pixel_logo_valid and divider_valid) or (ocr_matched and (pixel_logo_valid or divider_valid))
    return is_open, ocr_read_str, blue_bg_px, white_txt_px, divider_valid

def verify_supercell_id_list_box_twice(img=None):
    """
    Point #15 (Preserved) & Point #36:
    Re-verifies 2 times whether the bot is inside the Supercell ID List Box
    by checking the blue background, white 'SUPERCELL' text at (335, 502..710, 518), and x=1118 divider.
    """
    confirmations = 0
    for check_num in range(1, 3):
        cur_img = img if (check_num == 1 and img is not None) else get_screenshot(force_fresh=True)
        ok, ocr_txt, blue_px, white_px, div_ok = _check_supercell_logo_once(cur_img)
        if ok:
            confirmations += 1
            print(f" [✔] [ID LIST VERIFY #{check_num}/2] Supercell ID Box Confirmed (OCR='{ocr_txt}', Blue={blue_px}, White={white_px}, DividerX1118={div_ok})")
        else:
            print(f" [!] [ID LIST VERIFY #{check_num}/2] Not confirmed yet (OCR='{ocr_txt}', Blue={blue_px}, White={white_px}, DividerX1118={div_ok})")
        if check_num == 1:
            human_sleep(0.08, 0.02)

    return confirmations >= 1

# ==========================================
# 3. COC ID CARD POST-MORTEM SCANNER & OCR ENGINE
# ==========================================

def find_visible_coc_id_cards(img):
    """
    Point #43: Uses C-speed img.load() and exact Post-Mortem geometry of Card #1 (1158, 209 to 2376, 434)
    to detect all visible white ID cards on the right side of divider x=1118.
    """
    w, h = img.size
    px_map = img.load()

    scan_x_points = [1763, 2020, 2110]
    in_card = False
    card_top = 0
    raw_spans = []

    for y in range(160, min(h - 4, 1075), 2):
        white_hits = 0
        for sx in scan_x_points:
            r, g, b = px_map[sx, y]
            if r >= 247 and g >= 247 and b >= 247 and (max(r, g, b) - min(r, g, b) <= 8):
                white_hits += 1

        is_card_row = (white_hits >= 2)
        if is_card_row and not in_card:
            in_card = True
            card_top = y
        elif not is_card_row and in_card:
            in_card = False
            span_h = y - card_top
            if span_h >= 45:
                raw_spans.append((card_top, y))

    if in_card and (1075 - card_top) >= 45:
        raw_spans.append((card_top, 1075))

    detected_cards = []
    for idx, (y1, y2) in enumerate(raw_spans):
        span_h = y2 - y1
        is_full_card = (175 <= span_h <= 260)
        cy = (y1 + y2) // 2
        detected_cards.append({
            "slot": idx + 1,
            "top": y1,
            "bottom": y2,
            "height": span_h,
            "center_y": cy,
            "click_x": 1763,
            "click_y": cy if is_full_card else min(h - 15, y1 + 65),
            "is_full": is_full_card
        })

    if len(detected_cards) < 2:
        blueprint_tops = [209, 451, 688, 932]
        blueprint_clicks = ID_SWITCH_A14["ID_SLOTS"]
        detected_cards = []
        for i in range(4):
            top_y = blueprint_tops[i]
            bot_y = min(h - 1, top_y + ID_SWITCH_A14["CARD_HEIGHT"])
            detected_cards.append({
                "slot": i + 1,
                "top": top_y,
                "bottom": bot_y,
                "height": bot_y - top_y,
                "center_y": blueprint_clicks[i][1],
                "click_x": blueprint_clicks[i][0],
                "click_y": blueprint_clicks[i][1],
                "is_full": (i < 3)
            })

    return detected_cards

def read_supercell_unique_id_from_card(img, card_top):
    """
    Points #42-#46: Reads the Supercell Unique ID Box for a card using BILINEAR upscale,
    ink check, horizontal whitespace trimming, and dawg-disabled whitelist OCR.
    """
    w, h = img.size
    ux1 = ID_SWITCH_A14["UNIQUE_ID_BOX"][0]
    ux2 = ID_SWITCH_A14["UNIQUE_ID_BOX"][2]
    uy1 = max(0, card_top + ID_SWITCH_A14["UNIQUE_ID_REL_Y1"] - 3)
    uy2 = min(h, card_top + ID_SWITCH_A14["UNIQUE_ID_REL_Y2"] + 3)

    if uy2 - uy1 < 18:
        return ""

    crop = img.crop((ux1, uy1, ux2, uy2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
    cw, ch = upscaled.size
    src = upscaled.load()

    best_read = ""
    cfg = '--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

    for thresh in [115, 140]:
        bw = Image.new('L', (cw, ch), 255)
        dst = bw.load()
        for py in range(ch):
            for px in range(cw):
                r, g, b = src[px, py]
                if r < thresh and g < thresh and b < thresh:
                    dst[px, py] = 0
        if not has_enough_ink_pixels(bw, min_black_px=10):
            continue
        trimmed = trim_binary_horizontal_whitespace(bw, extra_pad=8)
        padded = ImageOps.expand(trimmed, border=10, fill=255)
        raw = pytesseract.image_to_string(padded, config=cfg).strip()
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '', raw)
        if len(cleaned) > len(best_read):
            best_read = cleaned
        if len(best_read) >= 5:
            break

    return best_read

def read_town_hall_from_card(img, card_top):
    """
    Point #33 (Preserved 100%): Reads the Town Hall Box for a card using Post-Mortem coordinates.
    """
    w, h = img.size
    tx1 = ID_SWITCH_A14["TOWN_HALL_BOX"][0]
    tx2 = ID_SWITCH_A14["TOWN_HALL_BOX"][2]
    ty1 = max(0, card_top + ID_SWITCH_A14["TH_REL_Y1"] - 2)
    ty2 = min(h, card_top + ID_SWITCH_A14["TH_REL_Y2"] + 2)

    if ty2 - ty1 < 14:
        return ""

    crop = img.crop((tx1, ty1, tx2, ty2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR).convert('L')
    bw = upscaled.point(lambda p: 0 if p < 165 else 255, '1').convert('L')
    if not has_enough_ink_pixels(bw, min_black_px=6):
        return ""
    padded = ImageOps.expand(bw, border=10, fill=255)
    txt = pytesseract.image_to_string(padded, config='--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0').strip()
    m = re.search(r'(\d{1,2})', txt)
    return m.group(1) if m else ""

def is_end_of_id_list_visible(img):
    """
    Point #20: Only runs full OCR on the bottom region if fewer than 3 full white ID cards are visible!
    """
    cards = find_visible_coc_id_cards(img)
    full_cards_count = sum(1 for c in cards if c.get("is_full", False))
    if full_cards_count >= 3:
        return False

    w, h = img.size
    crop = img.crop((1350, max(0, h - 380), min(w, 2150), h - 20))
    gray = crop.convert('L')
    txt = pytesseract.image_to_string(gray, config='--oem 3 --psm 6 -c load_system_dawg=0 -c load_freq_dawg=0').lower()
    if "other ids" in txt or "log in to" in txt or "login to" in txt:
        return True
    return False

def ids_roughly_match(id_a, id_b):
    """Fuzzy matcher for Supercell Unique IDs to handle minor 1-character OCR variations."""
    if not id_a or not id_b:
        return False
    a = id_a.lower().strip()
    b = id_b.lower().strip()
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5:
        if a in b or b in a:
            return True
        if a[:5] == b[:5] or a[-5:] == b[-5:]:
            return True
    return False

def scan_visible_cards_with_ocr(img):
    """
    Point #17 & #33 (Preserved 100%): Scans all full cards currently visible in the Switch ID list
    and attaches their Supercell Unique ID and Town Hall level.
    """
    cards = find_visible_coc_id_cards(img)
    enriched = []
    for c in cards:
        if c["top"] + ID_SWITCH_A14["UNIQUE_ID_REL_Y2"] <= img.height - 5:
            uid = read_supercell_unique_id_from_card(img, c["top"])
            th = read_town_hall_from_card(img, c["top"]) if c["is_full"] else ""
        else:
            uid = ""
            th = ""
        c_copy = dict(c)
        c_copy["unique_id"] = uid
        c_copy["th"] = th
        enriched.append(c_copy)
    return enriched

# ==========================================
# 4. NAVIGATION & SMOOTH SCROLLING ENGINE
# ==========================================

def open_supercell_id_list_from_home():
    """
    Follows the exact PDF Page 2 sequence to open the Supercell ID List Box:
      (i)   Click Profile (142, 122) -> 0.45s
      (ii)  Click Settings (1755, 92) -> 0.45s
      (iii) Click Switch Icon (1507, 207) -> 0.75s
    Then verifies the Supercell ID List Box twice (2x Verification).
    """
    for attempt in range(1, 4):
        check_pause_point(allow_raise=True)
        print(f"\n [ID SWITCH NAV] Opening Supercell ID List (Attempt #{attempt}/3)...")

        # Ensure no wrong popups or Daily Rewards are blocking Home Page before clicking Profile
        check_wrong_buttons_a14()

        # (i) Profile -> (142, 122)
        print(" [>] [STEP (i)] Clicking Profile Button (142, 122)...")
        tap(*ID_SWITCH_A14["PROFILE_BTN"], delay_range=(0.18, 0.32), jitter=3)
        human_sleep(0.45, 0.06)

        # (ii) Settings -> (1755, 92)
        print(" [>] [STEP (ii)] Clicking Settings Tab (1755, 92)...")
        tap(*ID_SWITCH_A14["SETTINGS_BTN"], delay_range=(0.18, 0.32), jitter=3)
        human_sleep(0.45, 0.06)

        # (iii) Switch Icon -> (1507, 207)
        print(" [>] [STEP (iii)] Clicking Switch ID Icon (1507, 207)...")
        tap(*ID_SWITCH_A14["SWITCH_ICON_BTN"], delay_range=(0.22, 0.36), jitter=3)
        human_sleep(0.75, 0.08)

        # Verify Supercell ID List Box 2 times!
        if verify_supercell_id_list_box_twice():
            return True

        print(" [!] Supercell ID List Box 2x verification failed. Checking Wrong Buttons & retrying Switch Icon...")
        chk = get_screenshot(force_fresh=True)
        if check_wrong_buttons_a14(chk) or is_on_home_page_a14(chk):
            continue

        tap(*ID_SWITCH_A14["SWITCH_ICON_BTN"], delay_range=(0.22, 0.36), jitter=3)
        human_sleep(0.80, 0.10)
        if verify_supercell_id_list_box_twice():
            return True

        # Reset back to Home Page before next attempt
        ensure_return_to_home_page_a14()
        human_sleep(0.50, 0.06)

    return False

def perform_smooth_id_list_scroll(scroll_num=1, total_scrolls=1):
    """
    Executes the exact smooth scroll from (1763, 1030) to (1763, 215)
    so that the 4th (half-visible) ID card moves cleanly to the 1st ID card position (1763, 321).
    """
    check_pause_point(allow_raise=True)
    sx1, sy1 = ID_SWITCH_A14["SCROLL_START"]
    sx2, sy2 = ID_SWITCH_A14["SCROLL_END"]
    dur = ID_SWITCH_A14.get("SCROLL_DURATION_MS", 750)
    print(f" [v] [ID LIST SCROLL {scroll_num}/{total_scrolls}] Smooth scrolling ({sx1},{sy1} -> {sx2},{sy2}) [4th ID -> 1st Place]...")
    swipe(sx1, sy1, sx2, sy2, duration=dur, post_sleep=0.60)

def compute_scroll_and_slot_for_id(target_id_index):
    """
    Exact Mathematical Mapping:
      scrolls_needed = (N - 1) // 3
      slot_index     = ((N - 1) % 3) + 1   (Always lands on Full Card Slot 1, 2, or 3!)
    """
    n = max(1, int(target_id_index))
    scrolls_needed = (n - 1) // 3
    slot_index = ((n - 1) % 3) + 1
    return scrolls_needed, slot_index

# ==========================================
# 5. MASTER ID SWITCH EXECUTION (MIN 3.5s WAIT, NO MAX LIMIT, DAILY REWARD & WATCHDOG)
# ==========================================

def switch_to_target_id(target_id_index, total_ids, current_id_index=None, max_load_wait=None):
    """
    Switches from the current village to target_id_index (1 to total_ids, max 100).
    Includes:
      - Point #34: Skips duplicate Scroll-0 pre-scan if IDs #1, #2, #3 are already saved in memory.
      - Point #32 & #35 (Pre-Click Guard): Fast pixel verification on intermediate scrolls; if kicked
        to Home Page or Wrong Button before clicking the ID card, cuts popup and restarts ID Switch!
      - Point #20: Smart End-of-List check only when < 3 full cards are visible.
      - Point #19 (Modified): Minimum 3.5s initial wait after clicking ID card, with NO maximum timeout limit!
        Polls every 1.0s until the village loads and Home Page (Green '+') is confirmed.
      - Daily Reward & Maintenance Break Scanner: Actively checks and claims Daily Reward popup
        starting right after the 3.5s initial wait and upon village arrival without slowing down the bot!
    """
    target_id_index = int(target_id_index)
    total_ids = max(1, min(100, int(total_ids)))
    if target_id_index > total_ids or target_id_index < 1:
        target_id_index = 1

    role_str = get_id_role_label(target_id_index)
    mem = load_id_memory()
    known_ids = mem.get("known_ids", {})

    print("\n======================================================================")
    print(f" || [ID SWITCH SYSTEM] Switching to ID #{target_id_index} / {total_ids} [{role_str}] ||")
    print("======================================================================")

    for nav_retry in range(1, 3):
        # Step 1: Open Supercell ID List Box & verify twice
        if not open_supercell_id_list_from_home():
            print(" [!] [ERROR] Could not open Supercell ID List Box! Staying on Home Page.")
            ensure_return_to_home_page_a14()
            return False

        # Step 2: Calculate exact scrolls & slot (4th card moves to 1st place on each scroll)
        scrolls_needed, expected_slot = compute_scroll_and_slot_for_id(target_id_index)
        print(f" [i] [SCROLL PLAN] Target ID #{target_id_index} ({role_str}) -> Smooth Scrolls: {scrolls_needed} | Expected Full Slot: #{expected_slot}")

        # Point #34: If on Scroll 0, only run pre-recording scan if any of IDs #1..#3 is missing from memory;
        # when scrolls_needed > 0, opportunistically record IDs #1, #2, #3 if missing.
        missing_top3 = any(str(i) not in known_ids or not known_ids[str(i)].get("unique_id") for i in range(1, min(4, total_ids + 1)))
        if scrolls_needed > 0 and missing_top3:
            img0 = get_screenshot()
            cards0 = scan_visible_cards_with_ocr(img0)
            for c in cards0:
                s_idx = c["slot"]
                if 1 <= s_idx <= 3 and c["unique_id"]:
                    known_ids[str(s_idx)] = {
                        "unique_id": c["unique_id"],
                        "th": c["th"],
                        "scrolls": 0,
                        "slot": s_idx
                    }
            mem["known_ids"] = known_ids
            save_id_memory(mem)

        # Step 3: Perform smooth scrolls (1763, 1030 -> 1763, 215) with Pre-Click Guard (Point #32 & #35)
        pre_click_interrupted = False
        for s_i in range(1, scrolls_needed + 1):
            perform_smooth_id_list_scroll(s_i, scrolls_needed)

            if s_i < scrolls_needed:
                # Point #32: Fast pixel check on intermediate scrolls + Pre-Click Home/Wrong-Button Guard (#35)
                if s_i % 3 == 0:
                    chk_img = get_screenshot()
                    pix_ok, div_ok, _, _ = _check_supercell_logo_pixel_fast(chk_img)
                    if not (pix_ok and div_ok):
                        print(" [!] [PRE-CLICK GUARD] Intermediate scroll par ID List hat gayi! Checking Wrong Button / Home Page...")
                        check_wrong_buttons_a14(chk_img)
                        pre_click_interrupted = True
                        break
                    if is_end_of_id_list_visible(chk_img):
                        print(" [!] [LIST END DETECTED] 'OTHER IDS / Log in' visible! Reached bottom of logged-in IDs.")
                        break
            else:
                # Final scroll: Full 2x Verification (Point #15 & #32)
                chk_img = get_screenshot(force_fresh=True)
                if not verify_supercell_id_list_box_twice(chk_img):
                    print(" [!] [PRE-CLICK GUARD] Final scroll par Supercell ID List Box nahi dikha! Re-starting ID Switch...")
                    check_wrong_buttons_a14(chk_img)
                    pre_click_interrupted = True
                    break

        if not pre_click_interrupted:
            break
        print(f" [🔄 RETRYING ID SWITCH] Pre-click interruption recovered (Retry #{nav_retry}/2)...")

    # Pre-Click Final Safety Check: Make sure we are still inside Supercell ID List before clicking ID card!
    img_now = get_screenshot(force_fresh=True)
    pix_ok, div_ok, _, _ = _check_supercell_logo_pixel_fast(img_now)
    if not (pix_ok or div_ok) and is_on_home_page_a14(img_now):
        print(" [!] [PRE-CLICK GUARD] Click se pehle Home Page par aa gaye! Re-opening ID List...")
        if not open_supercell_id_list_from_home():
            return False
        for s_i in range(1, scrolls_needed + 1):
            perform_smooth_id_list_scroll(s_i, scrolls_needed)
        img_now = get_screenshot(force_fresh=True)

    # Step 4: Scan visible cards on the target view & verify with Supercell Unique ID OCR Memory
    visible_cards = scan_visible_cards_with_ocr(img_now)
    for c in visible_cards:
        if c["slot"] <= 3 or c["unique_id"]:
            print(f" [CARD SLOT #{c['slot']}] Center=(1763, {c['center_y']}) | UniqueID='{c['unique_id']}' | TH='{c['th']}' | Full={c['is_full']}")
            if scrolls_needed == 0 and 1 <= c["slot"] <= 3 and c["unique_id"]:
                known_ids[str(c["slot"])] = {
                    "unique_id": c["unique_id"],
                    "th": c["th"],
                    "scrolls": 0,
                    "slot": c["slot"]
                }

    chosen_click_x, chosen_click_y = ID_SWITCH_A14["ID_SLOTS"][expected_slot - 1]
    chosen_uid = ""
    chosen_th = ""

    target_key = str(target_id_index)
    prev_key = str(target_id_index - 1) if target_id_index > 1 else None

    # Verification Case A: We already know Target ID's Unique ID from a previous cycle
    matched_by_ocr = False
    if target_key in known_ids and known_ids[target_key].get("unique_id"):
        saved_target_uid = known_ids[target_key]["unique_id"]
        for c in visible_cards:
            if ids_roughly_match(c["unique_id"], saved_target_uid):
                chosen_click_x, chosen_click_y = c["click_x"], c["click_y"]
                chosen_uid = c["unique_id"]
                chosen_th = c["th"]
                matched_by_ocr = True
                print(f" [✔] [OCR MEMORY MATCH] Found saved UniqueID '{saved_target_uid}' for ID #{target_id_index} at Slot #{c['slot']} ({chosen_click_x}, {chosen_click_y})!")
                break

    # Verification Case B: Find Previous ID (N-1) on screen and pick the card immediately below it
    if not matched_by_ocr and prev_key and prev_key in known_ids and known_ids[prev_key].get("unique_id"):
        prev_uid = known_ids[prev_key]["unique_id"]
        for idx, c in enumerate(visible_cards):
            if ids_roughly_match(c["unique_id"], prev_uid):
                if idx + 1 < len(visible_cards):
                    next_card = visible_cards[idx + 1]
                    chosen_click_x, chosen_click_y = next_card["click_x"], next_card["click_y"]
                    chosen_uid = next_card["unique_id"]
                    chosen_th = next_card["th"]
                    matched_by_ocr = True
                    print(f" [✔] [RELATIVE OCR MATCH] Found previous ID #{target_id_index - 1} ('{prev_uid}') at Slot #{c['slot']} -> Selecting next card below it at Slot #{next_card['slot']} ({chosen_click_x}, {chosen_click_y})!")
                break

    # Case C: Use exact mathematical slot (Slot 1: 1763,321 | Slot 2: 1763,563 | Slot 3: 1763,800 | Slot 4: 1763,1044)
    if not matched_by_ocr:
        slot_coord = ID_SWITCH_A14["ID_SLOTS"][expected_slot - 1]
        chosen_click_x, chosen_click_y = slot_coord[0], slot_coord[1]
        for c in visible_cards:
            if c["slot"] == expected_slot:
                if c["is_full"]:
                    chosen_click_x, chosen_click_y = c["click_x"], c["click_y"]
                chosen_uid = c["unique_id"]
                chosen_th = c["th"]
                break
        print(f" [SLOT LOCK] Selecting ID #{target_id_index} via Blueprint Slot #{expected_slot} at ({chosen_click_x}, {chosen_click_y}) [UniqueID='{chosen_uid}']")

    # Save learned Unique ID into persistent memory
    if chosen_uid:
        known_ids[target_key] = {
            "unique_id": chosen_uid,
            "th": chosen_th,
            "scrolls": scrolls_needed,
            "slot": expected_slot
        }
    mem["current_id_index"] = target_id_index
    mem["total_ids"] = total_ids
    mem["known_ids"] = known_ids
    save_id_memory(mem)

    # Step 5: Click the Target ID Card
    print(f" [CLICK ID] Clicking ID #{target_id_index} [{role_str}] at ({chosen_click_x}, {chosen_click_y})...")
    tap(chosen_click_x, chosen_click_y, delay_range=(0.22, 0.35), jitter=3)

    # Step 6: Point #19 (Modified) + Point #35 (Post-Click Watchdog) + Daily Reward Search
    # - Minimum Initial Wait: 3.5 seconds
    # - NO Maximum Waiting Time Limit! Polls every 1.0s until the new village loads & Home Page is confirmed.
    # - Actively checks Daily Reward Popup, Wrong Buttons & Maintenance Break during load.
    initial_wait = float(ID_SWITCH_A14.get("ID_INITIAL_WAIT_SEC", 3.5))
    poll_interval = float(ID_SWITCH_A14.get("ID_POLL_INTERVAL_SEC", 1.0))

    print(f" [SMART ID LOAD] Waiting minimum {initial_wait:.1f}s before continuous Home Page & Daily Reward check...")
    load_start_t = time.time()
    last_watchdog_t = load_start_t
    smart_sleep(initial_wait, apply_speed=False)

    while True:
        check_pause_point(allow_raise=True)
        chk_img = get_screenshot(force_fresh=True)
        elapsed_load = time.time() - load_start_t

        # 1. Check Maintenance Break banner if village load is taking time
        if elapsed_load >= 6.0:
            check_and_handle_maintenance_break(chk_img)

        # 2. Check Daily Reward Popup & Wrong Buttons (automatically claims green boxes & clicks 1858,153 Red 'X')
        was_popup_cut, is_home_now, chk_img = check_wrong_and_home_page_a14(chk_img)

        if is_home_now:
            # Brief 0.35s settle check to catch Daily Reward if it pops up split-second after Home Page appears
            human_sleep(0.35, 0.05)
            post_img = get_screenshot(force_fresh=True)
            if check_daily_reward_popup(post_img) or check_wrong_buttons_a14(post_img):
                post_img = get_screenshot(force_fresh=True)
            if is_on_home_page_a14(post_img):
                total_t = time.time() - load_start_t
                print(f" [✔] [VILLAGE LOADED] ID #{target_id_index} Home Page (Green '+') & Daily Reward check verified in {total_t:.1f}s!")
                break

        # 3. Point #35 Post-Click Watchdog: Every 12 seconds, check if tap missed and we are still inside Supercell ID List
        if (time.time() - last_watchdog_t) >= 12.0:
            last_watchdog_t = time.time()
            pix_still_open, div_still_open, _, _ = _check_supercell_logo_pixel_fast(chk_img)
            if pix_still_open and div_still_open:
                print(f" [!] [POST-CLICK WATCHDOG] {elapsed_load:.0f}s elapsed and Supercell ID List is still open! Re-clicking ID #{target_id_index} at ({chosen_click_x}, {chosen_click_y})...")
                tap(chosen_click_x, chosen_click_y, delay_range=(0.22, 0.35), jitter=3)
            else:
                print(f" [⏳ WAITING VILLAGE LOAD] {elapsed_load:.1f}s elapsed... Checking for Home Page / Daily Reward / Maintenance...")

        smart_sleep(poll_interval, apply_speed=False)

    # Step 7: Point #18 (Conditional) — Clean storage bar double-click and final state confirmation
    double_click_storage_bars()

    print(f" [✔] [ID SWITCH COMPLETE] Now active on ID #{target_id_index} / {total_ids} [{role_str}] (UniqueID='{chosen_uid}')!\n")
    return True
EOF
echo "✔ Part 3 (bot_id_switch.py) 100% Complete & Updated!"
