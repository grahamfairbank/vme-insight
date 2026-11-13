# Image tooling for the vme-insight appliance build. Runs without /dev/kvm (software emulation).
FROM debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive LIBGUESTFS_BACKEND=direct
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libguestfs-tools linux-image-amd64 qemu-system-x86 qemu-utils \
      ca-certificates curl genisoimage zstd xz-utils python3 openssh-client \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
