VERSION := $(shell python3 -c "import goveehome; print(goveehome.__version__)")

.PHONY: run test install uninstall rpm fake-lights clean

run:
	python3 -m goveehome

test:
	python3 -m pytest

install:
	./install.sh

uninstall:
	./uninstall.sh

fake-lights:
	python3 tools/fake_light.py --count 3

rpm:
	mkdir -p $(HOME)/rpmbuild/SOURCES
	git archive --format=tar.gz --prefix=GoveeHome-For-Linux-$(VERSION)/ \
		-o $(HOME)/rpmbuild/SOURCES/GoveeHome-For-Linux-$(VERSION).tar.gz HEAD
	rpmbuild -ba packaging/fedora/goveehome.spec

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
