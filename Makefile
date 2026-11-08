.PHONY: help check-env check-app up down status full-up \
	mcp-up mcp-down mcp-status app-up app-down app-status \
	optional-meraki-up optional-meraki-down optional-meraki-status

REPO_ROOT := $(CURDIR)
PLATFORMS_DIR ?= $(REPO_ROOT)/platforms-mcp-servers-oss
MERAKI_MAGIC_DIR ?= $(REPO_ROOT)/meraki-magic-mcp-community
LIBRECHAT_DIR ?= $(REPO_ROOT)/ai-agent-librechat-oss
LOG_DIR ?= $(REPO_ROOT)/logs
LAB_ENV ?= $(HOME)/lab.env
PYTHON_BIN ?= $(REPO_ROOT)/.venv/bin/python
DETACHED_LAUNCHER ?= $(REPO_ROOT)/scripts/launch_detached.py
REMOTE_MCP_CHECKER ?= $(REPO_ROOT)/scripts/check_remote_mcp.py
LLM_STATUS_CHECKER ?= $(REPO_ROOT)/scripts/check_llm_status.py
LAB_ENV_VALIDATOR ?= $(REPO_ROOT)/scripts/validate_lab_env.py
MCP_HOST ?= 0.0.0.0
MCP_CATALYST_PORT ?= 8000
MCP_MERAKI_PORT ?= 8001
MCP_MERAKI_MAGIC_PORT ?= 8002
MCP_ENABLE_TLS ?= true
MCP_SSL_CERTFILE ?= $(REPO_ROOT)/certs/mcp-selfsigned.crt
MCP_SSL_KEYFILE ?= $(REPO_ROOT)/certs/mcp-selfsigned.key
MCP_STARTUP_TIMEOUT ?= 90
MCP_CATALYST_PID ?= $(LOG_DIR)/catalyst_center_mcp.pid
MCP_MERAKI_MAGIC_PID ?= $(LOG_DIR)/meraki_magic_mcp.pid
MCP_MERAKI_PID ?= $(LOG_DIR)/meraki_mcp.pid
LIBRECHAT_HTTPS_PORT ?= 3080
LIBRECHAT_BACKEND_PORT ?= 3081
LIBRECHAT_STARTUP_TIMEOUT ?= 120
LIBRECHAT_LAUNCHER_LOG ?= $(LIBRECHAT_DIR)/logs/librechat_launcher.log
LIBRECHAT_LAUNCHER_PID ?= $(LIBRECHAT_DIR)/.launcher.pid

help:
	@echo "MCP AI Agent Lab targets:"
	@echo "  make up                       Start MCP servers and LibreChat"
	@echo "  make down                     Stop MCP servers and LibreChat"
	@echo "  make status                   Check stack, remote MCPs, and LLM config"
	@echo "  make mcp-up|mcp-down|mcp-status"
	@echo "                                Manage only the default MCP server pair"
	@echo "  make app-up|app-down|app-status"
	@echo "                                Manage only LibreChat (nginx + backend)"
	@echo "  make optional-meraki-up       Start the optional bundled Meraki MCP"
	@echo "  make optional-meraki-down     Stop the optional bundled Meraki MCP"
	@echo "  make optional-meraki-status   Show the optional bundled Meraki MCP status"
	@echo ""
	@echo "Defaults:"
	@echo "  Catalyst Center:  https://localhost:$(MCP_CATALYST_PORT)/mcp"
	@echo "  Meraki Magic:     https://localhost:$(MCP_MERAKI_MAGIC_PORT)/mcp"
	@echo "  LibreChat:        https://localhost:$(LIBRECHAT_HTTPS_PORT)"
	@echo "  Environment:      $(LAB_ENV)"
	@echo "  MongoDB:          dependency managed by the host; not stopped by make down"

check-env:
	@test -f "$(LAB_ENV)" || { \
	  echo "ERROR: Required environment file not found: $(LAB_ENV)"; \
	  echo "Copy .env.example to $(LAB_ENV) and add the instructor-provided values."; \
	  exit 1; \
	}
	@test -x "$(PYTHON_BIN)" || { echo "ERROR: Python environment not found: $(PYTHON_BIN)"; exit 1; }
	@test -f "$(LAB_ENV_VALIDATOR)" || { echo "ERROR: Lab environment validator not found."; exit 1; }
	@LAB_ENV="$(LAB_ENV)" "$(PYTHON_BIN)" "$(LAB_ENV_VALIDATOR)"
	@test -f "$(DETACHED_LAUNCHER)" || { echo "ERROR: Detached launcher not found: $(DETACHED_LAUNCHER)"; exit 1; }
	@test -f "$(PLATFORMS_DIR)/catalyst_center_remote.py" || { echo "ERROR: Catalyst Center entry point not found."; exit 1; }
	@test -f "$(MERAKI_MAGIC_DIR)/meraki_magic_remote.py" || { echo "ERROR: Meraki Magic entry point not found."; exit 1; }

check-app:
	@test -f "$(LIBRECHAT_DIR)/scripts/start_all.sh" || { echo "ERROR: LibreChat launcher not found."; exit 1; }
	@test -f "$(LIBRECHAT_DIR)/scripts/stop_suite.sh" || { echo "ERROR: LibreChat stop script not found."; exit 1; }
	@test "$(MCP_ENABLE_TLS)" = "true" && \
	      test "$(MCP_CATALYST_PORT)" = "8000" && \
	      test "$(MCP_MERAKI_MAGIC_PORT)" = "8002" || { \
	  echo "ERROR: Full-stack LibreChat configuration requires MCP TLS on ports 8000 and 8002."; \
	  echo "Custom MCP transport settings are supported only by MCP-only targets."; \
	  exit 1; \
	}
	@test -d "$(LIBRECHAT_DIR)/librechat-src" || { \
	  echo "ERROR: LibreChat is not installed at $(LIBRECHAT_DIR)/librechat-src"; \
	  echo "Run: cd $(LIBRECHAT_DIR) && bash scripts/setup_local.sh"; \
	  exit 1; \
	}

up: check-env check-app
	@$(MAKE) mcp-up
	@$(MAKE) app-up

down:
	@$(MAKE) app-down
	@$(MAKE) mcp-down

status:
	@$(MAKE) mcp-status
	@echo ""
	@$(MAKE) app-status
	@echo ""
	@echo "Remote MCP connectivity:"
	@if [ -x "$(PYTHON_BIN)" ] && [ -f "$(REMOTE_MCP_CHECKER)" ]; then \
	  LAB_ENV="$(LAB_ENV)" "$(PYTHON_BIN)" "$(REMOTE_MCP_CHECKER)" || true; \
	else \
	  echo "NOT CHECKED (Python environment or checker is unavailable)"; \
	fi
	@echo ""
	@echo "LLM configuration checks:"
	@if [ -x "$(PYTHON_BIN)" ] && [ -f "$(LLM_STATUS_CHECKER)" ]; then \
	  LAB_ENV="$(LAB_ENV)" "$(PYTHON_BIN)" "$(LLM_STATUS_CHECKER)" || true; \
	else \
	  echo "NOT CHECKED (Python environment or checker is unavailable)"; \
	fi

full-up: up

mcp-up: check-env
	@mkdir -p "$(LOG_DIR)"; \
	for f in "$(MCP_CATALYST_PID)" "$(MCP_MERAKI_MAGIC_PID)"; do \
	  if [ -f "$$f" ]; then \
	    PID="$$(cat "$$f")"; \
	    if kill -0 "$$PID" >/dev/null 2>&1; then kill "$$PID" >/dev/null 2>&1 || true; fi; \
	    rm -f "$$f"; \
	  fi; \
	done; \
	sleep 1; \
	for port in "$(MCP_CATALYST_PORT)" "$(MCP_MERAKI_MAGIC_PORT)"; do \
	  if lsof -tiTCP:"$$port" -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "ERROR: Port $$port is already used by a process not owned by this lab."; \
	    exit 1; \
	  fi; \
	done; \
	if [ "$(MCP_ENABLE_TLS)" = "true" ]; then \
	  mkdir -p "$$(dirname "$(MCP_SSL_CERTFILE)")"; \
	  if [ -f "$(MCP_SSL_CERTFILE)" ] && [ -f "$(MCP_SSL_KEYFILE)" ] && \
	     ! openssl x509 -in "$(MCP_SSL_CERTFILE)" -noout -checkend 86400 >/dev/null 2>&1; then \
	    echo "Existing MCP TLS certificate is invalid or expires within 24 hours; regenerating it."; \
	    rm -f "$(MCP_SSL_CERTFILE)" "$(MCP_SSL_KEYFILE)"; \
	  fi; \
	  if [ ! -f "$(MCP_SSL_CERTFILE)" ] || [ ! -f "$(MCP_SSL_KEYFILE)" ]; then \
	    rm -f "$(MCP_SSL_CERTFILE)" "$(MCP_SSL_KEYFILE)"; \
	    openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
	      -keyout "$(MCP_SSL_KEYFILE)" \
	      -out "$(MCP_SSL_CERTFILE)" \
	      -subj "/CN=localhost" \
	      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1; \
	  fi; \
	  chmod 600 "$(MCP_SSL_KEYFILE)"; \
	  echo "MCP TLS enabled with $(MCP_SSL_CERTFILE)"; \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/catalyst_center_mcp.log" \
	    --pid-file "$(MCP_CATALYST_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" MCP_LOG_DIR="$(LOG_DIR)" "$(PYTHON_BIN)" \
	    "$(PLATFORMS_DIR)/catalyst_center_remote.py" \
	    --host "$(MCP_HOST)" --port "$(MCP_CATALYST_PORT)" \
	    --ssl-certfile "$(MCP_SSL_CERTFILE)" --ssl-keyfile "$(MCP_SSL_KEYFILE)" >/dev/null; \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/meraki_magic_mcp.log" \
	    --pid-file "$(MCP_MERAKI_MAGIC_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" "$(PYTHON_BIN)" "$(MERAKI_MAGIC_DIR)/meraki_magic_remote.py" \
	    --host "$(MCP_HOST)" --port "$(MCP_MERAKI_MAGIC_PORT)" \
	    --ssl-certfile "$(MCP_SSL_CERTFILE)" --ssl-keyfile "$(MCP_SSL_KEYFILE)" >/dev/null; \
	else \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/catalyst_center_mcp.log" \
	    --pid-file "$(MCP_CATALYST_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" MCP_LOG_DIR="$(LOG_DIR)" "$(PYTHON_BIN)" \
	    "$(PLATFORMS_DIR)/catalyst_center_remote.py" \
	    --host "$(MCP_HOST)" --port "$(MCP_CATALYST_PORT)" >/dev/null; \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/meraki_magic_mcp.log" \
	    --pid-file "$(MCP_MERAKI_MAGIC_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" "$(PYTHON_BIN)" "$(MERAKI_MAGIC_DIR)/meraki_magic_remote.py" \
	    --host "$(MCP_HOST)" --port "$(MCP_MERAKI_MAGIC_PORT)" >/dev/null; \
	fi; \
	DEADLINE=$$(($$(date +%s) + $(MCP_STARTUP_TIMEOUT))); \
	while true; do \
	  C_PID="$$(lsof -tiTCP:$(MCP_CATALYST_PORT) -sTCP:LISTEN 2>/dev/null || true)"; \
	  M_PID="$$(lsof -tiTCP:$(MCP_MERAKI_MAGIC_PORT) -sTCP:LISTEN 2>/dev/null || true)"; \
	  if [ -n "$$C_PID" ] && [ -n "$$M_PID" ]; then break; fi; \
	  if [ "$$(date +%s)" -ge "$$DEADLINE" ]; then \
	    echo "ERROR: MCP servers did not become ready within $(MCP_STARTUP_TIMEOUT)s"; \
	    echo "Check $(LOG_DIR)/catalyst_center_mcp.log and $(LOG_DIR)/meraki_magic_mcp.log"; \
	    exit 1; \
	  fi; \
	  sleep 2; \
	done; \
	if [ "$(MCP_ENABLE_TLS)" = "true" ]; then \
	  curl --cacert "$(MCP_SSL_CERTFILE)" -fsS "https://localhost:$(MCP_CATALYST_PORT)/health" >/dev/null; \
	  curl --cacert "$(MCP_SSL_CERTFILE)" -fsS "https://localhost:$(MCP_MERAKI_MAGIC_PORT)/health" >/dev/null; \
	else \
	  curl -fsS "http://127.0.0.1:$(MCP_CATALYST_PORT)/health" >/dev/null; \
	  curl -fsS "http://127.0.0.1:$(MCP_MERAKI_MAGIC_PORT)/health" >/dev/null; \
	fi; \
	echo "Catalyst Center MCP ready on port $(MCP_CATALYST_PORT)"; \
	echo "Meraki Magic MCP ready on port $(MCP_MERAKI_MAGIC_PORT)"

mcp-down:
	@for f in "$(MCP_CATALYST_PID)" "$(MCP_MERAKI_MAGIC_PID)"; do \
	  if [ -f "$$f" ]; then \
	    PID="$$(cat "$$f")"; \
	    if kill -0 "$$PID" >/dev/null 2>&1; then kill "$$PID" >/dev/null 2>&1 || true; fi; \
	    rm -f "$$f"; \
	  fi; \
	done
	@echo "Default MCP server stop signals sent."

mcp-status:
	@echo "Port $(MCP_CATALYST_PORT) (Catalyst Center MCP):"
	@lsof -nP -iTCP:$(MCP_CATALYST_PORT) -sTCP:LISTEN || true
	@echo ""
	@echo "Port $(MCP_MERAKI_MAGIC_PORT) (Meraki Magic MCP):"
	@lsof -nP -iTCP:$(MCP_MERAKI_MAGIC_PORT) -sTCP:LISTEN || true
	@echo ""
	@if [ "$(MCP_ENABLE_TLS)" = "true" ]; then \
	  echo "Catalyst health (HTTPS):"; \
	  if curl --cacert "$(MCP_SSL_CERTFILE)" -fsS "https://localhost:$(MCP_CATALYST_PORT)/health" 2>/dev/null; then :; else echo "NOT READY"; fi; \
	  echo ""; \
	  echo "Meraki Magic health (HTTPS):"; \
	  if curl --cacert "$(MCP_SSL_CERTFILE)" -fsS "https://localhost:$(MCP_MERAKI_MAGIC_PORT)/health" 2>/dev/null; then :; else echo "NOT READY"; fi; \
	  echo ""; \
	else \
	  echo "Catalyst health (HTTP):"; \
	  if curl -fsS "http://127.0.0.1:$(MCP_CATALYST_PORT)/health" 2>/dev/null; then :; else echo "NOT READY"; fi; \
	  echo ""; \
	  echo "Meraki Magic health (HTTP):"; \
	  if curl -fsS "http://127.0.0.1:$(MCP_MERAKI_MAGIC_PORT)/health" 2>/dev/null; then :; else echo "NOT READY"; fi; \
	  echo ""; \
	fi

app-up: check-env check-app
	@mkdir -p "$(LIBRECHAT_DIR)/logs"; \
	"$(LIBRECHAT_DIR)/scripts/stop_suite.sh" >/dev/null 2>&1 || true; \
	rm -f "$(LIBRECHAT_LAUNCHER_PID)"; \
	"$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	  --log-file "$(LIBRECHAT_LAUNCHER_LOG)" \
	  --pid-file "$(LIBRECHAT_LAUNCHER_PID)" -- \
	  env LAB_ENV="$(LAB_ENV)" \
	  BACKEND_PORT="$(LIBRECHAT_BACKEND_PORT)" \
	  HTTPS_PROXY_PORT="$(LIBRECHAT_HTTPS_PORT)" \
	  bash "$(LIBRECHAT_DIR)/scripts/start_all.sh" >/dev/null; \
	LAUNCHER_PID="$$(cat "$(LIBRECHAT_LAUNCHER_PID)")"; \
	DEADLINE=$$(($$(date +%s) + $(LIBRECHAT_STARTUP_TIMEOUT))); \
	while true; do \
	  if curl --cacert "$(MCP_SSL_CERTFILE)" -fsS \
	    "https://localhost:$(LIBRECHAT_HTTPS_PORT)/" >/dev/null 2>&1; then \
	    echo "LibreChat ready on port $(LIBRECHAT_HTTPS_PORT)"; \
	    break; \
	  fi; \
	  if ! kill -0 "$$LAUNCHER_PID" >/dev/null 2>&1; then \
	    echo "ERROR: LibreChat launcher exited before becoming ready."; \
	    echo "Check $(LIBRECHAT_LAUNCHER_LOG)"; \
	    rm -f "$(LIBRECHAT_LAUNCHER_PID)"; \
	    exit 1; \
	  fi; \
	  if [ "$$(date +%s)" -ge "$$DEADLINE" ]; then \
	    echo "ERROR: LibreChat did not become ready within $(LIBRECHAT_STARTUP_TIMEOUT)s."; \
	    echo "Check $(LIBRECHAT_LAUNCHER_LOG)"; \
	    exit 1; \
	  fi; \
	  sleep 2; \
	done

app-down:
	@"$(LIBRECHAT_DIR)/scripts/stop_suite.sh" || true
	@if [ -f "$(LIBRECHAT_LAUNCHER_PID)" ]; then \
	  PID="$$(cat "$(LIBRECHAT_LAUNCHER_PID)")"; \
	  if kill -0 "$$PID" >/dev/null 2>&1; then kill "$$PID" >/dev/null 2>&1 || true; fi; \
	  rm -f "$(LIBRECHAT_LAUNCHER_PID)"; \
	fi
	@DEADLINE=$$(($$(date +%s) + 15)); \
	while lsof -tiTCP:$(LIBRECHAT_HTTPS_PORT) -sTCP:LISTEN >/dev/null 2>&1 || \
	      lsof -tiTCP:$(LIBRECHAT_BACKEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; do \
	  if [ "$$(date +%s)" -ge "$$DEADLINE" ]; then \
	    echo "WARN: LibreChat listeners are still present; check ports $(LIBRECHAT_HTTPS_PORT) and $(LIBRECHAT_BACKEND_PORT)."; \
	    break; \
	  fi; \
	  sleep 1; \
	done

app-status:
	@echo "Port $(LIBRECHAT_HTTPS_PORT) (LibreChat HTTPS):"
	@lsof -nP -iTCP:$(LIBRECHAT_HTTPS_PORT) -sTCP:LISTEN || true
	@echo ""
	@echo "Port $(LIBRECHAT_BACKEND_PORT) (LibreChat backend):"
	@lsof -nP -iTCP:$(LIBRECHAT_BACKEND_PORT) -sTCP:LISTEN || true
	@echo ""
	@echo "LibreChat health (HTTPS):"
	@if curl --cacert "$(MCP_SSL_CERTFILE)" -fsS \
	  "https://localhost:$(LIBRECHAT_HTTPS_PORT)/" >/dev/null 2>&1; then \
	  echo "OK: https://localhost:$(LIBRECHAT_HTTPS_PORT)/"; \
	else \
	  echo "NOT READY"; \
	fi

optional-meraki-up: check-env
	@mkdir -p "$(LOG_DIR)"; \
	if [ -f "$(MCP_MERAKI_PID)" ]; then \
	  PID="$$(cat "$(MCP_MERAKI_PID)")"; \
	  if kill -0 "$$PID" >/dev/null 2>&1; then kill "$$PID" >/dev/null 2>&1 || true; fi; \
	  rm -f "$(MCP_MERAKI_PID)"; \
	  sleep 1; \
	fi; \
	if lsof -tiTCP:"$(MCP_MERAKI_PORT)" -sTCP:LISTEN >/dev/null 2>&1; then \
	  echo "ERROR: Port $(MCP_MERAKI_PORT) is already used by a process not owned by this lab."; \
	  exit 1; \
	fi; \
	if [ "$(MCP_ENABLE_TLS)" = "true" ]; then \
	  test -f "$(MCP_SSL_CERTFILE)" && test -f "$(MCP_SSL_KEYFILE)" || { echo "ERROR: Run 'make up' first to create the shared lab certificate."; exit 1; }; \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/meraki_mcp.log" \
	    --pid-file "$(MCP_MERAKI_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" MCP_LOG_DIR="$(LOG_DIR)" "$(PYTHON_BIN)" \
	    "$(PLATFORMS_DIR)/meraki_remote.py" --host "$(MCP_HOST)" --port "$(MCP_MERAKI_PORT)" \
	    --ssl-certfile "$(MCP_SSL_CERTFILE)" --ssl-keyfile "$(MCP_SSL_KEYFILE)" >/dev/null; \
	else \
	  "$(PYTHON_BIN)" "$(DETACHED_LAUNCHER)" \
	    --log-file "$(LOG_DIR)/meraki_mcp.log" \
	    --pid-file "$(MCP_MERAKI_PID)" -- \
	    env LAB_ENV="$(LAB_ENV)" MCP_LOG_DIR="$(LOG_DIR)" "$(PYTHON_BIN)" \
	    "$(PLATFORMS_DIR)/meraki_remote.py" --host "$(MCP_HOST)" --port "$(MCP_MERAKI_PORT)" >/dev/null; \
	fi; \
	echo "Optional bundled Meraki MCP start requested on port $(MCP_MERAKI_PORT)."

optional-meraki-down:
	@if [ -f "$(MCP_MERAKI_PID)" ]; then \
	  PID="$$(cat "$(MCP_MERAKI_PID)")"; \
	  if kill -0 "$$PID" >/dev/null 2>&1; then kill "$$PID" >/dev/null 2>&1 || true; fi; \
	  rm -f "$(MCP_MERAKI_PID)"; \
	fi
	@echo "Optional bundled Meraki MCP stop signal sent."

optional-meraki-status:
	@echo "Port $(MCP_MERAKI_PORT) (optional bundled Meraki MCP):"
	@lsof -nP -iTCP:$(MCP_MERAKI_PORT) -sTCP:LISTEN || true
