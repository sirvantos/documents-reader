# Stage 2 in detail: extracting data

Nov 12, 2026

## Techniques: six ways to pull facts out of a document

The 2026 default is a language model filling in a short form from the text that Stage 1 produced; the older methods survive as cheap checks and as specialists.

| Technique | How it works, in plain words | Strengths | Weaknesses | Use it for |
| --- | --- | --- | --- | --- |
| 1. Templates and patterns | Fixed positions on the page, or text patterns such as "12 digits" or a date format | Free, instant, never invents anything | Breaks when layout or wording changes | Standard forms; and as automatic checks on the output of other methods |
| 2. Trained field-finder | A small model trained on a few hundred of your own labelled documents to mark where each field is | Copies text from the page, so it cannot invent; fast and cheap to run | Needs labelled examples and retraining when you add fields | Very high volumes of one document type |
| 3. Language model with a form | You describe the fields; the model reads the text and fills them in | No training; handles any layout and wording; understands meaning | Can invent, skip or misplace values; weak on very large forms | The general default |
| 4. Vision model on the page image | The model looks at the page picture and fills the form directly, skipping Stage 1 | Sees stamps, signatures, ticks and layout; one step fewer | Impractical for long documents; harder to trace a value back to its place | Short documents: invoices, certificates, ID pages |
| 5. Multi-step extraction | The model extracts, then checks its own work against the text and re-reads doubtful parts | Better on long documents and long lists | Slower and roughly twice the cost | Long agreements with appendices |
| 6. Purpose-built extraction model | A small model trained only to turn documents into filled forms | Small enough for modest hardware; open versions exist | Less tested outside English; narrower than a general model | Self-hosted setups with limited hardware |

Notes on the evidence:

- For technique 4, a 2025 Fraunhofer study on invoices found that showing the model the page image generally beat converting to text first ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- For technique 5, one vendor prices its multi-step mode at $40 per 1,000 pages against $20 for its standard mode ([source](https://www.dexto.ai/blog/best-document-parsing-apis-for-ai-agents/)).
- For technique 6, NuExtract3 is an open 4-billion-parameter model under the Apache 2.0 licence ([source](https://www.buildmvpfast.com/blog/nuextract3-open-weight-vlm-structured-extraction-self-hosted-2026)). In a medical-document study its predecessor was competitive with open models six to seventeen times larger ([source](https://www.researchgate.net/publication/400065221_Benchmarking_LLM-based_Information_Extraction_Tools_for_Medical_Documents)).

In practice these are combined: technique 3 or 5 does the extraction, and technique 1 checks the result.

## Leading models

Picking named facts out of a document works at roughly 85 to 90% today, including on Russian documents; finding and judging whole clauses is much harder, at around 64% for the best models.

**Russian business documents.** The MWS Vision Bench from MTS AI includes a task where the model fills in fields from Russian documents, contracts among them. Scores run from 0 to 1 ([source](https://github.com/mts-ai/MWS-Vision-Bench), leaderboard as updated July 2026).

| Model | Kind | Public set | Private set |
| --- | --- | --- | --- |
| Cotype Pro 3 (MTS AI) | Commercial, from the benchmark's maker | 0.873 | 0.906 |
| Gemini 3.6 Flash (Google) | Hosted | 0.903 | Not listed |
| Qwen3.6-27B | Open, can run on your own servers | 0.833 | 0.893 |
| GPT-5.5 (OpenAI) | Hosted | 0.873 | Not listed |
| Qwen 3.7 Plus | Hosted | 0.844 | 0.867 |
| GPT-5.6 Sol (OpenAI) | Hosted | 0.867 | 0.862 |
| Claude Fable 5 (Anthropic) | Hosted | 0.843 | Not listed |
| Qwen3.6-35B-A3B | Open | 0.822 | 0.840 |
| Gemma 4 31B (Google) | Open | 0.769 | 0.793 |
| Qwen3.5-9B | Open, small | 0.782 | 0.789 |
| Mistral Large 3 | Hosted or licensed | 0.560 | 0.542 |

The gap between the best hosted models and the best open one is small here, which matters if the documents must stay in-house. The maker's own model leads the private set, so treat that row with some caution.

**Other evidence.**

| Test | What it measures | Result |
| --- | --- | --- |
| ExtractBench (Feb 2026) | Filling forms of 12 to 369 fields from English PDFs | 81 to 87% of fields correct on a 13-field form from long credit agreements; no usable output at all on a 369-field form ([source](https://arxiv.org/html/2602.12247)) |
| ContractEval | Finding risk-relevant clauses in English commercial contracts | Best models about 0.64; open models scored lower and more often wrongly reported that no relevant clause exists ([source](https://arxiv.org/pdf/2508.03080)) |
| OCRBench v2 (Sept 2026 board) | Pulling a named field from a document image | Leading models about 94 out of 100 ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)) |
| Fraunhofer invoice study (2025) | Field accuracy on invoices and receipts | Best model 87 to 97% depending on scan quality ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)) |

What this means: simple, well-defined fields (parties, dates, amounts, numbers) are within reach. Questions that need legal judgement ("is there an unusual penalty clause?") are a different, harder task and should not be promised at the same accuracy.

## Tools

You need two things: a model to do the reading, and a toolkit that feeds it the form, checks the answer and links each value to its source. The toolkits are free; the hosted services bundle both for a price per page.

**Open-source toolkits** (all work with a model on your own servers):

| Toolkit | What it does | Best feature | Limits |
| --- | --- | --- | --- |
| LangExtract (Google, Apache 2.0) | Splits long text, runs the model on the pieces in parallel, and ties every extracted value to its exact position in the source | Source linking is built in; values it cannot locate in the text are marked as such | Works from examples you supply, not a formal field list; takes text only, so Stage 1 must come first |
| Instructor | Sends your field list to the model, checks the reply has the right shape, and retries automatically if not | The most widely used; simple and dependable | No source linking and no confidence scores; text only |
| Outlines | Forces the model's output to follow the form exactly | Guarantees a well-formed result with local models | Well-formed is not the same as correct, and strict forcing can hurt on big forms |
| llmground | A checker that runs after extraction and confirms each value really appears in the document | Needs no AI model and costs nothing to run | Checks presence only, not whether it is the right value for that field |
| NuExtract3 (NuMind, Apache 2.0) | A small open model built only for form-filling from documents and images | Runs on modest hardware | I found no results for it on Russian documents |

Sources: [LangExtract repository](https://github.com/google/langextract) and a [comparison by Nutrient](https://www.nutrient.io/blog/langextract-vs-llamaindex-extraction-comparison/); [Instructor overview](https://developersdigest.tech/tools/instructor) and a [practitioner comparison](https://medium.com/@obielinda/structured-data-extraction-from-any-document-using-llms-without-the-boilerplate-05d5c8dfab6e); [llmground](https://pypi.org/project/llmground/); [NuExtract3](https://www.buildmvpfast.com/blog/nuextract3-open-weight-vlm-structured-extraction-self-hosted-2026).

**Hosted services**, for comparison. Most are ruled out if your documents must stay in Kazakhstan, but three offer versions that run on your own servers.

| Service | Price per 1,000 pages (USD) | Notable | Runs on your own servers? |
| --- | --- | --- | --- |
| Mistral Document AI | $5 | Built on Mistral OCR 4; 170 languages | Yes, as a container |
| LlamaExtract | About $10 (basic) to $31 (multi-step) to $75 (top tier) | Several quality levels | Not found |
| Reducto Extract | $20; $40 for multi-step Deep Extract | A source reference and confidence label for each field | Yes, on its Enterprise plan |
| Azure Document Intelligence, custom extraction | $30 | Train your own field models | Yes, as containers at the same price |
| AWS Textract, forms and tables | About $65 | Mature, widely used | No |

Prices are list prices gathered in September and October 2026 ([Dexto](https://www.dexto.ai/blog/best-document-parsing-apis-for-ai-agents/), [Velrim](https://velrim.com/compare/reducto-vs-llamaextract), [Data Alchemy](https://www.data-alchemy.ai/en/confronto/api-estrazione-dati-documenti), [Startupik](https://startupik.com/document-extraction-api-startup-2026/)). Vendors publish benchmarks in which they each come first, so I have left those scores out.

## Where extraction fails

Extraction rarely fails loudly; it returns a tidy table with a few wrong or missing cells, and the risk grows with the size of the form and the length of the document.

| Failure | What happens | Evidence |
| --- | --- | --- |
| Form too big | Accuracy falls as fields are added, down to nothing usable at several hundred fields | ExtractBench: 0 of 42 attempts produced a usable result on a 369-field form ([source](https://arxiv.org/html/2602.12247)) |
| Long lists | Tables with many rows (line items, schedules) get cut off or lose rows | In the same study, the amount of output required predicted failure better than document length did |
| Tidy but wrong | The output has the right shape, so nothing looks broken | In one category 90% of outputs were well-formed but only 12.5% of fields were correct |
| Invented value | The model fills a field that the document does not contain, often with something typical | The study treats this separately from a missing value because it puts false data into your systems |
| "Not found" when it is there | The model gives up and reports that a clause or field is absent | ContractEval calls this laziness and found it more often in open models ([source](https://arxiv.org/pdf/2508.03080)) |
| Strict format mode backfires | Forcing the model to follow the form exactly can lower accuracy on complex forms | ExtractBench: usable outputs fell from 51% to 37% when strict mode was switched on |
| Main text versus amendments | A later amendment changes a value, and the system reports the old one, or the two disagree | A known problem in contract work; one paper's example is a minimum order of 100 in the agreement and 150 in an addendum ([source](https://arxiv.org/pdf/2601.06164)) |
| Errors inherited from Stage 1 | A misread digit or scrambled table is extracted faithfully | See the Stage 1 tab |

The second-to-last row deserves attention for agreements: supplementary agreements that change price, term or scope are common, so the system must know which document overrides which.

## How to make it reliable

The single most effective rule is that no value enters the table without a quote from the document that a program has confirmed is really there.

| Practice | What to do | Why it works |
| --- | --- | --- |
| 1. Keep forms short | Split the fields into several small forms, one per topic or document section, and run them separately | Accuracy drops as forms grow; a 13-field form is in the range that tested well |
| 2. Define each field precisely | Give a one-line definition, the expected format and one real example per field | Removes guessing about what "contract date" means when there are five dates |
| 3. Allow "not found" | Tell the model that an empty answer is acceptable and expected for absent fields | Removes the pressure to fill every box, which is what produces invented values |
| 4. Demand a quote and a location | For every value, the model must return the exact sentence it came from and where it is | A program can then check that the quote exists in the text; a value with no matching quote is rejected or flagged |
| 5. Add rule checks | Dates are valid and in order, numbers have the right length, amount in words equals amount in digits, parts add up to totals | Catches wrong values that do appear somewhere in the document |
| 6. Extract twice | Run the extraction a second time, or with a second model, and compare | Disagreement is a cheap and reliable signal that a field needs a person |
| 7. Keep the raw value | Store the text exactly as written next to the cleaned-up version (date, number) | The cleaned value is for sorting and totals; the raw one is the evidence |
| 8. Handle amendments as a chain | Extract each document on its own, then combine with a clear rule: the latest signed amendment wins, and the history is kept | Prevents old values surviving after a change |
| 9. Review by risk | People check everything flagged, all high-value fields, and a random sample of the rest | Puts human time where an error would cost most |

Sources: practices 1 and 3 follow from [ExtractBench](https://arxiv.org/html/2602.12247); practice 4 from work on grounded extraction ([SafePassage](https://arxiv.org/html/2510.00276v1), [LangExtract](https://github.com/google/langextract), [llmground](https://pypi.org/project/llmground/)); practice 8 from the [amendment conflict example](https://arxiv.org/pdf/2601.06164). The rest are standard practice and my own recommendation.

Two cautions:

- A quote check proves the value is in the document, not that it is in the right field. The buyer's name is a genuine quote even when it has been placed in the supplier field. Practices 5 and 6 cover that gap.
- Do not switch on strict format mode for large forms without testing it; it lowered accuracy in the one independent test.

## Your case: Russian-language agreements for Kazakhstan's railways

One open model on your own server can probably do both the reading and the extraction, and a starter set of about 30 fields in six short forms is a sensible first target.

**Model.** Qwen3.6-27B is the strongest open model on the Russian field-extraction test (0.83 to 0.89) and is also on the Stage 1 shortlist for reading. Using it for both stages means one model to install and maintain. It fits on a single 24 GB graphics card when compressed, or an 80 GB card at full quality (see the Stage 1 tab for hardware). A smaller option, Qwen3.5-9B, scores about 0.78. The same uncertainty about Kazakh-language text applies here as in Stage 1.

**Toolkit.** LangExtract for source-linked extraction or Instructor for simple form-filling, plus a quote checker such as llmground. All run locally.

**A starter field list.** This is my proposal, to be corrected by the people who work with these agreements. Each group is one short form.

| Form | Fields |
| --- | --- |
| 1. Identity | Agreement number; date signed; place signed; type of agreement; registration number if any |
| 2. Parties | Full name of each party; BIN of each; role (customer, supplier, contractor); signatory name and position; basis of authority (charter, power of attorney and its number) |
| 3. Subject and scope | Short description of goods, works or services; delivery or performance location; list of appendices |
| 4. Money | Total amount in digits; total amount in words; currency; VAT included or not; payment terms; advance payment share |
| 5. Dates and term | Start date; end date; delivery or completion deadlines; renewal terms |
| 6. Liability and legal | Penalty rate for delay; penalty cap; warranty period; governing law; dispute venue; termination conditions |

Separately, for each party: bank name, account number and bank code. And for the document as a whole: whether signatures and stamps are present on the signing page, which Stage 1 can report.

**Agreement-specific rules to build in.**

- Amount in words must equal amount in digits; a mismatch goes to a person.
- A BIN has 12 digits; anything else is flagged.
- End date after start date; signing date not after start date unless the text says so.
- Each supplementary agreement is extracted on its own and linked to its parent by agreement number, with the latest one overriding earlier values.
- Where the agreement is in two languages, extract from the Russian text and keep the Kazakh text as a cross-check for numbers and dates.

**What to keep out of the first version.** Legal-judgement questions, such as whether a clause is unusual or risky, score far lower than plain field extraction in tests. Add them later as a separate, clearly labelled aid for lawyers, not as table columns people will trust like dates.

## How to choose and test

Test extraction on the output of your real Stage 1 reader, count wrong, missing and invented values separately, and decide per field whether the result is good enough to use without review.

**A test plan in six steps**

1. Take the same 50 agreements used for the Stage 1 test and have a person fill in the starter forms by hand. This is the answer key.
2. Run each candidate model and toolkit on the text your Stage 1 reader produced, not on clean text, so the test reflects the whole chain.
3. Score each field as correct, wrong, missing (in the document but not extracted) or invented (extracted but not in the document).
4. Look at the results per field, not only overall. Dates and numbers may be near-perfect while payment terms are not.
5. Check how many of the wrong and invented values your safeguards caught: quote check, rule checks, second run.
6. Set a rule per field: accept automatically, accept if checks pass, or always review.

**How many documents.** Fifty is enough to compare tools and find weak fields. For a figure you can quote with confidence, one guide estimates about 400 documents for accuracy within 5 percentage points either way ([source](https://sygnet.ai/blog/benchmarking-llm-contract-review-accuracy-efficiency)). You can reach that gradually: the first months of reviewed production output become the larger test set.

**What to compare, for your situation.**

| Choice | Options | How to decide |
| --- | --- | --- |
| Model | Qwen3.6-27B compressed; Qwen3.6-27B full quality; a smaller Qwen | Start with the compressed 27B on a 24 GB card; move up only if the test shows a clear gain |
| Toolkit | LangExtract; Instructor with a separate quote checker | Whichever gives your reviewers the clearer click-to-source view |
| One step or two | Extract once; or extract, then verify and re-read doubtful fields | Use two steps for long agreements with many appendices if single-pass misses fields |
| Input | Text from Stage 1; or the page image for the signing page | Use the image where stamps, signatures and handwritten dates matter |

## Sources

- [ExtractBench paper](https://arxiv.org/html/2602.12247) (Feb 2026): accuracy versus form size, failure types, strict format mode
- [MWS Vision Bench](https://github.com/mts-ai/MWS-Vision-Bench) (MTS AI, updated Jul 2026): field extraction on Russian business documents
- [ContractEval paper](https://arxiv.org/pdf/2508.03080): clause-level results and the "no related clause" failure
- [OCR Benchmarks 2026](https://invoicedataextraction.com/blog/ocr-benchmarks) (Oct 2026): OCRBench v2 extraction scores, Fraunhofer invoice study
- [LangExtract repository](https://github.com/google/langextract) and [Nutrient comparison](https://www.nutrient.io/blog/langextract-vs-llamaindex-extraction-comparison/): source-linked extraction
- [Instructor overview](https://developersdigest.tech/tools/instructor) and [practitioner comparison](https://medium.com/@obielinda/structured-data-extraction-from-any-document-using-llms-without-the-boilerplate-05d5c8dfab6e)
- [llmground](https://pypi.org/project/llmground/): checking that extracted values exist in the source
- [NuExtract3 overview](https://www.buildmvpfast.com/blog/nuextract3-open-weight-vlm-structured-extraction-self-hosted-2026) and [medical-document study](https://www.researchgate.net/publication/400065221_Benchmarking_LLM-based_Information_Extraction_Tools_for_Medical_Documents)
- [SafePassage paper](https://arxiv.org/html/2510.00276v1): grounding extracted values in evidence
- [Contract2Plan paper](https://arxiv.org/pdf/2601.06164): conflicts between agreements and addenda
- Prices: [Dexto](https://www.dexto.ai/blog/best-document-parsing-apis-for-ai-agents/) (Oct 2026), [Velrim](https://velrim.com/compare/reducto-vs-llamaextract), [Data Alchemy](https://www.data-alchemy.ai/en/confronto/api-estrazione-dati-documenti) (Sep 2026), [Startupik](https://startupik.com/document-extraction-api-startup-2026/)
- [Sygnet: benchmarking contract review](https://sygnet.ai/blog/benchmarking-llm-contract-review-accuracy-efficiency): test-set size

I worked from search summaries for most of the tool and price pages, and read the ExtractBench paper and the MWS Vision Bench page in full. The field list and agreement rules are my own proposal, not taken from a source.
