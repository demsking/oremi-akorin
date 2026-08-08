APP_NAME := $(shell uvx --from=toml-cli toml get --toml-path pyproject.toml project.name)
APP_VERSION := $(shell uv version --short)
APP_DESCRIPTION := $(shell uvx --from=toml-cli toml get --toml-path pyproject.toml project.description)
APP_LICENSE := $(shell uvx --from=toml-cli toml get --toml-path pyproject.toml project.license.text 2>/dev/null || uvx --from=toml-cli toml get --toml-path pyproject.toml project.license)

DIST_DIR := dist
BUILD_DIR := build
BUILDER_NAME := $(APP_NAME)

IMAGE_NAME := demsking/$(APP_NAME)
IMAGE_PLATFORMS := linux/amd64,linux/arm64
IMAGE_REVISION := $(shell git rev-parse HEAD)
IMAGE_CREATED := $(shell date --utc --iso-8601=seconds)

.PHONY: install tests clean package pypi image bump patch minor major alpha beta rc release publish check-clean

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

clean: clean-dist
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov


#
## Packaging
clean-dist:
	rm -rf $(DIST_DIR)

package: clean-dist
	devbox run uv build --wheel
	devbox run twine check "$(DIST_DIR)"/*

pypi: package
	devbox run twine upload "$(DIST_DIR)"/*

image:
	@docker buildx inspect "$(BUILDER_NAME)" >/dev/null 2>&1 || \
	  docker buildx create --name "$(BUILDER_NAME)" --bootstrap

	@echo "Building $(IMAGE_NAME):$(APP_VERSION)"
	devbox run uv lock --locked
	docker buildx use "$(BUILDER_NAME)"
	docker buildx build . \
	  --platform "$(IMAGE_PLATFORMS)" \
	  --push \
	  --progress plain \
	  --tag "$(IMAGE_NAME):$(APP_VERSION)" \
	  --tag "$(IMAGE_NAME):latest" \
	  --label "org.opencontainers.image.title=$(APP_NAME)" \
	  --label "org.opencontainers.image.description=$(APP_DESCRIPTION)" \
	  --label "org.opencontainers.image.version=$(APP_VERSION)" \
	  --label "org.opencontainers.image.revision=$(IMAGE_REVISION)" \
	  --label "org.opencontainers.image.authors=Sébastien Demanou <demsking@gmail.com>" \
	  --label "org.opencontainers.image.created=$(IMAGE_CREATED)" \
	  --label "org.opencontainers.image.vendor=Sébastien Demanou" \
	  --label "org.opencontainers.image.licenses=$(APP_LICENSE)"

image-test:
	uv lock
	docker build . \
	  --progress plain \
	  --tag $(IMAGE_NAME):test

live: image-test
	docker run -it --rm --env-file .env.example -v ./data:/oremi/data --network host $(IMAGE_NAME):test

check-clean:
	@test -z "$$(git status --porcelain)" || (echo "Working tree is not clean" && exit 1)

bump:
	@test -n "$(VERSION)" || (echo "Usage: make bump VERSION=1.2.3" && exit 1)
	uv version "$(VERSION)"
	uv lock
	git add pyproject.toml uv.lock
	git commit -m "chore(release): bump version to $(VERSION)"

alpha: check-clean
	uv version --bump alpha
	uv lock

beta: check-clean
	uv version --bump beta
	uv lock

rc: check-clean
	uv version --bump rc
	uv lock

patch: check-clean
	uv version --bump patch
	uv lock

minor: check-clean
	uv version --bump minor
	uv lock

major: check-clean
	uv version --bump major
	uv lock

release: check-clean
	uv sync
	git add pyproject.toml uv.lock
	git commit -m "chore(release): bump version to $(shell uv version --short)"
	git tag --annotate "v$(shell uv version --short)" --message "Release v$(shell uv version --short)"

publish: check-clean image-test
	$(MAKE) pypi image
	git push origin main
	git push origin "v$(shell uv version --short)"

