sed -i 's/def ids_ roughly_match/def ids_roughly_match/g' bot_id_switch.py 2>/dev/null || true
sed -i 's/slot_ coord =/slot_coord =/g' bot_id_switch.py 2>/dev/null || true

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
    get_screenshot,
    smart_sleep,
    check_pause_point,
    check_wrong_buttons_a14,
    is_on_home_page_a14,
    click_gold_storage_3_times
)

BATTLE_TIMER_DURATION_SEC = 45.0

def scan_battlefield_or_restart(stage_name):
    """
    Checks Wrong Buttons and Home Page Green '+' icon during attack pauses.
    If either is detected, raises RestartLoopException to restart the Attack Loop.
    """
    check_pause_point(allow_raise=True)
    print(f"  [🔍 SCAN] [{stage_name}] Checking Wrong Buttons & Home Page status...")
    img = get_screenshot()
    wrong_found = check_wrong_buttons_a14(img)
    home_found = is_on_home_page_a14(img)

    if wrong_found or home_found:
        reason = "Wrong Button detected" if wrong_found else "Still stuck on Home Page (Green '+' visible)"
        print(f"  [!] [ALERT at {stage_name}] {reason}! Restarting Attack Loop...")
        raise RestartLoopException(reason)

def execute_attack(is_first_attack=True):
    for attempt in range(1, 4):
        try:
            check_pause_point(allow_raise=True)
            print("\n╔══════════════════════════════════════════════════════════╗")
            print(f"║     [FAST ATTACK LOOP - 45s TIMER] - ATTEMPT #{attempt}          ║")
            print("╚══════════════════════════════════════════════════════════╝")

            # 1. Home Page: Optimized 2.5s Wait + 3x Gold Storage Click
            print("  [⏳ 2.5s] Waiting 2.5 seconds on Home Page...")
            smart_sleep(2.5)
            check_wrong_buttons_a14()
            click_gold_storage_3_times()

            # 2. Matchmaking (Optimized Delays: 0.3s -> Battle -> 0.5s -> Find Match -> 1.0s -> Attack)
            print("  [⚔️ 0.3s] Clicking Battle Button (182, 961)...")
            smart_sleep(0.3)
            tap(*FAST_ATTACK["BATTLE_BTN"], delay_range=(0.08, 0.15), jitter=3)

            print("  [⏳ 0.5s] Waiting 0.5s -> Clicking Find Match (364, 808)...")
            smart_sleep(0.5)
            tap(*FAST_ATTACK["FIND_MATCH_BTN"], delay_range=(0.08, 0.15), jitter=3)

            print("  [⏳ 1.0s] Waiting 1.0s -> Clicking Attack Button (1980, 972)...")
            smart_sleep(1.0)
            tap(*FAST_ATTACK["ATTACK_BTN"], delay_range=(0.08, 0.15), jitter=3)

            # 3. 18 Seconds Enemy Base Load (Unchanged) + Screen Check #1
            print("  [⏳ 18s] Waiting 18 seconds for Enemy Base to load...")
            smart_sleep(18.0)
            scan_battlefield_or_restart("Post-18s Base Load Check")

            # 4. Spell Select (1527, 983) -> 0.35s -> 2 Rounds Deploy (Starts 45s Battle Timer)
            print("  [⚡ 0.35s] Selecting Spell (1527, 983)...")
            smart_sleep(0.35)
            tap(*FAST_ATTACK["SPELL_SELECT"], delay_range=(0.04, 0.08), jitter=2)
            spell_select_timer = time.time()

            print("  [⚡ 0.35s] Deploying Spells (2 Rounds in Serial Order)...")
            smart_sleep(0.35)
            fast_serial_taps(FAST_ATTACK["SPELL_DEPLOY_LIST"], rounds=2, jitter=3)

            # 5. Army 1 Select (470, 988) -> 4 Rounds Deploy
            print("  [🐉 0.35s] Selecting Army 1 (470, 988)...")
            smart_sleep(0.35)
            tap(*FAST_ATTACK["ARMY_1_SELECT"], delay_range=(0.04, 0.08), jitter=2)

            print("  [🐉] Deploying Army 1 (4 Rounds in Serial Order: 325,525 -> 375,524)...")
            fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=4, jitter=3)

            # 6. Army 2 Select (590, 985) -> 2 Rounds Deploy
            print("  [🎈 0.35s] Selecting Army 2 (590, 985)...")
            smart_sleep(0.35)
            tap(*FAST_ATTACK["ARMY_2_SELECT"], delay_range=(0.04, 0.08), jitter=2)

            print("  [🎈 0.35s] Deploying Army 2 (2 Rounds on 3 Coords)...")
            smart_sleep(0.35)
            fast_serial_taps(FAST_ATTACK["ARMY_2_DEPLOY_LIST"], rounds=2, jitter=3)

            # 7. Siege Machine + Heroes 1-4 (1 Round each on Army 1 Coords)
            print("  [👑] Deploying Siege Machine & Heroes 1-4 (1 Round each on Army 1 Coords)...")
            siege_and_heroes = [
                ("Siege Machine", FAST_ATTACK["SIEGE_SELECT"]),
                ("Hero 1", FAST_ATTACK["HERO_1_SELECT"]),
                ("Hero 2", FAST_ATTACK["HERO_2_SELECT"]),
                ("Hero 3", FAST_ATTACK["HERO_3_SELECT"]),
                ("Hero 4", FAST_ATTACK["HERO_4_SELECT"])
            ]
            for unit_name, select_coord in siege_and_heroes:
                check_pause_point(allow_raise=True)
                print(f"    -> Selecting {unit_name} {select_coord} & deploying 1 Round...")
                tap(*select_coord, delay_range=(0.04, 0.08), jitter=2)
                fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=1, jitter=3)

            # 8. Hero Abilities Activation + Screen Check #2
            print("  [✨ 2.0s] Waiting 2s -> Activating Hero 1, 2, 3, 4 Abilities...")
            smart_sleep(2.0)
            for h_idx, h_coord in enumerate([
                FAST_ATTACK["HERO_1_SELECT"],
                FAST_ATTACK["HERO_2_SELECT"],
                FAST_ATTACK["HERO_3_SELECT"],
                FAST_ATTACK["HERO_4_SELECT"]
            ], start=1):
                check_pause_point(allow_raise=True)
                print(f"    -> Activating Hero {h_idx} Ability at {h_coord}...")
                tap(*h_coord, delay_range=(0.06, 0.12), jitter=2)

            elapsed_deploy = time.time() - spell_select_timer
            print(f"  [i] Full Deployment & Abilities completed in {elapsed_deploy:.1f} seconds!")

            scan_battlefield_or_restart("Post-Hero-4-Ability Check")

            # 9. Wait until 45 seconds from Spell Select (Modified Battle Timer = 45.0s)
            elapsed_since_spell = time.time() - spell_select_timer
            if elapsed_since_spell < BATTLE_TIMER_DURATION_SEC:
                rem_wait = BATTLE_TIMER_DURATION_SEC - elapsed_since_spell
                print(f"  [⏳ 45s TIMER] Waiting remaining {rem_wait:.1f}s to complete 45s Battle Timer from Spell Select...")
                smart_sleep(rem_wait)

            # 10. Surrender (3x) -> 1.0s -> Okay -> 2.0s -> Check #3 -> Return Home (3x) -> 2.0s
            print("  [🏳️ SURRENDER] Clicking Surrender Button (181, 800) 3 times...")
            for _ in range(3):
                tap(*FAST_ATTACK["SURRENDER_BTN"], delay_range=(0.12, 0.20), jitter=3)

            print("  [⏳ 1.0s] Waiting 1.0s -> Clicking Okay Button (1419, 701)...")
            smart_sleep(1.0)
            tap(*FAST_ATTACK["OKAY_BTN"], delay_range=(0.12, 0.20), jitter=3)

            print("  [⏳ 2.0s] Waiting 2.0s before Return Home...")
            smart_sleep(2.0)

            print("  [🔍 SCAN] [Pre-Return-Home Check] Checking Wrong Buttons...")
            img_pre_ret = get_screenshot()
            check_wrong_buttons_a14(img_pre_ret)

            print("  [🏠 RETURN] Clicking Return Home Button (1222, 918) 3 times...")
            for _ in range(3):
                tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.12, 0.20), jitter=3)

            print("  [⏳ 2.0s] Waiting 2.0s to settle on Home Page...")
            smart_sleep(2.0)
            check_wrong_buttons_a14()
            click_gold_storage_3_times()

            print("  [✔] [FAST ATTACK COMPLETE] Fast Attack Cycle Finished Successfully!\n")
            return True

        except BotPausedResumeHomeException:
            # Propagate immediately to main_bot so it recovers to Home Page and resumes current attack count
            raise

        except RestartLoopException as re_err:
            print(f"\n  [↻ RESTARTING ATTACK] Reason: {re_err}")
            check_wrong_buttons_a14()
            smart_sleep(1.5)
            continue

        except Exception as e:
            print("\n[! ERROR !] Fast Attack Loop me error aayi:")
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
    check_wrong_buttons_a14,
    double_click_storage_bars,
    ensure_return_to_home_page_a14,
    check_resources_full_for_upgrade,
    check_wall_resources_full_a14
)
from bot_upgrade import (
    run_a14_upgrade_loop,
    run_a14_wall_upgrade_loop
)
from bot_attack import execute_attack
from bot_id_switch import (
    load_id_memory,
    save_id_memory,
    get_id_role_label,
    switch_to_target_id
)

# ==========================================
# 1. BOT OPERATING MODE & TOTAL ID SELECTION MENU
# ==========================================
def select_bot_configuration():
    print("\n╔══════════════════════════════════════════════════════════════════════╗")
    print("║         CLASH OF CLANS AI BOT - SAMSUNG GALAXY A14 ULTIMATE          ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print("║  Select Bot Operating Mode (1 to 7):                                 ║")
    print("║    [1] -> Fast Attack Only             (सिर्फ फास्ट अटैक - Infinity)    ║")
    print("║    [2] -> Building Upgrade Only        (सिर्फ बिल्डिंग अपग्रेड - 1m Gap) ║")
    print("║    [3] -> Wall Upgrade Only            (सिर्फ वॉल अपग्रेड - 1m Gap)     ║")
    print("║    [4] -> Tried All                    (Attack + Building + Wall)    ║")
    print("║    [5] -> ID Changement Only           (सिर्फ ID चेंज - हर 1 मिनट में)   ║")
    print("║    [6] -> ID Changement + Fast Attack  (हर ID पर 10 Min अटैक + स्विच)  ║")
    print("║    [7] -> ID Changement + Tried All    (Fully Botted System)         ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print("║  Live Controls Inside Termux:                                        ║")
    print("║    ⏸️  Pause Bot  : Type 'ZX' (or 'zx') anytime                       ║")
    print("║    ▶️  Resume Bot : Type 'QW' (or 'qw') anytime (Resumes from Home)   ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    while True:
        choice = input("\n👉 Apna Option type karein (1 / 2 / 3 / 4 / 5 / 6 / 7) [Default=7]: ").strip()
        if choice == "":
            choice = "7"
        if choice in ["1", "2", "3", "4", "5", "6", "7"]:
            break
        print("  [!] Galat input! Kripya 1 se 7 ke beech ka number type karein.")

    mode_names = {
        "1": "FAST ATTACK ONLY (सिर्फ फास्ट अटैक - Infinity)",
        "2": "BUILDING UPGRADE ONLY (सिर्फ बिल्डिंग अपग्रेड - 1 Min Gap)",
        "3": "WALL UPGRADE ONLY (सिर्फ वॉल अपग्रेड - 1 Min Gap)",
        "4": "TRIED ALL: ATTACK + BUILDING + WALL UPGRADE (10 Attacks Loop)",
        "5": "ID CHANGEMENT ONLY (हर 1 मिनट पर ID स्विच)",
        "6": "ID CHANGEMENT + FAST ATTACK (हर ID पर 10 मिनट फास्ट अटैक)",
        "7": "ID CHANGEMENT + TRIED ALL (FULLY BOTTED SYSTEM)"
    }
    print(f"\n  [✔] Selected Mode: [{choice}] -> {mode_names[choice]}")

    total_ids = 1
    start_id_index = 1

    if choice in ["5", "6", "7"]:
        mem = load_id_memory()
        default_total = mem.get("total_ids", 10)
        if default_total < 1 or default_total > 100:
            default_total = 10

        while True:
            raw_total = input(f"👉 Total IDs type karein (1 se 100 ke beech, First 4 = Main ID) [Default={default_total}]: ").strip()
            if raw_total == "":
                total_ids = default_total
                break
            if raw_total.isdigit() and 1 <= int(raw_total) <= 100:
                total_ids = int(raw_total)
                break
            print("  [!] Kripya 1 se 100 ke beech ka sahi number type karein.")

        saved_idx = mem.get("current_id_index", 1)
        if 1 < saved_idx <= total_ids:
            ans = input(f"👉 Pichhli baar Bot ID #{saved_idx} par tha. Kya ID #{saved_idx} se Resume karein? (y/n) [Default=n (Start from ID #1)]: ").strip().lower()
            if ans == "y":
                start_id_index = saved_idx

        mem["total_ids"] = total_ids
        mem["current_id_index"] = start_id_index
        save_id_memory(mem)
        print(f"  [✔] ID Changement Configured: Total IDs = {total_ids} | Starting on ID #{start_id_index} [{get_id_role_label(start_id_index)}]")

    input("\n🚀 Bot Start karne ke liye [ENTER] key dabayein: ")
    return choice, total_ids, start_id_index

# ==========================================
# 2. UPGRADE CHECK & EXECUTION HELPERS (BUILDING FIRST, WALL SECOND)
# ==========================================
def check_and_run_building_upgrade():
    """
    Checks Building Storage Box. If full, clicks Build after 0.45s gap and runs Condition 1.
    Returns True if at least one building was upgraded, False otherwise.
    """
    check_pause_point(allow_raise=True)
    check_wrong_buttons_a14()
    double_click_storage_bars()
    human_sleep(0.45, 0.08)

    print("\n  [🏢 BUILDING CHECK] Checking Building Gold & Elixir Storage Boxes...")
    if check_resources_full_for_upgrade():
        print("  [+] Building Storage Box is FULL! Starting Building Upgrade in 0.45s...")
        human_sleep(0.45, 0.08)
        upgraded = run_a14_upgrade_loop()
        return bool(upgraded)
    else:
        print("  [-] Building Storage Box is not full yet. Skipping Building Upgrade...")
        return False

def check_and_run_wall_upgrade():
    """
    Checks Wall Storage Box (1947,44..2015,76 & 1947,115..2015,149).
    If full, clicks Build after 0.45s gap and runs Wall Upgrade Process.
    Returns True if at least one wall was upgraded, False otherwise.
    """
    check_pause_point(allow_raise=True)
    check_wrong_buttons_a14()
    double_click_storage_bars()
    human_sleep(0.45, 0.08)

    print("\n  [🧱 WALL CHECK] Checking Wall Gold (1947,44..2015,76) & Elixir (1947,115..2015,149) Boxes...")
    if check_wall_resources_full_a14():
        print("  [+] Wall Storage Box is FULL! Activating Wall Upgrade System in 0.45s...")
        human_sleep(0.45, 0.08)
        upgraded = run_a14_wall_upgrade_loop()
        return bool(upgraded)
    else:
        print("  [-] Wall Storage Box is not full yet. Skipping Wall Upgrade...")
        return False

def run_combined_building_then_wall_upgrade(loop_label="UPGRADE LOOP"):
    """
    Always checks Building Upgrade FIRST, and after Building Upgrade finishes,
    checks Wall Upgrade SECOND (as strictly specified in PDF Page 1).
    Returns (building_upgraded, wall_upgraded, any_upgraded).
    """
    print(f"\n  ┌──────────────────────────────────────────────────────────────┐")
    print(f"  │  🛠️  [{loop_label}] Step 1: Building Check -> Step 2: Wall Check  │")
    print(f"  └──────────────────────────────────────────────────────────────┘")
    b_up = check_and_run_building_upgrade()
    human_sleep(0.6, 0.1)
    w_up = check_and_run_wall_upgrade()
    any_up = bool(b_up or w_up)
    print(f"  [📊 {loop_label} RESULT] Building Upgraded: {b_up} | Wall Upgraded: {w_up} | Any Upgraded: {any_up}")
    return b_up, w_up, any_up

def run_n_fast_attacks_with_resume_memory(state_dict, target_attacks, phase_label="ATTACK SERIES"):
    """
    Executes `target_attacks` Fast Attacks sequentially while saving progress in `state_dict["attacks_done"]`.
    If paused via 'ZX' and resumed via 'QW' during Attack #k, it returns to Home Page
    and resumes cleanly from the remaining attack count without losing memory!
    """
    while state_dict["attacks_done"] < target_attacks:
        check_pause_point(allow_raise=True)
        next_atk_num = state_dict["attacks_done"] + 1
        pre_attack_wait = random.uniform(1.0, 1.5)
        print(f"\n  [⚔️ {phase_label}] Attack #{next_atk_num} / {target_attacks} starting in {pre_attack_wait:.1f}s...")
        smart_sleep(pre_attack_wait)

        execute_attack(is_first_attack=(next_atk_num == 1))
        state_dict["attacks_done"] += 1
        print(f"  [✔] [{phase_label}] Completed Attack #{state_dict['attacks_done']} / {target_attacks}!")

# ==========================================
# 3. MASTER LOOP CONTROLLER (MODES 1 TO 7)
# ==========================================
def main_loop():
    bot_mode, total_ids, current_id = select_bot_configuration()

    # Start background keyboard listener for 'ZX' (Pause) and 'QW' (Resume)
    start_pause_resume_listener()

    # Optimized Startup Rest: 1.5 to 2.0 seconds
    startup_rest = random.uniform(1.5, 2.0)
    print(f"\n[⏳ STARTUP] Taking {startup_rest:.1f} seconds initial rest on Home Page...")
    smart_sleep(startup_rest)

    cycle_count = 1

    # Persistent runtime state so Pause ('ZX') / Resume ('QW') never forgets progress
    runtime_state = {
        "current_id": current_id,
        "phase": "START_CYCLE",      # Tracks sub-phase within Mode 4, 6, 7
        "attacks_done": 0,           # Tracks how many attacks completed in current 10-attack or 5-attack block
        "id_timer_start": None,      # Mode 6: 10-minute timer start timestamp
        "id_elapsed_sec": 0.0,       # Mode 6: accumulated active seconds on current ID
        "loop2_any_upgraded": False  # Mode 7: result of Second Upgrade Loop
    }

    while True:
        try:
            check_pause_point(allow_raise=True)
            active_id = runtime_state["current_id"]
            id_role = get_id_role_label(active_id)

            print("\n" + "═" * 70)
            if bot_mode in ["5", "6", "7"]:
                print(f"   🔄 MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}] | ACTIVE ID: #{active_id}/{total_ids} [{id_role}]")
            else:
                print(f"   🔄 MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}]")
            print("═" * 70)

            # ----------------------------------------------------
            # MODE 1: FAST ATTACK ONLY (Continues Infinitely)
            # ----------------------------------------------------
            if bot_mode == "1":
                pre_wait = random.uniform(1.0, 1.5)
                print(f"  [⚔️ MODE 1] Starting Fast Attack in {pre_wait:.1f}s...")
                smart_sleep(pre_wait)
                execute_attack(is_first_attack=(cycle_count == 1))

            # ----------------------------------------------------
            # MODE 2: BUILDING UPGRADE ONLY (Every 1 Minute Gap)
            # ----------------------------------------------------
            elif bot_mode == "2":
                check_and_run_building_upgrade()
                print("  [⏳ MODE 2] Waiting 1 Minute (60s) before next Building Upgrade resource check...")
                smart_sleep(60.0)

            # ----------------------------------------------------
            # MODE 3: WALL UPGRADE ONLY (Every 1 Minute Gap)
            # ----------------------------------------------------
            elif bot_mode == "3":
                check_and_run_wall_upgrade()
                print("  [⏳ MODE 3] Waiting 1 Minute (60s) before next Wall Upgrade resource check...")
                smart_sleep(60.0)

            # ----------------------------------------------------
            # MODE 4: TRIED ALL (Building Check -> Wall Check -> 10 Fast Attacks -> Repeat)
            # ----------------------------------------------------
            elif bot_mode == "4":
                if runtime_state["phase"] == "START_CYCLE":
                    run_combined_building_then_wall_upgrade("MODE 4 UPGRADE CHECK")
                    runtime_state["phase"] = "ATTACK_10"
                    runtime_state["attacks_done"] = 0

                if runtime_state["phase"] == "ATTACK_10":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=10,
                        phase_label="MODE 4 (10-ATTACK LOOP)"
                    )
                    runtime_state["phase"] = "START_CYCLE"
                    runtime_state["attacks_done"] = 0

            # ----------------------------------------------------
            # MODE 5: ID CHANGEMENT ONLY (Wait 1 Minute on each ID -> Switch ID -> Loop 1..N)
            # ----------------------------------------------------
            elif bot_mode == "5":
                print(f"  [⏳ MODE 5] Spending 1 Minute (60s) on ID #{active_id}/{total_ids} [{id_role}]...")
                check_wrong_buttons_a14()
                double_click_storage_bars()
                smart_sleep(60.0)

                next_id = (active_id % total_ids) + 1
                print(f"  [🔀 MODE 5] 1 Minute complete! Switching from ID #{active_id} -> ID #{next_id}/{total_ids}...")
                switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                runtime_state["current_id"] = next_id

            # ----------------------------------------------------
            # MODE 6: ID CHANGEMENT + FAST ATTACK (10 Minutes Fast Attack per ID -> Switch ID)
            # ----------------------------------------------------
            elif bot_mode == "6":
                target_duration_sec = 600.0  # 10 Minutes = 600 seconds
                if runtime_state["id_timer_start"] is None:
                    runtime_state["id_timer_start"] = time.time()
                    runtime_state["attacks_done"] = 0
                    print(f"  [⏱️ MODE 6] Started 10-Minute Fast Attack Timer on ID #{active_id}/{total_ids} [{id_role}]!")

                while True:
                    check_pause_point(allow_raise=True)
                    elapsed_total = runtime_state["id_elapsed_sec"] + (time.time() - runtime_state["id_timer_start"])
                    remaining_sec = target_duration_sec - elapsed_total

                    if remaining_sec <= 0:
                        print(f"\n  [⏰ 10 MIN COMPLETE] Spent {elapsed_total/60.0:.1f} minutes ({runtime_state['attacks_done']} attacks) on ID #{active_id}!")
                        break

                    atk_no = runtime_state["attacks_done"] + 1
                    print(f"\n  [⚔️ MODE 6 | ID #{active_id}] Starting Fast Attack #{atk_no} (Time elapsed: {elapsed_total/60.0:.1f}m / 10.0m)...")
                    pre_wait = random.uniform(1.0, 1.5)
                    smart_sleep(pre_wait)

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

            # ----------------------------------------------------
            # MODE 7: ID CHANGEMENT + TRIED ALL (FULLY BOTTED SYSTEM)
            #   Step 1: Upgrade Loop #1 (Building Check -> Wall Check)
            #   Step 2: 10 Fast Attacks
            #   Step 3: Upgrade Loop #2 (Building Check -> Wall Check)
            #           - If ANY Building or Wall upgraded in Loop #2 -> Switch ID immediately!
            #           - If NOTHING upgraded in Loop #2 -> Do 5 Fast Attacks -> Switch ID!
            # ----------------------------------------------------
            elif bot_mode == "7":
                # Phase 1: Initial Upgrade Loop #1 on Current ID
                if runtime_state["phase"] == "START_CYCLE":
                    run_combined_building_then_wall_upgrade(f"ID #{active_id} - UPGRADE LOOP #1")
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

                # Phase 3: Second Upgrade Loop #2 after 10 Attacks
                if runtime_state["phase"] == "UPGRADE_LOOP_2":
                    _, _, any_up_2 = run_combined_building_then_wall_upgrade(f"ID #{active_id} - UPGRADE LOOP #2")
                    runtime_state["loop2_any_upgraded"] = any_up_2

                    if any_up_2:
                        print(f"\n  [✔ MODE 7 RULE] Upgrade Loop #2 me upgrade safal raha! Attack rok kar seedha Next ID par switch kar rahe hain...")
                        runtime_state["phase"] = "SWITCH_ID"
                    else:
                        print(f"\n  [i MODE 7 RULE] Upgrade Loop #2 me koi Building ya Wall upgrade nahi hua! Ab 5 Fast Attacks karenge phir ID switch karenge...")
                        runtime_state["phase"] = "ATTACK_5"
                        runtime_state["attacks_done"] = 0

                # Phase 4 (Conditional): 5 Extra Fast Attacks if nothing upgraded in Loop #2
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

            print(f"\n[✔ SUCCESS] Master Cycle #{cycle_count} Completed!")
            cycle_count += 1
            smart_sleep(random.uniform(3.0, 4.5))

        except BotPausedResumeHomeException as resume_sig:
            print(f"\n  [🔄 RESUME HANDLER] {resume_sig}")
            # Save elapsed time if in Mode 6 before resetting timer start
            if bot_mode == "6" and runtime_state["id_timer_start"] is not None:
                runtime_state["id_elapsed_sec"] += max(0.0, time.time() - runtime_state["id_timer_start"])
                runtime_state["id_timer_start"] = time.time()

            # Bring game cleanly back to Home Page and continue from exact saved phase & attack count!
            ensure_return_to_home_page_a14()
            human_sleep(1.5, 0.2)
            print(f"  [▶️ RESUMED ON HOME PAGE] Continuing ID #{runtime_state['current_id']} | Phase: {runtime_state['phase']} | Attacks Done: {runtime_state['attacks_done']}")
            continue

        except KeyboardInterrupt:
            print("\n[!] Bot ko manually roka gaya (Ctrl+C). Safely shutting down...")
            break

        except Exception as e:
            print("\n==========================================")
            print("[! CRITICAL ERROR !] Main Loop me error aayi:")
            print(f"-> Reason: {str(e)}")
            traceback.print_exc()
            print("==========================================")
            print("Recovering in 5 seconds...")
            time.sleep(5)
            ensure_return_to_home_page_a14()

if __name__ == "__main__":
    main_loop()
EOF
echo "✅ All 4 files (bot_tools.py, bot_upgrade.py, bot_id_switch.py, bot_attack.py & main_bot.py) updated and cache cleared successfully!"
