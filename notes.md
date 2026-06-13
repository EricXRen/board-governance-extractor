
 I am getting this warning:" Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to
   enable higher rate limits and faster downloads". Where do I use HF hub

● It comes from sentence-transformers in evaluation/metrics.py:semantic_similarity() — when the evaluator first runs a
  semantic_similarity comparison, it downloads the all-MiniLM-L6-v2 model from Hugging Face Hub to a local cache.

  The warning is harmless. The model is only downloaded once and cached locally (usually at ~/.cache/huggingface/). It
  will not re-download on subsequent runs.

  If you want to silence it, set a free HF token:

  # Get a free token at huggingface.co/settings/tokens (read-only is enough)
  export HF_TOKEN=hf_...

  Or add it to your .env file:
  HF_TOKEN=hf_...

  Alternatively, if you want to skip semantic similarity entirely (e.g. for faster evaluation without the eval extra),
  you can change biographical.career_summary in config.yaml to use fuzzy_match instead:

  evaluation:
    field_metrics:
      "biographical.career_summary": fuzzy_match   # was: semantic_similarity

      