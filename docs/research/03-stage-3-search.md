# Stage 3 in detail: making documents searchable

Nov 13, 2026

## How search works

Search has two phases: a preparation done once per document, and a chain of quick steps run every time someone asks a question.

**Preparation, once per document**

1. Cut the text from Stage 1 into passages (see the section on cutting below).
2. Attach a label to each passage: which agreement, which parties, which section.
3. Build a keyword index: a list of which words occur in which passage, like the index at the back of a book.
4. Build a meaning index: a small model turns each passage into a list of numbers (an "embedding") so that passages about similar things get similar numbers.
5. Store the fields from Stage 2 (dates, parties, type, amount) next to each passage, to be used as filters.

**At question time**

&#91;embedded content: search at question time · 2 searches, 1 merged list\]

Filters narrow the pool first ("only 2025 agreements with supplier X"). The two searches then each return their best 50 or so passages, the lists are merged, and a reranker reads the question against each candidate and puts the best handful on top. Those go to Stage 4, where the AI writes the answer.

Every model in this chain is small, so by my estimate the search takes a fraction of the time the AI then spends writing the answer.

## Techniques

The proven combination is keyword search plus meaning-based search, merged and then reranked; for Russian, the keyword side needs one extra step that English does not.

| Technique | In plain words | Strengths | Weaknesses | Verdict |
| --- | --- | --- | --- | --- |
| 1. Keyword search (the standard method is called BM25) | Finds passages containing the words of the question, favouring rare words | Exact numbers, names, codes; fast; needs no AI model | Misses different wording | Always include |
| 2. Word-form handling for Russian | Reduces each word to its dictionary form before indexing, so "договор", "договора" and "договору" count as one word | Essential for languages with many word endings | Needs a Russian dictionary tool; Kazakh support is weaker | Always include for Russian |
| 3. Meaning-based search | A small model turns text into numbers; similar meaning gives similar numbers | Finds the right passage even when the wording differs; tolerant of small reading errors | Weak on exact identifiers; needs a model that knows Russian well | Always include |
| 4. Hybrid merge | Runs 1 and 3 and joins the two lists, usually by a simple method that rewards passages ranked high in either | Better than either alone | Still lets some irrelevant passages through | The default |
| 5. Reranker | A second small model reads the question together with each of the top 50 candidates and re-sorts them | Usually the biggest single quality gain | Adds some delay; general rerankers can misjudge legal text | Include, but test on your documents |
| 6. Context labels | A line added to each passage before indexing: which agreement, parties, section | Rescues passages that mean nothing alone ("the Supplier shall pay 0.1% per day") | Extra work at preparation time | Include |
| 7. Filters | Narrow by date, party, type or amount using Stage 2 fields | Exact and cheap; removes whole classes of wrong answers | Only as good as Stage 2 | Include |
| 8. Question rewriting | An AI rephrases or splits the question before searching | Helps vague or multi-part questions | Adds noise to short, specific questions | Later, if needed |
| 9. Visual page search | Searches images of pages | Charts, slides, drawings | Heavy storage; little benefit for text agreements | Not needed for agreements |

**What the evidence says.**

- On a Russian search benchmark of 17 datasets (RusBEIR), plain keyword search was a strong baseline, and its authors stress that handling word forms properly matters a great deal for Russian. Keyword search plus a reranker performed about as well as the best meaning-based models alone, and a meaning-based model plus a reranker did best overall ([source](https://www.themoonlight.io/en/review/building-russian-benchmark-for-evaluation-of-information-retrieval-models), [follow-up paper](https://arxiv.org/html/2511.05079v1)).
- In Anthropic's tests, context labels with hybrid search cut failed searches by 49%, and by 67% with a reranker added ([source](https://anthropic.com/research/contextual-retrieval)).
- One 2026 study of legal documents found that a general-purpose reranker made results worse, not better ([source](https://arxiv.org/html/2610.26313)). That is one study, but it is the reason the reranker row says "test".
- For Kazakh, a retrieval benchmark built from Kazakh Wikipedia found that reducing words to their stems outperformed multilingual meaning-based models ([source](https://github.com/Allessyer/awesome-kaz-datasets)). Keyword search with good word-form handling may matter even more for Kazakh text than for Russian.

## Cutting documents into passages

For agreements, cut along the document's own structure, one clause per passage; in a legal study that measured it, this mattered more than the choice of search method.

**Why it matters.** The common shortcut is to cut every 500 words or so regardless of content. That splits clauses in half and glues unrelated ones together, and the search then returns fragments.

**What the evidence says.**

- A 2026 study on legal documents compared structure-based cutting with the naive kind on an independent benchmark of 6,858 questions. Structure-based cutting found 83% more of the relevant text. In its breakdown for one of the five document sets, the cutting method accounted for 88% of the total improvement and the choice of search method for almost none ([source](https://arxiv.org/html/2610.26313)).
- A study on oil-and-gas company documents found the same direction: structure-aware cutting gave the best results and cost less to compute than AI-based "semantic" cutting ([source](https://arxiv.org/pdf/2603.24556)).

**Rules for agreements.** These combine the studies above with my own recommendations.

| Rule | What to do | Why |
| --- | --- | --- |
| One clause, one passage | Cut at numbered clauses (5.2, 5.2.1), not at a word count | The clause is the unit people ask about |
| Keep the path | Store the full position with each passage: agreement, section title, clause number | Lets the answer cite "clause 5.2 of agreement N" |
| Add the label | Prefix each passage with agreement number, parties and date | The clause text alone rarely says whose agreement it is |
| Tables stay whole | Keep a table as one passage, with its heading row; split very long tables by groups of rows and repeat the heading | A row without its column names is meaningless |
| Definitions travel | Where a clause uses a defined term, attach the definition or a pointer to it | "The Services" means nothing without it |
| Small to find, large to read | Search on the single clause, but hand Stage 4 the clause plus its neighbours or the whole section | Precise search, enough context for the answer |
| Appendices and amendments | Treat each as its own document linked to the parent, and mark superseded clauses | Stops old terms being returned as current |

This depends on Stage 1 keeping headings and clause numbers intact, which is one of the known weak spots of document readers. Check it in the Stage 1 test.

## Leading models

Search needs two small models, one for meaning-based search and one for reranking. Good open ones exist for Russian, and all are small enough to run on a laptop.

**Models for meaning-based search** (called embedding models). Scores are from the Russian benchmark ruMTEB, which averages 23 tasks, search among them; higher is better.

| Model | Size (parameters) | Russian score | Worth knowing |
| --- | --- | --- | --- |
| Qwen3-Embedding-8B | 7.6B | 71.4 | Highest of the general open models; too large for casual use |
| FRIDA (ai-forever, Sber) | 0.8B | 71.0 | Built for Russian; nearly matches the model nine times its size. MIT licence. Accepts at most 512 word-pieces per passage and is not designed for Kazakh |
| Qwen3-Embedding-4B | 4.0B | 70.1 | Over 100 languages |
| GigaEmbeddings (Sber, 2024) | About 2.5B | 69.1 | Built for Russian; a newer 2026 Giga-Embeddings family reports the top Russian score |
| Qwen3-Embedding-0.6B | 0.6B | 64.3 | Smallest; noticeably weaker on Russian |
| BGE-M3 (BAAI) | 0.6B | Not in this table | The multilingual workhorse; see below |

Scores are from the Giga-Embeddings paper's comparison table ([source](https://arxiv.org/pdf/2608.23806)) and the earlier GigaEmbeddings paper ([source](https://arxiv.org/pdf/2510.22369)). Both come from Sber's own team, so treat the ordering between Sber and other models with some care.

On search specifically, the RusBEIR benchmark adds two findings ([source](https://arxiv.org/html/2511.05079v1)):

- BGE-M3 and multilingual-E5-large were the best single models overall, and BGE-M3 with a reranker was the best combination.
- On longer texts, the Russian-tuned models FRIDA and USER-BGE-M3 consistently beat the multilingual ones.

BGE-M3 has two practical advantages for agreements: it accepts long passages (about 8,000 word-pieces, where older models cut off at around 500), and one model produces both the meaning numbers and a keyword-style signal. It is Apache 2.0 licensed and fits on any GPU with 8 GB ([source](https://www.spheron.network/blog/self-host-embedding-reranker-tei-gpu-cloud/)).

**Rerankers.**

| Model | Size | Licence | Worth knowing |
| --- | --- | --- | --- |
| BGE Reranker v2-m3 (BAAI) | 0.6B, about 2.5 GB of memory | Apache 2.0 | The most widely used open reranker; multilingual; the safe default |
| Qwen3-Reranker | 0.6B, 4B or 8B; about 2 GB to 8 GB for the first two | Apache 2.0 | Over 100 languages; can be given instructions about what counts as relevant |
| Jina Reranker v3 | 0.6B | Recent Jina rerankers are licensed for non-commercial use; commercial use is paid | Best score among rerankers on the standard English benchmark, by Jina's own figures |
| Cohere Rerank 4 | Hosted | Paid service | Often ranked first, but your text would leave your network |

Sources: [Mixpeek ranking](https://mixpeek.com/curated-lists/best-rerankers), [Future AGI comparison](https://futureagi.com/blog/best-rerankers-for-rag-2026/), [Jina's announcement](https://jina.ai/news/jina-reranker-v3-0-6b-listwise-reranker-for-sota-multilingual-retrieval), [Spheron](https://www.spheron.network/blog/self-host-embedding-reranker-tei-gpu-cloud/) for memory figures.

I found no reranker results measured on Russian legal text, and no results at all for Kazakh. Both need your own test.

## Search engines you can run yourself

At the scale of an agreement archive, every option below is fast enough; choose by what your team already runs and by how well the engine handles Russian word forms.

| Engine | What it is | Hybrid search | Strengths | Weaknesses |
| --- | --- | --- | --- | --- |
| PostgreSQL with pgvector | The common open database, with an add-on for meaning-based search | Yes, by combining its built-in text search with pgvector | One system for the Stage 2 table, the filters and the search; nothing new to operate if you already use Postgres | Slower than dedicated engines at very large scale; hybrid needs some setup |
| Qdrant | A dedicated search engine for meaning-based search | Built in | Lightest on memory in one benchmark; runs as a single container; strong filtering | Check how well its keyword side handles Russian word forms |
| Weaviate | A dedicated engine with keyword search built in | Built in, and often rated best at it | Easy hybrid search | More memory than Qdrant |
| OpenSearch or Elasticsearch | Mature keyword search engines that have added meaning-based search | Built in | The strongest keyword search, with Russian language handling available; rich filtering | Heavier to run and tune |
| Milvus | A dedicated engine built for billions of items | Built in | Very large scale | Several components to operate; more than an agreement archive needs |

Sources: a 2026 benchmark of the four dedicated options ([Computing for Geeks](https://computingforgeeks.com/qdrant-weaviate-milvus-pgvector/)), and comparisons by [Encore](https://encore.dev/articles/best-vector-databases), [Firecrawl](https://www.firecrawl.dev/blog/best-vector-databases) and [Redis](https://redis.io/blog/best-open-source-vector-databases-comparison/). All are open-source and free to run; licences are Apache 2.0 or similarly permissive, except that Elasticsearch's licence terms vary.

**How big is your problem?** By my rough arithmetic, 20,000 agreements of 30 pages each come to around one to two million passages. One comparison places pgvector's comfortable range at millions of items and the dedicated engines at hundreds of millions ([source](https://encore.dev/articles/best-vector-databases)). So scale does not decide this for you.

**What should decide it.**

- If the Stage 2 table will live in PostgreSQL anyway, keeping search there too is the simplest setup.
- If nobody on the team runs a database yet, Qdrant is the easiest dedicated engine to start with.
- If keyword precision in Russian and Kazakh turns out to be the weak point in testing, OpenSearch gives the most control over word-form handling.

## Where search fails

Search fails quietly: it always returns something, and a wrong passage looks as confident as a right one. Most failures trace back to preparation, not to the search step itself.

| Failure | What happens | Guard |
| --- | --- | --- |
| Exact identifiers missed | Meaning-based search returns passages about the right topic but not the one with agreement number КТЖ-2025/147 | Keyword search in the mix; filters on Stage 2 fields |
| Word forms missed | Keyword search for "поставка" misses "поставки" and "поставку" | Reduce words to dictionary form when indexing and when searching |
| Boilerplate flood | Hundreds of agreements share identical standard clauses, so the top results are the same clause from many agreements | Filter by agreement or party first; group results by agreement; show one hit per agreement |
| Superseded terms returned | The search finds the original price clause, not the amendment that replaced it | Mark superseded clauses during preparation; prefer the latest in the chain |
| Split or glued clauses | A passage holds half a clause, or two unrelated ones | Cut by structure (see above) |
| Passage too long for the model | Older meaning-search models silently ignore everything after about 500 word-pieces | Use a model that accepts long input, such as BGE-M3; keep passages to one clause |
| Reading errors from Stage 1 | A misread word no longer matches the keyword | Meaning-based search tolerates small errors better; fix at the source |
| Reranker misjudges legal text | A general reranker pushes the right clause down | Measure with and without it before switching it on |
| Stale index | New or amended agreements are not yet searchable | Index as part of intake, not as a separate periodic job |

The long-input and reranker rows come from the [RusBEIR work](https://arxiv.org/html/2511.05079v1) and the [legal chunking study](https://arxiv.org/html/2610.26313). The boilerplate and superseded-terms rows are my own expectation for an archive of similar agreements; I have no study for them, so check them early in your test.

## Your case: Russian-language agreements for Kazakhstan's railways

Everything in this stage runs comfortably on the MacBook you have for a pilot, because the search models are about fifty times smaller than the language model from Stage 2.

**A starting setup.**

| Part | Suggested choice | Fallback or alternative |
| --- | --- | --- |
| Cutting | One clause per passage, with agreement number, parties, date and section path attached | — |
| Context label | Built from Stage 2 fields by simple rules, no AI needed | A one-sentence AI-written summary per passage, once you have a server |
| Keyword search | Standard keyword search with Russian dictionary-form handling | Add Kazakh handling if testing shows a gap |
| Meaning search | BGE-M3 | FRIDA, which did better on longer Russian texts |
| Merge | The standard rank-based merge | — |
| Reranker | BGE Reranker v2-m3 | Qwen3-Reranker-0.6B; or none, if the test shows it hurts |
| Engine | PostgreSQL with pgvector if you use Postgres; otherwise Qdrant | OpenSearch if keyword precision becomes the issue |
| Filters | Party, BIN, agreement type, date range, amount range, in force or superseded | Whatever else Stage 2 extracts |

**Hardware.** BGE-M3 and the reranker each need 2 to 3 GB of memory and run on a laptop. On your 36 GB MacBook they fit alongside the compressed Qwen3.6-27B. Preparing the index is a one-off job per document; for a 50-agreement pilot I would expect minutes, not hours, though I have no measured figure for your machine.

**Questions the search should handle well.** Use these as the seed of your test set.

- "Agreement КТЖ-2025/147": an exact identifier, which tests keyword search and filters.
- "What is the penalty for late delivery in the agreement with supplier X?": one agreement, one clause, different wording from the text.
- "Which agreements with supplier X end in 2026?": really a filter question, answered from the Stage 2 table more than from text search.
- "Where do we allow advance payment above 30%?": needs both the table and clause text across many agreements.
- A question in Kazakh about a Russian-language agreement, if staff will ask that way.

**Two things specific to your archive.**

- Many questions about agreements are table questions in disguise. If the answer is a date, a party or an amount, the Stage 2 table answers it exactly, and text search is the wrong tool. Stage 4 should try the table first.
- Standard templates mean identical clauses across hundreds of agreements. Decide early whether a search result is "a clause" or "an agreement", and group accordingly.

## How to choose and test

Build a list of real questions with the correct passage marked for each, then add one technique at a time and keep it only if the numbers improve.

**The test set.** Collect 50 to 100 questions that staff really ask, across the types listed above. For each, a person marks which clause in which agreement answers it. This takes a day or two and is reused for every later decision.

**Two numbers to track.**

| Measure | Plain meaning | Why it matters |
| --- | --- | --- |
| Hit rate in the top 5 | For what share of questions is the correct passage among the first five results? | Stage 4 only sees the top few; if the passage is not there, the answer cannot be right |
| Position of the first correct result | On average, how far down is the right passage? | Shows whether the reranker is helping |

**The order to test in.**

1. Keyword search alone, with word-form handling. This is the baseline.
2. Meaning-based search alone.
3. Both merged.
4. Add the reranker.
5. Add context labels.
6. Add filters for the questions that name a party, date or type.

Record both numbers after each step. A step that does not improve them is left out, however standard it is. In particular, check step 4 carefully, given the one study where a reranker hurt legal search.

**Also compare,** once the chain works: BGE-M3 against FRIDA for step 2, and clause-level cutting against a naive fixed-size cut, to confirm the structure work is paying off on your documents.

Look at the failures by hand. Ten wrong results read by a person usually point to one fixable cause, such as a clause split in the wrong place or a missing word form.

## Sources

- [RusBEIR: Russian retrieval benchmark, summary](https://www.themoonlight.io/en/review/building-russian-benchmark-for-evaluation-of-information-retrieval-models) and the [Wikipedia-based follow-up](https://arxiv.org/html/2511.05079v1) (Nov 2025): keyword versus meaning-based search in Russian, model comparison
- [Giga-Embeddings paper](https://arxiv.org/pdf/2608.23806) (Aug 2026) and [GigaEmbeddings paper](https://arxiv.org/pdf/2510.22369): ruMTEB scores
- [StrucChunk: structure-aware retrieval for legal documents](https://arxiv.org/html/2610.26313) (Oct 2026): cutting by structure, reranker caveat
- [Chunking strategies in oil and gas enterprise documents](https://arxiv.org/pdf/2603.24556) (2026)
- [Anthropic: Introducing Contextual Retrieval](https://anthropic.com/research/contextual-retrieval): context labels, hybrid search, reranking
- [Awesome Kazakh datasets](https://github.com/Allessyer/awesome-kaz-datasets): Kazakh retrieval benchmark note
- Rerankers: [Mixpeek](https://mixpeek.com/curated-lists/best-rerankers), [Future AGI](https://futureagi.com/blog/best-rerankers-for-rag-2026/), [Jina](https://jina.ai/news/jina-reranker-v3-0-6b-listwise-reranker-for-sota-multilingual-retrieval)
- [Spheron: self-hosting embeddings and rerankers](https://www.spheron.network/blog/self-host-embedding-reranker-tei-gpu-cloud/) (2026): model sizes and memory
- Engines: [Computing for Geeks benchmark](https://computingforgeeks.com/qdrant-weaviate-milvus-pgvector/), [Encore](https://encore.dev/articles/best-vector-databases), [Firecrawl](https://www.firecrawl.dev/blog/best-vector-databases), [Redis](https://redis.io/blog/best-open-source-vector-databases-comparison/)

I worked from search summaries of these pages, not full readings. The ruMTEB scores come from Sber's own papers. The starting setup, the failure rows marked as mine, and the test order are my recommendations.
