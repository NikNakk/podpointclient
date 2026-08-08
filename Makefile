.PHONY: spec test lint clean package check publish

test: spec

spec:
	python3 -m pytest \
		-vv \
		-qq \
		--timeout=9 \
		--durations=10 \
		--cov podpointclient \
		--cov-report term \
		--cov-report html \
		-o console_output_style=count \
		-p no:sugar \
		-s \
		-vv \
		tests

lint:
	pylint ./podpointclient

clean:
	rm -rf dist/*

package:
	python3 -m build

check: package
	python3 -m twine check dist/*

publish: clean check
	python3 -m twine upload dist/* --verbose
