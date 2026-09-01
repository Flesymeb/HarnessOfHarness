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
  <a href="https://flesymeb.github.io/HarnessOfHarness/#resources"><img src="https://img.shields.io/badge/Download%20Games-478CBF?style=for-the-badge&logo=itchdotio&logoColor=white" alt="Download games"></a>
</p>

## 🗞️ News

- 🎉 **Coming soon** — We will publicly release **HoH-lite**, a lightweight implementation of HoH's core workflow.
- 🎉 **2026-09** — Added the Harness of Harness project page and the Fusepoint gameplay showcase.
- 🎉 **2026-08** — Fusepoint reached more than 70 autonomous development loops.

## Overview

We introduce Harness-of-Harness (HoH), a framework that equips coding agents with *continual improvement* capabilities for autonomous software development.

HoH builds upon existing coding-agent harnesses and organizes development into iterative planning–coding–testing loops.

In a multi-day deployment with more than 70 iterations, HoH autonomously develops a first-person-shooter game, featuring a coherent storyline, fully implemented core mechanics, human-playable experience, polished visuals and integrated audio.

<p align="center">
  <img src="assets/figures/framework.jpg" width="100%"
       alt="Harness-of-Harness framework">
</p>

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
| **Fusepoint** | FPS | [![Watch showcase](https://img.shields.io/badge/Watch%20showcase-365F7D?style=for-the-badge&logo=googlechrome&logoColor=white)](https://flesymeb.github.io/HarnessOfHarness/#demo) | [![Download game](https://img.shields.io/badge/Download%20game-478CBF?style=for-the-badge&logo=itchdotio&logoColor=white)](https://flesymeb.github.io/HarnessOfHarness/#resources) | [![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Flesymeb/fusepoint) |
| **Mournlight** | TBD | ![Coming soon](https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge) | [![Coming soon](https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge)](https://github.com/Flesymeb/mournlight/releases) | [![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Flesymeb/mournlight) |

## Code

We will publicly release HoH-lite, a lightweight implementation of HoH's core workflow, together with reproducibility materials.

## Citation

† Haoyang Yan, Min-Le Su, Hangfan Zhang, and Zhanhao Li contributed equally.

```bibtex
@article{yan2026harness,
  title={Harness of Harness: Multi-Day Autonomous Software Development with Continual Improvement},
  author={Yan, Haoyang and Su, Min-Le and Zhang, Hangfan and Li, Zhanhao and Zhang, Chen and Zhang, Shao and Chen, Yang and Bai, Lei and Hu, Shuyue},
  journal={arXiv preprint},
  year={2026}
}
```

## License

Original materials in this repository are released under the [MIT License](LICENSE).

## Contributors

We thank everyone who contributed to Harness of Harness and its case studies.

<p align="center">
  <a href="https://github.com/Flesymeb"><img src="assets/figures/contributors/Flesymeb-card.png" width="112" height="140" alt="Hyoung Yan"></a>&nbsp;&nbsp;&nbsp;
  <a href="https://github.com/rayburstray"><img src="assets/figures/contributors/rayburstray-card.png" width="112" height="140" alt="Ray Burstray"></a>&nbsp;&nbsp;&nbsp;
  <a href="https://github.com/HaoTechGuy"><img src="assets/figures/contributors/HaoTechGuy-card.png" width="112" height="140" alt="HaoTechGuy"></a>&nbsp;&nbsp;&nbsp;
  <a href="https://github.com/qzzqzzb"><img src="assets/figures/contributors/qzzqzzb-card.png" width="112" height="140" alt="qzzqzzb"></a>
</p>
