cat << 'EOF' > bot_attack.py
import time
import traceback
import bot_tools
from bot_tools import (
    RestartLoopException,
    BotPausedResumeHomeException,
    FAST_ATTACK,
    tap,
    fast_serial_taps,
    batch_tap_sequence,
    get_screenshot,
    smart_sleep,
    human_sleep,
    check_pause_point,
    check_wrong_buttons_a14,
    check_daily_reward_popup,
    check_and_handle_maintenance_break,
    is_on_home_page_a14,
    check_wrong_and_home_page_a14,
    click_gold_storage_3_times
)

# Point #4 (Preserved 100%): Full 45.0s Battle Timer
BATTLE_TIMER_DURATION_SEC = 45.0

# ==========================================
# 1. CLOUD, BATTLEFIELD & EARLY VICTORY DETECTORS (POINTS #28 & #29)
# ==========================================

def is_cloud_screen_a14(img):
    """
    Point #28 (Cloud Detector):
    Detects if the screen is currently covered in white/light-gray/hazy matchmaking clouds
    so the bot NEVER confuses matchmaking clouds with the Home Page or an active battlefield.
    """
    w, h = img.size
    px_map = img.load()
    cloud_px = 0
    total_px = 0

    for sy in range(200, min(h - 180, 860), 28):
        for sx in range(350, min(w - 300, 2050), 40):
            r, g, b = px_map[sx, sy]
            total_px += 1
            # Matchmaking clouds are bright white/light-gray/warm-white with low color saturation
            if r > 175 and g > 175 and b > 165 and (max(r, g, b) - min(r, g, b) <= 38):
                cloud_px += 1

    return total_px > 0 and (cloud_px / float(total_px)) >= 0.55

def is_enemy_battlefield_loaded_a14(img):
    """
    Point #28 (Battlefield Detector):
    Verifies that:
      1. We are NOT in matchmaking clouds.
      2. We are NOT on the Home Page (Green '+' is absent).
      3. The red/white Surrender / End Battle button at (181, 800) is clearly visible on screen.
    """
    if is_cloud_screen_a14(img):
        return False
    if is_on_home_page_a14(img):
        return False

    w, h = img.size
    px_map = img.load()
    sx_center, sy_center = FAST_ATTACK["SURRENDER_BTN"]

    red_btn_px = 0
    white_txt_px = 0
    for dy in range(-22, 23, 2):
        for dx in range(-45, 46, 3):
            px = min(max(0, sx_center + dx), w - 1)
            py = min(max(0, sy_center + dy), h - 1)
            r, g, b = px_map[px, py]
            if r > 165 and g < 90 and b < 90:
                red_btn_px += 1
            elif r > 200 and g > 200 and b > 200 and (max(r, g, b) - min(r, g, b) <= 30):
                white_txt_px += 1

    return red_btn_px >= 10 and white_txt_px >= 3

def is_return_home_victory_button_visible_a14(img):
    """
    Point #29 (Early 100% Victory / Battle End Detector):
    Checks if the green 'Return Home' button at (1222, 918) has already appeared on screen
    during the 45s battle timer (indicating the attack finished early).
    """
    w, h = img.size
    px_map = img.load()
    rx, ry = FAST_ATTACK["RETURN_HOME_BTN"]

    green_px = 0
    white_px = 0
    total_px = 0
    for dy in range(-20, 21, 2):
        for dx in range(-60, 61, 4):
            px = min(max(0, rx + dx), w - 1)
            py = min(max(0, ry + dy), h - 1)
            r, g, b = px_map[px, py]
            total_px += 1
            if g > 135 and g > (r + 25) and g > (b + 25):
                green_px += 1
            elif r > 210 and g > 210 and b > 210 and (max(r, g, b) - min(r, g, b) <= 28):
                white_px += 1

    return total_px > 0 and (green_px / float(total_px)) >= 0.30 and white_px >= 4

def scan_battlefield_or_restart(stage_name):
    """
    Point #2 (Conditional): Checks Wrong Buttons and Home Page Green '+' icon during attack pauses
    by sharing the screenshot cleanly while guaranteeing 100% accuracy for both checks.
    If either is detected, raises RestartLoopException to restart the Attack Loop.
    """
    check_pause_point(allow_raise=True)
    print(f" [SCAN] [{stage_name}] Checking Wrong Buttons & Home Page status...")
    img = get_screenshot(force_fresh=True)

    # Do not false-trigger if screen is momentarily in clouds
    if is_cloud_screen_a14(img):
        print(f" [i] [{stage_name}] Clouds still visible; waiting 2.0s to clear...")
        smart_sleep(2.0)
        img = get_screenshot(force_fresh=True)

    wrong_found, home_found, _ = check_wrong_and_home_page_a14(img)
    if wrong_found or home_found:
        reason = "Wrong Button detected" if wrong_found else "Still stuck on Home Page (Green '+' visible)"
        print(f" [!] [ALERT at {stage_name}] {reason}! Restarting Attack Loop...")
        raise RestartLoopException(reason)

def wait_for_enemy_base_load_smart(max_wait_sec=18.0):
    """
    Point #28: Dynamic Enemy Base Load with Cloud Recognition.
      - Waits a safe minimum of 3.8s after clicking Attack (1980, 972).
      - Polls every 0.9s up to 18.0s max:
          * If Clouds are detected -> keeps waiting calmly.
          * If Enemy Battlefield is confirmed -> breaks early to save 8-12s per attack!
          * If stuck on Home Page or Wrong Button -> restarts immediately!
    """
    min_initial_wait = 3.8
    print(f" [SMART 18s LOAD] Waiting initial {min_initial_wait:.1f}s (Max {max_wait_sec:.0f}s) for Enemy Base...")
    start_t = time.time()
    smart_sleep(min_initial_wait, apply_speed=False)

    while (time.time() - start_t) < max_wait_sec:
        check_pause_point(allow_raise=True)
        img = get_screenshot(force_fresh=True)
        elapsed = time.time() - start_t

        if is_cloud_screen_a14(img):
            print(f" [☁️ CLOUDS] Matchmaking clouds visible ({elapsed:.1f}s/{max_wait_sec:.0f}s)... Waiting for base...")
        elif is_enemy_battlefield_loaded_a14(img):
            print(f" [✔] [BASE LOADED EARLY] Enemy Battlefield confirmed in {elapsed:.1f}s (Saved {max_wait_sec - elapsed:.1f}s)!")
            human_sleep(0.30, 0.04)
            return True
        else:
            # After 6.5s, if neither clouds nor battlefield, check if stuck on Wrong Button or Home Page
            if elapsed >= 6.5:
                wrong_found, home_found, _ = check_wrong_and_home_page_a14(img)
                if wrong_found or home_found:
                    reason = "Wrong Button detected during matchmaking" if wrong_found else "Stuck on Home Page after clicking Attack"
                    print(f" [!] [LOAD ALERT] {reason}! Restarting Attack Loop...")
                    raise RestartLoopException(reason)

        rem = max_wait_sec - (time.time() - start_t)
        if rem <= 0:
            break
        smart_sleep(min(0.90, rem), apply_speed=False)

    return False

# ==========================================
# 2. MASTER FAST ATTACK EXECUTION
# ==========================================

def execute_attack(is_first_attack=True):
    for attempt in range(1, 4):
        try:
            check_pause_point(allow_raise=True)
            print("\n======================================================================")
            print(f" || [FAST ATTACK LOOP - 45s TIMER] - ATTEMPT #{attempt} ||")
            print("======================================================================")

            # 1. Home Page: Point #5 & #6 -> Merged 0.6s Wait + Wrong Button Check + Single 3x Gold Storage Click
            print(" [0.6s] Checking Home Page & clicking Gold Storage 3x...")
            smart_sleep(0.6, apply_speed=True)
            check_wrong_buttons_a14()
            click_gold_storage_3_times()

            # 2. Matchmaking (0.2s -> Battle -> 0.35s -> Find Match -> 0.65s -> Attack)
            print(" [0.2s] Clicking Battle Button (182, 961)...")
            smart_sleep(0.20, apply_speed=True)
            tap(*FAST_ATTACK["BATTLE_BTN"], delay_range=(0.05, 0.10), jitter=3)

            print(" [0.35s] Waiting 0.35s -> Clicking Find Match (364, 808)...")
            smart_sleep(0.35, apply_speed=True)
            tap(*FAST_ATTACK["FIND_MATCH_BTN"], delay_range=(0.05, 0.10), jitter=3)

            print(" [0.65s] Waiting 0.65s -> Clicking Attack Button (1980, 972)...")
            smart_sleep(0.65, apply_speed=True)
            tap(*FAST_ATTACK["ATTACK_BTN"], delay_range=(0.05, 0.10), jitter=3)

            # 3. Point #28: Smart 18s Enemy Base Load (Cloud-aware) + Screen Check #1
            wait_for_enemy_base_load_smart(max_wait_sec=18.0)
            scan_battlefield_or_restart("Post-18s Base Load Check")

            # 4. Point #7: Spell Select (1527, 983) -> Safe 0.22s -> 2 Rounds Deploy (Starts 45s Battle Timer)
            print(" [0.22s] Selecting Spell (1527, 983)...")
            smart_sleep(0.22, apply_speed=True)
            tap(*FAST_ATTACK["SPELL_SELECT"], delay_range=(0.04, 0.08), jitter=2)
            spell_select_timer = time.time()

            print(" [0.22s] Deploying Spells (2 Rounds in Serial Order)...")
            smart_sleep(0.22, apply_speed=True)
            fast_serial_taps(FAST_ATTACK["SPELL_DEPLOY_LIST"], rounds=2, jitter=3)

            # 5. Point #7: Army 1 Select (470, 988) -> 4 Rounds Deploy
            print(" [0.22s] Selecting Army 1 (470, 988)...")
            smart_sleep(0.22, apply_speed=True)
            tap(*FAST_ATTACK["ARMY_1_SELECT"], delay_range=(0.04, 0.08), jitter=2)

            print(" [*] Deploying Army 1 (4 Rounds in Serial Order: 325,525 -> 375,524)...")
            fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=4, jitter=3)

            # 6. Point #7: Army 2 Select (590, 985) -> 2 Rounds Deploy
            print(" [0.22s] Selecting Army 2 (590, 985)...")
            smart_sleep(0.22, apply_speed=True)
            tap(*FAST_ATTACK["ARMY_2_SELECT"], delay_range=(0.04, 0.08), jitter=2)

            print(" [0.22s] Deploying Army 2 (2 Rounds on 3 Coords)...")
            smart_sleep(0.22, apply_speed=True)
            fast_serial_taps(FAST_ATTACK["ARMY_2_DEPLOY_LIST"], rounds=2, jitter=3)

            # 7. Point #30: Siege Machine + Heroes 1-4 (1 Round each on Army 1 Coords via Persistent ADB Shell)
            print(" [*] Deploying Siege Machine & Heroes 1-4 (1 Round each on Army 1 Coords)...")
            siege_and_heroes = [
                ("Siege Machine", FAST_ATTACK["SIEGE_SELECT"]),
                ("Hero 1", FAST_ATTACK["HERO_1_SELECT"]),
                ("Hero 2", FAST_ATTACK["HERO_2_SELECT"]),
                ("Hero 3", FAST_ATTACK["HERO_3_SELECT"]),
                ("Hero 4", FAST_ATTACK["HERO_4_SELECT"])
            ]
            for unit_name, select_coord in siege_and_heroes:
                check_pause_point(allow_raise=True)
                print(f" -> Selecting {unit_name} {select_coord} & deploying 1 Round...")
                tap(*select_coord, delay_range=(0.05, 0.08), jitter=2)
                fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=1, jitter=3)

            # 8. Hero Abilities Activation + Screen Check #2
            print(" [2.0s] Waiting 2s -> Activating Hero 1, 2, 3, 4 Abilities...")
            smart_sleep(2.0, apply_speed=True)
            for h_idx, h_coord in enumerate([
                FAST_ATTACK["HERO_1_SELECT"],
                FAST_ATTACK["HERO_2_SELECT"],
                FAST_ATTACK["HERO_3_SELECT"],
                FAST_ATTACK["HERO_4_SELECT"]
            ], start=1):
                check_pause_point(allow_raise=True)
                print(f" -> Activating Hero {h_idx} Ability at {h_coord}...")
                tap(*h_coord, delay_range=(0.06, 0.12), jitter=2)

            elapsed_deploy = time.time() - spell_select_timer
            print(f" [i] Full Deployment & Abilities completed in {elapsed_deploy:.1f} seconds!")

            scan_battlefield_or_restart("Post-Hero-4-Ability Check")

            # 9. Point #4 (45s Battle Timer) + Point #29 (Early 100% Victory Return Home Detector)
            battle_ended_early = False
            while True:
                check_pause_point(allow_raise=True)
                elapsed_since_spell = time.time() - spell_select_timer
                rem_wait = BATTLE_TIMER_DURATION_SEC - elapsed_since_spell
                if rem_wait <= 0:
                    break

                # After 20s of battle, check every 2.5s if 100% Victory / Return Home (1222, 918) already appeared
                if elapsed_since_spell >= 20.0:
                    b_img = get_screenshot(force_fresh=True)
                    if is_return_home_victory_button_visible_a14(b_img):
                        print(f" [✔] [EARLY BATTLE END] Return Home button (1222, 918) detected at {elapsed_since_spell:.1f}s! Skipping Surrender...")
                        battle_ended_early = True
                        break
                    chunk = min(2.5, rem_wait)
                    print(f" [45s TIMER] {rem_wait:.1f}s remaining in 45s Battle Timer...")
                    smart_sleep(chunk, apply_speed=False)
                else:
                    wait_to_20 = min(rem_wait, max(0.5, 20.0 - elapsed_since_spell))
                    print(f" [45s TIMER] Waiting {rem_wait:.1f}s to complete 45s Battle Timer from Spell Select...")
                    smart_sleep(wait_to_20, apply_speed=False)

            # 10. Point #8 (Preserved Delays: 0.6s -> 1.1s -> 1.1s) + Point #31 (Batch Return Home & Green '+' Check)
            if not battle_ended_early:
                print(" [SURRENDER] Clicking Surrender Button (181, 800) 3 times...")
                batch_tap_sequence([FAST_ATTACK["SURRENDER_BTN"]] * 3, inter_delay=0.08, jitter=3)

                print(" [0.6s] Waiting 0.6s -> Clicking Okay Button (1419, 701)...")
                smart_sleep(0.6)
                tap(*FAST_ATTACK["OKAY_BTN"], delay_range=(0.08, 0.14), jitter=3)

                print(" [1.1s] Waiting 1.1s before Return Home...")
                smart_sleep(1.1)

                print(" [SCAN] [Pre-Return-Home Check] Checking Wrong Buttons...")
                img_pre_ret = get_screenshot(force_fresh=True)
                check_wrong_buttons_a14(img_pre_ret)

            print(" [RETURN] Clicking Return Home Button (1222, 918) 3 times...")
            batch_tap_sequence([FAST_ATTACK["RETURN_HOME_BTN"]] * 3, inter_delay=0.08, jitter=3)

            # Point #8 & #31: 1.1s settle with smart Home Page Green '+' & Wrong Button verification
            print(" [1.1s] Waiting 1.1s to settle on Home Page...")
            smart_sleep(1.1)
            check_wrong_and_home_page_a14()

            # Point #5: Duplicate click_gold_storage_3_times() at end of Step 10 removed (runs once in Step 1)
            print(" [✔] [FAST ATTACK COMPLETE] Fast Attack Cycle Finished Successfully!\n")
            return True

        except BotPausedResumeHomeException:
            # Propagate immediately to main_bot so it recovers to Home Page and resumes current attack count
            raise
        except RestartLoopException as re_err:
            print(f"\n [RESTARTING ATTACK] Reason: {re_err}")
            check_wrong_buttons_a14()
            smart_sleep(0.8)
            continue
        except Exception as e:
            print("\n[! ERROR!] Fast Attack Loop me error aayi:")
            traceback.print_exc()
            return False

    return False
EOF

cat << 'EOF' > main_bot.py
import time
import random
import traceback
import bot_tools
from bot_tools import (
    BotPausedResumeHomeException,
    start_pause_resume_listener,
    check_pause_point,
    smart_sleep,
    human_sleep,
    set_bot_speed_multiplier,
    get_bot_speed_multiplier,
    check_wrong_buttons_a14,
    check_daily_reward_popup,
    check_and_handle_maintenance_break,
    double_click_storage_bars,
    perform_home_cleanup_once,
    ensure_return_to_home_page_a14,
    check_resources_full_for_upgrade,
    clean_ram_garbage
)
from bot_upgrade import (
    run_a14_combined_upgrade_loop
)
from bot_attack import execute_attack
from bot_id_switch import (
    load_id_memory,
    save_id_memory,
    get_id_role_label,
    switch_to_target_id
)

# ==========================================
# 1. ADVANCE FEATURES MENU (GAME SPEED-UP: 1.0x TO 2.25x) & BOT MODE MENU
# ==========================================

ADVANCE_SPEED_TABLE = [
    ("A", 1.00, "Standard Speed (Default - 100% As Coded)"),
    ("B", 1.10, "1.10x Fast Speed"),
    ("C", 1.15, "1.15x Fast Speed"),
    ("D", 1.20, "1.20x Fast Speed"),
    ("E", 1.25, "1.25x Fast Speed"),
    ("F", 1.30, "1.30x Fast Speed"),
    ("G", 1.35, "1.35x Fast Speed"),
    ("H", 1.40, "1.40x Fast Speed"),
    ("I", 1.45, "1.45x Fast Speed"),
    ("J", 1.50, "1.50x Turbo Speed"),
    ("K", 1.55, "1.55x Turbo Speed"),
    ("L", 1.60, "1.60x Turbo Speed"),
    ("M", 1.65, "1.65x Turbo Speed"),
    ("N", 1.70, "1.70x Turbo Speed"),
    ("O", 1.75, "1.75x Turbo Speed"),
    ("P", 1.80, "1.80x Ultra Speed"),
    ("Q", 1.85, "1.85x Ultra Speed"),
    ("R", 1.90, "1.90x Ultra Speed"),
    ("S", 1.95, "1.95x Ultra Speed"),
    ("T", 2.00, "2.00x Ultra Speed"),
    ("U", 2.05, "2.05x Extreme Speed"),
    ("V", 2.10, "2.10x Extreme Speed"),
    ("W", 2.15, "2.15x Extreme Speed"),
    ("X", 2.20, "2.20x Extreme Speed"),
    ("Y", 2.25, "2.25x Maximum Speed Limit")
]

def open_advance_features_menu():
    """
    Opens the Advance Features Menu -> Game Speed-Up Controller (A = 1.00x Standard up to Y = 2.25x).
    Persists across the entire bot session (including ZX Pause & QW Resume) until bot is stopped/restarted.
    """
    letter_to_speed = {letter: mult for letter, mult, _ in ADVANCE_SPEED_TABLE}

    while True:
        cur_spd = get_bot_speed_multiplier()
        print("\n======================================================================")
        print(" ||        ⚡ ADVANCE FEATURES MENU - GAME SPEED-UP SYSTEM ⚡        ||")
        print("======================================================================")
        print(f" || Current Active Bot Speed : {cur_spd:.2f}x                               ||")
        print("----------------------------------------------------------------------")
        print(" || Select Game Speed-Up Option (A to Y):                          ||")
        for letter, mult, desc in ADVANCE_SPEED_TABLE:
            marker = " <-- [ACTIVE]" if abs(cur_spd - mult) < 0.005 else ""
            print(f" ||   [{letter}] -> {mult:.2f}x  ({desc}){marker}")
        print("----------------------------------------------------------------------")
        print(" ||   [0] -> Back to Main Bot Operating Menu                       ||")
        print("======================================================================")

        raw_in = input("\n Speed Option type karein (A se Y tak, ya 0 wapas jane ke liye) [Default=A (1.00x)]: ").strip().upper()
        if raw_in == "":
            set_bot_speed_multiplier(1.00)
            break
        if raw_in == "0":
            break
        if raw_in in letter_to_speed:
            chosen_mult = letter_to_speed[raw_in]
            set_bot_speed_multiplier(chosen_mult)
            print(f" [✔] Game Speed-Up '{raw_in}' ({chosen_mult:.2f}x) successfully activate ho gaya hai!")
            break
        # Also allow direct numeric entry like 1.25 or 2.25
        try:
            val = float(raw_in.replace("X", ""))
            if 1.0 <= val <= 2.25:
                set_bot_speed_multiplier(val)
                print(f" [✔] Custom Game Speed-Up ({val:.2f}x) successfully activate ho gaya hai!")
                break
        except Exception:
            pass
        print(" [!] Galat input! Kripya A se Y ke beech ka letter (jaise A, B, C, D, E...) type karein.")

def select_bot_configuration():
    while True:
        cur_spd = get_bot_speed_multiplier()
        print("\n======================================================================")
        print(" ||   CLASH OF CLANS AI BOT - SAMSUNG GALAXY A14 ULTIMATE EDITION  ||")
        print("======================================================================")
        print(f" || Active Game Speed Multiplier : {cur_spd:.2f}x {'(Standard Default)' if abs(cur_spd - 1.0) < 0.005 else '(Advance Speed-Up Active!)'}")
        print("----------------------------------------------------------------------")
        print(" || Select Bot Operating Mode (1 to 7):                            ||")
        print(" || [1] -> Fast Attack Only            (सिर्फ फास्ट अटैक - Infinity)  ||")
        print(" || [2] -> Combined Upgrade Only       (बिल्डिंग + वॉल अपग्रेड - 1m) ||")
        print(" || [3] -> Tried All                   (Combined Upgrade + Attack) ||")
        print(" || [4] -> ID Changement Only          (सिर्फ ID चेंज - हर 10 सेकंड)  ||")
        print(" || [5] -> ID Changement + Fast Attack (हर ID पर 10 Min अटैक स्विच)  ||")
        print(" || [6] -> ID Changement + Tried All   (Fully Botted System)       ||")
        print(" || [7] -> Advance Features            (Game Speed-Up: 1.0x–2.25x) ||")
        print("======================================================================")
        print(" || Live Controls Inside Termux:                                   ||")
        print(" || Pause Bot : Type 'ZX' (or 'zx') anytime                        ||")
        print(" || Resume Bot: Type 'QW' (or 'qw') anytime (Resumes at Same Speed)||")
        print("======================================================================")

        choice = input("\n Apna Option type karein (1/2/3/4/5/6/7) [Default=6 (Fully Botted)]: ").strip()
        if choice == "":
            choice = "6"

        if choice == "7":
            open_advance_features_menu()
            continue

        if choice in ["1", "2", "3", "4", "5", "6"]:
            break
        print(" [!] Galat input! Kripya 1 se 7 ke beech ka number type karein.")

    mode_names = {
        "1": "FAST ATTACK ONLY (सिर्फ फास्ट अटैक Infinity)",
        "2": "COMBINED UPGRADE ONLY (बिल्डिंग + वॉल कंबाइंड अपग्रेड - 1 Min Gap)",
        "3": "TRIED ALL: COMBINED UPGRADE + 10 FAST ATTACKS LOOP",
        "4": "ID CHANGEMENT ONLY (हर 10 सेकंड पर ID स्विच - Min 3.5s Dynamic Load)",
        "5": "ID CHANGEMENT + FAST ATTACK (हर ID पर 10 मिनट फास्ट अटैक)",
        "6": "ID CHANGEMENT + TRIED ALL (FULLY BOTTED: COMBINED UPGRADE + ATTACK + ID SWITCH)"
    }
    print(f"\n [✔] Selected Mode: [{choice}] -> {mode_names[choice]} | Speed: {get_bot_speed_multiplier():.2f}x")

    total_ids = 1
    start_id_index = 1

    if choice in ["4", "5", "6"]:
        mem = load_id_memory()
        default_total = mem.get("total_ids", 10)
        if default_total < 1 or default_total > 100:
            default_total = 10

        while True:
            raw_total = input(f" Total IDs type karein (1 se 100 ke beech, First 4 = Main ID) [Default={default_total}]: ").strip()
            if raw_total == "":
                total_ids = default_total
                break
            if raw_total.isdigit() and 1 <= int(raw_total) <= 100:
                total_ids = int(raw_total)
                break
            print(" [!] Kripya 1 se 100 ke beech ka sahi number type karein.")

        saved_idx = mem.get("current_id_index", 1)
        if 1 < saved_idx <= total_ids:
            ans = input(f" Pichhli baar Bot ID #{saved_idx} par tha. Kya ID #{saved_idx} se Resume karein? (y/n) [Default=n (Start from ID #1)]: ").strip().lower()
            if ans == "y":
                start_id_index = saved_idx

        mem["total_ids"] = total_ids
        mem["current_id_index"] = start_id_index
        save_id_memory(mem)
        print(f" [✔] ID Changement Configured: Total IDs = {total_ids} | Starting on ID #{start_id_index} [{get_id_role_label(start_id_index)}]")

    input("\n Bot Start karne ke liye [ENTER] key dabayein: ")
    return choice, total_ids, start_id_index

# ==========================================
# 2. MASTER COMBINED UPGRADE & ATTACK HELPERS (POINTS #24, #25, #40)
# ==========================================

def run_combined_building_and_wall_upgrade(loop_label="COMBINED UPGRADE"):
    """
    Point #24 & #25:
    Unified Combined Upgrade (Building First -> Direct Menu Handoff -> Wall Second):
      1. Runs Home Page cleanup once (Point #40) + checks Daily Reward & Maintenance Break.
      2. Performs a SINGLE Storage Check (check_resources_full_for_upgrade).
      3. If storage is full, opens Build menu once and runs Building Upgrade followed directly
         by Wall Upgrade inside the same menu without closing in between!
    Returns (building_upgraded, wall_upgraded, any_upgraded).
    """
    check_pause_point(allow_raise=True)
    print("\n----------------------------------------------------------------------")
    print(f" | [{loop_label}] Single Storage Check -> Building -> Wall Handoff |")
    print("----------------------------------------------------------------------")

    perform_home_cleanup_once(max_age_sec=1.5)
    human_sleep(0.18, 0.04)

    img = bot_tools.get_screenshot()
    check_and_handle_maintenance_break(img)
    if check_daily_reward_popup(img):
        img = bot_tools.get_screenshot(force_fresh=True)

    print(f"\n [{loop_label}] Checking Gold & Elixir Storage Boxes for Combined Upgrade...")
    if check_resources_full_for_upgrade(img):
        print(" [+] Storage Box is FULL! Starting Combined Upgrade (Building -> Wall) in 0.20s...")
        human_sleep(0.20, 0.04)
        b_up, w_up, any_up = run_a14_combined_upgrade_loop()
    else:
        print(" [-] Storage Box is not full yet. Skipping Combined Upgrade...")
        b_up, w_up, any_up = False, False, False

    print(f" [{loop_label} RESULT] Building Upgraded: {b_up} | Wall Upgraded: {w_up} | Any Upgraded: {any_up}")
    return b_up, w_up, any_up

def run_n_fast_attacks_with_resume_memory(state_dict, target_attacks, phase_label="ATTACK SERIES"):
    """
    Executes 'target_attacks' Fast Attacks sequentially while saving progress in state_dict["attacks_done"].
    Point #6: Uses merged 0.2s-0.4s pre_attack_wait.
    Also runs periodic Daily Reward & Maintenance Break checks after completing the attack block.
    """
    while state_dict["attacks_done"] < target_attacks:
        check_pause_point(allow_raise=True)
        next_atk_num = state_dict["attacks_done"] + 1
        pre_attack_wait = random.uniform(0.20, 0.40)
        print(f"\n [{phase_label}] Attack #{next_atk_num} / {target_attacks} starting in {pre_attack_wait:.2f}s (Speed={get_bot_speed_multiplier():.2f}x)...")
        smart_sleep(pre_attack_wait, apply_speed=True)

        execute_attack(is_first_attack=(next_atk_num == 1))
        state_dict["attacks_done"] += 1
        print(f" [✔] [{phase_label}] Completed Attack #{state_dict['attacks_done']} / {target_attacks}!")

    # Post-attack-series check for Daily Reward Popup & Maintenance Break
    chk_img = bot_tools.get_screenshot(force_fresh=True)
    check_and_handle_maintenance_break(chk_img)
    check_daily_reward_popup(chk_img)

# ==========================================
# 3. MASTER LOOP CONTROLLER (MODES 1 TO 6 + ADVANCE SPEED ENGINE)
# ==========================================

def main_loop():
    bot_mode, total_ids, current_id = select_bot_configuration()

    # Start background keyboard listener for 'ZX' (Pause) and 'QW' (Resume)
    start_pause_resume_listener()

    startup_rest = random.uniform(0.8, 1.2)
    print(f"\n[STARTUP] Taking {startup_rest:.1f} seconds initial rest on Home Page (Speed={get_bot_speed_multiplier():.2f}x)...")
    smart_sleep(startup_rest, apply_speed=True)

    cycle_count = 1

    # Persistent runtime state so Pause ('ZX') / Resume ('QW') never forgets progress
    runtime_state = {
        "current_id": current_id,
        "phase": "START_CYCLE",        # Tracks sub-phase within Mode 3, 5, 6
        "attacks_done": 0,             # Tracks how many attacks completed in current 10-attack or 5-attack block
        "id_timer_start": None,        # Mode 5: 10-minute timer start timestamp
        "id_elapsed_sec": 0.0,         # Mode 5: accumulated active seconds on current ID
        "loop2_any_upgraded": False    # Mode 6: result of Second Combined Upgrade Loop
    }

    while True:
        try:
            check_pause_point(allow_raise=True)
            active_id = runtime_state["current_id"]
            id_role = get_id_role_label(active_id)
            cur_spd = get_bot_speed_multiplier()

            print("\n" + "=" * 70)
            if bot_mode in ["4", "5", "6"]:
                print(f" MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}] | SPEED: {cur_spd:.2f}x | ACTIVE ID: #{active_id}/{total_ids} [{id_role}]")
            else:
                print(f" MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}] | SPEED: {cur_spd:.2f}x")
            print("=" * 70)

            # Check Maintenance Break & Daily Reward at the start of every Master Cycle
            cycle_img = bot_tools.get_screenshot()
            check_and_handle_maintenance_break(cycle_img)
            check_daily_reward_popup(cycle_img)

            # ------------------------------------------------------------------
            # MODE 1: FAST ATTACK ONLY (Continues Infinitely)
            # ------------------------------------------------------------------
            if bot_mode == "1":
                pre_wait = random.uniform(0.20, 0.40)
                print(f" [MODE 1] Starting Fast Attack in {pre_wait:.2f}s...")
                smart_sleep(pre_wait, apply_speed=True)
                execute_attack(is_first_attack=(cycle_count == 1))

            # ------------------------------------------------------------------
            # MODE 2: COMBINED UPGRADE ONLY (Building + Wall Combined - Every 1 Minute Gap)
            # ------------------------------------------------------------------
            elif bot_mode == "2":
                run_combined_building_and_wall_upgrade("MODE 2 COMBINED UPGRADE")
                print(" [MODE 2] Waiting 1 Minute (60s) before next Combined Upgrade resource check...")
                smart_sleep(60.0, apply_speed=False)

            # ------------------------------------------------------------------
            # MODE 3: TRIED ALL (Combined Upgrade -> 10 Fast Attacks -> Repeat)
            # ------------------------------------------------------------------
            elif bot_mode == "3":
                if runtime_state["phase"] == "START_CYCLE":
                    run_combined_building_and_wall_upgrade("MODE 3 COMBINED UPGRADE")
                    runtime_state["phase"] = "ATTACK_10"
                    runtime_state["attacks_done"] = 0

                if runtime_state["phase"] == "ATTACK_10":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=10,
                        phase_label="MODE 3 (10-ATTACK LOOP)"
                    )
                    runtime_state["phase"] = "START_CYCLE"
                    runtime_state["attacks_done"] = 0

            # ------------------------------------------------------------------
            # MODE 4: ID CHANGEMENT ONLY (Wait 10 Seconds on each ID -> Switch ID -> Loop 1..N)
            # ------------------------------------------------------------------
            elif bot_mode == "4":
                print(f" [MODE 4] Spending 10 Seconds on ID #{active_id}/{total_ids} [{id_role}]...")
                perform_home_cleanup_once(max_age_sec=1.0)
                smart_sleep(10.0, apply_speed=False)

                next_id = (active_id % total_ids) + 1
                print(f" [MODE 4] 10 Seconds complete! Switching from ID #{active_id} -> ID #{next_id}/{total_ids}...")
                switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                runtime_state["current_id"] = next_id

            # ------------------------------------------------------------------
            # MODE 5: ID CHANGEMENT + FAST ATTACK (10 Minutes Fast Attack per ID -> Switch ID)
            # ------------------------------------------------------------------
            elif bot_mode == "5":
                target_duration_sec = 600.0  # 10 Minutes = 600 seconds
                if runtime_state["id_timer_start"] is None:
                    runtime_state["id_timer_start"] = time.time()
                    runtime_state["attacks_done"] = 0
                    print(f" [MODE 5] Started 10-Minute Fast Attack Timer on ID #{active_id}/{total_ids} [{id_role}]!")

                while True:
                    check_pause_point(allow_raise=True)
                    elapsed_total = runtime_state["id_elapsed_sec"] + (time.time() - runtime_state["id_timer_start"])
                    remaining_sec = target_duration_sec - elapsed_total

                    if remaining_sec <= 0:
                        print(f"\n [10 MIN COMPLETE] Spent {elapsed_total/60.0:.1f} minutes ({runtime_state['attacks_done']} attacks) on ID #{active_id}!")
                        break

                    atk_no = runtime_state["attacks_done"] + 1
                    print(f"\n [MODE 5 | ID #{active_id}] Starting Fast Attack #{atk_no} (Time elapsed: {elapsed_total/60.0:.1f}m / 10.0m)...")
                    pre_wait = random.uniform(0.20, 0.40)
                    smart_sleep(pre_wait, apply_speed=True)

                    # Finishes the full attack even if the 10th minute expires mid-battle!
                    execute_attack(is_first_attack=(atk_no == 1))
                    runtime_state["attacks_done"] += 1

                # Switch to Next ID (wraps around from total_ids -> 1)
                next_id = (active_id % total_ids) + 1
                switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                runtime_state["current_id"] = next_id
                runtime_state["id_timer_start"] = None
                runtime_state["id_elapsed_sec"] = 0.0
                runtime_state["attacks_done"] = 0

            # ------------------------------------------------------------------
            # MODE 6: ID CHANGEMENT + TRIED ALL (FULLY BOTTED SYSTEM)
            # Step 1: Combined Upgrade Loop #1 (Building -> Wall Handoff)
            # Step 2: 10 Fast Attacks
            # Step 3: Combined Upgrade Loop #2 (Building -> Wall Handoff)
            #   - If ANY Building or Wall upgraded in Combined Loop #2 -> Switch ID immediately!
            #   - If NOTHING upgraded in Combined Loop #2 -> Do 5 Fast Attacks -> Switch ID!
            # ------------------------------------------------------------------
            elif bot_mode == "6":
                # Phase 1: Initial Combined Upgrade Loop #1 on Current ID
                if runtime_state["phase"] == "START_CYCLE":
                    run_combined_building_and_wall_upgrade(f"ID #{active_id} - COMBINED UPGRADE LOOP #1")
                    runtime_state["phase"] = "ATTACK_10"
                    runtime_state["attacks_done"] = 0

                # Phase 2: 10 Fast Attacks
                if runtime_state["phase"] == "ATTACK_10":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=10,
                        phase_label=f"ID #{active_id} - 10 FAST ATTACKS"
                    )
                    runtime_state["phase"] = "UPGRADE_LOOP_2"
                    runtime_state["attacks_done"] = 0

                # Phase 3: Second Combined Upgrade Loop #2 after 10 Attacks
                if runtime_state["phase"] == "UPGRADE_LOOP_2":
                    _, _, any_up_2 = run_combined_building_and_wall_upgrade(f"ID #{active_id} - COMBINED UPGRADE LOOP #2")
                    runtime_state["loop2_any_upgraded"] = any_up_2

                    if any_up_2:
                        print("\n [MODE 6 RULE] Combined Upgrade Loop #2 me upgrade safal raha! Attack rok kar seedha Next ID par switch kar rahe hain...")
                        runtime_state["phase"] = "SWITCH_ID"
                    else:
                        print("\n [i MODE 6 RULE] Combined Upgrade Loop #2 me koi upgrade nahi hua! Ab 5 Fast Attacks karenge phir ID switch karenge...")
                        runtime_state["phase"] = "ATTACK_5"
                        runtime_state["attacks_done"] = 0

                # Phase 4 (Conditional): 5 Extra Fast Attacks if nothing upgraded in Combined Loop #2
                if runtime_state["phase"] == "ATTACK_5":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=5,
                        phase_label=f"ID #{active_id} - 5 EXTRA FAST ATTACKS"
                    )
                    runtime_state["phase"] = "SWITCH_ID"
                    runtime_state["attacks_done"] = 0

                # Phase 5: Switch to Next ID (1 -> 2 -> ... -> total_ids -> 1)
                if runtime_state["phase"] == "SWITCH_ID":
                    next_id = (active_id % total_ids) + 1
                    switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                    runtime_state["current_id"] = next_id
                    runtime_state["phase"] = "START_CYCLE"
                    runtime_state["attacks_done"] = 0
                    runtime_state["loop2_any_upgraded"] = False

            # Point #50: Clean RAM garbage at the end of every Master Cycle so memory stays 100% fresh
            clean_ram_garbage()

            print(f"\n[SUCCESS] Master Cycle #{cycle_count} Completed! (Speed={get_bot_speed_multiplier():.2f}x)")
            cycle_count += 1
            smart_sleep(random.uniform(1.0, 1.5), apply_speed=True)

        except BotPausedResumeHomeException as resume_sig:
            print(f"\n[RESUME HANDLER] {resume_sig} (Speed={get_bot_speed_multiplier():.2f}x Preserved)")
            # Save elapsed time if in Mode 5 before resetting timer start
            if bot_mode == "5" and runtime_state["id_timer_start"] is not None:
                runtime_state["id_elapsed_sec"] += max(0.0, time.time() - runtime_state["id_timer_start"])
                runtime_state["id_timer_start"] = time.time()

            # Bring game cleanly back to Home Page and continue from exact saved phase, attack count & speed!
            ensure_return_to_home_page_a14()
            human_sleep(0.8, 0.15)
            print(f" [RESUMED ON HOME PAGE] Continuing ID #{runtime_state['current_id']} | Phase: {runtime_state['phase']} | Attacks Done: {runtime_state['attacks_done']} | Speed: {get_bot_speed_multiplier():.2f}x")
            continue

        except KeyboardInterrupt:
            print("\n[!] Bot ko manually roka gaya (Ctrl+C). Safely shutting down...")
            break

        except Exception as e:
            print("\n==================================================")
            print("[! CRITICAL ERROR !] Main Loop me error aayi:")
            print(f"-> Reason: {str(e)}")
            traceback.print_exc()
            print("==================================================")
            print("Recovering in 3 seconds...")
            time.sleep(3)
            ensure_return_to_home_page_a14()

if __name__ == "__main__":
    main_loop()
EOF

echo "✔ All 4 Parts (bot_tools.py, bot_upgrade.py, bot_id_switch.py, bot_attack.py & main_bot.py) 100% Updated & Ready!"

