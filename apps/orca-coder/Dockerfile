# syntax=docker/dockerfile:1
# AppImage factory — builds the trusted-proxy-patched Orca and EXPORTS a .AppImage.
#
# Docker here is only a hermetic build sandbox: the toolchain is pinned and the
# base is Debian bookworm (glibc 2.36), a floor at or below the Debian Coder
# workspaces this runs on. Nothing is shipped as an image — the final `export`
# stage is copied out via `buildx --output type=local`.
#
# Patch-file build (openclaw pattern): clone the pristine upstream release
# (stablyai/orca @ vVERSION) and `git apply` patches/. The build depends only on
# upstream, never on our fork (the fork is the authoring polygon).
#
# electron-builder 26's default AppImage toolset is a STATIC runtime (bundled
# mksquashfs + a prepended runtime binary) — so the build needs no FUSE and no
# appimagetool, and runs unprivileged in CI.

# ── builder ────────────────────────────────────────────────────────────────
# Mirrors Orca's own build env: node 24 + the toolchain electron-builder and the
# single native dep (node-pty) need. node/pnpm are pinned to Orca's declared
# versions (upstream-required — a newer pnpm would break the frozen lockfile).
FROM node:24-bookworm AS builder

ARG VERSION
ARG ORCA_REPO=https://github.com/stablyai/orca.git

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libasound2 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libsecret-1-dev \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxss1 \
    pkg-config \
    python3 \
  && rm -rf /var/lib/apt/lists/*

# pnpm pinned to Orca's own packageManager field — upstream-required, not "latest".
RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

WORKDIR /src
# Fetch only the pinned upstream release tag (shallow) — no fork dependency.
RUN git init -q . \
  && git remote add origin "${ORCA_REPO}" \
  && git fetch --depth 1 origin "refs/tags/${VERSION}" \
  && git checkout -q FETCH_HEAD

# Apply the local patch series on top of the pristine tag. git apply fails the
# build loudly if a patch no longer matches the pinned VERSION.
COPY patches/ /patches/
RUN for p in /patches/*.patch; do echo "applying $p"; git apply --verbose "$p"; done

# Frozen lockfile keeps the build reproducible against upstream's committed lock.
RUN pnpm install --frozen-lockfile

# build:desktop = typecheck (validates the patch) + relay + cli + electron-vite
# + web. Then rebuild node-pty against Electron's ABI and package a Linux
# AppImage (electron-builder default static toolset — no FUSE at build).
RUN pnpm build:desktop \
  && pnpm ensure:electron-runtime \
  && pnpm exec electron-builder --config config/electron-builder.config.cjs --linux AppImage

# Stage the single .AppImage under a predictable, versioned name for release.
RUN mkdir -p /out \
  && f="$(ls dist/*.AppImage | head -1)" \
  && test -n "$f" \
  && cp "$f" "/out/orca-coder-${VERSION}-x86_64.AppImage" \
  && ls -l /out

# ── export ─────────────────────────────────────────────────────────────────
# `buildx --output type=local,dest=./dist` writes THIS stage's filesystem to
# ./dist — i.e. just the .AppImage (mode 0755 preserved). No runtime image.
FROM scratch AS export
COPY --from=builder /out/ /
