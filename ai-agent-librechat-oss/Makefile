BACKEND_PORT ?= 3081
HTTPS_PROXY_PORT ?= 3080

.PHONY: help up down status app-up app-down app-status

help:
	@echo "Targets:"
	@echo "  make up         Restart local app stack (nginx + backend)"
	@echo "  make down       Stop local app stack"
	@echo "  make status     Check local app stack status"

up:
	@$(MAKE) app-down
	@$(MAKE) app-up

down:
	@$(MAKE) app-down

status:
	@$(MAKE) app-status

app-up:
	BACKEND_PORT=$(BACKEND_PORT) HTTPS_PROXY_PORT=$(HTTPS_PROXY_PORT) \
	bash scripts/start_suite_ssl.sh

app-down:
	bash scripts/stop_suite.sh

app-status:
	@echo "LibreChat status: https://127.0.0.1:$(HTTPS_PROXY_PORT)/"
	@curl -k -fsS https://127.0.0.1:$(HTTPS_PROXY_PORT)/ >/dev/null
	@echo "OK (HTTPS frontend reachable)"
