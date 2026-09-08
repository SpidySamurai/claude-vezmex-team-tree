.PHONY: help install uninstall check test demo

help:
	@echo "make install    link the plugin into Herdr and wire the agent hooks"
	@echo "make check      report what is currently wired, change nothing"
	@echo "make uninstall  remove only what the installer wired"
	@echo "make test       run the whole suite"

install:
	python3 install.py

uninstall:
	python3 install.py --uninstall

check:
	python3 install.py --check

# HERDR_WORKSPACE_ID is unset on purpose: the panel prefers it over the
# snapshot's focused workspace, so a real one leaks into the render tests and
# makes them look for an agent in the wrong workspace.
test:
	env -u HERDR_WORKSPACE_ID python3 -m unittest discover -s tests -t tests
