#!/bin/bash
set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
VENV="$SCRIPT_DIR/.venv/bin/python3"
TOTAL_PASS=0; TOTAL_FAIL=0; TOTAL_SKIP=0
START_TIME=$(date +%s)

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*"; TOTAL_PASS=$((TOTAL_PASS + 1)); }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
header() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

# Tier functions
tier1_syntax() {
    header "Tier 1: Syntax Check"
    local ok=0 err=0
    # Python files
    for f in src/amy/commander.py src/amy/sensorium.py src/amy/thinking.py src/amy/target_tracker.py \
             src/amy/escalation.py src/amy/perception.py src/amy/extraction.py src/amy/event_bus.py \
             src/amy/nodes/synthetic_camera.py src/amy/nodes/mqtt_robot.py src/amy/audio/synthetic.py \
             src/amy/audio/sound_effects.py src/amy/audio/audio_library.py \
             src/amy/synthetic/video_gen.py src/amy/synthetic/video_library.py \
             src/amy/simulation/combat.py src/amy/simulation/game_mode.py src/amy/simulation/behaviors.py \
             src/app/main.py src/app/config.py src/app/routers/audio.py src/app/routers/synthetic_feed.py; do
        if [ -f "$SCRIPT_DIR/$f" ]; then
            if python3 -m py_compile "$SCRIPT_DIR/$f" 2>/dev/null; then
                ok=$((ok + 1))
            else
                fail "py_compile: $f"
                err=$((err + 1))
            fi
        fi
    done
    # JS files
    for f in frontend/js/war.js frontend/js/war-fx.js frontend/js/war-combat.js \
             frontend/js/war-hud.js frontend/js/app.js frontend/js/assets.js \
             frontend/js/war-audio.js frontend/js/war-events.js frontend/js/war-fog.js; do
        if [ -f "$SCRIPT_DIR/$f" ]; then
            if node --check "$SCRIPT_DIR/$f" 2>/dev/null; then
                ok=$((ok + 1))
            else
                fail "node --check: $f"
                err=$((err + 1))
            fi
        fi
    done
    if [ $err -eq 0 ]; then pass "Syntax: $ok files OK"; else fail "Syntax: $err errors"; fi
}

tier2_unit() {
    header "Tier 2: Unit Tests (pytest)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/amy/" -m unit --tb=short -q 2>&1; then
        pass "Unit tests"
    else
        fail "Unit tests"
    fi
}

tier3_js() {
    header "Tier 3: JS Tests"
    local js_err=0
    for jstest in test_war_math.js test_war_audio.js test_war_fog.js test_geo_math.js test_panel_manager.js test_mesh_panel.js; do
        if [ -f "$SCRIPT_DIR/tests/js/$jstest" ]; then
            if node "$SCRIPT_DIR/tests/js/$jstest"; then
                pass "JS $jstest"
            else
                fail "JS $jstest"
                js_err=$((js_err + 1))
            fi
        else
            warn "JS test not found: tests/js/$jstest"
            TOTAL_SKIP=$((TOTAL_SKIP + 1))
        fi
    done
}

tier4_vision() {
    header "Tier 4: Vision Audit (llava:7b)"
    if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        local args="--quick"
        [ -n "${VIEWS:-}" ] && args="$args --views $VIEWS"
        $VENV "$SCRIPT_DIR/tests/ui/test_vision.py" $args
        pass "Vision audit"
    else
        warn "Ollama not available, skipping vision audit"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier4_gameplay() {
    header "Tier 4.5: Gameplay Verification"
    if [ -f "$SCRIPT_DIR/tests/ui/test_gameplay.py" ]; then
        if $VENV "$SCRIPT_DIR/tests/ui/test_gameplay.py"; then
            pass "Gameplay verification"
        else
            fail "Gameplay verification"
        fi
    else
        warn "Gameplay test not found"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier5_e2e() {
    header "Tier 5: E2E (Playwright)"
    if [ -d "$SCRIPT_DIR/tests/e2e/node_modules" ]; then
        cd "$SCRIPT_DIR/tests/e2e"
        if npx playwright test --project=chromium 2>&1; then
            pass "E2E tests"
        else
            fail "E2E tests"
        fi
        cd "$SCRIPT_DIR"
    else
        warn "Playwright not installed"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier6_battle() {
    header "Tier 6: Battle Verification (Fleet + llava)"
    if [ -f "$SCRIPT_DIR/tests/ui/test_battle.py" ]; then
        if $VENV "$SCRIPT_DIR/tests/ui/test_battle.py"; then
            pass "Battle verification (8 phases, fleet-parallel llava)"
        else
            fail "Battle verification"
        fi
    else
        warn "Battle test not found"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier7_visual() {
    header "Tier 7: Visual E2E (Three-Layer Verification)"
    if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        if $VENV -m pytest "$SCRIPT_DIR/tests/visual/" -v --tb=short 2>&1; then
            pass "Visual E2E (three-layer)"
        else
            fail "Visual E2E (three-layer)"
        fi
    else
        warn "Ollama not available, skipping visual E2E"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier8_lib() {
    header "Tier 8: Test Infrastructure Tests"
    if $VENV -m pytest "$SCRIPT_DIR/tests/lib/" -m unit --tb=short -q 2>&1; then
        pass "Test infrastructure tests"
    else
        fail "Test infrastructure tests"
    fi
}

tier8b_ros2() {
    header "Tier 8b: ROS2 Robot Tests"
    if [ -d "$SCRIPT_DIR/examples/ros2-robot/tests" ]; then
        if python3 -m pytest "$SCRIPT_DIR/examples/ros2-robot/tests/" --tb=short -q 2>&1; then
            pass "ROS2 robot tests"
        else
            fail "ROS2 robot tests"
        fi
    else
        warn "ROS2 robot tests not found"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier9_integration() {
    header "Tier 9: Integration Tests (Server E2E)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/integration/" -m integration --tb=short -q 2>&1; then
        pass "Integration tests"
    else
        fail "Integration tests"
    fi
}

tier10_quality() {
    header "Tier 10: Visual Quality Check (Unified Command Center)"
    if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_unified_quality.py" -v --timeout=180 --tb=short 2>&1; then
            pass "Visual quality tests (unified)"
        else
            fail "Visual quality tests (unified)"
        fi
    else
        warn "Ollama not available, skipping visual quality tests"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier11_smoke() {
    header "Tier 11: UI Smoke Tests (Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_unified_smoke.py" -v --tb=short 2>&1; then
        pass "UI smoke tests"
    else
        fail "UI smoke tests"
    fi
}

tier12_layout() {
    header "Tier 12: UI Layout Validation (Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/ui/test_layout_validation.py" -v --tb=short 2>&1; then
        pass "UI layout validation"
    else
        fail "UI layout validation"
    fi
}

tier13_ux() {
    header "Tier 13: User Experience Tests (Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/ui/" -m "ux and not defect" -v --tb=short 2>&1; then
        pass "UX tests"
    else
        fail "UX tests"
    fi
}

tier14_defects() {
    header "Tier 14: Known Defect Detection (expected failures)"
    info "These tests detect KNOWN panel management defects."
    info "Failures here = defects still present (not regressions)."
    info "When all pass = defects have been fixed."
    if $VENV -m pytest "$SCRIPT_DIR/tests/ui/test_panel_defects.py" -m defect -v --tb=short 2>&1; then
        pass "Defect tests (all defects fixed!)"
    else
        warn "Defect tests: known defects still present (see output above)"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
    fi
}

tier_dist() {
    header "Distributed Testing (local + ${REMOTE_HOST:-<unset>})"
    if [ -z "${REMOTE_HOST:-}" ]; then
        warn "REMOTE_HOST not set — skipping distributed tests"
        warn "Usage: REMOTE_HOST=myhost ./test.sh --dist"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
        return
    fi
    local REMOTE_CODE_PATH="${REMOTE_CODE_PATH:-~/Code/tritium-sc}"

    info "Syncing code to $REMOTE_HOST..."
    rsync -az --delete --exclude='.venv' --exclude='node_modules' --exclude='__pycache__' \
        --exclude='.git' --exclude='channel_*' --exclude='scenarios/.results' \
        --exclude='tests/.test-results' --exclude='tests/.baselines' \
        "$SCRIPT_DIR/" "$REMOTE_HOST:$REMOTE_CODE_PATH/"

    info "Running tier 2 + tier 8 on both machines..."
    $VENV -m pytest "$SCRIPT_DIR/tests/amy/" -m unit --tb=short -q &
    local pid1=$!
    ssh "$REMOTE_HOST" "cd $REMOTE_CODE_PATH && .venv/bin/python3 -m pytest tests/amy/ -m unit --tb=short -q" &
    local pid2=$!
    wait $pid1 && pass "local unit tests" || fail "local unit tests"
    wait $pid2 && pass "$REMOTE_HOST unit tests" || fail "$REMOTE_HOST unit tests"

    # Test infrastructure tests on remote
    ssh "$REMOTE_HOST" "cd $REMOTE_CODE_PATH && .venv/bin/python3 -m pytest tests/lib/ -m unit --tb=short -q" &
    local lpid=$!

    if command -v ollama &>/dev/null; then
        info "Splitting vision audit across machines..."
        VIEWS="grid,player,3d,zones,targets" $VENV "$SCRIPT_DIR/tests/ui/test_vision.py" --quick --views grid,player,3d,zones,targets &
        local vpid1=$!
        ssh "$REMOTE_HOST" "cd $REMOTE_CODE_PATH && .venv/bin/python3 tests/ui/test_vision.py --quick --views assets,analytics,amy,war,scenarios" &
        local vpid2=$!
        wait $vpid1 && pass "local vision" || fail "local vision"
        wait $vpid2 && pass "$REMOTE_HOST vision" || fail "$REMOTE_HOST vision"
    fi

    wait $lpid && pass "$REMOTE_HOST lib tests" || fail "$REMOTE_HOST lib tests"
}

# Summary
summary() {
    local elapsed=$(( $(date +%s) - START_TIME ))
    echo ""
    header "Summary"
    echo -e "  ${GREEN}Passed: $TOTAL_PASS${NC}"
    echo -e "  ${RED}Failed: $TOTAL_FAIL${NC}"
    echo -e "  ${YELLOW}Skipped: $TOTAL_SKIP${NC}"
    echo -e "  Time: ${elapsed}s"
    echo ""
    if [ $TOTAL_FAIL -eq 0 ]; then
        echo -e "${GREEN}${BOLD}ALL CLEAR${NC}"
    else
        echo -e "${RED}${BOLD}FAILURES DETECTED${NC}"
    fi
}

# Main — disable set -e for tier functions so failures don't kill the script
main() {
    header "TRITIUM-SC Test Suite"

    set +e
    case "${1:-}" in
        ""|fast)
            tier1_syntax; tier2_unit; tier3_js; tier8_lib; tier8b_ros2; tier11_smoke ;;
        all)
            tier1_syntax; tier2_unit; tier3_js; tier4_vision; tier4_gameplay; tier5_e2e; tier6_battle; tier7_visual; tier8_lib; tier8b_ros2; tier9_integration; tier10_quality; tier11_smoke; tier13_ux; tier14_defects ;;
        1) tier1_syntax ;;
        2) tier2_unit ;;
        3) tier3_js ;;
        4) tier4_vision ;;
        5) tier5_e2e ;;
        6) tier6_battle ;;
        7) tier7_visual ;;
        8) tier8_lib ;;
        9) tier9_integration ;;
        10) tier10_quality ;;
        11) tier11_smoke ;;
        12) tier12_layout ;;
        13) tier13_ux ;;
        14) tier14_defects ;;
        --dist) tier1_syntax; tier2_unit; tier3_js; tier8_lib; tier_dist ;;
        --visual) tier7_visual ;;
        --gameplay) tier4_gameplay ;;
        --battle) tier6_battle ;;
        --integration) tier9_integration ;;
        --quality) tier10_quality ;;
        --smoke) tier11_smoke ;;
        --layout) tier12_layout ;;
        --ux) tier13_ux ;;
        --defects) tier14_defects ;;
        *) echo "Usage: $0 [all|fast|1-14|--dist|--visual|--gameplay|--battle|--integration|--quality|--smoke|--layout|--ux|--defects]"; exit 1 ;;
    esac
    set -e

    summary
    exit $TOTAL_FAIL
}

main "$@"
