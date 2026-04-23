# Related Work: Comparable Systems for Automated Paper-to-Video Generation

*Literature survey compiled for the JushenRenji workshop paper (April 2026).*

JushenRenji is a fully automated pipeline that takes an arXiv link and produces a five-minute Chinese-narrated explainer video combining (i) a Ken-Burns-style "main video" that pans over figures extracted from the PDF while a TTS voice reads a four-section plan (opening / intro / method / results), (ii) a Manim-animated technical explainer whose code is written by an LLM (via `opencode` orchestrating DeepSeek) one scene at a time (TitleScene, IntroScene, MethodScene, ResultsScene), and (iii) automated publication to Bilibili and Xiaohongshu. The survey below situates this pipeline against eight adjacent research and product lines.

---

## 1. End-to-End Paper-to-Video Systems

### Paper2Video / PaperTalker (2025)
**Authors/Org**: Zeyu Zhu, Kevin Qinghong Lin, Mike Zheng Shou et al. (Show Lab, NUS)
**Link**: https://arxiv.org/abs/2510.05096 · https://github.com/showlab/Paper2Video
**Approach**: Multi-agent framework that, from a paper PDF, synthesises LaTeX Beamer slides (with compile-feedback refinement and a "Tree Search Visual Choice" layout optimiser), generates per-sentence subtitles with cursor-grounding, and finally renders a talking-head avatar reading the narration. Introduces a 101-paper benchmark paired with author-recorded videos and four metrics (Meta Similarity, PresentArena, PresentQuiz, IP Memory).
**Relevance to JushenRenji**: **Closest English-language peer.** Both target academic video generation and use an agentic pipeline. Differences: (a) Paper2Video emphasises slide + talking-head production; JushenRenji replaces slides with direct PDF-figure panning and replaces the avatar with pure TTS, gaining visual fidelity to the original paper. (b) JushenRenji adds a Manim explainer layer that Paper2Video does not produce. (c) JushenRenji is Chinese-first and optimised for social-platform publishing; Paper2Video is English, conference-presentation style.

### PresentAgent (EMNLP 2025 Demo)
**Authors/Org**: Jingwei Shi et al.
**Link**: https://arxiv.org/abs/2507.04036 · https://aclanthology.org/2025.emnlp-demos.58.pdf
**Approach**: Modular pipeline that segments a long document, plans and renders slide-style frames, then generates contextual spoken narration with LLM + TTS, composing a synchronised video. Introduces PresentEval, a VLM-as-judge framework scoring content fidelity, visual clarity, and audience comprehension.
**Relevance to JushenRenji**: Shares the "document → slides + TTS narration → video" core. JushenRenji differs by (a) producing raw-figure Ken-Burns instead of synthesised slides, which preserves author-drawn diagrams, and (b) layering Manim animation for equations/architecture, which PresentAgent does not attempt.

### ArXivisual (TartanHacks 2026, hackathon winner)
**Authors/Org**: Raj Shah et al.
**Link**: https://www.arxivisual.org/ · https://github.com/rajshah6/arXivisual
**Approach**: Next.js 16 + FastAPI full-stack webapp. Paste an arXiv URL, a 7-agent Claude pipeline segments sections, and inline 3Blue1Brown-style Manim animations play as the reader scrolls through the paper ("scrollytelling"). No TTS; the reader controls pacing.
**Relevance to JushenRenji**: Same raw input (arXiv URL) and same Manim-animation output, but consumed as an interactive reading artefact rather than a passive video. JushenRenji uniquely combines both a passive main-video narration and multi-scene Manim into one publishable artefact, and handles full end-to-end upload.

### DOC2PPT (AAAI 2022)
**Authors/Org**: Tsu-Jui Fu et al. (UCSB / Virginia Tech)
**Link**: https://arxiv.org/abs/2101.11796 · https://doc2ppt.github.io/
**Approach**: Hierarchical seq2seq framework that converts a scientific document into a slide deck: document summarisation, text/image retrieval, slide structure prediction, and layout prediction.
**Relevance to JushenRenji**: A pre-LLM precursor. Covers only the slide-generation leg, no narration, no rendering to video, no figure-aware animation. JushenRenji's plan-generation module plays the equivalent role but with LLM prompting and four pre-defined rhetorical sections rather than learnt layout.

### SlideTailor (2025)
**Authors/Org**: (Scientific slide personalisation team)
**Link**: https://arxiv.org/html/2512.20292
**Approach**: Personalised presentation-slide generation for scientific papers; conditions on author preferences / persona.
**Relevance to JushenRenji**: Adjacent — slide-only, no video; confirms the direction of personalised document-to-presentation work. JushenRenji ignores personalisation in favour of consistent daily-coverage quality.

---

## 2. LLM-Driven Manim / Code-Centric Animation

### Code2Video (NeurIPS 2025 DL4C Workshop)
**Authors/Org**: Show Lab, NUS
**Link**: https://arxiv.org/abs/2510.01174 · https://github.com/showlab/Code2Video
**Approach**: Three-agent framework (Planner → Coder → Critic) that emits executable Manim Python from a knowledge point, with scope-guided auto-fix and VLM-based visual-anchor critique to refine spatial layout. Introduces the MMMC benchmark and the TeachQuiz metric (VLM-unlearn-then-watch). Reports 40 % improvement over direct code generation.
**Relevance to JushenRenji**: **Second-closest peer for the Manim leg.** JushenRenji's per-scene Manim generation (Title/Intro/Method/Results) mirrors Code2Video's Planner-Coder split, but JushenRenji's Coder is `opencode` + DeepSeek rather than a custom agent, and the "Critic" role is effectively delegated to compile-and-render feedback rather than a dedicated VLM judge. JushenRenji scales past single-concept knowledge points to full-paper coverage.

### TheoremExplainAgent (ACL 2025 oral)
**Authors/Org**: TIGER-AI-Lab
**Link**: https://arxiv.org/abs/2502.19400 · https://github.com/TIGER-AI-Lab/TheoremExplainAgent
**Approach**: Two-agent (planner + coder) system generating long-form (5–10 min) Manim theorem-explanation videos. Ships TheoremExplainBench (240 theorems, 5 metrics across accuracy/depth/flow/visual relevance/layout). o3-mini reaches 93.8 % success rate.
**Relevance to JushenRenji**: Validates the viability of multi-minute LLM-generated Manim and provides a usable evaluation lens. Differences: scope is theorems (math-centric), not whole papers; no voice narration; no PDF figure ingestion. JushenRenji can adopt TheoremExplainBench-style metrics for its Manim scenes.

### Manimator (2025)
**Authors/Org**: HyperCluster-Tech
**Link**: https://arxiv.org/abs/2507.14306 · https://github.com/HyperCluster-Tech/manimator
**Approach**: Three-stage pipeline (LLM → structured Markdown scene description → LLM → Manim Python → render). Accepts prompts or arXiv PDFs. Strong on TheoremExplainBench Visual Relevance (0.899) and Logical Flow (0.880).
**Relevance to JushenRenji**: Near-identical input surface (arXiv PDF → Manim). Differences: Manimator produces one continuous animation per paper, JushenRenji structures output as four pedagogical scenes aligned to a plan. Manimator has no Chinese TTS and no social-media publishing layer.

### Math-To-Manim
**Authors/Org**: Harley Coops (community)
**Link**: https://github.com/HarleyCoops/Math-To-Manim
**Approach**: Six-agent swarm; reasons from foundations to advanced topics, pre-writes LaTeX equations and visual specifications, then composes verbose prompts that a code LLM turns into Manim.
**Relevance to JushenRenji**: Open-source exemplar of agent-decomposition for Manim code gen. JushenRenji uses a simpler single-pass opencode-driven generator per scene but inherits the same "plan-before-code" philosophy.

### 3Blue1Brown manim (engine) & manimCE / Manim Community
**Authors/Org**: Grant Sanderson; Manim Community Edition
**Link**: https://github.com/3b1b/manim · https://www.manim.community/
**Approach**: The original Python animation engine used by 3Blue1Brown; manimCE is the community-maintained fork.
**Relevance to JushenRenji**: Foundational dependency. JushenRenji is one of dozens of LLM-driven consumers of this engine; no novelty here but every system in this section relies on it.

### manim-video-generator / rohitg00
**Authors/Org**: rohitg00 (community)
**Link**: https://github.com/rohitg00/manim-video-generator
**Approach**: Natural-language → GPT → Manim code → rendered animation, FastAPI-served.
**Relevance to JushenRenji**: Educational-demo scale; single-prompt rather than paper-grounded. Illustrates the commodity nature of "LLM-writes-Manim" — JushenRenji's contribution is not code-gen per se but orchestrating paper comprehension → four-scene plan → per-scene code-gen → audio mix.

---

## 3. Multimodal Paper Summarisation, PDF Parsing, Figure Extraction

### Nougat (Meta AI, 2023)
**Authors/Org**: Lukas Blecher, Guillem Cucurull, Thomas Scialom, Robert Stojnic
**Link**: https://arxiv.org/abs/2308.13418 · https://github.com/facebookresearch/nougat
**Approach**: 350 M-param Swin + mBART encoder–decoder transcribing rasterised academic PDF pages to LaTeX-aware Markdown. No OCR dependency.
**Relevance to JushenRenji**: A potential upstream component. JushenRenji currently uses a combination of DeepSeek-OCR and bespoke extraction; Nougat remains a stronger baseline for equation-heavy papers and is worth citing as the dominant open-source academic-PDF parser.

### PDFFigures 2.0 & DeepFigures (Allen AI)
**Authors/Org**: Christopher Clark, Santosh Divvala et al.
**Link**: https://github.com/allenai/pdffigures2 · https://github.com/allenai/deepfigures-open
**Approach**: Scala rule-based (PDFFigures 2.0, 94 % precision @ 90 % recall) and distantly-supervised neural (DeepFigures, ResNet-101 regression on 640×480 page rasters) figure/caption/table extractors.
**Relevance to JushenRenji**: Directly relevant to the Ken-Burns leg, which requires high-quality figure crops with captions. JushenRenji cites these as the canonical figure-extraction prior art; its pipeline is a modern LLM/VLM replacement for the same job.

### DocLayout-YOLO (2024)
**Authors/Org**: OpenDataLab
**Link**: https://arxiv.org/html/2410.12628v1
**Approach**: YOLO-style detector fine-tuned on synthetic multi-domain layouts with global-to-local adaptive perception.
**Relevance to JushenRenji**: Modern fast layout detector; could be swapped in if figure-detection accuracy becomes a bottleneck.

### LayoutParser + PubLayNet
**Authors/Org**: Zejiang Shen et al. · IBM Research
**Link**: https://github.com/Layout-Parser/layout-parser
**Approach**: Toolkit wrapping Faster/Mask R-CNN detectors trained on PubLayNet, HJDataset, PrimaLayout, etc., for document-region detection.
**Relevance to JushenRenji**: Legacy but still widely used. JushenRenji's figure-aware module would historically have been built on LayoutParser; the project moves past it using VLM-based crop-and-caption.

### SciCap / SciCap+ / SciCap Challenge 2023
**Authors/Org**: Ting-Yao Hsu et al.
**Link**: https://arxiv.org/abs/2110.11624 · https://arxiv.org/abs/2306.03491 · https://github.com/tingyaohsu/SciCap
**Approach**: 2 M+ figure-caption dataset from 290 k arXiv CS papers, later extended with mention-paragraph context. The 2023 challenge showed GPT-4V-preferred captions beat author-written ones in blind editor studies.
**Relevance to JushenRenji**: When JushenRenji narrates over a figure in the main video, it effectively performs figure captioning. SciCap is the benchmark the project should evaluate on to quantify that module's quality.

### PaperQA / PaperQA2 (Future House)
**Authors/Org**: Andrew White et al.
**Link**: https://arxiv.org/abs/2312.07559 · https://github.com/Future-House/paper-qa
**Approach**: Agentic RAG over scientific PDFs with in-text citations; reported super-human performance on literature-synthesis tasks.
**Relevance to JushenRenji**: Orthogonal but complementary — PaperQA2 answers questions *about* papers; JushenRenji *explains* one paper end-to-end. Could be integrated as a fact-check step over the generated plan.

### Elicit / SciSpace / Semantic Scholar
**Authors/Org**: Ought · SciSpace · AI2
**Link**: https://elicit.com/ · https://scispace.com/ · https://www.semanticscholar.org/
**Approach**: Commercial / non-profit semantic-search and summary UIs over 200–280 M-paper indexes; chat-with-PDF, thematic analysis, structured literature reviews.
**Relevance to JushenRenji**: Consumer-facing analogues of the "read papers for you" value proposition, but *textual* rather than video. JushenRenji is differentiated by its output modality and daily-publishing cadence.

---

## 4. Audio / Podcast / TTS from Papers

### NotebookLM Audio Overviews (Google, 2024–)
**Authors/Org**: Google Labs
**Link**: https://notebooklm.google/audio · https://blog.google/technology/ai/notebooklm-audio-overviews/
**Approach**: Turns a set of user-uploaded sources (PDFs, slides, YouTube) into a two-host conversational "deep dive" audio, with four formats (Deep Dive, Brief, Critique, Debate). >2 M users.
**Relevance to JushenRenji**: **Most visible consumer competitor in the "audio-from-paper" space.** Audio-only, English-first, conversational. JushenRenji is video-first, single-narrator, Chinese, and deterministic in structure. The workshop paper should directly contrast the two on information density and verifiability (NotebookLM is known to paraphrase loosely).

### AI Papers Podcast / Paper-to-Podcast / Best AI Papers Explained
**Link**: https://open.spotify.com/show/5Tq5XPWQh9lonBvtAFow8O · https://www.paper2podcast.com/ · https://podcasts.apple.com/us/podcast/best-ai-papers-explained/id1802074035
**Approach**: Several independent podcasts use NotebookLM or bespoke LLM + TTS pipelines to publish daily / weekly paper summaries in audio form.
**Relevance to JushenRenji**: Demonstrates product-market fit for LLM-narrated science content. JushenRenji extends into video + visual grounding.

---

## 5. Automated Social-Media Science Content

### AK on X / Hugging Face Daily Papers
**Authors/Org**: Ahsen Khaliq (AK) · Hugging Face
**Link**: https://huggingface.co/papers · https://x.com/_akhaliq
**Approach**: After ~17 k tweets manually summarising arXiv papers, AK pivoted to the HF Daily Papers feed, where maintainers + authors claim papers and community up-votes rank them. Largely text + thumbnail.
**Relevance to JushenRenji**: The de-facto distribution channel for English AI paper discovery. JushenRenji plays the equivalent role for Chinese video platforms (Bilibili, Xiaohongshu) but with automated content generation — AK-class curation + automated production in one loop.

### arxiv-sanity-bot and similar
**Link**: https://github.com/giacomov/arxiv-sanity-bot
**Approach**: Bot that scrapes trending arXiv papers and posts LLM-generated summaries to Twitter.
**Relevance to JushenRenji**: Text-summary analogue; confirms the "automated-bot daily arXiv coverage" concept is proven, and JushenRenji is the video-upgrade path.

### alphaXiv · daily-arXiv-ai-enhanced
**Link**: https://www.alphaxiv.org/ · https://github.com/dw-dengwei/daily-arXiv-ai-enhanced
**Approach**: alphaXiv adds discussion threads and AI summaries directly onto arXiv pages; daily-arXiv-ai-enhanced auto-crawls and AI-summarises into a GitHub Pages site.
**Relevance to JushenRenji**: Peer content-surfacing systems; no video, no TTS. Strong upstream for paper selection.

---

## 6. LLM-to-Visual Code Generation (Broader)

### Agent Banana (2026)
**Authors/Org**: (image-editing team)
**Link**: https://arxiv.org/abs/2602.09084
**Approach**: Hierarchical Planner + Executor agentic image editor operating at 4 K resolution with tool use.
**Relevance to JushenRenji**: JushenRenji uses a Banana-style edit step ("Edit Banana") to pre-process extracted PDF figures (tighten crops, clean backgrounds, remove watermarks) before Ken-Burns. Agent Banana is the closest academic reference for this sub-step.

### Pico-Banana-400K
**Link**: https://arxiv.org/html/2510.19808v1
**Approach**: 400 k text-guided image-edit dataset created with Gemini 2.5 Flash + Nano-Banana + Gemini 2.5 Pro.
**Relevance to JushenRenji**: Supports fine-tuning a JushenRenji-specific figure-preprocessor if default APIs prove insufficient.

### SAM / SAM 2 / SAM 3 (Meta)
**Link**: https://github.com/facebookresearch/segment-anything · https://ai.meta.com/blog/segment-anything-model-3/
**Approach**: Promptable vision foundation for object / region segmentation. SAM 3 adds text prompts and real-time video tracking.
**Relevance to JushenRenji**: Used in JushenRenji's MethodScene_HiST_AT_SAM3.py variant to segment figure sub-regions for animated reveal in Manim. No closer-tied academic system does SAM-guided figure reveals in research-explainer videos.

### Hi-SAM (2024)
**Link**: https://arxiv.org/html/2401.17904v1
**Approach**: SAM-based hierarchical text segmenter (stroke/word/line/paragraph) with layout analysis.
**Relevance to JushenRenji**: Useful upstream if JushenRenji wants to isolate text captions from figures at sub-pixel quality.

---

## 7. Commercial AI Video / Avatar Platforms

### HeyGen (Avatar V, 2025)
**Link**: https://www.heygen.com/ · https://www.heygen.com/research/avatar-v-model
**Approach**: Single-reference-video → high-resolution arbitrary-length talking-head synthesis, modelling static (dentition, skin, geometry) and dynamic (rhythm, micro-expressions, gestures) personal identity. HeyGen Video Agent bundles avatar + scripting engine for explainers.
**Relevance to JushenRenji**: Best-in-class avatar generator; Paper2Video integrates a talking-head module in similar spirit. JushenRenji *deliberately avoids avatars* for faster render, lower cost, and better fit to Chinese AI-content conventions (most top Bilibili AI creators don't use avatars). Worth citing as the "avatar-path not taken."

### Synthesia · Pictory · VideoScribe · Simpleshow
**Link**: https://www.synthesia.io/ · https://pictory.ai/ · https://www.videoscribe.co/
**Approach**: Commercial SaaS for script-to-avatar-video, blog-to-video, whiteboard animation explainers, etc. Not science-specific.
**Relevance to JushenRenji**: General baseline for "AI-generated explainer video" UX quality. All lack academic-paper understanding and Manim-level mathematical animation.

### Yann.ai / Papers.fm
**Note**: Searches did not surface verifiable landing pages under these exact names; skipping rather than fabricating.

---

## 8. Chinese-Language AI Paper Explainer Channels (Bilibili Competitive Landscape)

### 跟李沐学AI (Mu Li)
**Link**: https://space.bilibili.com/1567748478 · https://github.com/mli/paper-reading
**Approach**: Mu Li (previously Amazon, now BosonAI co-founder) reads classic and new DL papers paragraph-by-paragraph with hand-drawn annotations. His "three-pass paper-reading method" is the de-facto pedagogy. ~25 h of recordings, 100+ classic papers, twice-weekly updates.
**Relevance to JushenRenji**: **The benchmark for quality in the Chinese AI-paper-video ecosystem.** JushenRenji trades off Mu Li's human insight for coverage (daily, any paper) and repeatability. Workshop paper should explicitly frame this as "complement, not replace": Mu Li for landmark papers, JushenRenji for the long tail.

### 朱毅 (Yi Zhu) — co-host on 跟李沐学AI
**Approach**: Co-presenter for several deep-learning paper-reading videos on Mu Li's channel (ViT, MAE, etc.); CV specialist.
**Relevance to JushenRenji**: Same channel, subset of content.

### 人工智能那点事 · 机器之心 · AI前线 · PaperWeekly (B站 + WeChat)
**Approach**: Human-edited news-style channels summarising AI/arXiv developments; mix of text posts and short video.
**Relevance to JushenRenji**: Editorial-scale operations with small teams; JushenRenji aims to match their volume with 0 human-in-the-loop per paper.

### AIGC-type short-form creators (小红书 / 抖音 / B站)
**Approach**: Individual creators posting 1–3 minute "I read this paper so you don't have to" reels. Typically manual slide + voice-over.
**Relevance to JushenRenji**: The Xiaohongshu publishing target sits directly in this competitive slot; JushenRenji's automation is an order of magnitude faster per output.

### Quality bar observations
- Top Chinese AI paper explainers are almost exclusively **human-narrated**, **slide- or whiteboard-based**, and **do not use avatars**. JushenRenji's TTS + PDF-figure + Manim stack is consistent with this stylistic convention while removing the human-labour bottleneck.
- The stylistic gap is the **absence of presenter insight**. JushenRenji's four-section plan (opening/intro/method/results) is a deterministic-narrative heuristic designed to simulate Mu Li-style structuring without true understanding — this is an explicit limitation the workshop paper should discuss.

---

## Positioning

JushenRenji occupies an under-explored point in the design space spanned by the eight sections above. The two closest academic systems are **Paper2Video / PaperTalker** (NUS Show Lab, arXiv 2510.05096) and **Code2Video** (same lab, arXiv 2510.01174), with **TheoremExplainAgent** (ACL 2025) and **Manimator** (arXiv 2507.14306) directly adjacent. Paper2Video solves the slide + talking-head presentation-video leg end-to-end; Code2Video and TheoremExplainAgent solve agentic Manim generation for single knowledge points / theorems; Manimator bridges arXiv-PDF to Manim. Consumer-side, **NotebookLM Audio Overviews** dominate audio, **AK / HF Daily Papers** dominate text, and **跟李沐学AI** sets the quality bar for Chinese video.

JushenRenji is novel primarily as a *composition* and a *distribution target*:

1. **Dual-track output**: a figure-preserving Ken-Burns main video (which no Manim-centric system produces) *plus* a four-scene Manim explainer (which no slide-centric system produces). Paper2Video + Code2Video would have to be combined and aligned to a shared narrative plan to match JushenRenji's output; neither paper attempts this.
2. **Deterministic four-section rhetorical plan** (opening/intro/method/results) that structures both tracks from a single LLM pass, avoiding the open-ended planning that causes Manimator and TheoremExplainAgent to drift on long papers.
3. **Chinese-first**, with a TTS and content-style matched to Bilibili / Xiaohongshu conventions — no avatar, no English-centric assumptions in the plan prompts.
4. **Publishing-loop closure**: automated upload to Bilibili and Xiaohongshu with daily-cadence arXiv coverage. Every academic peer stops at the rendered video file; every Chinese competitor stops at the manual editing step.
5. **Figure-preserving visual track**: JushenRenji keeps author-drawn figures (after a Banana-style clean-up) rather than re-synthesising slides. This materially improves fidelity for ML papers whose architecture diagrams carry irreducible information content.

The gap JushenRenji fills is the **automated-production-and-distribution layer for Chinese AI paper video**, with modest but deliberate technical contributions over prior work: the dual-track composition, the deterministic plan, and the figure-preserving main-video design. Weaknesses relative to peers include the absence of a formal evaluation benchmark (TheoremExplainBench / MMMC / PresentEval have established metrics JushenRenji should adopt), no avatar track, no personalisation, and reliance on third-party APIs (DeepSeek, Banana, TTS) whose quality bounds the output. The workshop paper's Related Work section should cite Paper2Video, Code2Video, and TheoremExplainAgent as the three primary anchors, acknowledge NotebookLM as the most-recognised product in the adjacent audio space, and position 跟李沐学AI as the human benchmark JushenRenji seeks to scale toward, not surpass.
