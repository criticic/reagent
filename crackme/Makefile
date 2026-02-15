CC      := cc
CXX     := c++
SRCDIR  := src
BINDIR  := .bin
CFLAGS  := -Wall -Wextra -O1
LDFLAGS :=

# Challenges
TARGETS := \
	$(BINDIR)/crackme01_password \
	$(BINDIR)/crackme02_xor \
	$(BINDIR)/crackme03_keygen \
	$(BINDIR)/crackme04_bof \
	$(BINDIR)/crackme05_multistage

# System utility reimplementations (compiled from source, unsigned)
SYS_TARGETS := \
	$(BINDIR)/sys_true \
	$(BINDIR)/sys_echo \
	$(BINDIR)/sys_yes \
	$(BINDIR)/sys_cat \
	$(BINDIR)/sys_base64

.PHONY: all clean

all: $(BINDIR) $(TARGETS) $(SYS_TARGETS)
	@echo ""
	@echo "Built $(words $(TARGETS)) crackmes + $(words $(SYS_TARGETS)) utilities into $(BINDIR)/"
	@echo ""
	@ls -lh $(BINDIR)/
	@echo ""
	@echo "Test with:  uv run reagent analyze $(BINDIR)/crackme01_password -g 'Find the password'"

$(BINDIR):
	mkdir -p $(BINDIR)

# --- Crackmes ---

$(BINDIR)/crackme01_password: $(SRCDIR)/crackme01_password.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/crackme02_xor: $(SRCDIR)/crackme02_xor.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/crackme03_keygen: $(SRCDIR)/crackme03_keygen.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

# BOF challenge: no stack protector, no PIE for exploitability
$(BINDIR)/crackme04_bof: $(SRCDIR)/crackme04_bof.c | $(BINDIR)
	$(CC) $(CFLAGS) -fno-stack-protector -Wno-deprecated-declarations -o $@ $<

# Multi-stage: stripped to make it harder
$(BINDIR)/crackme05_multistage: $(SRCDIR)/crackme05_multistage.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

# --- System utilities (our own implementations) ---

$(BINDIR)/sys_true: $(SRCDIR)/sys_true.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/sys_echo: $(SRCDIR)/sys_echo.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/sys_yes: $(SRCDIR)/sys_yes.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/sys_cat: $(SRCDIR)/sys_cat.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

$(BINDIR)/sys_base64: $(SRCDIR)/sys_base64.c | $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip $@

clean:
	rm -rf $(BINDIR)
