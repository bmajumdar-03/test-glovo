# ==============================================================================
# Caretta ADK - Local Testing Environment
# ==============================================================================

ifneq (,$(wildcard .env))
    include .env
    export
endif

ifeq ($(OS),Windows_NT)
    SYS_PYTHON = python
    VENV_BIN = venv/Scripts
    PYTHON = $(VENV_BIN)/python.exe
    PIP = $(VENV_BIN)/pip.exe
    RM_VENV = rmdir /s /q venv
    CLEAN_CACHE = $(SYS_PYTHON) -c "import shutil, os; [shutil.rmtree(os.path.join(r, d), ignore_errors=True) for r, dirs, f in os.walk('.') for d in dirs if d == '__pycache__']"
else
    SYS_PYTHON = python3
    VENV_BIN = venv/bin
    PYTHON = $(VENV_BIN)/python
    PIP = $(VENV_BIN)/pip
    RM_VENV = rm -rf venv
    CLEAN_CACHE = find . -type d -name "__pycache__" -exec rm -rf {} +
endif

.PHONY: setup test-pr run-agent clean help

help:
	@echo "💻 LOCAL MODE - Available commands:"
	@echo "  make setup     - Create virtual environment and install dependencies"
	@echo "  make test-pr   - Execute the GitHub PR State-Machine logic locally directly"
	@echo "  make run-agent - Execute the ADK 2.0 AI Agent"
	@echo "  make run-agent-with-prompt - Execute the ADK 2.0 AI Agent with NLP instructions"
	@echo "  make clean     - Delete the virtual environment and caches"

setup:
	@echo "==> Creating virtual environment..."
	$(SYS_PYTHON) -m venv venv
	@echo "==> Upgrading pip..."
	$(PYTHON) -m pip install --upgrade pip
	@echo "==> Installing production dependencies..."
	$(PYTHON) -m pip install -r requirements.txt --extra-index-url https://pypi.org/simple
	@echo "==> Setup complete!"

# Bypasses the AI and just runs your raw Python class for debugging
test-pr:
	@echo "==> 🚀 Testing raw GitHub PR State Machine (No AI)..."
	$(PYTHON) -c "from tools.github_pr_tool import GitHubPRStateMachine; GitHubPRStateMachine().run()"

# The main event: Runs the ADK Framework 
run-agent:
	@echo "==> 🤖 Running ADK 2.0 Agent Interactive CLI..."
	$(VENV_BIN)/adk run architect

run-agent-with-prompt:
	@echo "==> 🤖 Running ADK 2.0 Agent..."
	$(VENV_BIN)/adk run architect "Can you push the updated SQL code and open a PR for me?"

clean:
	@echo "==> Removing virtual environment..."
	-$(RM_VENV)
	@echo "==> Removing Python cache files..."
	-$(CLEAN_CACHE)
	@echo "==> Clean complete!"