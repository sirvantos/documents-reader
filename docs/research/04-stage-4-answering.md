# Stage 4 in detail: answering questions

Nov 14, 2026

## How answering works

Stage 4 turns a person's question into a written answer that rests only on your documents and shows where each statement comes from.

&#91;embedded content: answering a question · 2 kinds of evidence, 1 checked answer\]

1. **Choose the route.** The system decides what kind of question this is. "Which agreements with supplier X end in 2026?" is answered from the Stage 2 table. "What is the penalty for late delivery?" needs the clause text from Stage 3. Many questions need both.
2. **Fetch the evidence.** A table lookup returns exact rows; a text search returns the best few clauses, each with its agreement number and clause number.
3. **Write the answer.** A language model receives three things: instructions ("answer only from the evidence below, cite each statement, say so if the answer is not there"), the evidence, and the question. It writes a short answer.
4. **Check the sources.** A program confirms that every quote in the answer really appears in the passage it cites, and that every number matches the table or the text.
5. **Show the result.** The person sees the answer, the quoted clauses, and links to the pages they came from.

The language model is used once, in step 3, and sometimes in step 1. Everything else is ordinary software. Most of the quality comes from what is put in front of the model, which is why Stages 1 to 3 matter so much.

## Techniques

Start with two routes, a table lookup for facts and a one-step text answer for clauses, and add the heavier techniques only when the test shows a need.

| Technique | In plain words | Strengths | Weaknesses | Verdict |
| --- | --- | --- | --- | --- |
| 1. One-step text answer (known as RAG) | Search once, give the model the top clauses, it writes the answer | Fast, cheap, easy to check | Fails when the answer is spread over many documents | The default for clause questions |
| 2. Table lookup | The question becomes a query on the Stage 2 table: filter, count, sort, sum | Exact; can count and total across thousands of agreements | Only as good as Stage 2; free-form query writing by AI is error-prone | The default for fact questions |
| 3. Table then text | The table narrows to the right agreements, then text search runs inside them | Handles "penalty terms in all 2025 supply agreements with X" | Two steps to get right | Include |
| 4. Asking back | When the question is ambiguous, the system asks which agreement or period is meant | Prevents confident answers to the wrong question | One more turn for the user | Include |
| 5. Multi-step search (agentic) | The model searches, reads, decides what is missing, searches again | Comparisons and questions that need several pieces | Much slower and costlier; harder to check | Later, for the hard questions only |
| 6. Whole-document reading | Give the model one or two full agreements instead of passages | Summaries; "compare these two agreements" | Slow on small hardware; does not scale to an archive | For single-agreement tasks |
| 7. Knowledge graph | A map of parties, agreements and their links, queried directly | "Which suppliers are linked through the same guarantor?" | Costly to build; your table already holds most links | Not needed at first |

**What the evidence says.**

- **Numbers belong to the table.** In one 2026 study of generated financial memos, the share of exactly correct numbers was 54% with no documents, 88% with text search, 98% with an added checking step, and 100% when the numbers came from structured data ([source](https://www.researchgate.net/publication/408508115_Retrieval_Evidence_Quality_Prediction_for_RAG_Hallucination_Detection_with_LLM-Derived_Semantic_Features)). It is one study from a small journal, but it matches the logic: a number looked up cannot be misread.
- **Letting AI write database queries freely is not yet reliable.** On the main public test (BIRD), the best system gets 83% of queries right against 93% for human specialists, and results on real company databases are much lower ([source](https://count.co/ai/text-to-sql), [source](https://www.onvo.ai/blog/text-to-sql-accuracy-in-2026-the-performance-cliff-nobody-mentions)). Your case is far easier than those tests, with one table of about 30 columns. Even so, the safer design is for the model to fill in a fixed set of filters (party, type, date range, amount range, status), not to write queries from scratch.
- **Multi-step search costs about ten times more.** One reference puts a typical multi-step request at over 10 seconds and roughly ten times the cost of a single search on a large hosted model ([source](https://www.envisioning.com/vocab/agentic-retrieval)). On a laptop the gap in waiting time would be larger.

## Keeping answers trustworthy

Giving the model your documents reduces invented answers but does not eliminate them; trust comes from a set of checks around the model, not from the model.

**What the evidence says.**

- **Search-based tools still invent.** A Stanford and Yale study tested commercial legal research tools built this way. They gave false or misleading answers to between 17% and 33% of questions, against 43% for a general chatbot ([source](https://reglab.stanford.edu/?p=3154), [summary](https://www.llrx.com/2026/02/what-the-science-says-about-hallucinations-in-legal-research/)). The tools were tested in 2024, and the task was open legal research, which is harder than questions about your own agreements. The direction still holds: better, not solved.
- **Instructions help.** In a 2026 biomedical study, telling the model to use only the supplied passages and to flag missing evidence kept answers at about 0.90 out of 1 on a faithfulness score, whichever search method was used ([source](https://arxiv.org/pdf/2605.02520)). A separate study found answers were more faithful when the model was made to cite its sources ([source](https://www.mdpi.com/2076-3417/16/6/3013)).
- **The model believes what it is given.** When small models were handed a passage containing a planted wrong fact, 60% of their answers repeated it ([source](https://arxiv.org/pdf/2608.22228)). For you this means a superseded clause or a misread number passed up from earlier stages will be reported as fact.
- **Models are poor at saying "not found".** The same paper cites a benchmark where models correctly declined less than half the time when the documents did not contain the answer. This behaviour has to be tested, not assumed.
- **Models differ a lot.** On one public leaderboard of faithfulness to a given document, error rates across models ranged from about 2% to 24% ([source](https://www.elitecontentmarketer.com/ai-hallucination-statistics/)).

**The safeguards.**

| Safeguard | What to do | What it catches |
| --- | --- | --- |
| 1. Evidence-only instruction | Tell the model to answer only from the supplied passages and table rows | Answers from the model's general knowledge |
| 2. A source for every statement | Each sentence of the answer must point to a passage or a table row | Unsupported claims become visible |
| 3. Quote check | A program confirms each quoted phrase appears word for word in the passage cited | Invented or altered quotes; needs no AI |
| 4. Numbers from the table | Dates, amounts and counts are inserted from the Stage 2 table, not typed by the model | Misread digits |
| 5. Permission to decline | "Not found in the documents" is an accepted answer, and is shown plainly | Guessing when the evidence is missing |
| 6. Premise check | Instruct the model to check what the question assumes: "the 2024 agreement with X" may not exist | Agreeing with a wrong assumption, which the Stanford study names as a distinct error type |
| 7. Current terms only | Search excludes superseded clauses unless history is asked for | Old terms presented as current |
| 8. Click to source | Every source opens the scanned page at the right place | Lets people verify in seconds |
| 9. Second reader | For high-stakes answers, a second model run checks each statement against the passages | Subtle misreadings; doubles the time |

**Two security rules.**

- **Permissions are enforced in the search, not in the instructions.** If a user may not see an agreement, its passages must never be retrieved for them. Telling the model "do not reveal" is not a control ([source](https://wavect.io/blog/rag-permissions-sharepoint-confluence-drive/), [source](https://tianpan.co/blog/2026-05-04-permission-aware-retrieval-enterprise-rag-access-control)).
- **Text inside documents is data, not instructions.** A document can contain a sentence written to steer an AI. This is called prompt injection, and security guides rank it as the top risk for these systems ([source](https://www.okta.com/identity-101/how-to-secure-rag-workflows/)). The risk is low for signed agreements, but keep a log of which passages were used for each answer.

## Leading models

This is the stage where a larger model helps most, yet the open model you can run locally is within a few points of the best hosted ones on Russian document questions.

**Answering questions about Russian documents.** The MWS Vision Bench includes a task where the model answers questions about Russian business documents. Scores run from 0 to 1 ([source](https://github.com/mts-ai/MWS-Vision-Bench), leaderboard as updated July 2026). The test shows the model a page image, so it measures reading and answering together.

| Model | Kind | Public set | Private set |
| --- | --- | --- | --- |
| Gemini 3.6 Flash (Google) | Hosted | 0.967 | Not listed |
| Claude Fable 5 (Anthropic) | Hosted | 0.950 | Not listed |
| Qwen 3.7 Plus | Hosted | 0.935 | 0.938 |
| GPT-5.6 Sol (OpenAI) | Hosted | 0.926 | 0.930 |
| Qwen3.6-27B | Open, runs on one graphics card | 0.919 | 0.889 |
| Qwen3.6-35B-A3B | Open | 0.904 | 0.920 |
| Qwen3.5-9B | Open, small | 0.852 | 0.850 |
| Gemma 4 31B (Google) | Open | 0.829 | 0.792 |
| Cotype Pro 3 (MTS AI) | Commercial, on your servers | 0.791 | 0.776 |

**Russian models, text questions.** A November 2026 test of sixteen models on Russian-language documents by the Pospelov Centre reports YandexGPT Pro 5 correct on 89 of 96 tasks and GigaChat 3 Ultra on 86, against 91 for the best foreign model in that test ([source](https://pospelov.center/publications/model-tests-2026-11.html)). I have not examined its method. YandexGPT Pro is available only as a cloud service in Russia; GigaChat has open versions you can run yourself.

**What you can run, and where.**

| Model | Runs on | Notes |
| --- | --- | --- |
| Qwen3.6-27B, compressed | Your 36 GB MacBook; any 24 GB graphics card | The same model as Stage 2, so one model serves the whole pipeline |
| GigaChat 3.1 Lightning (Sber, MIT licence) | Laptop | 10 billion parameters with 1.8 billion active, so fast; I found no document-question score for it |
| T-pro 2.1 (T-Bank, Apache 2.0) | 24 GB card when compressed | 33 billion parameters, tuned for Russian on top of Qwen3-32B; no score found |
| GigaChat 3.5 Ultra, Qwen3-235B, DeepSeek V4 | A server with several data-centre GPUs | The "large model" option; only worth it if the test shows a clear gap |

Model details are from two Russian-language overviews ([Promolytica](https://www.promolytica.ru/knowledge/open-source-llm-sravnenie), [The Code](https://thecode.media/otkrytye-vesa-modeley/)).

**How to read this.** On the public set, the best hosted model is about five points ahead of Qwen3.6-27B. That gap is real but modest, and it is measured without the safeguards from the previous section, which close part of it. Size matters more here than in Stages 1 to 3 because the model must combine several passages and resist guessing. Start with the local model and measure the gap on your own questions before paying for more hardware.

**Speed on your MacBook.** By my estimate, reading a few passages and writing a short answer will take from half a minute to a couple of minutes with the compressed 27B model. That is acceptable for a pilot and too slow for many users at once. I have no measured figure for your machine.

## Tools

There are two kinds of tool: building-block libraries for a programmer, and ready-made applications that give you a chat screen over your documents in a day. All of those below are open-source and can run with no internet connection.

**Building-block libraries.**

| Library | GitHub stars (July 2026) | Licence | Best for |
| --- | --- | --- | --- |
| LangChain, with LangGraph | 143,000 | MIT | The broadest toolkit; multi-step and agent-style flows |
| LlamaIndex | 51,000 | MIT | Document-centred question answering; many loaders and index types |
| Haystack (deepset) | 26,000 | Apache 2.0 | Clear, explicit pipelines; favoured for production and regulated settings |

**Ready-made applications.**

| Application | GitHub stars | Licence | What you get |
| --- | --- | --- | --- |
| Dify | 151,000 | Apache 2.0 with modifications | A visual builder: connect a model, upload documents, draw the flow, get a chat screen |
| Open WebUI | Over 130,000 | Its own licence | A chat screen for local models with simple document upload |
| RAGFlow | 86,000 | Apache 2.0 | Strong document parsing and answers with citations out of the box |
| Onyx | Not found | Open-source | Built for staff-wide use, with permissions inherited from source systems |

Star counts and licences are from a July 2026 comparison ([Techsy](https://techsy.io/en/blog/best-rag-framework-2026)) and a self-hosting guide written by Onyx's own team ([source](https://onyx.app/insights/self-hosted-rag)). Stars show popularity, not fit.

**Tools for measuring answer quality.** Ragas is the most widely used open tool; DeepEval is the main alternative. Both score whether an answer is supported by its sources and whether it addresses the question, using a second model as the judge ([source](https://atlan.com/know/how-to-evaluate-rag-systems-explained/)).

**Which to use.**

- **For a first demo:** a ready-made application such as RAGFlow or Dify, connected to your local Qwen, shows people a working chat over agreements within days.
- **For the real system:** the parts that make your case work, namely the table-first route, clause-level cutting, the amendment chain and the quote check, are not in any ready-made product. They need custom code, with or without a library underneath.
- **A library is optional.** The whole Stage 4 chain is a few hundred lines of ordinary code. Libraries save time on connectors and add weight elsewhere, so let your programmer choose.

## Where answering fails

A wrong answer reads as fluently as a right one, so each failure below needs a specific guard; most of them start in an earlier stage and only become visible here.

| Failure | What happens | Guard |
| --- | --- | --- |
| Wrong evidence in, confident answer out | Search returned a clause from the wrong agreement and the model answered from it | Filters first; show the agreement number in every source; measure search separately |
| Answer goes beyond the evidence | The model adds a plausible detail that no passage contains | Source per statement; quote check |
| Counting from text | "How many agreements have advance payment?" is answered from the five passages retrieved | Route counting and totals to the table |
| Old terms as current | The original clause is quoted although an amendment replaced it | Exclude superseded clauses by default |
| Terms mixed between agreements | Near-identical clauses from two agreements are merged into one answer | Group evidence by agreement; ask back when more than one matches |
| Wrong premise accepted | The question assumes something false and the model goes along | Premise check; "no such agreement found" |
| No answer exists, model answers anyway | The documents do not cover the question | Permission to decline, tested with unanswerable questions |
| Refuses too often | The answer is there but the model says "not found" | Check search first; loosen instructions only with test evidence |
| Evidence drowned out | Twenty passages are supplied and the right one is ignored | Send fewer, better passages: five to eight after reranking |
| Legal judgement requested | "Is this clause enforceable?" gets a confident opinion | Scope statement; answer what the document says and decline the judgement |
| Language drift | A question in Kazakh gets an answer in Russian, or quotes are translated | Answer in the question's language; quotes always in the original |
| Someone sees what they should not | An answer draws on an agreement outside the user's access | Permissions enforced in the search |

The figure of five to eight passages follows common practitioner advice ([source](https://www.callmissed.com/blog/rag-best-practices-2026)). The first, sixth and seventh rows are supported by the studies in the trust section. The rest are my expectations for an agreement archive, so confirm them in testing.

## Your case: Russian-language agreements for Kazakhstan's railways

One local model can serve the whole pipeline for a pilot; the design work is in the routing, the answer format and the rules about what the system will not do.

**Three routes, with examples.**

| Route | Example question | How it is answered |
| --- | --- | --- |
| Table | "Which supply agreements with ТОО «Альфа» end in 2026?" | Filters on party, type and end date; the list comes straight from the Stage 2 table |
| Text | "What is the penalty for late delivery in agreement КТЖ-2025/147?" | Filter to that agreement, search its clauses, quote clause 5.2 and its neighbours |
| Table then text | "In which 2025 agreements is advance payment above 30%, and what conditions apply?" | The table finds the agreements; text search pulls the payment clauses from each |

Names and numbers in the examples are invented.

**A suggested answer format.**

1. A direct answer in one to three sentences, in the language of the question.
2. The supporting quotes in the original language, each with agreement number, clause number and a link to the scanned page.
3. A note if an amendment changed the term, with both versions.
4. If nothing was found: a plain statement saying so, and what was searched.

**Setup for the pilot.**

| Part | Choice |
| --- | --- |
| Model | Qwen3.6-27B compressed, the same one used in Stage 2 |
| Route choice | Simple rules first (an agreement number or a date range in the question points to the table); let the model choose only where rules cannot |
| Table queries | A fixed set of filters that the model fills in, not free-form queries |
| Passages per answer | Five to eight, each with its neighbours from the same section |
| Checks | Quote check and numbers from the table from day one; second reader later |
| Log | Question, route, passages used, answer, and who asked |

**Rules to decide before building.**

- **Scope.** The system reports what agreements say. It does not give legal opinions, and it says so when asked for one.
- **Access.** Decide who may see which agreements, and store that with each document so the search can enforce it. For a pilot with one user this can wait, but the design should leave room for it.
- **Amendments.** Current terms by default; history on request.
- **Kazakh.** If staff will ask in Kazakh or agreements contain Kazakh text, include such questions in the test from the start. I have no evidence on how well the local models answer in Kazakh.

**On using a larger model.** Your colleague's advice to use a large model fits this stage better than the others. A practical way to settle it: take a handful of agreements that are safe to send outside, such as public templates or anonymised copies, run the same questions through a large hosted model and through local Qwen, and compare. If the answers are close, the local setup is enough.

## How to choose and test

Reuse the question set from Stage 3, add the expected answer to each question, and include questions that have no answer.

**The test set.**

- The 50 to 100 real questions from the Stage 3 test, each with the correct answer written by a person.
- Ten to fifteen questions whose answer is not in the documents, to test declining.
- Five to ten questions with a false assumption built in, such as an agreement that does not exist.
- A mix across the three routes.

**Four things to score for each answer.**

| Measure | Question it answers |
| --- | --- |
| Correct | Does the answer match the expected one? |
| Supported | Is every statement backed by the passage it cites? |
| Right source | Does the cited clause belong to the right agreement and say what is claimed? |
| Declined properly | For unanswerable questions, did the system say so, and did it avoid declining answerable ones? |

**Who scores.** Start with a person reading every answer; with 100 questions this is a few hours. Automated scoring by a second model (the approach used by tools such as Ragas) helps once the set grows, but such judges have known biases, so check a sample by hand each time ([source](https://dev.to/dublecc/rag-evaluation-metrics-guide-2026-faithfulness-context-precision-and-how-to-score-a-pipeline-46gi)).

**Find the stage at fault.** For every wrong answer, ask in order: was the page read correctly (Stage 1), were the fields right (Stage 2), was the right passage found (Stage 3), and only then, did the model misuse good evidence (Stage 4)? Most errors turn out to be upstream, and fixing them there helps every later question.

**What to compare.**

1. Text route only, against the three routes together.
2. With and without the quote check and the table-supplied numbers.
3. Five passages against ten.
4. Local Qwen against a large hosted model, on documents that may leave your network.
5. Qwen against a Russian model such as GigaChat 3.1 Lightning, for quality and speed.

## Sources

- [Stanford RegLab: Hallucination-Free? Assessing the reliability of leading AI legal research tools](https://reglab.stanford.edu/?p=3154) and a [2026 summary of the research](https://www.llrx.com/2026/02/what-the-science-says-about-hallucinations-in-legal-research/)
- [Benchmarking retrieval strategies for biomedical RAG](https://arxiv.org/pdf/2605.02520) (2026): effect of grounding instructions
- [Citation-enforced prompting in medical RAG](https://www.mdpi.com/2076-3417/16/6/3013) (Mar 2026)
- [Prompt-based abstention fails under misleading context](https://arxiv.org/pdf/2608.22228) (2026): models repeating planted errors; declining
- [AI hallucination rate 2026: benchmark statistics](https://www.elitecontentmarketer.com/ai-hallucination-statistics/): spread between models
- [Retrieval evidence quality prediction](https://www.researchgate.net/publication/408508115_Retrieval_Evidence_Quality_Prediction_for_RAG_Hallucination_Detection_with_LLM-Derived_Semantic_Features) (Jun 2026): exact numbers with text versus structured data
- Database queries by AI: [Count](https://count.co/ai/text-to-sql) (Oct 2026), [Onvo](https://www.onvo.ai/blog/text-to-sql-accuracy-in-2026-the-performance-cliff-nobody-mentions)
- [Envisioning: Agentic retrieval](https://www.envisioning.com/vocab/agentic-retrieval): cost and speed of multi-step search
- [MWS Vision Bench](https://github.com/mts-ai/MWS-Vision-Bench) (MTS AI, Jul 2026): question answering on Russian documents
- [Pospelov Centre: tests of sixteen models on Russian-language documents](https://pospelov.center/publications/model-tests-2026-11.html) (Nov 2026)
- Russian open models: [Promolytica](https://www.promolytica.ru/knowledge/open-source-llm-sravnenie) (Oct 2026), [The Code](https://thecode.media/otkrytye-vesa-modeley/)
- Tools: [Techsy framework comparison](https://techsy.io/en/blog/best-rag-framework-2026) (Jul 2026), [Onyx self-hosting guide](https://onyx.app/insights/self-hosted-rag), [Atlan on evaluation tools](https://atlan.com/know/how-to-evaluate-rag-systems-explained/), [evaluation metrics guide](https://dev.to/dublecc/rag-evaluation-metrics-guide-2026-faithfulness-context-precision-and-how-to-score-a-pipeline-46gi)
- Security: [Wavect on permissions](https://wavect.io/blog/rag-permissions-sharepoint-confluence-drive/), [Tian Pan on permission-aware retrieval](https://tianpan.co/blog/2026-05-04-permission-aware-retrieval-enterprise-rag-access-control), [Okta on securing RAG](https://www.okta.com/identity-101/how-to-secure-rag-workflows/)
- [RAG best practices 2026](https://www.callmissed.com/blog/rag-best-practices-2026): number of passages

I worked from search summaries of these pages, not full readings, except the MWS Vision Bench page, which I read in full earlier. The routes, answer format, pilot setup, and most rows of the failure table are my recommendations, not findings from a source.
