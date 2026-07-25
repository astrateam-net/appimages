# AppImage factory target for orca-coder (Orca runtime, trusted-proxy patch).
# Docker is only a hermetic build sandbox — the `export` stage is written out via
# `buildx --output type=local`, not shipped as an image.

variable "VERSION" {
  // renovate: datasource=github-releases depName=stablyai/orca
  default = "v1.4.155"
}

variable "SOURCE" {
  default = "https://github.com/astrateam-net/appimages"
}

group "default" {
  targets = ["appimage"]
}

# Builds the patched Orca and exports the .AppImage to ./dist. amd64 only — Orca
# is an Electron app; an arm64 build under QEMU emulation is impractical.
target "appimage" {
  target    = "export"
  args      = { VERSION = "${VERSION}" }
  labels    = { "org.opencontainers.image.source" = "${SOURCE}" }
  platforms = ["linux/amd64"]
  output    = ["type=local,dest=./dist"]
}
