
import time
import re
import random
import traceback
from PIL import Image, ImageOps
import pytesseract
import bot_tools
from bot_tools import *

# Tracks whether any building or wall was upgraded in the current loop call
LAST_UPGRADE_SUCCESS = False
LAST_BUILDING_UPGRADED = False
LAST_WALL_UPGRADED = False
_LAST_WALL_AFTER_IMG = None

# ==========================================
# 1. CARD DETECTION, LAST-PAGE DETECTOR & DUAL-CROP LANCZOS OCR ENGINE
# ==========================================

def is_tan_card_background(r, g, b):
    if g > r + 8:
        return False
    return (142 <= r <= 225) and (118 <= g <= 200) and (88 <= b <= 172) and (r > g > b)

def find_cards_in_upgrade_list(img):
    """Detects individual upgrade card vertical spans (c_top, c_bot) inside (1820, 545, 2312, 926)."""
    lx1, ly1, lx2, ly2 = UPGRADE_A14["UPGRADE_LIST_BOX"]
    px_map = img.load()
    cards = []
    in_card = False
    card_top = 0

    for y in range(ly1 + 2, ly2 - 2, 1):
        r1, g1, b1 = px_map[2130, y]
        r2, g2, b2 = px_map[2000, y]
        is_tan = is_tan_card_background(r1, g1, b1) and is_tan_card_background(r2, g2, b2)

        if is_tan and not in_card:
            in_card = True
            card_top = y
        elif not is_tan and in_card:
            in_card = False
            ch = y - card_top
            if 48 <= ch <= 105:
                cards.append((card_top, y))
            elif ch > 105:
                n_cards = max(2, round(ch / 81.0))
                step = ch // n_cards
                for i in range(n_cards):
                    cards.append((card_top + i * step, min(y, card_top + (i + 1) * step)))

    if in_card:
        ch = (ly2 - 2) - card_top
        if 48 <= ch <= 105:
            cards.append((card_top, ly2 - 2))
        elif ch > 105:
            n_cards = max(2, round(ch / 81.0))
            step = ch // n_cards
            for i in range(n_cards):
                cards.append((card_top + i * step, min(ly2 - 2, card_top + (i + 1) * step)))

    return cards

def capture_upgrade_list_fingerprint(img):
    """Samples pixels across the Upgrade List Box to help detect when scrolling hits the bottom."""
    if img is None:
        return None
    px_map = img.load()
    lx1, ly1, lx2, ly2 = UPGRADE_A14["UPGRADE_LIST_BOX"]
    samples = []
    for sy in range(ly1 + 20, ly2 - 20, 14):
        for sx in range(lx1 + 25, lx2 - 25, 30):
            samples.append(px_map[sx, sy])
    return samples

def is_same_upgrade_list_page(fp_before, fp_after, diff_threshold=9.5):
    """Returns True if pixel fingerprint before and after swipe is nearly identical."""
    if not fp_before or not fp_after or len(fp_before) != len(fp_after):
        return False
    total_diff = 0
    n = len(fp_before)
    for (r1, g1, b1), (r2, g2, b2) in zip(fp_before, fp_after):
        total_diff += (abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)) / 3.0
    mean_diff = total_diff / float(n)
    return mean_diff <= diff_threshold

def is_upgrade_list_open_a14(img=None):
    """Checks if the Upgrade Menu (Close button at 2322, 45) OR Upgrade List cards are visible."""
    if img is None:
        img = get_screenshot()
    if is_red_x_box_at(img, *UPGRADE_A14["CLOSE_MENU"], radius=14):
        return True
    cards = find_cards_in_upgrade_list(img)
    return len(cards) > 0

def ensure_upgrade_list_is_open(img=None):
    """
    Only opens the Upgrade Menu if it is actually closed.
    NEVER clicks (2233, 948) if the menu is already open!
    """
    if img is None:
        img = get_screenshot()
    if is_upgrade_list_open_a14(img):
        return img

    print(" [*] [LIST GUARD] Upgrade List dikh nahi rahi. (2050, 56) / (2233, 948) se open kar rahe hain...")
    tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.20, 0.32), jitter=3)
    human_sleep(0.42, 0.05)
    img = get_screenshot(force_fresh=True)
    if not is_upgrade_list_open_a14(img):
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.22, 0.35), jitter=3)
        human_sleep(0.50, 0.06)
        img = get_screenshot(force_fresh=True)
    return img

def _ocr_card_box_region(img, x1, y1, x2, y2, thresh=178, psm=7):
    crop = img.crop((x1, y1, x2, y2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    w, h = upscaled.size
    src = upscaled.load()

    bw = Image.new('L', (w, h), 255)
    dst = bw.load()
    ink_count = 0
    for py in range(h):
        for px in range(w):
            r, g, b = src[px, py]
            if r > thresh and g > thresh and b > thresh and (max(r, g, b) - min(r, g, b) <= 40):
                dst[px, py] = 0
                ink_count += 1

    if ink_count < 8:
        return ""
    padded = ImageOps.expand(bw, border=12, fill=255)
    return pytesseract.image_to_string(padded, config=f'--oem 3 --psm {psm}').strip()

def read_card_name_a14(img, card_top, card_bottom, thresh=178):
    """
    Dual-Crop LANCZOS 2x OCR:
    1. Reads full name box (1823..2124).
    2. If the result is empty or very short (e.g. standalone single 'Wall' without 'x100'),
       also reads the focused left name box (1823..1975) so single 'Wall' is NEVER missed!
    """
    nx1 = CARD_GEOMETRY["NAME_X1"]
    nx2 = CARD_GEOMETRY["NAME_X2"]
    ny1 = max(0, card_top + CARD_GEOMETRY["NAME_DY1"] - 2)
    ny2 = min(img.height, card_top + CARD_GEOMETRY["NAME_DY2"] + 4)

    full_txt = _ocr_card_box_region(img, nx1, ny1, nx2, ny2, thresh=thresh, psm=7)
    clean_full = re.sub(r'[^a-zA-Z0-9]', '', full_txt)
    if len(clean_full) >= 3:
        return full_txt

    # Focused left-box fallback for short standalone words like single 'Wall'
    short_nx2 = min(nx2, nx1 + 150)
    short_txt = _ocr_card_box_region(img, nx1, ny1, short_nx2, ny2, thresh=thresh, psm=8)
    return short_txt if len(re.sub(r'[^a-zA-Z0-9]', '', short_txt)) > len(clean_full) else full_txt

def verify_card_is_wall_carefully(img, card_top, card_bottom):
    """
    Enhanced Single-Wall & Multi-Wall Verifier:
    1. Checks full card name box at thresh=178.
    2. Checks focused left-side single-word box (1823..1975) so standalone 'Wall' (without xN)
       is detected with 100% accuracy!
    3. Re-verifies across thresholds [162, 190] whenever needed.
    """
    raw_1 = read_card_name_a14(img, card_top, card_bottom, thresh=178)
    if is_text_matching_wall(raw_1):
        print(f" [✔] [WALL VERIFIED] Reading '{raw_1}' -> Confirmed 'Wall'!")
        return True, raw_1

    cleaned_1 = re.sub(r'[^a-zA-Z0-9\s]', '', raw_1).strip()
    starts_like_wall = cleaned_1.lower().startswith(('w', 'v', 'i', 'l')) or len(cleaned_1) <= 5

    if not starts_like_wall:
        return False, raw_1

    # Focused left crop (1823..1975) specifically for standalone Single Wall ('Wall')
    nx1 = CARD_GEOMETRY["NAME_X1"]
    short_nx2 = nx1 + 152
    ny1 = max(0, card_top + CARD_GEOMETRY["NAME_DY1"] - 2)
    ny2 = min(img.height, card_top + CARD_GEOMETRY["NAME_DY2"] + 4)

    readings = [raw_1]
    for extra_thresh in [162, 190, 174]:
        raw_full = _ocr_card_box_region(img, nx1, ny1, CARD_GEOMETRY["NAME_X2"], ny2, thresh=extra_thresh, psm=7)
        if raw_full:
            readings.append(raw_full)
        if is_text_matching_wall(raw_full):
            print(f" [✔] [WALL RE-VERIFIED] Readings {readings} -> Confirmed 'Wall'!")
            return True, raw_full

        raw_short = _ocr_card_box_region(img, nx1, ny1, short_nx2, ny2, thresh=extra_thresh, psm=8)
        if raw_short:
            readings.append(raw_short)
        if is_text_matching_wall(raw_short):
            print(f" [✔] [SINGLE WALL VERIFIED] Readings {readings} -> Confirmed Single 'Wall'!")
            return True, raw_short

    return False, raw_1

def check_card_cost_color_a14(img, card_top, card_bottom):
    """
    RED-FIRST PRIORITY VETO + DIGIT-ONLY COST SCANNER:
      1. Scans ONLY the cost digits region (x = 2108..2252, excluding the resource icon at 2260..2313
         which has white border highlights even when the cost numbers are RED!).
      2. Checks RED pixels FIRST! If red_px >= 4, immediately returns "RED" (Veto!) so the bot
         NEVER clicks a Red-Cost building or gets stuck on insufficient resources!
      3. Uses safe upper-middle row click coordinate (2180, card_top + 34).
    """
    cx1 = CARD_GEOMETRY["COST_X1"]          # 2108
    cx2 = min(2252, CARD_GEOMETRY["COST_X2"])  # 2252 (strictly digits, excludes resource icon)
    cy1 = max(0, card_top + 28)
    cy2 = min(img.height - 1, max(cy1 + 14, min(card_bottom - 5, card_top + 74)))

    card_h = max(48, card_bottom - card_top)
    safe_offset_y = max(24, min(36, int(card_h * 0.42)))
    click_x = 2180
    click_y = min(card_bottom - 18, card_top + safe_offset_y)

    px_map = img.load()
    white_px = 0
    red_px = 0

    for sy in range(cy1, cy2, 2):
        for sx in range(cx1, cx2, 2):
            r, g, b = px_map[sx, sy]
            # Red cost digit pixel (bright red / salmon-red text on tan card)
            if r > 170 and g < 98 and b < 98 and (r > g + 75):
                red_px += 1
            # Pure white cost digit pixel
            elif r > 205 and g > 205 and b > 205 and (max(r, g, b) - min(r, g, b) <= 28):
                white_px += 1

    # RED-FIRST VETO: Any red digits in the cost box mean resources are insufficient -> strictly RED!
    if red_px >= 4:
        return "RED", click_x, click_y
    if white_px >= 6 and red_px <= 1:
        return "WHITE", click_x, click_y
    return "NONE", click_x, click_y

def _normalize_card_signature_for_last_page(raw_name):
    if not raw_name:
        return ""
    _, clean_n = classify_building_name_a14(raw_name)
    s = re.sub(r'[^a-zA-Z]', '', clean_n if clean_n else raw_name).lower()
    return s[:10] if len(s) >= 3 else ""

# ==========================================
# 2. BUILDING UPGRADE PROCESS (STRICT RED-COST VETO + MULTI-BUILDER GUARD)
# ==========================================

def run_condition_1_buildings(handoff_to_wall=True, initial_builders=None, stop_at_builders=1):
    """
    Executes Building Upgrade (Condition 1):
      - Strictly skips any card where cost_color is RED or NONE (Red-First Veto).
      - Double-checks cost color right before clicking so a RED building is NEVER clicked!
      - Tracks bottom card OCR names across scrolls for instant Last-Page detection.
      - Protects against premature closing when 3+ builders are free.
    Returns (upgraded_any_building, remaining_builders, scroll_idx).
    """
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED
    upgraded_any_building = False
    if initial_builders is not None:
        avail_builders = initial_builders
    elif bot_tools.LAST_DETECTED_BUILDERS is not None:
        avail_builders = bot_tools.LAST_DETECTED_BUILDERS
    else:
        avail_builders = 2

    print("\n======================================================================")
    print(f"|| [STEP 1: BUILDINGS UPGRADE] ACTIVE (Target Stop Builders <= {stop_at_builders}) ||")
    print("======================================================================")

    max_scrolls = 8
    scroll_idx = 0
    last_page_fp = None
    last_view_signatures = []
    same_bottom_name_streak = 0

    while scroll_idx <= max_scrolls:
        check_pause_point(allow_raise=True)
        upgraded_in_this_view = False
        reopened_after_red_x = False
        post_confirm_img = None

        img = ensure_upgrade_list_is_open()
        cur_fp = capture_upgrade_list_fingerprint(img)
        cards = find_cards_in_upgrade_list(img)

        view_items = []
        current_view_sigs = []
        for (c_top, c_bot) in cards:
            check_pause_point(allow_raise=True)
            cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
            raw_name = read_card_name_a14(img, c_top, c_bot)
            category, clean_name = classify_building_name_a14(raw_name)
            sig = _normalize_card_signature_for_last_page(clean_name if category != "UNKNOWN" else raw_name)
            if sig:
                current_view_sigs.append(sig)
            view_items.append((c_top, c_bot, cost_color, click_x, click_y, raw_name, category, clean_name))

        # Dual Last-Page Check (OCR Card Name Repeat + Pixel Fingerprint):
        if scroll_idx > 0:
            fp_same = (last_page_fp is not None and is_same_upgrade_list_page(last_page_fp, cur_fp))
            names_same = (
                len(current_view_sigs) > 0
                and len(last_view_signatures) > 0
                and (current_view_sigs == last_view_signatures or current_view_sigs[-1] == last_view_signatures[-1])
            )
            if names_same:
                same_bottom_name_streak += 1
            else:
                same_bottom_name_streak = 0

            if fp_same or same_bottom_name_streak >= 2:
                print(f" [✔] [LAST PAGE DETECTED] Scroll #{scroll_idx} par same building name ('{current_view_sigs[-1] if current_view_sigs else 'Bottom'}') repeat hua! Building List Last Page reached.")
                break

        for (c_top, c_bot, cost_color, click_x, click_y, raw_name, category, clean_name) in view_items:
            check_pause_point(allow_raise=True)
            if category == "UNKNOWN":
                continue

            print(f" [SCAN] '{raw_name}' -> '{clean_name}' [{category}] | Cost: {cost_color} | Click=({click_x},{click_y})")

            # Strictly skip RED or NONE cost cards!
            if cost_color != "WHITE":
                continue

            if category in ["EXCLUDED", "WALL"]:
                print(f" [-] Skipping Excluded/Wall Item in Building Phase: '{clean_name}'")
                continue

            if category == "BUILDING" and cost_color == "WHITE":
                print(f" [+] [MATCH FOUND] Upgrading '{clean_name}'! Clicking White Cost at ({click_x}, {click_y})...")
                tap(click_x, click_y, delay_range=(0.18, 0.28), jitter=2)
                human_sleep(0.35, 0.05)

                # Step (i): Click 1582, 930 to confirm upgrade
                print(" [>] [STEP (i)] Clicking Confirm Upgrade (1582, 930)...")
                tap(*UPGRADE_A14["C1_CONFIRM_CLICK"], delay_range=(0.18, 0.28), jitter=3)
                human_sleep(0.42, 0.05)

                # Step (ii): Check Wrong Button at (1589, 339)
                check_img = get_screenshot(force_fresh=True)
                if is_red_x_box_at(check_img, *UPGRADE_A14["C1_WRONG_BTN"], radius=12):
                    print(" [!] [STEP (ii)] Red 'X' found at (1589, 339)! Clicking (1589, 339) -> (2050, 56)...")
                    record_stat("wrong_buttons_cut", 1)
                    tap(*UPGRADE_A14["C1_WRONG_BTN"], delay_range=(0.15, 0.25), jitter=3)
                    human_sleep(0.30, 0.04)
                    tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.18, 0.28), jitter=3)
                    human_sleep(0.42, 0.05)
                    reopened_after_red_x = True
                    last_page_fp = None
                    same_bottom_name_streak = 0
                    break
                else:
                    post_confirm_img = ensure_upgrade_list_is_open(check_img)
                    upgraded_in_this_view = True
                    upgraded_any_building = True
                    LAST_BUILDING_UPGRADED = True
                    LAST_UPGRADE_SUCCESS = True
                    record_stat("buildings_upgraded", 1)
                    last_page_fp = None
                    same_bottom_name_streak = 0
                    break

        if reopened_after_red_x:
            img_now = ensure_upgrade_list_is_open()
            avail_builders = read_builder_check_box_a14(img_now)
            if avail_builders <= stop_at_builders:
                break
            continue

        if upgraded_in_this_view:
            prev_builders = avail_builders
            expected_after_one_upgrade = max(0, prev_builders - 1)

            img_now = post_confirm_img if post_confirm_img is not None else ensure_upgrade_list_is_open()
            read_b = read_builder_check_box_a14(img_now)

            if expected_after_one_upgrade > stop_at_builders and read_b <= stop_at_builders:
                print(f" [i] [BUILDER GUARD] Previous Builders={prev_builders} (Expected={expected_after_one_upgrade}), but OCR read {read_b}. Re-verifying...")
                human_sleep(0.32, 0.04)
                img_recheck = ensure_upgrade_list_is_open(get_screenshot(force_fresh=True))
                read_b2 = read_builder_check_box_a14(img_recheck)
                if read_b2 <= stop_at_builders and expected_after_one_upgrade >= (stop_at_builders + 1):
                    print(f" [BUILDER GUARD] Trusting mathematical builder count ({expected_after_one_upgrade}) so remaining builders are NOT skipped!")
                    avail_builders = expected_after_one_upgrade
                else:
                    avail_builders = read_b2
            else:
                avail_builders = read_b

            print(f" [i] [STEP (iii)] Remaining Available Builders: {avail_builders} (Stop Target <= {stop_at_builders})")

            if avail_builders <= stop_at_builders:
                if handoff_to_wall and avail_builders >= 1:
                    print(f" [DIRECT HANDOFF] Builders reached {avail_builders}! Bina Close button dabaye seedha Wall Upgrade par jump kar rahe hain...")
                elif not handoff_to_wall:
                    print(f" [✔] [BUILDING UPGRADE COMPLETE] Builders reached {avail_builders}! Clicking (2322, 45) to return Home...")
                    tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
                    human_sleep(0.35, 0.05)
                break
            else:
                print(f" [*] {avail_builders} Builders still free (>{stop_at_builders})! Continuing inside Upgrade List...")
                continue

        if scroll_idx < max_scrolls:
            last_page_fp = cur_fp
            if current_view_sigs:
                last_view_signatures = current_view_sigs
            scroll_idx += 1
            print(f" [v] [BUILDING SCROLL {scroll_idx}/{max_scrolls}] Scrolling list inside menu (2050,863 -> 2050,542)...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=350, post_sleep=0.38)
        else:
            print(" [!] [BUILDING LIST END] 8 Scrolls complete! No more White-Cost buildings found.")
            break

    if not handoff_to_wall:
        img_chk = get_screenshot()
        if is_upgrade_list_open_a14(img_chk):
            print(" [x] Closing Upgrade Menu (2322, 45) -> Returning to Home Page...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
            human_sleep(0.35, 0.05)

    return upgraded_any_building, avail_builders, scroll_idx

# ==========================================
# 3. WALL UPGRADE PROCESS (SINGLE WALL + 100-WALL CONTINUOUS STREAK LOCK FIX!)
# ==========================================

def find_matching_wall_card_at_spot(img, prev_top, prev_bot):
    """
    Locates the same Wall card at or near its previous Y position (within +/- 52px)
    in the automatically reopened Upgrade List.
    Returns (c_top, c_bot, found_wall_bool).
    """
    cards = find_cards_in_upgrade_list(img)
    best_card = None
    best_dist = 999

    for (c_top, c_bot) in cards:
        dist = abs(c_top - prev_top)
        if dist <= 52:
            is_wall, _ = verify_card_is_wall_carefully(img, c_top, c_bot)
            if is_wall and dist < best_dist:
                best_dist = dist
                best_card = (c_top, c_bot)

    if best_card is not None:
        return best_card[0], best_card[1], True

    # Fallback: scan all visible cards in current view for Wall
    for (c_top, c_bot) in cards:
        is_wall, _ = verify_card_is_wall_carefully(img, c_top, c_bot)
        if is_wall:
            return c_top, c_bot, True

    # If a card exists very close to prev_top (dist <= 28), return its coordinates for re-verification
    for (c_top, c_bot) in cards:
        if abs(c_top - prev_top) <= 28:
            return c_top, c_bot, False

    return prev_top, prev_bot, False

def _wait_for_wall_upgrade_list_settle(max_polls=3):
    """
    Dynamic Wall List Reopen Polling:
    Waits for the Upgrade List cards to cleanly reappear after double-clicking (1595, 942)
    so frame lag after 5-6 fast wall upgrades never causes a false 'NONE' or missed Wall read!
    """
    human_sleep(0.38, 0.04)
    img_after = get_screenshot(force_fresh=True)

    for poll_i in range(max_polls):
        cards = find_cards_in_upgrade_list(img_after)
        if len(cards) >= 2:
            return img_after
        if poll_i == 1 and not is_upgrade_list_open_a14(img_after):
            print(" [*] Reopening Upgrade List via (2062, 54)...")
            tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.18, 0.28), jitter=3)
        human_sleep(0.24, 0.03)
        img_after = get_screenshot(force_fresh=True)

    return img_after

def upgrade_wall_card_until_red(initial_top, initial_bot, initial_click_x, initial_click_y):
    """
    CONTINUOUS 100+ WALL STREAK ENGINE (Fixes premature stop after 5-6 walls!):
      1. Clicks safe upper-middle coordinate of the White-Cost Wall row -> (439, 851) -> Double-Tap (1595, 942).
      2. Uses _wait_for_wall_upgrade_list_settle() so the list is 100% settled before re-checking cost color.
      3. 2-Strike Confirmation Lock:
         - If cost is WHITE -> immediately continues streak!
         - If cost reads NONE or OCR momentarily misses 'Wall' due to animation -> waits 0.32s, refreshes screenshot,
           and re-checks! Does NOT falsely break the streak after 5-6 walls!
         - Only returns "TURNED_RED" when RED pixels are genuinely confirmed (or when all walls of that level
           are completely finished and replaced by a non-wall card on 2 consecutive checks)!
    """
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED, _LAST_WALL_AFTER_IMG
    cur_top, cur_bot = initial_top, initial_bot
    click_x, click_y = initial_click_x, initial_click_y
    upgrade_count = 0

    while True:
        check_pause_point(allow_raise=True)

        # Step (b): Click Safe Upper-Middle Coordinate on the White-Cost Wall Row
        print(f" [WALL STEP (b)] Clicking Safe Wall Row at ({click_x}, {click_y}) [Same-Row Streak #{upgrade_count + 1}]...")
        tap(click_x, click_y, delay_range=(0.16, 0.25), jitter=2)
        human_sleep(0.30, 0.04)

        # Step a.(i): Click (439, 851)
        print(" [>] [WALL STEP a.(i)] Clicking (439, 851)...")
        tap(*UPGRADE_A14["WALL_STEP_A1_CLICK"], delay_range=(0.16, 0.25), jitter=3)
        human_sleep(0.30, 0.04)

        # Step a.(iii): Compulsory Double Tap on (1595, 942) to upgrade Wall
        print(" [+] [WALL STEP a.(iii)] Double-Clicking (1595, 942) to upgrade Wall...")
        batch_tap_sequence(
            [UPGRADE_A14["WALL_CONFIRM_CLICK"], UPGRADE_A14["WALL_CONFIRM_CLICK"]],
            inter_delay=0.14,
            jitter=3
        )
        upgrade_count += 1
        LAST_WALL_UPGRADED = True
        LAST_UPGRADE_SUCCESS = True
        record_stat("walls_upgraded", 1)

        # Wait dynamically for Upgrade List to reopen and settle
        img_after = _wait_for_wall_upgrade_list_settle(max_polls=3)
        _LAST_WALL_AFTER_IMG = img_after

        cur_top, cur_bot, is_wall_now = find_matching_wall_card_at_spot(img_after, cur_top, cur_bot)
        new_color, click_x, click_y = check_card_cost_color_a14(img_after, cur_top, cur_bot)

        # 2-Strike Re-Verification if list was still animating (NONE color or Wall OCR missed on 1st frame)
        if not is_wall_now or new_color == "NONE":
            print(f" [*] [STREAK SETTLE CHECK] Frame settle wait (is_wall={is_wall_now}, color={new_color})... Re-checking in 0.32s...")
            human_sleep(0.32, 0.04)
            img_after = ensure_upgrade_list_is_open(get_screenshot(force_fresh=True))
            _LAST_WALL_AFTER_IMG = img_after
            cur_top, cur_bot, is_wall_now = find_matching_wall_card_at_spot(img_after, cur_top, cur_bot)
            new_color, click_x, click_y = check_card_cost_color_a14(img_after, cur_top, cur_bot)

        if not is_wall_now:
            # One final check at the exact spot before declaring all walls of this row finished
            is_still_w, _ = verify_card_is_wall_carefully(img_after, cur_top, cur_bot)
            if not is_still_w:
                print(f" [✔] [ROW ALL WALLS UPGRADED] {upgrade_count} Wall(s) upgrade hone ke baad is level ki saari Walls poori ho gayi!")
                return "TURNED_RED"

        print(f" [i] [WALL COST RE-CHECK] Same-Row Streak #{upgrade_count} ke baad Cost Color: {new_color}")
        if new_color == "WHITE":
            print(" [*] Wall Cost abhi bhi WHITE hai! Continuing streak on same Wall row...")
            human_sleep(0.04, 0.01, min_floor=0.02)
            continue
        elif new_color == "RED":
            # Confirm RED once more after 0.20s so a momentary flash never stops a 100-wall streak early
            human_sleep(0.20, 0.03)
            img_confirm_red = get_screenshot(force_fresh=True)
            _LAST_WALL_AFTER_IMG = img_confirm_red
            confirm_color, click_x, click_y = check_card_cost_color_a14(img_confirm_red, cur_top, cur_bot)
            if confirm_color == "WHITE":
                print(" [*] Re-check confirmed Wall Cost is still WHITE! Continuing streak...")
                continue
            print(f" [✔] [STEP (c)] {upgrade_count} baar upgrade ke baad is Wall pankti (Row) ka Cost WHITE se RED ho gaya!")
            return "TURNED_RED"
        else:
            # If still NONE, check if card cost is readable after one tap on reopen
            print(f" [✔] [STEP (c)] {upgrade_count} baar upgrade ke baad Wall Cost WHITE nahi raha ({new_color})!")
            return "TURNED_RED"

def run_wall_upgrade_process(from_building_handoff=False, building_scrolls_done=0, close_menu_on_exit=True):
    """
    Executes Wall Upgrade System inside the open Upgrade List:
      - Detects both multi-wall ('Wall x100') and single-wall ('Wall') rows.
      - Upgrades all walls in a White-Cost row continuously until genuinely RED or all pieces finish.
      - Detects Last Page automatically when bottom card names repeat across scrolls.
    """
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED, _LAST_WALL_AFTER_IMG
    print("\n======================================================================")
    print("|| [STEP 2: WALL UPGRADE SYSTEM] ACTIVE (SINGLE/MULTI WALL & STREAK LOCK) ||")
    print("======================================================================")

    if from_building_handoff and building_scrolls_done > 0:
        print(f" [TOP RESET] Building phase me {building_scrolls_done} scroll hue the -> (2062, 54) double-tap se list Top par la rahe hain...")
        batch_tap_sequence(
            [UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], UPGRADE_A14["WALL_REOPEN_LIST_CLICK"]],
            inter_delay=0.20,
            jitter=3
        )
        human_sleep(0.45, 0.05)

    max_scrolls = 25
    scroll_idx = 0
    has_upgraded_any_wall = False
    upgraded_wall_rows_count = 0
    max_wall_rows_limit = 4
    last_page_fp = None
    last_bottom_card_sig = ""
    last_view_sigs = []
    same_name_repeat_count = 0

    while scroll_idx <= max_scrolls:
        check_pause_point(allow_raise=True)

        if scroll_idx > 0 and (scroll_idx % 4 == 0):
            chk_img = get_screenshot()
            if not is_upgrade_list_open_a14(chk_img):
                check_wrong_buttons_a14(chk_img)
                if is_on_home_page_a14(chk_img) and not is_upgrade_list_open_a14(chk_img):
                    print(" [!] [SAFETY GUARD] Home Page par atke hue mile! (2062, 54) / (2233, 948) se List open kar rahe hain...")
                    tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.20, 0.32), jitter=3)
                    human_sleep(0.42, 0.05)
                    chk_img = get_screenshot(force_fresh=True)
                    if not is_upgrade_list_open_a14(chk_img):
                        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.22, 0.35), jitter=3)
                        human_sleep(0.50, 0.06)

        img = ensure_upgrade_list_is_open()
        cur_fp = capture_upgrade_list_fingerprint(img)
        cards = find_cards_in_upgrade_list(img)

        found_white_wall_in_view = False
        cur_view_sigs = []

        for (c_top, c_bot) in cards:
            check_pause_point(allow_raise=True)
            cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
            is_wall, raw_name = verify_card_is_wall_carefully(img, c_top, c_bot)
            sig = _normalize_card_signature_for_last_page("Wall" if is_wall else raw_name)
            if sig:
                cur_view_sigs.append(sig)

            if not is_wall:
                continue

            print(f" [WALL FOUND] '{raw_name}' -> 'Wall' | Cost: {cost_color} | SafeClick=({click_x},{click_y}) | Rows: {upgraded_wall_rows_count}/{max_wall_rows_limit}")

            if cost_color == "RED" or cost_color == "NONE":
                print(" [-] [STEP (a)] Wall ke aage Cost RED hai. Scroll karke White Cost wala Wall khojenge...")
                continue

            if cost_color == "WHITE":
                found_white_wall_in_view = True
                result = upgrade_wall_card_until_red(c_top, c_bot, click_x, click_y)

                if result == "TURNED_RED":
                    has_upgraded_any_wall = True
                    LAST_WALL_UPGRADED = True
                    LAST_UPGRADE_SUCCESS = True
                    upgraded_wall_rows_count += 1
                    last_page_fp = None
                    same_name_repeat_count = 0
                    last_bottom_card_sig = ""
                    last_view_sigs = []

                    print(f" [i] [WALL ROW COUNTER] Distinct Wall Row #{upgraded_wall_rows_count}/{max_wall_rows_limit} upgraded & turned RED!")

                    if upgraded_wall_rows_count >= max_wall_rows_limit:
                        print(f" [✔] [4-ROW LIMIT REACHED] {upgraded_wall_rows_count} alag-alag Wall panktiyan upgrade hokar RED ho gayi! Exiting Wall Upgrade...")
                        break

                    max_scrolls = 22
                    scroll_idx = 0
                    print(f" [STEP (c)] Ab List ko {max_scrolls} baar tak scroll karke agli White-Cost Wall pankti khojenge...")
                    break
                elif result == "NOT_WALL_REOPENED":
                    if not has_upgraded_any_wall:
                        max_scrolls = 12
                    last_page_fp = None
                    same_name_repeat_count = 0
                    break

        if upgraded_wall_rows_count >= max_wall_rows_limit:
            break

        if found_white_wall_in_view and scroll_idx == 0 and has_upgraded_any_wall:
            print(f" [v] [SCROLL 1/{max_scrolls}] Scrolling past Red Wall (2050,863 -> 2050,542)...")
            ref_img = _LAST_WALL_AFTER_IMG if _LAST_WALL_AFTER_IMG is not None else get_screenshot()
            last_page_fp = capture_upgrade_list_fingerprint(ref_img)
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=350, post_sleep=0.38)
            scroll_idx = 1
            continue

        # Dual Last-Page Detection in Wall Upgrade
        if scroll_idx > 0 and not found_white_wall_in_view:
            fp_same = (last_page_fp is not None and is_same_upgrade_list_page(last_page_fp, cur_fp))
            cur_bottom_sig = cur_view_sigs[-1] if cur_view_sigs else ""
            if (cur_bottom_sig and cur_bottom_sig == last_bottom_card_sig) or (cur_view_sigs and cur_view_sigs == last_view_sigs):
                same_name_repeat_count += 1
            else:
                same_name_repeat_count = 1 if cur_bottom_sig else 0

            if fp_same or same_name_repeat_count >= 2:
                print(f" [✔] [WALL LAST PAGE DETECTED] Scroll #{scroll_idx} par bottom item ('{cur_bottom_sig or 'End'}') repeat ho raha hai! Upgrade List Last Page reached.")
                break

        if scroll_idx < max_scrolls:
            last_page_fp = cur_fp
            if cur_view_sigs:
                last_bottom_card_sig = cur_view_sigs[-1]
                last_view_sigs = cur_view_sigs
            scroll_idx += 1
            print(f" [v] [WALL SCROLL {scroll_idx}/{max_scrolls}] Scrolling List to find White-Cost Wall...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=350, post_sleep=0.38)
        else:
            print(f" [!] [STEP (d)] {max_scrolls} baar scroll karne par bhi aur White Cost wala Wall nahi mila!")
            break

    if close_menu_on_exit:
        print(" [x] Clicking Close Button (2322, 45) -> Returning to Home Page (Wall Upgrade Close)...")
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
        human_sleep(0.35, 0.05)

    return has_upgraded_any_wall or LAST_WALL_UPGRADED

# ==========================================
# 4. MASTER COMBINED, BUILDINGS-ONLY & CUSTOM MODE [9] UPGRADE CONTROLLERS
# ==========================================

def run_a14_combined_upgrade_loop(stop_at_builders=1):
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_BUILDING_UPGRADED = False
    LAST_WALL_UPGRADED = False
    upg_start_t = time.time()

    try:
        print("\n======================================================================")
        print("|| STARTING SAMSUNG GALAXY A14 COMBINED UPGRADE (BUILDING -> WALL)  ||")
        print("======================================================================")

        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.20, 0.32), jitter=3)
        human_sleep(0.45, 0.05)

        builders = read_builder_check_box_a14()
        print(f" [i] [COMBINED BUILDER CHECK] Initial Available Builders Detected: {builders}")

        if builders <= 0:
            print(" [!] [BUILDERS = 0] Ek bhi builder khali nahi hai. Closing menu (2322, 45)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
            human_sleep(0.35, 0.05)
            perform_home_cleanup_once(max_age_sec=0.0)
            record_duration("upgrade", time.time() - upg_start_t)
            return False, False, False

        remaining_builders = builders
        did_building_phase = False
        b_scrolls_done = 0

        if builders > 1:
            did_building_phase = True
            b_upgraded, remaining_builders, b_scrolls_done = run_condition_1_buildings(
                handoff_to_wall=True,
                initial_builders=builders,
                stop_at_builders=max(1, stop_at_builders)
            )
            LAST_BUILDING_UPGRADED = bool(b_upgraded)
            LAST_UPGRADE_SUCCESS = LAST_UPGRADE_SUCCESS or LAST_BUILDING_UPGRADED
        else:
            print(" [DIRECT WALL JUMP] Builders = 1! Building skip karke seedha Wall Upgrade start kar rahe hain...")

        if remaining_builders >= 1:
            w_upgraded = run_wall_upgrade_process(
                from_building_handoff=did_building_phase,
                building_scrolls_done=b_scrolls_done,
                close_menu_on_exit=True
            )
            LAST_WALL_UPGRADED = bool(w_upgraded)
            LAST_UPGRADE_SUCCESS = LAST_UPGRADE_SUCCESS or LAST_WALL_UPGRADED
        else:
            print(" [i] Building Upgrade ke baad Builders = 0 bache. Closing Upgrade Menu (2322, 45)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
            human_sleep(0.35, 0.05)

        perform_home_cleanup_once(max_age_sec=0.0)

        # Home-Page-Only Symmetric 2-Finger Zoom-Out after Upgrade Menu closes
        zoom_out_village_a14(passes=2, reason="POST-COMBINED-UPGRADE HOME RESET")

        any_up = bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED or LAST_UPGRADE_SUCCESS)
        upg_dur = time.time() - upg_start_t
        record_duration("upgrade", upg_dur)

        print("======================================================================")
        print(f"|| COMBINED UPGRADE COMPLETED in {upg_dur:.1f}s (Building={LAST_BUILDING_UPGRADED} | Wall={LAST_WALL_UPGRADED} | Any={any_up}) ||")
        print("======================================================================\n")
        return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, any_up

    except BotPausedResumeHomeException:
        raise
    except Exception as e:
        print("\n[! ERROR!] Combined Upgrade Loop me error aayi:")
        traceback.print_exc()
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), check_pause=False)
        zoom_out_village_a14(passes=2, reason="UPGRADE ERROR RECOVERY")
        record_duration("upgrade", time.time() - upg_start_t)
        any_up = bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED or LAST_UPGRADE_SUCCESS)
        return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, any_up

def run_a14_buildings_only_upgrade_loop(stop_at_builders=1):
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_BUILDING_UPGRADED = False
    LAST_WALL_UPGRADED = False
    upg_start_t = time.time()

    try:
        print("\n======================================================================")
        print(f"|| [BUILDINGS-ONLY UPGRADE] ACTIVE (Stop Builders <= {stop_at_builders}) ||")
        print("======================================================================")

        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.20, 0.32), jitter=3)
        human_sleep(0.45, 0.05)

        builders = read_builder_check_box_a14()
        print(f" [i] [BUILDINGS-ONLY CHECK] Initial Available Builders Detected: {builders}")

        if builders > stop_at_builders:
            b_upgraded, _, _ = run_condition_1_buildings(
                handoff_to_wall=False,
                initial_builders=builders,
                stop_at_builders=stop_at_builders
            )
            LAST_BUILDING_UPGRADED = bool(b_upgraded)
            LAST_UPGRADE_SUCCESS = LAST_BUILDING_UPGRADED
        else:
            print(f" [i] Builders = {builders} (<= {stop_at_builders}). Closing menu (2322, 45)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
            human_sleep(0.35, 0.05)

        perform_home_cleanup_once(max_age_sec=0.0)
        zoom_out_village_a14(passes=2, reason="POST-BUILDING-UPGRADE HOME RESET")
        record_duration("upgrade", time.time() - upg_start_t)

        print("======================================================================")
        print(f"|| [BUILDINGS-ONLY COMPLETED] (Building Upgraded={LAST_BUILDING_UPGRADED}) ||")
        print("======================================================================\n")
        return LAST_BUILDING_UPGRADED

    except BotPausedResumeHomeException:
        raise
    except Exception as e:
        print("\n[! ERROR!] Buildings-Only Upgrade Loop me error aayi:")
        traceback.print_exc()
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), check_pause=False)
        zoom_out_village_a14(passes=2, reason="BUILDING UPGRADE ERROR RECOVERY")
        record_duration("upgrade", time.time() - upg_start_t)
        return bool(LAST_BUILDING_UPGRADED)

def run_custom_mode_upgrade_loop(order_type="BUILDING_THEN_WALL", stop_at_builders=0):
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_BUILDING_UPGRADED = False
    LAST_WALL_UPGRADED = False
    upg_start_t = time.time()

    try:
        if order_type == "BUILDING_ONLY":
            b_up = run_a14_buildings_only_upgrade_loop(stop_at_builders=stop_at_builders)
            return b_up, False, b_up

        if order_type == "WALL_ONLY":
            w_up = run_a14_wall_upgrade_loop()
            return False, w_up, w_up

        if order_type == "WALL_THEN_BUILDING":
            print("\n======================================================================")
            print(f"|| [CUSTOM MODE 9] WALL FIRST -> THEN BUILDING (Stop Builders <= {stop_at_builders}) ||")
            print("======================================================================")
            tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.20, 0.32), jitter=3)
            human_sleep(0.45, 0.05)
            builders = read_builder_check_box_a14()
            if builders <= 0:
                print(" [!] [BUILDERS = 0] Closing menu (2322, 45)...")
                tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
                human_sleep(0.35, 0.05)
                perform_home_cleanup_once(max_age_sec=0.0)
                record_duration("upgrade", time.time() - upg_start_t)
                return False, False, False

            w_up = run_wall_upgrade_process(from_building_handoff=False, building_scrolls_done=0, close_menu_on_exit=False)
            LAST_WALL_UPGRADED = bool(w_up)

            batch_tap_sequence([UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], UPGRADE_A14["WALL_REOPEN_LIST_CLICK"]], inter_delay=0.20, jitter=3)
            human_sleep(0.42, 0.05)

            builders_now = read_builder_check_box_a14()
            b_up = False
            if builders_now > stop_at_builders:
                b_up, _, _ = run_condition_1_buildings(
                    handoff_to_wall=False,
                    initial_builders=builders_now,
                    stop_at_builders=stop_at_builders
                )
            else:
                tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
                human_sleep(0.35, 0.05)

            LAST_BUILDING_UPGRADED = bool(b_up)
            perform_home_cleanup_once(max_age_sec=0.0)
            zoom_out_village_a14(passes=2, reason="POST-CUSTOM-UPGRADE HOME RESET")
            record_duration("upgrade", time.time() - upg_start_t)
            any_up = bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED)
            return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, any_up

        b_up, w_up, any_up = run_a14_combined_upgrade_loop(stop_at_builders=1)
        if stop_at_builders == 0 and (bot_tools.LAST_DETECTED_BUILDERS is None or bot_tools.LAST_DETECTED_BUILDERS >= 1):
            print(" [CUSTOM 0-BUILDER RULE] Checking if last remaining builder (1 -> 0) can upgrade a Building...")
            b_extra = run_a14_buildings_only_upgrade_loop(stop_at_builders=0)
            b_up = bool(b_up or b_extra)
            any_up = bool(b_up or w_up)
        return b_up, w_up, any_up

    except BotPausedResumeHomeException:
        raise
    except Exception:
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), check_pause=False)
        zoom_out_village_a14(passes=2, reason="CUSTOM UPGRADE RECOVERY")
        return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED)

def run_a14_upgrade_loop():
    _, _, any_up = run_a14_combined_upgrade_loop()
    return bool(any_up)

def run_a14_wall_upgrade_loop():
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_WALL_UPGRADED = False
    upg_start_t = time.time()
    try:
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.20, 0.32), jitter=3)
        human_sleep(0.45, 0.05)
        builders = read_builder_check_box_a14()
        if builders <= 0:
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), jitter=3)
            human_sleep(0.35, 0.05)
            perform_home_cleanup_once(max_age_sec=0.0)
            record_duration("upgrade", time.time() - upg_start_t)
            return False
        w_up = run_wall_upgrade_process(from_building_handoff=False, building_scrolls_done=0, close_menu_on_exit=True)
        perform_home_cleanup_once(max_age_sec=0.0)
        zoom_out_village_a14(passes=2, reason="POST-WALL-UPGRADE HOME RESET")
        record_duration("upgrade", time.time() - upg_start_t)
        return bool(w_up)
    except BotPausedResumeHomeException:
        raise
    except Exception:
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.28), check_pause=False)
        zoom_out_village_a14(passes=2, reason="WALL UPGRADE RECOVERY")
        record_duration("upgrade", time.time() - upg_start_t)
        return bool(LAST_WALL_UPGRADED)

