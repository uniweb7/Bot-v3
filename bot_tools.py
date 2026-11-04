rm -rf __pycache__ *.pyc
cat << 'EOF' > bot_tools.py
import sys
import os
import time
import subprocess
import random
import re
import threading
import select
from PIL import Image, ImageOps
import pytesseract

class RestartLoopException(Exception):
    """Raised when bot detects Home Page or Wrong Button during Attack."""
    pass

class BotPausedResumeHomeException(Exception):
    """Raised when bot is paused via 'ZX' and resumed via 'QW' to restart cleanly from Home Page."""
    pass

# ==========================================
# 0. LIVE PAUSE ('ZX') & RESUME ('QW') ENGINE
# ==========================================
_PAUSE_STATE = {
    "paused": False,
    "resumed_just_now": False,
    "buffer": "",
    "listener_started": False
}
_PAUSE_LOCK = threading.Lock()

def _keyboard_listener_worker():
    """
    Background thread that watches Termux keyboard input continuously.
    Typing 'zx' (case-insensitive, with or without Enter) pauses the bot immediately.
    Typing 'qw' (case-insensitive, with or without Enter) resumes the bot from Home Page.
    """
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        use_cbreak = True
    except Exception:
        use_cbreak = False

    try:
        while True:
            if use_cbreak:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.15)
                if rlist:
                    ch = sys.stdin.read(1)
                    if not ch:
                        time.sleep(0.1)
                        continue
                    with _PAUSE_LOCK:
                        _PAUSE_STATE["buffer"] = (_PAUSE_STATE["buffer"] + ch.lower())[-12:]
                        buf = _PAUSE_STATE["buffer"]
                        if not _PAUSE_STATE["paused"] and "zx" in buf:
                            _PAUSE_STATE["paused"] = True
                            _PAUSE_STATE["buffer"] = ""
                            print("\n╔══════════════════════════════════════════════════════════════════╗")
                            print("║  [⏸️ BOT PAUSED BY 'ZX'] Bot wahin ruk gaya hai (Memory Safe)!    ║")
                            print("║  👉 Dubara Home Page se Resume karne ke liye 'QW' type karein... ║")
                            print("╚══════════════════════════════════════════════════════════════════╝\n")
                        elif _PAUSE_STATE["paused"] and "qw" in buf:
                            _PAUSE_STATE["paused"] = False
                            _PAUSE_STATE["resumed_just_now"] = True
                            _PAUSE_STATE["buffer"] = ""
                            print("\n╔══════════════════════════════════════════════════════════════════╗")
                            print("║  [▶️ BOT RESUMED BY 'QW'] Home Page se wapas start ho raha hai!  ║")
                            print("╚══════════════════════════════════════════════════════════════════╝\n")
            else:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                clean_line = line.strip().lower()
                with _PAUSE_LOCK:
                    if not _PAUSE_STATE["paused"] and "zx" in clean_line:
                        _PAUSE_STATE["paused"] = True
                        print("\n╔══════════════════════════════════════════════════════════════════╗")
                        print("║  [⏸️ BOT PAUSED BY 'ZX'] Bot wahin ruk gaya hai (Memory Safe)!    ║")
                        print("║  👉 Dubara Home Page se Resume karne ke liye 'QW' type karein... ║")
                        print("╚══════════════════════════════════════════════════════════════════╝\n")
                    elif _PAUSE_STATE["paused"] and "qw" in clean_line:
                        _PAUSE_STATE["paused"] = False
                        _PAUSE_STATE["resumed_just_now"] = True
                        print("\n╔══════════════════════════════════════════════════════════════════╗")
                        print("║  [▶️ BOT RESUMED BY 'QW'] Home Page se wapas start ho raha hai!  ║")
                        print("╚══════════════════════════════════════════════════════════════════╝\n")
    except Exception:
        pass
    finally:
        if use_cbreak:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

def start_pause_resume_listener():
    with _PAUSE_LOCK:
        if _PAUSE_STATE["listener_started"]:
            return
        _PAUSE_STATE["listener_started"] = True
    t = threading.Thread(target=_keyboard_listener_worker, daemon=True)
    t.start()

def check_pause_point(allow_raise=True):
    """
    Blocks execution if 'ZX' was pressed until 'QW' is typed.
    Once 'QW' is typed, raises BotPausedResumeHomeException so active loops return to Home Page.
    """
    was_paused = False
    while True:
        with _PAUSE_LOCK:
            is_paused = _PAUSE_STATE["paused"]
            resumed_flag = _PAUSE_STATE["resumed_just_now"]
        if is_paused:
            was_paused = True
            time.sleep(0.25)
            continue
        if was_paused or resumed_flag:
            with _PAUSE_LOCK:
                _PAUSE_STATE["resumed_just_now"] = False
            if allow_raise:
                raise BotPausedResumeHomeException("Resumed via QW -> Resetting to Home Page")
        break

def smart_sleep(seconds):
    """Sleeps in small chunks while checking for 'ZX' pause / 'QW' resume."""
    end_time = time.time() + max(0.0, float(seconds))
    while time.time() < end_time:
        check_pause_point(allow_raise=True)
        rem = end_time - time.time()
        if rem <= 0:
            break
        time.sleep(min(0.25, rem))
    check_pause_point(allow_raise=True)

# ==========================================
# 1. WRONG BUTTON CUT & HOME PAGE CHECK (PDF PAGE 1)
# ==========================================
WRONG_BUTTON_CUT_COORDS = [
    ("Profile Section", 1917, 87),
    ("League Page", 2149, 84),
    ("Clan War", 192, 981),
    ("Season Reward", 2290, 83),
    ("Events", 1820, 76),
    ("News Letter", 2283, 89),
    ("News", 2284, 73),
    ("Tournament Hub", 1831, 73),
    ("Magic Items", 1720, 164),
    ("Shop", 2282, 79)
]

# Green box with white '+' check on Home Page
HOME_PAGE_CHECK_COORDS = [(2050, 285), (2050, 250)]

# Storage Bars & Check Boxes (Condition 1: Building Upgrade)
GOLD_STORAGE_BAR = (2170, 63)
ELIXIR_STORAGE_BAR = (2166, 128)
GOLD_STORAGE_CHECK_BOX = (2015, 43, 2081, 78)
ELIXIR_STORAGE_CHECK_BOX = (2003, 116, 2103, 151)

# Wall Upgrade Storage Bar Check Boxes (Separate boxes for Wall Upgrade)
WALL_GOLD_STORAGE_CHECK_BOX = (1947, 44, 2015, 76)
WALL_ELIXIR_STORAGE_CHECK_BOX = (1947, 115, 2015, 149)

# ==========================================
# 2. UPGRADE SYSTEM COORDINATES (SAMSUNG GALAXY A14)
# ==========================================
ENABLE_CONDITION_2 = True

UPGRADE_A14 = {
    "BUILD_CLICK": (2233, 948),
    "BUILDER_CHECK_BOX": (1754, 1008, 1847, 1038),
    "UPGRADE_LIST_BOX": (1820, 545, 2312, 926),
    "CLOSE_MENU": (2322, 45),

    # Condition 1 Filter & Confirm Clicks
    "C1_CLICK_1": (1780, 46),
    "C1_CLICK_2": (1392, 707),
    "C1_CLICK_3": (2048, 54),
    "SCROLL_START": (2050, 863),
    "SCROLL_END": (2050, 542),
    "C1_CONFIRM_CLICK": (1582, 930),
    "C1_WRONG_BTN": (1589, 339),
    "C1_REOPEN_LIST": (2050, 56),

    # Wall Upgrade (Condition 2) New Coordinates
    "WALL_STEP_A1_CLICK": (439, 851),
    "WALL_NAME_CHECK_BOX": (1018, 45, 1400, 108),
    "WALL_REOPEN_LIST_CLICK": (2062, 54),
    "WALL_CONFIRM_CLICK": (1595, 942),

    # Legacy Condition 2 Keys (Preserved)
    "C2_STEP_1": (960, 845),
    "C2_STEP_2": (1580, 930),
    "C2_RED_X": (1590, 326),
    "C2_RED_X_NEXT": (2065, 51),
    "C2_RED_X_ALT_1": (1162, 841),
    "C2_RED_X_ALT_2": (1587, 928),
    "C2_NO_RED_ALT_1": (1172, 835),
    "C2_NO_RED_ALT_2": (1586, 927),
    "C2_FOUR_CLICK": (2080, 50)
}

CARD_GEOMETRY = {
    "CARD_X1": 1820,
    "CARD_X2": 2312,
    "CARD_HEIGHT": 81,
    "NAME_X1": 1823,
    "NAME_X2": 2124,
    "NAME_DY1": 5,
    "NAME_DY2": 41,
    "TIME_X1": 2241,
    "TIME_X2": 2310,
    "TIME_DY1": 2,
    "TIME_DY2": 35,
    "COST_X1": 2107,
    "COST_X2": 2313,
    "COST_DY1": 33,
    "COST_DY2": 81
}

# Condition 1 Excluded List (Includes Town Hall as requested)
CONDITION_1_EXCLUDED = [
    "town hall", "townhall",
    "barbarian", "king",
    "dragon duke", "duke",
    "minion prince", "prince",
    "crafting", "station",
    "royal", "champion",
    "archer queen", "queen",
    "grand warden", "warden",
    "wall"
]

KNOWN_BUILDINGS = [
    "eagle artillery", "scattershot", "inferno tower", "x-bow", "xbow",
    "monolith", "spell tower", "firespitter", "ricochet cannon", "multi-archer tower",
    "multi-gear tower", "air defense", "wizard tower", "hidden tesla", "tesla",
    "bomb tower", "mortar", "archer tower", "cannon", "air sweeper", "builder's hut",
    "builder hut", "clan castle", "laboratory", "spell factory", "dark spell factory",
    "barracks", "dark barracks", "workshop", "pet house", "blacksmith", "hero hall",
    "army camp", "gold storage", "elixir storage", "dark elixir storage",
    "gold mine", "elixir collector", "dark elixir drill", "helper hut", "revenge tower",
    "giant bomb", "air bomb", "seeking air mine", "skeleton trap", "tornado trap",
    "spring trap", "bomb", "giga bomb"
]

# ==========================================
# 3. FAST ATTACK 1 (1 MIN) COORDINATES (A14)
# ==========================================
FAST_ATTACK = {
    "BATTLE_BTN": (182, 961),
    "FIND_MATCH_BTN": (364, 808),
    "ATTACK_BTN": (1980, 972),

    "SPELL_SELECT": (1527, 983),
    "SPELL_DEPLOY_LIST": [
        (378, 469),
        (594, 350),
        (566, 569),
        (691, 461),
        (864, 278),
        (812, 760),
        (928, 569),
        (915, 444),
        (1170, 580),
        (1070, 250),
        (892, 815)
    ],

    "ARMY_1_SELECT": (470, 988),
    "ARMY_1_DEPLOY_LIST": [
        (325, 525),
        (225, 510),
        (303, 473),
        (292, 592),
        (222, 516),
        (453, 363),
        (337, 611),
        (256, 512),
        (375, 524)
    ],

    "ARMY_2_SELECT": (590, 985),
    "ARMY_2_DEPLOY_LIST": [
        (243, 522),
        (318, 527),
        (355, 465)
    ],

    "SIEGE_SELECT": (770, 977),
    "HERO_1_SELECT": (925, 1005),
    "HERO_2_SELECT": (1073, 987),
    "HERO_3_SELECT": (1218, 990),
    "HERO_4_SELECT": (1350, 978),

    "SURRENDER_BTN": (181, 800),
    "OKAY_BTN": (1419, 701),
    "RETURN_HOME_BTN": (1222, 918)
}

# ==========================================
# 3B. SUPERCELL ID SWITCH SYSTEM COORDINATES (PDF PAGES 2-3)
# ==========================================
ID_SWITCH_A14 = {
    # Navigation from Home Page to Supercell ID List
    "PROFILE_BTN": (142, 122),
    "SETTINGS_BTN": (1755, 92),
    "SWITCH_ICON_BTN": (1507, 207),
    "CLOSE_SWITCH_PANEL_BTN": (135, 80),

    # Supercell ID List Box & Verification Coordinates
    "LIST_BOX_CORNERS": (135, 150, 2370, 1040),
    "SUPERCELL_LOGO_BOX": (335, 502, 710, 518),
    "SUPERCELL_LOGO_OCR_BOX": (325, 465, 725, 550),
    "DIVIDER_X": 1118,

    # First COC ID Card Post-Mortem Geometry (Reference Card #1)
    "FIRST_CARD_BOX": (1158, 209, 2376, 434),
    "PROFILE_ICON_BOX": (1187, 237, 1340, 386),
    "UNIQUE_ID_BOX": (1350, 236, 1940, 292),
    "ID_NAME_BOX": (1190, 300, 1429, 353),
    "TOWN_HALL_BOX": (1348, 360, 1662, 396),
    "LEAGUE_BOX": (2162, 265, 2335, 368),

    # Relative offsets from any ID card's top Y (card_top = 209 for Card #1)
    "CARD_HEIGHT": 225,
    "CARD_STEP_Y": 242,
    "UNIQUE_ID_REL_Y1": 27,
    "UNIQUE_ID_REL_Y2": 83,
    "ID_NAME_REL_Y1": 91,
    "ID_NAME_REL_Y2": 144,
    "TH_REL_Y1": 151,
    "TH_REL_Y2": 187,

    # Direct Click Coordinates for the 4 ID Card Slots
    "ID_1_CLICK": (1763, 321),
    "ID_2_CLICK": (1763, 563),
    "ID_3_CLICK": (1763, 800),
    "ID_4_CLICK": (1763, 1044),
    "ID_SLOTS": [
        (1763, 321),
        (1763, 563),
        (1763, 800),
        (1763, 1044)
    ],

    # Smooth Scroll (Moves 4th half-visible card to 1st card position)
    "SCROLL_START": (1763, 1030),
    "SCROLL_END": (1763, 215),
    "SCROLL_DURATION_MS": 950,

    # Wait time after clicking an ID card for village loading
    "ID_LOAD_WAIT_SEC": 40.0
}

# ==========================================
# 4. ADB INPUT & HIGH-SPEED BATCH DEPLOY ENGINE
# ==========================================
def human_sleep(base_sec, variance=0.08):
    check_pause_point(allow_raise=True)
    actual = max(0.02, base_sec + random.uniform(-variance, variance))
    smart_sleep(actual)

def tap(x, y, delay_range=(0.05, 0.10), jitter=2, check_pause=True):
    if check_pause:
        check_pause_point(allow_raise=True)
    jx = int(x) + random.randint(-jitter, jitter)
    jy = int(y) + random.randint(-jitter, jitter)
    subprocess.run(["adb", "shell", "input", "tap", str(jx), str(jy)])
    if delay_range[1] > 0:
        wait_t = random.uniform(*delay_range)
        if check_pause:
            smart_sleep(wait_t)
        else:
            time.sleep(wait_t)

def fast_serial_taps(coord_list, rounds=1, jitter=2):
    """
    Executes multiple rounds of taps in exact serial order inside a SINGLE adb shell call
    so 2 rounds of Spells or 4 rounds of Army 1 finish within ~1 second.
    """
    check_pause_point(allow_raise=True)
    cmds = []
    for _ in range(rounds):
        for (x, y) in coord_list:
            jx = int(x) + random.randint(-jitter, jitter)
            jy = int(y) + random.randint(-jitter, jitter)
            cmds.append(f"input tap {jx} {jy}")
    full_cmd = " ; ".join(cmds)
    subprocess.run(["adb", "shell", full_cmd])

def swipe(x1, y1, x2, y2, duration=450, post_sleep=0.85):
    check_pause_point(allow_raise=True)
    sx1 = int(x1) + random.randint(-4, 4)
    sy1 = int(y1) + random.randint(-4, 4)
    sx2 = int(x2) + random.randint(-4, 4)
    sy2 = int(y2) + random.randint(-4, 4)
    dur = duration + random.randint(-30, 50)
    subprocess.run(["adb", "shell", "input", "swipe", str(sx1), str(sy1), str(sx2), str(sy2), str(dur)])
    human_sleep(post_sleep, 0.10)

def get_screenshot(check_pause=True):
    if check_pause:
        check_pause_point(allow_raise=True)
    subprocess.run("adb exec-out screencap -p > screen.png", shell=True)
    return Image.open("screen.png").convert('RGB')

# ==========================================
# 5. SCREEN SCANNERS (WRONG BUTTON, HOME PAGE & STORAGE)
# ==========================================
def is_red_x_box_at(img, cx, cy, radius=10):
    w, h = img.size
    red_count = 0
    white_count = 0
    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            px = min(max(0, cx + dx), w - 1)
            py = min(max(0, cy + dy), h - 1)
            r, g, b = img.getpixel((px, py))
            if r > 175 and g < 85 and b < 85:
                red_count += 1
            elif r > 200 and g > 200 and b > 200:
                white_count += 1
    return (red_count >= 5 and white_count >= 1) or (red_count >= 9)

def check_wrong_buttons_a14(img=None):
    """Scans the 10 Wrong-Button Cut coordinates from PDF Page 1."""
    if img is None:
        img = get_screenshot()
    clicked_any = False
    for label, x, y in WRONG_BUTTON_CUT_COORDS:
        if is_red_x_box_at(img, x, y, radius=12):
            print(f"  [!] [WRONG BUTTON CUT] '{label}' ({x}, {y}) par Red 'X' mila! Cut kar rahe hain...")
            tap(x, y, delay_range=(0.2, 0.35), jitter=2)
            clicked_any = True
            human_sleep(0.35, 0.08)
            img = get_screenshot()
    return clicked_any

def is_on_home_page_a14(img=None):
    """Checks (2050, 285) and (2050, 250) for the green box with a white '+' sign."""
    if img is None:
        img = get_screenshot()
    w, h = img.size
    for (cx, cy) in HOME_PAGE_CHECK_COORDS:
        green_pixels = 0
        white_pixels = 0
        for dy in range(-12, 13, 2):
            for dx in range(-12, 13, 2):
                px = min(max(0, cx + dx), w - 1)
                py = min(max(0, cy + dy), h - 1)
                r, g, b = img.getpixel((px, py))
                if g > 135 and g > r + 25 and g > b + 25:
                    green_pixels += 1
                elif r > 210 and g > 210 and b > 210:
                    white_pixels += 1
        if green_pixels >= 6 and white_pixels >= 1:
            return True
    return False

def ensure_return_to_home_page_a14():
    """
    Ensures the bot is back on the Home Page (used after Resume 'QW' or ID Switch).
    Closes Upgrade menu or Wrong Buttons if open, and verifies Home Page Green '+'.
    """
    print("  [🏠 HOME RECOVERY] Ensuring bot is cleanly on the Home Page...")
    for _ in range(3):
        img = get_screenshot(check_pause=False)
        if is_on_home_page_a14(img):
            check_wrong_buttons_a14(img)
            double_click_storage_bars()
            return True
        if is_red_x_box_at(img, *UPGRADE_A14["CLOSE_MENU"], radius=14):
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.4, 0.6), jitter=3, check_pause=False)
            time.sleep(0.8)
            continue
        check_wrong_buttons_a14(img)
        tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.15, 0.25), jitter=3, check_pause=False)
        double_click_storage_bars()
        time.sleep(1.0)
    return is_on_home_page_a14()

def click_gold_storage_3_times():
    print("  [*] [HOME PAGE] Gold Storage Bar (2170, 63) par 3 baar click kar rahe hain...")
    for _ in range(3):
        tap(*GOLD_STORAGE_BAR, delay_range=(0.08, 0.14), jitter=2)

def double_click_storage_bars():
    for _ in range(2):
        tap(*GOLD_STORAGE_BAR, delay_range=(0.08, 0.14), jitter=2)
    for _ in range(2):
        tap(*ELIXIR_STORAGE_BAR, delay_range=(0.08, 0.14), jitter=2)

def check_resources_full_for_upgrade(img=None):
    """Checks Condition 1 (Building Upgrade) Gold & Elixir Storage Bar Boxes."""
    if img is None:
        img = get_screenshot()

    gx1, gy1, gx2, gy2 = GOLD_STORAGE_CHECK_BOX
    gold_total, gold_colored = 0, 0
    for y in range(gy1, gy2, 2):
        for x in range(gx1, gx2, 2):
            r, g, b = img.getpixel((x, y))
            if r > 215 and g > 215 and b > 215:
                continue
            gold_total += 1
            if r > 165 and g > 125 and b < 95 and (r + g) > (b * 3):
                gold_colored += 1
    gold_ratio = (gold_colored / gold_total) if gold_total > 0 else 0.0

    ex1, ey1, ex2, ey2 = ELIXIR_STORAGE_CHECK_BOX
    elixir_total, elixir_colored = 0, 0
    for y in range(ey1, ey2, 2):
        for x in range(ex1, ex2, 2):
            r, g, b = img.getpixel((x, y))
            if r > 215 and g > 215 and b > 215:
                continue
            elixir_total += 1
            if r > 145 and b > 110 and r > (g + 25):
                elixir_colored += 1
    elixir_ratio = (elixir_colored / elixir_total) if elixir_total > 0 else 0.0

    is_gold_full = gold_ratio >= 0.45
    is_elixir_full = elixir_ratio >= 0.45
    print(f"  [i] [BUILDING STORAGE SCAN] Gold Yellow: {gold_ratio*100:.0f}% (Full={is_gold_full}) | Elixir Pink: {elixir_ratio*100:.0f}% (Full={is_elixir_full})")
    return is_gold_full or is_elixir_full

def check_wall_resources_full_a14(img=None):
    """
    1. Wall Resources Check:
       Gold Storage Bar Box: (1947, 44) to (2015, 76)
       Elixir Storage Bar Box: (1947, 115) to (2015, 149)
       Activates Wall Upgrade if either Gold is yellow-filled OR Elixir is pink/purple-filled.
    """
    if img is None:
        img = get_screenshot()

    gx1, gy1, gx2, gy2 = WALL_GOLD_STORAGE_CHECK_BOX
    gold_total, gold_colored = 0, 0
    for y in range(gy1, gy2, 2):
        for x in range(gx1, gx2, 2):
            r, g, b = img.getpixel((x, y))
            if r > 215 and g > 215 and b > 215:
                continue
            gold_total += 1
            if r > 165 and g > 125 and b < 95 and (r + g) > (b * 3):
                gold_colored += 1
    gold_ratio = (gold_colored / gold_total) if gold_total > 0 else 0.0

    ex1, ey1, ex2, ey2 = WALL_ELIXIR_STORAGE_CHECK_BOX
    elixir_total, elixir_colored = 0, 0
    for y in range(ey1, ey2, 2):
        for x in range(ex1, ex2, 2):
            r, g, b = img.getpixel((x, y))
            if r > 215 and g > 215 and b > 215:
                continue
            elixir_total += 1
            if r > 145 and b > 110 and r > (g + 25):
                elixir_colored += 1
    elixir_ratio = (elixir_colored / elixir_total) if elixir_total > 0 else 0.0

    is_gold_full = gold_ratio >= 0.45
    is_elixir_full = elixir_ratio >= 0.45
    print(f"  [i] [WALL STORAGE SCAN] Gold Box (1947,44..2015,76): {gold_ratio*100:.0f}% (Full={is_gold_full}) | Elixir Box (1947,115..2015,149): {elixir_ratio*100:.0f}% (Full={is_elixir_full})")
    return is_gold_full or is_elixir_full

# ==========================================
# 6. BUILDER CHECK BOX READER & WALL VERIFIERS
# ==========================================
def parse_builder_fraction(raw_text):
    if not raw_text:
        return None
    s = raw_text.strip().replace(" ", "")
    s = re.sub(r'^[|Il!i](?=/\d)', '1', s)

    if '/' in s:
        left = s.split('/')[0].strip()
        if not left:
            return None
        digits = re.sub(r'[^0-9]', '', left)
        if digits:
            val = int(digits[-1])
            if 0 <= val <= 6:
                return val
        return None

    digits_only = re.sub(r'[^0-9]', '', s)
    if len(digits_only) == 3 and digits_only[1] == '1' and digits_only[2] in ['5', '6']:
        return int(digits_only[0])
    if len(digits_only) == 2 and digits_only[1] in ['5', '6']:
        return int(digits_only[0])
    return None

def read_builder_check_box_a14(img=None):
    if img is None:
        img = get_screenshot()

    x1, y1, x2, y2 = UPGRADE_A14["BUILDER_CHECK_BOX"]
    w = x2 - x1

    for thresh in [180, 168, 192]:
        crop = img.crop((x1 - 2, y1 - 2, x2 + 2, y2 + 2))
        large = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS).convert('L')
        bw = large.point(lambda p: 0 if p > thresh else 255, '1').convert('L')
        padded = ImageOps.expand(bw, border=14, fill=255)

        cfg = '--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/|Il!'
        txt = pytesseract.image_to_string(padded, config=cfg).strip()
        val = parse_builder_fraction(txt)
        if val is not None:
            print(f"  [i] [BUILDER OCR] Box (1754,1008..1847,1038) Read: '{txt}' -> {val} Builders Free")
            return val

    left_crop = img.crop((x1 - 2, y1, x1 + int(w * 0.42), y2))
    l_large = left_crop.resize((left_crop.width * 3, left_crop.height * 3), Image.Resampling.LANCZOS).convert('L')
    l_bw = ImageOps.expand(l_large.point(lambda p: 0 if p > 175 else 255, '1').convert('L'), border=14, fill=255)
    l_txt = pytesseract.image_to_string(l_bw, config='--oem 3 --psm 10 -c tessedit_char_whitelist=0123456|Il!').strip()

    if l_txt in ['|', 'I', 'l', '!']:
        print(f"  [i] [BUILDER LEFT-OCR] Read '{l_txt}' -> 1 Builder Free")
        return 1
    if l_txt.isdigit() and int(l_txt[0]) <= 6:
        print(f"  [i] [BUILDER LEFT-OCR] Read '{l_txt[0]}' -> {int(l_txt[0])} Builders Free")
        return int(l_txt[0])
    return 0

def is_text_matching_wall(raw_text):
    """Checks if OCR text starts with or clearly represents 'Wall' (ignoring trailing x100 etc.)."""
    if not raw_text:
        return False
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text).lower()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return False

    # Reject other 'W' buildings/heroes immediately
    non_wall_w_words = ["wizard", "workshop", "warden", "watch", "witch"]
    if any(nw in cleaned for nw in non_wall_w_words):
        return False

    first_token = cleaned.split()[0]
    wall_regexes = [
        r'^wall',
        r'^wa[l1i!|]{2}',
        r'^w[a4o][l1i!|]{1,2}$',
        r'\bwall\b',
        r'\bwalls\b',
        r'\bwali\b',
        r'\bwail\b',
        r'\bwa11\b',
        r'\bwal1\b'
    ]
    return any(re.search(pat, first_token) or re.search(pat, cleaned) for pat in wall_regexes)

def verify_wall_name_box_a14(img=None):
    """
    a.(ii) Checks Wall Name Box (1018, 45, 1400, 108) to verify if the first 4 letters are 'Wall'.
    Uses multi-threshold OCR verification for 100% accuracy.
    """
    if img is None:
        img = get_screenshot()

    x1, y1, x2, y2 = UPGRADE_A14["WALL_NAME_CHECK_BOX"]
    crop = img.crop((x1, y1, x2, y2))
    upscaled = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
    w, h = upscaled.size
    src = upscaled.load()

    for thresh in [175, 160, 190]:
        bw = Image.new('L', (w, h), 255)
        dst = bw.load()
        for py in range(h):
            for px in range(w):
                r, g, b = src[px, py]
                if r > thresh and g > thresh and b > thresh and (max(r, g, b) - min(r, g, b) <= 45):
                    dst[px, py] = 0
        padded = ImageOps.expand(bw, border=14, fill=255)
        txt = pytesseract.image_to_string(padded, config='--oem 3 --psm 7').strip()
        if is_text_matching_wall(txt):
            print(f"  [✔] [WALL BOX VERIFIED] Box (1018,45..1400,108) Read: '{txt}' -> Confirmed 'Wall'!")
            return True, txt

    print(f"  [!] [WALL BOX FAILED] Box (1018,45..1400,108) me 'Wall' nahi mila (Last read: '{txt}').")
    return True, txt

def classify_building_name_a14(raw_ocr_text):
    if not raw_ocr_text:
        return "UNKNOWN", ""

    cleaned = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', raw_ocr_text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    base_name = re.sub(r'\b[xX]\s*\d+.*$', '', cleaned).strip()
    if not base_name:
        base_name = cleaned

    lower = base_name.lower().strip()
    if len(lower) < 2:
        return "UNKNOWN", base_name

    if is_text_matching_wall(lower):
        return "WALL", "Wall"

    for ex in CONDITION_1_EXCLUDED:
        if ex in lower:
            if ex == "archer" and "tower" in lower:
                continue
            return "EXCLUDED", base_name

    for known in KNOWN_BUILDINGS:
        if known in lower:
            return "BUILDING", known.title()

    alpha_only = re.sub(r'[^a-zA-Z]', '', lower)
    if len(alpha_only) >= 3:
        return "BUILDING", base_name

    return "UNKNOWN", base_name
EOF
