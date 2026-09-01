<div align="center">
  <img src="assets/figures/banner-readme.webp" width="100%" alt="Harness of Harness continual development process">
</div>

<hr>

<p align="center"><strong><big><big>Harness of Harness</big></big></strong></p>

<p align="center"><em>Multi-Day Autonomous Software Development with Continual Improvement</em></p>

<p align="center">
  <a href="https://flesymeb.github.io/HarnessOfHarness/#resources"><img src="https://img.shields.io/badge/-Paper-8F3B45?style=for-the-badge&labelColor=8F3B45&logo=arxiv&logoColor=white" alt="Paper"></a>
  <a href="https://github.com/Flesymeb/HarnessOfHarness"><img src="https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub"></a>
  <a href="https://flesymeb.github.io/HarnessOfHarness/"><img src="https://img.shields.io/badge/Project%20Page-365F7D?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Project page"></a>
  <a href="https://flesymeb.github.io/HarnessOfHarness/#resources"><img src="https://img.shields.io/badge/-Download%20Games-478CBF?style=for-the-badge&labelColor=478CBF&logo=data:image/svg%2bxml%3bbase64%2cPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI%2bPHBhdGggZmlsbD0iI2ZmZiIgZD0iTTcgNmgxMGMyLjggMCA0LjggMi4zIDUuNiA1LjFsMSA0LjRjLjUgMi4yLS44IDMuOS0yLjUgMy45LTEuMiAwLTIuMS0uNy0yLjktMS43bC0xLjEtMS40SDYuOWwtMS4xIDEuNEM1IDE4LjcgNC4xIDE5LjQgMi45IDE5LjRjLTEuNyAwLTMtMS43LTIuNS0zLjlsMS00LjRDMi4yIDguMyA0LjIgNiA3IDZ6bTEuNSAzdjJoMnYxLjVoLTJ2MmgtMS41di0yaC0yVjExaDJWOWgxLjV6bTguMiAxLjVhMSAxIDAgMSAwIDAgMiAxIDEgMCAwIDAgMC0yem0yLjUgMi41YTEgMSAwIDEgMCAwIDIgMSAxIDAgMCAwIDAtMnoiLz48L3N2Zz4%3D" alt="Download games"></a>
</p>

## 🗞️ News

- 🎉 **2026-09** — Added the Harness of Harness project page and the Fusepoint gameplay showcase.
- 🎉 **2026-08** — Fusepoint reached more than 60 autonomous development loops.

## Overview

Harness of Harness (HoH) extends coding-agent harnesses with a persistent,
evidence-grounded development loop. Instead of treating every invocation as an
isolated coding task, HoH carries the evolving software artifact, execution
evidence, and next-step decisions across iterations.

Our paper studies autonomous software development from scratch and evaluates
the approach on three software-engineering benchmarks. **Fusepoint** provides
an open-ended case study: a single-player FPS developed over more than 60
autonomous loops.

## How It Works

Each iteration uses the same evolving project workspace and coordinates three
stable roles:

- **Project Planner** — reads the public requirements and evidence from the
  previous iteration, then writes a prioritized development document. It does
  not modify the artifact.
- **Developer** — implements the current development document in the shared
  workspace while preserving functionality that has already been verified.
- **QA Tester** — executes and inspects the updated artifact against the
  requirements, recording evidence for verified behavior and unresolved gaps.
  It remains read-only.

<p align="center">
  <img src="assets/figures/role_black.png" width="100%"
       alt="Project Planner, Developer, and QA Tester across continual development iterations">
</p>

The resulting artifact and evidence bundle become the starting state for the
next iteration, allowing the system to improve loop by loop.

## Demos

- **[Development process](https://flesymeb.github.io/HarnessOfHarness/#demo)**
  — watch Fusepoint evolve through successive autonomous iterations.
- **[Real gameplay](https://flesymeb.github.io/HarnessOfHarness/#demo)**
  — view footage captured directly from the resulting game.
- **[Project page](https://flesymeb.github.io/HarnessOfHarness/)**
  — paper overview, loop comparison, benchmark results, and supplementary
  videos.

## Code

The core Harness of Harness implementation is being prepared for release.
We plan to release **HoH-lite**, a lightweight open-source implementation of
the continual planning–development–QA workflow, together with configuration
examples and reproducibility instructions.

**Status:** Code coming soon.

## Citation

```bibtex
@article{yan2026harness,
  title={Harness of Harness: Multi-Day Autonomous Software Development with Continual Improvement},
  author={Yan, Haoyang and Su, Minle and Zhang, Hangfan and Li, Zhanhao and Zhang, Chen and Zhang, Shao and Chen, Yang and Bai, Lei and Hu, Shuyue},
  journal={arXiv preprint},
  year={2026}
}
```

## License

The HoH-lite implementation and associated research artifacts will include
their license terms with the corresponding release. Third-party game assets,
fonts, and other bundled materials remain subject to their original licenses.
