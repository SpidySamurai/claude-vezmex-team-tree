.PHONY: help install uninstall check sync-hooks test demo

help:
	@echo "make install      link the plugin into Herdr and wire the agent hooks"
	@echo "make check        report what is currently wired, change nothing"
	@echo "make uninstall    remove only what the installer wired"
	@echo "make sync-hooks   repair/wire hooks only, quietly (what the startup hook runs)"
	@echo "make test         run the whole suite"

install:
	python3 install.py

uninstall:
	python3 install.py --uninstall

check:
	python3 install.py --check

sync-hooks:
	python3 install.py --sync-hooks

# HERDR_WORKSPACE_ID is unset on purpose: the panel prefers it over the
# snapshot's focused workspace, so a real one leaks into the render tests and
# makes them look for an agent in the wrong workspace.
test:
	env -u HERDR_WORKSPACE_ID python3 -m unittest discover -s tests -t tests
