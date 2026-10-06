# Sandbox image for the Coder Agent's run_shell tool and CoderVerifier.
#
# Based on node:20 (NOT node:20-slim) specifically because the -slim variant
# ships without git -- the Coder Agent's system prompt explicitly encourages
# `git status`/`git diff` as a self-check, and both silently failed with
# exit 127 on -slim (documented in CLAUDE.md). @babel/parser is baked into
# the image itself (not the project's own node_modules) so the check_syntax
# tool can validate JSX files even before a project's own `npm install` has
# run for the very first time.
FROM node:20

RUN npm install -g @babel/parser@^7.25.0

# npm's global install location isn't on Node's default require() search
# path -- NODE_PATH is the standard way to make it requireable from any cwd.
ENV NODE_PATH=/usr/local/lib/node_modules

WORKDIR /workspace
