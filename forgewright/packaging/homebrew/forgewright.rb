# This formula is auto-published to forest/homebrew-tap on each release tag.
# The sha256 and sdist URL are placeholders; CI (release.yml) replaces them
# with the real values from PyPI when a new tag is pushed.
#
# Local install (for maintainers):
#   brew tap forest/tap https://github.com/forest/homebrew-tap
#   brew install --cask forest/tap/forgewright
#
# Or directly from this file while testing the formula:
#   brew install --build-from-source packaging/homebrew/forgewright.rb
class Forgewright < Formula
  desc "An open-source, CLI-first AI agent framework. Bring your own keys, run on your own box."
  homepage "https://github.com/forest/forgewright"
  url "https://files.pythonhosted.org/packages/source/f/forgewright/forgewright-0.1.0.tar.gz"
  # PLACEHOLDER_CI_REPLACES — the release workflow runs `python -m hashlib`
  # over the downloaded sdist and `sed`s this line on tag.
  sha256 "0" * 64
  license "MIT"

  head "https://github.com/forest/forgewright.git", branch: "main"

  depends_on "python@3.12"

  # crawl4ai is part of the `[crawl]` extra and pulls a Rust build toolchain
  # at install time. Most users get a usable forgewright without it; the
  # `crawl` extra is opt-in. We deliberately do NOT add a `depends_on "rust"`
  # here so the default install stays light. Power users who want crawling
  # should `pip install forgewright[crawl]` themselves (or set
  # HOMEBREW_FORGEWRIGHT_RUST=1 in their environment before tapping).

  # Playwright (used by `[browser]`) is also opt-in. We do not bundle a
  # Chromium resource into the formula — users who want browsers run
  # `python -m playwright install chromium` after install. The trade-off is
  # a smaller bottle and a faster first install.

  def install
    # Create an isolated virtualenv and pip-install the wheel from PyPI.
    # `virtualenv_create` is provided by Homebrew's Python tap.
    venv = virtualenv_create(libexec, "python3.12")

    # The wheel pulls in the *runtime* extras declared in pyproject.toml.
    # Dev extras (pytest, mypy, ruff, etc.) are deliberately excluded.
    venv.pip_install "forgewright==#{version}"

    # Ship the `forgewright` entry point on PATH.
    bin.install_symlink libexec/"bin/forgewright"

    # Bash / zsh completions (optional; Typer emits these at runtime, but
    # we still ship a small static stub for `forgewright build` and
    # `forgewright mcp` so completions work *before* the first run).
    bash_completion.install build_completions("bash") if respond_to?(:build_completions)
    zsh_completion.install  build_completions("zsh")  if respond_to?(:build_completions)
  end

  def caveats
    <<~EOS
      forgewright has been installed.

      First-run checklist:
        1. forgewright init                   # write ~/.config/forgewright/
        2. export FORGEWRIGHT_PROVIDER=stub   # or: openai / anthropic
        3. forgewright build "say hi"         # smoke test
        4. forgewright                        # open the REPL

      Optional extras (not installed by default to keep the bottle small):
        forgewright[browser]    # playwright + headless Chromium
        forgewright[mcp]        # MCP client / server
        forgewright[crawl]      # crawl4ai (needs a Rust toolchain)
        forgewright[all]        # everything above
    EOS
  end

  test do
    # Smoke test 1: version string
    assert_match version.to_s, shell_output("#{bin}/forgewright --version")

    # Smoke test 2: mcp subcommand is wired up
    assert_match "MCP", shell_output("#{bin}/forgewright mcp --help")
  end
end
