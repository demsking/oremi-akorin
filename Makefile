APP_NAME := $(shell python scripts/metadata.py name)
APP_VERSION := $(shell python scripts/metadata.py version)
IMAGE_NAME := demsking/$(APP_NAME)

COMPOSE_SERVICES := mosquitto ollama isinmi weather rediyo kansa

.PHONY: all clean build dist

# Start the development environment using tmuxinator
shell:
	tmuxinator

stop:
	tmux kill-session -t $(APP_NAME)

up: pull
	docker compose -f .devcontainer/workspace.yaml up -d $(COMPOSE_SERVICES) --remove-orphans

ps:
	docker compose -f .devcontainer/workspace.yaml ps $(COMPOSE_SERVICES)

logs:
	docker compose -f .devcontainer/workspace.yaml logs -f

pull:
	docker compose -f .devcontainer/workspace.yaml pull $(COMPOSE_SERVICES)

restart:
	docker compose -f .devcontainer/workspace.yaml restart $(COMPOSE_SERVICES)

down:
	docker compose -f .devcontainer/workspace.yaml down $(COMPOSE_SERVICES)

stats:
	docker compose -f .devcontainer/workspace.yaml stats

clean:
	rm -rf dist/ build/

docs:
	devbox run serve -l 9650 doc/

install:
	rm -rf .venv
	devbox run uv venv --python 3.12
	devbox run uv sync

# Show outdated dependencies using uv
outdated:
	devbox run uv pip list --outdated

# Update dev env
update: pull
	devbox run uv sync --upgrade
	devbox update
	pre-commit autoupdate

lint:
	pre-commit run --all-files

fix:
	devbox run ruff check . --fix

test:
	devbox run pytest

coverage:
	devbox run pytest --cov=oremi_akorin

coverage-html:
	devbox run pytest --cov=oremi_akorin --cov-report=html

#
## Packaging
package:
	rm -rf dist/*
	devbox run uv build --wheel
	devbox run twine check dist/*

pypi: package
	devbox run twine upload dist/*

build/context:
	docker buildx create --name $(APP_NAME) --bootstrap
	mkdir -p build/
	touch $@

image: build/context
	docker buildx use $(APP_NAME)
	docker buildx build . \
	  --platform linux/amd64,linux/arm64 \
	  --push \
	  --progress plain \
	  --tag $(IMAGE_NAME):$(APP_VERSION) \
	  --tag $(IMAGE_NAME):latest \
	  --label "org.opencontainers.image.title=$(APP_NAME)" \
	  --label "org.opencontainers.image.description=$(shell python metadata.py description)" \
	  --label "org.opencontainers.image.version=$(APP_VERSION)" \
	  --label "org.opencontainers.image.revision=$(shell git rev-parse HEAD)" \
	  --label "org.opencontainers.image.authors=$(shell python metadata.py authors)" \
	  --label "org.opencontainers.image.created=$(shell date --rfc-3339=seconds)" \
	  --label "org.opencontainers.image.source=$(shell python metadata.py repository)" \
	  --label "org.opencontainers.image.url=$(shell python metadata.py repository)" \
	  --label "org.opencontainers.image.documentation=$(shell python metadata.py documentation)" \
	  --label "org.opencontainers.image.vendor=Oremi" \
	  --label "org.opencontainers.image.licenses=$(shell python metadata.py license)"

image-test:
	docker build --debug . \
	  --progress plain \
	  --tag $(IMAGE_NAME):test

publish: image-test image pypi
	git push --tags origin main
