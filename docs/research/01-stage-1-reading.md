# Stage 1 in detail: reading documents

Nov 12, 2026

## Techniques: four ways to read a document

The 2026 default is a small, specialised AI reader that looks at each page as a picture; older pipelines and large general AI models each still have a niche.

| Technique | How it works, in plain words | Strengths | Weaknesses | Use it for |
| --- | --- | --- | --- | --- |
| 1. Direct text extraction | Copies the text already stored inside a digital PDF; no AI | Instant, free, exact characters | Fails on scans; loses tables and reading order | First pass on PDFs exported from Word or accounting systems |
| 2. Multi-step pipeline | Separate tools in a row: find blocks on the page (layout), read the letters (OCR), rebuild tables, then put it all in order | Predictable; each step can be checked and swapped | Errors pile up from step to step; struggles with complex layouts and formulas | Toolkits such as Docling and Marker; audit-heavy work |
| 3. Specialised AI reader (end-to-end) | One small vision-language model (about 1 to 3 billion parameters) looks at the page image and writes clean text, tables and headings directly | Top accuracy on public tests; cheap to run on your own servers | Can occasionally invent text, because it generates rather than copies | The best general default today |
| 4. Large general AI model | Hand the page to GPT, Gemini or Claude and ask it to transcribe | No setup; can also reason about the content | Lower parsing scores than specialised readers; far more expensive per page | Small volumes, or when you also want questions answered from the same call |

The main risk with techniques 3 and 4 is that they can make up text. ThoughtWorks' 2026 Technology Radar notes this and suggests a hybrid or classic OCR where errors are not tolerable ([source](https://www.thoughtworks.com/radar/techniques/vision-language-models-for-end-to-end-document-parsing)). A practical guard is to ask for confidence scores and position boxes for every block, so a person can check doubtful parts against the image.

### How to guard against invented text

No setting switches this off, so the fix is layers of independent checks, with a person reviewing only what the checks flag.

**What the problem looks like.** Classic OCR fails visibly: it produces gibberish that anyone can spot. An AI reader fails quietly, with text that looks correct. Three forms are documented:

- **Silent substitution.** An unusual value is swapped for a more typical one. This hits numbers, codes and names hardest (contract numbers, amounts, bank details), because the model cannot guess them from context the way it can guess ordinary words ([source](https://www.llamaindex.ai/blog/llm-ocr)).
- **Silent rewriting.** When the page itself has a typo or damaged word, readers tend to write the "corrected" version, not what is printed. An Amazon study of 15 systems found this across general and specialised AI readers ([source](https://www.alphaxiv.org/abs/2607.21617.md)). For a legal text, the printed wording is what counts.
- **Skipped or repeated passages.** The reader stops early, or loops on the same lines. Classic OCR does neither ([source](https://www.llamaindex.ai/blog/llm-ocr)).

Poor scans make all three more likely ([source](https://lacuna.tiptreesystems.com/work/teaching-vlms-to-admit-uncertainty-in-ocr-from-lossy-visual-inputs/wrk_51cd26531ed708cc87be64aba788e3b9)).

**The safeguards, from cheapest to most thorough.**

| Safeguard | How it works | What it catches |
| --- | --- | --- |
| 1. Use the digital text when it exists | If the PDF already contains its text, copy it and skip AI reading for those pages | Everything on those pages: nothing is generated, so nothing can be invented |
| 2. Scan well | 300 dots per inch or more, straight, good contrast | Reduces the damaged input that triggers guessing |
| 3. Second reader | Run a classic OCR engine on the same page and compare the two texts automatically. Where they differ, flag it. For numbers and names, prefer the classic result when it is confident | Substitutions, skipped and repeated passages. The two kinds of reader make different kinds of mistakes, so agreement is a strong sign, though not proof |
| 4. Rule checks | Automatic tests on the output: dates are real dates, ID numbers have the right length, line items add up to the total, the amount in words matches the amount in digits | Wrong numbers and dates |
| 5. Page sanity checks | Compare text length with what the page should hold; look for the same line repeated; look for letters from the wrong alphabet in a Russian page | Loops, skipped sections, off-script output |
| 6. Confidence scores | Ask the reader for a score per block and send low scores to review. First measure on your own pages how well the scores match real errors | Doubtful regions such as text under stamps |
| 7. Click-to-source review | Every block keeps its position on the page, so a reviewer clicks a value and sees that spot in the scan | Makes human checking take seconds per item |
| 8. Spot audits | A person fully checks a random sample each month, including pages nothing flagged | Errors that slip past every automatic check; shows whether quality is drifting |

Sources for the table: [Edge of Context OCR guide](https://slavadubrov.com/blog/2026/03/04/ocr-guide/) (digital text first, second reader, rule checks, calibrating confidence); [OCR vs VLM hybrid](https://dev.to/kesimo/ocr-vs-vlm-why-you-need-both-and-how-hybrid-approaches-win-5bo4) (which reader wins on numbers and names); [DocuPipe](https://www.docupipe.ai/blog/preventing-ai-hallucinations-visual-review) (click-to-source review); [Inria study](https://arxiv.org/pdf/2605.27750) (repetition and off-script output); [LlamaIndex](https://www.llamaindex.ai/glossary/sealed-or-notarized-document-ocr) (scan resolution).

**For agreements specifically**, I would treat safeguards 1, 3, 4 and 7 as the minimum:

- The second reader matters most for contract numbers, amounts, dates and bank details, where one wrong character changes the meaning.
- The words-versus-digits check on amounts is a free, strong test that agreements happen to offer.
- Keep the scanned image as the record of truth. The extracted text is a working copy for search and extraction, never a replacement for the signed original.

What remains after all of this is a small rate of errors in ordinary prose, where two readers can agree on the same wrong word. The spot audits in row 8 are how you learn how large that rate is for your documents.

## Leading models

On the main public test, the six best readers are all small specialised models scoring 95 to 97; the best general AI models trail by 3 to 10 points.

Scores below are from the maintainers' own OmniDocBench v1.6 leaderboard, read on 12 November 2026 ([source](https://github.com/opendatalab/OmniDocBench)). The score combines text, table and formula accuracy, 0 to 100, higher is better. The test pages are English and Chinese only.

| Model | Type | Size (parameters) | Score | Worth knowing |
| --- | --- | --- | --- | --- |
| OXR-1.0 | Specialised reader | 1.3B | 97.03 | Current leader; also tops the open olmOCR-Bench board (self-reported) |
| [TeleOCR](https://huggingface.co/StarDoc-AI/TeleOCR) | Specialised reader | 1.2B | 96.91 | Best table score on the board; added September 2026 |
| [OvisOCR2](https://huggingface.co/ATH-MaaS/OvisOCR2) | Specialised reader | 0.8B | 96.47 | Smallest of the top group; best reading order; added September 2026 |
| PaddleOCR-VL-1.6 (Baidu) | Specialised reader | 0.9B | 96.34 | Apache 2.0 licence; 109 languages including Russian; best formula score |
| [MinerU2.5-Pro](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) (OpenDataLab) | Specialised reader | 1.2B | 95.75 | Comes from the benchmark's own lab; custom licence with conditions for large companies |
| [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR) (Zhipu) | Specialised reader | 0.9B | 95.22 | MIT-style licence; good with formulas |
| Ovis2.6-30B-A3B | General open model | 30B | 93.70 | Best general-purpose model on the board |
| Gemini 3 Pro (Google) | General hosted model | Not disclosed | 92.91 | Best closed model on the board |
| GPT-5.2 (OpenAI) | General hosted model | Not disclosed | 86.59 | Below many 1 to 3B open readers |
| olmOCR (Allen Institute) | Specialised reader | 7B | 85.74 | Fully open, English-focused |
| Mistral OCR | Hosted reader | Not disclosed | 85.66 | This is the March 2025 version; Mistral reports 93.07 for OCR 4, with no benchmark version named |
| Marker | Multi-step pipeline | Pipeline | 78.44 | Version 1.8.2, before the Marker 2 rewrite |

Claude has no row on this board. Licences above are from [Codesota](https://www.codesota.com/tasks/document-ocr) and [Particula](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser); check the rest before commercial use.

**Read these scores with care.**

- The test is weighted towards academic papers, textbooks and Chinese-English publishing. It contains no invoices, receipts or forms, and formulas make up a third of the score ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- The top six are within 1.8 points of each other, so on your documents the order may well change.
- On the English-only olmOCR-Bench, other names lead: Chandra 2 at 85.8 and Mistral OCR 4 at 85.2 are both self-reported by their makers, and Ai2's own olmOCR 2 scores 82.4 ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).

### Hardware to run them locally

The small specialised readers run on one ordinary graphics card (GPU) with 12 to 24 GB of memory; only the large general models need data-centre hardware.

The figure that matters is GPU memory (VRAM). All of these need an NVIDIA GPU for practical speed.

| Model | GPU memory needed | Example hardware | Reported speed | Source of the figures |
| --- | --- | --- | --- | --- |
| PaddleOCR-VL-1.6 (0.9B) | About 2 GB for the model itself; 10 to 12 GB when served for many pages at once | A 12 GB card (RTX 3060) works; 24 GB is comfortable | 0.5 pages per second on an RTX 3060; 1.1 to 1.4 on a data-centre A100 | Baidu's own tests for version 1.5; Baidu says 1.6 is the same speed |
| GLM-OCR (0.9B) | About 3 GB for the model; 4 to 6 GB typical, about 10 GB when served at volume | 12 GB card or better | About 1.9 pages per second (maker's figure) | Maker and deployment guides |
| MinerU2.5-Pro (1.2B) | 8 GB or more | 12 to 24 GB card; also runs on Apple Silicon Macs | About 1.0 page per second on an A100 | MinerU release notes; Baidu's comparison table |
| DeepSeek-OCR 2 (3B) | About 20 GB | 24 GB card | Not found | One deployment guide |
| Qwen3.6-27B, full quality | About 61 GB | One 80 GB data-centre GPU (A100 or H100), or two 32 GB cards | Not found for document reading; expect far slower per page than a 1B reader | GPU-sizing tools and community model pages |
| Qwen3.6-27B, compressed to 4-bit | 16 to 19 GB | One 24 GB card (RTX 3090 or 4090) | Not found | Same; compression can cost some accuracy, so test it |
| Mistral OCR 4, self-hosted | Not published | One GPU, one container | Up to 2,000 pages per minute on a single GPU (Mistral's claim, GPU type not stated) | Trade press; ask Mistral for the exact specification |
| OXR-1.0, TeleOCR, OvisOCR2 | Not found | Similar in size to PaddleOCR-VL (0.8 to 1.3B), so probably the same class | Not found | My inference from model size, not verified |

Sources: [PaddleOCR-VL setup and benchmarks](https://paddleocr.dev/paddleocr-vl) and the [PaddleOCR-VL-1.5 paper](https://www.researchgate.net/publication/400237357_PaddleOCR-VL-15_Towards_a_Multi-Task_09B_VLM_for_Robust_In-the-Wild_Document_Parsing); [memect-ppx serving notes](https://pypi.org/project/memect-ppx/0.0.2/) (10 GB and 20 GB serving figures); [GLM-OCR deployment guide](https://apidog.com/blog/glm-ocr-document-understanding/); [MinerU release notes](https://github.com/FoxInField/MinerU); [Qwen3.6-27B sizing](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen3.6-27B/) and [Qwen hardware guide](https://llmhardware.io/guides/qwen3-hardware-requirements); [Mistral OCR 4 throughput](https://aibusiness.com/generative-ai/mistral-ai-tackles-unstructured-data-challenge-ocr-4).

**What to buy, in practice.**

| Stage | Machine | What it covers |
| --- | --- | --- |
| Pilot and testing | One workstation with a 24 GB NVIDIA card (RTX 3090 or 4090 class), 16 or more processor cores, 32 to 64 GB of memory, fast disk | Any of the small readers, and the compressed Qwen3.6-27B, so you can compare all shortlisted tools on one machine |
| Production with a small reader | One server with a 24 to 48 GB GPU, plus a second for backup | At 0.5 to 1.4 pages per second, roughly 40,000 to 120,000 pages a day if run around the clock |
| Production with Qwen3.6-27B at full quality | A server with an 80 GB data-centre GPU | Needed only if the large model clearly wins your test |

One published PaddleOCR-VL setup was tested on a 24 GB GPU with a 16-core processor and 16 GB of memory ([source](https://github.com/Ghost-141/PaddleOCR-VL-Deployment/blob/main/README.md)); the larger memory I suggest above is my own margin. The pages-per-day range is my arithmetic from Baidu's speed figures.

Three things to keep in mind:

- **Memory needs depend on settings.** The model itself is small; most of the 10 to 12 GB is working space for handling many pages at once, and it can be turned down.
- **Without a GPU** these readers run, but much too slowly for volume. The classic OCR engine used as a second reader is the exception: it runs well on ordinary processors.
- **Speed figures are the makers' own**, measured on clean benchmark pages. Dense contract pages with tables will be slower.

## Hosted services

Hosted readers cost from about $1.50 to $65 per 1,000 pages; the newer AI-based services are among the cheapest, and the big cloud providers among the most expensive.

| Service | Price per 1,000 pages (USD) | Strengths | Watch out for |
| --- | --- | --- | --- |
| Mistral OCR 4 | $4; $2 in batch; $5 with form-filling | 170 languages; returns position boxes, block types and confidence scores; can also run on your own servers in one container | Headline scores are Mistral's own |
| Reducto | About $5 to $20 | Output shaped for search: chunking and layout-aware extraction | Price depends on volume and features |
| Azure Document Intelligence | $1.50 (text only) to $50 (custom) | Over 140 languages; produces Markdown directly | Tables and forms tier costs $10 |
| AWS Textract | $1.50 (text only) to $15 for tables and forms, plus $25 per question type | Mature forms and receipts tooling | Costs add up quickly; limited Asian-language support |
| Google Document AI | $30 to $65 | Good form parser | Most expensive of the large clouds |
| Mathpix | About $5 to $15 | The specialist for formulas (outputs LaTeX) | Mainly English and maths |
| Mindee | Priced per document | Ready-made invoice, receipt and ID readers that return named fields | A field extractor rather than a general reader |

Mistral prices are from its OCR 4 launch in June 2026 ([source](https://dev.to/damogallagher/mistral-ocr-4-brings-self-hosted-document-ai-to-rag-pipelines-3ce2)); the rest are list prices compiled by Codesota in April 2026 ([source](https://www.codesota.com/tasks/document-ocr)). Prices change often, so check each vendor's page before budgeting.

For comparison, Codesota estimates that running an open reader such as PaddleOCR-VL on a rented GPU costs around $0.03 to $0.10 per 1,000 pages in compute, before staff time ([source](https://www.codesota.com/tasks/document-ocr)). It puts the break-even point for self-hosting at roughly 1 million pages a month.

## Open-source toolkits

A toolkit is the ready-made software around a reader: it opens files, splits pages, runs the models and writes Markdown or JSON. Docling, Marker and MinerU are the three most used, and the licence often decides between them before accuracy does.

| Toolkit | Made by | Best at | Speed and accuracy | Licence |
| --- | --- | --- | --- | --- |
| Docling | IBM | Complex tables; many input formats; links into common search frameworks | 50.3% on olmOCR-Bench at 2.1 pages per second, in Datalab's test | Permissive: MIT code, permissive model weights |
| Marker 2 | Datalab | Fast bulk conversion of PDF, Word, PowerPoint, Excel and e-books to Markdown | 76.0% at 2.9 pages per second, in Datalab's own test | Apache 2.0 code, but its models need a paid licence above $5M yearly revenue |
| MinerU 4 | OpenDataLab | Formulas, scientific papers, Chinese, Japanese and Korean text | 72.7% at 0.54 pages per second (classic mode); its AI-reader mode scores higher | Apache-based with extra terms: paid licence above 100M monthly users or $20M monthly revenue |

Speed and accuracy figures come from Marker's own benchmark harness, so treat them as a vendor comparison ([source](https://gmagazine.it.com/?p=566)). Licence details are from [Particula](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser) and the same release coverage. On formulas, one guide found Docling and Marker below 70% on complex maths, where MinerU did better ([source](https://www.spheron.network/blog/self-host-document-intelligence-docling-marker-mineru-rag-guide/)).

Toolkits and models are not either-or: MinerU, for example, can run its own MinerU2.5-Pro reader from the models table instead of its classic pipeline.

## Where readers still fail

The 95+ scores are earned on clean digital pages; on photos, long documents and less common languages, even the best readers lose several points, and open models on average lose up to a fifth of their score.

| Test (2026) | What it changes | What happened |
| --- | --- | --- |
| PureDocBench | The same 1,475 pages in clean, digital and real-world (printed, photographed) versions | Scores fell 3.3 points on digital copies and 11.6 points on real-world copies, on average; best overall score 79.7 out of 100 across 58 models |
| Real5-OmniDocBench | The benchmark's own pages rebuilt as scans, warped pages, screen photos, bad lighting and skew | PaddleOCR-VL-1.6 fell from 96.3 to 93.2; Gemini 3 Pro scored 89.2 |
| MDPBench | Photographed documents in 17 languages | Open models lost 17.8% on average on photos, and 14.0% on non-Latin scripts |
| MPDocBench-Parse | Whole multi-page documents instead of single pages | Tables and text cut by a page break, and heading levels, were mostly reconstructed wrongly; the leader scored 80.8 |

Sources: [OCR Benchmarks 2026](https://invoicedataextraction.com/blog/ocr-benchmarks) for the first three rows; [BenchmarkList](https://benchmarklist.com/benchmarks/mpdocbench_parse/) for the last.

Other known weak spots:

- **Tables vary most between readers.** On olmOCR-Bench, table scores ranged from 60.6 to 92.1 across leading tools, a much wider spread than their overall scores ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- **Handwriting** mixed with print remains the main differentiator; printed text is largely solved ([source](https://www.codesota.com/tasks/document-ocr)).
- **Headers and footers.** Some readers are trained to drop page headers and footers as noise. On invoices, that is often where the invoice number, tax ID and bank details are ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- **Invented text.** AI readers generate their output, so they can occasionally write words that are not on the page ([source](https://www.thoughtworks.com/radar/techniques/vision-language-models-for-end-to-end-document-parsing)).

## Your case: Russian-language agreements for Kazakhstan's railways

For Russian agreements the famous leaderboard is no guide, the data probably has to stay in Kazakhstan, and the shortlist changes to three tools you can run on your own servers.

**1. The main leaderboard contains no Russian.** OmniDocBench pages are tagged English, Simplified Chinese or mixed, and nothing else ([source](https://github.com/opendatalab/OmniDocBench)). A score of 96 there says how well a reader handles English and Chinese pages, not Cyrillic ones.

**2. What Russian-specific evidence exists.**

| Test | What it covers | What it shows | Limits |
| --- | --- | --- | --- |
| MWS Vision Bench (MTS AI) | 800 Russian business images, contracts included; 2,580 questions | Page-to-structured-text scores top out around 0.75 to 0.78 out of 1, so a quarter of the content is still lost or misplaced (the scoring differs from OmniDocBench, so the numbers are not directly comparable). Open Qwen3.6 models (27B and 35B) are at or near the top for this task, level with the best paid models | Tests only large general AI models; none of the small specialised readers has been run on it. The maintainer's own Cotype models rank high |
| MDPBench | 17 languages including Russian; digital and photographed pages | Gemini 3 Pro leads overall at 86.4 and is best in 14 of 17 languages; the best open reader scores 80.5 and PaddleOCR-VL-1.5 scores 78.3 | I could not open the per-language table, so I have no Russian-only figure |

Sources: [MWS Vision Bench](https://github.com/mts-ai/MWS-Vision-Bench) (leaderboard as updated July 2026); [MDPBench summary](https://benchmarklist.com/benchmarks/mdpbench/) and [paper summary](https://www.emergentmind.com/papers/2603.28130).

On the same Russian test, pulling named fields out of a document scores higher than converting whole pages: the best models reach 0.87 to 0.91 on field extraction. For agreements where you need parties, dates and amounts, that is encouraging.

**3. Kazakh text is the least-tested part.** If your agreements carry Kazakh alongside Russian, note that Kazakh adds nine letters to the Russian alphabet (Ә, Ғ, Қ, Ң, Ө, Ұ, Ү, Һ, І). The only public Kazakh reading tests I found are built from computer-generated images, not real documents ([source](https://github.com/Allessyer/awesome-kaz-datasets)). Treat every reader's Kazakh accuracy as unknown until you test it.

**4. Where the documents may be processed.** Kazakhstan's law requires personal data of its citizens to be stored in the country, and the Informatization Law extends localisation rules to state and quasi-state organisations ([source](https://amcham.kz/wp-content/uploads/2026/05/2026-05-15_AmCham_DataLocalization_Issue-Brief_ENG_v5.pdf)). Agreements contain signatories' names and often ID details. This is not legal advice, but plan on running the reader inside Kazakhstan unless your legal and security teams confirm otherwise. That rules out most hosted services in the earlier table.

**5. Shortlist for a test, all self-hosted.**

| Candidate | Why it is on the list | What to check |
| --- | --- | --- |
| PaddleOCR-VL-1.6 | Small, Apache 2.0 licence, lists Russian among 109 languages, and has built-in recognition of seals and stamps | Real accuracy on Russian and Kazakh; no independent Russian score exists |
| Qwen3.6-27B (or 35B) | Best open model on the Russian business-document test | Needs a much larger GPU than a 1B reader; confirm the licence terms |
| Mistral OCR 4, self-hosted container | 170 languages; returns confidence scores and marks signature blocks; vendor support | Paid licence; all its scores are Mistral's own |

PaddleOCR-VL details are from [Roboflow](https://roboflow.com/blog/best-open-source-ocr-models) and its [1.5 paper](https://arxiv.org/pdf/2601.21957); Mistral details from the [OCR 4 coverage](https://dev.to/damogallagher/mistral-ocr-4-brings-self-hosted-document-ai-to-rag-pipelines-3ce2).

A cheap first step before any AI reader: where you still have the original Word or digital PDF of an agreement, take the text from that file and use the scan only for the signed and stamped pages.

**6. What to put in your 50-page test.** These are the places I would expect agreements to break, so include several of each:

- Pages where a round stamp or signature sits on top of printed text. Stamp ink over text is a known cause of misread characters ([source](https://www.llamaindex.ai/glossary/sealed-or-notarized-document-ocr)).
- Two-column pages with Kazakh on one side and Russian on the other, to see whether the reader keeps the columns apart.
- Numbered clauses several levels deep (1.1, 1.1.1), since heading structure is a general weak spot.
- Appendices with price or specification tables that run over several pages.
- Amounts written in digits and in words, dates, contract numbers, BIN and bank details: check them character by character.
- Old or faxed scans and phone photos, if you receive any.

## How to choose and test

Shortlist two or three candidates for your situation, then let a test on your own documents decide.

| Your situation | Shortlist | Why |
| --- | --- | --- |
| Want to start this week, documents may go to the cloud | Mistral OCR 4, Reducto | Modern AI readers, no servers to run, low price per page |
| Confidential documents, must stay in-house | PaddleOCR-VL, GLM-OCR, Mistral OCR 4 self-hosted | Top-ranked open readers with permissive licences, or a vendor model in your own container |
| Millions of pages a month | PaddleOCR-VL or another top open reader on your own GPUs | Compute cost per page is a small fraction of hosted prices |
| Already contracted with Microsoft, Amazon or Google | Azure Document Intelligence, AWS Textract, Google Document AI | Contracts, security review and access control are already in place |
| Invoices, receipts, ID documents | Mindee, Azure prebuilt invoice, AWS Textract forms, plus one open reader | Ready-made field extractors ship fastest; compare against a general reader |
| Scientific papers and formulas | Mathpix, MinerU, GLM-OCR | Strongest formula output |
| Many languages or non-Latin scripts | Mistral OCR 4, PaddleOCR-VL, Azure | Widest language coverage; test on photographed pages too |

Shortlist based on [Codesota's decision guide](https://www.codesota.com/tasks/document-ocr) and the scores and licences above.

**A test plan in six steps**

1. Collect 50 real pages, including your worst: phone photos, faxes, multi-page tables, stamps and handwriting.
2. For each page, write down what a correct result looks like, at least the key values and one table.
3. Run every candidate on the same pages, without telling reviewers which output came from which tool.
4. Score what you actually need: are the key values exactly right, are table rows intact, are headers and footers kept?
5. Check that each output gives position boxes and confidence scores, so people can verify doubtful parts quickly.
6. Work out the cost for your monthly volume, including staff time if you self-host.

Two practical tips from Codesota: require position boxes if you will ever need to show where a value came from, and store results by a fingerprint of each page so repeated uploads are not paid for twice ([source](https://www.codesota.com/tasks/document-ocr)).

## Sources

- [OCR Benchmarks 2026: What Each Measures and Who Leads](https://invoicedataextraction.com/blog/ocr-benchmarks) (21 Oct 2026): OmniDocBench v1.6 and olmOCR-Bench scores, PureDocBench, Real5-OmniDocBench, MDPBench, benchmark caveats
- [Codesota: OCR and Document Parsing APIs 2026](https://www.codesota.com/tasks/document-ocr) (prices checked Apr 2026): hosted prices, self-hosting costs, licences, decision guide, test advice
- [MPDocBench-Parse leaderboard](https://benchmarklist.com/benchmarks/mpdocbench_parse/) (Jul 2026): multi-page parsing
- [ThoughtWorks Technology Radar: VLMs for end-to-end document parsing](https://www.thoughtworks.com/radar/techniques/vision-language-models-for-end-to-end-document-parsing) (Apr 2026): pipeline versus end-to-end, invented-text risk
- [Mistral OCR 4 brings self-hosted document AI to RAG pipelines](https://dev.to/damogallagher/mistral-ocr-4-brings-self-hosted-document-ai-to-rag-pipelines-3ce2) (Jun 2026): Mistral OCR 4 prices
- [Marker 2 vs MinerU, Docling and LiteParse](https://gmagazine.it.com/?p=566): toolkit speed and accuracy from Datalab's harness
- [Particula: Docling vs MinerU vs Marker](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser) (Sep 2026): toolkit licences
- [Spheron: Self-host Docling, Marker and MinerU](https://www.spheron.network/blog/self-host-document-intelligence-docling-marker-mineru-rag-guide/) (May 2026): toolkit strengths

Added for the Russian and Kazakh section:

- [OmniDocBench repository](https://github.com/opendatalab/OmniDocBench) (read 12 Nov 2026; first 100,000 characters of the page): v1.6 leaderboard, page languages
- [MWS Vision Bench](https://github.com/mts-ai/MWS-Vision-Bench) (MTS AI, updated Jul 2026): Russian business-document results
- [MDPBench summary](https://benchmarklist.com/benchmarks/mdpbench/) and [paper summary](https://www.emergentmind.com/papers/2603.28130): 17-language results
- [Awesome Kazakh datasets](https://github.com/Allessyer/awesome-kaz-datasets): available Kazakh reading tests
- [AmCham Kazakhstan issue brief on data localisation](https://amcham.kz/wp-content/uploads/2026/05/2026-05-15_AmCham_DataLocalization_Issue-Brief_ENG_v5.pdf) (May 2026): localisation rules for state and quasi-state bodies
- [Roboflow: Best open-source OCR models](https://roboflow.com/blog/best-open-source-ocr-models) and [PaddleOCR-VL-1.5 paper](https://arxiv.org/pdf/2601.21957): languages, seal recognition
- [Mistral OCR 4 block types](https://dev.to/aarhamforensics_eb3c024eb/mistral-ocr-4-the-ai-technology-rebuilding-document-ingestion-21mo): signature blocks, confidence scores
- [LlamaIndex: sealed or notarized document OCR](https://www.llamaindex.ai/glossary/sealed-or-notarized-document-ocr): stamps over text

Most figures are self-reported by vendors or compiled by blogs; only benchmark-maintainer leaderboards are independent, and even those contain no business documents.
