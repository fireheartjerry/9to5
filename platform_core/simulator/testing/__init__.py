"""9TO5 end-to-end "virtual operator" testing.

A deterministic stand-in for a human at the controls: it drives a real run through the
exact surfaces a person uses (the ControlBus that backs the terminal/Discord commands,
and the web dashboard's HTTP control handler) and asserts the system responds correctly,
end to end. Paired with the --dry-run simulation doubles, this runs a full pipeline with
no Ollama / Claude CLI / Discord / Obsidian -- reproducibly, offline, in CI.
"""
