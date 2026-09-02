<div align="center">
  <img src="assets/figures/banner-readme.webp" width="100%" alt="Harness of Harness continual development process">
</div>

<hr>

<p align="center"><strong><big><big>Harness of Harness</big></big></strong></p>

<p align="center"><em>Multi-Day Autonomous Software Development with Continual Improvement</em></p>

<p align="center">
  <a href="https://arxiv.org/abs/2609.01481"><img src="https://img.shields.io/badge/Paper-8F3B45?style=for-the-badge&logo=arxiv&logoColor=white" alt="Paper"></a>
  <a href="#demos"><img src="https://img.shields.io/badge/Video-6B5B73?style=for-the-badge&logo=googleplay&logoColor=white" alt="Video"></a>
  <a href="https://github.com/Flesymeb/HarnessOfHarness"><img src="https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub"></a>
  <a href="https://flesymeb.github.io/HarnessOfHarness/"><img src="https://img.shields.io/badge/Project%20Page-365F7D?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Project page"></a>
  <a href="https://flesymeb.github.io/HarnessOfHarness/#resources"><img src="https://img.shields.io/badge/Download%20Games-5F6872?style=for-the-badge&logo=itchdotio&logoColor=white" alt="Download games"></a>
</p>

## 🗞️ News

- 🎉 **2026-09-02** — 🌐 Our [project page](https://flesymeb.github.io/HarnessOfHarness/) is now live, featuring demo videos and project resources.
- 🎉 **2026-09-02** — 📄 Our paper, [Harness-of-Harness](https://arxiv.org/abs/2609.01481), is now available on arXiv.
- 🎉 **Coming soon** — We will publicly release HoH-lite, a lightweight implementation of HoH's core workflow.
- 🎉 **2026-09** — Mournlight, a Vampire Survivors–style roguelite, has reached 80+ loops.
- 🎉 **2026-09** — [Fusepoint](https://github.com/Flesymeb/fusepoint), a single-player narrative first-person shooter, has reached 70+ loops. [Watch demo →](https://flesymeb.github.io/HarnessOfHarness/#demo)

## Overview

We introduce **Harness-of-Harness (HoH)**, a framework that equips coding agents with **continual improvement** capabilities for autonomous software development. HoH builds upon existing coding-agent harnesses and organizes development into iterative **planning–coding–testing loops**.

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

<div align="center">
  <video src="https://github.com/Flesymeb/HarnessOfHarness/raw/refs/heads/main/assets/video/HoH-video-full-web.mp4"
         poster="https://raw.githubusercontent.com/Flesymeb/HarnessOfHarness/main/assets/figures/hoh-video-full-poster.jpg"
         controls preload="metadata" width="100%"
         aria-label="Full Harness-of-Harness project showcase"></video>
</div>

<p align="center"><a href="https://github.com/Flesymeb/HarnessOfHarness/raw/refs/heads/main/assets/video/HoH-video-full-web.mp4">Watch the full showcase video</a></p>

We will continue adding games and demos across different genres. For each project, you can access the source repository and follow its development trajectory.

| Game           | Genre     |                                                                                       Showcase                                                                                       |                                                                                       Download                                                                                       |                                                                       Trajectory                                                                       |
| :------------- | :-------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------------------------------------------------------------------------------: |
| **Fusepoint**  | FPS       | [![Watch showcase](<https://img.shields.io/badge/Watch%20showcase-365F7D?style=for-the-badge&logo=googlechrome&logoColor=white>)](https://flesymeb.github.io/HarnessOfHarness/#demo) | [![Download game](<https://img.shields.io/badge/Download%20game-5F6872?style=for-the-badge&logo=itchdotio&logoColor=white>)](https://flesymeb.github.io/HarnessOfHarness/#resources) | [![Trajectory](https://img.shields.io/badge/Trajectory-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Flesymeb/fusepoint) |
| **Mournlight** | Roguelite |                                               ![Coming soon](<https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge>)                                                |                      [![Coming soon](<https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge>)](https://github.com/Flesymeb/mournlight/releases)                      |       [![Coming soon](<https://img.shields.io/badge/Coming%20soon-9AA5AD?style=for-the-badge>)](https://github.com/Flesymeb/mournlight/releases)       |

## Code

We will publicly release HoH-lite, a lightweight implementation of HoH's core workflow.

## Citation

```bibtex
@article{yan2026harness,
  title={Harness of Harness: Multi-Day Autonomous Software Development with Continual Improvement},
  author={Yan, Haoyang and Su, Min-Le and Zhang, Hangfan and Li, Zhanhao and Zhang, Chen and Zhang, Shao and Chen, Yang and Bai, Lei and Hu, Shuyue},
  journal={arXiv preprint},
  eprint={2609.01481},
  archivePrefix={arXiv},
  year={2026}
}
```

## License

Original materials in this repository are released under the [MIT License](LICENSE).

## Contributors

We thank everyone who contributed to Harness of Harness and its case studies.

<p align="center">
  <a href="https://github.com/Flesymeb"><img src="assets/figures/contributors/Flesymeb-card.png" width="112" height="140" alt="Hyoung Yan"></a>   
  <a href="https://github.com/rayburstray"><img src="assets/figures/contributors/rayburstray-card.png" width="112" height="140" alt="Ray Burstray"></a>   
  <a href="https://github.com/HaoTechGuy"><img src="assets/figures/contributors/HaoTechGuy-card.png" width="112" height="140" alt="HaoTechGuy"></a>   
  <a href="https://github.com/qzzqzzb"><img src="assets/figures/contributors/qzzqzzb-card.png" width="112" height="140" alt="qzzqzzb"></a>
</p>

## Contact

For questions, suggestions, or feedback, please feel free to contact us at:

[yanhaoyang](mailto:yanhaoyang@pjlab.org.cn) · [suminle](mailto:suminle@pjlab.org.cn) · [zhanghangfan](mailto:zhanghangfan@pjlab.org.cn) · [lizhanhao](mailto:lizhanhao@pjlab.org.cn) · [hushuyue](mailto:hushuyue@pjlab.org.cn) @pjlab.org.cn
