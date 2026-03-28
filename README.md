# Automated Ticket Routing and Priority Management System

## Objective
A Python and SQLite backend that automates ticket categorization,
priority assignment, storage, lifecycle management, audit logging,
and operational reporting — using pure Python standard library only.

## Architecture: 3-Layer Design
- **Routing Engine:** Deterministic keyword-based routing converts
  unstructured text into structured category and department fields.
- **Data Layer:** Full CRUD with ACID-compliant transactions —
  every write wrapped in try/except with rollback on failure.
- **Analytics Layer:** Dynamic SQL filtering, keyword search, and
  3-part operational reporting using JOIN and GROUP BY aggregation.

## Features
- **Rule-Based Routing:** Prioritized if/elif rules assign category,
  priority (Critical/High/Medium/Low), and department automatically.
- **3-Table Normalized Schema:** departments → tickets → ticket_logs.
  Two Foreign Key constraints enforce referential integrity.
- **State Machine Workflow:** VALID_TRANSITIONS enforces lifecycle
  rules. Resolved is a terminal state — no way back.
- **Atomic Audit Trail:** Every status change writes to ticket_logs
  in the same transaction as the ticket UPDATE — fully atomic.
- **B-tree Performance Indices:** O(log n) lookups on status and
  priority vs O(n) full table scans without indices.
- **SQL Injection Prevention:** All inputs use parameterized ? queries.
- **Dynamic Filtering:** WHERE 1=1 pattern builds optional filters
  at runtime without string concatenation.

## Technologies
- Python 3.x (Type Hints, modular design)
- SQLite3 (Foreign Keys, Parameterized Queries, B-tree Indices)

## Project Structure
Ticket_Routing_System/
├── main.py              # Production backend script
├── smart_helpdesk.db    # SQLite database (auto-generated)
├── requirements.txt     # Dependency manifest
├── sample_output.txt    # Expected console output
└── README.md            # This file
