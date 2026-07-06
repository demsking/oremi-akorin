APP_NAME := $(shell python scripts/metadata.py name)
APP_VERSION := $(shell python scripts/metadata.py version)
IMAGE_NAME := demsking/$(APP_NAME)

.PHONY: install tests dist clean

shell:
	tmuxinator

stop:
	tmux kill-session -t $(APP_NAME)

up: pull
	docker compose up -d --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs -f

pull:
	docker compose pull

restart:
	docker compose restart

down:
	docker compose down

stats:
	docker compose stats

install:
	rm -rf .venv
	devbox run uv venv --python 3.12
	devbox run uv sync

outdated:
	devbox run uv pip list --outdated

update: pull
	devbox run uv sync --upgrade
	devbox update
	pre-commit autoupdate

tests:
	uv run pytest tests/ -v

coverage:
	uv run pytest --cov=server

coverage-html:
	uv run pytest --cov=server --cov-report=html

lint:
	pre-commit run --all-files

fix:
	ruff check . --fix

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
	rm -rf dist/ build/

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
	@echo "Building $(IMAGE_NAME):$(APP_VERSION)"
	uv lock
	docker buildx use $(APP_NAME)
	docker buildx build . \
	  --platform linux/amd64,linux/arm64 \
	  --push \
	  --progress plain \
	  --tag $(IMAGE_NAME):$(APP_VERSION) \
	  --tag $(IMAGE_NAME):latest \
	  --label "org.opencontainers.image.title=$(APP_NAME)" \
	  --label "org.opencontainers.image.description=$(shell python scripts/metadata.py description)" \
	  --label "org.opencontainers.image.version=$(APP_VERSION)" \
	  --label "org.opencontainers.image.revision=$(shell git rev-parse HEAD)" \
	  --label "org.opencontainers.image.authors=Sébastien Demanou <demsking@gmail.com>" \
	  --label "org.opencontainers.image.created=$(shell date --rfc-3339=seconds)" \
	  --label "org.opencontainers.image.vendor=Sébastien Demanou" \
	  --label "org.opencontainers.image.licenses=$(shell python scripts/metadata.py license)"


image-test:
	uv lock
	docker build . \
	  --progress plain \
	  --tag $(IMAGE_NAME):test

live: image-test
	docker run -it --rm --env-file .env.example -v ./data:/oremi/data -p 5020:5020 $(IMAGE_NAME):test

publish: image-test
	git tag v$(APP_VERSION)
	$(MAKE) pypi image
	git push --tags origin main
