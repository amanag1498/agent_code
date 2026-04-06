# Phase 2 Increment Plan

This increment focuses on the first Phase 2 slice while keeping the existing
application runnable and compatible:

1. `ai_repo_agent/core/models.py`
   - Add additive embedding/vector and semantic compare models.
   - Extend compare payloads with semantic summaries without breaking current consumers.

2. `ai_repo_agent/db/database.py`
   - Add additive SQLite table for embedding vectors.
   - Keep existing `embedding_chunks` table and APIs intact.

3. `ai_repo_agent/db/repositories.py`
   - Extend `EmbeddingStore` to persist and load vector payloads.
   - Preserve current chunk storage methods.

4. `ai_repo_agent/analysis/embeddings.py`
   - Add a local deterministic embedding model and vector similarity helpers.
   - No cloud dependency required.

5. `ai_repo_agent/analysis/lsp_semantic.py`
   - Deepen best-effort semantic enrichment with optional definitions, references,
     call hierarchy, and hover/type-style metadata.
   - Remain fail-open when no language server is available.

6. `ai_repo_agent/analysis/treesitter_analyzer.py`
   - Normalize more language-specific symbol/import coverage and richer metadata.

7. `ai_repo_agent/analysis/diff.py`
   - Add semantic symbol change summaries and compare metadata while preserving
     current delta behavior.

8. `ai_repo_agent/services/scan_orchestrator.py`
   - Build and persist embedding vectors after chunk persistence.
   - Preserve existing snapshot/findings flow.

9. `ai_repo_agent/llm/evidence.py`
   - Introduce retrieval-aware evidence ranking that combines vectors and
     heuristics for chat and patch context.

10. `ai_repo_agent/services/chat_orchestrator.py`
    - Use the upgraded retrieval path.

11. `ai_repo_agent/services/patch_orchestrator.py`
    - Use the upgraded retrieval path and richer semantic context.

12. `ai_repo_agent/tests/test_analyzer_pipeline.py`
    - Extend tests for:
      - multi-language extraction
      - optional LSP fallback/enrichment behavior
      - embedding persistence and retrieval compatibility
      - semantic compare summary compatibility

Compatibility notes:
- Existing scan APIs, compare APIs, patch APIs, repo chat, SQLite snapshot model,
  and UI contracts remain valid.
- Additive fields are preferred over replacing existing payload shapes.
- When vectors or semantic data are unavailable, the app falls back to the
  current heuristic behavior.
