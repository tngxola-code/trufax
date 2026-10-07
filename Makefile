.PHONY: install test lint format gates demo serve clean

install:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check gates src/trufax tests/platform scripts
	mypy src/trufax tests/platform

format:
	ruff format gates src/trufax tests/platform scripts

gates:
	./scripts/run-gates.sh commit

demo:
	cd examples/catalog && trufax run catalog.yaml
	cd examples/budget && trufax run budget.yaml
	cd examples/assessment-roll && trufax run assessment-roll.yaml

serve:
	trufax serve --home trufax-home

clean:
	rm -rf data/raw/* data/interim/* data/output/* examples/*/output trufax-home
