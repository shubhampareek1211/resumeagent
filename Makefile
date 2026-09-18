PYTHON := .venv/bin/python

.PHONY: setup test check demo package
setup:
	./scripts/setup.sh
test:
	$(PYTHON) -m unittest discover -s tests -v
check:
	$(PYTHON) -m ruff check scripts checks tests
	$(PYTHON) -m compileall -q scripts checks tests
	$(PYTHON) -m pip check
	$(PYTHON) scripts/check_public_tree.py
demo:
	cp examples/sample_resume.tex folder/outputs/sample_resume.tex
	cp examples/sample_keywords.txt folder/outputs/checks/sample_resume_keywords.txt
	./build.sh --type resume sample_resume --local-only
package:
	$(PYTHON) scripts/package_release.py
