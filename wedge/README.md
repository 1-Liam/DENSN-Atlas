# Formal Systems Wedge

This is the shipping wedge for the repo:

`verifier-backed abstraction invention for formal systems`

The claim is narrow on purpose. In this repository, "formal systems" primarily means protocol, lease/lock, distributed coordination, and related concurrency-oriented problems with objective verifier surfaces.

Given those formal artifacts, the system can:

- accumulate contradiction in a persistent ontology
- invent or remap a reusable abstraction
- verify it externally
- transfer it where it should
- block it where it should not

This wedge does not claim broad theorem proving, arbitrary proof search, or general symbolic reasoning over open-ended mathematics.

Primary raw evidence:

- [artifacts/phase11/final_proof_bundle.json](../artifacts/phase11/final_proof_bundle.json)
- [artifacts/phase12/credit_window_summary.json](../artifacts/phase12/credit_window_summary.json)
- [artifacts/phase12/decisive_demo_summary.json](../artifacts/phase12/decisive_demo_summary.json)
- [artifacts/phase12/wedge_eval_summary.json](../artifacts/phase12/wedge_eval_summary.json)

Run:

```powershell
python scripts/run_decisive_demo.py
python scripts/export_demo_figure_data.py
python scripts/run_wedge_eval.py
```

Live proposal-path scripts require your own `GROQ_API_KEY`. Copy `.env.example` to `.env` or set the variable directly in your shell before running them.
