# Research: Search-Grounded LLMs for L2a Ingredient Data Collection

**Date**: 2026-03-26
**Researcher**: researcher agent
**Purpose**: Evaluate Google Gemini, Grok, and Perplexity for ingredient data enrichment

---

## 1. Google Gemini with Search Grounding (PRIMARY RECOMMENDATION)

Built-in `google_search_retrieval` tool. Auto-searches Google, synthesizes grounded response with source citations. Supports structured JSON output with grounding in Gemini 2.5+.

### Pricing
| Component | Price |
|-----------|-------|
| Gemini 2.5 Flash input | $0.15/M tokens |
| Gemini 2.5 Flash output | $0.60/M tokens |
| **Grounding search** | **$0.035 per query** |
| Free tier | **500 requests/day** |

Cost for 5,000 ingredients: **$175** or free over 10 days.

### Assessment
- Best search quality (Google's index), excellent Chinese support
- We already have GEMINI_API_KEY
- **Gotcha**: Grounding metadata (URLs) in separate field, not inside JSON

---

## 2. Grok (xAI) — NOT RECOMMENDED
- Search primarily hits X/Twitter, not broad web
- Chinese food content minimal, pricing higher, docs immature

## 3. Perplexity Sonar — STRONG SECONDARY
- Every query auto-grounded, **$0.005/query** (7x cheaper), OpenAI-compatible API
- Good for cross-reference, always returns citations

## 4. YouTube Pipeline — DEFERRED
- Better for L1 (techniques/equipment) than L2a (ingredients)
- Requires: YouTube Data API → transcript extraction → LLM processing

---

## Recommendation
1. **Primary**: Gemini 2.5 Flash + Search Grounding
2. **Secondary**: Perplexity Sonar for cross-reference
3. **YouTube**: Defer to L1 phase
