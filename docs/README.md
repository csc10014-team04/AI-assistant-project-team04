# docs

Project documents. Code is in [`../sourceCode`](../sourceCode/README.md).

| File | What it is |
|---|---|
| [`duties.pdf`](duties.pdf) | The list of duties per phase (Phase 1: 9, Phase 2: 13) with who does them and how. The test suite and the feature table in the root README follow it. |
| [`Problem_analysis.pdf`](Problem_analysis.pdf) | The problem, the users, the success criteria and the edge cases the system must handle. |
| [`architecture.md`](architecture.md) | Architecture and pipeline description. |
| [`UI_design_and_BE_integration.md`](UI_design_and_BE_integration.md) | Frontend (Kivy/KivyMD) UI design specification and Backend API integration contract. |
| [`Database_and_AI_Host_Code_Guide.docx`](Database_and_AI_Host_Code_Guide.docx) | Beginner guide to the database and AI-host code, line by line (written before the proposals API, tasks, OAuth and the knowledge base were added). |
| [`Tester_Code_Guide.docx`](Tester_Code_Guide.docx) | Beginner guide for the tester: how to run the tests and what each one checks (also written before those additions). |
| [`Subagent_Test_Generation_Prompt.md`](Subagent_Test_Generation_Prompt.md) | A ready-to-paste prompt for a QA subagent: writes 300+ adversarial tests across every module and reports conflicts and wrong parts. |

Other documentation:
- root [`README.md`](../README.md): what the system is, how to deploy it, how to use it;
- [`../AGENTS.md`](../AGENTS.md): architectural rules every contributor (and AI assistant) must follow;
- [`../tests/README.md`](../tests/README.md): every test and the known gaps;
- [`../scripts/check_readmes.py`](../scripts/check_readmes.py): run it to find empty READMEs, broken links and out-of-date team lists.
