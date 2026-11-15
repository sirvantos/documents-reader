# Document Extraction and Search: A Plain-Language Guide

Nov 12, 2026 · @Vladimir Altukhov

## The short answer

The best current setup is a four-stage pipeline: read each document once with an AI document reader, extract key facts into a table, make everything searchable, and let an AI model answer questions with links to the source pages.

- **Read:** use a modern AI reader, not classic OCR. It understands tables, columns and headings, not only letters.
- **Extract:** let a language model fill in a short form per document, then check the result with simple rules and a human for doubtful cases.
- **Search:** combine keyword search and meaning-based search, then let a second model re-sort the top results.
- **Answer:** the AI answers only from the pages it found and shows where each fact came from. For hard questions it searches several times, like a researcher.

No tool is accurate on every document, so the most important step is testing on your own files before choosing anything.

## The big picture

Every document system, whatever the vendor calls it, does the same four jobs in the same order.

&#91;embedded content: document pipeline · 4 stages, 2 outputs\]

The two highlighted boxes are the things people actually use: a table of facts and answers to questions. Reading happens once and feeds both.

A library is a useful comparison. Reading is the clerk who unpacks new books and types up damaged pages. Extraction is the catalogue card with author, year and subject. Search is the librarian who knows which shelf to go to. Answering is a research assistant who reads those pages and gives you a summary with page numbers.

## Stage 1: Reading the documents

Everything later depends on this step: if the reader garbles a table, no search or AI model can repair it afterwards.

**What changed.** Classic OCR recognised letters one by one and often lost the page structure. Modern readers are small AI models that look at the whole page like a person does. They return clean text with headings, tables and reading order kept intact.

**What the evidence says.**

- Small specialised readers now beat large general AI models at this job. On the main public test (OmniDocBench v1.6), the top five are all compact specialised models scoring 95 to 97 out of 100, while GPT-5.2 scores 86.6 ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- Clean pages flatter everyone. On a test that uses printed and photographed versions of the same pages (PureDocBench), scores fall by about 12 points on average ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- Long documents are still hard. Tables that continue across pages and the heading structure of a long report are often reconstructed wrongly, even by the best readers ([source](https://benchmarklist.com/benchmarks/mpdocbench_parse/)).

**The practical choice** is between two routes:

| Route | Examples | Choose it when |
| --- | --- | --- |
| Hosted service (you send pages, get text back) | Mistral OCR, Reducto, Azure Document Intelligence | You want to start quickly and documents may leave your network |
| Open model on your own servers | PaddleOCR-VL, MinerU, GLM-OCR | Documents are confidential, or volume is high enough that per-page fees add up |

One industry overview suggests starting hosted and moving in-house only when scale or compliance requires it ([source](https://codesota.com/browse/vision-documents/document-ocr)).

Techniques, model scores, prices and a test plan: Stage 1 in detail

## Stage 2: Extracting data into a table

Extraction works well today when the form is short, and fails when you ask for hundreds of fields at once.

**How it works.** You describe the facts you want as a form: supplier name, date, total, contract end date. A language model reads the document and fills in the form. No templates per layout are needed, so a new supplier's invoice works without setup.

**What the evidence says.**

- Short forms work. In an independent test (ExtractBench), the four models able to accept such long files filled a 13-field form from credit agreements of 100 to 200 pages with 81 to 87% of fields correct ([source](https://arxiv.org/html/2602.12247)).
- Huge forms break. With a 369-field financial form, none of the six models tested produced a usable result, on any document ([source](https://arxiv.org/html/2602.12247)).
- A result that looks tidy can still be wrong. In one category 90% of outputs were well-formed, yet only 12.5% of fields passed ([source](https://arxiv.org/html/2602.12247)).
- For short documents such as invoices, a 2025 Fraunhofer study found that showing the model the page image directly generally beat converting to text first. Its best model reached 87 to 97% field accuracy depending on document quality ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).

**What to do with that.**

- Split big forms into several small ones, by section of the document.
- Add automatic checks: do line items add up to the total, is the date valid, does the tax number have the right length.
- Keep a link from every extracted value to the page it came from, so a person can verify it in seconds.
- Send doubtful or high-value items to a human. One wrong digit in a total is a wrong total, not a 99% correct one.

Techniques, model scores, tools, safeguards and a starter field list for agreements: Stage 2 in detail

## Stage 3: Making documents searchable

The current standard is hybrid search with a reranker: two kinds of search run together, and a second model re-sorts the best results.

Documents are first cut into passages of a few paragraphs, because a search should return the relevant part, not a 200-page file. Then several techniques work together:

| Technique | In plain words | Good at | Weak at |
| --- | --- | --- | --- |
| Keyword search | Finds passages containing the exact words | Invoice numbers, names, product codes | Questions worded differently from the document |
| Meaning-based search | Finds passages about the same idea, even in other words | "What is our policy on late payment?" | Exact codes and numbers |
| Hybrid search | Runs both and merges the lists | Nearly everything; the sensible default | Still returns some irrelevant passages |
| Reranker | A careful second reader that re-sorts the top 20 to 50 results | Pushing the truly relevant passage to the top | Adds a small delay |
| Context labels | A sentence added to each passage saying which document and section it is from | Passages that make no sense alone ("revenue grew 3%": whose?) | Costs a little at setup time |
| Filters | Narrowing by date, client or document type using the fields from Stage 2 | "Only 2025 contracts with client X" | Needs Stage 2 done well |
| Visual page search | Searches pictures of pages instead of text | Slides, charts, scans with complex layout | Needs far more storage; still need a reader to get text out |

**What the evidence says.**

- Practitioner guides agree that meaning-based search alone misses exact identifiers, and that combining it with keyword search is consistently better than either alone ([source](https://www.callmissed.com/blog/rag-best-practices-2026), [source](https://dev.to/nexmind_ai/rag-in-production-in-2026-beyond-naive-chunk-and-embed-3803)).
- In Anthropic's tests, adding context labels to hybrid search cut failed searches by 49%. Adding a reranker on top cut them by 67%, from 5.7% of searches to 1.9% ([source](https://anthropic.com/research/contextual-retrieval)).
- Visual page search matched or beat text-based search on visually rich documents, but it only finds the page. You still need Stage 1 to get the text out ([source](https://mixpeek.com/guides/visual-document-retrieval)).

How search works step by step, models for Russian, engines, and a setup for agreements: Stage 3 in detail

## Stage 4: Answering questions

Use simple one-step answering by default, and switch on the multi-step "agent" mode only for questions that need it.

**One-step answering (called RAG).** Think of an open-book exam. The system searches once, hands the best passages to an AI model, and the model answers using only those passages, with links to each source. It is fast and cheap, and it suits direct questions such as "What is the notice period in the Acme contract?"

**Multi-step answering (agentic search).** Here the AI behaves like a researcher. It reads the question, searches, judges whether the results are enough, and searches again with better wording. This helps with questions that span several documents, such as "How did our payment terms change across all 2025 supplier contracts?" The price is time and cost: one reference puts a typical multi-step request at over 10 seconds and roughly ten times the cost of a single search ([source](https://www.envisioning.com/vocab/agentic-retrieval)). A common pattern is to answer in one step by default and escalate only when the question needs it ([source](https://aiagentrank.io/glossary/agentic-rag)).

**Knowledge graphs (GraphRAG).** The system builds a map of people, companies and how they relate, then uses it to answer "connect the dots" questions. It is worth adding only when testing shows it clearly improves the questions you care about; it is not an automatic upgrade ([source](https://www.cognee.ai/graphrag-vs-rag)).

**No search at all.** For a small set of documents you can skip stages 3 and 4 and give the files straight to an AI model. Anthropic notes this is often the simplest solution for small collections, while larger ones need search ([source](https://anthropic.com/research/contextual-retrieval)).

Whichever mode you use, two rules keep answers trustworthy: every answer shows its source pages, and the model is allowed to say "not found in the documents".

How an answer is produced step by step, safeguards, models, tools and a setup for agreements: Stage 4 in detail

## Which approach fits which situation

Most teams need only the first three rows; the rest are add-ons for specific problems.

| Your situation | What to use | Why |
| --- | --- | --- |
| A few dozen documents, occasional questions | Give the files directly to an AI assistant | A pipeline is not worth building at this size |
| Invoices, forms or contracts where you need the same facts from each | Stages 1 and 2: reader, short form, automatic checks, human review | The goal is a reliable table, not a chat |
| Thousands of mixed documents that staff ask questions about | Stages 1, 3 and 4: reader, hybrid search with reranker, answers with sources | The proven default |
| Questions that need comparing many documents | Add multi-step (agentic) answering | One search cannot gather everything |
| Many scans, photos, slides or charts | Test readers on your worst pages first; consider visual page search | Benchmark scores on clean pages do not carry over |
| Questions about relationships (who is linked to whom) | Trial a knowledge graph on real questions | Helps this question type, costs more to build |
| Documents that must not leave the company | Open models on your own servers for every stage | Strong open readers exist; you pay in setup effort |

## Recommended setup, step by step

Start narrow, measure, then widen. Steps 1 to 3 need no engineering and decide most of the outcome.

1. **Pick one document type and one goal.** For example: supplier invoices into a spreadsheet, or questions about contracts.
2. **Build a test set by hand.** Take 50 to 100 real documents, including the ugly ones, and write down the correct answers. This is the yardstick for every later choice.
3. **Compare two or three readers** on that test set. Look at tables and scans first; that is where they differ most.
4. **Add extraction** with short forms, automatic checks and a link back to the source page.
5. **Add search:** hybrid search, a reranker, and context labels on each passage.
6. **Add answering** with mandatory source links and permission to say "not found".
7. **Put a person in the loop** for doubtful and high-value items, and re-run the test set after every change.
8. **Only then consider add-ons:** multi-step answering, visual page search, a knowledge graph. Add one at a time and keep it only if the test set improves.

## Common mistakes and how to check quality

The most common mistake is choosing tools from published scores instead of testing on your own documents.

- **Trusting leaderboards.** Many published scores are reported by the model's own maker, and the same model can show three different numbers depending on test version. The main reading benchmarks contain no invoices or business forms at all ([source](https://invoicedataextraction.com/blog/ocr-benchmarks)).
- **Saving money on the reader.** Errors made in Stage 1 flow into every later stage.
- **Using meaning-based search alone.** It misses exact codes, numbers and names.
- **Asking for everything in one giant form.** Accuracy collapses as the form grows.
- **Answers without sources.** If people cannot check an answer in one click, they either stop trusting the system or trust it too much.
- **No measurement.** Without a test set, nobody can tell whether a change helped.

Three numbers are enough to track quality:

| Measure | Question it answers |
| --- | --- |
| Field accuracy | Of the extracted values, how many are exactly right? |
| Search hit rate | For test questions, how often is the right passage in the top results? |
| Answer correctness | Is the final answer right, and does its source really say so? |

## Glossary

| Term | Meaning |
| --- | --- |
| OCR | Software that turns a picture of text into text characters |
| Language model (LLM) | An AI that reads and writes text, such as Claude, GPT or Gemini |
| Vision-language model | A language model that can also look at images of pages |
| Parsing | Turning a PDF or scan into clean, structured text |
| Schema | The list of fields you want extracted; a blank form |
| Chunk | A passage of a document, usually a few paragraphs |
| Embedding / vector search | The technique behind meaning-based search |
| BM25 | The standard method behind keyword search |
| Hybrid search | Keyword and meaning-based search combined |
| Reranker | A model that re-sorts search results by true relevance |
| RAG | Search first, then let the AI answer from what was found |
| Agent / agentic | An AI that plans and takes several steps on its own |
| Knowledge graph | A map of things and the relationships between them |
| Hallucination | An AI stating something that is not in the source |

## Sources

- [OCR Benchmarks 2026: What Each Measures and Who Leads](https://invoicedataextraction.com/blog/ocr-benchmarks) (Oct 2026): OmniDocBench v1.6 leaderboard, PureDocBench, Fraunhofer invoice study, caveats on self-reported scores
- [MPDocBench-Parse leaderboard](https://benchmarklist.com/benchmarks/mpdocbench_parse/) (Jul 2026): multi-page parsing weaknesses
- [ExtractBench paper](https://arxiv.org/html/2602.12247) (Feb 2026): extraction accuracy versus form size
- [Anthropic: Introducing Contextual Retrieval](https://anthropic.com/research/contextual-retrieval): context labels, hybrid search and reranking results
- [Codesota: OCR and Document Parsing](https://codesota.com/browse/vision-documents/document-ocr): hosted versus self-hosted readers
- [RAG Best Practices in 2026](https://www.callmissed.com/blog/rag-best-practices-2026) and [RAG in Production in 2026](https://dev.to/nexmind_ai/rag-in-production-in-2026-beyond-naive-chunk-and-embed-3803): hybrid search and reranking practice
- [Mixpeek: Visual Document Retrieval](https://mixpeek.com/guides/visual-document-retrieval) (May 2026): page-image search
- [Envisioning: Agentic Retrieval](https://www.envisioning.com/vocab/agentic-retrieval) and [AI Agent Rank: Agentic RAG](https://aiagentrank.io/glossary/agentic-rag): multi-step answering, cost and speed
- [Cognee: GraphRAG vs RAG](https://www.cognee.ai/graphrag-vs-rag) (Jul 2026): when a knowledge graph is worth it

Several sources are vendor or practitioner blogs; the benchmark figures come from the two benchmark pages and the ExtractBench paper.
