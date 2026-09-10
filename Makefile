# Developer convenience targets for the avatar-art pipeline.
# The GPS-server Go cross-build has its own makefile (gps-server/Makefile).
#
# These scripts need Python with Pillow (PIL). Pick the first interpreter that
# has it - python3, then python, then the Windows 'py' launcher. Override with
# 'make lowres PYTHON=/path/to/python' if yours is elsewhere.
ifndef PYTHON
PYTHON := $(shell for p in python3 python py; do command -v "$$p" >/dev/null 2>&1 && "$$p" -c "import PIL" >/dev/null 2>&1 && { printf '%s' "$$p"; break; }; done)
endif
ifeq ($(strip $(PYTHON)),)
PYTHON := python3
endif

.PHONY: help lowres avatar templates build

help:
	@echo "targets:"
	@echo "  make lowres     scale highres/ avatar art down to lowres/ (128x168)"
	@echo "  make lowres FILTER=nearest   crisp pixel-exact reduction instead of smooth"
	@echo "  make avatar     make lowres, then embed the highres art into the phone page"
	@echo "  make templates  regenerate the drawing templates in avatar_assets/templates/"
	@echo "  make build      build the GPS-server binary (delegates to gps-server/)"

# Draw once at the highres size; this makes the Pager's lowres copies.
lowres:
	$(PYTHON) assets/gen_lowres.py $(FILTER)

# The full "I added art, wire it up" step: lowres copies + embed into the page.
avatar: lowres
	$(PYTHON) assets/gen_avatar.py

templates:
	$(PYTHON) assets/gen_templates.py

build:
	$(MAKE) -C gps-server build
