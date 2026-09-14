# SupportPilot AI — Product Specification

## Purpose

SupportPilot AI is a deployable personal portfolio project designed to demonstrate professional capabilities in Generative AI, Retrieval-Augmented Generation (RAG), bounded AI agents, full-stack development, APIs, authentication, databases, automation, security basics, testing, and deployment.

V1 should be credible enough to demonstrate to prospective Upwork clients without making fake claims about customers, revenue, or production usage.

## V1 business/admin capabilities

A business/admin should eventually be able to:

- register and authenticate;
- create and use a business workspace;
- upload support knowledge in PDF, DOCX, TXT, Markdown, and manually entered FAQs;
- see document processing and indexing status;
- remove documents and eventually reprocess them;
- maintain an isolated business knowledge base;
- view customer conversations;
- view source information used by AI answers;
- view customer feedback;
- view and manage escalations;
- see useful basic support analytics.

## V1 customer capabilities

Customers should eventually be able to:

- open a hosted support-chat interface;
- ask questions;
- receive streamed AI-generated responses;
- receive answers grounded in that business's knowledge base;
- see relevant citations and sources;
- continue multi-turn conversations;
- provide feedback;
- request a human;
- receive appropriate handling when evidence is insufficient.

## Embeddable support widget

V1 should eventually include an embeddable website support widget so a business can expose the SupportPilot experience from its own website.

## AI behavior

Normal customer question-answering uses RAG rather than an autonomous agent. Answers should be grounded in workspace-scoped evidence, provide sources, and handle insufficient evidence safely instead of inventing an answer.

The primary agentic capability is a bounded Support Triage Agent for unresolved or human-requested conversations. It may classify the issue, determine priority, summarize the conversation, and create an escalation through explicitly permitted tools.

## Multi-tenancy

Business-owned data must be isolated by workspace. Tenant isolation is a security requirement, not merely a UI concern.

## Explicit V1 exclusions

The following are intentionally excluded from V1:

- payments or subscriptions;
- native mobile apps;
- WhatsApp;
- voice support;
- Salesforce;
- complex CRM integrations;
- live human-agent chat infrastructure;
- fine-tuning;
- Kubernetes;
- microservices;
- multi-agent swarms;
- complex enterprise RBAC;
- unnecessary enterprise infrastructure.

## Product constraints

- Initial development and public portfolio demo target ₹0 / $0 infrastructure and AI cost.
- The system should remain provider-agnostic where practical, especially for LLM and embedding providers.
- Only synthetic, demo, or otherwise non-confidential support knowledge should be used while relying on free AI tiers whose terms permit submitted content to be used for product improvement.
- Implementation should proceed incrementally according to `ROADMAP.md`.
