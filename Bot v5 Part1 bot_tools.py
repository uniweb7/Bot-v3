rm -rf __pycache__ *.pyc
cat << 'EOF' > bot_tools.py
import sys
import os
import io
import gc
import time
import subprocess
import random
import re
import threading
import select

# Point #41: Single-thread Tesseract lock to prevent CPU contention & phone heating/lag
os.environ["OMP_THREAD_LIMIT"] = "1"

from PIL import Image, ImageOps
import pytesseract

class RestartLoopException(Exception):
    """Raised when bot detects Home Page or Wrong Button during Attack."""
    pass

class BotPausedResumeHomeException(Exception):
    """Raised when bot is paused via 'ZX' and resumed via 'QW' to restart cleanly from Home Page."""
    pass

# ==========================================
# 0A. ADVANCE FEATURE: GAME SPEED-UP ENGINE (1.0x to 2.25x)
# ==========================================
BOT_SPEED_MULTIPLIER = 1.0

SPEED_PRESETS = {
    "A": 1.00,
    "B": 1.10,
    "C": 1.15,
    "D": 1.20,
    "E": 1.25,
    "F": 1.35,
    "G": 1.50,
    "H": 1.75,
    "I": 2.00,
    "J": 2.25
}

def set_bot_speed_multiplier(mult):
    """Sets the global bot speed multiplier (1.0x standard up to 2.25x max). Persists across ZX/QW."""
    global BOT_SPEED_MULTIPLIER
    val = max(1.0, min(2.25, float(mult)))
    BOT_SPEED_MULTIPLIER = round(val, 2)
    print(f" [⚡ SPEED ENGINE] Bot Speed Multiplier set to: {BOT_SPEED_MULTIPLIER:.2f}x")
    return BOT_SPEED_MULTIPLIER

def get_bot_speed_multiplier():
    return BOT_SPEED_MULTIPLIER

def scale_time_by_speed(seconds, min_floor=0.015):
    """Scales wait/delay durations inversely by BOT_SPEED_MULTIPLIER while keeping a safe minimum floor."""
    if BOT_SPEED_MULTIPLIER <= 1.0:
        return max(min_floor, float(seconds))
    return max(min_floor, float(seconds) / BOT_SPEED_MULTIPLIER)

# ==========================================
# 0B. LIVE PAUSE ('ZX') & RESUME ('QW') ENGINE
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
    Typing 'qw' (case-insensitive, with or without Enter) resumes the bot from Home Page
    at the exact same BOT_SPEED_MULTIPLIER.
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
                            print("\n======================================================================")
                            print(f"|| [BOT PAUSED BY 'ZX'] Bot wahin ruk gaya hai (Speed={BOT_SPEED_MULTIPLIER:.2f}x Safe)! ||")
                            print("|| Dubara Home Page se Resume karne ke liye 'QW' type karein...      ||")
                            print("======================================================================\n")
                        elif _PAUSE_STATE["paused"] and "qw" in buf:
                            _PAUSE_STATE["paused"] = False
                            _PAUSE_STATE["resumed_just_now"] = True
                            _PAUSE_STATE["buffer"] = ""
                            print("\n======================================================================")
                            print(f"|| [BOT RESUMED BY 'QW'] Home Page se wapas start (Speed={BOT_SPEED_MULTIPLIER:.2f}x)! ||")
                            print("======================================================================\n")
            else:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                clean_line = line.strip().lower()
                with _PAUSE_LOCK:
                    if not _PAUSE_STATE["paused"] and "zx" in clean_line:
                        _PAUSE_STATE["paused"] = True
                        print("\n======================================================================")
                        print(f"|| [BOT PAUSED BY 'ZX'] Bot wahin ruk gaya hai (Speed={BOT_SPEED_MULTIPLIER:.2f}x Safe)! ||")
                        print("|| Dubara Home Page se Resume karne ke liye 'QW' type karein...      ||")
                        print("======================================================================\n")
                    elif _PAUSE_STATE["paused"] and "qw" in clean_line:
                        _PAUSE_STATE["paused"] = False
                        _PAUSE_STATE["resumed_just_now"] = True
                        print("\n======================================================================")
                        print(f"|| [BOT RESUMED BY 'QW'] Home Page se wapas start (Speed={BOT_SPEED_MULTIPLIER:.2f}x)! ||")
                        print("======================================================================\n")
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
            time.sleep(0.20)
            continue
        if was_paused or resumed_flag:
            with _PAUSE_LOCK:
                _PAUSE_STATE["resumed_just_now"] = False
            if allow_raise:
                raise BotPausedResumeHomeException("Resumed via QW -> Resetting to Home Page")
        break

def smart_sleep(seconds, apply_speed=False):
    """
    Sleeps in small chunks while checking for 'ZX' pause / 'QW' resume.
    If apply_speed=True, scales duration by BOT_SPEED_MULTIPLIER.
    """
    dur = scale_time_by_speed(seconds) if apply_speed else max(0.0, float(seconds))
    end_time = time.time() + dur
    while time.time() < end_time:
        check_pause_point(allow_raise=True)
        rem = end_time - time.time()
        if rem <= 0:
            break
        time.sleep(min(0.20, rem))
        check_pause_point(allow_raise=True)

# ==========================================
# 1. WRONG BUTTON, DAILY REWARD, MAINTENANCE & HOME PAGE COORDS
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

# Daily Reward Popup Coordinates (from user's handwritten specification)
DAILY_REWARD_OUTER_BOX = (458, 113, 1921, 930)
DAILY_REWARD_CLOSE_BTN = (1858, 153)
DAILY_REWARD_GREEN_BOXES = [
    (540, 467, 753, 490),
    (839, 467, 1042, 487),
    (1131, 468, 1332, 488),
    (537, 782, 744, 805),
    (844, 786, 1033, 804),
    (1136, 791, 1346, 812),
    (1435, 782, 1731, 813)
]

# Maintenance Break Coordinates (Yellow Background + Black "MAINTENANCE BREAK" Letters)
MAINTENANCE_BREAK_BOX = (979, 16, 1442, 63)
MAINTENANCE_CLICK_COORD = (1210, 39)
MAINTENANCE_REST_SEC = 600.0  # 10 Minutes rest between double-click checks

# Green box with white '+' check on Home Page
HOME_PAGE_CHECK_COORDS = [(2050, 285), (2050, 250)]

# Storage Bars & Check Boxes (Point #24: Single Storage Check for Combined Building + Wall Upgrade)
GOLD_STORAGE_BAR = (2170, 63)
ELIXIR_STORAGE_BAR = (2166, 128)
GOLD_STORAGE_CHECK_BOX = (2015, 43, 2081, 78)
ELIXIR_STORAGE_CHECK_BOX = (2003, 116, 2103, 151)

# Preserved for backward compatibility (aliased to Combined Upgrade check in Point #24)
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

    # Condition 1 Filter & Confirm Clicks (Coordinates preserved)
    "C1_CLICK_1": (1780, 46),
    "C1_CLICK_2": (1392, 707),
    "C1_CLICK_3": (2048, 54),
    "SCROLL_START": (2050, 863),
    "SCROLL_END": (2050, 542),
    "C1_CONFIRM_CLICK": (1582, 930),
    "C1_WRONG_BTN": (1589, 339),
    "C1_REOPEN_LIST": (2050, 56),

    # Wall Upgrade (Condition 2) Coordinates
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
        (378, 469), (594, 350), (566, 569), (691, 461),
        (864, 278), (812, 760), (928, 569), (915, 444),
        (1170, 580), (1070, 250), (892, 815)
    ],

    "ARMY_1_SELECT": (470, 988),
    "ARMY_1_DEPLOY_LIST": [
        (325, 525), (225, 510), (303, 473), (292, 592),
        (222, 516), (453, 363), (337, 611), (256, 512),
        (375, 524)
    ],

    "ARMY_2_SELECT": (590, 985),
    "ARMY_2_DEPLOY_LIST": [
        (243, 522), (318, 527), (355, 465)
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
# 3B. SUPERCELL ID SWITCH SYSTEM COORDINATES
# ==========================================
ID_SWITCH_A14 = {
    "PROFILE_BTN": (142, 122),
    "SETTINGS_BTN": (1755, 92),
    "SWITCH_ICON_BTN": (1507, 207),
    "CLOSE_SWITCH_PANEL_BTN": (135, 80),

    "LIST_BOX_CORNERS": (135, 150, 2370, 1040),
    "SUPERCELL_LOGO_BOX": (335, 502, 710, 518),
    "SUPERCELL_LOGO_OCR_BOX": (325, 465, 725, 550),
    "DIVIDER_X": 1118,

    "FIRST_CARD_BOX": (1158, 209, 2376, 434),
    "PROFILE_ICON_BOX": (1187, 237, 1340, 386),
    "UNIQUE_ID_BOX": (1350, 236, 1940, 292),
    "ID_NAME_BOX": (1190, 300, 1429, 353),
    "TOWN_HALL_BOX": (1348, 360, 1662, 396),
    "LEAGUE_BOX": (2162, 265, 2335, 368),

    "CARD_HEIGHT": 225,
    "CARD_STEP_Y": 242,
    "UNIQUE_ID_REL_Y1": 27,
    "UNIQUE_ID_REL_Y2": 83,
    "ID_NAME_REL_Y1": 91,
    "ID_NAME_REL_Y2": 144,
    "TH_REL_Y1": 151,
    "TH_REL_Y2": 187,

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

    "SCROLL_START": (1763, 1030),
    "SCROLL_END": (1763, 215),
    "SCROLL_DURATION_MS": 750,

    # Point #19: Min 3.5s initial wait + 1.0s polling interval (No max timeout limit!)
    "ID_INITIAL_WAIT_SEC": 3.5,
    "ID_POLL_INTERVAL_SEC": 1.0,
    "ID_LOAD_WAIT_SEC": 30.0
}

# ==========================================
# 4. PERSISTENT ADB SHELL ENGINE (#38) & MICRO-CACHED RAM SCREENSHOT (#37, #48)
# ==========================================
_ADB_SHELL_PROC = None
_ADB_LOCK = threading.Lock()

_SCREENSHOT_CACHE = {
    "img": None,
    "timestamp": 0.0
}
LAST_HOME_CLEANUP_TIME = 0.0
LAST_DETECTED_BUILDERS = None
LAST_BUILDER_CHECK_TIME = 0.0

def _invalidate_screen_cache():
    _SCREENSHOT_CACHE["img"] = None
    _SCREENSHOT_CACHE["timestamp"] = 0.0

def _exec_adb_shell_cmd(cmd_str):
    """
    Point #38: Sends input tap/swipe commands through a persistent open 'adb shell' pipe
    for near-zero latency (~0.01s), with automatic fallback to subprocess.run if pipe resets.
    """
    global _ADB_SHELL_PROC
    _invalidate_screen_cache()
    with _ADB_LOCK:
        try:
            if _ADB_SHELL_PROC is None or _ADB_SHELL_PROC.poll() is not None:
                _ADB_SHELL_PROC = subprocess.Popen(
                    ["adb", "shell"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1
                )
            _ADB_SHELL_PROC.stdin.write(cmd_str + "\n")
            _ADB_SHELL_PROC.stdin.flush()
            return
        except Exception:
            _ADB_SHELL_PROC = None
    # Instant fallback if persistent pipe was interrupted
    subprocess.run(["adb", "shell", cmd_str])

def human_sleep(base_sec, variance=0.04, apply_speed=True):
    check_pause_point(allow_raise=True)
    raw_t = max(0.015, float(base_sec) + random.uniform(-variance, variance))
    actual = scale_time_by_speed(raw_t) if apply_speed else raw_t
    smart_sleep(actual, apply_speed=False)

def tap(x, y, delay_range=(0.03, 0.07), jitter=2, check_pause=True, apply_speed=True):
    if check_pause:
        check_pause_point(allow_raise=True)
    jx = int(x) + random.randint(-jitter, jitter)
    jy = int(y) + random.randint(-jitter, jitter)
    _exec_adb_shell_cmd(f"input tap {jx} {jy}")
    if delay_range and delay_range[1] > 0:
        wait_t = random.uniform(*delay_range)
        if apply_speed:
            wait_t = scale_time_by_speed(wait_t)
        if check_pause:
            smart_sleep(wait_t, apply_speed=False)
        else:
            time.sleep(wait_t)

def fast_serial_taps(coord_list, rounds=1, jitter=2):
    """
    Executes multiple rounds of taps in exact serial order inside a SINGLE adb shell command
    so 2 rounds of Spells or 4 rounds of Army 1 finish within ~1 second with anti-ban jitter.
    """
    check_pause_point(allow_raise=True)
    cmds = []
    for _ in range(rounds):
        for (x, y) in coord_list:
            jx = int(x) + random.randint(-jitter, jitter)
            jy = int(y) + random.randint(-jitter, jitter)
            cmds.append(f"input tap {jx} {jy}")
    if cmds:
        _exec_adb_shell_cmd("; ".join(cmds))

def batch_tap_sequence(coord_list, inter_delay=0.04, jitter=2):
    """
    Point #1 & #47: Sends a small batch of taps (such as 3x Gold Storage, 2x2 Storage Bars,
    or 3x Surrender/Return Home) in a single ADB shell line with safe micro-gaps.
    """
    check_pause_point(allow_raise=True)
    cmds = []
    scaled_gap = scale_time_by_speed(inter_delay, min_floor=0.02) if inter_delay > 0 else 0.0
    for idx, (x, y) in enumerate(coord_list):
        jx = int(x) + random.randint(-jitter, jitter)
        jy = int(y) + random.randint(-jitter, jitter)
        cmds.append(f"input tap {jx} {jy}")
        if scaled_gap >= 0.08 and idx < len(coord_list) - 1:
            cmds.append(f"sleep {scaled_gap:.2f}")
    if cmds:
        _exec_adb_shell_cmd("; ".join(cmds))
    if 0 < scaled_gap < 0.08:
        smart_sleep(scaled_gap * len(coord_list), apply_speed=False)

def swipe(x1, y1, x2, y2, duration=300, post_sleep=0.32):
    """Point #14: Optimized 300ms swipe duration and 0.32s post_sleep with speed scaling."""
    check_pause_point(allow_raise=True)
    sx1 = int(x1) + random.randint(-4, 4)
    sy1 = int(y1) + random.randint(-4, 4)
    sx2 = int(x2) + random.randint(-4, 4)
    sy2 = int(y2) + random.randint(-4, 4)
    scaled_dur = int(max(180, scale_time_by_speed(duration, min_floor=180) + random.randint(-15, 20)))
    _exec_adb_shell_cmd(f"input swipe {sx1} {sy1} {sx2} {sy2} {scaled_dur}")
    human_sleep(post_sleep, 0.04, apply_speed=True)

def get_screenshot(check_pause=True, force_fresh=False):
    """
    Point #37 & #48: In-Memory RAM Screenshot using io.BytesIO (zero disk wear, ~4MB fixed RAM)
    with a 0.18s micro-cache when no tap/swipe occurred in between.
    """
    if check_pause:
        check_pause_point(allow_raise=True)

    now = time.time()
    if (not force_fresh) and (_SCREENSHOT_CACHE["img"] is not None) and ((now - _SCREENSHOT_CACHE["timestamp"]) <= 0.18):
        return _SCREENSHOT_CACHE["img"]

    img = None
    try:
        proc = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
             timeout=8
        )
        if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 1024:
            bio = io.BytesIO(proc.stdout)
            loaded_img = Image.open(bio)
            loaded_img.load()
            img = loaded_img.convert("RGB")
            bio.close()
    except Exception:
        img = None

    if img is None:
        subprocess.run("adb exec-out screencap -p > screen.png", shell=True)
        img = Image.open("screen.png").convert("RGB")

    _SCREENSHOT_CACHE["img"] = img
    _SCREENSHOT_CACHE["timestamp"] = time.time()
    return img

def clean_ram_garbage():
    """Point #50: Periodic RAM garbage collection to keep 1GB free RAM completely fresh."""
    _invalidate_screen_cache()
    gc.collect()

# ==========================================
# 5. SCREEN SCANNERS (WRONG BUTTON, DAILY REWARD, MAINTENANCE, HOME & STORAGE)
# ==========================================
def is_red_x_box_at(img, cx, cy, radius=10):
    """Point #43: C-speed img.load() pixel access for Red 'X' button detection."""
    w, h = img.size
    px_map = img.load()
    red_count = 0
    white_count = 0
    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            px = min(max(0, cx + dx), w - 1)
            py = min(max(0, cy + dy), h - 1)
            r, g, b = px_map[px, py]
            if r > 175 and g < 85 and b < 85:
                red_count += 1
            elif r > 200 and g > 200 and b > 200:
                white_count += 1
    return (red_count >= 5 and white_count >= 1) or (red_count >= 9)

def _is_box_filled_green(px_map, w, h, x1, y1, x2, y2):
    """Checks if a Daily Reward claim box is predominantly Green (not black, red, or gray)."""
    green_px = 0
    total_px = 0
    for sy in range(max(0, y1 + 2), min(h, y2 - 1), 2):
        for sx in range(max(0, x1 + 4), min(w, x2 - 3), 4):
            r, g, b = px_map[sx, sy]
            total_px += 1
            # Bright/solid green button color criteria in CoC
            if g > 125 and g > (r + 25) and g > (b + 25):
                green_px += 1
    return total_px > 0 and (green_px / total_px) >= 0.35

def check_daily_reward_popup(img=None):
    """
    New Feature (Daily Reward Handler):
    Outer Box: (458, 113) to (1921, 930) | Top-Right Red Cross: (1858, 153)
    Scans all 7 reward boxes:
      1. (540, 467) to (753, 490)
      2. (839, 467) to (1042, 487)
      3. (1131, 468) to (1332, 488)
      4. (537, 782) to (744, 805)
      5. (844, 786) to (1033, 804)
      6. (1136, 791) to (1346, 812)
      7. (1435, 782) to (1731, 813)
    If any box is Green, clicks the green box(es) first, and then clicks the top-right Red 'X' (1858, 153).
    """
    if img is None:
        img = get_screenshot()
    w, h = img.size
    px_map = img.load()

    close_x, close_y = DAILY_REWARD_CLOSE_BTN
    has_close_red_x = is_red_x_box_at(img, close_x, close_y, radius=13)

    green_Found_indices = []
    for idx, (bx1, by1, bx2, by2) in enumerate(DAILY_REWARD_GREEN_BOXES, start=1):
        if _is_box_filled_green(px_map, w, h, bx1, by1, bx2, by2):
            green_Found_indices.append((idx, (bx1 + bx2) // 2, (by1 + by2) // 2))

    # Only trigger if the Daily Reward Red 'X' (1858, 153) is present OR at least one reward box is Green
    # while we are NOT on normal unobstructed Home Page
    if not has_close_red_x and not green_Found_indices:
        return False

    if not has_close_red_x and is_on_home_page_a14(img):
        return False

    print(f" [!] [DAILY REWARD] Popup detected (RedX_1858_153={has_close_red_x}, GreenBoxes={len(green_Found_indices)})!")
    for idx, cx, cy in green_Found_indices:
        print(f" [+] [DAILY REWARD] Box #{idx} is GREEN! Clicking ({cx}, {cy}) to claim...")
        tap(cx, cy, delay_range=(0.12, 0.22), jitter=3)
        human_sleep(0.28, 0.05)

    # After clicking all green boxes, click the top-right Red 'X' button (1858, 153)
    print(f" [x] [DAILY REWARD] Clicking Top-Right Red 'X' Button ({close_x}, {close_y})...")
    tap(close_x, close_y, delay_range=(0.12, 0.22), jitter=3)
    human_sleep(0.25, 0.05)
    return True

def check_and_handle_maintenance_break(img=None):
    """
    New Feature (Maintenance Break Handler):
    Box: (979, 16) to (1442, 63) -> Yellow Background with Black Capital Letters 'MAINTENANCE BREAK'.
    1. Checks pixel signature (Yellow background + Black letters).
    2. Verifies 'MAINTENANCE' via OCR.
    3. If confirmed: sleeps 10 minutes (600s), double-clicks (1210, 39), and repeats every 10 minutes
       until Maintenance Break ends!
    """
    if img is None:
        img = get_screenshot()

    def _is_maintenance_banner_visible(cur_img):
        w, h = cur_img.size
        px_map = cur_img.load()
        mx1, my1, mx2, my2 = MAINTENANCE_BREAK_BOX
        yellow_px = 0
        black_px = 0
        total_px = 0
        for sy in range(max(0, my1), min(h, my2), 2):
            for sx in range(max(0, mx1), min(w, mx2), 3):
                r, g, b = px_map[sx, sy]
                total_px += 1
                if r > 185 and g > 145 and b < 95 and (r + g) > (b * 3):
                    yellow_px += 1
                elif r < 80 and g < 80 and b < 80:
                    black_px += 1

        if total_px == 0 or (yellow_px / total_px) < 0.22 or black_px < 10:
            return False, ""

        # OCR Verification for 'MAINTENANCE' (Black letters on Yellow background)
        crop = cur_img.crop((mx1, my1, mx2, my2))
        upscaled = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
        uw, uh = upscaled.size
        u_src = upscaled.load()
        bw = Image.new("L", (uw, uh), 255)
        u_dst = bw.load()
        for py in range(uh):
            for px in range(uw):
                r, g, b = u_src[px, py]
                if r < 95 and g < 95 and b < 95:
                    u_dst[px, py] = 0
        padded = ImageOps.expand(bw, border=10, fill=255)
        cfg = "--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ "
        txt = pytesseract.image_to_string(padded, config=cfg).strip().upper()
        clean_t = re.sub(r"[^A-Z]", "", txt)
        if "MAINT" in clean_t or "TENANCE" in clean_t or "BREAK" in clean_t:
            return True, txt
        return False, txt

    is_maint, read_txt = _is_maintenance_banner_visible(img)
    if not is_maint:
        return False

    cycle_idx = 1
    while True:
        print("\n======================================================================")
        print(f"|| [⚠️ MAINTENANCE BREAK VERIFIED] Read: '{read_txt}' at (979,16..1442,63) ||")
        print(f"|| [REST #{cycle_idx}] Bot 10 Minute (600s) ke rest par ja raha hai...        ||")
        print("======================================================================\n")

        # Wait 10 minutes (pause/resume 'ZX'/'QW' aware, real time not shortened by speed-up)
        smart_sleep(MAINTENANCE_REST_SEC, apply_speed=False)

        print(f" [🔄 MAINTENANCE CHECK #{cycle_idx}] 10 Min complete! Clicking (1210, 39) 2 times...")
        tap(*MAINTENANCE_CLICK_COORD, delay_range=(0.15, 0.25), jitter=3, apply_speed=False)
        tap(*MAINTENANCE_CLICK_COORD, delay_range=(0.15, 0.25), jitter=3, apply_speed=False)
        smart_sleep(5.0, apply_speed=False)

        chk_img = get_screenshot(force_fresh=True)
        check_wrong_buttons_a14(chk_img)
        still_maint, read_txt = _is_maintenance_banner_visible(chk_img)
        if not still_maint:
            print(" [✔] [MAINTENANCE OVER] Maintenance Break khatam ho gaya hai! Resuming Bot...")
            return True
        cycle_idx += 1

def check_wrong_buttons_a14(img=None):
    """
    Scans the 10 Wrong-Button Cut coordinates AND checks Daily Reward Popup.
    Point #2: Shares screenshot cleanly and re-captures only when a button is actually cut.
    """
    if img is None:
        img = get_screenshot()
    clicked_any = False

    # Check Daily Reward Popup as part of Wrong Button protection
    if check_daily_reward_popup(img):
        clicked_any = True
        img = get_screenshot(force_fresh=True)

    for label, x, y in WRONG_BUTTON_CUT_COORDS:
        if is_red_x_box_at(img, x, y, radius=12):
            print(f" [!] [WRONG BUTTON CUT] '{label}' ({x}, {y}) par Red 'X' mila! Cut kar rahe hain...")
            tap(x, y, delay_range=(0.10, 0.18), jitter=2)
            clicked_any = True
            human_sleep(0.16, 0.03)
            img = get_screenshot(force_fresh=True)

    return clicked_any

def is_on_home_page_a14(img=None):
    """Checks (2050, 285) and (2050, 250) for the green box with a white '+' sign using fast px_map."""
    if img is None:
        img = get_screenshot()
    w, h = img.size
    px_map = img.load()
    for (cx, cy) in HOME_PAGE_CHECK_COORDS:
        green_pixels = 0
        white_pixels = 0
        for dy in range(-12, 13, 2):
            for dx in range(-12, 13, 2):
                px = min(max(0, cx + dx), w - 1)
                py = min(max(0, cy + dy), h - 1)
                r, g, b = px_map[px, py]
                if g > 135 and g > r + 25 and g > b + 25:
                    green_pixels += 1
                elif r > 210 and g > 210 and b > 210:
                    white_pixels += 1
        if green_pixels >= 6 and white_pixels >= 1:
            return True
    return False

def check_wrong_and_home_page_a14(img=None):
    """
    Point #2 (Conditional): Executes BOTH Wrong Button Check AND Home Page Check with 100% accuracy.
    If no wrong button was clicked, reuses the exact same screenshot for Home Page check to save ~0.7s.
    If any wrong button was cut, takes a fresh screenshot to verify Home Page status accurately.
    Returns (was_wrong_cut, is_home, latest_img).
    """
    if img is None:
        img = get_screenshot()
    was_cut = check_wrong_buttons_a14(img)
    if was_cut:
        img = get_screenshot(force_fresh=True)
    is_home = is_on_home_page_a14(img)
    return was_cut, is_home, img

def ensure_return_to_home_page_a14():
    """
    Ensures the bot is back on the Home Page (used after Resume 'QW' or ID Switch).
    Closes Upgrade menu, Daily Reward, or Wrong Buttons if open, and verifies Home Page Green '+'.
    """
    print(" [*] [HOME RECOVERY] Ensuring bot is cleanly on the Home Page...")
    for _ in range(3):
        img = get_screenshot(check_pause=False, force_fresh=True)
        check_and_handle_maintenance_break(img)
        if is_on_home_page_a14(img):
            check_wrong_buttons_a14(img)
            double_click_storage_bars()
            return True
        if is_red_x_box_at(img, *UPGRADE_A14["CLOSE_MENU"], radius=14):
            tap(*UPGRADE_A14["CLOSE_MENU"], delay_range=(0.18, 0.30), jitter=3, check_pause=False)
            time.sleep(0.40)
            continue
        check_wrong_buttons_a14(img)
        tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.10, 0.18), jitter=3, check_pause=False)
        double_click_storage_bars()
        time.sleep(0.50)
    return is_on_home_page_a14()

def click_gold_storage_3_times():
    """Point #1: Sends 3x Gold Storage clicks in a single fast batch command."""
    print(" [*] [HOME PAGE] Gold Storage Bar (2170, 63) par 3 baar click kar rahe hain...")
    batch_tap_sequence([GOLD_STORAGE_BAR] * 3, inter_delay=0.04, jitter=2)

def double_click_storage_bars():
    """Point #1 & #40: Sends 2x Gold + 2x Elixir Storage clicks in a single fast batch command."""
    global LAST_HOME_CLEANUP_TIME
    batch_tap_sequence(
        [GOLD_STORAGE_BAR, GOLD_STORAGE_BAR, ELIXIR_STORAGE_BAR, ELIXIR_STORAGE_BAR],
        inter_delay=0.04,
        jitter=2
    )
    LAST_HOME_CLEANUP_TIME = time.time()

def perform_home_cleanup_once(max_age_sec=1.5):
    """
    Point #40: Prevents duplicate back-to-back Wrong Button + Storage Bar cleanup on phase transitions
    if cleanup already ran within the last 1.5 seconds.
    """
    global LAST_HOME_CLEANUP_TIME
    if (time.time() - LAST_HOME_CLEANUP_TIME) <= max_age_sec:
        return
    img = get_screenshot()
    check_wrong_buttons_a14(img)
    double_click_storage_bars()
    LAST_HOME_CLEANUP_TIME = time.time()

def check_resources_full_for_upgrade(img=None):
    """
    Point #24 & #43: Single unified Storage Check for the Combined Upgrade System (Building + Wall).
    Uses C-speed px_map on Gold (2015, 43..2081, 78) & Elixir (2003, 116..2103, 151).
    """
    if img is None:
        img = get_screenshot()
    px_map = img.load()
    gx1, gy1, gx2, gy2 = GOLD_STORAGE_CHECK_BOX
    gold_total, gold_colored = 0, 0
    for y in range(gy1, gy2, 2):
        for x in range(gx1, gx2, 2):
            r, g, b = px_map[x, y]
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
            r, g, b = px_map[x, y]
            if r > 215 and g > 215 and b > 215:
                continue
            elixir_total += 1
            if r > 145 and b > 110 and r > (g + 25):
                elixir_colored += 1
    elixir_ratio = (elixir_colored / elixir_total) if elixir_total > 0 else 0.0

    is_gold_full = gold_ratio >= 0.45
    is_elixir_full = elixir_ratio >= 0.45
    print(f" [i] [COMBINED STORAGE SCAN] Gold Yellow: {gold_ratio*100:.0f}% (Full={is_gold_full}) | Elixir Pink: {elixir_ratio*100:.0f}% (Full={is_elixir_full})")
    return is_gold_full or is_elixir_full

def check_wall_resources_full_a14(img=None):
    """Point #24: Wall storage check is now unified with Building storage check."""
    return check_resources_full_for_upgrade(img=img)

# ==========================================
# 6. BUILDER CHECK BOX READER & OCR FUNDAMENTALS (#3, #42-#46, #49)
# ==========================================
def has_enough_ink_pixels(bw_img, min_black_px=8):
    """Point #42: Fast pre-check to skip Tesseract only if a cropped box is completely blank white."""
    w, h = bw_img.size
    px = bw_img.load()
    black_cnt = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if px[x, y] == 0:
                black_cnt += 1
                if black_cnt >= min_black_px:
                    return True
    return False

def trim_binary_horizontal_whitespace(bw_img, extra_pad=8):
    """Point #46: Trims trailing blank white space on wide text crops while preserving 100% letter accuracy."""
    inv = ImageOps.invert(bw_img)
    bbox = inv.getbbox()
    if not bbox:
        return bw_img
    left, top, right, bottom = bbox
    w, h = bw_img.size
    c_left = max(0, left - extra_pad)
    c_right = min(w, right + extra_pad)
    return bw_img.crop((c_left, 0, c_right, h))

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
    """
    Point #3 & #23: Fast BILINEAR 3x zoom + dawg-disabled OCR with full Left-Crop fallback
    so 100% accuracy is maintained and LAST_DETECTED_BUILDERS is recorded.
    """
    global LAST_DETECTED_BUILDERS, LAST_BUILDER_CHECK_TIME
    if img is None:
        img = get_screenshot()
    x1, y1, x2, y2 = UPGRADE_A14["BUILDER_CHECK_BOX"]
    w = x2 - x1
    crop = img.crop((x1 - 2, y1 - 2, x2 + 2, y2 + 2))
    large = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.BILINEAR).convert('L')
    cfg = '--oem 3 --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0 -c tessedit_char_whitelist=0123456789/|Il!'

    for thresh in [180, 168, 192]:
        bw = large.point(lambda p: 0 if p > thresh else 255, '1').convert('L')
        padded = ImageOps.expand(bw, border=10, fill=255)
        txt = pytesseract.image_to_string(padded, config=cfg).strip()
        val = parse_builder_fraction(txt)
        if val is not None:
            print(f" [i] [BUILDER OCR] Box (1754,1008..1847,1038) Read: '{txt}' -> {val} Builders Free")
            LAST_DETECTED_BUILDERS = val
            LAST_BUILDER_CHECK_TIME = time.time()
            return val

    # Full Left-Crop Fallback preserved for 100% accuracy
    left_crop = img.crop((x1 - 2, y1, x1 + int(w * 0.42), y2))
    l_large = left_crop.resize((left_crop.width * 3, left_crop.height * 3), Image.Resampling.BILINEAR).convert('L')
    l_bw = ImageOps.expand(l_large.point(lambda p: 0 if p > 175 else 255, '1').convert('L'), border=10, fill=255)
    l_txt = pytesseract.image_to_string(
        l_bw,
        config='--oem 3 --psm 10 -c load_system_dawg=0 -c load_freq_dawg=0 -c tessedit_char_whitelist=0123456|Il!'
    ).strip()
    if l_txt in ['|', 'I', 'l', '!']:
        print(f" [i] [BUILDER LEFT-OCR] Read '{l_txt}' -> 1 Builder Free")
        LAST_DETECTED_BUILDERS = 1
        LAST_BUILDER_CHECK_TIME = time.time()
        return 1
    if l_txt.isdigit() and int(l_txt[0]) <= 6:
        val = int(l_txt[0])
        print(f" [i] [BUILDER LEFT-OCR] Read '{l_txt[0]}' -> {val} Builders Free")
        LAST_DETECTED_BUILDERS = val
        LAST_BUILDER_CHECK_TIME = time.time()
        return val

    LAST_DETECTED_BUILDERS = 0
    LAST_BUILDER_CHECK_TIME = time.time()
    return 0

def is_text_matching_wall(raw_text):
    """Checks if OCR text starts with or clearly represents 'Wall' (all 10 regex patterns preserved)."""
    if not raw_text:
        return False
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', raw_text).lower()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return False

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
    """Permanently bypassed as instructed to save time and avoid second-time OCR read failures."""
    return True, "Wall"

def classify_building_name_a14(raw_ocr_text):
    if not raw_ocr_text:
        return "UNKNOWN", ""
    cleaned = re.sub(r'[^a-zA-Z0-9\s\-]', '', raw_ocr_text)
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
echo "✔ Part 1 (bot_tools.py) 100% Complete & Updated!"
