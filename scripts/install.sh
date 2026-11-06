#!/usr/bin/env bash
set -euo pipefail

# OS-Migrate Skills & Agents Installer
# Installs skills and agents to the local Claude Code filesystem

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default Claude Code directories
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$CLAUDE_HOME/skills}"
AGENTS_DIR="${CLAUDE_AGENTS_DIR:-$CLAUDE_HOME/agents}"

# Script directory (where install.sh lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Functions
print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  OS-Migrate Skills & Agents Installer${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_info() {
    echo -e "${BLUE}→${NC} $1"
}

check_prerequisites() {
    print_info "Checking prerequisites..."

    # Check if Claude Code is installed (look for common locations)
    if ! command -v claude &> /dev/null && [ ! -d "$CLAUDE_HOME" ]; then
        print_error "Claude Code does not appear to be installed"
        print_info "Please install Claude Code first: https://claude.ai/code"
        exit 1
    fi

    print_success "Prerequisites check passed"
    echo
}

create_directories() {
    print_info "Creating installation directories..."

    # Create Claude home directory if it doesn't exist
    if [ ! -d "$CLAUDE_HOME" ]; then
        mkdir -p "$CLAUDE_HOME"
        print_success "Created $CLAUDE_HOME"
    fi

    # Create skills directory
    if [ ! -d "$SKILLS_DIR" ]; then
        mkdir -p "$SKILLS_DIR"
        print_success "Created $SKILLS_DIR"
    else
        print_info "Skills directory already exists: $SKILLS_DIR"
    fi

    # Create agents directory
    if [ ! -d "$AGENTS_DIR" ]; then
        mkdir -p "$AGENTS_DIR"
        print_success "Created $AGENTS_DIR"
    else
        print_info "Agents directory already exists: $AGENTS_DIR"
    fi

    echo
}

install_skills() {
    print_info "Installing skills..."

    local skills_installed=0

    if [ -d "$REPO_ROOT/skills" ]; then
        for skill_dir in "$REPO_ROOT/skills"/*; do
            if [ -d "$skill_dir" ]; then
                local skill_name
                skill_name=$(basename "$skill_dir")
                local target_dir="$SKILLS_DIR/$skill_name"

                # Check if skill already exists
                if [ -d "$target_dir" ]; then
                    print_warning "Skill '$skill_name' already exists, overwriting..."
                    rm -rf "$target_dir"
                fi

                # Copy skill directory
                cp -r "$skill_dir" "$target_dir"
                print_success "Installed skill: $skill_name"
                ((skills_installed++))
            fi
        done
    else
        print_warning "No skills directory found in repository"
    fi

    if [ $skills_installed -eq 0 ]; then
        print_warning "No skills were installed"
    else
        print_success "Installed $skills_installed skill(s)"
    fi

    echo
}

install_agents() {
    print_info "Installing agents..."

    local agents_installed=0

    if [ -d "$REPO_ROOT/agents" ]; then
        for agent_dir in "$REPO_ROOT/agents"/*; do
            if [ -d "$agent_dir" ]; then
                local agent_name
                agent_name=$(basename "$agent_dir")
                local target_dir="$AGENTS_DIR/$agent_name"

                # Check if agent already exists
                if [ -d "$target_dir" ]; then
                    print_warning "Agent '$agent_name' already exists, overwriting..."
                    rm -rf "$target_dir"
                fi

                # Copy agent directory
                cp -r "$agent_dir" "$target_dir"
                print_success "Installed agent: $agent_name"
                ((agents_installed++))
            fi
        done
    else
        print_warning "No agents directory found in repository"
    fi

    if [ $agents_installed -eq 0 ]; then
        print_warning "No agents were installed"
    else
        print_success "Installed $agents_installed agent(s)"
    fi

    echo
}

create_symlinks() {
    print_info "Would you like to create symlinks instead of copying? (y/N)"
    read -r response

    if [[ "$response" =~ ^[Yy]$ ]]; then
        print_info "Creating symlinks..."

        # Remove previously copied skills and create symlinks
        if [ -d "$REPO_ROOT/skills" ]; then
            for skill_dir in "$REPO_ROOT/skills"/*; do
                if [ -d "$skill_dir" ]; then
                    local skill_name
                    skill_name=$(basename "$skill_dir")
                    local target_dir="$SKILLS_DIR/$skill_name"

                    rm -rf "$target_dir"
                    ln -s "$skill_dir" "$target_dir"
                    print_success "Linked skill: $skill_name"
                fi
            done
        fi

        # Remove previously copied agents and create symlinks
        if [ -d "$REPO_ROOT/agents" ]; then
            for agent_dir in "$REPO_ROOT/agents"/*; do
                if [ -d "$agent_dir" ]; then
                    local agent_name
                    agent_name=$(basename "$agent_dir")
                    local target_dir="$AGENTS_DIR/$agent_name"

                    rm -rf "$target_dir"
                    ln -s "$agent_dir" "$target_dir"
                    print_success "Linked agent: $agent_name"
                fi
            done
        fi

        print_success "Symlinks created (changes to repo will reflect immediately)"
        echo
    fi
}

print_summary() {
    echo -e "${GREEN}================================================${NC}"
    echo -e "${GREEN}  Installation Complete!${NC}"
    echo -e "${GREEN}================================================${NC}"
    echo
    echo "Skills installed to: $SKILLS_DIR"
    echo "Agents installed to: $AGENTS_DIR"
    echo
    echo "Available skills:"
    if [ -d "$SKILLS_DIR" ]; then
        for skill in "$SKILLS_DIR"/*; do
            if [ -d "$skill" ]; then
                echo "  - $(basename "$skill")"
            fi
        done
    fi
    echo

    if [ -d "$AGENTS_DIR" ] && [ "$(ls -A "$AGENTS_DIR" 2>/dev/null)" ]; then
        echo "Available agents:"
        for agent in "$AGENTS_DIR"/*; do
            if [ -d "$agent" ]; then
                echo "  - $(basename "$agent")"
            fi
        done
        echo
    fi

    echo "To use skills in Claude Code, start a conversation and use:"
    echo "  /<skill-name> [args]"
    echo
    echo "For example:"
    echo "  /vmw-release 2.3.0 --changelog \"New feature\" \"Bug fix\""
    echo
}

uninstall() {
    print_info "Uninstalling OS-Migrate skills and agents..."

    # Remove skills
    if [ -d "$REPO_ROOT/skills" ]; then
        for skill_dir in "$REPO_ROOT/skills"/*; do
            if [ -d "$skill_dir" ]; then
                local skill_name
                skill_name=$(basename "$skill_dir")
                local target_dir="$SKILLS_DIR/$skill_name"

                if [ -d "$target_dir" ] || [ -L "$target_dir" ]; then
                    rm -rf "$target_dir"
                    print_success "Removed skill: $skill_name"
                fi
            fi
        done
    fi

    # Remove agents
    if [ -d "$REPO_ROOT/agents" ]; then
        for agent_dir in "$REPO_ROOT/agents"/*; do
            if [ -d "$agent_dir" ]; then
                local agent_name
                agent_name=$(basename "$agent_dir")
                local target_dir="$AGENTS_DIR/$agent_name"

                if [ -d "$target_dir" ] || [ -L "$target_dir" ]; then
                    rm -rf "$target_dir"
                    print_success "Removed agent: $agent_name"
                fi
            fi
        done
    fi

    print_success "Uninstall complete"
    echo
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo
    echo "Options:"
    echo "  --help, -h          Show this help message"
    echo "  --uninstall         Uninstall skills and agents"
    echo "  --symlink           Create symlinks instead of copying (development mode)"
    echo "  --skills-dir DIR    Override skills installation directory"
    echo "  --agents-dir DIR    Override agents installation directory"
    echo
    echo "Environment Variables:"
    echo "  CLAUDE_HOME         Claude Code home directory (default: ~/.claude)"
    echo "  CLAUDE_SKILLS_DIR   Skills installation directory (default: \$CLAUDE_HOME/skills)"
    echo "  CLAUDE_AGENTS_DIR   Agents installation directory (default: \$CLAUDE_HOME/agents)"
    echo
}

# Main execution
main() {
    local use_symlinks=false
    local do_uninstall=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                show_usage
                exit 0
                ;;
            --uninstall)
                do_uninstall=true
                shift
                ;;
            --symlink)
                use_symlinks=true
                shift
                ;;
            --skills-dir)
                SKILLS_DIR="$2"
                shift 2
                ;;
            --agents-dir)
                AGENTS_DIR="$2"
                shift 2
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    print_header

    if [ "$do_uninstall" = true ]; then
        uninstall
        exit 0
    fi

    check_prerequisites
    create_directories
    install_skills
    install_agents

    if [ "$use_symlinks" = true ]; then
        print_info "Using symlink mode (development)..."
        create_symlinks
    fi

    print_summary
}

# Run main function
main "$@"
