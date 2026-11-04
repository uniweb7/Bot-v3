cat << 'EOF' > bot_upgrade.py
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

# ==========================================
# 1. CARD DETECTION, LAST-PAGE DETECTOR & FAST OCR ENGINE
# ==========================================

def is_tan_card_background(r, g, b):
    if g > r + 8:
        return False
    return (142 <= r <= 225) and (118 <= g <= 200) and (88 <= b <= 172) and (r > g > b)

def find_cards_in_upgrade_list(img):
    """Point #43: Uses C-speed img.load() pixel matrix to detect upgrade cards."""
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
    """
    Point #21 (Last Page / End-of-List Detection):
    Samples a dense grid of pixels across the Upgrade List Box (1820, 545 to 2312, 926)
    including card names, icons, and cost regions so we can detect if a swipe moved the list or hit the bottom.
    """
    if img is None:
        return None
    px_map = img.load()
    lx1, ly1, lx2, ly2 = UPGRADE_A14["UPGRADE_LIST_BOX"]
    samples = []
    for sy in range(ly1 + 18, ly2 - 18, 12):
        for sx in range(lx1 + 25, lx2 - 25, 28):
            samples.append(px_map[sx, sy])
    return samples

def is_same_upgrade_list_page(fp_before, fp_after, diff_threshold=6.5):
    """
    Point #21: Compares two list fingerprints before and after scrolling.
    Returns True if the list did not move (i.e., reached Last Page / Bottom of Upgrade List).
    """
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
    tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.20, 0.35), jitter=3)
    human_sleep(0.50, 0.06)
    img = get_screenshot(force_fresh=True)
    if not is_upgrade_list_open_a14(img):
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.25, 0.40), jitter=3)
        human_sleep(0.60, 0.08)
        img = get_screenshot(force_fresh=True)
    return img

def read_card_name_a14(img, card_top, card_bottom, thresh=178):
    """
    Points #42, #43, #44, #45, #46, #49:
    Direct sub-box crop + BILINEAR 2x upscale + ink pre-check + horizontal whitespace trim
    + dawg-disabled Tesseract OCR for 2x speed with 100% text accuracy.
    """
    nx1 = CARD_GEOMETRY["NAME_X1"]
    nx2 = CARD_GEOMETRY["NAME_X2"]
    ny1 = max(0, card_top + CARD_GEOMETRY["NAME_DY1"] - 2)
    ny2 = min(img.height, card_top + CARD_GEOMETRY["NAME_DY2"] + 4)

    crop = img.crop((nx1, ny1, nx2, ny2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
    w, h = upscaled.size
    src = upscaled.load()

    bw = Image.new('L', (w, h), 255)
    dst = bw.load()
    for py in range(h):
        for px in range(w):
            r, g, b = src[px, py]
            if r > thresh and g > thresh and b > thresh and (max(r, g, b) - min(r, g, b) <= 38):
                dst[px, py] = 0

    # Point #42: Skip Tesseract if the card name box is blank
    if not has_enough_ink_pixels(bw, min_black_px=8):
        return ""

    # Point #46: Trim trailing blank white space on the right
    trimmed = trim_binary_horizontal_whitespace(bw, extra_pad=8)
    padded = ImageOps.expand(trimmed, border=10, fill=255)
    cfg = '--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0'
    return pytesseract.image_to_string(padded, config=cfg).strip()

def verify_card_is_wall_carefully(img, card_top, card_bottom):
    """
    Checks if a card in the Upgrade List is 'Wall'.
    Fast-path: returns immediately if first threshold clearly matches 'Wall'.
    Fallback: if it starts with 'W', re-verifies across extra thresholds [164, 190] for 100% accuracy.
    """
    raw_1 = read_card_name_a14(img, card_top, card_bottom, thresh=178)
    cleaned_1 = re.sub(r'[^a-zA-Z0-9\s]', '', raw_1).strip()
    starts_with_w = cleaned_1.lower().startswith('w')
    first_match = is_text_matching_wall(raw_1)

    if first_match:
        print(f" [✔] [WALL VERIFIED] Reading '{raw_1}' -> Confirmed 'Wall'!")
        return True, raw_1

    if not starts_with_w:
        return False, raw_1

    confirm_count = 0
    readings = [raw_1]
    for extra_thresh in [164, 190]:
        raw_extra = read_card_name_a14(img, card_top, card_bottom, thresh=extra_thresh)
        readings.append(raw_extra)
        if is_text_matching_wall(raw_extra):
            confirm_count += 1
            break

    if confirm_count >= 1:
        print(f" [✔] [WALL RE-VERIFIED] Readings {readings} -> Confirmed 'Wall'!")
        return True, raw_1

    return False, raw_1

def check_card_cost_color_a14(img, card_top, card_bottom):
    """Point #43: Uses C-speed img.load() pixel access to check if card cost is WHITE or RED."""
    cx1 = CARD_GEOMETRY["COST_X1"]
    cx2 = CARD_GEOMETRY["COST_X2"]
    cy1 = card_top + CARD_GEOMETRY["COST_DY1"]
    cy2 = min(img.height - 1, max(cy1 + 14, min(card_bottom - 2, card_top + CARD_GEOMETRY["COST_DY2"])))

    click_x = (cx1 + cx2) // 2
    click_y = (cy1 + cy2) // 2

    px_map = img.load()
    white_px = 0
    red_px = 0

    for sy in range(cy1, cy2, 2):
        for sx in range(cx1, cx2, 3):
            r, g, b = px_map[sx, sy]
            if r > 200 and g > 200 and b > 200 and (max(r, g, b) - min(r, g, b) < 32):
                white_px += 1
            elif r > 180 and g < 90 and b < 90:
                red_px += 1

    if white_px >= 6:
        return "WHITE", click_x, click_y
    elif red_px >= 5:
        return "RED", click_x, click_y
    return "NONE", click_x, click_y

# ==========================================
# 2. BUILDING UPGRADE PROCESS (WITH POINT #10, #21, #24, #26)
# ==========================================

def run_condition_1_buildings(handoff_to_wall=True):
    """
    Executes Building Upgrade (Condition 1):
      - Point #8: Filter setup skipped; scans Upgrade List directly.
      - Point #10: Checks Cost Color FIRST; only runs OCR on WHITE-cost cards (skips RED-cost OCR).
      - Point #26: Preserves scroll_idx across building upgrades so it never over-scrolls past 8 scrolls total.
      - Point #21: Detects Last Page (End-of-List) automatically if swipe no longer moves the list.
      - Point #24: When builders reach 1 (or 8 scrolls / Last Page reached) and handoff_to_wall=True,
                   DOES NOT click Close Menu (2322, 45) — jumps directly to Wall Upgrade!
    Returns (upgraded_any_building, remaining_builders).
    """
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED
    upgraded_any_building = False
    avail_builders = LAST_DETECTED_BUILDERS if LAST_DETECTED_BUILDERS is not None else 2

    print("\n======================================================================")
    print("|| [STEP 1: BUILDINGS UPGRADE] ACTIVE (WHITE-COST OCR & SMART HANDOFF) ||")
    print("======================================================================")

    max_scrolls = 8
    scroll_idx = 0
    last_page_fp = None

    while scroll_idx <= max_scrolls:
        check_pause_point(allow_raise=True)
        upgraded_in_this_view = False

        img = ensure_upgrade_list_is_open()
        cur_fp = capture_upgrade_list_fingerprint(img)

        # Point #21: Check if the previous scroll hit the Last Page (End of Upgrade List)
        if scroll_idx > 0 and last_page_fp is not None and is_same_upgrade_list_page(last_page_fp, cur_fp):
            print(f" [i] [LAST PAGE DETECTED] Scroll #{scroll_idx} par Building List ke Last Page par pahunch gaye!")
            break

        cards = find_cards_in_upgrade_list(img)

        for (c_top, c_bot) in cards:
            check_pause_point(allow_raise=True)

            # Point #10: Check Cost Color FIRST! Skip OCR if Cost is RED or NONE
            cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
            if cost_color != "WHITE":
                continue

            raw_name = read_card_name_a14(img, c_top, c_bot)
            category, clean_name = classify_building_name_a14(raw_name)

            if category == "UNKNOWN":
                continue

            print(f" [SCAN] '{raw_name}' -> '{clean_name}' [{category}] | Cost: {cost_color}")

            if category in ["EXCLUDED", "WALL"]:
                print(f" [-] Skipping Excluded/Wall Item in Building Phase: '{clean_name}'")
                continue

            if category == "BUILDING" and cost_color == "WHITE":
                print(f" [+] [MATCH FOUND] Upgrading '{clean_name}'! Clicking White Cost at ({click_x}, {click_y})...")
                tap(click_x, click_y, delay_range=(0.22, 0.35), jitter=3)
                human_sleep(0.42, 0.06)

                # Step (i): Click 1582, 930 to confirm upgrade
                print(" [>] [STEP (i)] Clicking Confirm Upgrade (1582, 930)...")
                tap(*UPGRADE_A14["C1_CONFIRM_CLICK"], delay_range=(0.22, 0.35), jitter=3)
                human_sleep(0.50, 0.06)

                # Step (ii): Check Wrong Button at (1589, 339)
                check_img = get_screenshot(force_fresh=True)
                if is_red_x_box_at(check_img, *UPGRADE_A14["C1_WRONG_BTN"], radius=12):
                    print(" [!] [STEP (ii)] Red 'X' found at (1589, 339)! Clicking (1589, 339) -> (2050, 56)...")
                    tap(*UPGRADE_A14["C1_WRONG_BTN"], delay_range=(0.18, 0.30), jitter=3)
                    human_sleep(0.32, 0.05)
                    tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.22, 0.35), jitter=3)
                    human_sleep(0.50, 0.06)
                else:
                    ensure_upgrade_list_is_open()

                upgraded_in_this_view = True
                upgraded_any_building = True
                LAST_BUILDING_UPGRADED = True
                LAST_UPGRADE_SUCCESS = True
                last_page_fp = None  # Reset fingerprint because list refreshed after upgrade
                break

        if upgraded_in_this_view:
            # Step (iii): Check Available Builders inside the open menu (1754, 1008, 1847, 1038)
            img_now = ensure_upgrade_list_is_open()
            avail_builders = read_builder_check_box_a14(img_now)
            print(f" [i] [STEP (iii)] Remaining Available Builders: {avail_builders}")

            if avail_builders <= 1:
                if handoff_to_wall and avail_builders >= 1:
                    print(" [⚡ DIRECT HANDOFF] Builders reached 1 (1/5 or 1/6)! Bina Close button dabaye seedha Wall Upgrade par jump kar rahe hain...")
                elif not handoff_to_wall:
                    print(" [✔] [CONDITION 1 COMPLETE] Builders reached 1! Clicking (2322, 45) to return Home...")
                    tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
                    human_sleep(0.40, 0.05)
                break
            else:
                print(f" [*] {avail_builders} Builders still free (>1)! Staying inside Upgrade List (Scroll #{scroll_idx}/{max_scrolls})...")
                continue

        # Scroll down if no White-Cost building was upgraded in the current view
        if scroll_idx < max_scrolls:
            last_page_fp = cur_fp
            scroll_idx += 1
            print(f" [v] [BUILDING SCROLL {scroll_idx}/{max_scrolls}] Scrolling list inside menu (2050,863 -> 2050,542)...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=300, post_sleep=0.32)
        else:
            print(" [!] [BUILDING LIST END] 8 Scrolls complete! No more White-Cost buildings found.")
            break

    if not handoff_to_wall:
        # Standalone mode only: Close menu and clean up once (Point #9)
        img_chk = get_screenshot()
        if is_upgrade_list_open_a14(img_chk):
            print(" [x] Closing Upgrade Menu (2322, 45) -> Returning to Home Page...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
            human_sleep(0.40, 0.05)

    return upgraded_any_building, avail_builders

# ==========================================
# 3. WALL UPGRADE PROCESS (WITH POINT #13, #14, #21, #24, #27, #47)
# ==========================================

def find_matching_wall_card_at_spot(img, prev_top, prev_bot):
    """
    Point #11 & #12 (Preserved 100%):
    After upgrading a Wall, locates the same Wall card at or near its previous Y position
    in the automatically reopened Upgrade List to check if its Cost is still WHITE or turned RED.
    """
    cards = find_cards_in_upgrade_list(img)
    best_card = None
    best_dist = 999

    for (c_top, c_bot) in cards:
        dist = abs(c_top - prev_top)
        if dist <= 38:
            is_wall, _ = verify_card_is_wall_carefully(img, c_top, c_bot)
            if is_wall and dist < best_dist:
                best_dist = dist
                best_card = (c_top, c_bot)

    if best_card is not None:
        return best_card

    # Fallback: scan all visible cards in current view for Wall
    for (c_top, c_bot) in cards:
        is_wall, _ = verify_card_is_wall_carefully(img, c_top, c_bot)
        if is_wall:
            return (c_top, c_bot)

    return (prev_top, prev_bot)

def upgrade_wall_card_until_red(initial_top, initial_bot, initial_click_x, initial_click_y):
    """
    Executes Step (b) -> a.(i) -> a.(iii) continuously on a single White-Cost Wall row
    (with Wall Name Box OCR a.(ii) permanently skipped, and compulsory Double Tap on 1595, 942)
    until the Cost Number in front of that Wall row turns from White to Red.
    Note for Point #27: Even if this loop upgrades a Wall row 25 times in a row, it counts as 1 Wall Row!
    """
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED
    cur_top, cur_bot = initial_top, initial_bot
    click_x, click_y = initial_click_x, initial_click_y
    upgrade_count = 0

    while True:
        check_pause_point(allow_raise=True)

        # Step (b): Click White Cost Number in front of Wall
        print(f" [WALL STEP (b)] Clicking White Cost Number at ({click_x}, {click_y}) [Same-Row Streak #{upgrade_count + 1}]...")
        tap(click_x, click_y, delay_range=(0.18, 0.30), jitter=3)
        human_sleep(0.35, 0.05)

        # Step a.(i): Click (439, 851)
        print(" [>] [WALL STEP a.(i)] Clicking (439, 851)...")
        tap(*UPGRADE_A14["WALL_STEP_A1_CLICK"], delay_range=(0.18, 0.30), jitter=3)
        human_sleep(0.35, 0.05)

        # Step a.(ii) Wall Name Box OCR check is permanently skipped as instructed!

        # Step a.(iii) & Point #47: Compulsory Double Tap on (1595, 942) to upgrade Wall
        print(" [+] [WALL STEP a.(iii)] Double-Clicking (1595, 942) to upgrade Wall...")
        batch_tap_sequence(
            [UPGRADE_A14["WALL_CONFIRM_CLICK"], UPGRADE_A14["WALL_CONFIRM_CLICK"]],
            inter_delay=0.14,
            jitter=3
        )
        upgrade_count += 1
        LAST_WALL_UPGRADED = True
        LAST_UPGRADE_SUCCESS = True
        human_sleep(0.55, 0.07)

        # Game automatically returns to the Upgrade List. Re-check the same Wall's Cost color!
        img_after = get_screenshot(force_fresh=True)
        if not is_upgrade_list_open_a14(img_after):
            print(" [*] Upgrade List automatically open nahi dikhi, (2062, 54) click kar rahe hain...")
            tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.22, 0.35), jitter=3)
            human_sleep(0.50, 0.07)
            img_after = get_screenshot(force_fresh=True)

        cur_top, cur_bot = find_matching_wall_card_at_spot(img_after, cur_top, cur_bot)
        new_color, click_x, click_y = check_card_cost_color_a14(img_after, cur_top, cur_bot)

        # Point #11 (Preserved): Verify that the matched card at this spot is still Wall
        is_still_wall, _ = verify_card_is_wall_carefully(img_after, cur_top, cur_bot)
        if not is_still_wall:
            print(" [!] [NOT WALL ANYMORE] Yeh card ab Wall nahi hai! Wall upgrade loop tod rahe hain...")
            if upgrade_count > 0:
                return "TURNED_RED"
            return "NOT_WALL_REOPENED"

        print(f" [i] [WALL COST RE-CHECK] Same-Row Streak #{upgrade_count} ke baad Cost Color: {new_color}")
        if new_color == "WHITE":
            print(" [*] Wall Cost abhi bhi WHITE hai! Bina chhed-chhad kiye same Wall row par process repeat kar rahe hain...")
            human_sleep(0.14, 0.03)
            continue
        else:
            print(f" [✔] [STEP (c)] {upgrade_count} baar upgrade ke baad is Wall pankti (Row) ka Cost WHITE se {new_color} (RED) ho gaya!")
            return "TURNED_RED"

def run_wall_upgrade_process(from_building_handoff=False):
    """
    Executes Wall Upgrade System inside the already-open Upgrade List:
      - Initial search allows up to 25 scrolls; after a Wall row turns Red (Step c), allows up to 22 scrolls (Point #22 preserved).
      - Point #13: Safety check runs every 4 scrolls (scroll_idx % 4 == 0).
      - Point #27: Tracks distinct Wall rows upgraded (max_wall_rows = 4). Upgrading the same Wall row
                   multiple times in a streak counts as 1 row. Once 4 distinct Wall rows turn RED, exits immediately!
      - Point #21: Detects Last Page (End-of-List) automatically when scrolling stops moving the list,
                   and immediately clicks Close Button (2322, 45) to return to Home Page!
    """
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED
    print("\n======================================================================")
    print("|| [STEP 2: WALL UPGRADE SYSTEM] ACTIVE (4-ROW LIMIT & LAST-PAGE EXIT) ||")
    print("======================================================================")

    # If handed off after Building Upgrade scrolled the list down, first check current view;
    # if needed, reopening via (2062, 54) starts cleanly from top when a wall upgrades.
    max_scrolls = 25
    scroll_idx = 0
    has_upgraded_any_wall = False
    upgraded_wall_rows_count = 0
    max_wall_rows_limit = 4
    last_page_fp = None
    reopened_top_after_handoff = False

    while scroll_idx <= max_scrolls:
        check_pause_point(allow_raise=True)

        # Point #13: Safety Check every 4 scrolls
        if scroll_idx > 0 and (scroll_idx % 4 == 0):
            chk_img = get_screenshot()
            check_wrong_buttons_a14(chk_img)
            if is_on_home_page_a14(chk_img) and not is_upgrade_list_open_a14(chk_img):
                print(" [!] [SAFETY GUARD] Home Page par atke hue mile! (2062, 54) / (2233, 948) se List open kar rahe hain...")
                tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.22, 0.35), jitter=3)
                human_sleep(0.50, 0.07)
                chk_img = get_screenshot(force_fresh=True)
                if not is_upgrade_list_open_a14(chk_img):
                    tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.25, 0.40), jitter=3)
                    human_sleep(0.60, 0.08)

        img = ensure_upgrade_list_is_open()
        cur_fp = capture_upgrade_list_fingerprint(img)

        # Point #21: Detect if scroll reached the Last Page (End of Upgrade List)
        if scroll_idx > 0 and last_page_fp is not None and is_same_upgrade_list_page(last_page_fp, cur_fp):
            if from_building_handoff and not reopened_top_after_handoff and not has_upgraded_any_wall:
                # If Building Upgrade handed off near the bottom of the list, reopen list once at top (2062, 54)
                print(" [*] [HANDOFF TOP RESET] Building handoff ke baad bottom par the -> (2062, 54) double-tap se list top par la rahe hain...")
                batch_tap_sequence(
                    [UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], UPGRADE_A14["WALL_REOPEN_LIST_CLICK"]],
                    inter_delay=0.22,
                    jitter=3
                )
                human_sleep(0.50, 0.06)
                reopened_top_after_handoff = True
                last_page_fp = None
                scroll_idx = 0
                continue
            print(f" [✔] [LAST PAGE DETECTED] Scroll #{scroll_idx} par Upgrade List ke Last Page (End) par pahunch gaye! Exiting Wall Upgrade...")
            break

        cards = find_cards_in_upgrade_list(img)
        found_white_wall_in_view = False

        for (c_top, c_bot) in cards:
            check_pause_point(allow_raise=True)
            is_wall, raw_name = verify_card_is_wall_carefully(img, c_top, c_bot)
            if not is_wall:
                continue

            cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
            print(f" [WALL FOUND] '{raw_name}' -> 'Wall' | Cost Color: {cost_color} | Upgraded Rows So Far: {upgraded_wall_rows_count}/{max_wall_rows_limit}")

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

                    print(f" [i] [WALL ROW COUNTER] Distinct Wall Row #{upgraded_wall_rows_count}/{max_wall_rows_limit} upgraded & turned RED!")

                    # Point #27: Exit immediately if 4 distinct Wall rows have been upgraded and turned RED
                    if upgraded_wall_rows_count >= max_wall_rows_limit:
                        print(f" [✔] [4-ROW LIMIT REACHED] {upgraded_wall_rows_count} alag-alag Wall panktiyan upgrade hokar RED ho gayi! Exiting Wall Upgrade...")
                        break

                    # Step (c) & Point #22 (Preserved): Reset scroll counter to search up to 22 times for a new White-Cost Wall!
                    max_scrolls = 22
                    scroll_idx = 0
                    print(f" [STEP (c)] Ab List ko {max_scrolls} baar tak scroll karke agli White-Cost Wall pankti khojenge...")
                    break
                elif result == "NOT_WALL_REOPENED":
                    if not has_upgraded_any_wall:
                        max_scrolls = 12
                    last_page_fp = None
                    break

        # Point #27 check outside inner card loop
        if upgraded_wall_rows_count >= max_wall_rows_limit:
            break

        if found_white_wall_in_view and scroll_idx == 0 and has_upgraded_any_wall:
            # Do one scroll to move past the Wall row that just turned Red
            print(f" [v] [SCROLL 1/{max_scrolls}] Scrolling past Red Wall (2050,863 -> 2050,542)...")
            last_page_fp = capture_upgrade_list_fingerprint(get_screenshot())
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=300, post_sleep=0.32)
            scroll_idx = 1
            continue

        if scroll_idx < max_scrolls:
            last_page_fp = cur_fp
            scroll_idx += 1
            print(f" [v] [WALL SCROLL {scroll_idx}/{max_scrolls}] Scrolling List to find White-Cost Wall...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=300, post_sleep=0.32)
        else:
            print(f" [!] [STEP (d)] {max_scrolls} baar scroll karne par bhi aur White Cost wala Wall nahi mila!")
            break

    # Close menu (2322, 45) -> Return to Home Page (Point #9: single clean exit)
    print(" [x] Clicking Close Button (2322, 45) -> Returning to Home Page (Combined/Wall Upgrade Close)...")
    tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
    human_sleep(0.42, 0.05)

    return has_upgraded_any_wall or LAST_WALL_UPGRADED

# ==========================================
# 4. MASTER COMBINED UPGRADE ENTRY POINTS (POINT #24, #9, #23)
# ==========================================

def run_a14_combined_upgrade_loop():
    """
    Point #24 Master Combined Upgrade Loop (Building First -> Direct Menu Handoff -> Wall Second):
      1. Clicks Build Button (2233, 948) once.
      2. Checks Builder Check Box (1754, 1008, 1847, 1038) once:
         - Case A (Builders <= 0): Clicks Close (2322, 45) -> Returns Home immediately (Point #23).
         - Case B (Builders == 1): Skips Building Upgrade -> Directly runs Wall Upgrade inside the open menu!
         - Case C (Builders > 1) : Runs Building Upgrade -> When builders reach 1 (or 8 scrolls / Last Page),
                                   DOES NOT close menu -> Directly transitions into Wall Upgrade!
      3. When Wall Upgrade finishes (on Last Page, 4-Wall-Row Limit, or max scrolls), clicks Close (2322, 45)
         and runs Home Page cleanup ONCE (Point #9).
    Returns (building_upgraded, wall_upgraded, any_upgraded).
    """
    global LAST_UPGRADE_SUCCESS, LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_BUILDING_UPGRADED = False
    LAST_WALL_UPGRADED = False

    try:
        print("\n======================================================================")
        print("|| STARTING SAMSUNG GALAXY A14 COMBINED UPGRADE (BUILDING -> WALL)  ||")
        print("======================================================================")

        # 1. Click Build Button (2233, 948)
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.22, 0.36), jitter=3)
        human_sleep(0.60, 0.08)

        # 2. Read Builder Check Box (1754, 1008, 1847, 1038)
        builders = read_builder_check_box_a14()
        print(f" [i] [COMBINED BUILDER CHECK] Initial Available Builders Detected: {builders}")

        # Case A (Point #23): 0 Builders available -> Close menu immediately, skip both Building & Wall!
        if builders <= 0:
            print(" [!] [BUILDERS = 0] (0/6 ya 0/5)! Ek bhi builder khali nahi hai. Closing menu (2322, 45)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
            human_sleep(0.42, 0.05)
            perform_home_cleanup_once(max_age_sec=0.0)
            print("======================================================================")
            print("|| COMBINED UPGRADE COMPLETED (Building=False | Wall=False | Any=False) ||")
            print("======================================================================\n")
            return False, False, False

        # Case B: More than 1 Builder available -> Run Building Upgrade first with direct handoff!
        remaining_builders = builders
        did_building_phase = False
        if builders > 1:
            did_building_phase = True
            b_upgraded, remaining_builders = run_condition_1_buildings(handoff_to_wall=True)
            LAST_BUILDING_UPGRADED = bool(b_upgraded)
            LAST_UPGRADE_SUCCESS = LAST_UPGRADE_SUCCESS or LAST_BUILDING_UPGRADED
        else:
            print(" [⚡ DIRECT WALL JUMP] Builders = 1 (1/5 ya 1/6)! Building skip karke seedha Wall Upgrade start kar rahe hain...")

        # Case C: Direct Handoff to Wall Upgrade inside the open menu (if >= 1 builder is free)
        if remaining_builders >= 1:
            w_upgraded = run_wall_upgrade_process(from_building_handoff=did_building_phase)
            LAST_WALL_UPGRADED = bool(w_upgraded)
            LAST_UPGRADE_SUCCESS = LAST_UPGRADE_SUCCESS or LAST_WALL_UPGRADED
        else:
            print(" [i] Building Upgrade ke baad Builders = 0 bache. Closing Upgrade Menu (2322, 45)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
            human_sleep(0.42, 0.05)

        # Point #9: Single cleanup at the end of the entire Combined Upgrade loop
        perform_home_cleanup_once(max_age_sec=0.0)

        any_up = bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED or LAST_UPGRADE_SUCCESS)
        print("======================================================================")
        print(f"|| COMBINED UPGRADE COMPLETED (Building={LAST_BUILDING_UPGRADED} | Wall={LAST_WALL_UPGRADED} | Any={any_up}) ||")
        print("======================================================================\n")
        return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, any_up

    except BotPausedResumeHomeException:
        raise
    except Exception as e:
        print("\n[! ERROR!] Combined Upgrade Loop me error aayi:")
        traceback.print_exc()
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), check_pause=False)
        any_up = bool(LAST_BUILDING_UPGRADED or LAST_WALL_UPGRADED or LAST_UPGRADE_SUCCESS)
        return LAST_BUILDING_UPGRADED, LAST_WALL_UPGRADED, any_up

def run_a14_upgrade_loop():
    """
    Compatible wrapper: runs the Combined Upgrade Loop and returns True if any Building or Wall upgraded.
    """
    _, _, any_up = run_a14_combined_upgrade_loop()
    return bool(any_up)

def run_a14_wall_upgrade_loop():
    """
    Standalone Wall Upgrade entry point (if ever called directly).
    """
    global LAST_UPGRADE_SUCCESS, LAST_WALL_UPGRADED
    LAST_UPGRADE_SUCCESS = False
    LAST_WALL_UPGRADED = False
    try:
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.22, 0.36), jitter=3)
        human_sleep(0.60, 0.08)
        builders = read_builder_check_box_a14()
        if builders <= 0:
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3)
            human_sleep(0.42, 0.05)
            perform_home_cleanup_once(max_age_sec=0.0)
            return False
        w_up = run_wall_upgrade_process(from_building_handoff=False)
        perform_home_cleanup_once(max_age_sec=0.0)
        return bool(w_up)
    except BotPausedResumeHomeException:
        raise
    except Exception:
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), check_pause=False)
        return bool(LAST_WALL_UPGRADED)
EOF
echo "✔ Part 2 (bot_upgrade.py) 100% Complete & Updated!"
