
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
    check_clan_chat_drawer_a14,
    is_on_home_page_a14,
    check_wrong_and_home_page_a14,
    ensure_return_to_home_page_a14,
    click_gold_storage_3_times,
    record_stat,
    record_duration
)

# Full 45.0s Battle Timer
BATTLE_TIMER_DURATION_SEC = 45.0

# ==========================================
# 1. CLOUD, BATTLEFIELD & EARLY VICTORY DETECTORS
# ==========================================

def is_cloud_screen_a14(img):
    """
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
            if r > 175 and g > 175 and b > 165 and (max(r, g, b) - min(r, g, b) <= 38):
                cloud_px += 1

    return total_px > 0 and (cloud_px / float(total_px)) >= 0.55

def is_enemy_battlefield_loaded_a14(img):
    """
    Verifies that:
      1. We are NOT in matchmaking clouds.
      2. We are NOT on the Home Page (Green '+' is absent).
      3. The red/white Surrender / End Battle button at (181, 800) is clearly visible.
      4. The bottom troop deployment bar (y = 955..1025) has active card contrast.
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

    if not (red_btn_px >= 10 and white_txt_px >= 3):
        return False

    bar_bright_px = 0
    for tx in range(470, min(w - 100, 1530), 65):
        r, g, b = px_map[tx, min(h - 10, 985)]
        if (r + g + b) > 140:
            bar_bright_px += 1

    return bar_bright_px >= 4

def is_return_home_victory_button_visible_a14(img):
    """
    Checks if the green 'Return Home' button at (1222, 918) has appeared on screen.
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

def scan_battlefield_or_restart(stage_name, img=None):
    """
    Checks Wrong Buttons and Home Page Green '+' icon during attack pauses.
    If clouds are still visible after 18s, waits up to 8s extra for clouds to clear.
    """
    check_pause_point(allow_raise=True)
    print(f" [SCAN] [{stage_name}] Checking Battlefield, Wrong Buttons & Home Page status...")
    if img is None:
        img = get_screenshot(force_fresh=True)

    cloud_wait_extra = 0.0
    while is_cloud_screen_a14(img) and cloud_wait_extra < 8.0:
        print(f" [EXTENDED CLOUD GUARD] [{stage_name}] Clouds still visible ({cloud_wait_extra:.1f}s/8.0s extra)... Waiting 1.0s...")
        smart_sleep(1.0, apply_speed=False)
        cloud_wait_extra += 1.0
        img = get_screenshot(force_fresh=True)

    if is_cloud_screen_a14(img):
        reason = "Clouds did not clear after extended 26s wait"
        print(f" [!] [ALERT at {stage_name}] {reason}! Restarting Attack Loop...")
        raise RestartLoopException(reason)

    wrong_found, home_found, latest_img = check_wrong_and_home_page_a14(img, check_clan_chat=False)
    if wrong_found or home_found:
        reason = "Wrong Button detected" if wrong_found else "Still stuck on Home Page (Green '+' visible)"
        print(f" [!] [ALERT at {stage_name}] {reason}! Restarting Attack Loop...")
        raise RestartLoopException(reason)

    return latest_img

def wait_for_enemy_base_load_smart(max_wait_sec=18.0):
    """
    Starts checking for Enemy Battlefield / Clouds just 0.5s after clicking Attack (1980, 972).
    Polls every 0.55s up to 18.0s max.
    """
    min_initial_wait = 0.5
    poll_interval = 0.55
    print(f" [SMART 18s LOAD] Waiting initial {min_initial_wait:.1f}s (Max {max_wait_sec:.0f}s) for Enemy Base...")
    start_t = time.time()
    smart_sleep(min_initial_wait, apply_speed=False)

    while (time.time() - start_t) < max_wait_sec:
        check_pause_point(allow_raise=True)
        img = get_screenshot(force_fresh=True)
        elapsed = time.time() - start_t

        if is_cloud_screen_a14(img):
            print(f" [CLOUDS] Matchmaking clouds visible ({elapsed:.1f}s/{max_wait_sec:.0f}s)... Waiting for base...")
        elif is_enemy_battlefield_loaded_a14(img):
            print(f" [✔] [BASE LOADED EARLY] Enemy Battlefield & Troop Bar confirmed in {elapsed:.1f}s (Saved {max_wait_sec - elapsed:.1f}s)!")
            return True
        else:
            if elapsed >= 2.8:
                wrong_found, home_found, _ = check_wrong_and_home_page_a14(img, check_clan_chat=True)
                if wrong_found or home_found:
                    reason = "Wrong Button / Clan Chat blocked matchmaking" if wrong_found else f"Stuck on Home Page at {elapsed:.1f}s after Attack click"
                    print(f" [!] [FAST MATCHMAKING RETRY] {reason}! Restarting Attack Loop...")
                    raise RestartLoopException(reason)

        rem = max_wait_sec - (time.time() - start_t)
        if rem <= 0:
            break
        smart_sleep(min(poll_interval, rem), apply_speed=False)

    return False

def _deploy_all_troops_and_heroes_sequence():
    """
    Executes:
      1. Army 1 (470, 988) -> 4 Rounds on ARMY_1_DEPLOY_LIST
      2. Army 2 (590, 985) -> 2 Rounds on ARMY_2_DEPLOY_LIST
      3. Siege Machine (770, 977) -> Selected ONCE, deployed on ONLY 4 safe coords (SIEGE_DEPLOY_LIST),
         and NEVER tapped again so it never self-destructs!
      4. Heroes 1, 2, 3, 4 -> 1 Round each on ARMY_1_DEPLOY_LIST
    NO battlefield zoom-in/zoom-out is ever performed here so the enemy base never shifts off-center!
    """
    # 1. Army 1 Select (470, 988) -> 4 Rounds Deploy
    print(" [DEPLOY] Selecting Army 1 (470, 988) & deploying 4 Rounds in Serial Order...")
    tap(*FAST_ATTACK["ARMY_1_SELECT"], delay_range=(0.03, 0.05), jitter=2)
    smart_sleep(0.05, apply_speed=True, min_floor=0.03)
    fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=4, jitter=3)

    # 2. Army 2 Select (590, 985) -> 2 Rounds Deploy
    print(" [DEPLOY] Selecting Army 2 (590, 985) & deploying 2 Rounds on 3 Coords...")
    smart_sleep(0.08, apply_speed=True, min_floor=0.04)
    tap(*FAST_ATTACK["ARMY_2_SELECT"], delay_range=(0.03, 0.05), jitter=2)
    smart_sleep(0.05, apply_speed=True, min_floor=0.03)
    fast_serial_taps(FAST_ATTACK["ARMY_2_DEPLOY_LIST"], rounds=2, jitter=3)

    # 3. Siege Machine (770, 977) -> Select ONCE & tap ONLY 4 coords (never tapped again!)
    print(" [DEPLOY] Selecting Siege Machine (770, 977) ONCE & deploying on 4 safe coords...")
    smart_sleep(0.06, apply_speed=True, min_floor=0.03)
    tap(*FAST_ATTACK["SIEGE_SELECT"], delay_range=(0.04, 0.06), jitter=2)
    siege_coords = FAST_ATTACK.get("SIEGE_DEPLOY_LIST", FAST_ATTACK["ARMY_1_DEPLOY_LIST"][:4])
    fast_serial_taps(siege_coords, rounds=1, jitter=3)
    smart_sleep(0.04, apply_speed=True, min_floor=0.02)

    # 4. Heroes 1-4 (1 Round each on Army 1 Coords)
    print(" [DEPLOY] Deploying Heroes 1-4 (1 Round each on Army 1 Coords)...")
    heroes_only = [
        ("Hero 1", FAST_ATTACK["HERO_1_SELECT"]),
        ("Hero 2", FAST_ATTACK["HERO_2_SELECT"]),
        ("Hero 3", FAST_ATTACK["HERO_3_SELECT"]),
        ("Hero 4", FAST_ATTACK["HERO_4_SELECT"])
    ]
    for unit_name, select_coord in heroes_only:
        check_pause_point(allow_raise=True)
        tap(*select_coord, delay_range=(0.03, 0.05), jitter=2)
        fast_serial_taps(FAST_ATTACK["ARMY_1_DEPLOY_LIST"], rounds=1, jitter=3)
        smart_sleep(0.03, apply_speed=True, min_floor=0.02)

# ==========================================
# 2. MASTER FAST ATTACK EXECUTION (6s DEPLOY + 4s WAIT + HERO ABILITY + 4.2s RETURN HOME)
# ==========================================

def execute_attack(is_first_attack=True):
    for attempt in range(1, 4):
        atk_attempt_start_t = time.time()
        try:
            check_pause_point(allow_raise=True)
            print("\n======================================================================")
            print(f" || [FAST ATTACK LOOP - 45s TIMER] - ATTEMPT #{attempt}/3 ||")
            print("======================================================================")

            # 1. Home Page: 0.6s Wait + Clan Chat & Wrong Button Check + Single 3x Gold Storage Click
            print(" [0.6s] Checking Home Page, Clan Chat Drawer & clicking Gold Storage 3x...")
            smart_sleep(0.60, apply_speed=True)
            check_wrong_buttons_a14(check_clan_chat=True)
            click_gold_storage_3_times()

            # 2. Matchmaking (0.20s -> Battle -> 0.35s -> Find Match -> 0.65s -> Attack)
            print(" [0.20s] Clicking Battle Button (182, 961)...")
            smart_sleep(0.20, apply_speed=True)
            tap(*FAST_ATTACK["BATTLE_BTN"], delay_range=(0.0, 0.0), jitter=3)

            print(" [0.35s] Waiting 0.35s -> Clicking Find Match (364, 808)...")
            smart_sleep(0.35, apply_speed=True)
            tap(*FAST_ATTACK["FIND_MATCH_BTN"], delay_range=(0.0, 0.0), jitter=3)

            print(" [0.65s] Waiting 0.65s -> Clicking Attack Button (1980, 972)...")
            smart_sleep(0.65, apply_speed=True)
            tap(*FAST_ATTACK["ATTACK_BTN"], delay_range=(0.0, 0.0), jitter=3)

            # 3. Smart Enemy Base Load (Starts checking at 0.5s!)
            loaded_early = wait_for_enemy_base_load_smart(max_wait_sec=18.0)
            if not loaded_early:
                scan_battlefield_or_restart("Post-18s Base Load Check")

            # ==================================================================
            # PHASE 1: SELECT & DEPLOY ALL SPELLS, TROOPS, SIEGE & HEROES WITHIN 6.0 SECONDS!
            # (NO Battlefield Zoom-Out here so the base NEVER scrolls or shifts off-center!)
            # ==================================================================
            print(" [6s DEPLOY WINDOW] Starting Spells + Army 1/2 + Siege (4-tap) + Heroes 1-4 deployment (Target <= 6.0s)...")

            # Step 4: Spell Select (1527, 983) -> 2 Rounds Deploy (Starts 45s Battle Timer & 6s Deploy Window)
            tap(*FAST_ATTACK["SPELL_SELECT"], delay_range=(0.03, 0.05), jitter=2)
            spell_select_timer = time.time()
            smart_sleep(0.08, apply_speed=True, min_floor=0.04)
            fast_serial_taps(FAST_ATTACK["SPELL_DEPLOY_LIST"], rounds=2, jitter=3)
            smart_sleep(0.08, apply_speed=True, min_floor=0.04)

            # Steps 5, 6, 7: Deploy Army 1 (4x), Army 2 (2x), Siege (4-tap once), & Heroes 1-4 (1x each)
            _deploy_all_troops_and_heroes_sequence()

            # Complete the 6.0-second deployment window cleanly
            elapsed_deploy_window = time.time() - spell_select_timer
            if elapsed_deploy_window < 6.0:
                rem_6s = 6.0 - elapsed_deploy_window
                print(f" [6s WINDOW] All units deployed in {elapsed_deploy_window:.2f}s! Completing remaining {rem_6s:.2f}s of 6.0s window...")
                smart_sleep(rem_6s, apply_speed=False)
            else:
                print(f" [6s WINDOW] All units selected & deployed in {elapsed_deploy_window:.2f}s!")

            # ==================================================================
            # PHASE 2: WAIT EXACTLY 4.0 SECONDS AFTER THE 6-SECOND DEPLOYMENT WINDOW!
            # ==================================================================
            print(" [4.0s POST-DEPLOY WAIT] 6s deployment finished! Waiting 4.0 seconds before activating Hero Abilities...")
            smart_sleep(4.0, apply_speed=False)

            # ==================================================================
            # PHASE 3: ACTIVATE ONLY HERO 1, 2, 3, 4 ABILITIES (SIEGE IS NEVER TAPPED AGAIN!)
            # ==================================================================
            print(" [HERO ABILITIES] Activating Hero 1, 2, 3, 4 Abilities (Siege Machine untouched)...")
            batch_tap_sequence([
                FAST_ATTACK["HERO_1_SELECT"],
                FAST_ATTACK["HERO_2_SELECT"],
                FAST_ATTACK["HERO_3_SELECT"],
                FAST_ATTACK["HERO_4_SELECT"]
            ], inter_delay=0.06, jitter=2)

            total_ability_mark = time.time() - spell_select_timer
            print(f" [i] Deployment (6s) + Wait (4s) + Hero Abilities completed at {total_ability_mark:.2f}s mark!")

            post_ability_img = get_screenshot(force_fresh=True)
            battle_ended_early = False
            if is_return_home_victory_button_visible_a14(post_ability_img):
                print(f" [✔] [INSTANT VICTORY] Return Home button (1222, 918) already visible at {total_ability_mark:.1f}s!")
                battle_ended_early = True
            else:
                scan_battlefield_or_restart("Post-Hero-4-Ability Check", img=post_ability_img)

            # 9. Wait until 45 seconds from Spell Select (with Early 100% Victory Detection after 20s)
            while not battle_ended_early:
                check_pause_point(allow_raise=True)
                elapsed_since_spell = time.time() - spell_select_timer
                rem_wait = BATTLE_TIMER_DURATION_SEC - elapsed_since_spell
                if rem_wait <= 0:
                    break

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

            # ==================================================================
            # 10. FIXED RETURN HOME SEQUENCE (4.2s RELIABLE SEQUENCE):
            #   - Surrender (3x) -> 0.6s -> Click Okay (1419, 701)
            #   - Wait 2.2 Seconds after Okay so Return Home button reliably appears!
            #   - Click Return Home (1222, 918) TWICE with a 1.0-second gap:
            #       Click #1 -> 1.0s Wait -> Click #2 -> 1.0s Wait
            #   - Verify Home Page Green '+' before counting attack as Successful!
            # ==================================================================
            if not battle_ended_early:
                print(" [SURRENDER] Clicking Surrender Button (181, 800) 3 times...")
                batch_tap_sequence([FAST_ATTACK["SURRENDER_BTN"]] * 3, inter_delay=0.08, jitter=3)

                print(" [0.6s] Waiting 0.6s -> Clicking Okay Button (1419, 701)...")
                smart_sleep(0.60, apply_speed=False)
                tap(*FAST_ATTACK["OKAY_BTN"], delay_range=(0.08, 0.14), jitter=3, apply_speed=False)

                print(" [2.2s GAP] Waiting 2.2 seconds after Okay for Return Home button to appear...")
                smart_sleep(2.20, apply_speed=False)

            print(" [RETURN HOME #1/2] Clicking Return Home Button (1222, 918) [1st Click]...")
            tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.05, 0.08), jitter=3, apply_speed=False)
            print(" [1.0s GAP] Waiting 1.0 second before 2nd Return Home click...")
            smart_sleep(1.00, apply_speed=False)

            print(" [RETURN HOME #2/2] Clicking Return Home Button (1222, 918) [2nd Click]...")
            tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.05, 0.08), jitter=3, apply_speed=False)
            print(" [1.0s SETTLE] Waiting 1.0 second to settle on Home Page...")
            smart_sleep(1.00, apply_speed=False)

            # Strictly verify we returned to Home Page before marking Attack as Successful!
            ret_img = get_screenshot(force_fresh=True)
            _, home_verified, ret_img = check_wrong_and_home_page_a14(ret_img, check_clan_chat=True)

            if not home_verified:
                print(" [!] [RETURN HOME GUARD] Home Page Green '+' abhi nahi dikha! Running extra Return Home tap & recovery...")
                tap(*FAST_ATTACK["RETURN_HOME_BTN"], delay_range=(0.10, 0.18), jitter=3, apply_speed=False)
                smart_sleep(1.00, apply_speed=False)
                home_verified = ensure_return_to_home_page_a14()

            if not home_verified:
                raise RestartLoopException("Could not verify Home Page after Return Home clicks")

            atk_dur = time.time() - atk_attempt_start_t
            record_stat("attacks_success", 1)
            record_duration("attack", atk_dur)
            print(f" [✔] [FAST ATTACK COMPLETE in {atk_dur:.1f}s] Verified back on Home Page!\n")
            return True

        except BotPausedResumeHomeException:
            raise
        except RestartLoopException as re_err:
            record_stat("attacks_failed", 1)
            print(f"\n [RESTARTING ATTACK] Attempt #{attempt}/3 interrupted ({re_err}). Recovering Home Page...")
            ensure_return_to_home_page_a14()
            smart_sleep(0.40, apply_speed=True)
            continue
        except Exception as e:
            record_stat("attacks_failed", 1)
            print("\n[! ERROR!] Fast Attack Loop me error aayi:")
            traceback.print_exc()
            ensure_return_to_home_page_a14()
            return False

    print(" [!] [3 ATTEMPTS FAILED] Running Full In-Game Home Recovery...")
    ensure_return_to_home_page_a14()
    return False

