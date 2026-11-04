cat << 'EOF' > bot_id_switch.py
import os
import sys
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
    is_on_home_page_a14,
    ensure_return_to_home_page_a14,
    double_click_storage_bars,
    click_gold_storage_3_times
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
# 2. SUPERCELL ID LIST BOX 2X VERIFIER (PDF PAGE 2)
# ==========================================

def _check_supercell_logo_once(img):
    """
    Single pass check for Supercell ID List Box (135, 150 to 2370, 1040):
    1. Checks blue background + white letters inside (335, 502) to (710, 518).
    2. Checks left blue panel vs right white list panel across divider x=1118.
    3. Runs OCR on (325, 465, 725, 550) looking for 'SUPERCELL' or 'S'-starting text.
    """
    w, h = img.size
    lx1, ly1, lx2, ly2 = ID_SWITCH_A14["SUPERCELL_LOGO_BOX"]

    blue_bg_px = 0
    white_txt_px = 0
    total_box_px = 0

    for y in range(max(0, ly1 - 8), min(h, ly2 + 8), 2):
        for x in range(max(0, lx1 - 8), min(w, lx2 + 8), 2):
            r, g, b = img.getpixel((x, y))
            total_box_px += 1
            if b > 95 and b > r + 25 and b > g + 15:
                blue_bg_px += 1
            elif r > 200 and g > 200 and b > 200 and (max(r, g, b) - min(r, g, b) <= 35):
                white_txt_px += 1

    # Check Divider Line x=1118 contrast (Left side Blue, Right side Light/White)
    div_x = ID_SWITCH_A14["DIVIDER_X"]
    left_blue_count = 0
    right_light_count = 0
    for sample_y in [250, 400, 550, 700, 850]:
        if sample_y < h:
            lr, lg, lb = img.getpixel((max(0, div_x - 120), sample_y))
            rr, rg, rb = img.getpixel((min(w - 1, div_x + 120), sample_y))
            if lb > lr + 20 and lb > 60:
                left_blue_count += 1
            if rr > 210 and rg > 210 and rb > 210:
                right_light_count += 1

    divider_valid = (left_blue_count >= 3 and right_light_count >= 3)
    pixel_logo_valid = (blue_bg_px >= 12 and white_txt_px >= 5) or (blue_bg_px >= 35 and divider_valid)

    # OCR Check on SUPERCELL logo region
    ox1, oy1, ox2, oy2 = ID_SWITCH_A14["SUPERCELL_LOGO_OCR_BOX"]
    crop = img.crop((ox1, oy1, ox2, oy2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    cw, ch = upscaled.size
    src = upscaled.load()

    ocr_matched = False
    ocr_read_str = ""
    for thresh in [185, 165]:
        bw = Image.new('L', (cw, ch), 255)
        dst = bw.load()
        for py in range(ch):
            for px in range(cw):
                r, g, b = src[px, py]
                if r > thresh and g > thresh and b > thresh:
                    dst[px, py] = 0
        padded = ImageOps.expand(bw, border=12, fill=255)
        txt = pytesseract.image_to_string(padded, config='--oem 3 --psm 7').strip()
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
    Re-verifies 2 times (as instructed) whether the bot is inside the Supercell ID List Box
    by checking the blue background, white 'SUPERCELL' text at (335, 502..710, 518), and x=1118 divider.
    """
    confirmations = 0
    for check_num in range(1, 3):
        cur_img = img if (check_num == 1 and img is not None) else get_screenshot()
        ok, ocr_txt, blue_px, white_px, div_ok = _check_supercell_logo_once(cur_img)
        if ok:
            confirmations += 1
            print(f" [✔] [ID LIST VERIFY #{check_num}/2] Supercell ID Box Confirmed (OCR='{ocr_txt}', Blue={blue_px}, White={white_px}, DividerX1118={div_ok})")
        else:
            print(f" [!] [ID LIST VERIFY #{check_num}/2] Not confirmed yet (OCR='{ocr_txt}', Blue={blue_px}, White={white_px}, DividerX1118={div_ok})")
        if check_num == 1:
            human_sleep(0.15, 0.04)

    return confirmations >= 1

# ==========================================
# 3. COC ID CARD POST-MORTEM SCANNER & OCR ENGINE
# ==========================================

def find_visible_coc_id_cards(img):
    """
    Uses the exact Post-Mortem geometry of Card #1 (1158, 209 to 2376, 434)
    and vertical center distance (563 - 321 = 242 px) to detect all visible white ID cards
    on the right side of divider x=1118.
    Returns a list of dicts:
      [{"slot": 1..4, "top": y1, "bottom": y2, "center_y": cy, "is_full": bool}, ...]
    """
    w, h = img.size
    card_x1, _, card_x2, _ = ID_SWITCH_A14["FIRST_CARD_BOX"]

    # Scan vertical strips in the clear white interior of the cards (avoiding text/avatars)
    scan_x_points = [1763, 2020, 2110]
    in_card = False
    card_top = 0
    raw_spans = []

    for y in range(160, min(h - 4, 1075), 2):
        white_hits = 0
        for sx in scan_x_points:
            r, g, b = img.getpixel((sx, y))
            # White card surface has RGB >= 248, while gray list background is ~235-242
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
        # Full card height is ~225 px (434 - 209 = 225). Half card at bottom is ~60-140 px.
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

    # Fallback to fixed blueprint slot geometry if pixel spans are obscured by volume bar etc.
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
    Reads the Supercell Unique ID Box for a card using the exact Post-Mortem coordinates:
    For Card #1 (top=209): (1350, 236) to (1940, 292) -> rel_y1 = +27, rel_y2 = +83.
    Supercell Unique IDs contain clean English letters & digits (e.g., 'Boiling Serene Rihan', 'NagiEmpiree').
    """
    w, h = img.size
    ux1 = ID_SWITCH_A14["UNIQUE_ID_BOX"][0]
    ux2 = ID_SWITCH_A14["UNIQUE_ID_BOX"][2]
    uy1 = max(0, card_top + ID_SWITCH_A14["UNIQUE_ID_REL_Y1"] - 3)
    uy2 = min(h, card_top + ID_SWITCH_A14["UNIQUE_ID_REL_Y2"] + 3)

    if uy2 - uy1 < 18:
        return ""

    crop = img.crop((ux1, uy1, ux2, uy2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    cw, ch = upscaled.size
    src = upscaled.load()

    best_read = ""
    for thresh in [115, 140]:
        bw = Image.new('L', (cw, ch), 255)
        dst = bw.load()
        for py in range(ch):
            for px in range(cw):
                r, g, b = src[px, py]
                # Unique ID is bold dark/black text on white card background
                if r < thresh and g < thresh and b < thresh:
                    dst[px, py] = 0
        padded = ImageOps.expand(bw, border=12, fill=255)
        cfg = '--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        raw = pytesseract.image_to_string(padded, config=cfg).strip()
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '', raw)
        if len(cleaned) > len(best_read):
            best_read = cleaned
        if len(best_read) >= 5:
            break

    return best_read

def read_town_hall_from_card(img, card_top):
    """
    Reads the Town Hall Box for a card using the Post-Mortem coordinates:
    For Card #1 (top=209): (1348, 360) to (1662, 396) -> rel_y1 = +151, rel_y2 = +187.
    """
    w, h = img.size
    tx1 = ID_SWITCH_A14["TOWN_HALL_BOX"][0]
    tx2 = ID_SWITCH_A14["TOWN_HALL_BOX"][2]
    ty1 = max(0, card_top + ID_SWITCH_A14["TH_REL_Y1"] - 2)
    ty2 = min(h, card_top + ID_SWITCH_A14["TH_REL_Y2"] + 2)

    if ty2 - ty1 < 14:
        return ""

    crop = img.crop((tx1, ty1, tx2, ty2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS).convert('L')
    bw = upscaled.point(lambda p: 0 if p < 165 else 255, '1').convert('L')
    padded = ImageOps.expand(bw, border=10, fill=255)
    txt = pytesseract.image_to_string(padded, config='--oem 3 --psm 7').strip()
    m = re.search(r'(\d{1,2})', txt)
    return m.group(1) if m else ""

def is_end_of_id_list_visible(img):
    """
    Checks if 'OTHER IDS' or 'Log in to Supercell ID' (from Screenshot 4) is visible
    at the bottom of the right panel, indicating the end of logged-in accounts.
    """
    w, h = img.size
    crop = img.crop((1350, max(0, h - 380), min(w, 2150), h - 20))
    gray = crop.convert('L')
    txt = pytesseract.image_to_string(gray, config='--oem 3 --psm 6').lower()
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
    Scans the full cards currently visible in the Switch ID list and attaches
    their Supercell Unique ID and Town Hall level.
    """
    cards = find_visible_coc_id_cards(img)
    enriched = []
    for c in cards:
        # Read OCR for full cards (or cards with enough vertical space for the Unique ID box)
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
    Follows the exact PDF Page 2 sequence to open the Supercell ID List Box (Optimized Time-Cutting):
      (i)   Click Profile (142, 122) -> 0.45s
      (ii)  Click Settings (1755, 92) -> 0.45s
      (iii) Click Switch Icon (1507, 207) -> 0.75s
    Then verifies the Supercell ID List Box twice (2x Verification).
    """
    for attempt in range(1, 4):
        check_pause_point(allow_raise=True)
        print(f"\n [ID SWITCH NAV] Opening Supercell ID List (Attempt #{attempt}/3)...")

        # Ensure no wrong popups are blocking Home Page before clicking Profile
        check_wrong_buttons_a14()

        # (i) Profile -> (142, 122)
        print(" [>] [STEP (i)] Clicking Profile Button (142, 122)...")
        tap(*ID_SWITCH_A14["PROFILE_BTN"], delay_range=(0.20, 0.35), jitter=3)
        human_sleep(0.45, 0.08)

        # (ii) Settings -> (1755, 92)
        print(" [>] [STEP (ii)] Clicking Settings Tab (1755, 92)...")
        tap(*ID_SWITCH_A14["SETTINGS_BTN"], delay_range=(0.20, 0.35), jitter=3)
        human_sleep(0.45, 0.08)

        # (iii) Switch Icon -> (1507, 207)
        print(" [>] [STEP (iii)] Clicking Switch ID Icon (1507, 207)...")
        tap(*ID_SWITCH_A14["SWITCH_ICON_BTN"], delay_range=(0.25, 0.40), jitter=3)
        human_sleep(0.75, 0.10)

        # Verify Supercell ID List Box 2 times!
        if verify_supercell_id_list_box_twice():
            return True

        print(" [!] Supercell ID List Box 2x verification failed. Retrying Switch Icon click...")
        tap(*ID_SWITCH_A14["SWITCH_ICON_BTN"], delay_range=(0.25, 0.40), jitter=3)
        human_sleep(0.85, 0.12)
        if verify_supercell_id_list_box_twice():
            return True

        # Reset back to Home Page before next attempt
        ensure_return_to_home_page_a14()
        human_sleep(0.55, 0.08)

    return False

def perform_smooth_id_list_scroll(scroll_num=1, total_scrolls=1):
    """
    Executes the exact smooth scroll from (1763, 1030) to (1763, 215)
    so that the 4th (half-visible) ID card moves cleanly to the 1st ID card position (1763, 321).
    Optimized: 750ms duration + 0.60s post_sleep.
    """
    check_pause_point(allow_raise=True)
    sx1, sy1 = ID_SWITCH_A14["SCROLL_START"]
    sx2, sy2 = ID_SWITCH_A14["SCROLL_END"]
    dur = ID_SWITCH_A14.get("SCROLL_DURATION_MS", 750)
    print(f" [v] [ID LIST SCROLL {scroll_num}/{total_scrolls}] Smooth scrolling ({sx1},{sy1} -> {sx2},{sy2}) [4th ID -> 1st Place]...")
    swipe(sx1, sy1, sx2, sy2, duration=dur, post_sleep=0.60)

def compute_scroll_and_slot_for_id(target_id_index):
    """
    Exact Mathematical Mapping based on the user's rule:
      - 3 full cards + 4th half card are visible initially.
      - Each smooth scroll (1763, 1030 -> 1763, 215) moves the 4th card to the 1st place (stride = 3 cards per scroll).
      - Therefore:
          * ID #1 -> 0 Scrolls, Slot 1 (1763, 321)
          * ID #2 -> 0 Scrolls, Slot 2 (1763, 563)
          * ID #3 -> 0 Scrolls, Slot 3 (1763, 800)
          * ID #4 -> 1 Scroll,  Slot 1 (1763, 321) [4th card moved to 1st place for 100% clean full-card click!]
          * ID #5 -> 1 Scroll,  Slot 2 (1763, 563)
          * ID #6 -> 1 Scroll,  Slot 3 (1763, 800)
          * ID #7 -> 2 Scrolls, Slot 1 (1763, 321)
          * General Formula for ID #N (N >= 1):
              scrolls_needed = (N - 1) // 3
              slot_index     = ((N - 1) % 3) + 1   (Always lands on Full Card Slot 1, 2, or 3!)
    """
    n = max(1, int(target_id_index))
    scrolls_needed = (n - 1) // 3
    slot_index = ((n - 1) % 3) + 1
    return scrolls_needed, slot_index

def _is_mode_5_id_only_active():
    """
    Detects if the bot is currently running in Mode 5 (ID Changement Only)
    by checking the caller stack (main_loop's bot_mode variable).
    """
    try:
        frame = sys._getframe(1)
        while frame:
            if "bot_mode" in frame.f_locals:
                return str(frame.f_locals["bot_mode"]).strip() == "5"
            frame = frame.f_back
    except Exception:
        pass
    return False

# ==========================================
# 5. MASTER ID SWITCH EXECUTION (SMART 5s+DYNAMIC LOAD: 15s IN MODE 5 / 30s IN OTHERS)
# ==========================================

def switch_to_target_id(target_id_index, total_ids, current_id_index=None, max_load_wait=None):
    """
    Switches from the current village to target_id_index (1 to total_ids, max 100).
    Combines:
      1. Exact 3-Card-Stride Smooth Scroll Math (4th card -> 1st place)
      2. Dynamic White Card Post-Mortem Scanner + Supercell Unique ID OCR Memory verification
      3. Smart Dynamic Loading Wait:
         - Starts checking Home Page (Green '+') after 5.0 seconds.
         - If Mode 5 (ID Changement Only) is selected: Maximum wait = 15.0 seconds.
         - In all other Modes (Mode 6, Mode 7, etc.): Maximum wait = 30.0 seconds.
      4. Home Page Green '+' & Wrong Button verification after load
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

    # Step 1: Open Supercell ID List Box & verify twice
    if not open_supercell_id_list_from_home():
        print(" [!] [ERROR] Could not open Supercell ID List Box! Staying on Home Page.")
        ensure_return_to_home_page_a14()
        return False

    # Step 2: Calculate exact scrolls & slot (4th card moves to 1st place on each scroll)
    scrolls_needed, expected_slot = compute_scroll_and_slot_for_id(target_id_index)
    print(f" [i] [SCROLL PLAN] Target ID #{target_id_index} ({role_str}) -> Smooth Scrolls: {scrolls_needed} | Expected Full Slot: #{expected_slot}")

    # If on Scroll 0, opportunistically record IDs #1, #2, #3 in memory
    if scrolls_needed == 0:
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

    # Step 3: Perform smooth scrolls (1763, 1030 -> 1763, 215)
    reached_end_early = False
    for s_i in range(1, scrolls_needed + 1):
        perform_smooth_id_list_scroll(s_i, scrolls_needed)

        # Re-verify that we are still inside the Supercell ID List Box every few scrolls
        if s_i == scrolls_needed or (s_i % 3 == 0):
            chk_img = get_screenshot()
            if not verify_supercell_id_list_box_twice(chk_img):
                print(" [!] Supercell ID List Box closed unexpectedly during scroll! Re-opening...")
                if not open_supercell_id_list_from_home():
                    return False
            if is_end_of_id_list_visible(chk_img) and s_i < scrolls_needed:
                print(" [!] [LIST END DETECTED] 'OTHER IDS / Log in' visible! Reached bottom of logged-in IDs.")
                reached_end_early = True
                break

    # Step 4: Scan visible cards on the target view & verify with Supercell Unique ID OCR Memory
    img_now = get_screenshot()
    visible_cards = scan_visible_cards_with_ocr(img_now)
    for c in visible_cards:
        if c["slot"] <= 3 or c["unique_id"]:
            print(f" [CARD SLOT #{c['slot']}] Center=(1763, {c['center_y']}) | UniqueID='{c['unique_id']}' | TH='{c['th']}' | Full={c['is_full']}")

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
    tap(chosen_click_x, chosen_click_y, delay_range=(0.25, 0.40), jitter=3)

    # Step 6: Smart Dynamic Village Loading Wait
    # - Mode 5 (ID Changement Only): 5s Initial Wait + Dynamic Screen Check up to 15s Max
    # - All Other Modes (Mode 6 / Mode 7): 5s Initial Wait + Dynamic Screen Check up to 30s Max
    initial_wait = float(ID_SWITCH_A14.get("ID_INITIAL_WAIT_SEC", 5.0))
    poll_interval = float(ID_SWITCH_A14.get("ID_POLL_INTERVAL_SEC", 1.5))

    if max_load_wait is not None:
        total_max_wait = float(max_load_wait)
    elif _is_mode_5_id_only_active():
        total_max_wait = 15.0
    else:
        total_max_wait = float(ID_SWITCH_A14.get("ID_LOAD_WAIT_SEC", 30.0))

    print(f" [SMART ID LOAD] Waiting initial {initial_wait:.0f}s before checking Home Screen (Max Wait: {total_max_wait:.0f}s)...")
    load_start_t = time.time()
    smart_sleep(initial_wait)

    loaded_early = False
    while (time.time() - load_start_t) < total_max_wait:
        check_pause_point(allow_raise=True)
        chk_img = get_screenshot()
        check_wrong_buttons_a14(chk_img)
        if is_on_home_page_a14(chk_img):
            elapsed_load = time.time() - load_start_t
            print(f" [✔] [FAST ID LOAD] ID #{target_id_index} Home Page (Green '+') detected in {elapsed_load:.1f}s!")
            loaded_early = True
            break
        rem_t = total_max_wait - (time.time() - load_start_t)
        if rem_t <= 0:
            break
        smart_sleep(min(poll_interval, rem_t))

    if not loaded_early:
        print(f" [i] [ID LOAD TIMEOUT] Reached {total_max_wait:.0f}s max load timer. Proceeding to Home Page check...")

    # Step 7: Post-Load Home Page Check & Popup Cleanup
    print(" [POST-SWITCH CHECK] Verifying Home Page (Green '+') & clearing any Wrong Buttons...")
    check_wrong_buttons_a14()
    if not is_on_home_page_a14():
        ensure_return_to_home_page_a14()
    else:
        double_click_storage_bars()

    print(f" [✔] [ID SWITCH COMPLETE] Now active on ID #{target_id_index} / {total_ids} [{role_str}] (UniqueID='{chosen_uid}')!\n")
    return True
EOF
