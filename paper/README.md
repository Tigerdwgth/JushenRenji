# JushenRenji Workshop Paper Draft (v1)

End-to-end workshop paper describing the `JushenRenji` paper-to-video pipeline.

## Files

- `workshop.tex` — main paper source, single file (`\documentclass{article}` for now).
- `references.bib` — BibTeX with ~20 entries.
- `README.md` — this file.

## Compile

Standard four-pass LaTeX build (the middle two passes pick up bibliography + cross-refs):

```bash
cd paper/
pdflatex workshop
bibtex   workshop
pdflatex workshop
pdflatex workshop
```

Or, if `latexmk` is available:

```bash
latexmk -pdf workshop.tex
```

Packages required (all in `texlive-full` / `texlive-latex-extra` + `texlive-lang-chinese`):
`inputenc`, `fontenc`, `lmodern`, `geometry`, `microtype`, `graphicx`, `hyperref`, `url`,
`booktabs`, `amsmath`, `amssymb`, `xcolor`, `listings`, `caption`, `subcaption`,
`enumitem`, `natbib`, `xurl`, `CJKutf8`.

Ubuntu install hint:
```bash
sudo apt-get install texlive-latex-extra texlive-fonts-recommended texlive-lang-chinese biber
```

## Style switch

Paper is in **default `article`** format, single-column, 11pt, A4 with 1in margins.
Rough length estimate: ~7-8 pages rendered (within 4-9 page target).

To switch to a specific workshop template, edit the top of `workshop.tex`:

- **NeurIPS 2024 workshop**: replace `\documentclass[11pt,a4paper]{article}` with
  `\documentclass{neurips_2024}` and add `\usepackage[final]{neurips_2024}`.
  Copy `neurips_2024.sty` into this directory.
- **ACL short paper**: `\documentclass[11pt]{article}` + `\usepackage[review]{acl}`.
  Copy `acl.sty` and `acl_natbib.bst` into this directory, and change
  `\bibliographystyle{plainnat}` to `\bibliographystyle{acl_natbib}`.
- **CVPR / ICML**: analogous; see the respective style guide.

## Known TODOs (resolve tomorrow)

Search the `.tex` and `.bib` for `% TODO` (there are ~25 markers). Priority ones:

1. **Pipeline figure** (`\label{fig:pipeline}`). Currently an ASCII placeholder inside
   an `\fbox{...}`. Replace with a real PDF/PNG diagram (e.g., draw in Excalidraw or
   TikZ). The ASCII version is readable but not publication-quality.
2. **Quantitative table** (`tab:quant` in Section 6). All values are `% TODO: fill`.
   Numbers are measurable from `~/Projects/VlogCutter/JushenRenji/output/*.mp4` and
   the run logs in `app.log`. Specifically:
   - End-to-end success rate: count `*_with_cover.mp4` files vs. attempted runs
   - Per-scene success: parse `app.log` for `场景 X/4: ... 生成成功` entries
   - Consistency check pass rate: grep `app.log` for `一致性检查 ... pass=True/False`
   - Upload success: grep for `上传成功` / `upload failed` in distribution logs
3. **Case study table** (`tab:corpus`) — fill in Bilibili BV IDs for HiST-AT, VAG, LAPA;
   verify MultiWorld BV matches the repaired render (not the first pass).
4. **Related-work citations**. Related Work is now synced with
   `docs/related_work.md` (the sibling agent landed it mid-draft). All primary
   anchors (Paper2Video/PaperTalker, Code2Video, TheoremExplainAgent, Manimator,
   DOC2PPT, PresentAgent, arXivisual, Nougat, SciCap, NotebookLM, PaperQA2, Mu Li)
   are cited with real arXiv / URL references. User should still double-check
   author lists and publication venues where marked `% TODO: verify`.
5. **Author block + acknowledgment**. Anonymous for now; add real authors and
   institution credit before camera-ready.
6. **Venue decision**. Pick NeurIPS / ICML / CVPR / ACL workshop and swap the
   style file as described above. Page budget may require trimming Section 5 (Method)
   if a double-column format is chosen.

## Section-by-section status

| Section | Status | Notes |
|---|---|---|
| Abstract | Done | 170 words, within 150-200 target |
| 1 Introduction | Done | Motivation + 4 contribution bullets |
| 2 Related Work | Skeleton (placeholders for 3 refs) | Finalize after `docs/related_work.md` lands |
| 3 System Overview | Done | ASCII pipeline placeholder — need real figure |
| 4 Method | Done | Pseudocode block for consistency loop |
| 5 Method (cont'd) | Done | opencode + manim_skill + safety transforms |
| 6 Experiments | Skeleton (tables have TODOs) | Prose is written; numbers needed |
| 7 Limitations | Done | Includes ethics note |
| 8 Conclusion | Done | ~150 words |
| References | Mostly done | 20 entries; 3 placeholder for paper-to-video prior art |

## Repo location

This directory lives at `~/Projects/VlogCutter/JushenRenji/paper/` on the
`local` branch of `git@github.com:Tigerdwgth/JushenRenji.git`.
