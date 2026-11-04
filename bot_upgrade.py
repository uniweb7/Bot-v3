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

# ==========================================
# CARD DETECTION & GEOMETRY ENGINE (1820, 545 to 2312, 926)
# ==========================================
def is_tan_card_background(r, g, b):
    if g > r + 8:
        return False
    return (142 <= r <= 225) and (118 <= g <= 200) and (88 <= b <= 172) and (r > g > b)

def find_cards_in_upgrade_list(img):
    lx1, ly1, lx2, ly2 = UPGRADE_A14["UPGRADE_LIST_BOX"]
    cards = []
    in_card = False
    card_top = 0

    for y in range(ly1 + 2, ly2 - 2, 1):
        r1, g1, b1 = img.getpixel((2130, y))
        r2, g2, b2 = img.getpixel((2000, y))
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

def is_upgrade_list_open_a14(img=None):
    """Checks if the Upgrade Menu (Close button at 2322, 45) OR Upgrade List cards are visible."""
    if img is None:
        img = get_screenshot()
    if is_red_x_box_at(img, *UPGRADE_A14["CLOSE_MENU"], radius=14):
        return True
    cards = find_cards_in_upgrade_list(img)
    return len(cards) > 0

def ensure_upgrade_list_is_open():
    """
    Only opens the Upgrade Menu if it is actually closed.
    NEVER clicks (2233, 948) if the menu is already open!
    """
    img = get_screenshot()
    if is_upgrade_list_open_a14(img):
        return img

    print("  [*] [LIST GUARD] Upgrade List dikh nahi rahi. (2050, 56) / (2233, 948) se open kar rahe hain...")
    tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.45, 0.7), jitter=3)
    human_sleep(1.0, 0.15)
    img = get_screenshot()

    if not is_upgrade_list_open_a14(img):
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.5, 0.8), jitter=3)
        human_sleep(1.2, 0.15)
        img = get_screenshot()
    return img

def read_card_name_a14(img, card_top, card_bottom, thresh=178):
    nx1 = CARD_GEOMETRY["NAME_X1"]
    nx2 = CARD_GEOMETRY["NAME_X2"]
    ny1 = max(0, card_top + CARD_GEOMETRY["NAME_DY1"] - 2)
    ny2 = min(img.height, card_top + CARD_GEOMETRY["NAME_DY2"] + 4)

    crop = img.crop((nx1, ny1, nx2, ny2))
    upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    w, h = upscaled.size
    src = upscaled.load()

    bw = Image.new('L', (w, h), 255)
    dst = bw.load()
    for py in range(h):
        for px in range(w):
            r, g, b = src[px, py]
            if r > thresh and g > thresh and b > thresh and (max(r, g, b) - min(r, g, b) <= 38):
                dst[px, py] = 0

    padded = ImageOps.expand(bw, border=12, fill=255)
    return pytesseract.image_to_string(padded, config='--oem 3 --psm 7').strip()

def verify_card_is_wall_carefully(img, card_top, card_bottom):
    """
    Carefully checks if a card in the Upgrade List is 'Wall'.
    If it starts with 'W' or resembles 'Wall', re-verifies 2-3 times across multiple thresholds.
    Ignores trailing quantities (e.g., 'Wall x125') and only checks for 'Wall'.
    """
    raw_1 = read_card_name_a14(img, card_top, card_bottom, thresh=178)
    cleaned_1 = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_1).strip()

    starts_with_w = cleaned_1.lower().startswith('w')
    first_match = is_text_matching_wall(raw_1)

    if not (first_match or starts_with_w):
        return False, raw_1

    # Re-verify 2 more times with different contrast thresholds to be 100% sure
    confirm_count = 1 if first_match else 0
    readings = [raw_1]

    for extra_thresh in [164, 190]:
        raw_extra = read_card_name_a14(img, card_top, card_bottom, thresh=extra_thresh)
        readings.append(raw_extra)
        if is_text_matching_wall(raw_extra):
            confirm_count += 1

    if confirm_count >= 2 or (first_match and confirm_count >= 1):
        print(f"  [✔] [WALL RE-VERIFIED] Readings {readings} -> Confirmed 'Wall'!")
        return True, raw_1

    return False, raw_1

def check_card_cost_color_a14(img, card_top, card_bottom):
    cx1 = CARD_GEOMETRY["COST_X1"]
    cx2 = CARD_GEOMETRY["COST_X2"]
    cy1 = card_top + CARD_GEOMETRY["COST_DY1"]
    cy2 = min(img.height - 1, max(cy1 + 14, min(card_bottom - 2, card_top + CARD_GEOMETRY["COST_DY2"])))

    click_x = (cx1 + cx2) // 2
    click_y = (cy1 + cy2) // 2

    white_px = 0
    red_px = 0
    for sy in range(cy1, cy2, 2):
        for sx in range(cx1, cx2, 3):
            r, g, b = img.getpixel((sx, sy))
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
# CONDITION 1: BUILDINGS UPGRADE (Stays Inside List Until Builders == 1)
# ==========================================
def run_condition_1_buildings():
    global LAST_UPGRADE_SUCCESS
    upgraded_any_building = False

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║      [CONDITION 1] BUILDINGS UPGRADE SYSTEM ACTIVE       ║")
    print("║      Target: Keep Upgrading Inside List Until Builder=1  ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Apply Filter Click Sequence ONCE at the beginning of Condition 1:
    # (i) 1780, 46 -> (ii) 1392, 707 -> (iii) 2048, 54
    print("  [>] [FILTER SETUP] Clicking (1780,46) -> (1392,707) -> (2048,54) ONCE...")
    tap(*UPGRADE_A14["C1_CLICK_1"], delay_range=(0.45, 0.7))
    human_sleep(0.55, 0.1)
    tap(*UPGRADE_A14["C1_CLICK_2"], delay_range=(0.45, 0.7))
    human_sleep(0.55, 0.1)
    tap(*UPGRADE_A14["C1_CLICK_3"], delay_range=(0.45, 0.7))
    human_sleep(1.1, 0.15)

    while True:
        check_pause_point(allow_raise=True)
        upgraded_one = False
        max_scrolls = 8

        for scroll_idx in range(max_scrolls + 1):
            check_pause_point(allow_raise=True)
            img = ensure_upgrade_list_is_open()
            cards = find_cards_in_upgrade_list(img)

            for (c_top, c_bot) in cards:
                check_pause_point(allow_raise=True)
                cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
                raw_name = read_card_name_a14(img, c_top, c_bot)
                category, clean_name = classify_building_name_a14(raw_name)

                if category == "UNKNOWN":
                    continue

                print(f"  [SCAN] '{raw_name}' -> '{clean_name}' [{category}] | Cost: {cost_color}")

                if category in ["EXCLUDED", "WALL"]:
                    print(f"    [-] Skipping Excluded Item: '{clean_name}'")
                    continue

                if category == "BUILDING" and cost_color == "WHITE":
                    print(f"  [+] [MATCH FOUND] Upgrading '{clean_name}'! Clicking White Cost at ({click_x}, {click_y})...")
                    tap(click_x, click_y, delay_range=(0.5, 0.75), jitter=3)
                    human_sleep(0.8, 0.15)

                    # Step (i): Click 1582, 930 to confirm upgrade
                    print("  [>] [STEP (i)] Clicking Confirm Upgrade (1582, 930)...")
                    tap(*UPGRADE_A14["C1_CONFIRM_CLICK"], delay_range=(0.5, 0.75), jitter=3)
                    human_sleep(1.1, 0.15)

                    # Step (ii): Check Wrong Button at (1589, 339)
                    check_img = get_screenshot()
                    if is_red_x_box_at(check_img, *UPGRADE_A14["C1_WRONG_BTN"], radius=12):
                        print("  [!] [STEP (ii)] Red 'X' found at (1589, 339)! Clicking (1589, 339) -> (2050, 56)...")
                        tap(*UPGRADE_A14["C1_WRONG_BTN"], delay_range=(0.4, 0.6), jitter=3)
                        human_sleep(0.6, 0.1)
                        tap(*UPGRADE_A14["C1_REOPEN_LIST"], delay_range=(0.45, 0.7), jitter=3)
                        human_sleep(1.1, 0.15)
                    else:
                        # Do NOT click (2233, 948) if the menu is already open!
                        ensure_upgrade_list_is_open()

                    upgraded_one = True
                    upgraded_any_building = True
                    LAST_UPGRADE_SUCCESS = True
                    break

            if upgraded_one:
                break

            if scroll_idx < max_scrolls:
                print(f"  [v] [SCROLL {scroll_idx+1}/{max_scrolls}] Scrolling list inside menu (2050,863 -> 2050,542)...")
                swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=450)
            else:
                print("  [!] [LIST END] No more White-Cost buildings found after scrolling.")

        if not upgraded_one:
            print("  [x] Closing Upgrade Menu (2322, 45) -> Returning to Home Page...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.45, 0.7), jitter=3)
            human_sleep(0.9, 0.12)
            break

        # Step (iii): Check Available Builders inside the open menu (1754, 1008, 1847, 1038)
        img_now = ensure_upgrade_list_is_open()
        avail_builders = read_builder_check_box_a14(img_now)
        print(f"  [i] [STEP (iii)] Remaining Available Builders: {avail_builders}")

        if avail_builders <= 1:
            print("  [✔] [CONDITION 1 COMPLETE] Builders reached 1 (1/5 or 1/6)! Clicking (2322, 45) to return Home...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.45, 0.7), jitter=3)
            human_sleep(0.9, 0.12)
            break
        else:
            print(f"  [↻] {avail_builders} Builders still free (>1)! Staying inside Upgrade List for next upgrade...")

    check_wrong_buttons_a14()
    double_click_storage_bars()
    return upgraded_any_building

def run_a14_upgrade_loop():
    """
    Runs the Building Upgrade Loop (Condition 1).
    Returns True if at least 1 building was upgraded, False otherwise.
    """
    global LAST_UPGRADE_SUCCESS
    LAST_UPGRADE_SUCCESS = False
    try:
        print("\n┌──────────────────────────────────────────────────────────┐")
        print("│         STARTING SAMSUNG GALAXY A14 UPGRADE LOOP         │")
        print("└──────────────────────────────────────────────────────────┘")

        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.5, 0.8), jitter=3)
        human_sleep(1.3, 0.2)

        builders = read_builder_check_box_a14()
        print(f"  [i] Initial Available Builders Detected: {builders}")

        if builders > 1:
            upgraded = run_condition_1_buildings()
            LAST_UPGRADE_SUCCESS = bool(upgraded)
        else:
            print(f"  [i] Builders = {builders} (<= 1). Building Upgrade requires > 1 builder.")
            print("  [x] Clicking Close Button (2322, 45) to return to Home Page...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.45, 0.7), jitter=3)
            human_sleep(0.9, 0.12)
            check_wrong_buttons_a14()
            double_click_storage_bars()

        print("┌──────────────────────────────────────────────────────────┐")
        print(f"│   UPGRADE LOOP COMPLETED CLEANLY (Upgraded={LAST_UPGRADE_SUCCESS})   │")
        print("└──────────────────────────────────────────────────────────┘\n")
        return LAST_UPGRADE_SUCCESS
    except BotPausedResumeHomeException:
        raise
    except Exception as e:
        print("\n[! ERROR !] Upgrade Loop me error aayi:")
        traceback.print_exc()
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.4, 0.65), check_pause=False)
        return LAST_UPGRADE_SUCCESS

# ==========================================
# CONDITION 2: NEW WALL UPGRADE SYSTEM (PDF PAGES 1-3)
# ==========================================
def find_matching_wall_card_at_spot(img, prev_top, prev_bot):
    """
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
    Executes Step (b) -> a.(i) -> a.(ii) -> a.(iii) continuously on a White-Cost Wall card
    until the Cost Number in front of that Wall turns from White to Red.
    Returns:
      - "TURNED_RED": Wall was upgraded 1+ times and its cost turned Red (triggers 20-22 scroll search).
      - "NOT_WALL_REOPENED": Box (1018,45..1400,108) did not say 'Wall', clicked (2062,54) to reopen list.
    """
    global LAST_UPGRADE_SUCCESS
    cur_top, cur_bot = initial_top, initial_bot
    click_x, click_y = initial_click_x, initial_click_y
    upgrade_count = 0

    while True:
        check_pause_point(allow_raise=True)
        print(f"  [🧱 WALL STEP (b)] Clicking White Cost Number at ({click_x}, {click_y}) [Streak #{upgrade_count + 1}]...")
        tap(click_x, click_y, delay_range=(0.42, 0.65), jitter=3)
        human_sleep(0.75, 0.12)

        # Step a.(i): Click (439, 851)
        print("  [>] [WALL STEP a.(i)] Clicking (439, 851)...")
        tap(*UPGRADE_A14["WALL_STEP_A1_CLICK"], delay_range=(0.45, 0.68), jitter=3)
        human_sleep(0.85, 0.14)

        # Step a.(ii): Check Wall Name Box (1018, 45, 1400, 108) for 'Wall'
        print("  [🔍] [WALL STEP a.(ii)] Checking Wall Name Box (1018, 45 to 1400, 108)...")
        box_img = get_screenshot()
        is_wall_box, box_txt = verify_wall_name_box_a14(box_img)

        if not is_wall_box:
            print("  [!] [NOT WALL] Box me 'Wall' nahi likha hai! Clicking (2062, 54) to reopen list & scroll...")
            tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.48, 0.72), jitter=3)
            human_sleep(1.05, 0.15)
            if upgrade_count > 0:
                return "TURNED_RED"
            return "NOT_WALL_REOPENED"

        # Step a.(iii): If 'Wall' is written, click (1595, 942) to upgrade
        print("  [+] [WALL STEP a.(iii)] 'Wall' confirmed! Clicking (1595, 942) to upgrade Wall...")
        tap(*UPGRADE_A14["WALL_CONFIRM_CLICK"], delay_range=(0.48, 0.72), jitter=3)
        tap(*UPGRADE_A14["WALL_CONFIRM_CLICK"], delay_range=(0.48, 0.72), jitter=3)
        upgrade_count += 1
        LAST_UPGRADE_SUCCESS = True
        human_sleep(1.15, 0.16)

        # Game automatically returns to the Upgrade List. Re-check the same Wall's Cost color!
        img_after = get_screenshot()
        if not is_upgrade_list_open_a14(img_after):
            print("  [*] Upgrade List automatically open nahi dikhi, (2062, 54) click kar rahe hain...")
            tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.45, 0.7), jitter=3)
            human_sleep(1.0, 0.15)
            img_after = get_screenshot()

        cur_top, cur_bot = find_matching_wall_card_at_spot(img_after, cur_top, cur_bot)
        new_color, click_x, click_y = check_card_cost_color_a14(img_after, cur_top, cur_bot)

        # Yeh check karega ki agla card sach mein Wall hai ya nahi
        is_still_wall, _ = verify_card_is_wall_carefully(img_after, cur_top, cur_bot)
        if not is_still_wall:
            print("  [!] [NOT WALL ANYMORE] Yeh card ab Wall nahi hai! Wall upgrade loop tod rahe hain...")
            if upgrade_count > 0:
                return "TURNED_RED"
            return "NOT_WALL_REOPENED"

        print(f"  [i] [WALL COST RE-CHECK] Upgrade #{upgrade_count} ke baad Cost Color: {new_color}")

        if new_color == "WHITE":
            print("  [↻] Wall Cost abhi bhi WHITE hai! Bina chhed-chhad kiye same Wall par process repeat kar rahe hain...")
            human_sleep(0.25, 0.08)
            continue
        else:
            print(f"  [✔] [STEP (c)] {upgrade_count} baar upgrade ke baad Wall Cost WHITE se {new_color} (RED) ho gaya!")
            return "TURNED_RED"

def run_wall_upgrade_process():
    global LAST_UPGRADE_SUCCESS
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║         [WALL UPGRADE SYSTEM] ACTIVE (PDF FLOW)          ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Initial search allows 25 scrolls; after a Wall turns Red (Step c), allows 22 scrolls!
    max_scrolls = 25
    scroll_idx = 0
    has_upgraded_any_wall = False

    while scroll_idx <= max_scrolls:
        check_pause_point(allow_raise=True)
        # Safety Check every 2 scrolls: Check Wrong Buttons & Home Page stuck status
        if scroll_idx > 0 and scroll_idx % 2 == 0:
            chk_img = get_screenshot()
            check_wrong_buttons_a14(chk_img)
            if is_on_home_page_a14(chk_img) and not is_upgrade_list_open_a14(chk_img):
                print("  [!] [SAFETY GUARD] Home Page par atke hue mile! (2062, 54) / (2233, 948) se List open kar rahe hain...")
                tap(*UPGRADE_A14["WALL_REOPEN_LIST_CLICK"], delay_range=(0.45, 0.7), jitter=3)
                human_sleep(1.0, 0.15)
                chk_img = get_screenshot()
                if not is_upgrade_list_open_a14(chk_img):
                    tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.5, 0.8), jitter=3)
                    human_sleep(1.2, 0.15)

        img = ensure_upgrade_list_is_open()
        cards = find_cards_in_upgrade_list(img)
        found_white_wall_in_view = False

        for (c_top, c_bot) in cards:
            check_pause_point(allow_raise=True)
            is_wall, raw_name = verify_card_is_wall_carefully(img, c_top, c_bot)
            if not is_wall:
                continue

            cost_color, click_x, click_y = check_card_cost_color_a14(img, c_top, c_bot)
            print(f"  [WALL FOUND] '{raw_name}' -> 'Wall' | Cost Color: {cost_color}")

            if cost_color == "RED" or cost_color == "NONE":
                print("    [-] [STEP (a)] Wall ke aage Cost RED hai. Scroll karke White Cost wala Wall khojenge...")
                continue

            if cost_color == "WHITE":
                found_white_wall_in_view = True
                result = upgrade_wall_card_until_red(c_top, c_bot, click_x, click_y)

                if result == "TURNED_RED":
                    has_upgraded_any_wall = True
                    LAST_UPGRADE_SUCCESS = True
                    # Step (c): Reset scroll counter and search up to 22 times for a new White-Cost Wall!
                    max_scrolls = 22
                    scroll_idx = 0
                    print(f"  [🔎 STEP (c)] Ab List ko {max_scrolls} baar tak scroll karke naya White-Cost Wall khojenge...")
                    break
                elif result == "NOT_WALL_REOPENED":
                    # Step a.(ii) fallback: Reopened list via (2062, 54), now scroll up to 10-12 times
                    if not has_upgraded_any_wall:
                        max_scrolls = 12
                    break

        if found_white_wall_in_view and scroll_idx == 0 and has_upgraded_any_wall:
            # Do one scroll to move past the Wall that just turned Red
            print(f"  [v] [SCROLL 1/{max_scrolls}] Scrolling past Red Wall (2050,863 -> 2050,542)...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=450)
            scroll_idx = 1
            continue

        if scroll_idx < max_scrolls:
            scroll_idx += 1
            print(f"  [v] [WALL SCROLL {scroll_idx}/{max_scrolls}] Scrolling List to find White-Cost Wall...")
            swipe(*UPGRADE_A14["SCROLL_START"], *UPGRADE_A14["SCROLL_END"], duration=450)
        else:
            print(f"  [!] [STEP (d)] {max_scrolls} baar scroll karne par bhi White Cost wala Wall nahi mila!")
            break

    # Close menu (2322, 45) -> Return to Home Page
    print("  [x] Clicking Close Button (2322, 45) -> Returning to Home Page (Wall Upgrade Close)...")
    tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.45, 0.7), jitter=3)
    human_sleep(0.9, 0.12)
    check_wrong_buttons_a14()
    double_click_storage_bars()
    return has_upgraded_any_wall or LAST_UPGRADE_SUCCESS

def run_a14_wall_upgrade_loop():
    """
    Master entry point for Wall Upgrade System:
    1. Clicks Build Button (2233, 948)
    2. Checks Builder Check Box (1754, 1008, 1847, 1038)
       - (i) If Builders == 0 (0/6 or 0/5): Clicks (2322, 45) -> Home Page (Wall Upgrade Close)
       - (ii) If Builders >= 1 (1/6, 1/5, or >1): Starts Wall Upgrade List Search & Upgrade Loop
    Returns True if at least 1 Wall was upgraded, False otherwise.
    """
    global LAST_UPGRADE_SUCCESS
    LAST_UPGRADE_SUCCESS = False
    try:
        print("\n┌──────────────────────────────────────────────────────────┐")
        print("│       STARTING SAMSUNG GALAXY A14 WALL UPGRADE LOOP      │")
        print("└──────────────────────────────────────────────────────────┘")

        # 2. Build Click -> (2233, 948)
        tap(*UPGRADE_A14["BUILD_CLICK"], delay_range=(0.5, 0.8), jitter=3)
        human_sleep(1.3, 0.2)

        # 3. Builder Check Box -> (1754, 1008, 1847, 1038)
        builders = read_builder_check_box_a14()
        print(f"  [i] [WALL BUILDER CHECK] Available Builders Detected: {builders}")

        if builders <= 0:
            # 3.(i) Agar Builder 0/6 ya 0/5 hai -> Click 2322, 45 -> Home Page
            print("  [!] [STEP 3.(i)] Builders = 0 (0/6 ya 0/5)! Ek bhi builder khali nahi hai.")
            print("  [x] Clicking (2322, 45) -> Returning to Home Page (Wall Upgrade Close)...")
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.45, 0.7), jitter=3)
            human_sleep(0.9, 0.12)
            check_wrong_buttons_a14()
            double_click_storage_bars()
        else:
            # 3.(ii) Agar Builder 1/6, 1/5 ya 1 se jyada hai -> Start Wall Upgrade Process
            print(f"  [+] [STEP 3.(ii)] {builders} Builder(s) available (>= 1)! Starting Wall Upgrade Search...")
            upgraded_wall = run_wall_upgrade_process()
            LAST_UPGRADE_SUCCESS = bool(upgraded_wall) or LAST_UPGRADE_SUCCESS

        print("┌──────────────────────────────────────────────────────────┐")
        print(f"│     WALL UPGRADE LOOP COMPLETED (Upgraded={LAST_UPGRADE_SUCCESS})      │")
        print("└──────────────────────────────────────────────────────────┘\n")
        return LAST_UPGRADE_SUCCESS
    except BotPausedResumeHomeException:
        raise
    except Exception as e:
        print("\n[! ERROR !] Wall Upgrade Loop me error aayi:")
        traceback.print_exc()
        tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.4, 0.65), check_pause=False)
        return LAST_UPGRADE_SUCCESS
EOF
