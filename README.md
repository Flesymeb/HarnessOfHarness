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

- 🎉 **Coming soon** — We will publicly release **HoH-lite**, a lightweight implementation of HoH's core workflow.
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

| Game | Genre | Showcase | Download | GitHub |
|:--|:--|:--:|:--:|:--:|
| **Fusepoint** | FPS | [![Watch showcase](https://img.shields.io/badge/Watch%20showcase-365F7D?style=for-the-badge&logo=googlechrome&logoColor=white)](https://flesymeb.github.io/HarnessOfHarness/#demo) | [![Download game](https://img.shields.io/badge/Download%20game-478CBF?style=for-the-badge&logo=google-drive&logoColor=white)](https://flesymeb.github.io/HarnessOfHarness/#resources) | [![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Flesymeb/fusepoint) |
| **Mournlight** | TBD | ![Coming soon](https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge) | [![Coming soon](https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge)](https://github.com/Flesymeb/mournlight/releases) | [![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Flesymeb/mournlight) |

## Code

We will publicly release HoH-lite, a lightweight implementation of HoH's core workflow.

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

Original materials in this repository are released under the [MIT License](LICENSE).

## Contributors

We thank everyone who contributed to Harness of Harness and its case studies.

| Contributor | GitHub |
|:--|:--:|
| Hyoung Yan | [@Flesymeb](https://github.com/Flesymeb) |
| Ray Burstray | [@rayburstray](https://github.com/rayburstray) |
| HaoTechGuy | [@HaoTechGuy](https://github.com/HaoTechGuy) |
| qzzqzzb | [@qzzqzzb](https://github.com/qzzqzzb) |
