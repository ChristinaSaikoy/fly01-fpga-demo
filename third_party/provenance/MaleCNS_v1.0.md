# MaleCNS v1.0 provenance

Role: structural connectome source for the FLY-01 FULL backend.

Release: `male-cns:v1.0`  
Release date recorded by the local FULL-0 audit: 2026-06-08  
License recorded by the local FULL-0 audit: CC BY 4.0

Official project: https://www.janelia.org/project-team/flyem/male-cns-connectome  
Official download: https://male-cns.janelia.org/download/

Pinned assets used by the accepted FULL pipeline:

- `body-annotations-male-cns-v1.0-minconf-0.5.feather`
  - size: 14,483,314 bytes
  - SHA256: `2177E246113E4CFBF1E7772EC37C6DA1955FF22E8063D0B1F833101F99A9A3B2`
- `body-neurotransmitters-male-cns-v1.0.feather`
  - size: 43,282,834 bytes
  - SHA256: `95C9289220663ABEB3409F3AD9E5A7F8A53F8093F5139D15502CD08DA8879621`
- `connectome-weights-male-cns-v1.0-minconf-0.5.feather`
  - size: 1,051,241,946 bytes
  - SHA256: `E35DA783D1C686B2B58B3B87CD6A403AE43BFCFBA8BFF28E08EF752C1A56AFC1`

These raw datasets are intentionally **not committed**. Reconstruct the canonical pack with the accepted scripts after downloading the pinned official files and verifying checksums.

Scientific boundary: MaleCNS supplies structural connectivity and annotations. FLY-01's Shiu-derived LIF dynamics are an engineering reconstruction, not native MaleCNS biological dynamics.
