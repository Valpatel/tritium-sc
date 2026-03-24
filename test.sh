#!/bin/bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
VENV="$SCRIPT_DIR/.venv/bin/python3"
TOTAL_PASS=0; TOTAL_FAIL=0; TOTAL_SKIP=0
START_TIME=$(date +%s)

# CPU-friendly: run at lower priority so other processes aren't starved.
# nice -n 10 lowers scheduling priority; ionice -c 2 -n 6 lowers I/O priority.
# This makes tests take ~10-20% longer but keeps the system responsive.
NICE_PREFIX="nice -n 10"
if command -v ionice &>/dev/null; then
    NICE_PREFIX="nice -n 10 ionice -c 2 -n 6"
fi

# Limit parallel operations to half of CPU cores (min 2)
MAX_JOBS=$(( $(nproc 2>/dev/null || echo 4) / 2 ))
[ "$MAX_JOBS" -lt 2 ] && MAX_JOBS=2
export PYTEST_XDIST_AUTO_NUM_WORKERS="$MAX_JOBS"

# --- Gentle mode (--gentle flag) ---
# Gentle mode: lower priority, stricter fail-fast, tighter timeouts
GENTLE=false
GENTLE_PYTEST_ARGS=""
# Default pytest resource guards for non-gentle mode
PYTEST_RESOURCE_ARGS="--maxfail=20"

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*"; TOTAL_PASS=$((TOTAL_PASS + 1)); }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
header() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

# Gentle mode: pause between tiers/sub-tiers to let the system breathe
gentle_pause() {
    if $GENTLE; then
        info "Gentle mode: pausing 2s..."
        sleep 2
    else
        sleep 1
    fi
}

# Resource monitoring — prevent OOM kills and swap exhaustion
resource_check() {
    local context="${1:-}"
    if [ ! -f /proc/meminfo ]; then return; fi
    local mem_available swap_used swap_total load
    mem_available=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    swap_used=$(awk '/SwapTotal/{t=$2} /SwapFree/{f=$2} END{print int((t-f)/1024)}' /proc/meminfo)
    swap_total=$(awk '/SwapTotal/{print int($2/1024)}' /proc/meminfo)
    load=$(awk '{print $1}' /proc/loadavg)

    if [ -n "$context" ]; then
        info "Resources [$context]: ${mem_available}MB avail, swap ${swap_used}/${swap_total}MB, load $load"
    fi

    # Warn if memory is critically low
    if [ "$mem_available" -lt 4096 ]; then
        warn "LOW MEMORY: Only ${mem_available}MB available — test performance may suffer"
    fi

    # Abort if swap is >90% used and memory is critically low
    if [ "$swap_total" -gt 0 ]; then
        local swap_pct=$(( swap_used * 100 / swap_total ))
        if [ "$swap_pct" -gt 90 ] && [ "$mem_available" -lt 2048 ]; then
            warn "CRITICAL: Swap ${swap_pct}% used, only ${mem_available}MB RAM free"
            warn "Consider closing other applications before continuing"
        fi
    fi
}

# Tier functions
tier1_syntax() {
    header "Tier 1: Syntax Check"
    local py_count js_count err=0
    local py_err_file js_err_file
    py_err_file=$(mktemp)
    js_err_file=$(mktemp)

    # Python: batch compile with limited parallelism
    py_count=$(find "$SCRIPT_DIR/src/" -name '*.py' -not -path '*/__pycache__/*' -not -name '*.pyc' | wc -l)
    find "$SCRIPT_DIR/src/" -name '*.py' -not -path '*/__pycache__/*' -not -name '*.pyc' | sort | \
        xargs -P "$MAX_JOBS" -I{} sh -c 'nice -n 10 python3 -m py_compile "$1" 2>/dev/null || echo "$1" >> '"$py_err_file" _ {}

    # JS: batch check with limited parallelism
    js_count=$(find "$SCRIPT_DIR/src/frontend/js/" -name '*.js' -not -path '*/node_modules/*' | wc -l)
    find "$SCRIPT_DIR/src/frontend/js/" -name '*.js' -not -path '*/node_modules/*' | sort | \
        xargs -P "$MAX_JOBS" -I{} sh -c 'nice -n 10 node --check "$1" 2>/dev/null || echo "$1" >> '"$js_err_file" _ {}

    # Report errors
    if [ -s "$py_err_file" ]; then
        while IFS= read -r f; do
            fail "py_compile: ${f#$SCRIPT_DIR/}"
            err=$((err + 1))
        done < "$py_err_file"
    fi
    if [ -s "$js_err_file" ]; then
        while IFS= read -r f; do
            fail "node --check: ${f#$SCRIPT_DIR/}"
            err=$((err + 1))
        done < "$js_err_file"
    fi

    rm -f "$py_err_file" "$js_err_file"

    local ok=$(( py_count + js_count - err ))
    if [ $err -eq 0 ]; then
        pass "Syntax: $ok files OK ($py_count Python, $js_count JS)"
    else
        fail "Syntax: $err errors in $((py_count + js_count)) files"
    fi
}

tier2_unit() {
    header "Tier 2: Unit Tests (pytest)"
    resource_check "before unit tests"

    # Split into 3 sequential sub-tiers to reduce peak memory and allow
    # the system to reclaim resources between chunks:
    #   2a: engine/simulation (heaviest: ~3100 tests, ~270s)
    #   2b: engine/* except simulation (~4900 tests)
    #   2c: amy (~830 tests)
    local sim_ok=0 engine_ok=0 amy_ok=0

    # --- Sub-tier 2a: simulation (heaviest) ---
    info "Tier 2a: engine/simulation unit tests (~3100 tests)..."
    if $NICE_PREFIX $VENV -m pytest \
        "$SCRIPT_DIR/tests/engine/simulation/" \
        -m unit --tb=short -q $PYTEST_RESOURCE_ARGS $GENTLE_PYTEST_ARGS 2>&1; then
        sim_ok=1
    fi
    gentle_pause
    resource_check "after simulation tests"

    # --- Sub-tier 2b: remaining engine tests ---
    info "Tier 2b: engine (non-simulation) unit tests (~4900 tests)..."
    if $NICE_PREFIX $VENV -m pytest \
        "$SCRIPT_DIR/tests/engine/actions/" \
        "$SCRIPT_DIR/tests/engine/addons/" \
        "$SCRIPT_DIR/tests/engine/api/" \
        "$SCRIPT_DIR/tests/engine/audio/" \
        "$SCRIPT_DIR/tests/engine/backup/" \
        "$SCRIPT_DIR/tests/engine/comms/" \
        "$SCRIPT_DIR/tests/engine/inference/" \
        "$SCRIPT_DIR/tests/engine/intelligence/" \
        "$SCRIPT_DIR/tests/engine/layers/" \
        "$SCRIPT_DIR/tests/engine/nodes/" \
        "$SCRIPT_DIR/tests/engine/perception/" \
        "$SCRIPT_DIR/tests/engine/plugins/" \
        "$SCRIPT_DIR/tests/engine/scenarios/" \
        "$SCRIPT_DIR/tests/engine/synthetic/" \
        "$SCRIPT_DIR/tests/engine/tactical/" \
        "$SCRIPT_DIR/tests/engine/testing/" \
        "$SCRIPT_DIR/tests/engine/units/" \
        -m unit --tb=short -q $PYTEST_RESOURCE_ARGS $GENTLE_PYTEST_ARGS 2>&1; then
        engine_ok=1
    fi
    gentle_pause
    resource_check "after engine tests"

    # --- Sub-tier 2c: amy ---
    info "Tier 2c: amy unit tests (~830 tests)..."
    if $NICE_PREFIX $VENV -m pytest \
        "$SCRIPT_DIR/tests/amy/" \
        -m unit --tb=short -q $PYTEST_RESOURCE_ARGS $GENTLE_PYTEST_ARGS 2>&1; then
        amy_ok=1
    fi

    # Report results
    if [ $sim_ok -eq 1 ] && [ $engine_ok -eq 1 ] && [ $amy_ok -eq 1 ]; then
        pass "Unit tests (simulation + engine + amy)"
    else
        [ $sim_ok -eq 0 ] && fail "Simulation unit tests"
        [ $engine_ok -eq 0 ] && fail "Engine unit tests"
        [ $amy_ok -eq 0 ] && fail "Amy unit tests"
    fi

    resource_check "after all unit tests"
}

tier3_js() {
    header "Tier 3: JS Tests"
    resource_check "before JS tests"
    local js_err=0
    local batch_runner="$SCRIPT_DIR/tests/js/run-all.js"

    if [ -f "$batch_runner" ]; then
        # Parallel batch runner: discovers all test_*.js, runs with controlled
        # concurrency (~4x faster than sequential).
        local batch_output
        batch_output=$($NICE_PREFIX node "$batch_runner" --concurrency "$MAX_JOBS" 2>&1) || true

        # Parse BATCH_PASS / BATCH_FAIL / BATCH_SKIP lines into test.sh format
        while IFS= read -r line; do
            case "$line" in
                BATCH_PASS:*)
                    pass "JS ${line#BATCH_PASS: }" ;;
                BATCH_FAIL:*)
                    fail "JS ${line#BATCH_FAIL: }"
                    js_err=$((js_err + 1)) ;;
                BATCH_SKIP:*)
                    warn "JS test not found: ${line#BATCH_SKIP: }"
                    TOTAL_SKIP=$((TOTAL_SKIP + 1)) ;;
                BATCH_SUMMARY:*)
                    info "${line#BATCH_SUMMARY: }" ;;
            esac
        done <<< "$batch_output"
    else
        # Fallback: sequential execution (no batch runner available)
        for jstest in "$SCRIPT_DIR"/tests/js/test_*.js; do
            local name
            name=$(basename "$jstest")
            if $NICE_PREFIX node "$jstest"; then
                pass "JS $name"
            else
                fail "JS $name"
                js_err=$((js_err + 1))
            fi
        done
    fi
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
    if $NICE_PREFIX $VENV -m pytest "$SCRIPT_DIR/tests/lib/" -m unit --tb=short -q 2>&1; then
        pass "Test infrastructure tests"
    else
        fail "Test infrastructure tests"
    fi
}

tier8b_ros2() {
    header "Tier 8b: ROS2 Robot Tests"
    if [ -d "$SCRIPT_DIR/examples/ros2-robot/tests" ]; then
        if $NICE_PREFIX python3 -m pytest "$SCRIPT_DIR/examples/ros2-robot/tests/" --tb=short -q 2>&1; then
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

tier_docs() {
    header "Doc Screenshots: Generate README hero images"
    if $VENV -m pytest "$SCRIPT_DIR/tests/visual/test_doc_screenshots.py" -v -s --tb=short 2>&1; then
        pass "Doc screenshots generated"
        info "Screenshots saved to docs/screenshots/"
        info "Gallery: tests/.test-results/doc-screenshots/gallery.html"
    else
        fail "Doc screenshot generation"
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
    # Pre-parse flags that modify behavior before the mode switch
    local args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --gentle)
                GENTLE=true
                NICE_PREFIX="nice -n 15"
                if command -v ionice &>/dev/null; then
                    NICE_PREFIX="nice -n 15 ionice -c 3"
                fi
                MAX_JOBS=2
                export PYTEST_XDIST_AUTO_NUM_WORKERS="$MAX_JOBS"
                # Gentle: tighter timeout, lower maxfail, stop-on-first for early bail
                GENTLE_PYTEST_ARGS="--timeout=15"
                PYTEST_RESOURCE_ARGS="--maxfail=5"
                info "Gentle mode: nice -n 15, ionice idle, timeout=15s, maxfail=5"
                shift
                ;;
            --resource-report)
                resource_check "system status"
                echo "CPU cores: $(nproc 2>/dev/null || echo unknown)"
                echo "MAX_JOBS: $MAX_JOBS"
                echo "NICE_PREFIX: $NICE_PREFIX"
                echo "GENTLE: $GENTLE"
                exit 0
                ;;
            *)
                args+=("$1")
                shift
                ;;
        esac
    done
    set -- "${args[@]+"${args[@]}"}"

    header "TRITIUM-SC Test Suite"
    resource_check "startup"

    set +e
    case "${1:-}" in
        ""|fast)
            tier1_syntax; gentle_pause; tier2_unit; gentle_pause; tier3_js; gentle_pause; tier8_lib; gentle_pause; tier8b_ros2 ;;
        all)
            tier1_syntax; gentle_pause; tier2_unit; gentle_pause; tier3_js; gentle_pause; tier4_vision; gentle_pause; tier4_gameplay; gentle_pause; tier5_e2e; gentle_pause; tier6_battle; gentle_pause; tier7_visual; gentle_pause; tier8_lib; gentle_pause; tier8b_ros2; gentle_pause; tier9_integration; gentle_pause; tier10_quality; gentle_pause; tier11_smoke; gentle_pause; tier13_ux; gentle_pause; tier14_defects; gentle_pause; tier15_alignment; gentle_pause; tier16_layer_isolation; gentle_pause; tier17_ui_isolation; gentle_pause; tier18_defense; gentle_pause; tier19_user_stories; gentle_pause; tier20_ui_overlap; gentle_pause; tier21_panel_coverage; gentle_pause; tier22_combat_effects ;;
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
        docs|--docs) tier_docs ;;
        *) echo "Usage: $0 [--gentle] [--resource-report] [all|fast|1-22|docs|--dist|--visual|--gameplay|--battle|--integration|--quality|--smoke|--layout|--ux|--defects|--alignment|--layers|--ui-isolation|--defense|--user-stories|--overlap|--panels|--docs]"
           echo "  --gentle          Lower priority, tighter timeouts (15s), maxfail=5"
           echo "  --resource-report Show memory/CPU/swap status and exit"
           exit 1 ;;
    esac
    set -e

    summary
    exit $TOTAL_FAIL
}

main "$@"
