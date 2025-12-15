
.PHONY: install test ingest query serve clean

install:
	pip install .

dev-install:
	pip install -e .
	pip install pytest pytest-cov

test:
	python -m pytest tests/

clean:
	python -c "import shutil, os; [shutil.rmtree(d) for d in ['dist', 'build'] if os.path.exists(d)]; [shutil.rmtree(d) for d in __import__('glob').glob('*.egg-info') if os.path.exists(d)]"
	python -c "import os; [os.remove(os.path.join(r, f)) for r, d, f in os.walk('.') for f in f if f.endswith('.pyc')]"
	python -c "import shutil, os; [shutil.rmtree(os.path.join(r, d)) for r, d, f in os.walk('.') for d in d if d == '__pycache__']"

ingest:
	python -m core.cli ingest --data-dir data/corpus

query:
	python -m core.cli query "$(Q)"

serve:
	python -m core.cli serve
