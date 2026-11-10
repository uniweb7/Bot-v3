
import os
import json
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
    run_zone2_home_periodic_checks,
    double_click_storage_bars,
    perform_home_cleanup_once,
    ensure_return_to_home_page_a14,
    check_resources_full_for_upgrade,
    zoom_out_village_a14,
    clean_ram_garbage,
    reset_session_progress_report,
    print_previous_progress_report,
    record_stat
)
from bot_upgrade import (
    run_a14_combined_upgrade_loop,
    run_a14_buildings_only_upgrade_loop,
    run_custom_mode_upgrade_loop
)
from bot_attack import execute_attack
from bot_id_switch import (
    load_id_memory,
    save_id_memory,
    get_id_role_label,
    switch_to_target_id,
    sync_initial_id_to_report
)

CUSTOM_PRESET_FILE = "bot_custom_preset.json"

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

def load_custom_preset():
    default_preset = {
        "combo_type": "1+2+3",
        "attacks_per_round": 5,
        "upgrade_order": "BUILDING_THEN_WALL",
        "check_storage": False,
        "stop_builders": 0,
        "rounds_per_id": 3
    }
    if not os.path.exists(CUSTOM_PRESET_FILE):
        return default_preset
    try:
        with open(CUSTOM_PRESET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                default_preset.update(data)
    except Exception:
        pass
    return default_preset

def save_custom_preset(preset_data):
    try:
        with open(CUSTOM_PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(preset_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def configure_custom_mode_9():
    preset = load_custom_preset()
    print("\n==============================================================================")
    print(" ||         OPTION [9]: CREATE OPTIONS (MANUAL CUSTOM BUILDER)              ||")
    print("==============================================================================")
    print(" || Saved Custom Preset Summary:                                             ||")
    print(f" ||   * Combination      : {preset['combo_type']}                                              ||")
    print(f" ||   * Attacks / Round  : {preset['attacks_per_round']} Fast Attacks                                    ||")
    print(f" ||   * Upgrade Sequence : {preset['upgrade_order']}                             ||")
    print(f" ||   * Storage Check    : {'Yes' if preset['check_storage'] else 'No (Direct Fast Upgrade)'}                               ||")
    print(f" ||   * Builder Target   : Stop at {preset['stop_builders']} Builder(s)                                ||")
    print(f" ||   * Attempts per ID  : {preset['rounds_per_id']} Round(s) before ID Switch                       ||")
    print("==============================================================================")

    use_saved = input("\n Kya pichhla Saved Custom Preset use karein? (y/n) [Default=y]: ").strip().lower()
    if use_saved in ["", "y", "yes"]:
        return preset

    print("\n [STEP 1] Select System Combination:")
    print("   [1] -> 1 + 3 : Fast Attack + ID Switching Only")
    print("   [2] -> 1 + 2 : Fast Attack + Fast Upgrading Only")
    print("   [3] -> 1 + 2 + 3 : Fast Attack + Fast Upgrading + ID Switching (Full Custom Sequence)")
    c_in = input(" Option type karein (1/2/3) [Default=3 (1+2+3)]: ").strip()
    if c_in == "1":
        preset["combo_type"] = "1+3"
    elif c_in == "2":
        preset["combo_type"] = "1+2"
    else:
        preset["combo_type"] = "1+2+3"

    raw_atk = input(f"\n [STEP 2] Har round me kitne Fast Attacks karne hain? (1 se 50) [Default={preset['attacks_per_round']}]: ").strip()
    if raw_atk.isdigit() and 1 <= int(raw_atk) <= 50:
        preset["attacks_per_round"] = int(raw_atk)

    if "2" in preset["combo_type"]:
        print("\n [STEP 3] Select Upgrade Category & Sequence Order:")
        print("   [1] -> Building Upgrade FIRST -> then Wall Upgrade")
        print("   [2] -> Wall Upgrade FIRST -> then Building Upgrade")
        print("   [3] -> Building Upgrade ONLY (No Wall)")
        print("   [4] -> Wall Upgrade ONLY (No Building)")
        u_in = input(" Option type karein (1/2/3/4) [Default=1]: ").strip()
        if u_in == "2":
            preset["upgrade_order"] = "WALL_THEN_BUILDING"
        elif u_in == "3":
            preset["upgrade_order"] = "BUILDING_ONLY"
        elif u_in == "4":
            preset["upgrade_order"] = "WALL_ONLY"
        else:
            preset["upgrade_order"] = "BUILDING_THEN_WALL"

        st_in = input("\n [STEP 4] Upgrade se pehle Storage Box check karein ya Direct Upgrade? (d=Direct / c=Check) [Default=d]: ").strip().lower()
        preset["check_storage"] = (st_in == "c")

        b_in = input("\n [STEP 5] Builders kitne bachne par upgrade close karein? (0 = Zero Builders / 1 = One Builder) [Default=0]: ").strip()
        preset["stop_builders"] = 1 if b_in == "1" else 0

    if "3" in preset["combo_type"]:
        r_in = input(f"\n [STEP 6] Ek ID par (Attack + Upgrade) kitne Attempts/Rounds chalane ke baad ID Switch karein? (1 se 10) [Default=3]: ").strip()
        if r_in.isdigit() and 1 <= int(r_in) <= 10:
            preset["rounds_per_id"] = int(r_in)
        else:
            preset["rounds_per_id"] = 3

    save_custom_preset(preset)
    print(" [✔] Custom Option [9] Preset saved successfully!")
    return preset

def open_advance_features_menu():
    letter_to_speed = {letter: mult for letter, mult, _ in ADVANCE_SPEED_TABLE}

    while True:
        cur_spd = get_bot_speed_multiplier()
        print("\n======================================================================")
        print(" ||        ADVANCE FEATURES MENU - GAME SPEED-UP SYSTEM              ||")
        print("======================================================================")
        print(f" || Current Active Bot Speed : {cur_spd:.2f}x                               ||")
        print("----------------------------------------------------------------------")
        print(" || Select Game Speed-Up Option (A to Y):                          ||")
        for letter, mult, desc in ADVANCE_SPEED_TABLE:
            marker = " <-- [ACTIVE]" if abs(cur_spd - mult) < 0.005 else ""
            print(f" ||   [{letter}] -> {mult:.2f}x  ({desc}){marker}")
        print("----------------------------------------------------------------------")
        print(" ||   [R] -> View Current / Previous Progress Report               ||")
        print(" ||   [0] -> Back to Main Bot Operating Menu                       ||")
        print("======================================================================")

        raw_in = input("\n Speed Option type karein (A se Y tak, R report ke liye, ya 0 wapas jane ke liye) [Default=A]: ").strip().upper()
        if raw_in == "":
            set_bot_speed_multiplier(1.00)
            break
        if raw_in == "0":
            break
        if raw_in == "R":
            print_previous_progress_report(report_stage="MENU PREVIEW")
            continue
        if raw_in in letter_to_speed:
            chosen_mult = letter_to_speed[raw_in]
            set_bot_speed_multiplier(chosen_mult)
            print(f" [✔] Root-Level Game Speed-Up '{raw_in}' ({chosen_mult:.2f}x) successfully activate ho gaya hai!")
            break
        try:
            val = float(raw_in.replace("X", ""))
            if 1.0 <= val <= 2.25:
                set_bot_speed_multiplier(val)
                print(f" [✔] Custom Root-Level Game Speed-Up ({val:.2f}x) successfully activate ho gaya hai!")
                break
        except Exception:
            pass
        print(" [!] Galat input! Kripya A se Y ke beech ka letter (jaise A, B, C, D, E...) type karein.")

def select_bot_configuration():
    while True:
        cur_spd = get_bot_speed_multiplier()
        print("\n==============================================================================")
        print(" ||      CLASH OF CLANS AI BOT v8 - SAMSUNG GALAXY A14 ULTIMATE EDITION      ||")
        print("==============================================================================")
        print(f" || Active Game Speed Multiplier : {cur_spd:.2f}x {'(Standard Default)' if abs(cur_spd - 1.0) < 0.005 else '(Root Speed-Up Active!)'}")
        print("------------------------------------------------------------------------------")
        print(" || Select Bot Operating Mode (1 to 9):                                      ||")
        print(" || [1] -> Fast Attack Only                  (सिर्फ फास्ट अटैक - Infinity)      ||")
        print(" || [2] -> Combined Upgrade Only             (बिल्डिंग + वॉल अपग्रेड - 1m Gap)  ||")
        print(" || [3] -> Tried All                         (Combined Upgrade + 10 Attacks) ||")
        print(" || [4] -> ID Changement Only                (सिर्फ ID चेंज - हर 2 सेकंड में)    ||")
        print(" || [5] -> ID Changement + Fast Attack       (हर ID पर 10 Min अटैक स्विच)      ||")
        print(" || [6] -> ID Changement + Tried All         (Fully Botted System - Default) ||")
        print(" || [7] -> Advance Features                  (Game Speed-Up: 1.00x to 2.25x) ||")
        print(" || [8] -> Fast Tried With Building Upgrade  (5 Atk -> Direct Bld Up -> 1s)  ||")
        print(" || [9] -> Create Options (Custom Builder)   (1+3 / 1+2 / 5 Atk+Bld+Wall+3x) ||")
        print("==============================================================================")
        print(" || Live Controls Inside Termux:                                             ||")
        print(" || Pause & Show Progress Report : Type 'ZX' (or 'zx') anytime               ||")
        print(" || Resume Bot (Same Speed/State): Type 'QW' (or 'qw') anytime               ||")
        print(" || Stop & Final Progress Report : Press Ctrl+C anytime                      ||")
        print("==============================================================================")

        choice = input("\n Apna Option type karein (1/2/3/4/5/6/7/8/9) [Default=6]: ").strip()
        if choice == "":
            choice = "6"

        if choice == "7":
            open_advance_features_menu()
            continue

        if choice in ["1", "2", "3", "4", "5", "6", "8", "9"]:
            break
        print(" [!] Galat input! Kripya 1 se 9 ke beech ka number type karein.")

    custom_cfg = load_custom_preset()
    if choice == "9":
        custom_cfg = configure_custom_mode_9()

    mode_names = {
        "1": "MODE 1: FAST ATTACK ONLY (Infinity)",
        "2": "MODE 2: COMBINED UPGRADE ONLY (1 Min Gap)",
        "3": "MODE 3: TRIED ALL (Combined Upgrade + 10 Fast Attacks)",
        "4": "MODE 4: ID CHANGEMENT ONLY (2s Hold + Fast Dynamic Switch)",
        "5": "MODE 5: ID CHANGEMENT + FAST ATTACK (10 Min per ID)",
        "6": "MODE 6: ID CHANGEMENT + TRIED ALL (Fully Botted System)",
        "8": "MODE 8: FAST TRIED WITH BUILDING UPGRADE (Fast Attacks -> Direct Building Upgrade -> 1s Switch)",
        "9": f"MODE 9: CUSTOM ({custom_cfg['combo_type']} | {custom_cfg['attacks_per_round']} Atk | {custom_cfg['upgrade_order']} | {custom_cfg['rounds_per_id']}x Rounds)"
    }
    print(f"\n [✔] Selected Mode: [{choice}] -> {mode_names[choice]} | Speed: {get_bot_speed_multiplier():.2f}x")

    total_ids = 1
    start_id_index = 1
    mode8_attacks_per_id = 5

    needs_id_config = (choice in ["4", "5", "6", "8"]) or (choice == "9" and "3" in custom_cfg["combo_type"])
    if needs_id_config:
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

        if choice == "8":
            default_m8_atk = mem.get("mode8_attacks_per_id", 5)
            if not isinstance(default_m8_atk, int) or default_m8_atk < 1 or default_m8_atk > 50:
                default_m8_atk = 5
            while True:
                raw_atk = input(f" [MODE 8] Har ID par kitne Fast Attacks karne hain? (1 se 50) [Default={default_m8_atk}]: ").strip()
                if raw_atk == "":
                    mode8_attacks_per_id = default_m8_atk
                    break
                if raw_atk.isdigit() and 1 <= int(raw_atk) <= 50:
                    mode8_attacks_per_id = int(raw_atk)
                    break
                print(" [!] Kripya 1 se 50 ke beech ka sahi attack number type karein.")
            mem["mode8_attacks_per_id"] = mode8_attacks_per_id

        saved_idx = mem.get("current_id_index", 1)
        if 1 < saved_idx <= total_ids:
            ans = input(f" Pichhli baar Bot ID #{saved_idx} par tha. Kya ID #{saved_idx} se Resume karein? (y/n) [Default=n (Start from ID #1)]: ").strip().lower()
            if ans == "y":
                start_id_index = saved_idx

        mem["total_ids"] = total_ids
        mem["current_id_index"] = start_id_index
        save_id_memory(mem)
        print(f" [✔] ID Changement Configured: Total IDs = {total_ids} | Starting on ID #{start_id_index} [{get_id_role_label(start_id_index)}]")

    mode_summary_label = mode_names[choice] + (f" ({mode8_attacks_per_id} Atk/ID)" if choice == "8" else "")
    reset_session_progress_report(mode_label=mode_summary_label)
    sync_initial_id_to_report(start_id_index)

    input("\n Bot Start karne ke liye [ENTER] key dabayein: ")
    return choice, total_ids, start_id_index, mode8_attacks_per_id, custom_cfg

def run_combined_building_and_wall_upgrade(loop_label="COMBINED UPGRADE"):
    check_pause_point(allow_raise=True)
    print("\n----------------------------------------------------------------------")
    print(f" | [{loop_label}] Single Storage Check -> Building -> Wall Handoff |")
    print("----------------------------------------------------------------------")

    if perform_home_cleanup_once(max_age_sec=1.5):
        human_sleep(0.18, 0.04)

    img = bot_tools.get_screenshot()
    check_and_handle_maintenance_break(img)

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
    consecutive_failed_attacks = 0

    while state_dict["attacks_done"] < target_attacks:
        check_pause_point(allow_raise=True)
        next_atk_num = state_dict["attacks_done"] + 1
        pre_attack_wait = random.uniform(0.20, 0.38)
        print(f"\n [{phase_label}] Attack #{next_atk_num} / {target_attacks} starting in {pre_attack_wait:.2f}s (Speed={get_bot_speed_multiplier():.2f}x)...")
        smart_sleep(pre_attack_wait, apply_speed=True)

        atk_ok = execute_attack(is_first_attack=(next_atk_num == 1))
        if atk_ok:
            consecutive_failed_attacks = 0
            state_dict["attacks_done"] += 1
            print(f" [✔] [{phase_label}] Completed Attack #{state_dict['attacks_done']} / {target_attacks}!")
        else:
            consecutive_failed_attacks += 1
            print(f" [!] [{phase_label}] Attack #{next_atk_num} unsuccessful (Consecutive Fails: {consecutive_failed_attacks}/2).")
            if consecutive_failed_attacks >= 2:
                print(" [SMART RECOVERY] 2 consecutive full attacks failed on this ID! Advancing to next phase...")
                ensure_return_to_home_page_a14()
                break

        if state_dict["attacks_done"] > 0 and (state_dict["attacks_done"] % 5 == 0) and (state_dict["attacks_done"] < target_attacks):
            print(f" [HEALTH CHECK] 5-Attack milestone ({state_dict['attacks_done']}/{target_attacks}) -> Checking Clan Chat, Daily Reward & Maintenance...")
            run_zone2_home_periodic_checks()

    run_zone2_home_periodic_checks()

def main_loop():
    bot_mode, total_ids, current_id, mode8_attacks_per_id, custom_cfg = select_bot_configuration()

    start_pause_resume_listener()

    # Home-Page-Only Symmetric 2-Finger Zoom-Out at startup
    zoom_out_village_a14(passes=2, reason="BOT STARTUP HOME PAGE ZOOM-OUT")

    if bot_mode in ["8", "9"]:
        print(f"\n[MODE {bot_mode} STARTUP] Waiting 1.0 second on ID #{current_id} before starting...")
        smart_sleep(1.0, apply_speed=True)
    else:
        startup_rest = random.uniform(0.8, 1.2)
        print(f"\n[STARTUP] Taking {startup_rest:.1f} seconds initial rest on Home Page (Speed={get_bot_speed_multiplier():.2f}x)...")
        smart_sleep(startup_rest, apply_speed=True)

    cycle_count = 1
    consecutive_loop_errors = 0

    runtime_state = {
        "current_id": current_id,
        "phase": "START_CYCLE",
        "attacks_done": 0,
        "custom_round_idx": 1,
        "id_timer_start": None,
        "id_elapsed_sec": 0.0,
        "loop2_any_upgraded": False
    }

    while True:
        try:
            check_pause_point(allow_raise=True)
            active_id = runtime_state["current_id"]
            id_role = get_id_role_label(active_id)
            cur_spd = get_bot_speed_multiplier()

            print("\n" + "=" * 74)
            if bot_mode in ["4", "5", "6", "8", "9"]:
                print(f" MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}] | SPEED: {cur_spd:.2f}x | ACTIVE ID: #{active_id}/{total_ids} [{id_role}]")
            else:
                print(f" MASTER CYCLE #{cycle_count} | MODE: [{bot_mode}] | SPEED: {cur_spd:.2f}x")
            print("=" * 74)

            run_zone2_home_periodic_checks()

            if bot_mode == "1":
                pre_wait = random.uniform(0.20, 0.38)
                print(f" [MODE 1] Starting Fast Attack in {pre_wait:.2f}s...")
                smart_sleep(pre_wait, apply_speed=True)
                execute_attack(is_first_attack=(cycle_count == 1))

            elif bot_mode == "2":
                run_combined_building_and_wall_upgrade("MODE 2 COMBINED UPGRADE")
                print(" [MODE 2] Waiting 1 Minute (60s) before next Combined Upgrade resource check...")
                smart_sleep(60.0, apply_speed=False)

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

            elif bot_mode == "4":
                print(f" [MODE 4] Spending 2 Seconds on ID #{active_id}/{total_ids} [{id_role}]...")
                perform_home_cleanup_once(max_age_sec=1.0)
                smart_sleep(2.0, apply_speed=True)

                next_id = (active_id % total_ids) + 1
                print(f" [MODE 4] 2 Seconds complete! Switching from ID #{active_id} -> ID #{next_id}/{total_ids}...")
                switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                runtime_state["current_id"] = next_id

            elif bot_mode == "5":
                target_duration_sec = 600.0
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
                    pre_wait = random.uniform(0.20, 0.38)
                    smart_sleep(pre_wait, apply_speed=True)

                    execute_attack(is_first_attack=(atk_no == 1))
                    runtime_state["attacks_done"] += 1

                next_id = (active_id % total_ids) + 1
                switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                runtime_state["current_id"] = next_id
                runtime_state["id_timer_start"] = None
                runtime_state["id_elapsed_sec"] = 0.0
                runtime_state["attacks_done"] = 0

            elif bot_mode == "6":
                if runtime_state["phase"] == "START_CYCLE":
                    run_combined_building_and_wall_upgrade(f"ID #{active_id} - COMBINED UPGRADE LOOP #1")
                    runtime_state["phase"] = "ATTACK_10"
                    runtime_state["attacks_done"] = 0

                if runtime_state["phase"] == "ATTACK_10":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=10,
                        phase_label=f"ID #{active_id} - 10 FAST ATTACKS"
                    )
                    runtime_state["phase"] = "UPGRADE_LOOP_2"
                    runtime_state["attacks_done"] = 0

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

                if runtime_state["phase"] == "ATTACK_5":
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=5,
                        phase_label=f"ID #{active_id} - 5 EXTRA FAST ATTACKS"
                    )
                    runtime_state["phase"] = "SWITCH_ID"
                    runtime_state["attacks_done"] = 0

                if runtime_state["phase"] == "SWITCH_ID":
                    next_id = (active_id % total_ids) + 1
                    switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                    runtime_state["current_id"] = next_id
                    runtime_state["phase"] = "START_CYCLE"
                    runtime_state["attacks_done"] = 0
                    runtime_state["loop2_any_upgraded"] = False

            elif bot_mode == "8":
                if runtime_state["phase"] in ["START_CYCLE", "MODE8_ATTACKS"]:
                    runtime_state["phase"] = "MODE8_ATTACKS"
                    run_n_fast_attacks_with_resume_memory(
                        runtime_state,
                        target_attacks=mode8_attacks_per_id,
                        phase_label=f"MODE 8 | ID #{active_id} ({mode8_attacks_per_id} FAST ATTACKS)"
                    )
                    runtime_state["phase"] = "MODE8_BUILDING_UPGRADE"
                    runtime_state["attacks_done"] = 0

                if runtime_state["phase"] == "MODE8_BUILDING_UPGRADE":
                    print(f"\n [MODE 8 DIRECT UPGRADE] {mode8_attacks_per_id} Attacks complete! Bina Storage Check kiye seedha Building Upgrade par ja rahe hain...")
                    run_a14_buildings_only_upgrade_loop(stop_at_builders=1)
                    runtime_state["phase"] = "MODE8_SWITCH_ID"

                if runtime_state["phase"] == "MODE8_SWITCH_ID":
                    print(" [MODE 8] Waiting 1.0 second after Building Upgrade before ID Switch...")
                    smart_sleep(1.0, apply_speed=True)

                    next_id = (active_id % total_ids) + 1
                    switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                    runtime_state["current_id"] = next_id
                    runtime_state["phase"] = "START_CYCLE"
                    runtime_state["attacks_done"] = 0

                    print(f" [MODE 8] Arrived on ID #{next_id}! Waiting 1.0 second before starting {mode8_attacks_per_id} Fast Attacks...")
                    smart_sleep(1.0, apply_speed=True)

            elif bot_mode == "9":
                combo = custom_cfg.get("combo_type", "1+2+3")
                atk_target = int(custom_cfg.get("attacks_per_round", 5))
                upg_order = custom_cfg.get("upgrade_order", "BUILDING_THEN_WALL")
                chk_store = bool(custom_cfg.get("check_storage", False))
                stop_b = int(custom_cfg.get("stop_builders", 0))
                max_rounds = int(custom_cfg.get("rounds_per_id", 3)) if "3" in combo else 1

                while runtime_state["custom_round_idx"] <= max_rounds:
                    r_no = runtime_state["custom_round_idx"]
                    print(f"\n [CUSTOM MODE 9] ID #{active_id} | Attempt/Round #{r_no}/{max_rounds} | Combo={combo} | Order={upg_order}")

                    if runtime_state["phase"] in ["START_CYCLE", "CUSTOM_ATTACKS"]:
                        runtime_state["phase"] = "CUSTOM_ATTACKS"
                        run_n_fast_attacks_with_resume_memory(
                            runtime_state,
                            target_attacks=atk_target,
                            phase_label=f"CUSTOM MODE 9 | ID #{active_id} (Round {r_no}/{max_rounds} - {atk_target} ATTACKS)"
                        )
                        runtime_state["phase"] = "CUSTOM_UPGRADE"
                        runtime_state["attacks_done"] = 0

                    if runtime_state["phase"] == "CUSTOM_UPGRADE":
                        if "2" in combo:
                            do_upg = True
                            if chk_store:
                                perform_home_cleanup_once(max_age_sec=1.5)
                                do_upg = check_resources_full_for_upgrade()
                            if do_upg:
                                run_custom_mode_upgrade_loop(order_type=upg_order, stop_at_builders=stop_b)
                                if bot_tools.LAST_DETECTED_BUILDERS is not None and bot_tools.LAST_DETECTED_BUILDERS <= 0:
                                    print(f" [✔] [CUSTOM MODE 9] Builders reached 0 on Round #{r_no}! Proceeding to ID Switch...")
                                    runtime_state["custom_round_idx"] = max_rounds + 1
                                    break
                        runtime_state["custom_round_idx"] += 1
                        runtime_state["phase"] = "START_CYCLE"

                if "3" in combo:
                    smart_sleep(1.0, apply_speed=True)
                    next_id = (active_id % total_ids) + 1
                    switch_to_target_id(next_id, total_ids, current_id_index=active_id)
                    runtime_state["current_id"] = next_id
                    smart_sleep(1.0, apply_speed=True)

                runtime_state["custom_round_idx"] = 1
                runtime_state["phase"] = "START_CYCLE"
                runtime_state["attacks_done"] = 0

            clean_ram_garbage()
            consecutive_loop_errors = 0

            print(f"\n[SUCCESS] Master Cycle #{cycle_count} Completed! (Speed={get_bot_speed_multiplier():.2f}x)")
            cycle_count += 1
            smart_sleep(random.uniform(0.40, 0.70), apply_speed=True)

        except BotPausedResumeHomeException as resume_sig:
            print(f"\n[RESUME HANDLER] {resume_sig} (Speed={get_bot_speed_multiplier():.2f}x Preserved)")
            if bot_mode == "5" and runtime_state["id_timer_start"] is not None:
                runtime_state["id_elapsed_sec"] += max(0.0, time.time() - runtime_state["id_timer_start"])
                runtime_state["id_timer_start"] = time.time()

            ensure_return_to_home_page_a14()
            zoom_out_village_a14(passes=2, reason="RESUME HOME ZOOM-OUT")
            human_sleep(0.6, 0.10)
            print(f" [RESUMED ON HOME PAGE] Continuing ID #{runtime_state['current_id']} | Phase: {runtime_state['phase']} | Attacks Done: {runtime_state['attacks_done']} | Speed: {get_bot_speed_multiplier():.2f}x")
            continue

        except KeyboardInterrupt:
            print("\n[!] Bot ko manually roka gaya (Ctrl+C). Generating Final Previous Progress Report...")
            print_previous_progress_report(report_stage="STOPPED / COMPLETED (FINAL SESSION REPORT)")
            break

        except Exception as e:
            consecutive_loop_errors += 1
            record_stat("stuck_recoveries", 1)
            print("\n==================================================")
            print(f"[! CRITICAL ERROR #{consecutive_loop_errors} !] Main Loop me error aayi:")
            print(f"-> Reason: {str(e)}")
            traceback.print_exc()
            print("==================================================")
            print("Recovering in 2.5 seconds...")
            time.sleep(2.5)
            ensure_return_to_home_page_a14()
            zoom_out_village_a14(passes=2, reason="ERROR RECOVERY ZOOM-OUT")

            if consecutive_loop_errors >= 5 and bot_mode in ["4", "5", "6", "8", "9"] and total_ids > 1:
                next_id = (runtime_state["current_id"] % total_ids) + 1
                print(f" [NIGHT WATCHDOG] 5 consecutive errors on ID #{runtime_state['current_id']}! Switching to ID #{next_id}...")
                switch_to_target_id(next_id, total_ids, current_id_index=runtime_state["current_id"])
                runtime_state["current_id"] = next_id
                runtime_state["phase"] = "START_CYCLE"
                runtime_state["attacks_done"] = 0
                runtime_state["custom_round_idx"] = 1
                consecutive_loop_errors = 0

if __name__ == "__main__":
    main_loop()
