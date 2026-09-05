#!/bin/bash
# LocalSetup - Path resolution (repo-local by default)
# When deployed, framework is at ls/framework; set LOCALSETUP_PROJECT_ROOT to client repo root for repo-local user data.

get_user_home() {
    if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
        echo "$HOME"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ -n "${WINDIR:-}" ]]; then
        [[ -n "${USERPROFILE:-}" ]] && echo "$USERPROFILE" || echo "${HOME:-~}"
    else
        echo "${HOME:-$HOME}"
    fi
}

# User data dir: prefer repo-local (LOCALSETUP_PROJECT_DATA or PROJECT_ROOT/.localsetup-project)
get_user_data_dir() {
    if [[ -n "${LOCALSETUP_PROJECT_DATA:-}" ]] && [[ -d "${LOCALSETUP_PROJECT_DATA}" ]]; then
        echo "${LOCALSETUP_PROJECT_DATA}"
        return 0
    fi
    if [[ -n "${LOCALSETUP_PROJECT_ROOT:-}" ]] && [[ -d "${LOCALSETUP_PROJECT_ROOT}/.localsetup-project" ]]; then
        echo "${LOCALSETUP_PROJECT_ROOT}/.localsetup-project"
        return 0
    fi
    if [[ -n "${LOCALSETUP_PROJECT_ROOT:-}" ]]; then
        echo "${LOCALSETUP_PROJECT_ROOT}/.localsetup-project"
        return 0
    fi
    echo "$(get_user_home)/.localsetup"
}

# Engine dir = directory containing lib/, tools/, etc. (e.g. ls/framework when deployed)
get_engine_dir() {
    if [[ -n "${LOCALSETUP_FRAMEWORK_DIR:-}" ]] && [[ -d "${LOCALSETUP_FRAMEWORK_DIR}" ]]; then
        echo "${LOCALSETUP_FRAMEWORK_DIR}"
        return 0
    fi
    echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
}

# Project root = client repo root when deployed (parent of ls)
get_project_root() {
    if [[ -n "${LOCALSETUP_PROJECT_ROOT:-}" ]] && [[ -d "${LOCALSETUP_PROJECT_ROOT}" ]]; then
        echo "${LOCALSETUP_PROJECT_ROOT}"
        return 0
    fi
    local engine_dir=$(get_engine_dir)
    local parent="$(cd "$engine_dir/.." && pwd)"
    # When deployed, engine is at ls/framework; client root is parent of ls
    if [[ "$(basename "$parent")" == "ls" ]]; then
        echo "$(cd "$parent/.." && pwd)"
    else
        echo "$parent"
    fi
}

ensure_user_data_dir() {
    local user_data_dir=$(get_user_data_dir)
    mkdir -p "$user_data_dir"/{context/{system,rules,research},scripts/{temp,dry-run,archive},logs,config}
    echo "$user_data_dir"
}

get_path_separator() {
    [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] && echo "\\" || echo "/"
}

export -f get_user_home get_user_data_dir get_engine_dir get_project_root ensure_user_data_dir get_path_separator
