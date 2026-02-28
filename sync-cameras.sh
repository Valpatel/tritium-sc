#!/bin/bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
#
# Reolink NVR Recording Sync Script
# Downloads recordings from NVR via HTTP API
# - Syncs newest recordings first
# - Skips already downloaded files
# - Organizes by channel/YYYY/MM/DD
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$SCRIPT_DIR"
LOG_FILE="$SCRIPT_DIR/sync.log"
STATE_FILE="$SCRIPT_DIR/.sync_state"
PID_FILE="$SCRIPT_DIR/.sync.pid"

# Load environment variables
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "Error: .env file not found" >&2
    exit 1
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT

# Check if another sync is running
check_running() {
    if [[ -f "$PID_FILE" ]]; then
        local old_pid
        old_pid=$(cat "$PID_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            log "Another sync is running (PID $old_pid). Exiting."
            exit 0
        fi
    fi
    echo $$ > "$PID_FILE"
}

# Get authentication token
get_token() {
    local result
    result=$(curl -s -k --max-time 30 -X POST \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=Login" \
        -H "Content-Type: application/json" \
        -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"$NVR_USER\",\"password\":\"$NVR_PASS\"}}}]")

    echo "$result" | grep -o '"name" *: *"[^"]*"' | head -1 | cut -d'"' -f4
}

# Get list of online channels
get_channels() {
    local token="$1"
    curl -s -k --max-time 30 -X POST \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=GetChannelStatus&token=$token" \
        -H "Content-Type: application/json" \
        -d '[{"cmd":"GetChannelStatus","action":0,"param":{}}]' | \
        grep -o '"channel" *: *[0-9]*' | grep -o '[0-9]*'
}

# Get recording days for a channel/month (returns bitmask)
get_recording_days() {
    local token="$1" channel="$2" year="$3" month="$4"

    curl -s -k --max-time 30 -X POST \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=Search&token=$token" \
        -H "Content-Type: application/json" \
        -d "[{\"cmd\":\"Search\",\"action\":1,\"param\":{\"Search\":{\"channel\":$channel,\"onlyStatus\":1,\"streamType\":\"main\",\"StartTime\":{\"year\":$year,\"mon\":$month,\"day\":1,\"hour\":0,\"min\":0,\"sec\":0},\"EndTime\":{\"year\":$year,\"mon\":$month,\"day\":31,\"hour\":23,\"min\":59,\"sec\":59}}}}]" | \
        grep -o '"table" *: *"[^"]*"' | cut -d'"' -f4
}

# Get recordings for a specific day
get_day_recordings() {
    local token="$1" channel="$2" year="$3" month="$4" day="$5"

    curl -s -k --max-time 60 -X POST \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=Search&token=$token" \
        -H "Content-Type: application/json" \
        -d "[{\"cmd\":\"Search\",\"action\":0,\"param\":{\"Search\":{\"channel\":$channel,\"onlyStatus\":0,\"streamType\":\"main\",\"StartTime\":{\"year\":$year,\"mon\":$month,\"day\":$day,\"hour\":0,\"min\":0,\"sec\":0},\"EndTime\":{\"year\":$year,\"mon\":$month,\"day\":$day,\"hour\":23,\"min\":59,\"sec\":59}}}}]"
}

# Prepare download and get filename
prepare_download() {
    local token="$1" channel="$2" start_json="$3" end_json="$4"

    local start_year start_mon start_day start_hour start_min start_sec
    local end_year end_mon end_day end_hour end_min end_sec

    read start_year start_mon start_day start_hour start_min start_sec <<< "$start_json"
    read end_year end_mon end_day end_hour end_min end_sec <<< "$end_json"

    curl -s -k --max-time 30 -X POST \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=NvrDownload&token=$token" \
        -H "Content-Type: application/json" \
        -d "[{\"cmd\":\"NvrDownload\",\"action\":0,\"param\":{\"NvrDownload\":{\"channel\":$channel,\"iLogicChannel\":0,\"streamType\":\"main\",\"StartTime\":{\"year\":$start_year,\"mon\":$start_mon,\"day\":$start_day,\"hour\":$start_hour,\"min\":$start_min,\"sec\":$start_sec},\"EndTime\":{\"year\":$end_year,\"mon\":$end_mon,\"day\":$end_day,\"hour\":$end_hour,\"min\":$end_min,\"sec\":$end_sec}}}}]"
}

# Download a file
download_file() {
    local token="$1" filename="$2" output_path="$3" expected_size="$4"

    # Skip if file exists and is correct size
    if [[ -f "$output_path" ]]; then
        local existing_size
        existing_size=$(stat -c%s "$output_path" 2>/dev/null || echo 0)
        if [[ "$existing_size" -eq "$expected_size" ]]; then
            log "  Skipping (already exists): $(basename "$output_path")"
            return 0
        fi
    fi

    mkdir -p "$(dirname "$output_path")"

    log "  Downloading: $(basename "$output_path") ($(numfmt --to=iec-i --suffix=B "$expected_size"))"

    local http_code
    http_code=$(curl -s -k --max-time 600 \
        "https://$NVR_HOST:$NVR_PORT/cgi-bin/api.cgi?cmd=Download&source=$filename&output=$filename&token=$token" \
        -o "$output_path" -w "%{http_code}")

    if [[ "$http_code" == "200" ]]; then
        local actual_size
        actual_size=$(stat -c%s "$output_path" 2>/dev/null || echo 0)
        if [[ "$actual_size" -eq "$expected_size" ]]; then
            return 0
        else
            log "  WARNING: Size mismatch (expected $expected_size, got $actual_size)"
            return 1
        fi
    else
        log "  ERROR: HTTP $http_code"
        rm -f "$output_path"
        return 1
    fi
}

# Process a single day's recordings for a channel
process_day() {
    local token="$1" channel="$2" year="$3" month="$4" day="$5"

    local day_dir
    day_dir=$(printf "%s/channel_%02d/%04d/%02d/%02d" "$LOCAL_DIR" "$channel" "$year" "$month" "$day")

    log "Processing channel $channel: $year-$(printf '%02d' $month)-$(printf '%02d' $day)"

    local recordings
    recordings=$(get_day_recordings "$token" "$channel" "$year" "$month" "$day")

    # Parse recordings JSON and process each
    echo "$recordings" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data[0].get('code') == 0:
    files = data[0].get('value', {}).get('SearchResult', {}).get('File', [])
    for f in files:
        st = f['StartTime']
        et = f['EndTime']
        size = f.get('size', 0)
        print(f\"{st['year']} {st['mon']} {st['day']} {st['hour']} {st['min']} {st['sec']} {et['year']} {et['mon']} {et['day']} {et['hour']} {et['min']} {et['sec']} {size}\")
" 2>/dev/null | while read -r sy sm sd sh smin ss ey em ed eh emin es size; do
        # Get filename via NvrDownload
        local prep_result filename filesize
        prep_result=$(prepare_download "$token" "$channel" "$sy $sm $sd $sh $smin $ss" "$ey $em $ed $eh $emin $es")
        filename=$(echo "$prep_result" | grep -o '"fileName" *: *"[^"]*"' | cut -d'"' -f4)
        filesize=$(echo "$prep_result" | grep -o '"fileSize" *: *"[^"]*"' | cut -d'"' -f4)

        if [[ -n "$filename" && -n "$filesize" ]]; then
            local output_path="$day_dir/$filename"
            download_file "$token" "$filename" "$output_path" "$filesize"
        fi
    done
}

# Main sync logic
main() {
    log "=== Starting NVR sync from $NVR_HOST ==="

    check_running

    # Get token
    log "Authenticating..."
    local token
    token=$(get_token)
    if [[ -z "$token" ]]; then
        log "ERROR: Failed to authenticate"
        exit 1
    fi
    log "Authenticated successfully"

    # Get current date for working backwards
    local current_year current_month
    current_year=$(date +%Y)
    current_month=$(date +%-m)

    # Get all channels
    local channels
    mapfile -t channels < <(get_channels "$token")
    log "Found ${#channels[@]} channels"

    # Process each channel, newest dates first
    for channel in "${channels[@]}"; do
        log "Scanning channel $channel..."

        # Work backwards through months (current year first, then previous)
        for year in "$current_year" "$((current_year - 1))"; do
            local start_month=12
            if [[ "$year" == "$current_year" ]]; then
                start_month=$current_month
            fi

            for ((month=start_month; month>=1; month--)); do
                # Check if this month has recordings
                local day_table
                day_table=$(get_recording_days "$token" "$channel" "$year" "$month")

                if [[ -z "$day_table" || "$day_table" == "0000000000000000000000000000000" ]]; then
                    continue
                fi

                # Parse day table (bit per day, 1-31)
                for ((day=31; day>=1; day--)); do
                    local idx=$((day - 1))
                    local has_recording="${day_table:$idx:1}"

                    if [[ "$has_recording" == "1" ]]; then
                        # Refresh token periodically (every 30 minutes)
                        if (( SECONDS > 1800 )); then
                            log "Refreshing token..."
                            token=$(get_token)
                            SECONDS=0
                        fi

                        process_day "$token" "$channel" "$year" "$month" "$day"
                    fi
                done
            done
        done
    done

    log "=== Sync completed ==="
}

main "$@"
