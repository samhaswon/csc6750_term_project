PYTHON ?= python3
DOCKER_COMPOSE ?= sudo docker compose

LOGIC_TESTS = \
	ollama_proxy.tests.test_auth_guards \
	ollama_proxy.tests.test_model_resolution \
	ollama_proxy.tests.test_response_payload_parsing \
	ollama_proxy.tests.test_tool_result_handling \
	ollama_proxy.tests.test_wake_word_config \
	whisper_service.tests.test_service \
	deepface_service.tests.test_service \
	kitten_tts_service.tests.test_service

HARNESS_TEST = ollama_proxy.tests.test_tool_call_success_rates

.PHONY: help build deploy up down restart test test-logic test-harness test-all

help:
	@printf '%s\n' \
		'Targets:' \
		'  build        Build all Docker images' \
		'  deploy/up    Build and start the full stack in detached mode' \
		'  down         Stop the full Docker Compose stack' \
		'  restart      Recreate the full Docker Compose stack' \
		'  test         Run the fast logic/unit test suite' \
		'  test-harness Run the Ollama proxy tool-call evaluation harness' \
		'  test-all     Run logic tests followed by the harness'

build:
	$(DOCKER_COMPOSE) build

deploy up:
	$(DOCKER_COMPOSE) up -d --build

down:
	$(DOCKER_COMPOSE) down

restart: down deploy

test: test-logic

test-logic:
	$(PYTHON) -m unittest $(LOGIC_TESTS)

test-harness:
	$(PYTHON) -m unittest $(HARNESS_TEST)

test-all: test-logic test-harness
