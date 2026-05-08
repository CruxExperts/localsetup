#!/bin/bash
# Localsetup v3 - JSON formatter

format_json() {
    local json_input="$1"
    if command -v jq >/dev/null 2>&1; then
        echo "$json_input" | jq '.' 2>/dev/null && return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        echo "$json_input" | python3 -m json.tool 2>/dev/null && return 0
    fi
    echo "$json_input" | sed 's/,/,\n/g' | sed 's/{/{\n/g' | sed 's/}/\n}/g' | head -1000
    return 0
}

format_json_to_file() {
    local json_input="$1"
    local output_file="$2"
    format_json "$json_input" > "$output_file"
}

export -f format_json format_json_to_file
