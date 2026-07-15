# GALAXY R3 specification package — 2026-07-14

Seven specification documents, revised 2026-07-14 (supersedes the 2026-07-13 freeze).
This revision adds one canonical 50-repository/35-paper evidence registry and
subsystem projections. It changes no qualified node/edge count, gate, threshold,
authority rule, activation permission, or runtime behaviour. Start with the design
document; appendix A is the rename map.

## Contents (SHA-256)

- `2026-07-14-galaxy-r3-accretion-context-virtualization-r1.md`
  - `f4b753dcd7010b755ad956fa21cd76665acb990e7300f5b7d27ab43d8b134abf`
- `2026-07-14-galaxy-r3-brownfield-frontier-registry.md`
  - `ff69bb5867442b76f076a067be571e95113bf35bb000788023ac9b0b155cb3e2`
- `2026-07-14-galaxy-r3-design.md`
  - `d437cf9f04a874a8365c8542e0b0a03e2e893acf4d6c746ac7fed8298975e99b`
- `2026-07-14-galaxy-r3-preimplementation-readiness-ledger.md`
  - `672e68a53f0647183d0071bc16d897f1d3c76d570594a6bcdcbe99bcd87c6c4c`
- `2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md`
  - `1a72cc7bf1953c7f0a8cb0b05a42da43afa2b99e8cf45d9b55bcde9b55ac44ee`
- `2026-07-14-galaxy-r3-qualified-capability-topology.md`
  - `80c3c5704adb8b6a10c5cf57997b1e8cc89d50f74cd667d69d3d7b81d69eeab2`
- `2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md`
  - `0f52ea42c44e7eb482d923b9e89a12d04e44c1302f1a13d698366dc3bed0d89e`

## Read order

1. `2026-07-14-galaxy-r3-design.md` — system thesis; **appendix A** = astro rename map (old→new), **§13.1** = scaling-pattern posture, **§15.1** = deterministic simulation testing harness
2. `2026-07-14-galaxy-r3-brownfield-frontier-registry.md` — canonical `BR01..BR50` and `FR01..FR35`; source passports, Pulsar laboratory, and ICPC/IOI admission queue
3. `2026-07-14-galaxy-r3-qualified-capability-topology.md` — node/edge contract, §2.3 manifest definition of done
4. `2026-07-14-galaxy-r3-pulsar-r1-qualified-topology.md` — scheduler; §12.3 progress obligation, §12.4 mission-major trade-off, §12.5 research laboratory
5. `2026-07-14-galaxy-r3-quark-portfolio-r2-qualified-topology.md` — solver substrate; §14.1 Orbit + Parallax candidates, §16 qualified quarries
6. `2026-07-14-galaxy-r3-accretion-context-virtualization-r1.md` — context plane; §1.1 MemGPT prior art and divergence, §10 registry projection
7. `2026-07-14-galaxy-r3-preimplementation-readiness-ledger.md` — audit; read the banner first

## Required follow-up (not in this package)

- Plan/research artifacts under `plans/` and `state/research/` still carry retired names
  and remain dated 2026-07-13; they were not revised. Migrate them per design appendix
  §A.4, then recompute their SHA-256 values.
- **All implementation-plan hashes in the ledger are invalidated** until that migration
  completes. No plan-hash assertion may be treated as current.
- The base 71/95 node/edge ledger is still not materialized row-by-row anywhere in this
  package; it is a prerequisite of the validated single manifest.

## Verify

```bash
sha256sum -c SHA256SUMS
```
