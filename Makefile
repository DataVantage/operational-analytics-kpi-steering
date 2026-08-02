PYTHON  ?= python3
export PYTHONPATH := src

.DEFAULT_GOAL := help
.PHONY: help demo data run sample test compile lint info clean distclean all

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

demo:  ## Run the whole pipeline on the committed offline fixture (no download)
	$(PYTHON) -m oakpi run --source data/sample/online_retail_II_sample.csv.gz

data:  ## Download the real UCI Online Retail II dataset into data/raw/
	$(PYTHON) -m oakpi data

run:  ## Run the pipeline (uses data/raw/ if present, otherwise the fixture)
	$(PYTHON) -m oakpi run

sample:  ## Regenerate the offline fixture
	$(PYTHON) -m oakpi sample

info:  ## Show what is currently in the warehouse
	$(PYTHON) -m oakpi info

test:  ## Run the test suite
	$(PYTHON) -m unittest discover -s tests -v

compile:  ## Check that all Python files compile
	$(PYTHON) -m compileall -q src tests

lint:  ## Run Ruff static analysis
	$(PYTHON) -m ruff check src tests

all: sample run test  ## Rebuild everything from scratch and verify it

clean:  ## Remove generated artefacts, keep the fixture
	rm -rf data/warehouse/marts data/warehouse/*.sqlite* data/warehouse/*.duckdb* data/warehouse/run_log.json
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

distclean: clean  ## Also remove the downloaded raw data
	rm -rf data/raw/*
