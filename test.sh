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
    local ok=0 err=0 py_count=0 js_count=0

    # Python: all .py files under src/ (dynamic discovery)
    while IFS= read -r f; do
        py_count=$((py_count + 1))
        if python3 -m py_compile "$f" 2>/dev/null; then
            ok=$((ok + 1))
        else
            fail "py_compile: ${f#$SCRIPT_DIR/}"
            err=$((err + 1))
        fi
    done < <(find "$SCRIPT_DIR/src/" -name '*.py' -not -path '*/__pycache__/*' -not -name '*.pyc' | sort)

    # JS: all .js files under frontend/js/ (dynamic discovery)
    while IFS= read -r f; do
        js_count=$((js_count + 1))
        if node --check "$f" 2>/dev/null; then
            ok=$((ok + 1))
        else
            fail "node --check: ${f#$SCRIPT_DIR/}"
            err=$((err + 1))
        fi
    done < <(find "$SCRIPT_DIR/frontend/js/" -name '*.js' -not -path '*/node_modules/*' | sort)

    if [ $err -eq 0 ]; then
        pass "Syntax: $ok files OK ($py_count Python, $js_count JS)"
    else
        fail "Syntax: $err errors in $((py_count + js_count)) files"
    fi
}

tier2_unit() {
    header "Tier 2: Unit Tests (pytest)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/amy/" "$SCRIPT_DIR/tests/engine/" -m unit --tb=short -q 2>&1; then
        pass "Unit tests"
    else
        fail "Unit tests"
    fi
}

tier3_js() {
    header "Tier 3: JS Tests"
    local js_err=0
    for jstest in test_war_math.js test_war_audio.js test_war_fog.js test_war_fx.js test_fsm_state.js test_geo_math.js test_panel_manager.js test_layout_manager.js test_mesh_panel.js test_game_hud.js test_amy_panel.js test_units_panel.js test_alerts_panel.js test_menu_bar.js test_game_panel.js test_audio_panel.js test_cameras_panel.js test_escalation_panel.js test_events_panel.js test_scenarios_panel.js test_search_panel.js test_system_panel.js test_tak_panel.js test_patrol_panel.js test_videos_panel.js test_zones_panel.js test_events.js test_store.js test_websocket.js test_unit_icons.js test_unit_types.js test_tactical_labels.js test_input.js test_map_render.js test_command_bar.js test_main.js test_map3d.js test_label_collision.js test_war_combat.js test_war_events.js test_war_hud.js; do
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

tier15_alignment() {
    header "Tier 15: Map Layer Alignment (OpenCV + Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_map_alignment.py" -v --tb=short 2>&1; then
        pass "Map alignment tests"
    else
        fail "Map alignment tests"
    fi
}

tier16_layer_isolation() {
    header "Tier 16: Layer Isolation Tests (OpenCV + VLM + Playwright)"
    if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_layer_isolation.py" -v --tb=short 2>&1; then
            pass "Layer isolation tests"
        else
            fail "Layer isolation tests"
        fi
    else
        warn "Ollama not available — running without VLM checks"
        if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_layer_isolation.py" -v --tb=short 2>&1; then
            pass "Layer isolation tests (no VLM)"
        else
            fail "Layer isolation tests (no VLM)"
        fi
    fi
}

tier17_ui_isolation() {
    header "Tier 17: UI Element Isolation (OpenCV + Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_ui_isolation.py" -v --tb=short 2>&1; then
        pass "UI element isolation"
    else
        fail "UI element isolation"
    fi
}

tier18_defense() {
    header "Tier 18: Defense Layers (OpenCV + VLM + Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_defense_layers.py" -v --tb=short 2>&1; then
        pass "Defense layer tests"
    else
        fail "Defense layer tests"
    fi
}

tier19_user_stories() {
    header "Tier 19: User Story Verification (Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_user_stories.py" -v --tb=short 2>&1; then
        pass "User story tests"
    else
        fail "User story tests"
    fi
}

tier20_ui_overlap() {
    header "Tier 20: UI Overlap & Label Validation (OpenCV + Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_ui_overlap.py" -v --tb=short 2>&1; then
        pass "UI overlap tests"
    else
        fail "UI overlap tests"
    fi
}

tier21_panel_coverage() {
    header "Tier 21: Panel & Menu Bar Coverage (Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_panel_coverage.py" -v --tb=short 2>&1; then
        pass "Panel coverage tests"
    else
        fail "Panel coverage tests"
    fi
}

tier22_combat_effects() {
    header "Tier 22: Combat Effects & Game Flow (OpenCV + Playwright)"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_combat_effects.py" -v --tb=short 2>&1; then
        pass "Combat effects tests"
    else
        fail "Combat effects tests"
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
    $VENV -m pytest "$SCRIPT_DIR/tests/amy/" "$SCRIPT_DIR/tests/engine/" -m unit --tb=short -q &
    local pid1=$!
    ssh "$REMOTE_HOST" "cd $REMOTE_CODE_PATH && .venv/bin/python3 -m pytest tests/amy/ tests/engine/ -m unit --tb=short -q" &
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
        # LLM analysis of failures (if Ollama fleet is reachable)
        if command -v curl &>/dev/null && curl -s --connect-timeout 2 http://localhost:11434/api/tags &>/dev/null; then
            info "Running LLM failure analysis..."
            $VENV tests/lib/report_gen.py --latest --fleet 2>/dev/null && \
                info "Report with LLM analysis generated" || true
        fi
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
            tier1_syntax; tier2_unit; tier3_js; tier4_vision; tier4_gameplay; tier5_e2e; tier6_battle; tier7_visual; tier8_lib; tier8b_ros2; tier9_integration; tier10_quality; tier11_smoke; tier13_ux; tier14_defects; tier15_alignment; tier16_layer_isolation; tier17_ui_isolation; tier18_defense; tier19_user_stories; tier20_ui_overlap; tier21_panel_coverage; tier22_combat_effects ;;
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
        15) tier15_alignment ;;
        16) tier16_layer_isolation ;;
        17) tier17_ui_isolation ;;
        18) tier18_defense ;;
        19) tier19_user_stories ;;
        20) tier20_ui_overlap ;;
        21) tier21_panel_coverage ;;
        22) tier22_combat_effects ;;
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
        --alignment) tier15_alignment ;;
        --layers) tier16_layer_isolation ;;
        --ui-isolation) tier17_ui_isolation ;;
        --defense) tier18_defense ;;
        --user-stories) tier19_user_stories ;;
        --overlap) tier20_ui_overlap ;;
        --panels) tier21_panel_coverage ;;
        --combat) tier22_combat_effects ;;
        *) echo "Usage: $0 [all|fast|1-22|--dist|--visual|--gameplay|--battle|--integration|--quality|--smoke|--layout|--ux|--defects|--alignment|--layers|--ui-isolation|--defense|--user-stories|--overlap|--panels]"; exit 1 ;;
    esac
    set -e

    summary
    exit $TOTAL_FAIL
}

main "$@"
