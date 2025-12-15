
.PHONY: install test ingest query serve clean

install:
	pip install .

dev-install:
	pip install -e .
	pip install pytest pytest-cov

test:
	python -m pytest tests/

clean:
	rm -rf dist build *.egg-info
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete

ingest:
	python -m core.cli ingest --data-dir data/corpus

query:
	python -m core.cli query "$(Q)"

serve:
	python -m core.cli serve
